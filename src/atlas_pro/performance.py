"""Independent daily performance and opportunity-cost attribution.
QuantStats-inspired, deterministic, no network or automatic data fetching.
Inputs must be total returns net of costs and already adjusted for cash flows.
"""
from __future__ import annotations
import math, statistics
from .ledger import iso,digest
from .research import num


def paired_performance(rows, *, expected_sessions, annual_periods=252, risk_free_annual=0.0):
    if not rows or len(rows)!=len(expected_sessions) or len(set(expected_sessions))!=len(expected_sessions) or not 1<=annual_periods<=366:
        raise ValueError('incomplete or invalid session coverage')
    rf=num(risk_free_annual)
    if rf<=-1:raise ValueError('risk free rate invalid')
    daily_rf=(1+rf)**(1/annual_periods)-1
    ps=[];bs=[];peaks=wealth=bwealth=1.;maxdd=0.; previous=None; path=[]
    for row,stamp in zip(rows,expected_sessions):
        t=iso(row['at']); expected=iso(stamp)
        if t!=expected or (previous and t<=previous) or not row.get('evidence_ids') or row.get('cash_flow_adjusted') is not True or row.get('net_of_costs') is not True:raise ValueError('invalid session or unqualified returns')
        p,b=num(row['net_return']),num(row['benchmark_total_return'])
        if min(p,b)<-1:raise ValueError('invalid return')
        wealth*=1+p;bwealth*=1+b
        if not math.isfinite(wealth+bwealth):raise ValueError('nonfinite wealth')
        peaks=max(peaks,wealth);maxdd=max(maxdd,1-wealth/peaks);previous=t
        ps.append(p);bs.append(b);path.append({'at':t.isoformat(),'nav_index':wealth,'benchmark_index':bwealth,'drawdown':wealth/peaks-1})
    n=len(ps);excess=[p-b for p,b in zip(ps,bs)];vol=statistics.stdev(ps) if n>1 else 0;te=statistics.stdev(excess) if n>1 else 0
    return {'status':'CONDITIONAL_PERFORMANCE','n':n,'net_total_return':wealth-1,'benchmark_total_return':bwealth-1,
            'relative_wealth_return':wealth/bwealth-1 if bwealth>0 else None,'max_drawdown':maxdd,
            'annualized_volatility':vol*math.sqrt(annual_periods) if n>1 else None,'annualized_sharpe':(statistics.mean(ps)-daily_rf)/vol*math.sqrt(annual_periods) if vol>0 else None,
            'annualized_tracking_error':te*math.sqrt(annual_periods) if n>1 else None,'information_ratio':statistics.mean(excess)/te*math.sqrt(annual_periods) if te>0 else None,
            'annualized_return':wealth**(annual_periods/n)-1 if n>=annual_periods else None,
            'path':path,'input_hash':digest(rows),'can_trade':False,'limitations':['conditional on independently verified daily total returns, fees, cash flows and complete exchange calendar','not a significance test or evidence of alpha']}
