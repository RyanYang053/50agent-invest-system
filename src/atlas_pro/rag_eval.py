"""Locked RAG retrieval evaluation, inspired by Inspect/FinanceBench.
Gold relevance judgments must be made independently and rights-checked.
"""
from __future__ import annotations
import math
from .ledger import digest,iso

def evaluate_retrieval(index,cases,*,expected_hash,top_k=5,embed=None,vector_backend=None):
    if type(top_k) is not int or not 1<=top_k<=25:raise ValueError('invalid top_k')
    if digest(cases)!=expected_hash:raise ValueError('evaluation dataset changed')
    if not cases or len({c['case_id'] for c in cases})!=len(cases):raise ValueError('empty or duplicate cases')
    if any(c.get('evaluation_rights_verified') is not True for c in cases):raise PermissionError('evaluation data rights unverified')
    rows=[]
    for c in cases:
        gold=set(c['relevant_doc_ids']); at=iso(c['decision_at']); scope=c.get('scope','public_only')
        if len(gold)!=len(c['relevant_doc_ids']) or scope not in ('public_only','private_local'):raise ValueError('invalid gold or scope')
        docs=index.search(c['query'],decision_at=c['decision_at'],security_id=c.get('security_id',''),scope=scope,top_k=top_k,embed=embed,vector_backend=vector_backend)
        ids=[d['doc_id'] for d in docs]
        if len(set(ids))!=len(ids):raise ValueError('duplicate retrieval results')
        violation=len(docs)>top_k or any(iso(d['available_at'])>at or (scope=='public_only' and d['scope']!='public') or (c.get('security_id') and d.get('security_id')!=c['security_id']) for d in docs)
        hits=[int(x in gold) for x in ids]
        dcg=sum(hit/math.log2(i+2) for i,hit in enumerate(hits)); ideal=sum(1/math.log2(i+2) for i in range(min(len(gold),top_k)))
        rows.append({'case_id':c['case_id'],'recall':sum(hits)/len(gold) if gold else float(not ids),'mrr':next((1/(i+1) for i,h in enumerate(hits) if h),0) if gold else float(not ids),'ndcg':dcg/ideal if ideal else float(not ids),'boundary_violation':violation,'retrieved_ids':ids})
    return {'n':len(rows),'dataset_hash':expected_hash,'recall_at_k':sum(r['recall'] for r in rows)/len(rows),'mrr':sum(r['mrr'] for r in rows)/len(rows),'ndcg_at_k':sum(r['ndcg'] for r in rows)/len(rows),'boundary_violations':sum(r['boundary_violation'] for r in rows),'results':rows,'promotion_allowed':False,'can_trade':False,'limitations':['gold relevance and temporal authenticity require human adjudication','retrieval scores do not establish claim entailment']}
