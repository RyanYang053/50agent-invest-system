"""Developer-visible REAL public-domain macro and industrial panel baselines.
Revised vintage data, not true historical information sets or stock returns.
No paid API, no portfolio authorization, no claim of tradable alpha.
"""
from __future__ import annotations
import argparse,json,math
from pathlib import Path
from .ledger import digest


def macro_forecast():
    import numpy as np
    from statsmodels.datasets import macrodata
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.ensemble import HistGradientBoostingRegressor
    from threadpoolctl import threadpool_limits
    d=macrodata.load_pandas().data
    dates=[f'{int(y)}Q{int(q)}' for y,q in zip(d.year,d.quarter)]
    # Target next quarter GDP growth; features through t-2 relative to target,
    # leaving one full quarter for release. 2009-vintage revisions still leak
    # information relative to actual historical vintage; NOT a PIT experiment.
    g=np.diff(np.log(d.realgdp.to_numpy()))*400
    rows=[]
    for i in range(4,len(d)):
        rows.append({'target_date':dates[i],'feature_date':dates[i-2],
            'x':[float(g[i-3]),float(g[i-4]),float(d.unemp.iloc[i-2]),float(d.tbilrate.iloc[i-2]),float(d.infl.iloc[i-2])],
            'y':float(g[i-1])})
    out={k:[] for k in ('expanding_mean','last_available_growth','ridge','hist_gradient_boosting')}
    # Fixed first 80 observations; never tune on subsequent outcomes.
    with threadpool_limits(limits=1):
        for i in range(81,len(rows)):
            train=rows[:i-1];test=rows[i];x=np.array([r['x'] for r in train]);y=np.array([r['y'] for r in train]);t=np.array([test['x']]);actual=test['y']
            preds={'expanding_mean':float(y.mean()),'last_available_growth':test['x'][0],
                'ridge':float(make_pipeline(StandardScaler(),Ridge(alpha=10.)).fit(x,y).predict(t)[0]),
                'hist_gradient_boosting':float(HistGradientBoostingRegressor(max_iter=40,max_leaf_nodes=7,early_stopping=False,random_state=42).fit(x,y).predict(t)[0])}
            for name,pred in preds.items():out[name].append({'target':test['target_date'],'actual':actual,'prediction':pred,'training_last_target':train[-1]['target_date'],'feature_date':test['feature_date']})
    summary={}
    for k,ps in out.items():
        errors=[p['prediction']-p['actual'] for p in ps];summary[k]={'n':len(ps),'rmse_annualized_percentage_points':math.sqrt(sum(e*e for e in errors)/len(errors)),'mae_annualized_percentage_points':sum(abs(e) for e in errors)/len(errors),'predictions_hash':digest(ps)}
    return {'source':'statsmodels.datasets.macrodata (FRED/BLS, compiled 2009-12-15; public domain)','source_url':'https://github.com/statsmodels/statsmodels/tree/main/statsmodels/datasets/macrodata','data_hash':digest(d.to_dict(orient='records')),'observations':len(d),'period':[dates[0],dates[-1]],'oos_period':[out['ridge'][0]['target'],out['ridge'][-1]['target']],'models':summary,'predictions':out,'true_pit':False,'synthetic':False,'can_trade':False,'promotion_allowed':False,'limitations':['revised 2009 vintage; conservative calendar lag is not actual release/vintage evidence','public developer-visible series; not a preregistered untouched test','GDP forecasts, not equity returns or investment alpha']}


def industrial_panel():
    import numpy as np
    from statsmodels.datasets import grunfeld
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from scipy.stats import spearmanr
    from threadpoolctl import threadpool_limits
    d=grunfeld.load_pandas().data.copy();d['year']=d['year'].astype(int);firms=sorted(str(x) for x in d.firm.unique());years=sorted(d.year.unique());by={(str(r.firm),int(r.year)):r for r in d.itertuples()};pred=[]
    # Fixed historical selected firms; target log investment,
    # not market returns. Lag two years; dates are economic periods, not publication.
    for yr in years[11:]:
        train=[];test=[]
        for y in years[2:]:
            if y>yr:break
            for f in firms:
                lag=by[f,y-2];cur=by[f,y]
                x=[math.log1p(float(lag.value)),math.log1p(float(lag.capital)),math.log1p(float(lag.invest))];target=math.log1p(float(cur.invest))
                if y<=yr-2:train.append((x,target))
                if y==yr:test.append((f,x,target,math.log1p(float(lag.invest))))
        with threadpool_limits(limits=1):
            m=make_pipeline(StandardScaler(),Ridge(alpha=10.)).fit(np.array([x for x,y in train]),np.array([y for x,y in train]));vals=m.predict(np.array([x[1] for x in test]))
        for t,v in zip(test,vals):pred.append({'year':int(yr),'firm':t[0],'actual_log_invest':t[2],'ridge':float(v),'lag2':t[3]})
    summary={}
    for key in ('ridge','lag2'):
        e=[x[key]-x['actual_log_invest'] for x in pred];ics=[float(spearmanr([x[key] for x in pred if x['year']==y],[x['actual_log_invest'] for x in pred if x['year']==y]).statistic) for y in years[11:]]
        summary[key]={'n':len(e),'mae_log_investment':sum(abs(x) for x in e)/len(e),'mean_rank_ic':sum(ics)/len(ics)}
    return {'source':'statsmodels.datasets.grunfeld (public domain historical 11-firm investment panel)','source_url':'https://github.com/statsmodels/statsmodels/tree/main/statsmodels/datasets/grunfeld','observations':len(d),'firms':len(firms),'period':[int(years[0]),int(years[-1])],'oos_years':[int(years[11]),int(years[-1])],'data_hash':digest(d.to_dict(orient='records')),'models':summary,'predictions':pred,'synthetic':False,'true_pit':False,'can_trade':False,'promotion_allowed':False,'limitations':['selected historical firms, not a survivorship-free universe','publication and revision timestamps unknown','corporate investment forecasts not stock return forecasts']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path);a=p.parse_args();report={'status':'PUBLIC_DEVELOPER_EXPERIMENTS','macro':macro_forecast(),'industrial_panel':industrial_panel(),'l6_certified':False,'can_trade':False}
    raw=json.dumps(report,allow_nan=False,indent=2)
    if a.output:
        with a.output.open('x',encoding='utf8') as f:f.write(raw+'\n')
    print(raw);return 0
if __name__=='__main__':raise SystemExit(main())
