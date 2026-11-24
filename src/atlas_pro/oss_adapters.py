"""Opt-in, local-only adapters for mature open-source research engines.
External engines run under an operator in a separate, egress-restricted process.
No pickles, executable artifacts, brokerage keys, arbitrary SQL or live routes.
An optional dependency or a valid artifact hash does not certify financial quality.
"""
from __future__ import annotations
import hashlib, json, math, re, uuid
from pathlib import Path
from datetime import timezone
from .ledger import iso, digest
from .research import num
from .evaluation import grade_locked
from .experiments import review_experiment


def local_bytes(path, expected_sha256, *, max_bytes=32*1024*1024):
    """Read one pinned regular local file; never a URL, glob or serialized code."""
    p=Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size>max_bytes:
        raise ValueError('invalid local artifact')
    with p.open('rb') as f: b=f.read(max_bytes+1)
    if len(b)>max_bytes or hashlib.sha256(b).hexdigest()!=expected_sha256:
        raise ValueError('artifact size/hash mismatch')
    return b


def artifact_json(path, expected_sha256):
    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result: raise ValueError('duplicate JSON field')
            result[k]=v
        return result
    def reject_constant(x): raise ValueError('nonfinite JSON constant')
    return json.loads(local_bytes(path,expected_sha256),object_pairs_hook=unique,parse_constant=reject_constant)


def qlib_predictions(rows, *, universe, decision_at, model_hash, data_hash, evidence_lookup):
    """Accept exported numeric scores, not Qlib recorder pickles. No alpha claim.
    Universe membership and each input evidence row are independently checked.
    evidence_lookup is an operator-bound authoritative evidence resolver.
    """
    cutoff=iso(decision_at); allowed=set(universe)
    if not allowed or len(allowed)!=len(universe) or len(rows)>len(allowed):raise ValueError('invalid locked universe')
    if any(not re.fullmatch('[a-f0-9]{64}',h) for h in (model_hash,data_hash)):raise ValueError('artifact hashes required')
    seen=set(); valid=[]
    for r in rows:
        s=r['security_id']; t=iso(r['signal_at']); training_end=iso(r['training_label_end_at'])
        if s not in allowed or s in seen or not training_end<t<=cutoff or r.get('model_sha256')!=model_hash or r.get('data_sha256')!=data_hash:
            raise ValueError('prediction identity/temporal mismatch')
        seen.add(s)
        ids=r['evidence_ids']
        if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)):raise ValueError('missing prediction provenance')
        records=evidence_lookup(ids,security_id=s,decision_at=t.isoformat())
        if {x['record_id'] for x in records}!=set(ids) or any(iso(x['available_at'])>t or x['security_id']!=s for x in records):raise ValueError('prediction evidence mismatch')
        valid.append({'security_id':s,'score':num(r['score']),'signal_at':t.isoformat(),'evidence_ids':ids,'can_trade':False})
    return {'status':'UNVERIFIED_EXTERNAL_RANKING','engine':'qlib','ranked':sorted(valid,key=lambda x:(-x['score'],x['security_id'])),'missing':sorted(allowed-seen),'input_hash':digest(rows),'can_trade':False}


