"""Independent long-only cash-equity shadow risk, inspired by skfolio/CVaR.
No brokerage, margin, options, price discovery, or execution authority.
Inputs must come from the separately authenticated local data operator.
"""
from __future__ import annotations
import math
from .ledger import digest, iso
from .research import num


def tail_loss(returns, alpha=.95):
    """Empirical expected shortfall with fractional boundary mass, positive loss."""
    a=num(alpha); xs=sorted(-num(r) for r in returns)[::-1]
    if not 0<a<1 or not xs: raise ValueError('tail inputs')
    mass=(1-a)*len(xs); whole=int(mass)
    return sum(xs)/len(xs) if whole>=len(xs) else (sum(xs[:whole])+(mass-whole)*xs[whole])/mass


def portfolio_review(snapshot, targets, returns, clusters, limits, *, at, stress_scenarios, alpha=.95):
    """Recalculate from position quantities/prices and target weights; not supplied risk flags.
    Same-currency, unlevered cash equity only. Historical returns must be aligned,
    point-in-time and total returns. Empirical CVaR is not a maximum loss bound.
    """
    now=iso(at); stamp=iso(snapshot['as_of']); age=(now-stamp).total_seconds()
    if not 0<=age<=300 or snapshot.get('complete') is not True or snapshot.get('reconciled') is not True:
        raise ValueError('unqualified snapshot')
    if snapshot.get('currency')!='USD' or snapshot.get('account_type')!='cash' or not snapshot.get('evidence_ids'):
        raise ValueError('only reconciled USD cash shadow account')
    cash=num(snapshot['cash']); nav=num(snapshot['nav']); values={}
    if cash<0 or nav<=0: raise ValueError('unsupported account balance')
    for p in snapshot['positions']:
        s=p['security_id']; q=num(p['quantity']); price=num(p['price'])
        if not s or s=='CASH' or s in values or q<0 or price<=0 or p.get('asset_type')!='common_equity' or p.get('unlevered') is not True:
            raise ValueError('unsupported or duplicate position')
        if not 0<=(now-iso(p['price_asof'])).total_seconds()<=90 or not p.get('evidence_ids'):
            raise ValueError('stale position quote')
        values[s]=q*price
    if abs(cash+sum(values.values())-nav)>max(.01,nav*1e-6):raise ValueError('NAV reconciliation failure')
    weights={s:num(w) for s,w in targets.items()}
    if 'CASH' not in weights or any(w<0 for w in weights.values()) or abs(sum(weights.values())-1)>1e-8:raise ValueError('invalid target weights')
    names={s for s in weights if s!='CASH' and weights[s]>0}
    if any(s not in clusters or not clusters[s] for s in names):raise ValueError('missing cluster classification')
    group={}
    for s in names:group[clusters[s]]=group.get(clusters[s],0)+weights[s]
    prev={s:v/nav for s,v in values.items()}|{'CASH':cash/nav}
    turnover=sum(abs(weights.get(s,0)-prev.get(s,0)) for s in set(weights)|set(prev) if s!='CASH')
    if len(returns)<100:raise ValueError('insufficient aligned historical observations')
    last=None; series=[]
    for r in returns:
        dt=iso(r['at']); available=iso(r['available_at'])
        if dt>available or available>now or (last is not None and dt<=last) or not r.get('evidence_ids'):
            raise ValueError('future, unordered or untraceable return')
        last=dt
        if not names.issubset(r['returns']) or 'CASH' not in r['returns']:raise ValueError('missing aligned return')
        vals={s:num(r['returns'][s]) for s in names|{'CASH'}}
        if min(vals.values())< -1:raise ValueError('invalid unlevered return')
        series.append(sum(weights[s]*v for s,v in vals.items()))
    stress={}
    if len(stress_scenarios)<3:raise ValueError('at least three stress scenarios required')
    for scenario,shock in stress_scenarios.items():
        if not names.issubset(shock) or 'CASH' not in shock:raise ValueError('incomplete stress')
        vals={s:num(shock[s]) for s in names|{'CASH'}}
        if min(vals.values())< -1:raise ValueError('impossible shock')
        stress[scenario]=sum(weights[s]*v for s,v in vals.items())
    metrics={'single':max((weights[s] for s in names),default=0),'cluster':max(group.values(),default=0),
             'cash':weights['CASH'],'gross':1-weights['CASH'],'turnover':turnover,'cvar':max(0,tail_loss(series,alpha)),
             'worst_stress_loss':max(0,-min(stress.values()))}
    checks={'single':'max_single_stock_weight','cluster':'max_correlated_cluster_weight','gross':'max_gross_economic_leverage',
            'turnover':'max_turnover','cvar':'max_cvar','worst_stress_loss':'max_stress_loss'}
    reasons=[]
    for field,key in checks.items():
        bound=num(limits[key])
        if bound<0:raise ValueError('invalid risk limit')
        if metrics[field]>bound+1e-10:reasons.append(key)
    floor=num(limits['min_cash_reserve_weight']); economic=num(limits['max_economic_leverage'])
    if not 0<=floor<=1 or economic<0:raise ValueError('invalid cash or leverage bound')
    if metrics['cash']+1e-10<floor:reasons.append('min_cash_reserve_weight')
    if metrics['gross']>economic+1e-10:reasons.append('max_economic_leverage')
    result={'status':'BLOCK' if reasons else 'SHADOW_RISK_REVIEW','metrics':metrics,'stress':stress,'reasons':sorted(reasons),
            'snapshot_hash':digest(snapshot),'target_hash':digest(weights),'return_data_hash':digest(returns),'limits_hash':digest(limits),
            'stress_hash':digest(stress_scenarios),'as_of':now.isoformat(),'observations':len(series),'alpha':alpha,'can_trade':False,
            'limitations':['cash equity only; not a broker margin model','source authenticity and coverage require independent operator verification','scenario and empirical CVaR do not guarantee drawdown']}
    return result|{'risk_id':digest(result)}
