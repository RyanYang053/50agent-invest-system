"""Recompute reviewed performance claims from content-addressed daily evidence.

Developer/validator tool, not proof of provenance or a grant of trading rights.
All returns and confidence bounds are arithmetic daily decimal fractions. The
risk-adjusted statistic is a single-factor excess-return intercept, not a full
factor attribution. Independent reviewers must validate input truth, complete
trials, benchmark suitability, model selection and actual execution costs.
"""
from __future__ import annotations
import hashlib,json,math
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from .ledger import iso
from .independent_review import ishash,verify_artifacts


def read_artifact(root,h,*,max_bytes=20_000_000):
    if not ishash(h):raise ValueError('invalid evidence hash')
    p=Path(root)/h
    if p.is_symlink() or not p.is_file():raise ValueError('missing evidence artifact')
    with p.open('rb') as f: raw=f.read(max_bytes+1)
    if len(raw)>max_bytes or hashlib.sha256(raw).hexdigest()!=h:raise ValueError('evidence size or digest mismatch')
    def unique(pairs):
        out={}
        for k,v in pairs:
            if k in out:raise ValueError('duplicate evidence JSON key')
            out[k]=v
        return out
    return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite evidence')))


def full_session_closes(start,end):
    import exchange_calendars as xc
    a,b=iso(start),iso(end)
    if not a<b or b-a>timedelta(days=365*20+10):raise ValueError('invalid performance interval')
    et=ZoneInfo('America/New_York');da=a.astimezone(et).date().isoformat();db=b.astimezone(et).date().isoformat()
    cal=xc.get_calendar('XNYS',start=(a.astimezone(et).date()-timedelta(days=7)).isoformat(),end=(b.astimezone(et).date()+timedelta(days=7)).isoformat())
    return [cal.session_close(s).to_pydatetime() for s in cal.sessions_in_range(da,db) if cal.session_open(s).to_pydatetime()>=a and cal.session_close(s).to_pydatetime()<=b]


def _numeric(x,lo=-1,hi=10):
    if type(x) not in (int,float) or not math.isfinite(x) or not lo<=x<=hi:raise ValueError('invalid numeric performance evidence')
    return float(x)


def _hac(y,x,n_trials):
    """One-sided Bonferroni-adjusted HAC lower bounds, worst of fixed lags.
    Uses asymptotic normal approximation; rejects degenerate designs. No
    confidence claim if sample is short or materially ill-conditioned.
    """
    import numpy as np
    from scipy.stats import norm
    n=len(y)
    if n<252:raise ValueError('insufficient daily performance observations')
    coef,_,rank,_=np.linalg.lstsq(x,y,rcond=None)
    if rank!=x.shape[1] or not np.isfinite(coef).all() or np.linalg.cond(x)>1e8:raise ValueError('degenerate risk adjustment')
    errors=y-x@coef;scores=x*errors[:,None];bread=np.linalg.inv(x.T@x)
    critical=float(norm.isf(.05/n_trials));bounds=[];pvals=[];ses=[]
    for lag in (5,10,20):
        meat=scores.T@scores
        for j in range(1,lag+1):
            cross=scores[j:].T@scores[:-j];meat+=(1-j/(lag+1))*(cross+cross.T)
        variance=float((bread@meat@bread)[0,0])*n/(n-x.shape[1])
        if not math.isfinite(variance) or variance<=1e-24:raise ValueError('degenerate HAC variance')
        se=math.sqrt(variance);ses.append(se);bounds.append(float(coef[0])-critical*se);pvals.append(min(1.,float(norm.sf(float(coef[0])/se))*n_trials))
    return {'estimate':float(coef[0]),'lower_ci':min(bounds),'adjusted_p':max(pvals),'max_hac_se':max(ses),'beta':float(coef[1]) if x.shape[1]>1 else None}