def lean_equity_review(request, *, equity_rows, benchmark_rows, locked_test_ids, cost_usd, synthetic):
    """Normalize an explicit LEAN equity curve export; benchmark is independent.
    Require a starting NAV point plus exact ordered observations; no money flows.
    Net NAV must already reflect fees/slippage/dividends per independently audited run.
    """
    if request['engine']!='lean':raise ValueError('LEAN request required')
    if len(equity_rows)!=len(locked_test_ids)+1 or len(benchmark_rows)!=len(locked_test_ids)+1:raise ValueError('incomplete equity curve')
    if not locked_test_ids or [r['id'] for r in equity_rows[1:]]!=list(locked_test_ids) or [r['id'] for r in benchmark_rows[1:]]!=list(locked_test_ids):raise ValueError('holdout alignment')
    observations=[]; prior=None
    for e,b in zip(equity_rows,benchmark_rows):
        t=iso(e['at']); x,y=num(e['net_equity']),num(b['total_return_index'])
        if iso(b['at'])!=t or e['id']!=b['id'] or min(x,y)<=0 or e.get('external_flow')!=0 or not e.get('evidence_ids') or not b.get('evidence_ids'):
            raise ValueError('invalid curve, cash flow or benchmark')
        if prior:
            if t<=prior[0]:raise ValueError('nonchronological curve')
            observations.append({'id':e['id'],'at':t.isoformat(),'net_return':x/prior[1]-1,'benchmark_return':y/prior[2]-1,'evidence_ids':sorted(set(e['evidence_ids']+b['evidence_ids']))})
        prior=(t,x,y)
    report={k:request[k] for k in ('experiment_id','artifact_sha256','data_sha256','split_sha256','policy_sha256','engine')}
    report.update(execution_mode='OFFLINE_ISOLATED_RESEARCH',cost_usd=cost_usd,synthetic=synthetic,observations=observations,can_trade=False)
    return review_experiment(request,report,locked_test_ids=locked_test_ids)


def inspect_responses(samples, cases, *, expected_hash, minimum_quality=.95, min_cases=100):
    """Independently grade structured answers exported from Inspect EvalSample.
    Discard upstream scores, judge messages and reported certification. Never parse code.
    The exporter should use EvalSample.output.completion and stable sample IDs.
    """
    known={c['case_id'] for c in cases}; answers={}; seen=set()
    for s in samples:
        k=s['case_id']
        if k not in known or k in seen:raise ValueError('unexpected/duplicate sample')
        seen.add(k)
        if s.get('error') or s.get('completed') is not True:continue
        raw=s.get('completion')
        if not isinstance(raw,str) or len(raw)>100_000:continue
        try:
            def unique(pairs):
                d={}
                for x,y in pairs:
                    if x in d:raise ValueError('duplicate key')
                    d[x]=y
                return d
            answers[k]=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite')))
        except (ValueError,TypeError):continue
    return grade_locked(cases,answers,expected_hash=expected_hash,minimum_quality=minimum_quality,min_cases=min_cases)


def duckdb_pit(path, *, sha256, security_id, decision_at, license_policy, max_rows=100_000):
    """Read a fixed-schema local Parquet snapshot via DuckDB; no arbitrary SQL.
    Data ingestion is not evidence certification. Require prior retention rights.
    Run in an OS-restricted process; parser isolation is not provided by Python.
    """
    if license_policy.get('permitted_for_personal_analysis') is not True or license_policy.get('allow_local_retention') is not True:raise PermissionError('warehouse license denied')
    if not 1<=max_rows<=100_000 or not security_id:raise ValueError('query bounds')
    p=Path(path)
    if p.suffix.lower()!='.parquet' or any(x in str(p) for x in '*?[]'):raise ValueError('local parquet required')
    local_bytes(p,sha256,max_bytes=256*1024*1024)
    import duckdb
    c=duckdb.connect(':memory:',config={'autoinstall_known_extensions':'false','autoload_known_extensions':'false'})
    try:
        # The path is an operator-approved, hash-pinned file; no SQL interpolation.
        c.read_parquet(str(p.resolve())).create_view('atlas_snapshot')
        rows=c.execute('''SELECT security_id, field, period_end, available_at, revision, value, evidence_id
            FROM atlas_snapshot WHERE security_id=? AND CAST(available_at AS TIMESTAMPTZ)<=CAST(? AS TIMESTAMPTZ)
            QUALIFY DENSE_RANK() OVER (PARTITION BY security_id,field,period_end ORDER BY CAST(available_at AS TIMESTAMPTZ) DESC,revision DESC)=1
            ORDER BY field,period_end LIMIT ?''',[security_id,iso(decision_at).isoformat(),max_rows+1]).fetchall()
    finally:c.close()
    if len(rows)>max_rows:raise ValueError('warehouse capacity exceeded')
    local_bytes(p,sha256,max_bytes=256*1024*1024)
    out=[];seen=set()
    for s,field,period,t,revision,value,eid in rows:
        k=(s,field,str(period)); stamp=iso(t.isoformat() if hasattr(t,'isoformat') else str(t))
        if k in seen or s!=security_id or stamp>iso(decision_at) or not field or not eid:raise ValueError('warehouse duplicate/invalid fact')
        seen.add(k);out.append({'security_id':s,'field':field,'period_end':str(period),'available_at':stamp.isoformat(),'revision':revision,'value':num(value),'evidence_id':eid})
    return {'status':'PIT_WAREHOUSE_CANDIDATES','source_sha256':sha256,'rows':out,'can_trade':False,'requires_ledger_verification':True}


