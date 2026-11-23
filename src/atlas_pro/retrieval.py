"""Local citation-first research retrieval with PIT, ACL, and license enforcement.

FTS5 is the baseline. Optional embedding callback upgrades to vector+lexical fusion;
no semantic model is silently implied, and no network embedding is used.
"""
from __future__ import annotations
from contextlib import contextmanager
import json, math, re, sqlite3, hashlib
from datetime import datetime, timezone
from pathlib import Path
from .ledger import iso

class ResearchIndex:
    def __init__(self, path: str|Path):
        self.path=str(path)
        with self._db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS docs(
              doc_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_uri TEXT NOT NULL,
              security_id TEXT NOT NULL, available_at TEXT NOT NULL,
              scope TEXT NOT NULL, license_id TEXT NOT NULL, text_sha256 TEXT NOT NULL,
              indexed_at TEXT NOT NULL, embedding_json TEXT,
              content TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(content, content='docs', content_rowid='rowid', tokenize='unicode61');
            CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON docs BEGIN
              INSERT INTO docs_fts(rowid,content) VALUES(new.rowid,new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON docs BEGIN
              INSERT INTO docs_fts(docs_fts,rowid,content) VALUES('delete',old.rowid,old.content);
            END;
            CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON docs BEGIN
              INSERT INTO docs_fts(docs_fts,rowid,content) VALUES('delete',old.rowid,old.content);
              INSERT INTO docs_fts(rowid,content) VALUES(new.rowid,new.content);
            END;
            ''')

    @contextmanager
    def _db(self):
        c=sqlite3.connect(self.path, timeout=10)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def add(self, document:dict, license_policy:dict, embed=None):
        required=['doc_id','source_id','source_uri','security_id','available_at','scope','license_id','content']
        if any(not document.get(k) for k in required): raise ValueError('MISSING_REQUIRED_DOC_METADATA')
        if document['scope'] not in ('public','licensed','private'): raise ValueError('INVALID_SCOPE')
        dt=iso(document['available_at'])
        if document['license_id']!=license_policy.get('license_id') or not license_policy.get('permitted_for_personal_analysis'):
            raise PermissionError('LICENSE_RESTRICTED')
        if not license_policy.get('allow_local_retention') or not license_policy.get('allow_rag_indexing'):
            raise PermissionError('LICENSE_FORBIDS_INDEXING')
        if document['scope']=='private' and license_policy.get('cloud_allowed'):
            raise PermissionError('PRIVATE_CLOUD_SCOPE_INVALID')
        body=document['content']
        if len(body)>250_000: raise ValueError('DOC_TOO_LARGE_SPLIT_INTO_CHUNKS')
        if embed and document['scope'] != 'public' and not getattr(embed,'local_only',False):
            raise PermissionError('PRIVATE_EMBEDDING_MUST_BE_LOCAL')
        vector=embed(body) if embed else None
        if vector is not None:
            if not isinstance(vector,(tuple,list)) or not vector or any(not isinstance(x,(float,int)) or not math.isfinite(x) for x in vector):
                raise ValueError('INVALID_EMBEDDING')
        hashval=hashlib.sha256(body.encode()).hexdigest()
        with self._db() as c:
            old=c.execute('SELECT text_sha256 FROM docs WHERE doc_id=?',(document['doc_id'],)).fetchone()
            if old:
                if old['text_sha256']!=hashval: raise ValueError('DOC_IMMUTABILITY_CONFLICT')
                return 'DUPLICATE'
            c.execute('''INSERT INTO docs(doc_id,source_id,source_uri,security_id,available_at,scope,license_id,text_sha256,indexed_at,embedding_json,content)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
              (document['doc_id'],document['source_id'],document['source_uri'],document['security_id'],dt.isoformat(),document['scope'],document['license_id'],hashval,datetime.now(timezone.utc).isoformat(),json.dumps(vector) if vector is not None else None,body))
        return 'ADDED'

    @staticmethod
    def _cos(a,b):
        if len(a)!=len(b): return 0
        norm_a=math.sqrt(sum(x*x for x in a)); norm_b=math.sqrt(sum(x*x for x in b))
        return sum(x*y for x,y in zip(a,b))/(norm_a*norm_b) if norm_a and norm_b else 0.0

    def search(self, query:str, *, decision_at:str, scope:str='public_only', security_id:str='', top_k:int=5, embed=None):
        decision_at=iso(decision_at).isoformat()
        if scope not in ('public_only','private_local'):
            raise ValueError('INVALID_RETRIEVAL_SCOPE')
        if embed and scope=='private_local' and not getattr(embed,'local_only',False):
            raise PermissionError('PRIVATE_QUERY_EMBEDDING_MUST_BE_LOCAL')
        if not 1<=top_k<=25: raise ValueError('TOP_K_OUT_OF_RANGE')
        terms=re.findall(r'[\w]+',query,flags=re.UNICODE)
        # Avoid raw FTS query syntax and unsafe operators; use terms only.
        terms=[t for t in terms if len(t)>=2][:10]
        if not terms: return []
        clauses=['d.available_at<=?']; params=[decision_at]
        if scope=='public_only': clauses.append("d.scope='public'")
        if security_id: clauses.append('d.security_id=?'); params.append(security_id)
        where=' AND '.join(clauses)
        fts_query=' OR '.join('"'+term.replace('"','')+'"' for term in terms)
        with self._db() as c:
            rows=c.execute(f'''SELECT d.*,bm25(docs_fts) AS bm FROM docs_fts
              JOIN docs d ON d.rowid=docs_fts.rowid
              WHERE docs_fts MATCH ? AND {where} ORDER BY bm LIMIT 60''',[fts_query]+params).fetchall()
            lexical={r['doc_id']:(1.0/(60+i),dict(r)) for i,r in enumerate(rows)}
            if embed:
                allrows=c.execute(f'SELECT * FROM docs d WHERE {where} AND embedding_json IS NOT NULL LIMIT 5000',params).fetchall()
                vec=embed(query)
                sims=[]
                for r in allrows:
                    sim=self._cos(vec,json.loads(r['embedding_json']))
                    if sim>0: sims.append((sim,dict(r)))
                sims.sort(reverse=True,key=lambda x:x[0])
                for i,(_,r) in enumerate(sims[:60]):
                    prior=lexical.get(r['doc_id'],(0,r))
                    lexical[r['doc_id']]=(prior[0]+1.0/(60+i),r)
        results=sorted(lexical.values(),key=lambda x:x[0],reverse=True)[:top_k]
        # Return source refs, NOT operator instructions. Cloud cannot query private.
        return [{'doc_id':r['doc_id'],'source_id':r['source_id'],'source_uri':r['source_uri'],
                 'available_at':r['available_at'],'evidence_sha256':r['text_sha256'],
                 'scope':r['scope'],'text':r['content'][:1600],
                 'retrieval_score':round(score,7),'untrusted_source_text':True}
                for score,r in results]
