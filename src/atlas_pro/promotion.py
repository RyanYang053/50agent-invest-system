"""Champion/challenger evidence gate, never deployment. Paired moving-block
bootstrap preserves within-block dependence; Bonferroni penalizes recorded trials.
The locked holdout and trial history still require external verification.
"""
from __future__ import annotations
import math,random,statistics
from .ledger import digest,iso
from .research import num


def compare_challenger(champion,challenger,*,locked_ids,trial_count,block_size=10,resamples=2000,seed=42,max_drawdown=.25):
    if type(trial_count) is not int or not 1<=trial_count<=1000 or type(block_size) is not int or not 2<=block_size<=60 or type(resamples) is not int or not 1000<=resamples<=10000:
        raise ValueError('invalid experiment controls')
    if not locked_ids or len(locked_ids)!=len(set(locked_ids)) or len(champion)!=len(locked_ids) or len(challenger)!=len(locked_ids) or len(locked_ids)>5000:raise ValueError('holdout coverage mismatch')
    paired=[]; wealth=peak=1.;dd=0.;last=None
    for a,b,k in zip(champion,challenger,locked_ids):
        t=iso(a['at'])
        if a['id']!=k or b['id']!=k or iso(b['at'])!=t or (last and t<=last) or not a.get('evidence_ids') or not b.get('evidence_ids'):raise ValueError('unaligned evaluation evidence')
        if a.get('net_of_costs') is not True or b.get('net_of_costs') is not True or a.get('synthetic') is not False or b.get('synthetic') is not False:raise ValueError('unqualified prospective data')
        x,y=num(a['net_return']),num(b['net_return'])
        if min(x,y)<=-1:raise ValueError('insolvency or invalid return')
        paired.append(math.log1p(y)-math.log1p(x)); wealth*=1+y;peak=max(peak,wealth);dd=max(dd,1-wealth/peak);last=t
        if not math.isfinite(wealth):raise ValueError('nonfinite path')
    n=len(paired); blockers=[]; cap=num(max_drawdown)
    if not 0<=cap<=1:raise ValueError('invalid drawdown budget')
    if dd>cap:blockers.append('DRAWDOWN_LIMIT')
    if n<max(100,10*block_size):blockers.append('INSUFFICIENT_DEPENDENT_OBSERVATIONS')
    corrected=.05/trial_count
    # Do not extrapolate an unresolvable percentile below Monte Carlo resolution.
    if resamples*corrected<10:blockers.append('INSUFFICIENT_RESAMPLES_FOR_TRIAL_COUNT')
    lower=None
    if not blockers or blockers==['DRAWDOWN_LIMIT']:
        rng=random.Random(seed);stats=[];nblocks=math.ceil(n/block_size)
        # Prefix sums make each block O(1). Truncate final block to exact n.
        prefix=[0.]
        for x in paired:prefix.append(prefix[-1]+x)
        for _ in range(resamples):
            total=0.;remaining=n
            for _ in range(nblocks):
                size=min(block_size,remaining);i=rng.randrange(n-size+1);total+=prefix[i+size]-prefix[i];remaining-=size
            stats.append(total/n)
        stats.sort();lower=stats[max(0,int(corrected*resamples)-1)]
        if lower<=0:blockers.append('NO_ROBUST_PAIRED_ADVANTAGE')
    result={'status':'REJECTED' if blockers else 'INDEPENDENT_REVIEW_REQUIRED','reasons':blockers,'n':n,'paired_mean_log_advantage':statistics.mean(paired),'lower_bootstrap_bound':lower,'corrected_tail_probability':corrected,'trial_count':trial_count,'block_size':block_size,'resamples':resamples,'seed':seed,'challenger_drawdown':dd,'holdout_hash':digest(locked_ids),'champion_hash':digest(champion),'challenger_hash':digest(challenger),'promotion_allowed':False,'can_trade':False,'limitations':['bootstrap conditional on weak stationarity and dependence assumptions','must independently verify all trial counts, locked holdout, costs and forward shadow outcomes; not alpha proof']}
    return result|{'review_id':digest(result)}
