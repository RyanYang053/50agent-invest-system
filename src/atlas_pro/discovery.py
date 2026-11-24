"""Sector-relative multi-factor discovery (Qlib-inspired, no trained model).
All inputs must be already evidence-bound; rankings are exploratory only.
"""
from __future__ import annotations
from collections import defaultdict
from .ledger import iso,digest
from .research import num

def rank_factors(candidates,*,at,weights,min_sector=5):
    now=iso(at); weights={k:num(v) for k,v in weights.items()}
    if not weights or any(w<0 for w in weights.values()) or abs(sum(weights.values())-1)>1e-8 or min_sector<3:raise ValueError('bad factor weights')
    groups=defaultdict(list); seen=set(); rejected=[]
    for r in candidates:
        s=r['security_id']
        if not s or s in seen:raise ValueError('duplicate security')
        seen.add(s)
        if r.get('can_trade') is not False or not r.get('evidence_ids') or iso(r['available_at'])>now or not r.get('sector'):
            rejected.append(s);continue
        try:metrics={k:num(r['factors'][k]) for k in weights}
        except (KeyError,TypeError,ValueError):rejected.append(s);continue
        groups[r['sector']].append((s,metrics,r))
    scores=[]
    for sector,rows in groups.items():
        if len(rows)<min_sector:rejected.extend(r[0] for r in rows);continue
        n=len(rows)
        for s,metrics,raw in rows:
            percentiles={k:(sum(x[1][k]<metrics[k] for x in rows)+.5*sum(x[1][k]==metrics[k] for x in rows))/n for k in weights}
            scores.append({'security_id':s,'sector':sector,'sector_count':n,'score':sum(weights[k]*v for k,v in percentiles.items()),'factor_percentiles':percentiles,'evidence_ids':raw['evidence_ids'],'can_trade':False})
    return {'status':'RESEARCH_RANKING','ranked':sorted(scores,key=lambda r:(-r['score'],r['security_id'])),'rejected':sorted(rejected),'input_hash':digest(candidates),'weights_hash':digest(weights),'can_trade':False,'limitations':['higher factor values assumed desirable; caller must transform risk factors','unvalidated heuristic, not a probability or expected return','within supplied universe only']}
