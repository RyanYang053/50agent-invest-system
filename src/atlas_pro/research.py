"""PIT stock screening and scenario research. No orders or automatic price targets."""
from __future__ import annotations
from datetime import date, timedelta, datetime, timezone
from decimal import Decimal, InvalidOperation
import math
from .ledger import iso, digest


def num(v):
    if isinstance(v, bool):
        raise ValueError('boolean is not a financial number')
    try:
        n = float(v)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError('missing or invalid number') from exc
    if not math.isfinite(n):
        raise ValueError('nonfinite number')
    return n


# Deliberately restrict initial coverage to US GAAP industrial/operating issuers.
TAGS = {
    'revenue': ('RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet'),
    'operating_income': ('OperatingIncomeLoss',),
    'ocf': ('NetCashProvidedByUsedInOperatingActivities',),
    'capex': ('PaymentsToAcquirePropertyPlantAndEquipment',),
    'net_income': ('NetIncomeLoss',),
    'equity': ('StockholdersEquity',),
    'assets': ('Assets',),
    'cash': ('CashAndCashEquivalentsAtCarryingValue',),
    'long_debt': ('LongTermDebtNoncurrent',),
    'current_debt': ('LongTermDebtCurrent',),
}
FLOWS = {'revenue','operating_income','ocf','capex','net_income'}


def sec_annual_facts(companyfacts, submissions, *, at, received_at, replay=False):
    """Only annual facts from 10-K/10-K/A; join exact accession acceptance timestamp.

    Live availability is max(acceptance, actual receipt). Historical replay uses
    acceptance as proxy (not an independently proven historical feed capture).
    Current-only submissions can omit old accessions: skip, never infer timestamps.
    Does not claim historical universe completeness or normalize foreign issuers.
    """
    cutoff, received = iso(at), iso(received_at)
    if not replay and received > cutoff:
        raise ValueError('received after decision cutoff')
    if replay not in (True, False) or type(replay) is not bool:
        raise ValueError('invalid replay mode')
    cik = int(companyfacts['cik'])
    if cik != int(submissions['cik']) or cik <= 0:
        raise ValueError('CIK mismatch')
    recent = submissions['filings']['recent']
    accessions, times = recent['accessionNumber'], recent['acceptanceDateTime']
    if len(accessions) != len(times):
        raise ValueError('SEC submissions arrays mismatch')
    accepts = {}
    for acc, stamp in zip(accessions, times):
        try:
            dt = iso(stamp)
        except (ValueError, TypeError, AttributeError):
            continue
        if acc in accepts and accepts[acc] != dt:
            raise ValueError('conflicting accession timestamp')
        accepts[acc] = dt
    taxonomy = companyfacts.get('facts', {}).get('us-gaap', {})
    rows = []
    for field, aliases in TAGS.items():
        for priority, tag in enumerate(aliases):
            for fact in taxonomy.get(tag, {}).get('units', {}).get('USD', []):
                if fact.get('form') not in ('10-K', '10-K/A'):
                    continue
                accepted = accepts.get(fact.get('accn'))
                if accepted is None:
                    continue
                available = accepted if replay else max(accepted, received)
                if available > cutoff:
                    continue
                try:
                    end = date.fromisoformat(fact['end'])
                    if end > accepted.date():
                        continue
                    start = date.fromisoformat(fact['start']) if 'start' in fact else None
                    if field in FLOWS and (start is None or not 330 <= (end-start).days <= 380):
                        continue
                    if field not in FLOWS and start is not None:
                        continue
                    v = num(fact['val'])
                except (KeyError, TypeError, ValueError):
                    continue
                rows.append({'cik':cik,'field':field,'tag':tag,'priority':priority,'value':v,
                    'unit':'USD','start':start.isoformat() if start else None,'end':end.isoformat(),
                    'accession':fact['accn'],'published_at':accepted.isoformat(),
                    'available_at':available.isoformat(),'replay_availability_proxy':replay})
    # conflicting duplicates for one tag/period/accession are not a reliable fact.
    by_key = {}
    for row in rows:
        key = (row['field'], row['tag'], row['start'], row['end'], row['accession'])
        by_key.setdefault(key, []).append(row)
    result = [group[0] for group in by_key.values() if len({r['value'] for r in group}) == 1]
    return sorted(result, key=lambda r:(r['end'],r['field'],r['available_at'],r['tag'],r['accession']))