class LocalQdrantSnapshot:
    """Local Qdrant vector index built from authoritative SQLite snapshot.
    No text or credentials sent to a server. Rebuild on changes; query scope and
    timestamps pre-filtered, results rehydrated by Atlas. Operator-only backend.
    """
    local_only=True
    def __init__(self,index, *, model_id, dimension, max_documents=100_000):
        if not model_id or type(dimension) is not int or not 1<=dimension<=8192 or not 1<=max_documents<=100_000:raise ValueError('index bounds')
        from qdrant_client import QdrantClient,models
        self.index=index;self.model_id=model_id;self.dimension=dimension;self.models=models
        self.client=QdrantClient(':memory:');self.collection='atlas_vectors'
        self.client.create_collection(collection_name=self.collection,vectors_config=models.VectorParams(size=dimension,distance=models.Distance.COSINE))
        with index._db() as c:
            c.execute('BEGIN');self.fingerprint=self._fingerprint(c)
            cursor=c.execute('SELECT doc_id,security_id,scope,available_at,text_sha256,embedding_json FROM docs WHERE embedding_model_id=? AND embedding_json IS NOT NULL ORDER BY doc_id',(model_id,))
            count=0
            while batch:=cursor.fetchmany(256):
                count+=len(batch)
                if count>max_documents:raise ValueError('Qdrant snapshot cap exceeded')
                points=[]
                for r in batch:
                    v=json.loads(r['embedding_json']);self._check(v)
                    points.append(models.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL,r['doc_id'])),vector=v,payload={'doc_id':r['doc_id'],'scope':r['scope'],'security_id':r['security_id'],'available_us':int(iso(r['available_at']).timestamp()*1_000_000),'sha':r['text_sha256']}))
                self.client.upsert(collection_name=self.collection,points=points,wait=True)
    def _check(self,v):
        if not isinstance(v,(list,tuple)) or len(v)!=self.dimension or any(type(x) not in (int,float) or not math.isfinite(x) for x in v) or not any(v):raise ValueError('invalid vector')
    def _fingerprint(self,c):
        # Full ordered manifest binds immutable source hashes, metadata and vectors.
        h=hashlib.sha256()
        for r in c.execute('SELECT doc_id,security_id,scope,available_at,text_sha256,embedding_json FROM docs WHERE embedding_model_id=? AND embedding_json IS NOT NULL ORDER BY doc_id',(self.model_id,)):
            h.update(digest(dict(r)).encode())
        return h.hexdigest()
    def search(self,query_vector,*,decision_at,scope,security_id,model_id,limit=60):
        if model_id!=self.model_id or scope not in ('public_only','private_local') or not 1<=limit<=60:raise ValueError('invalid query scope or model')
        self._check(query_vector);m=self.models
        clauses=[m.FieldCondition(key='available_us',range=m.Range(lte=int(iso(decision_at).timestamp()*1_000_000)))]
        if scope=='public_only':clauses.append(m.FieldCondition(key='scope',match=m.MatchValue(value='public')))
        if security_id:clauses.append(m.FieldCondition(key='security_id',match=m.MatchValue(value=security_id)))
        with self.index._db() as c:
            c.execute('BEGIN')
            if self._fingerprint(c)!=self.fingerprint:raise ValueError('QDRANT_SNAPSHOT_STALE_REBUILD')
            hits=self.client.query_points(collection_name=self.collection,query=list(query_vector),query_filter=m.Filter(must=clauses),limit=limit,with_payload=True,with_vectors=False).points
            out=[]
            for hit in hits:
                p=hit.payload or {};row=c.execute('SELECT * FROM docs WHERE doc_id=?',(p.get('doc_id'),)).fetchone()
                if row is None or row['text_sha256']!=p.get('sha') or row['embedding_model_id']!=model_id or iso(row['available_at'])>iso(decision_at) or (scope=='public_only' and row['scope']!='public') or (security_id and row['security_id']!=security_id):raise ValueError('QDRANT_RESULT_SCOPE_MISMATCH')
                out.append((num(hit.score),dict(row)))
        return out
    def close(self):self.client.close()


