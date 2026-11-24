"""Retrospective thick-tail challenger study; no model promotion or order authority."""
from __future__ import annotations
import argparse, hashlib, json, math, statistics
from pathlib import Path
from .risk_calibration import ALPHAS, DECAY, END, SOURCE, START, WINDOW, coverage, forecasts, parse_archive, validate_rows
from .portfolio import tail_loss

FIT_END = '2014-12-31'
FHS_WINDOW = 750
FIXED_DF = 5.0
MODELS = ('historical_252', 'ewma_normal_094', 'ewma_t5', 'ewma_filtered_750', 'garch_t_fixed_fit')
FLOOR = 1e-12


def student_tail(alpha, df, sigma):
    from scipy.stats import t
    if not 0 < alpha < 1 or not math.isfinite(df) or df <= 2 or not math.isfinite(sigma) or sigma <= 0:
        raise ValueError('invalid Student-t tail inputs')
    q = float(t.ppf(alpha, df))
    scale = sigma * math.sqrt((df-2)/df)
    return q*scale, scale*(df+q*q)/(df-1)*float(t.pdf(q,df))/(1-alpha)


def garch_fit(train):
    """Fit zero-mean stationary GARCH(1,1)-t once; no test-period optimization."""
    import numpy as np
    from scipy.optimize import minimize
    from scipy.special import gammaln
    if len(train)<1000 or any(not math.isfinite(r) or abs(r)>=1 for r in train):
        raise ValueError('invalid GARCH training sample')
    scale = max(statistics.mean(r*r for r in train[:WINDOW]), FLOOR)
    x=np.asarray(train,dtype=float)/math.sqrt(scale)
    sq=x*x
    def objective(p):
        w,a,b,nu=p
        if w<=0 or a<0 or b<0 or a+b>=.999 or nu<=2:return 1e20
        v=np.empty(len(x)); v[0]=1.
        for i in range(1,len(x)):v[i]=max(w+a*sq[i-1]+b*v[i-1],FLOOR)
        const=gammaln((nu+1)/2)-gammaln(nu/2)-.5*math.log(math.pi*(nu-2))
        return float(np.sum(.5*np.log(v)+(nu+1)/2*np.log1p(sq/((nu-2)*v))-const))
    bounds=[(1e-7,5.),(0.,.998),(0.,.998),(2.1,60.)]
    constraint={'type':'ineq','fun':lambda p:.9989-p[1]-p[2]}
    starts=[(.03,.08,.89,5.),(.06,.12,.80,8.),(.10,.05,.85,15.)]
    results=[minimize(objective,s,method='SLSQP',bounds=bounds,constraints=constraint,options={'maxiter':300,'ftol':1e-8}) for s in starts]
    valid=[r for r in results if r.success and math.isfinite(r.fun) and r.fun<1e19 and all(math.isfinite(v) for v in r.x) and sum(r.x[1:3])<.999]
    if not valid:raise ValueError('GARCH fit failed; no silent fallback')
    best=min(valid,key=lambda r:r.fun)
    w,a,b,nu=map(float,best.x)
    variance=scale
    for r in train:variance=max(w*scale+a*r*r+b*variance,FLOOR)
    return {'omega':w*scale,'alpha':a,'beta':b,'df':nu,'variance_next':variance,'training_n':len(train),'optimizer_successes':len(valid),'optimizer_attempts':len(starts)}


