"""Locked numeric/citation evaluation for model candidates, no self-promotion.
The operator must use authorized evaluation data, and hold out test answers.
Synthetic cases can validate infrastructure, never certify market performance.
"""
from __future__ import annotations
from .ledger import digest
from .research import num
import math


def grade_locked(cases, responses, *, expected_hash, minimum_quality=.95, min_cases=100):
    """Exact structured answers, tolerance and citation allowlists; missing = fail.
    No LLM-as-judge. Cannot assess arbitrary prose faithfulness or stock alpha.
    """
    if digest(cases)!=expected_hash:raise ValueError('LOCKED_DATASET_HASH_MISMATCH')
    if not cases or not 0<minimum_quality<=1 or min_cases<1:raise ValueError('invalid evaluation thresholds')
    if len({c['case_id'] for c in cases})!=len(cases):raise ValueError('duplicate case IDs')
    results=[]
    for c in cases:
        if c.get('evaluation_rights_verified') is not True:raise PermissionError('UNAUTHORIZED_EVALUATION_DATA')
        tolerance=num(c.get('relative_tolerance',.00001))
        if not 0<=tolerance<=.01:raise ValueError('invalid numerical tolerance')
        a=responses.get(c['case_id']); valid=False; critical=True
        if isinstance(a,dict):
            cited=a.get('evidence_ids'); allowed=set(c['allowed_evidence_ids'])
            citation_ok=isinstance(cited,list) and all(isinstance(x,str) and x in allowed for x in cited) and bool(cited)
            if c.get('must_abstain') is True:
                valid=a.get('abstain') is True and a.get('values')=={} and isinstance(cited,list) and all(isinstance(x,str) and x in allowed for x in cited)
                critical=not valid
            else:
                expected=c['expected_values']; got=a.get('values'); valid=citation_ok and isinstance(got,dict) and set(got)==set(expected) and a.get('abstain') is False
                if valid:
                    try:valid=all(abs(num(got[k])-num(v))<=max(1e-10,abs(num(v))*tolerance) for k,v in expected.items())
                    except (TypeError,ValueError):valid=False
                critical=not citation_ok
        results.append({'case_id':c['case_id'],'pass':valid,'critical_failure':critical})
    quality=sum(r['pass'] for r in results)/len(results); fails=sum(r['critical_failure'] for r in results)
    synthetic=any(c.get('synthetic') is not False for c in cases)
    return {'locked_testset_hash':expected_hash,'results':results,'quality':quality,'critical_failures':fails,'n':len(cases),
            'eligible_for_external_review':len(cases)>=min_cases and quality>=minimum_quality and fails==0 and not synthetic,
            'synthetic_or_unspecified':synthetic,'promotion_allowed':False,'limitations':['numeric extraction and citation membership only','human verification of dataset rights and holdout integrity required']}