def audit_performance(p,artifact_dir,*,gate):
    import numpy as np
    modes={'G4_research':'historical_oos','G9_forward_performance':'forward_paper','G10_live_evidence':'live'}
    mode=modes[gate];keys=('benchmark_hash','cost_model_hash','trial_registry_hash','returns_hash');hashes=[p[k] for k in keys]
    if len(set(hashes))!=4 or not set(hashes).issubset(p['artifact_hashes']):raise ValueError('missing distinct performance artifacts')
    benchmark,costs,trials,returns=[read_artifact(artifact_dir,h) for h in hashes]
    if benchmark.get('kind')!='BENCHMARK_DAILY_V1' or costs.get('kind')!='COST_DAILY_V1' or returns.get('kind')!='PORTFOLIO_DAILY_V1' or trials.get('kind')!='PERFORMANCE_TRIALS_V1':raise ValueError('invalid performance artifact kinds')
    if not isinstance(benchmark.get('benchmark_id'),str) or not benchmark['benchmark_id'] or returns.get('mode')!=mode or returns.get('currency') not in ('USD','CAD') or any(x.get('currency')!=returns['currency'] for x in (benchmark,costs)):raise ValueError('invalid benchmark, mode or currency')
    if returns.get('benchmark_hash')!=p['benchmark_hash'] or returns.get('cost_model_hash')!=p['cost_model_hash'] or trials.get('returns_hash')!=p['returns_hash']:raise ValueError('unbound performance artifacts')
    start,end,reviewed=iso(p['period_start']),iso(p['period_end']),iso(p['reviewed_at'])
    if not iso(trials['registered_at'])<=start or not iso(returns['frozen_at'])<=start:raise ValueError('post-hoc strategy or trial registration')
    items=trials['trials'];ids=[x['id'] for x in items]
    if not 1<=len(ids)<=10000 or any(not isinstance(i,str) or not i for i in ids) or len(set(ids))!=len(ids) or any(x.get('status') not in ('COMPLETED','FAILED','ABORTED') for x in items):raise ValueError('invalid or unfinished trial registry')
    selected=[x for x in items if x['id']==trials.get('selected_trial_id')]
    if len(selected)!=1 or selected[0]['status']!='COMPLETED' or returns.get('trial_id')!=selected[0]['id']:raise ValueError('selected trial not completed')
    if any(not ishash(x.get('result_hash')) for x in items) or len({x['result_hash'] for x in items})!=len(items):raise ValueError('missing or reused trial result artifact')
    # All registered attempts, including failed attempts, count for multiplicity.
    trial_hashes={x['result_hash'] for x in items};sources=set(trial_hashes)
    if sources & set(hashes):raise ValueError('trial result must be distinct evidence')
    closes=full_session_closes(p['period_start'],p['period_end']);n=len(closes)
    if n<252 or n>5500 or any(not isinstance(a.get('rows'),list) or len(a['rows'])!=n for a in (returns,benchmark,costs)):raise ValueError('incomplete exchange session coverage')
    ps=[];bs=[];rfs=[];wealth=peak=1.;dd=0.
    for stamp,r,b,c in zip(closes,returns['rows'],benchmark['rows'],costs['rows']):
        for row in (r,b,c):
            if iso(row['at'])!=stamp or not ishash(row.get('evidence_hash')) or not stamp<=iso(row['recorded_at'])<=reviewed:raise ValueError('row date or evidence mismatch')
            if mode!='historical_oos' and iso(row['recorded_at'])>stamp+timedelta(days=3):raise ValueError('late forward evidence')
            sources.add(row['evidence_hash'])
        if r.get('cash_flow_adjusted') is not True or b.get('total_return') is not True or c.get('all_costs_included') is not True:raise ValueError('unqualified return/cost accounting')
        gross=_numeric(r['gross_return'],-.999999);fee=_numeric(c['cost_fraction'],0,.5);net=(1+gross)*(1-fee)-1
        bench=_numeric(b['return'],-.999999);rf=_numeric(b['risk_free_return'],-.1,.1)
        ps.append(net);bs.append(bench);rfs.append(rf);wealth*=1+net
        if not math.isfinite(wealth) or wealth<=0:raise ValueError('invalid portfolio wealth')
        peak=max(peak,wealth);dd=max(dd,1-wealth/peak)
    if sources & set(hashes):raise ValueError('manifest cannot be its own raw source')
    if not sources.issubset(p['artifact_hashes']):raise ValueError('unreviewed raw evidence')
    verify_artifacts(sources,artifact_dir)
    ps=np.array(ps);bs=np.array(bs);rf=np.array(rfs)
    excess=_hac(ps-bs,np.ones((n,1)),len(items));alpha=_hac(ps-rf,np.column_stack([np.ones(n),bs-rf]),len(items))
    return {'status':'CONDITIONAL_RECOMPUTATION','n':n,'mode':mode,'trial_count':len(items),'net_excess_lower_ci':excess['lower_ci'],'risk_adjusted_excess_lower_ci':alpha['lower_ci'],'multiple_test_adjusted_p':excess['adjusted_p'],'max_drawdown':dd,'net_total_return':wealth-1,'excess':excess,'alpha':alpha,'can_trade':False,'limitations':['daily decimal return units','one-sided HAC normal-approximation bounds, Bonferroni across registered attempts, fixed lags 5/10/20','single benchmark factor; missing factors, regime instability and benchmark appropriateness require independent review','signed timestamps and raw files do not establish historical availability or independent execution']}


def check_signed_metrics(p,artifact_dir,*,gate):
    audit=audit_performance(p,artifact_dir,gate=gate);m=p['metrics'];prefix='live_' if gate=='G10_live_evidence' else ''
    reasons=[]
    pairs=[(prefix+'net_excess_lower_ci','net_excess_lower_ci')]
    if gate in ('G9_forward_performance','G10_live_evidence'):pairs.append((prefix+'risk_adjusted_excess_lower_ci','risk_adjusted_excess_lower_ci'))
    if gate=='G4_research':pairs.append(('multiple_test_adjusted_p','multiple_test_adjusted_p'))
    if gate=='G9_forward_performance':pairs.append(('max_drawdown','max_drawdown'))
    for signed,computed in pairs:
        if not math.isclose(m[signed],audit[computed],rel_tol=1e-7,abs_tol=1e-10):reasons.append('recomputed_metric_mismatch:'+signed)
    if audit['net_excess_lower_ci']<=0 or audit['multiple_test_adjusted_p']>.05:reasons.append('no_adjusted_net_advantage')
    if gate!='G4_research' and audit['risk_adjusted_excess_lower_ci']<=0:reasons.append('no_risk_adjusted_advantage')
    if gate=='G9_forward_performance' and (audit['n']!=m['prospective_sessions'] or audit['max_drawdown']>.25):reasons.append('forward_session_or_drawdown_mismatch')
    if gate=='G10_live_evidence' and audit['n']!=m['independently_verified_live_sessions']:reasons.append('live_session_mismatch')
    return reasons
