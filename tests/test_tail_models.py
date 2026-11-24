import math
import pytest
pytest.importorskip("scipy")
import exchange_calendars as xc
from atlas_pro.tail_models import challenger_forecasts, evaluate, student_tail, garch_fit, es_moment


def rows():
    import numpy as np
    rng=np.random.default_rng(71);sigma=.01;out=[]
    dates=xc.get_calendar('XNYS',start='2008-01-01',end='2016-12-31').sessions
    for d in dates:
        r=sigma*rng.standard_t(6)*math.sqrt(4/6)
        out.append((d.date().isoformat(),float(r)))
        sigma=math.sqrt(.000002+.08*r*r+.9*sigma*sigma)
    return out


@pytest.mark.parametrize('a',[.95,.99])
def test_t_formula_against_integration(a):
    from scipy.stats import t
    from scipy.integrate import quad
    df=5.;sigma=.02;var,es=student_tail(a,df,sigma);scale=sigma*math.sqrt((df-2)/df)
    assert var==pytest.approx(scale*t.ppf(a,df))
    assert es==pytest.approx(scale*quad(lambda x:x*t.pdf(x,df),var/scale,math.inf)[0]/(1-a),rel=1e-7)
    assert es>var>0


def test_frozen_fit_and_no_future_leak(monkeypatch):
    import atlas_pro.tail_models as mod
    x=rows();fit_end='2013-12-31';train=[r for d,r in x if d<=fit_end]
    fit=garch_fit(train);assert fit['alpha']+fit['beta']<1 and fit['df']>2
    monkeypatch.setattr(mod,'garch_fit',lambda r:fit if r==train else pytest.fail('training leaked'))
    a,_=challenger_forecasts(x,fit_end)
    idx=next(i for i,(d,r) in enumerate(x) if d>'2014-06-01');d=x[idx][0];y=x.copy();y[idx]=(d,-.4)
    b,_=challenger_forecasts(y,fit_end)
    assert [r for r in a if r['date']<d]==[r for r in b if r['date']<d]
    assert [(r['model'],r['var'],r['es']) for r in a if r['date']==d]==[(r['model'],r['var'],r['es']) for r in b if r['date']==d]
    assert any(i['var']!=j['var'] for i,j in zip(a,b) if i['date']>d)
    assert all(r['through']<r['date'] and r['es']>=r['var']-1e-12 for r in a)
    report=evaluate(x,fit_end)
    assert len(report['models'])==5 and report['promotion_allowed'] is False and report['can_trade'] is False
    assert report['fit']['training_n']==len(train)


def test_es_moment_hac():
    seq=[{'loss':.02,'var':.01,'es':.03} for _ in range(100)]
    r=es_moment(seq,.95)
    assert r['mean']==pytest.approx(.18) and r['hac_se']==pytest.approx(0,abs=1e-10)


@pytest.mark.parametrize('a,df,sigma',[(.99,2.,.01),(.99,5.,0),(.99,float('nan'),1), (1,5,1)])
def test_invalid_t(a,df,sigma):
    with pytest.raises(ValueError):student_tail(a,df,sigma)
