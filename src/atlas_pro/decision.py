"""Integrated valuation decision grid. Outputs research readiness, not orders.
Only independent risk review and authenticated approvals can advance beyond research.
"""
from __future__ import annotations
from .research import dcf,reverse_dcf,scenario_grid,num
from .ledger import iso,digest


def decision_grid(*, candidate, assumptions, terminal_scenarios, quote_price, benchmark_return, at, horizon_days=365, cost_fraction=0.0):
    """Distinguish intrinsic value today, hypothetical future price, and uncertainty.
    Probabilities are not certified by this function. No exact Kelly sizing or trade.
    All DCF inputs are explicit assumptions, not historical reported facts.
    """
    cutoff=iso(at)
    if candidate.get('status')!='CANDIDATE' or candidate.get('can_trade') is not False or not candidate.get('fundamental_evidence_ids') or not candidate.get('market_evidence_ids'):
        return {'status':'INSUFFICIENT_RESEARCH','decision':'WAIT','can_trade':False}
    if not 1<=horizon_days<=3650 or type(horizon_days) is not int:raise ValueError('horizon bounds')
    quote_price=num(quote_price)
    if quote_price<=0 or set(assumptions)!={'bear','base','bull'}:raise ValueError('invalid decision inputs')
    if candidate.get('price') is not None and abs(num(candidate['price'])-quote_price)>max(1e-8,quote_price*1e-8):raise ValueError('candidate quote mismatch')
    if any(iso(candidate[k])>cutoff for k in ('available_at','decision_at','price_asof') if k in candidate):raise ValueError('future candidate')
    vals={k:dcf(**assumptions[k]) for k in ('bear','base','bull')}
    ordered=[vals[k]['value_per_share'] for k in ('bear','base','bull')]
    if ordered!=sorted(ordered):raise ValueError('DCF scenarios not economically ordered')
    rev=reverse_dcf(quote_price,assumptions['base'])
    scenario=scenario_grid(terminal_scenarios,price=quote_price,benchmark_return=benchmark_return,cost_fraction=cost_fraction,probabilities_validated=False)
    base=assumptions['base']; sensitivity=[]
    for dw in (-.01,0,.01):
        row=[]
        for dg in (-.005,0,.005):
            try:row.append(dcf(**(base|{'wacc':num(base['wacc'])+dw,'terminal_growth':num(base['terminal_growth'])+dg}))['value_per_share'])
            except ValueError:row.append(None)
        sensitivity.append(row)
    result={'status':'RESEARCH_GRID','decision':'WAIT','reason':'unvalidated future probabilities and full portfolio risk review required',
        'symbol':candidate['symbol'],'decision_at':cutoff.isoformat(),'horizon_days':horizon_days,'price':quote_price,
        'fair_values_today':{k:v['value_per_share'] for k,v in vals.items()},'valuation_schedules':vals,
        'base_margin_of_safety':1-quote_price/ordered[1] if ordered[1]>0 else None,
        'base_upside_to_intrinsic_value':ordered[1]/quote_price-1,'reverse_dcf':rev,
        'sensitivity':{'wacc_offsets':[-.01,0,.01],'terminal_growth_offsets':[-.005,0,.005],'values':sensitivity},
        'future_scenarios':scenario,'fundamental_evidence_ids':candidate['fundamental_evidence_ids'],'market_evidence_ids':candidate['market_evidence_ids'],
        'assumptions_hash':digest(assumptions),'can_trade':False,'position_size':None,
        'limitations':['scenario probabilities supplied by researcher and not validated','DCF value today is not a 12-month price target','peer comps, SBC/dilution, portfolio correlation, FX, taxes and liquidity require independent review']}
    result['decision_id']=digest(result)
    return result
