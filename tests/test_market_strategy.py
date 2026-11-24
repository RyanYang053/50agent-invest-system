import math
import pytest
from atlas_pro.market_strategy import rebalance, target_weight, replay, describe, load_archive, STRATEGIES


@pytest.mark.parametrize("current,target,rate",[(0,1,.001),(1,0,.005),(.7,.2,.003),(.2,.7,.003),(.5,.5,.001),(0,1,0),(1,0,0)])
def test_exact_self_financing(current,target,rate):
    turn,fee=rebalance(current,target,rate)
    delta=math.copysign(turn,target-current)
    assert current+delta==pytest.approx(target*(1-fee))
    assert 1-current-delta-fee==pytest.approx((1-target)*(1-fee))
    assert fee==pytest.approx(rate*turn)


@pytest.mark.parametrize("args",[(True,.5,.01),(.5,1.1,.001),(-.1,.5,.001),(.5,.5,float("nan"))])
def test_bad_rebalance(args):
    with pytest.raises(ValueError):rebalance(*args)


def sample():
    import exchange_calendars as xc
    cal=xc.get_calendar("XNYS",start="2004-01-01",end="2006-12-31")
    dates=[d.date().isoformat() for d in cal.sessions]
    return [(d,.001+.004*math.sin(i/5),.0001) for i,d in enumerate(dates)]


@pytest.mark.parametrize("name",STRATEGIES)
def test_future_cannot_change_target(name):
    rows=sample();dates=[d for d,r,c in rows];rs=[r for d,r,c in rows]
    i=300;a=target_weight(name,dates,rs,i,.4,True)
    rs[i-1:]=[-.9]*(len(rs)-i+1)
    assert target_weight(name,dates,rs,i,.4,True)==a


def test_buy_hold_initial_fee_only():
    rows=sample();p=replay(rows,"buy_hold",10)
    assert p[0]["fee_fraction"]==pytest.approx(.001/1.001)
    assert all(r["turnover"]==pytest.approx(0) for r in p[1:])
    wealth=math.prod(1+r["market_return"] for r in p)/1.001
    assert p[-1]["nav"]==pytest.approx(wealth)


def test_higher_cost_cannot_improve_fixed_buyhold():
    rows=sample()
    assert replay(rows,"buy_hold",50)[-1]["nav"]<replay(rows,"buy_hold",10)[-1]["nav"]


def test_replay_dates_and_returns():
    p=replay(sample(),"static_70_monthly",25)
    assert all(r["signal_through"]<r["execution_close"]<r["date"] for r in p)
    assert all(0<=r["target"]<=1 for r in p)
    assert p[-1]["nav"]==pytest.approx(math.prod(1+r["net_return"] for r in p))
    assert describe(p)["total_return"]==pytest.approx(p[-1]["nav"]-1)


def test_rejects_missing_session():
    rows=sample();del rows[300]
    with pytest.raises(ValueError):replay(rows,"trend_200",10)


def test_archive_revision_rejected():
    with pytest.raises(ValueError):load_archive(b"wrong archive")
