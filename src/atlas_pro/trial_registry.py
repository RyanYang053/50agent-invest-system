"""Local preregistered research campaigns and one-shot holdout consumption.
This is an operator-controlled journal, not proof of independent experiment timing,
source identity or completeness. It never promotes strategies or calls models/brokers.
"""
from __future__ import annotations
import json, sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from .ledger import canonical, digest, iso
from .experiments import ENGINES, review_experiment
from .independent_review import ishash
from .research import num


def _now():return datetime.now(timezone.utc).isoformat()


class TrialRegistry:
    def __init__(self,path,*,clock=_now):
        self.path=str(path);self.clock=clock
        with self._db() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS campaigns(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS holdout_samples(sample_id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL REFERENCES campaigns(id));
            CREATE TABLE IF NOT EXISTS trials(id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL REFERENCES campaigns(id),state TEXT NOT NULL,started TEXT,finished TEXT,result TEXT,result_hash TEXT);''')
    @contextmanager
    def _db(self):
        c=sqlite3.connect(self.path,timeout=15,isolation_level=None);c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA synchronous=FULL')
        try:
            yield c
            if c.in_transaction:c.commit()
        except Exception:
            if c.in_transaction:c.rollback()
            raise
        finally:c.close()
    def register(self,requests,locked_ids,*,operator_confirmed=False):
        if operator_confirmed is not True:raise PermissionError('operator campaign confirmation required')
        if not isinstance(locked_ids,list) or not 1<=len(locked_ids)<=50000 or any(not isinstance(x,str) or not x or len(x)>256 for x in locked_ids) or len(set(locked_ids))!=len(locked_ids):raise ValueError('invalid stable holdout sample IDs')
        if not isinstance(requests,list) or not 1<=len(requests)<=1000:raise ValueError('invalid planned trial count')
        now=iso(self.clock());seen=set();split=digest(locked_ids)
        # Every planned strategy must use one locked split, data version and policy.
        fields={'engine','artifact_sha256','data_sha256','split_sha256','policy_sha256','budget_usd','created_at','mode','broker_credentials','can_trade','experiment_id'}
        for r in requests:
            if not isinstance(r,dict) or set(r)!=fields or r['experiment_id']!=digest({k:v for k,v in r.items() if k!='experiment_id'}) or r['experiment_id'] in seen:raise ValueError('invalid or duplicate trial request')
            if r['engine'] not in ENGINES or r['mode']!='OFFLINE_ISOLATED_RESEARCH' or r['can_trade'] is not False or r['broker_credentials'] is not False or iso(r['created_at'])>now or not 0<=num(r['budget_usd'])<=100:raise ValueError('unsafe trial request')
            if r['split_sha256']!=split or not all(ishash(r[k]) for k in ('artifact_sha256','data_sha256','policy_sha256')):raise ValueError('trial provenance mismatch')
            seen.add(r['experiment_id'])
        for k in ('data_sha256','policy_sha256'):
            if len({r[k] for r in requests})!=1:raise ValueError('campaign data/policy mismatch')
        manifest={'registered_at':now.isoformat(),'locked_ids':locked_ids,'requests':requests,'can_trade':False}
        cid=digest(manifest)
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM campaigns WHERE id=?',(cid,)).fetchone():return cid
            # Stable sample IDs cannot be consumed by a later campaign, even with
            # reordered IDs or a partially overlapping split. Aliases remain an external concern.
            if any(c.execute('SELECT 1 FROM holdout_samples WHERE sample_id=?',(k,)).fetchone() for k in locked_ids):raise ValueError('holdout sample already preregistered')
            c.execute('INSERT INTO campaigns VALUES(?,?)',(cid,canonical(manifest)))
            c.executemany('INSERT INTO holdout_samples VALUES(?,?)',((k,cid) for k in locked_ids))
            c.executemany("INSERT INTO trials(id,campaign_id,state) VALUES(?,?,'PLANNED')",((r['experiment_id'],cid) for r in requests))
        return cid
    def _load(self,c,cid):
        row=c.execute('SELECT payload FROM campaigns WHERE id=?',(cid,)).fetchone()
        if row is None:raise KeyError('unknown campaign')
        m=json.loads(row[0]);
        if digest(m)!=cid:raise ValueError('campaign integrity failure')
        ids={r[0] for r in c.execute('SELECT sample_id FROM holdout_samples WHERE campaign_id=?',(cid,))}
        if ids!=set(m['locked_ids']):raise ValueError('holdout registry integrity failure')
        return m
    def start(self,cid,tid):
        now=iso(self.clock())
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE');m=self._load(c,cid)
            if now<iso(m['registered_at']):raise ValueError('clock precedes campaign')
            row=c.execute('SELECT state FROM trials WHERE id=? AND campaign_id=?',(tid,cid)).fetchone()
            if row is None:raise KeyError('unregistered trial')
            if row['state']!='PLANNED':raise ValueError('trial already attempted; no retry on same holdout')
            c.execute("UPDATE trials SET state='RUNNING',started=? WHERE id=?",(now.isoformat(),tid))
        return {'status':'RUNNING','campaign_id':cid,'trial_id':tid,'can_trade':False}
    def finish(self,cid,tid,*,report=None,failure=None):
        if (report is None)==(failure is None):raise ValueError('exactly one result or failure required')
        now=iso(self.clock())
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE');m=self._load(c,cid)
            row=c.execute('SELECT * FROM trials WHERE id=? AND campaign_id=?',(tid,cid)).fetchone()
            if row is None or row['state']!='RUNNING' or now<iso(row['started']):raise ValueError('trial not in a valid running state')
            if failure is not None:
                if failure not in ('TIMEOUT','CRASH','INVALID_REPORT','BUDGET','OPERATOR_ABORT'):raise ValueError('invalid failure code')
                result={'status':'FAILED','failure':failure,'can_trade':False,'promotion_allowed':False};state='FAILED'
            else:
                req=next(r for r in m['requests'] if r['experiment_id']==tid)
                result=review_experiment(req,report,locked_test_ids=m['locked_ids']);state='COMPLETED'
            record={'trial_id':tid,'campaign_id':cid,'started':row['started'],'finished':now.isoformat(),'state':state,'result':result}
            c.execute('UPDATE trials SET state=?,finished=?,result=?,result_hash=? WHERE id=?',(state,now.isoformat(),canonical(record),digest(record),tid))
        return result
    def audit(self,cid):
        with self._db() as c:
            c.execute('BEGIN');m=self._load(c,cid);rows=c.execute('SELECT * FROM trials WHERE campaign_id=? ORDER BY id',(cid,)).fetchall()
            if {r['id'] for r in rows}!={r['experiment_id'] for r in m['requests']}:raise ValueError('trial registry integrity failure')
            counts=dict.fromkeys(('PLANNED','RUNNING','FAILED','COMPLETED'),0);records=[]
            for r in rows:
                state=r['state'];counts[state]+=1
                if state in ('FAILED','COMPLETED'):
                    record=json.loads(r['result']);
                    if digest(record)!=r['result_hash'] or any(record[k]!=v for k,v in {'trial_id':r['id'],'campaign_id':cid,'state':state,'started':r['started'],'finished':r['finished']}.items()):raise ValueError('trial result integrity failure')
                    records.append({'id':r['id'],'state':state,'result_hash':r['result_hash']})
                else:
                    if r['result'] is not None or r['result_hash'] is not None or r['finished'] is not None or ((state=='PLANNED')!=(r['started'] is None)):raise ValueError('trial state integrity failure')
                    records.append({'id':r['id'],'state':state,'result_hash':None})
        return {'campaign_id':cid,'planned_trials':len(rows),'counts':counts,'trial_registry_hash':digest(records),'all_attempts_accounted':counts['PLANNED']==counts['RUNNING']==0,'can_trade':False,'promotion_allowed':False,'limitations':['local operator journal, not externally timestamped','sample aliasing and completeness require independent review','failed attempts counted; no retry or promotion']}