def annual_snapshot(rows, *, at, max_age_days=550):
    """Prefer most recent available accession for each period; same FY length for flows.
    Missing fields are not filled with zero. Restatements only as of cutoff.
    """
    cutoff = iso(at)
    rows = [r for r in rows if iso(r['available_at']) <= cutoff]
    if not rows:
        return None
    if len({r['cik'] for r in rows}) != 1:
        raise ValueError('mixed CIKs')
    periods = sorted({r['end'] for r in rows if r['field']=='revenue'}, reverse=True)
    if not periods:
        return None
    end = periods[0]
    if not 0 <= (cutoff.date()-date.fromisoformat(end)).days <= max_age_days:
        return None
    values, sources = {}, {}
    def select(field, period, start=None):
        options = [r for r in rows if r['field']==field and r['end']==period and (field not in FLOWS or start is None or r['start']==start)]
        if not options:
            return None
        options.sort(key=lambda r:(r['available_at'], -r['priority'], r['accession']), reverse=True)
        best = options[0]
        same = [x for x in options if (x['available_at'],x['priority'],x['accession']) == (best['available_at'],best['priority'],best['accession'])]
        if len({(x['value'],x['start']) for x in same}) != 1:
            return None
        return best
    anchor = select('revenue',end)
    if anchor is None:
        return None
    for field in TAGS:
        chosen = select(field,end,anchor['start'])
        if chosen:
            values[field]=chosen['value']; sources[field]=chosen
    prev = next((p for p in periods[1:] if 330 <= (date.fromisoformat(end)-date.fromisoformat(p)).days <= 400),None)
    if prev:
        old=select('revenue',prev)
        if old and old['value']>0:
            values['revenue_growth']=values['revenue']/old['value']-1
            sources['prior_revenue']=old
    return {'cik':anchor['cik'],'period_end':end,'metrics':values,'sources':sources,'as_of':cutoff.isoformat(),'basis':'annual_us_gaap_usd_not_ttm'}


def _clip(x,lo=0,hi=1):
    return max(lo,min(hi,x))


