"""Optional SciPy HiGHS long-only CVaR linear program (skfolio-inspired).
Never sends orders. Independently review rounded weights before using them.
"""
from __future__ import annotations
from .research import num
from .ledger import digest


def minimum_cvar(samples,*,limits,clusters,expected_return_floor,alpha=.95):
    """Equal-weight scenarios, explicit cash return, no shorting/leverage.
    Empirical tail risk is horizon-specific; the mean floor is an assumption.
    Requires optional scipy, never silently changes solver or relaxes constraints.
    """
    import numpy as np
    from scipy.optimize import linprog
    a=num(alpha); floor=num(expected_return_floor)
    if not 0<a<1 or not 100<=len(samples)<=2000:raise ValueError('insufficient scenarios or invalid alpha')
    names=sorted(samples[0]); n=len(names); m=len(samples)
    if 'CASH' not in names or n>100 or any(set(s)!=set(names) for s in samples):raise ValueError('misaligned scenarios')
    R=np.array([[num(s[k]) for k in names] for s in samples]);
    if np.min(R)<-1:raise ValueError('invalid unlevered return')
    cash=names.index('CASH'); cap=num(limits['max_single_stock_weight']); cash_floor=num(limits['min_cash_reserve_weight']); cluster_cap=num(limits['max_correlated_cluster_weight'])
    gross_cap=min(num(limits['max_gross_economic_leverage']),num(limits['max_economic_leverage']))
    if not all(0<=x<=1 for x in (cap,cash_floor,cluster_cap)) or gross_cap<0:raise ValueError('invalid constraints')
    if any(k not in clusters or not clusters[k] for k in names if k!='CASH'):raise ValueError('missing cluster')
    # variables: weights, VaR threshold (free), nonnegative excess losses.
    c=np.r_[np.zeros(n),1,np.full(m,1/((1-a)*m))]
    A=np.c_[-R,-np.ones(m),-np.eye(m)]; b=np.zeros(m)
    extra=[np.r_[-R.mean(axis=0),np.zeros(m+1)]]; bounds_rhs=[-floor]
    for group in sorted(set(clusters[k] for k in names if k!='CASH')):
        extra.append(np.r_[[float(k!='CASH' and clusters.get(k)==group) for k in names],np.zeros(m+1)]);bounds_rhs.append(cluster_cap)
    extra.append(np.r_[[float(k!='CASH') for k in names],np.zeros(m+1)]);bounds_rhs.append(gross_cap)
    bounds=[(cash_floor,1) if i==cash else (0,cap) for i in range(n)]+[(None,None)]+[(0,None)]*m
    r=linprog(c,A_ub=np.vstack([A,*extra]),b_ub=np.r_[b,bounds_rhs],A_eq=np.array([np.r_[np.ones(n),np.zeros(m+1)]]),b_eq=[1],bounds=bounds,method='highs')
    if not r.success:return {'status':'NO_FEASIBLE_SOLUTION','solver_status':int(r.status),'can_trade':False}
    weights={k:float(r.x[i]) for i,k in enumerate(names)}
    return {'status':'RESEARCH_CANDIDATE','weights':weights,'sample_cvar':float(r.fun),'sample_mean':float(R.mean(axis=0)@r.x[:n]),'sample_hash':digest(samples),'can_trade':False,'requires_independent_risk_review':True}
