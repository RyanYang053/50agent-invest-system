"""Developer reference on FinanceBench annotated evidence pages only.
Not full-filing RAG, model QA, temporal validation or an untouched holdout.
Operator supplies the official, locally licensed JSONL. Raw text never emitted.
FinanceBench: Islam et al., arXiv:2311.11944; Patronus AI public sample,
noncommercial use. Do not train, redistribute or assume commercial rights.
"""
from __future__ import annotations
import argparse,hashlib,json,math,re
from collections import Counter
from pathlib import Path
from .ledger import digest
SOURCE='https://github.com/patronus-ai/financebench/blob/cc39aeb4afdf33909ee1412188bf89035950c2eb/data/financebench_open_source.jsonl'
BLOB='4aef1d43a443474ba193f158f2baf70550ff528d'


def run_reference(rows):
    """Exactly the declared BM25 reference, with no indexed questions/answers."""
    if not isinstance(rows,list) or not rows or len(rows)>1000:raise ValueError('dataset bounds')
    pages={};gold={}
    def tok(s):return re.findall(r'[a-z0-9]+(?:\.[0-9]+)?',s.lower())
    for row in rows:
        qid=row['financebench_id'];company=row['company']
        if qid in gold or not row['question'] or not row['evidence']:raise ValueError('duplicate or invalid question')
        ids=set()
        for e in row['evidence']:
            pid=f"{e['doc_name']}:{e['evidence_page_num']}";body=e.get('evidence_text_full_page') or e['evidence_text']
            if pid not in pages:pages[pid]={'id':pid,'doc':e['doc_name'],'company':company,'body':body}
            elif pages[pid]['company']!=company:raise ValueError('ambiguous filing ownership')
            elif body not in pages[pid]['body']:pages[pid]['body']+='\n'+body
            ids.add(pid)
        gold[qid]=ids
    docs=list(pages.values());df=Counter();total=0
    for d in docs:
        ts=tok(d['body']);d['n']=len(ts);total+=len(ts);d['freq']=Counter(ts);df.update(d['freq'].keys())
    avg=total/len(docs)
    if avg<=0:raise ValueError('empty corpus')
    def score(d,terms):
        s=0.
        for t in terms:
            n=d['freq'][t]
            if n:s+=math.log(1+(len(docs)-df[t]+.5)/(df[t]+.5))*(n*2.2)/(n+1.2*(.25+.75*d['n']/avg))
        return s
    benchmarks={}
    for scope in ('global','company_known','filing_known'):
        vals=[]
        for q in rows:
            terms=list(dict.fromkeys(tok(q['question'])));g=gold[q['financebench_id']]
            found=[(d['id'],score(d,terms)) for d in docs if scope=='global' or (d['company']==q['company'] if scope=='company_known' else d['doc']==q['doc_name'])]
            found=sorted((v for v in found if v[1]>0),key=lambda v:(-v[1],v[0].casefold()));rank=next((i for i,v in enumerate(found) if v[0] in g),-1)
            def recall(k):return sum(v[0] in g for v in found[:k])/len(g)
            vals.append({'r1':recall(1),'r5':recall(5),'r10':recall(10),'mrr':1/(rank+1) if rank>=0 else 0.,'hit10':int(0<=rank<10)})
        benchmarks[scope]={k:sum(v[k] for v in vals)/len(vals) for k in vals[0]}
    return {'status':'DEVELOPER_REFERENCE_ONLY','questions':len(rows),'companies':len({r['company'] for r in rows}),'filings':len({r['doc_name'] for r in rows}),'unique_annotated_pages':len(docs),'benchmark':benchmarks,'can_trade':False,'promotion_allowed':False,'l6_certified':False,'limitations':['annotated gold pages only, not full filings','known company/filing is oracle metadata, not entity resolution quality','public developer-visible dataset, not independent holdout','no claim entailment, no paid model and no proof of PIT availability']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--jsonl',type=Path,required=True);p.add_argument('--confirm-noncommercial-evaluation-rights',action='store_true');a=p.parse_args()
    if not a.confirm_noncommercial_evaluation_rights:raise PermissionError('explicit dataset rights confirmation required')
    with a.jsonl.open('rb') as f:raw=f.read(2_000_001)
    if len(raw)>2_000_000 or hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=BLOB:raise ValueError('official dataset Git blob mismatch')
    rows=[json.loads(x) for x in raw.decode('utf8').splitlines() if x.strip()]
    if len(rows)!=150:raise ValueError('unexpected official sample count')
    r=run_reference(rows);print(json.dumps(r|{'source':SOURCE,'git_blob_sha1':BLOB,'sha256':hashlib.sha256(raw).hexdigest()},allow_nan=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