def screen(snapshot, market, *, at):
    """Transparent heuristic triage; absolute score, not probability or alpha.
    Market inputs are operator/adapter supplied, timestamped, explicitly scoped.
    No assumptions about missing data, no buy recommendation from screen alone.
    """
    cutoff=iso(at)
    excluded=lambda *r:{'status':'INSUFFICIENT_DATA','reasons':list(r),'action':'RESEARCH_ONLY','can_trade':False}
    if not snapshot or not market:
        return excluded('missing financial or market snapshot')
    if market.get('currency')!='USD' or market.get('security_type')!='common_equity' or market.get('sector_class')!='operating_company':
        return excluded('unsupported instrument or valuation method')
    try:
        if int(market['cik'])!=snapshot['cik'] or iso(snapshot['as_of'])>cutoff:
            return excluded('entity or financial cutoff mismatch')
        if not 0 <= (cutoff.date()-date.fromisoformat(snapshot['period_end'])).days <= 550:
            return excluded('stale annual financials')
        if not snapshot['sources'] or any(iso(x['available_at'])>cutoff for x in snapshot['sources'].values()):
            return excluded('future or missing fundamental evidence')
        for key in ('price_asof','shares_asof','available_at'):
            dt=iso(market[key]); age=(cutoff-dt).total_seconds()
            if age<0 or (key=='price_asof' and age>7*86400) or (key=='shares_asof' and age>180*86400):
                return excluded('stale or future market input: '+key)
        if iso(market['available_at']) < max(iso(market['price_asof']),iso(market['shares_asof'])):
            return excluded('market availability precedes observation')
        if not market.get('evidence_ids') or market.get('qualified_research_data') is not True:
            return excluded('market provenance/entitlement unverified')
        m=snapshot['metrics']; rev,op,ocf,capex,ni,eq,assets,cash,debt,cur,growth=(num(m[k]) for k in ('revenue','operating_income','ocf','capex','net_income','equity','assets','cash','long_debt','current_debt','revenue_growth'))
        price,shares=num(market['price']),num(market['shares'])
        if min(rev,eq,assets,price,shares)<=0 or min(capex,cash,debt,cur)<0:
            return excluded('unsupported financial signs or incomplete balance sheet')
        if eq>assets or cash>assets or debt+cur>assets:
            return excluded('balance sheet consistency failure')
    except (KeyError,TypeError,ValueError,OverflowError):
        return excluded('incomplete or nonfinite required metrics')
    fcf=ocf-capex; market_cap=price*shares
    if not math.isfinite(market_cap) or market_cap<=0:
        return excluded('invalid market capitalization')
    net_debt=debt+cur-cash
    # Proxies, not ROIC, and not sector-neutral. Thresholds are candidate heuristics.
    profitability=_clip((op/rev)/.25); cash_quality=_clip((fcf/rev)/.20)
    return_on_equity=_clip((ni/eq)/.25); growth_score=_clip((growth+.10)/.35)
    valuation=_clip((fcf/market_cap)/.08); leverage=_clip(1-(debt+cur)/assets/.65)
    components={'profitability':profitability,'cash_quality':cash_quality,'roe':return_on_equity,'growth':growth_score,'fcf_yield':valuation,'balance_sheet':leverage}
    weights={'profitability':.20,'cash_quality':.20,'roe':.10,'growth':.15,'fcf_yield':.25,'balance_sheet':.10}
    score=100*sum(weights[k]*v for k,v in components.items())
    return {'status':'CANDIDATE','cik':snapshot['cik'],'symbol':market['symbol'],'score':round(score,4),
        'components':components,'metrics':{'operating_margin':op/rev,'fcf_margin':fcf/rev,'roe':ni/eq,'revenue_growth':growth,'fcf_yield':fcf/market_cap,'net_debt':net_debt},
        'price':price,'price_asof':iso(market['price_asof']).isoformat(),'available_at':iso(market['available_at']).isoformat(),'price_basis':market.get('price_basis','unspecified'),'financial_period':snapshot['period_end'],
        'fundamental_evidence_ids':[digest(v) for v in snapshot['sources'].values()],
        'market_evidence_ids':market['evidence_ids'],'action':'RESEARCH_ONLY','can_trade':False,
        'limitations':['annual US GAAP; no TTM or sector normalization','heuristic weights not validated for alpha','no full debt/lease or dilution adjustment; not a buy signal']}


def dcf(*, revenue, growth, margin, tax, da_rate, capex_rate, nwc_rate, wacc, terminal_growth, net_debt, diluted_shares):
    """FCFF with year-specific assumptions and normalized terminal FCFF."""
    revenue,tax,wacc,terminal_growth,net_debt,diluted_shares=map(num,(revenue,tax,wacc,terminal_growth,net_debt,diluted_shares))
    arrays=[list(map(num, xs)) for xs in (growth,margin,da_rate,capex_rate,nwc_rate)]
    n=len(arrays[0]); g,m,da,cap,nwc=arrays
    if not 3<=n<=15 or any(len(x)!=n for x in arrays):raise ValueError('forecast lengths')
    if revenue<=0 or diluted_shares<=0 or not 0<=tax<1 or not 0<wacc<=1 or not -0.05<=terminal_growth<wacc or wacc-terminal_growth<.005:raise ValueError('DCF bounds')
    if any(x<=-1 or x>2 for x in g) or any(not -1<=x<=1 for x in m) or any(not 0<=x<=1 for x in da+cap) or any(not -1<=x<=1 for x in nwc):raise ValueError('driver bounds')
    def cashflow(prev,rate,om,dar,cr,nr):
        r=prev*(1+rate); ebit=r*om; nopat=ebit-max(ebit,0)*tax
        return r,nopat+r*dar-r*cr-(r-prev)*nr
    pv=0; schedule=[]
    for t in range(n):
        revenue,fcff=cashflow(revenue,g[t],m[t],da[t],cap[t],nwc[t]); discounted=fcff/(1+wacc)**(t+1);pv+=discounted
        schedule.append({'year':t+1,'revenue':revenue,'fcff':fcff,'pv_fcff':discounted})
    _,terminal_fcff=cashflow(revenue,terminal_growth,m[-1],da[-1],cap[-1],nwc[-1])
    if terminal_fcff<=0:raise ValueError('terminal cash flow must be positive; use alternate methodology')
    tv=terminal_fcff/(wacc-terminal_growth)/(1+wacc)**n; ev=pv+tv
    if not all(map(math.isfinite,(ev,tv,pv))) or ev<=0:raise ValueError('unsupported enterprise value')
    equity=ev-net_debt
    return {'schedule':schedule,'enterprise_value':ev,'equity_value':equity,'value_per_share':max(0,equity/diluted_shares),
        'terminal_value_share':tv/ev,'warnings':['TERMINAL_VALUE_DOMINATES'] if tv/ev>.8 else [],'method':'FCFF_DCF_v1','can_trade':False}


