import random
import math
import pytest
from atlas_pro.backtest import self_financing_rebalance

@pytest.mark.parametrize("target,previous,rate",[
    ({"A":1},{"CASH":1},.1),
    ({"CASH":1},{"A":1},.1),
    ({"A":.3,"B":.4,"CASH":.3},{"A":.7,"B":.1,"CASH":.2},.005),
    ({"A":.5,"B":.5},{"B":1},.1),
    ({"A":.5,"B":.5},{"B":1},0),
    ({"CASH":1},{"CASH":1},.1)])
def test_exact_multisecurity_cash_conservation(target,previous,rate):
    turn,fee=self_financing_rebalance(target,previous,rate)
    keys=(set(target)|set(previous))-{"CASH"}
    deltas=[(1-fee)*target.get(k,0)-previous.get(k,0) for k in keys]
    assert turn==pytest.approx(sum(abs(x) for x in deltas))
    assert fee==pytest.approx(turn*rate)
    assert previous.get("CASH",0)-sum(deltas)-fee==pytest.approx((1-fee)*target.get("CASH",0))

def test_randomized_exact_rebalance_crosscheck():
    scipy=pytest.importorskip("scipy.optimize")
    rng=random.Random(20261124)
    for _ in range(300):
        n=rng.randrange(2,20);keys=[str(i) for i in range(n)]+["CASH"]
        a=[rng.random() for k in keys];b=[rng.random() for k in keys]
        target=dict(zip(keys,[v/sum(a) for v in a]));previous=dict(zip(keys,[v/sum(b) for v in b]))
        rate=rng.uniform(0,.1)
        turn,fee=self_financing_rebalance(target,previous,rate)
        f=lambda x:x+rate*sum(abs(x*target[k]-previous[k]) for k in keys[:-1])-1
        root=scipy.brentq(f,0,1,xtol=1e-14)
        assert abs(1-fee-root)<1e-12

@pytest.mark.parametrize("a,b,c",[
    ({"A":.5},{"CASH":1},.01),
    ({"A":-1,"B":2},{"CASH":1},.01),
    ({"A":1},{"CASH":1},.2),
    ({"A":float("nan")},{"CASH":1},.01)])
def test_bad_weights_refused(a,b,c):
    with pytest.raises(ValueError):self_financing_rebalance(a,b,c)
