"""Independent, read-only multi-account risk diagnostics. No broker margin simulation.
Inputs are operator-attested snapshots; never infer account completeness from NAV.
Options use conservative instantaneous intrinsic/upper bounds, not an options pricer.
"""
from __future__ import annotations
from .ledger import digest, iso
from .research import num


def _age(value, now, limit):
    if not 0 <= (now-iso(value)).total_seconds() <= limit:
        raise ValueError('stale or future snapshot')


def review_accounts(snapshot, *, expected_accounts, scenarios, limits, at):
    now=iso(at)
    _age(snapshot['as_of'],now,300)
    if snapshot.get('complete') is not True or snapshot.get('reconciled') is not True or not snapshot.get('evidence_ids'):
        raise ValueError('incomplete or untraceable portfolio')
    if not isinstance(expected_accounts,list) or not expected_accounts or len(set(expected_accounts))!=len(expected_accounts):
        raise ValueError('explicit account roster required')
    accounts=snapshot['accounts']; ids=[a['account_id'] for a in accounts]
    if len(set(ids))!=len(ids) or set(ids)!=set(expected_accounts):raise ValueError('account coverage mismatch')
    base=snapshot['base_currency']; rates={base:1.0}
    for cur,quote in snapshot['fx'].items():
        if cur==base or not quote.get('evidence_ids'):raise ValueError('invalid FX provenance')
        _age(quote['as_of'],now,300);rate=num(quote['rate_to_base'])
        if rate<=0:raise ValueError('invalid FX rate')
        rates[cur]=rate
    if len(scenarios)<3:raise ValueError('at least three stress scenarios')
    normalized=[]; exposures={};clusters={};gross=0.;net=0.;nav=0.;cash_total=0.;issues=[]
    for a in accounts:
        aid=a['account_id'];_age(a['as_of'],now,300)
        if not a.get('evidence_ids') or a['account_type'] not in ('cash','margin','registered'):raise ValueError('account type/provenance')
        equity=num(a['nav_base']); cash={c:num(v) for c,v in a['cash_by_currency'].items()}
        if equity<=0 or not cash:raise ValueError('invalid account balances')
        if any(c not in rates for c in cash):raise ValueError('missing cash FX')
        if a['account_type']!='margin' and any(v<0 for v in cash.values()):issues.append('BORROWING_IN_NON_MARGIN:'+aid)
        cv=sum(v*rates[c] for c,v in cash.items()); market=0.; seen=set(); positions=[]; agross=0.
        maint=num(a['maintenance_margin_base']); excess=num(a['excess_liquidity_base'])
        if maint<0 or (a['account_type']=='margin' and not a.get('margin_evidence_ids')):raise ValueError('margin observation required')
        if a['account_type']=='margin':
            _age(a['margin_as_of'],now,180)
            if excess<0:issues.append('NEGATIVE_EXCESS_LIQUIDITY:'+aid)
        for p in a['positions']:
            sid=p['security_id'];cur=p['currency'];q=num(p['quantity']);px=num(p['price']);mult=num(p.get('multiplier',1))
            if not sid or sid in seen or cur not in rates or px<0 or mult<=0 or not p.get('evidence_ids'):raise ValueError('invalid position')
            _age(p['price_asof'],now,90);seen.add(sid)
            if q<0 and a['account_type']!='margin':issues.append('SHORT_IN_NON_MARGIN:'+aid)
            typ=p['asset_type'];value=q*px*mult*rates[cur];market+=value
            if typ in ('equity','etf'):
                if px<=0 or mult!=1:raise ValueError('invalid equity price or multiplier')
                if typ=='etf':
                    # Operator-supplied exposure decomposition, NOT inferred from ticker.
                    factors=p['factor_exposure'];
                    if not factors or not p.get('factor_evidence_ids'):raise ValueError('ETF look-through required')
                    factor={k:num(v) for k,v in factors.items()}
                    if sum(abs(v) for v in factor.values())<=0:raise ValueError('invalid ETF factors')
                else:factor={sid:1.0}
                e={k:value*v for k,v in factor.items()}
            elif typ=='option':
                if p['right'] not in ('call','put') or p['style'] not in ('american','european') or not p.get('underlying_id') or not p.get('greek_evidence_ids'):
                    raise ValueError('option metadata required')
                _age(p['greeks_asof'],now,90);_age(p['underlying_asof'],now,90)
                spot=num(p['underlying_price']);strike=num(p['strike']);delta=num(p['delta'])
                if spot<=0 or strike<=0 or iso(p['expiry'])<=now or not (-1<=delta<=0 if p['right']=='put' else 0<=delta<=1):raise ValueError('option contract invalid')
                # Stress bounds assume nonnegative rates. Require explicit input, not a broker-implied rate.
                rate=num(p['risk_free_rate'])
                if not 0<=rate<=1 or not p.get('rate_evidence_ids'):raise ValueError('nonnegative rate assumption with evidence required')
                intrinsic=max(0,spot-strike) if p['right']=='call' else max(0,strike-spot)
                if px>(spot if p['right']=='call' else strike)+.01 or (p['style']=='american' and px+.01<intrinsic):raise ValueError('option mark outside bounds')
                e={p['underlying_id']:q*mult*spot*delta*rates[cur]}
            else:raise ValueError('unsupported instrument: '+str(typ))
            if not p.get('cluster_map') or not set(e).issubset(p['cluster_map']):raise ValueError('cluster decomposition required')
            for k,v in e.items():
                exposures[k]=exposures.get(k,0)+v
                cl=p['cluster_map'][k]
                if not isinstance(cl,str) or not cl:raise ValueError('invalid cluster')
                clusters[cl]=clusters.get(cl,0)+abs(v)
            agross+=sum(abs(v) for v in e.values());net+=sum(e.values());positions.append((p,q,px,mult,value))
        if abs(cv+market-equity)>max(.05,equity*1e-5):raise ValueError('account NAV reconciliation failure: '+aid)
        gross+=agross;nav+=equity;cash_total+=cv
        normalized.append((a,equity,cash,positions,agross,maint,excess))
    stresses={}
    for name,s in scenarios.items():
        price=s['price_shocks']; fx=s['fx_shocks']; mm=num(s['maintenance_multiplier'])
        if mm<1 or set(fx)!=(set(rates)-{base}):raise ValueError('incomplete FX/margin stress')
        sr={base:1.0}|{c:rates[c]*(1+num(x)) for c,x in fx.items()}
        if min(sr.values())<=0:raise ValueError('invalid FX shock')
        per={};sum_equity=0.
        for a,equity,cash,positions,agross,maint,excess in normalized:
            stressed=sum(v*sr[c] for c,v in cash.items())
            for p,q,px,mult,value in positions:
                key=p['underlying_id'] if p['asset_type']=='option' else p['security_id']
                shock=num(price[key]);
                if shock< -1:raise ValueError('impossible shock')
                if p['asset_type']=='option':
                    spot=num(p['underlying_price'])*(1+shock);strike=num(p['strike'])
                    # Conservative instantaneous bounds, deliberately ignore favorable time value.
                    # European long puts/calls may trade below intrinsic before expiry: use zero lower bound.
                    intrinsic=max(0,spot-strike) if p['right']=='call' else max(0,strike-spot)
                    new=(intrinsic if p['style']=='american' else 0.) if q>=0 else (spot if p['right']=='call' else strike)
                else:new=px*(1+shock)
                stressed+=q*new*mult*sr[p['currency']]
            # Diagnostic only: not a broker what-if; preserve the observed excess buffer
            # and apply loss plus explicit maintenance inflation without cross-account netting.
            buffer=excess+(stressed-equity)-maint*(mm-1) if a['account_type']=='margin' else None
            if buffer is not None and buffer<0:issues.append('STRESS_MARGIN_DEFICIT:'+a['account_id']+':'+name)
            if stressed<=0:issues.append('STRESS_INSOLVENCY:'+a['account_id']+':'+name)
            per[a['account_id']]={'stressed_nav_base':stressed,'estimated_excess_liquidity_base':buffer,'loss_base':equity-stressed}
            sum_equity+=stressed
        stresses[name]={'nav_base':sum_equity,'loss_fraction':max(0,1-sum_equity/nav),'accounts':per}
    # Net exposure is not a substitute for gross exposure. Single name uses gross
    # absolute look-through contributions to avoid cancellation across accounts.
    singles={}
    for a,eq,cash,positions,agross,maint,excess in normalized:
        for p,q,px,mult,value in positions:
            if p['asset_type']=='option':e={p['underlying_id']:q*mult*num(p['underlying_price'])*num(p['delta'])*rates[p['currency']]}
            elif p['asset_type']=='etf':e={k:value*num(v) for k,v in p['factor_exposure'].items()}
            else:e={p['security_id']:value}
            for k,v in e.items():singles[k]=singles.get(k,0)+abs(v)
    metrics={'gross_economic_leverage':gross/nav,'net_economic_leverage':net/nav,'cash_weight':cash_total/nav,
             'single_gross_weight':max(singles.values(),default=0)/nav,'cluster_gross_weight':max(clusters.values(),default=0)/nav,
             'worst_stress_loss':max(x['loss_fraction'] for x in stresses.values())}
    for field,key in [('gross_economic_leverage','max_gross_economic_leverage'),('single_gross_weight','max_single_stock_weight'),('cluster_gross_weight','max_correlated_cluster_weight'),('worst_stress_loss','max_stress_loss')]:
        bound=num(limits[key]);
        if bound<0:raise ValueError('invalid risk limit')
        if metrics[field]>bound:issues.append('LIMIT:'+key)
    net_bound=num(limits['max_economic_leverage']);floor=num(limits['min_cash_reserve_weight'])
    if net_bound<0 or not 0<=floor<=1:raise ValueError('invalid leverage/cash limits')
    if abs(metrics['net_economic_leverage'])>net_bound:issues.append('LIMIT:max_economic_leverage')
    if metrics['cash_weight']<floor:issues.append('LIMIT:min_cash_reserve_weight')
    report={'status':'BLOCK' if issues else 'DIAGNOSTIC_ONLY','metrics':metrics,'nav_base':nav,'base_currency':base,'signed_exposures_base':exposures,'gross_exposures_base':singles,'stress':stresses,'reasons':sorted(set(issues)),
        'snapshot_hash':digest(snapshot),'limits_hash':digest(limits),'scenario_hash':digest(scenarios),'as_of':now.isoformat(),'can_trade':False,'broker_margin_verified':False,
        'limitations':['operator-attested snapshot and ETF decomposition; not independently authenticated','instantaneous option bounds conditional on nonnegative rates and supplied shocks, not expected option prices','stress buffer is an approximation; IBKR what-if and account permissions still required','delta exposure omits changing Greeks; ETF exposures vary; no cross-account collateral netting']}
    return report|{'risk_id':digest(report)}