def reverse_dcf(target_price, assumptions, *, low=-.2, high=1.0):
    """Solve constant forecast growth conditional on other assumptions, not a forecast."""
    target_price,low,high=map(num,(target_price,low,high))
    if target_price<=0 or low>=high:raise ValueError('invalid reverse target')
    n=len(assumptions['growth'])
    def f(g):return dcf(**(assumptions|{'growth':[g]*n}))['value_per_share']-target_price
    # Require monotonicity on a coarse grid, otherwise withhold solution.
    grid=[low+(high-low)*i/20 for i in range(21)]
    fs=[f(x) for x in grid]
    if any(b<a-1e-8 for a,b in zip(fs,fs[1:])) or fs[0]>0 or fs[-1]<0:
        return {'status':'UNBRACKETED_OR_NONMONOTONIC','implied_growth':None}
    for _ in range(80):
        mid=(low+high)/2
        if f(mid)>0:high=mid
        else:low=mid
    root=(low+high)/2
    return {'status':'SOLVED','implied_growth':root,'residual':f(root),'conditional_on_other_assumptions':True}


def scenario_grid(scenarios, *, price, benchmark_return, cost_fraction=0, probabilities_validated=False, max_fraction=.15):
    """Research-only finite-horizon outcomes. Do not derive probabilities from DCF.
    If probabilities not validated, no Kelly sizing. Returns are net of user costs.
    """
    price,benchmark_return,cost_fraction,max_fraction=map(num,(price,benchmark_return,cost_fraction,max_fraction))
    if price<=0 or not -1<=benchmark_return or not 0<=cost_fraction<1 or not 0<=max_fraction<1:raise ValueError('invalid scenario inputs')
    if set(scenarios)!={'bear','base','bull'}:raise ValueError('three named scenarios required')
    p=[num(scenarios[k]['probability']) for k in ('bear','base','bull')]
    targets=[num(scenarios[k]['terminal_price']) for k in ('bear','base','bull')]
    if any(x<0 for x in p+targets) or abs(sum(p)-1)>1e-8 or targets!=sorted(targets):raise ValueError('invalid probability or price ordering')
    r=[t/price-1-cost_fraction for t in targets]
    exp=sum(pi*ri for pi,ri in zip(p,r)); excess=exp-benchmark_return
    # Long-only single-asset log optimum, cap below insolvency; not total portfolio sizing.
    upper=min(max_fraction, min((-.999999/x for x in r if x<0),default=max_fraction))
    def derivative(f):return sum(pi*ri/(1+f*ri) for pi,ri in zip(p,r))
    kelly=None
    if probabilities_validated is True:
        lo,hi=0,upper
        if derivative(0)<=0:kelly=0.0
        elif derivative(hi)>=0:kelly=hi
        else:
            for _ in range(70):
                mid=(lo+hi)/2
                if derivative(mid)>0:lo=mid
                else:hi=mid
            kelly=(lo+hi)/2
    return {'status':'RESEARCH_ONLY','scenarios':[{ 'name':k,'probability':pi,'terminal_price':t,'return':ri} for k,pi,t,ri in zip(('bear','base','bull'),p,targets,r)],
        'expected_return':exp,'expected_excess_vs_assumed_benchmark':excess,'worst_scenario_return':min(r),
        'kelly_capped_single_asset':kelly,'quarter_kelly_before_portfolio_constraints':kelly/4 if kelly is not None else None,
        'probabilities_validated':probabilities_validated is True,'decision':'WAIT' if (probabilities_validated is not True or excess<=0) else 'RESEARCH_CANDIDATE',
        'can_trade':False,'limitations':['conditional subjective scenarios; not price-target probabilities from DCF','no correlation, tax, margin, FX or existing holdings sizing']}