def docling_markdown(path, *, sha256, artifact_directory, sandbox_confirmed=False):
    """Explicit operator local PDF conversion. Markdown alone is not table/cell provenance.
    Requires pre-fetched model assets and a real network-denied OS sandbox.
    The flag is an operator attestation, not a sandbox implementation.
    """
    if sandbox_confirmed is not True:raise PermissionError('independent offline sandbox required')
    p=Path(path);root=Path(artifact_directory)
    if p.suffix.lower()!='.pdf' or not root.is_dir() or root.is_symlink():raise ValueError('local PDF and model artifacts required')
    b=local_bytes(p,sha256,max_bytes=64*1024*1024)
    if not b.startswith(b'%PDF-'):raise ValueError('invalid PDF')
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter,PdfFormatOption
    opts=PdfPipelineOptions(artifacts_path=root.resolve(),enable_remote_services=False,allow_external_plugins=False,do_ocr=False,document_timeout=120)
    converter=DocumentConverter(format_options={InputFormat.PDF:PdfFormatOption(pipeline_options=opts)})
    result=converter.convert(p.resolve(),max_num_pages=500,max_file_size=64*1024*1024)
    local_bytes(p,sha256,max_bytes=64*1024*1024)
    status=getattr(result.status,'value',str(result.status))
    if status!='success':raise ValueError('PDF conversion incomplete')
    text=result.document.export_to_markdown()
    if not isinstance(text,str) or not text.strip() or len(text)>5_000_000:raise ValueError('invalid conversion')
    return {'status':'UNVERIFIED_DOCUMENT_CONVERSION','source_sha256':sha256,'markdown':text,'can_trade':False,'requires_table_and_citation_verification':True}


def skfolio_cvar(samples,weights,*,alpha=.95):
    """Independent skfolio risk cross-check with same aligned scenarios/weights.
    Do not use an optimizer result as trade authorization; verify conventions.
    """
    import pandas as pd
    from skfolio import Portfolio
    if not 0<alpha<1 or len(samples)<100 or not weights or any(set(s)!=set(weights) for s in samples):raise ValueError('misaligned samples')
    names=sorted(weights);w=[num(weights[k]) for k in names]
    if min(w)<0 or abs(sum(w)-1)>1e-8:raise ValueError('weights invalid')
    frame=pd.DataFrame([[num(s[k]) for k in names] for s in samples],columns=names)
    if (frame<-1).any().any():raise ValueError('return invalid')
    p=Portfolio(X=frame,weights=w,cvar_beta=alpha)
    return {'status':'EXTERNAL_RISK_CROSSCHECK','cvar':num(p.cvar),'alpha':alpha,'sample_hash':digest(samples),'can_trade':False}
