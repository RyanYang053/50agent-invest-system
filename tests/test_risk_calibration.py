import io,math,zipfile
import pytest
import exchange_calendars as xc
from atlas_pro.risk_calibration import coverage,forecasts,parse_archive,summarize,validate_rows


def rows():
    dates=xc.get_calendar('XNYS',start='2020-01-01',end='2023-12-31').sessions
    return [(d.date().isoformat(),.012*math.sin(i*.43)+.004*math.cos(i*.17)) for i,d in enumerate(dates)]


def test_walkforward_no_current_or_future_leak():
    x=rows();base=forecasts(x);y=x.copy();d,_=y[300];y[300]=(d,-.7);changed=forecasts(y)
    assert [r for r in base if r['date']<d]==[r for r in changed if r['date']<d]
    for a,b in zip([r for r in base if r['date']==d],[r for r in changed if r['date']==d]):
        assert (a['var'],a['es'],a['through'])==(b['var'],b['es'],b['through'])
    assert any(a['var']!=b['var'] for a,b in zip(base,changed) if a['date']>d)
    assert all(r['through']<r['date'] and r['es']>=r['var']-1e-12 for r in base)
    report=summarize(base);assert report['promotion_allowed'] is False and report['can_trade'] is False


@pytest.mark.parametrize('mutate',[lambda x:x[:300]+x[301:],lambda x:x[:300]+[x[299]]+x[300:],lambda x:x[:300]+list(reversed(x[300:])),lambda x:x[:300]+[(x[300][0],float('nan'))]+x[301:]])
def test_bad_series(mutate):
    with pytest.raises(ValueError):validate_rows(mutate(rows()))


def test_coverage_endpoints_and_clusters():
    assert coverage([False]*300,.95)['independence_p'] is None
    assert coverage([True]*300,.95)['independence_p'] is None
    dispersed=coverage([i%20==0 for i in range(1000)],.95)
    clustered=coverage([i<50 for i in range(1000)],.95)
    assert dispersed['kupiec_p']>.999 and clustered['kupiec_p']>.999
    assert clustered['independence_p']<1e-10 and clustered['conditional_coverage_p']<1e-10


def zipped(text):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('factors.csv',text)
    return b.getvalue()


def test_factor_parser_units_and_sentinel():
    header='Description\n,Mkt-RF,SMB,HML,RF\n'
    assert parse_archive(zipped(header+'20040102,0.4,0,0,0.01\n'))==[('2004-01-02',.0041)]
    with pytest.raises(ValueError):parse_archive(zipped(header+'20040102,-99.99,0,0,0.01\n'))
    with pytest.raises(ValueError):parse_archive(zipped('date,price\n20040102,5\n'))
