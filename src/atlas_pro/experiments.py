"""Bounded external research interchange, walk-forward validation and promotion proposals.
Inspired by Qlib/RD-Agent, LEAN, Inspect and MLflow; no subprocess or broker access.
No imported output is trusted merely because its producer has a recognized name.
"""
from __future__ import annotations
from .ledger import digest,iso
from .research import num
import math

ENGINES={'qlib','rd-agent','lean','skfolio','inspect-ai','dspy','promptfoo','quantstats'}


def purged_folds(samples, *, min_train=100, test_size=20, embargo_seconds=0):
    """Expanding walk-forward, purge label windows crossing test start; no future training."""
    if type(min_train) is not int or type(test_size) is not int or min_train<1 or test_size<1 or not math.isfinite(num(embargo_seconds)) or embargo_seconds<0:raise ValueError('invalid fold settings')
    ids=set(); times=[]
    for s in samples:
        t,e,a=(iso(s[k]) for k in ('signal_at','label_end_at','feature_available_at'))
        if a>t or e<=t or s['id'] in ids or (times and t<=times[-1][0]):raise ValueError('leakage, duplicate or unordered samples')
        ids.add(s['id']);times.append((t,e,s['id']))
    folds=[]
    for i in range(min_train,len(times)-test_size+1,test_size):
        test=times[i:i+test_size]; start=test[0][0]
        train=[k for t,e,k in times[:i] if (start-e).total_seconds()>embargo_seconds]
        if len(train)>=min_train:folds.append({'train_ids':train,'test_ids':[x[2] for x in test],'test_start':start.isoformat(),'test_end':max(x[1] for x in test).isoformat()})
    return folds


def experiment_request(*, engine, artifact_sha256, data_sha256, split_sha256, policy_sha256, budget_usd, at):
    """Export only hashes and a budget; an isolated operator runs the external engine."""
    if engine not in ENGINES or any(not isinstance(h,str) or len(h)!=64 or any(x not in '0123456789abcdef' for x in h) for h in (artifact_sha256,data_sha256,split_sha256,policy_sha256)):
        raise ValueError('unknown engine or invalid artifact hash')
    budget=num(budget_usd)
    if not 0<=budget<=100:raise ValueError('experiment budget outside bounds')
    r={'engine':engine,'artifact_sha256':artifact_sha256,'data_sha256':data_sha256,'split_sha256':split_sha256,'policy_sha256':policy_sha256,
       'budget_usd':budget,'created_at':iso(at).isoformat(),'mode':'OFFLINE_ISOLATED_RESEARCH','broker_credentials':False,'can_trade':False}
    return r|{'experiment_id':digest(r)}


def review_experiment(request, report, *, locked_test_ids, max_drawdown=.25, min_observations=100):
    """Validate a normalized report, independently recompute paired returns/drawdown.
    A schema pass is not proof of genuine source data, runtime identity, or alpha.
    Independent owner must attest provenance out of band before any promotion.
    """
    if request.get('experiment_id')!=digest({k:v for k,v in request.items() if k!='experiment_id'}):raise ValueError('request modified')
    for k in ('experiment_id','artifact_sha256','data_sha256','split_sha256','policy_sha256'):
        if report.get(k)!=request[k]:raise ValueError('experiment provenance mismatch: '+k)
    if report.get('engine')!=request['engine'] or report.get('execution_mode')!='OFFLINE_ISOLATED_RESEARCH' or report.get('can_trade') is not False:
        raise ValueError('unsafe or wrong engine report')
    if not 0<=num(report['cost_usd'])<=request['budget_usd']:raise ValueError('experiment budget exceeded')
    rows=report['observations']; expected=list(locked_test_ids)
    if not expected or len(set(expected))!=len(expected) or [r['id'] for r in rows]!=expected:raise ValueError('holdout coverage mismatch')
    if digest(expected)!=request['split_sha256']:raise ValueError('holdout IDs not locked')
    nav=bench=peak=1.; dd=0.; last=None; excess=[]
    for r in rows:
        t=iso(r['at'])
        if last is not None and t<=last:raise ValueError('unordered observations')
        last=t
        x,y=num(r['net_return']),num(r['benchmark_return'])
        if min(x,y)<-1 or not r.get('evidence_ids'):raise ValueError('invalid returns/provenance')
        nav*=1+x;bench*=1+y;peak=max(peak,nav);dd=max(dd,1-nav/peak);excess.append(x-y)
        if not math.isfinite(nav+bench):raise ValueError('nonfinite wealth')
    cap=num(max_drawdown)
    if not 0<=cap<=1 or min_observations<1:raise ValueError('invalid research gate')
    blockers=[]
    if len(rows)<min_observations:blockers.append('INSUFFICIENT_OBSERVATIONS')
    if nav<=bench:blockers.append('NO_NET_BENCHMARK_OUTPERFORMANCE')
    if dd>cap:blockers.append('DRAWDOWN_LIMIT')
    if report.get('synthetic') is not False:blockers.append('SYNTHETIC_OR_UNKNOWN_DATA')
    result={'status':'REJECTED' if blockers else 'INDEPENDENT_REVIEW_REQUIRED','blockers':blockers,'experiment_id':request['experiment_id'],
            'observations':len(rows),'net_return':nav-1,'benchmark_return':bench-1,'max_drawdown':dd,'mean_period_excess':sum(excess)/len(excess),
            'report_hash':digest(report),'promotion_allowed':False,'can_trade':False,
            'limitations':['paired path only; not statistically significant alpha','verify licensed historical universe, costs, leakage, trials, regime stability and shadow results independently']}
    return result|{'review_id':digest(result)}
