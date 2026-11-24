import pytest
from atlas_pro.option_crosscheck import european_crosscheck
from atlas_pro.role_jobs import _option_bounds

P=dict(spot=100,strike=100,rate=.05,dividend=.02,volatility=.2,expiry="2027-11-24T12:00:00Z",at="2026-11-24T12:00:00Z",right="call")
@pytest.mark.parametrize("right",["call","put"])
@pytest.mark.parametrize("strike",[60,100,140])
def test_quantlib_optional(right,strike):
    pytest.importorskip("QuantLib")
    r=european_crosscheck(**(P|{"right":right,"strike":strike}))
    assert r["status"]=="ENGINE_AGREEMENT" and r["price_per_share"]>=0 and not r["can_trade"]
def test_quantlib_optional_role_route():
    pytest.importorskip("QuantLib")
    r=_option_bounds(dict(spot=100,strike=100,mark=10,risk_free_rate=.05,dividend_yield=.02,expiry=P["expiry"],right="call",style="european",quantlib_crosscheck=True,volatility=.2),P["at"])
    assert r["quantlib"]["status"]=="ENGINE_AGREEMENT"
def test_quantlib_refuses_invalid_input():
    with pytest.raises(ValueError):european_crosscheck(**(P|{"volatility":0}))
    with pytest.raises(ValueError):_option_bounds(dict(spot=100,strike=100,mark=10,risk_free_rate=.05,dividend_yield=.02,expiry=P["expiry"],right="call",style="american",quantlib_crosscheck=True,volatility=.2),P["at"])
