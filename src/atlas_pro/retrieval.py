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
            cols={r[1] for r in c.execute('PRAGMA table_info(docs)')}
            if 'embedding_model_id' not in cols:c.execute('ALTER TABLE docs ADD COLUMN embedding_model_id TEXT')

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
        if document['license_id']!=license_policy.get('license_id') or license_policy.get('permitted_for_personal_analysis') is not True:
            raise PermissionError('LICENSE_RESTRICTED')
        if license_policy.get('allow_local_retention') is not True or license_policy.get('allow_rag_indexing') is not True:
            raise PermissionError('LICENSE_FORBIDS_INDEXING')
        if document['scope']=='public' and license_policy.get('cloud_allowed') is not True:
            raise PermissionError('PUBLIC_SCOPE_REQUIRES_CLOUD_ENTITLEMENT')
        if document['scope']=='private' and license_policy.get('cloud_allowed'):
            raise PermissionError('PRIVATE_CLOUD_SCOPE_INVALID')
        body=document['content']
        if len(body)>250_000: raise ValueError('DOC_TOO_LARGE_SPLIT_INTO_CHUNKS')
        if embed and document['scope'] != 'public' and not getattr(embed,'local_only',False):
            raise PermissionError('PRIVATE_EMBEDDING_MUST_BE_LOCAL')
        model_id=getattr(embed,'model_id',None) if embed else None
        if model_id is not None and (not isinstance(model_id,str) or not model_id.strip()):raise ValueError('INVALID_EMBEDDING_MODEL_ID')
        vector=embed(body) if embed else None
        if vector is not None:
            if not isinstance(vector,(tuple,list)) or not vector or any(not isinstance(x,(float,int)) or not math.isfinite(x) for x in vector):
                raise ValueError('INVALID_EMBEDDING')
        hashval=hashlib.sha256(body.encode()).hexdigest()
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM docs WHERE doc_id=?',(document['doc_id'],)).fetchone()
            if old:
                if old['text_sha256']!=hashval or any(old[k]!=document[k] for k in ('source_id','source_uri','security_id','scope','license_id')) or old['available_at']!=dt.isoformat(): raise ValueError('DOC_IMMUTABILITY_CONFLICT')
                if vector is not None and old['embedding_model_id']!=model_id:raise ValueError('EMBEDDING_MODEL_MISMATCH_REINDEX_REQUIRED')
                return 'DUPLICATE'
            c.execute('''INSERT INTO docs(doc_id,source_id,source_uri,security_id,available_at,scope,license_id,text_sha256,indexed_at,embedding_json,content,embedding_model_id)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
              (document['doc_id'],document['source_id'],document['source_uri'],document['security_id'],dt.isoformat(),document['scope'],document['license_id'],hashval,datetime.now(timezone.utc).isoformat(),json.dumps(vector) if vector is not None else None,body,model_id))
        return 'ADDED'

    @staticmethod
    def _cos(a,b):
        if len(a)!=len(b): return 0
        norm_a=math.sqrt(sum(x*x for x in a)); norm_b=math.sqrt(sum(x*x for x in b))
        return sum(x*y for x,y in zip(a,b))/(norm_a*norm_b) if norm_a and norm_b else 0.0

    def search(self, query:str, *, decision_at:str, scope:str='public_only', security_id:str='', top_k:int=5, embed=None, vector_backend=None):
        decision_at=iso(decision_at).isoformat()
        if scope not in ('public_only','private_local'):
            raise ValueError('INVALID_RETRIEVAL_SCOPE')
        if vector_backend is not None and (not embed or getattr(vector_backend,'local_only',False) is not True or getattr(vector_backend,'index',None) is not self):
            raise PermissionError('INVALID_LOCAL_VECTOR_BACKEND')
        if embed and scope=='private_local' and not getattr(embed,'local_only',False):
            raise PermissionError('PRIVATE_QUERY_EMBEDDING_MUST_BE_LOCAL')
        if not 1<=top_k<=25: raise ValueError('TOP_K_OUT_OF_RANGE')
        terms=re.findall(r'[\w]+',query,flags=re.UNICODE)
        # Avoid raw FTS query syntax and unsafe operators; use terms only.
        terms=[t for t in terms if len(t)>=2][:10]
        cjk_terms=re.findall(r'[\u3400-\u9fff]+',query)[:5]
        if not terms: return []
        clauses=['d.available_at<=?']; params=[decision_at]
        if scope=='public_only': clauses.append("d.scope='public'")
        if security_id: clauses.append('d.security_id=?'); params.append(security_id)
        where=' AND '.join(clauses)
        fts_query=' OR '.join('"'+term.replace('"','')+'"' for term in terms)
        with self._db() as c:
            rows=c.execute(f'''SELECT d.*,bm25(docs_fts) AS bm FROM docs_fts
              JOIN docs d ON d.rowid=docs_fts.rowid
              WHERE docs_fts MATCH ? AND {where} ORDER BY bm,d.doc_id LIMIT 60''',[fts_query]+params).fetchall()
            lexical={r['doc_id']:(1.0/(60+i),dict(r)) for i,r in enumerate(rows)}
            if cjk_terms:
                extra=c.execute(f"SELECT d.* FROM docs d WHERE {where} AND ("+' OR '.join('instr(d.content,?)>0' for _ in cjk_terms)+") ORDER BY d.available_at DESC, d.doc_id LIMIT 60",params+cjk_terms).fetchall()
                for i,r in enumerate(extra):
                    if r['doc_id'] not in lexical:lexical[r['doc_id']]=(1.0/(60+i),dict(r))
            # Unversioned vectors cannot safely be compared across model revisions.
            model_id=getattr(embed,'model_id',None) if embed else None
            if embed and model_id:
                vec=embed(query)
                if not isinstance(vec,(list,tuple)) or not vec or any(type(x) not in (float,int) or not math.isfinite(x) for x in vec):raise ValueError('INVALID_QUERY_EMBEDDING')
                sims=[]
                if vector_backend is not None:
                    hits=vector_backend.search(vec,decision_at=decision_at,scope=scope,security_id=security_id,model_id=model_id,limit=60)
                    if len(hits)>60:raise ValueError('VECTOR_BACKEND_RESULT_CAP')
                    seen=set()
                    for score,hit in hits:
                        doc=hit['doc_id']
                        if doc in seen or not math.isfinite(score):raise ValueError('INVALID_VECTOR_HIT')
                        seen.add(doc)
                        # Rehydrate authoritative content, never accept text from a vector backend.
                        row=c.execute(f'SELECT d.* FROM docs d WHERE {where} AND d.doc_id=? AND d.embedding_model_id=?',params+[doc,model_id]).fetchone()
                        if row is None or row['text_sha256']!=hit.get('text_sha256'):raise ValueError('VECTOR_HIT_NOT_AUTHORIZED')
                        if score>0:sims.append((score,dict(row)))
                else:
                    allrows=c.execute(f'SELECT * FROM docs d WHERE {where} AND embedding_json IS NOT NULL AND embedding_model_id=? ORDER BY d.doc_id LIMIT 5001',params+[model_id]).fetchall()
                    if len(allrows)>5000:raise ValueError('EXACT_VECTOR_CAPACITY_EXCEEDED_USE_VALIDATED_INDEX')
                    for r in allrows:
                        stored=json.loads(r['embedding_json'])
                        if len(vec)!=len(stored):raise ValueError('EMBEDDING_DIMENSION_MISMATCH')
                        sim=self._cos(vec,stored)
                        if sim>0:sims.append((sim,dict(r)))
                sims.sort(key=lambda x:(-x[0],x[1]['doc_id']))
                for i,(_,r) in enumerate(sims[:60]):
                    prior=lexical.get(r['doc_id'],(0,r))
                    lexical[r['doc_id']]=(prior[0]+1.0/(60+i),r)
        results=sorted(lexical.values(),key=lambda x:(-x[0],x[1]['doc_id']))[:top_k]
        for _,r in results:
            if hashlib.sha256(r['content'].encode()).hexdigest()!=r['text_sha256']:raise ValueError('DOCUMENT_CONTENT_INTEGRITY_FAILURE')
        # Return source refs, NOT operator instructions. Cloud cannot query private.
        return [{'doc_id':r['doc_id'],'source_id':r['source_id'],'source_uri':r['source_uri'],
                 'available_at':r['available_at'],'security_id':r['security_id'],'evidence_sha256':r['text_sha256'],
                 'scope':r['scope'],'text':r['content'][:1600],
                 'retrieval_score':round(score,7),'untrusted_source_text':True}
                for score,r in results]