def challenger_forecasts(rows, fit_end=FIT_END):
    dates,rs=validate_rows(rows)
    cut=sum(d<=fit_end for d in dates)
    if cut<FHS_WINDOW+WINDOW or len(rs)-cut<252:raise ValueError('training/evaluation split too short')
    fit=garch_fit(rs[:cut]);gv=fit['variance_next']
    variance=max(statistics.mean(x*x for x in rs[:WINDOW]),FLOOR)
    residuals=[];result=[]
    for i in range(WINDOW,len(rs)):
        sig=math.sqrt(variance)
        if i>=cut:
            sample=residuals[-FHS_WINDOW:]
            if len(sample)!=FHS_WINDOW:raise ValueError('filtered residual history incomplete')
            loss=-rs[i]
            losses=sorted(-x for x in sample)
            for a in ALPHAS:
                tvar,tes=student_tail(a,FIXED_DF,sig)
                gvar,ges=student_tail(a,fit['df'],math.sqrt(gv))
                fvar=losses[math.ceil(a*FHS_WINDOW)-1]*sig
                fes=tail_loss(sample,a)*sig
                for m,var,es in [('ewma_t5',tvar,tes),('ewma_filtered_750',fvar,fes),('garch_t_fixed_fit',gvar,ges)]:
                    if not math.isfinite(var) or not math.isfinite(es) or es+1e-12<var:raise ValueError('invalid tail forecast')
                    result.append({'date':dates[i],'through':dates[i-1],'model':m,'alpha':a,'loss':loss,'var':var,'es':es,'breach':loss>var})
            gv=max(fit['omega']+fit['alpha']*rs[i]**2+fit['beta']*gv,FLOOR)
        # Residual computed with the volatility forecast issued BEFORE today's return.
        residuals.append(rs[i]/sig)
        variance=max(DECAY*variance+(1-DECAY)*rs[i]**2,FLOOR)
    result.extend(r for r in forecasts(rows) if r['date']>fit_end)
    return result,fit


def es_moment(seq, alpha):
    """Descriptive unconditional ES moment with fixed-lag HAC uncertainty.
    Joint VaR/ES calibration and finite-sample bootstrap remain external gates.
    """
    x=[max(r['loss']-r['var'],0.)/(1-alpha)-(r['es']-r['var']) for r in seq]
    n=len(x);mean=statistics.mean(x);d=[z-mean for z in x];lag=min(20,n-1)
    v=sum(z*z for z in d)/n
    for k in range(1,lag+1):v+=2*(1-k/(lag+1))*sum(a*b for a,b in zip(d[k:],d[:-k]))/n
    se=math.sqrt(max(v,0.)/n)
    return {'mean':mean,'hac_se':se,'ci95':[mean-1.95996398454*se,mean+1.95996398454*se],'lag':lag,'diagnostic_only':True}


def evaluate(rows,fit_end=FIT_END):
    records,fit=challenger_forecasts(rows,fit_end)
    report={}
    for m in MODELS:
        report[m]={}
        for a in ALPHAS:
            seq=[r for r in records if r['model']==m and r['alpha']==a]
            stat=coverage([r['breach'] for r in seq],a)
            stat['quantile_loss_mean']=statistics.mean((a-(r['loss']<r['var']))*(r['loss']-r['var']) for r in seq)
            stat['es_moment']=es_moment(seq,a)
            stat['coverage_rejected_at_5pct']=stat['conditional_coverage_p'] is None or stat['conditional_coverage_p']<.05
            report[m][str(a)]=stat
    return {'status':'RETROSPECTIVE_CHALLENGER_DIAGNOSTIC','source':SOURCE,'fit_through':fit_end,'first_forecast':min(r['date'] for r in records),'last_forecast':max(r['date'] for r in records),'fit':fit,'models':report,'forecasts':len(records),'l6_certified':False,'promotion_allowed':False,'can_trade':False,'limitations':['2015–2024 was already inspected in prior baseline study; NOT untouched holdout','reconstructed archive, not historical PIT vintages','single aggregate US market return series, no account margin or positions','conditional coverage nonrejection is not proof; ES moment descriptive with asymptotic HAC','no automatic model selection; prospective preregistered replication required']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--zip',type=Path,required=True);p.add_argument('--confirm-research-rights',action='store_true');a=p.parse_args()
    if not a.confirm_research_rights:raise PermissionError('explicit personal research rights confirmation required')
    with a.zip.open('rb') as f:raw=f.read(2_000_001)
    rows=parse_archive(raw)
    if not rows or rows[0][0]!=START or rows[-1][0]!=END:raise ValueError('archive window incomplete')
    print(json.dumps(evaluate(rows)|{'archive_sha256':hashlib.sha256(raw).hexdigest(),'observations':len(rows)},indent=2,allow_nan=False));return 0
if __name__=='__main__':raise SystemExit(main())
