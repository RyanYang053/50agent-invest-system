"""Immutable-ish local evidence and event audit store.

Security model: SQLite file permissions, parameterized queries, hash-chain audit;
NOT a tamper-proof remote ledger. An administrator with filesystem write access
can edit the DB and repair hashes. Use external signed backups for stronger proof.
"""
from __future__ import annotations
import hashlib, json, sqlite3, threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None:
        raise ValueError('timezone-aware timestamp required')
    return dt.astimezone(timezone.utc)


def canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)


def digest(obj: object) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


class EvidenceLedger:
    def __init__(self, path: str | Path):
        self.path=str(path)
        self.lock=threading.RLock()
        with self._db() as c:
            c.executescript('''
              CREATE TABLE IF NOT EXISTS evidence (
                record_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
                document_id TEXT NOT NULL, security_id TEXT NOT NULL,
                observed_at TEXT NOT NULL, published_at TEXT NOT NULL,
                available_at TEXT NOT NULL, ingested_at TEXT NOT NULL,
                payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
                data_class TEXT NOT NULL, license_id TEXT NOT NULL,
                revision_of TEXT, retention_mode TEXT NOT NULL,
                FOREIGN KEY(revision_of) REFERENCES evidence(record_id)
              );
              CREATE INDEX IF NOT EXISTS idx_evidence_asof ON evidence(security_id, available_at);
              CREATE TABLE IF NOT EXISTS audits (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL, action TEXT NOT NULL,
                object_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
                prev_hash TEXT NOT NULL, chain_hash TEXT NOT NULL
              );
            ''')

    @contextmanager
    def _db(self):
        c=sqlite3.connect(self.path, timeout=10)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA foreign_keys=ON')
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def append_audit(self, c, action, obj, payload):
        last=c.execute('SELECT chain_hash FROM audits ORDER BY seq DESC LIMIT 1').fetchone()
        prev=last['chain_hash'] if last else 'GENESIS'
        row={'action':action,'object_id':obj,'payload_hash':digest(payload),'prev_hash':prev}
        chain=digest(row)
        c.execute('INSERT INTO audits(created_at,action,object_id,payload_hash,prev_hash,chain_hash) VALUES(?,?,?,?,?,?)',
                  (datetime.now(timezone.utc).isoformat(),action,obj,row['payload_hash'],prev,chain))

    def add_evidence(self, item: dict, *, policy: dict):
        required=('record_id','source_id','document_id','security_id','observed_at','published_at','available_at','payload','data_class','license_id')
        missing=[x for x in required if not item.get(x)]
        if missing: raise ValueError('MISSING_EVIDENCE_FIELDS:'+','.join(missing))
        for key in ('observed_at','published_at','available_at'):
            iso(item[key])
        if iso(item['available_at']) < iso(item['published_at']):
            raise ValueError('AVAILABILITY_BEFORE_PUBLICATION')
        if item['data_class'] not in ('public','licensed','private'):
            raise ValueError('INVALID_DATA_CLASS')
        if policy.get('license_id') != item['license_id']:
            raise PermissionError('UNKNOWN_LICENSE')
        if policy.get('permitted_for_personal_analysis') is not True:
            raise PermissionError('PROVIDER_PERSONAL_ANALYSIS_DENIED')
        if item['data_class']=='licensed' and not policy.get('allow_local_retention'):
            # Record only safe metadata; never build a restricted data archive.
            raise PermissionError('LICENSE_FORBIDS_RETENTION')
        if item['data_class']=='public' and policy.get('cloud_allowed') is not True:
            raise PermissionError('PUBLIC_SCOPE_REQUIRES_CLOUD_ENTITLEMENT')
        if item['data_class']=='private' and policy.get('cloud_allowed'):
            raise PermissionError('PRIVATE_CLOUD_POLICY_INVALID')
        revision=item.get('revision_of')
        obj={k:item[k] for k in required if k!='payload'}
        for field in ('observed_at','published_at','available_at'):
            obj[field]=iso(obj[field]).isoformat()
        obj['payload']=item['payload']; obj['revision_of']=revision
        fingerprint=digest(obj)
        with self.lock, self._db() as c:
            c.execute('BEGIN IMMEDIATE')
            prior=c.execute('SELECT payload_sha256 FROM evidence WHERE record_id=?',(item['record_id'],)).fetchone()
            if prior:
                if prior['payload_sha256']!=fingerprint: raise ValueError('IDEMPOTENCY_CONFLICT')
                return {'status':'DUPLICATE','sha256':fingerprint}
            if revision:
                original=c.execute('SELECT * FROM evidence WHERE record_id=?',(revision,)).fetchone()
                if not original: raise ValueError('REVISION_PARENT_NOT_FOUND')
                if original['security_id']!=item['security_id']: raise ValueError('REVISION_SECURITY_MISMATCH')
            c.execute('''INSERT INTO evidence(record_id,source_id,document_id,security_id,observed_at,published_at,available_at,ingested_at,payload_json,payload_sha256,data_class,license_id,revision_of,retention_mode)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (item['record_id'],item['source_id'],item['document_id'],item['security_id'],obj['observed_at'],obj['published_at'],obj['available_at'],datetime.now(timezone.utc).isoformat(),canonical(item['payload']),fingerprint,item['data_class'],item['license_id'],revision,'metadata_and_payload'))
            self.append_audit(c,'ingest_evidence',item['record_id'],obj)
        return {'status':'ADDED','sha256':fingerprint}

    def asof(self, security_id: str, decision_at: str, *, include_private: bool=False, max_rows: int=100):
        iso(decision_at)
        q='SELECT * FROM evidence WHERE security_id=? AND available_at<=?'
        params=[security_id,iso(decision_at).isoformat()]
        if not include_private: q+=' AND data_class = ?'; params.append('public')
        q+=' ORDER BY available_at DESC, record_id DESC LIMIT ?'; params.append(min(max(max_rows,1),500))
        with self._db() as c:
            rows=c.execute(q,params).fetchall()
        return [dict(row)|{'payload':json.loads(row['payload_json'])} for row in rows]

    def verify_chain(self) -> bool:
        prev='GENESIS'
        with self._db() as c:
            rows=c.execute('SELECT * FROM audits ORDER BY seq').fetchall()
        for r in rows:
            row={'action':r['action'],'object_id':r['object_id'],'payload_hash':r['payload_hash'],'prev_hash':prev}
            if r['prev_hash']!=prev or digest(row)!=r['chain_hash']: return False
            prev=r['chain_hash']
        return True

    def verify_evidence_integrity(self) -> bool:
        with self._db() as c:
            rows=c.execute('SELECT * FROM evidence').fetchall()
        for r in rows:
            obj={k:r[k] for k in ('record_id','source_id','document_id','security_id','observed_at','published_at','available_at','data_class','license_id')}
            obj['payload']=json.loads(r['payload_json']);obj['revision_of']=r['revision_of']
            if digest(obj)!=r['payload_sha256']:return False
        return self.verify_chain()
