"""Actual Atlas RAG smoke on FinanceBench annotated pages, local research only.
This is NOT full-filing retrieval, historical PIT, model QA or G3 certification.
Do not export underlying texts or use for commercial purposes without rights.
"""
from __future__ import annotations
import argparse,hashlib,json,tempfile
from pathlib import Path
from .financebench_reference import BLOB,SOURCE
from .query_terms import resolve_company
from .retrieval import ResearchIndex


def evaluate(rows):
    if not isinstance(rows,list) or not 1<=len(rows)<=1000:raise ValueError('dataset bounds')
    pages={};gold={};directory={};at='2099-01-01T00:00:00Z'
    for r in rows:
        qid,company=r['financebench_id'],r['company']
        if qid in gold or not company or not r['question'] or not r['evidence']:raise ValueError('invalid case')
        directory[company]=[company];ids=set()
        for e in r['evidence']:
            pid=e['doc_name']+':'+str(e['evidence_page_num']);body=e.get('evidence_text_full_page') or e['evidence_text']
            if pid not in pages:pages[pid]=(company,body)
            elif pages[pid][0]!=company:raise ValueError('ambiguous ownership')
            elif body not in pages[pid][1]:pages[pid]=(company,pages[pid][1]+'\n'+body)
            ids.add(pid)
        gold[qid]=ids
    # Dedicated temporary index; never put NC material in public/cloud-eligible scope.
    policy={'license_id':'financebench-noncommercial','permitted_for_personal_analysis':True,'allow_local_retention':True,'allow_rag_indexing':True,'cloud_allowed':False}
    with tempfile.TemporaryDirectory() as d:
        idx=ResearchIndex(Path(d)/'local.sqlite')
        for pid,(company,body) in pages.items():
            idx.add({'doc_id':pid,'source_id':'financebench','source_uri':SOURCE,'security_id':company,'available_at':at,'scope':'licensed','license_id':policy['license_id'],'content':body},policy)
        outcomes={};matched=correct=wrong=0
        for mode in ('global','auto_company','oracle_company'):
            vals=[]
            for r in rows:
                company=resolve_company(r['question'],directory) if mode=='auto_company' else r['company'] if mode=='oracle_company' else None
                if mode=='auto_company' and company is not None:
                    matched+=1;correct+=company==r['company'];wrong+=company!=r['company']
                hits=idx.search(r['question'],decision_at=at,security_id=company or '',scope='private_local',top_k=10)
                ids=[x['doc_id'] for x in hits];g=gold[r['financebench_id']];rank=next((i for i,x in enumerate(ids) if x in g),-1)
                # Reconstruct excerpts independently against original page text.
                for x in hits:
                    body=pages[x['doc_id']][1]
                    if x['text']!=body[x['excerpt_start']:x['excerpt_end']] or x['excerpt_sha256']!=hashlib.sha256(x['text'].encode()).hexdigest():raise ValueError('EXCERPT_MISMATCH')
                vals.append({'recall1':len(set(ids[:1])&g)/len(g),'recall5':len(set(ids[:5])&g)/len(g),'recall10':len(set(ids)&g)/len(g),'mrr':1/(rank+1) if rank>=0 else 0.})
            outcomes[mode]={k:sum(v[k] for v in vals)/len(vals) for k in vals[0]}
        if idx.search('revenue',decision_at=at,scope='public_only',top_k=10):raise ValueError('NC_SCOPE_LEAK')
    return {'status':'DEVELOPER_ATLAS_RETRIEVAL_ONLY','questions':len(rows),'pages':len(pages),'companies':len(directory),'entity_resolution':{'matched':matched,'correct':correct,'wrong':wrong,'unresolved':len(rows)-matched},'benchmark':outcomes,'can_trade':False,'l6_certified':False,'promotion_allowed':False,'limitations':['only annotated pages, not full filings','synthetic availability timestamp, not PIT','company dictionary from dataset corpus, not per-question oracle except explicit oracle mode','page relevance, not answer entailment','developer-visible noncommercial sample']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--jsonl',type=Path,required=True);p.add_argument('--confirm-noncommercial-evaluation-rights',action='store_true');a=p.parse_args()
    if not a.confirm_noncommercial_evaluation_rights:raise PermissionError('explicit noncommercial rights confirmation required')
    with a.jsonl.open('rb') as f:raw=f.read(2_000_001)
    if len(raw)>2_000_000 or hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=BLOB:raise ValueError('official Git blob mismatch')
    rows=[json.loads(x) for x in raw.decode('utf8').splitlines() if x.strip()]
    if len(rows)!=150:raise ValueError('unexpected official sample count')
    print(json.dumps(evaluate(rows)|{'source':SOURCE,'git_blob_sha1':BLOB},indent=2,allow_nan=False));return 0
if __name__=='__main__':raise SystemExit(main())
