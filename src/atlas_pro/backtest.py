"""Explicit, narrow next-period portfolio replay for precomputed PIT selections.
Not a security master, broker simulator, or a claim of alpha. Refuse gaps.
"""
from __future__ import annotations
from .ledger import iso
from .research import num
import math


def replay_periods(periods,*,initial_nav=1.0,cost_bps=10.0):
    """Long-only fully invested unlevered targets + explicit CASH; total-return bars.
    Each period is non-overlapping. Targets are frozen before executable start;
    costs are charged on gross traded notional. Delisting returns required.
    User supplies the verified historical universe and corporate-action-aware returns.
    """
    initial_nav=num(initial_nav); wealth=benchmark=initial_nav; costs=num(cost_bps)/10000
    if wealth<=0 or not 0<=costs<=.1 or not periods:raise ValueError('invalid backtest settings')
    previous_weights={'CASH':1.0}; peak=wealth; mdd=0; previous_end=None; rows=[]
    for p in periods:
        signal,start,end=(iso(p[k]) for k in ('signal_at','start_at','end_at'))
        if not signal<start<end or (previous_end is not None and start!=previous_end):raise ValueError('temporal leakage, overlap or gap')
        if p.get('historical_universe_verified') is not True or p.get('corporate_actions_verified') is not True or not p.get('universe_evidence_id'):
            raise ValueError('universe or corporate action evidence missing')
        if not p.get('signal_evidence_available_at') or any(iso(t)>signal for t in p['signal_evidence_available_at']):raise ValueError('future signal evidence')
        weights={k:num(v) for k,v in p['weights'].items()}; returns={k:num(v) for k,v in p['total_returns'].items()}
        if any(v<0 for v in weights.values()) or abs(sum(weights.values())-1)>1e-8 or not set(weights).issubset(returns):raise ValueError('invalid weights or missing returns')
        if any(v< -1 for v in returns.values()):raise ValueError('impossible unlevered return')
        turnover=sum(abs(weights.get(k,0)-previous_weights.get(k,0)) for k in set(weights)|set(previous_weights) if k!='CASH')
        fee=wealth*turnover*costs; net_start=wealth-fee
        if net_start<=0:raise ValueError('portfolio insolvent')
        gross_return=sum(v*returns[k] for k,v in weights.items()); wealth=net_start*(1+gross_return)
        b=num(p['benchmark_total_return'])
        if b< -1:raise ValueError('invalid benchmark return')
        benchmark*=1+b; peak=max(peak,wealth);mdd=min(mdd,wealth/peak-1)
        if wealth<=0:previous_weights={'CASH':1.0}
        else:previous_weights={k:v*(1+returns[k])/(1+gross_return) for k,v in weights.items()}
        rows.append({'start_at':start.isoformat(),'end_at':end.isoformat(),'nav':wealth,'benchmark_nav':benchmark,'turnover':turnover,'fee':fee})
        previous_end=end
        if wealth<=0:break
    return {'status':'CONDITIONAL_REPLAY','rows':rows,'total_return':wealth/initial_nav-1,'benchmark_return':benchmark/initial_nav-1,'max_drawdown_at_period_boundaries':mdd,'total_cost':sum(r['fee'] for r in rows),'can_trade':False,
        'limitations':['period-end drawdown only','input coverage and PIT timestamps not independently verified','no spreads, intraperiod trading, taxes, leverage or capacity unless separately modeled','not sample-out alpha proof']}
