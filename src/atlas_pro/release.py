"""Approval-only strategy promotion. Requires HMAC outside the model process.

Signing must occur in an out-of-band privileged owner interface. This module
cannot establish that the person holding a secret is the account owner.
"""
from __future__ import annotations
from contextlib import contextmanager
import hmac, hashlib, json, sqlite3
from datetime import datetime, timezone
from .ledger import canonical, iso, digest

class ReleaseRegistry:
    def __init__(self,path):
        self.path=str(path)
        with self._db() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS releases(
              release_id TEXT PRIMARY KEY, artifact_sha256 TEXT NOT NULL,
              approval_at TEXT NOT NULL, evaluation_id TEXT NOT NULL,
              shadow_id TEXT NOT NULL, owner_signature TEXT NOT NULL,
              status TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS kill_switch(id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL);
              INSERT OR IGNORE INTO kill_switch VALUES(1,1);''')

    @contextmanager
    def _db(self):
        c=sqlite3.connect(self.path)
        c.row_factory=sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def signature(secret:bytes,payload:dict):
        return hmac.new(secret,canonical(payload).encode(),hashlib.sha256).hexdigest()

    def promote(self,payload,signature,*,secret:bytes,at:str):
        required=('release_id','artifact_sha256','evaluation_id','shadow_id','quality_pass','risk_pass','license_pass','owner_approved')
        if any(k not in payload for k in required): raise ValueError('INCOMPLETE_RELEASE')
        if any(payload[k] is not True for k in ('quality_pass','risk_pass','license_pass','owner_approved')):
            raise PermissionError('RELEASE_GATES_NOT_MET')
        if not hmac.compare_digest(signature,self.signature(secret,payload)):
            raise PermissionError('OWNER_SIGNATURE_INVALID')
        now=iso(at).isoformat()
        with self._db() as c:
            cur=c.execute('SELECT enabled FROM kill_switch WHERE id=1').fetchone()
            if cur['enabled']!=1: raise PermissionError('KILL_SWITCH_OFF')
            existing=c.execute('SELECT artifact_sha256 FROM releases WHERE release_id=?',(payload['release_id'],)).fetchone()
            if existing:
                if existing['artifact_sha256']!=payload['artifact_sha256']:raise ValueError('RELEASE_ID_COLLISION')
                return 'ALREADY_RELEASED'
            c.execute('INSERT INTO releases VALUES(?,?,?,?,?,?,?)',(payload['release_id'],payload['artifact_sha256'],now,payload['evaluation_id'],payload['shadow_id'],signature,'PROMOTED'))
        return 'PROMOTED'

    def stop(self):
        with self._db() as c:c.execute('UPDATE kill_switch SET enabled=0 WHERE id=1')

    def enabled(self):
        with self._db() as c:
            return c.execute('SELECT enabled FROM kill_switch WHERE id=1').fetchone()['enabled']==1
