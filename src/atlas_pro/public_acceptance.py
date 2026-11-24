"""Small developer-visible public-fact and synthetic RAG boundary smoke tests.
Not a held-out benchmark, certification, actual SEC network capture or investment result.
The public facts are manually transcribed from the linked SEC 10-Ks. No model calls.
"""
from __future__ import annotations
import argparse, json, tempfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from importlib.resources import files
from .ledger import digest
from .research import sec_annual_facts, annual_snapshot, TAGS
from .retrieval import ResearchIndex
from .rag_eval import evaluate_retrieval

PUBLIC_POLICY={'license_id':'PUBLIC_FACTS_DEV_SMOKE','permitted_for_personal_analysis':True,'allow_local_retention':True,'allow_rag_indexing':True,'cloud_allowed':True}
PRIVATE_POLICY={'license_id':'SYNTHETIC_PRIVATE_SMOKE','permitted_for_personal_analysis':True,'allow_local_retention':True,'allow_rag_indexing':True,'cloud_allowed':False}


def _add(index,doc_id,sid,when,content,*,uri='fixture:synthetic',private=False):
    policy=PRIVATE_POLICY if private else PUBLIC_POLICY
    index.add({'doc_id':doc_id,'source_id':'public_fact_smoke' if uri.startswith('https://') else 'synthetic_fixture','source_uri':uri,'security_id':sid,'available_at':when,'scope':'private' if private else 'public','license_id':policy['license_id'],'content':content},policy)


def _case(i,sid,at,ids,query,scope='public_only'):
    return {'case_id':i,'query':query,'security_id':sid,'decision_at':at,'scope':scope,'relevant_doc_ids':ids,'evaluation_rights_verified':True}


def _proxy(row):
    # SEC filing date only is verified for this small smoke. Use next-day 05:00 UTC,
    # conservatively after midnight in New York; not historical capture provenance.
    return (datetime.fromisoformat(row['filing_date']).replace(tzinfo=timezone.utc)+timedelta(days=1,hours=5)).isoformat()


def public_smoke(path):
    dataset=json.loads(files('atlas_pro').joinpath('public_filing_smoke.json').read_text())
    index=ResearchIndex(path);cases=[];checks=[]
    for issuer in dataset['issuers']:
        sid=f"CIK:{issuer['cik']}";rows=issuer['filings'];facts=[];ids=[]
        for row in rows:
            doc=row['accession'];ids.append(doc)
            _add(index,doc,sid,_proxy(row),f"{issuer['name']} {row['year']} annual consolidated revenue {row['revenue_usd_millions']} USD millions",uri=row['url'])
            facts.append({'form':'10-K','accn':doc,'start':row['start'],'end':row['end'],'val':row['revenue_usd_millions']*1_000_000})
        cf={'cik':issuer['cik'],'facts':{'us-gaap':{TAGS['revenue'][0]:{'units':{'USD':facts}}}}}
        sub={'cik':issuer['cik'],'filings':{'recent':{'accessionNumber':ids,'acceptanceDateTime':[_proxy(r) for r in rows]}}}
        # Replay normalized public facts through parser. No claims about real SEC JSON transport.
        cutoffs=[('before', (datetime.fromisoformat(_proxy(rows[0]))-timedelta(days=1)).isoformat(),[]),('first',_proxy(rows[0]),ids[:1]),('second',_proxy(rows[1]),ids)]
        for label,at,expected in cutoffs:
            f=sec_annual_facts(cf,sub,at=at,received_at=at,replay=True);snapshot=annual_snapshot(f,at=at)
            expected_revenue=None if not expected else rows[len(expected)-1]['revenue_usd_millions']*1_000_000
            actual=None if not snapshot else snapshot['metrics']['revenue']
            if actual!=expected_revenue or len(f)!=len(expected):raise AssertionError(f'public fact PIT failure {sid} {label}')
            cases.append(_case(sid+':'+label,sid,at,expected,'annual consolidated revenue'))
            checks.append({'security_id':sid,'case':label,'revenue_usd':actual,'expected_revenue_usd':expected_revenue,'eligible_filing_count':len(f)})
            if label=='second':
                independent=float(Decimal(rows[1]['revenue_usd_millions'])/Decimal(rows[0]['revenue_usd_millions'])-1)
                actual_growth=snapshot['metrics']['revenue_growth']
                if abs(actual_growth-independent)>1e-12:raise AssertionError('public fact revenue growth disagreement')
                checks[-1]['revenue_growth']=actual_growth
    report=evaluate_retrieval(index,cases,expected_hash=digest(cases),top_k=10)
    if report['recall_at_k']!=1 or report['boundary_violations']:raise AssertionError('public fact retrieval failed')
    return {'kind':'DEVELOPER_VISIBLE_PUBLIC_FACT_SMOKE','dataset_hash':digest(dataset),'issuers':len(dataset['issuers']),'filings':sum(len(x['filings']) for x in dataset['issuers']),'checks':checks,'rag':report,'limitations':['manually transcribed revenue facts, not full raw filing ingest','filing-date availability proxy, not historical capture','not independent, not holdout, no model or semantic entailment measurement']}


def boundary_smoke(path,*,entities=100):
    if type(entities) is not int or not 1<=entities<=1000:raise ValueError('invalid synthetic case count')
    index=ResearchIndex(path);cases=[]
    past='2025-01-02T12:00:00Z';future='2026-01-02T12:00:00Z'
    for i in range(entities):
        sid=f'FIXTURE:{i}';a,b,c=[sid+':'+s for s in ('public-past','public-future','private-past')]
        # Identical text across companies and scopes forces correct filtering.
        for doc,at,private in ((a,past,False),(b,future,False),(c,past,True)):
            _add(index,doc,sid,at,'shared financial revenue margin adversarial fixture',private=private)
        for j,(at,scope,gold) in enumerate([('2024-01-01T00:00:00Z','public_only',[]),(past,'public_only',[a]),(past,'private_local',[a,c]),(future,'public_only',[a,b]),(future,'private_local',[a,b,c])]):
            cases.append(_case(f'{i}:{j}',sid,at,gold,'shared financial revenue margin',scope))
    report=evaluate_retrieval(index,cases,expected_hash=digest(cases),top_k=10)
    if report['recall_at_k']!=1 or report['boundary_violations']:raise AssertionError('RAG security boundary failure')
    # Keep an aggregate and a hash for reproducibility; generated cases are not real gold.
    return {k:v for k,v in report.items() if k!='results'}|{'kind':'SYNTHETIC_BOUNDARY_SMOKE','entities':entities,'fixture_documents':entities*3,'result_hash':digest(report['results'])}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path);a=p.parse_args()
    with tempfile.TemporaryDirectory(prefix='atlas-acceptance-') as tmp:
        r={'status':'DEVELOPER_SMOKE_PASSED','public':public_smoke(Path(tmp)/'public.sqlite'),'synthetic_rag':boundary_smoke(Path(tmp)/'boundary.sqlite'),'network_calls':0,'model_calls':0,'broker_orders':0,'l6_certified':False,'can_trade':False}
    raw=json.dumps(r,indent=2,allow_nan=False)
    if a.output:
        with a.output.open('x',encoding='utf8') as f:f.write(raw+'\n')
    print(raw);return 0
if __name__=='__main__':raise SystemExit(main())
