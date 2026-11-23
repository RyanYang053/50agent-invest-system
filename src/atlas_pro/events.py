"""Durable event admission; NYSE sessions/half days via exchange_calendars."""
from __future__ import annotations
from contextlib import contextmanager
import json, sqlite3, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from .ledger import iso, digest

class EventBus:
    def __init__(self, path, rules, *, calendar=None, roles=None):
        self.path=str(path)
        self.rules={r['event_type']:r for r in rules}
        self.calendar=calendar
        self.roles={r['agent_id']:r for r in roles} if roles else None
        with self._db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS events(
              dedupe_key TEXT PRIMARY KEY, event_type TEXT NOT NULL, priority TEXT NOT NULL,
              source_event_id TEXT NOT NULL, first_seen_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL, attempts INTEGER NOT NULL, last_result TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS queue(
              work_id TEXT PRIMARY KEY, dedupe_key TEXT NOT NULL,
              payload_json TEXT NOT NULL, status TEXT NOT NULL,
              created_at TEXT NOT NULL, FOREIGN KEY(dedupe_key) REFERENCES events(dedupe_key)
            );
            ''')

    @contextmanager
    def _db(self):
        c=sqlite3.connect(self.path,timeout=10,isolation_level=None)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA foreign_keys=ON')
        try:
            yield c
            if c.in_transaction: c.commit()
        except Exception:
            if c.in_transaction: c.rollback()
            raise
        finally:
            c.close()

    def market_status(self, at: str, exchange='XNYS') -> dict:
        from zoneinfo import ZoneInfo
        at_dt=iso(at)
        if self.calendar is None:
            import exchange_calendars as xc
            self.calendar=xc.get_calendar(exchange)
        cal=self.calendar
        d=at_dt.date().isoformat()
        if not cal.is_session(d): return {'session':'CLOSED','is_open':False,'early_close':False}
        start=cal.session_open(d).to_pydatetime().astimezone(timezone.utc)
        end=cal.session_close(d).to_pydatetime().astimezone(timezone.utc)
        return {'session':'REGULAR' if start<=at_dt<end else 'OUTSIDE_REGULAR',
                'is_open':start<=at_dt<end,'early_close':(end-start)<timedelta(hours=6,minutes=30),
                'open_utc':start.isoformat(),'close_utc':end.isoformat()}

    def submit(self, event:dict, *, verified:bool, at:str):
        now=iso(at)
        kind=event.get('event_type')
        if kind not in self.rules: return {'status':'UNKNOWN_EVENT','can_trade':False}
        rule=self.rules[kind]
        source=event.get('source_event_id') or ''
        if rule['requires_verified_event'] and (not verified or not source):
            return {'status':'UNVERIFIED','can_trade':False}
        if 'published_at' in event and iso(event['published_at'])>now:
            return {'status':'FUTURE_EVENT','can_trade':False}
        # A source_id ensures two different SEC filings aren't conflated.
        # A missing source ID is permitted only for deterministic P0 signals.
        if not source and rule['priority']!='P0':
            return {'status':'MISSING_SOURCE_ID','can_trade':False}
        dedupe=digest({'type':kind,'security':event.get('security_id','ALL'),'source_event':source or event.get('signal_id','UNATTRIBUTED')})
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                old=c.execute('SELECT * FROM events WHERE dedupe_key=?',(dedupe,)).fetchone()
                if old:
                    age=(now-iso(old['last_seen_at'])).total_seconds()
                    if rule['priority']!='P0':
                        c.execute('COMMIT')
                        return {'status':'DUPLICATE','dedupe_key':dedupe,'can_trade':False}
                    # P0 accepted even for repeats, but only one queued job per fixed time window.
                    if age<5:
                        c.execute('UPDATE events SET attempts=attempts+1,last_seen_at=? WHERE dedupe_key=?',(now.isoformat(),dedupe))
                        c.execute('COMMIT')
                        return {'status':'P0_ALREADY_ACTIVE','can_trade':False}
                if not old:
                    c.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?)',(dedupe,kind,rule['priority'],source,now.isoformat(),now.isoformat(),1,'QUEUED'))
                else:
                    c.execute('UPDATE events SET last_seen_at=?,attempts=attempts+1,last_result=? WHERE dedupe_key=?',(now.isoformat(),'QUEUED',dedupe))
                work_id=digest({'event':dedupe,'window':int(now.timestamp()/5) if rule['priority']=='P0' else 0})
                routed=rule['primary_agents']
                if rule['priority']=='P0':
                    if self.roles is None: raise ValueError('P0_ROLE_MANIFEST_REQUIRED')
                    routed=[a for a in routed if a in self.roles and self.roles[a]['primary_model']=='deterministic']
                    if not routed: raise ValueError('P0_WITHOUT_DETERMINISTIC_GUARD')
                c.execute('INSERT OR IGNORE INTO queue VALUES(?,?,?,?,?)',(work_id,dedupe,json.dumps({'event':event,'agents':routed,'priority':rule['priority']}),'QUEUED',now.isoformat()))
                c.execute('COMMIT')
                return {'status':'QUEUED','work_id':work_id,'priority':rule['priority'],'agents':routed,'can_trade':False}
            except Exception:
                c.execute('ROLLBACK')
                raise

    def fetch_pending(self, limit=20):
        with self._db() as c:
            return [dict(r) for r in c.execute("SELECT * FROM queue WHERE status='QUEUED' ORDER BY CASE json_extract(payload_json,'$.priority') WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END, created_at LIMIT ?",(limit,))]
