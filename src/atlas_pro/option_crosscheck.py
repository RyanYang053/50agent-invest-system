"""Optional independent European vanilla valuation, no broker or market data access."""
from __future__ import annotations
import math
from .research import num
from .ledger import digest,iso

def european_crosscheck(*,spot,strike,rate,dividend,volatility,expiry,at,right):
    s,k,r,q,v=map(num,(spot,strike,rate,dividend,volatility))
    t=(iso(expiry)-iso(at)).total_seconds()/(365.25*86400)
    if not 0<t<=20 or min(s,k)<=0 or max(s,k)>1e9 or not -.1<=r<=1 or not 0<=q<=1 or not .0001<=v<=5 or right not in ("call","put"):
        raise ValueError("unsupported valuation inputs")
    import QuantLib as ql
    discount=math.exp(-r*t);f=s*math.exp((r-q)*t);std=v*math.sqrt(t)
    d1=(math.log(s/k)+(r-q+v*v/2)*t)/std;d2=d1-std
    N=lambda x: .5*math.erfc(-x/math.sqrt(2))
    local=s*math.exp(-q*t)*N(d1)-k*discount*N(d2) if right=="call" else k*discount*N(-d2)-s*math.exp(-q*t)*N(-d1)
    option=ql.Option.Call if right=="call" else ql.Option.Put
    price=num(ql.BlackCalculator(ql.PlainVanillaPayoff(option,k),f,std,discount).value())
    tol=1e-7+1e-9*max(s,k)
    diff=abs(price-local)
    return {"status":"ENGINE_AGREEMENT" if diff<=tol else "ENGINE_DISAGREEMENT","engine":"QuantLib","engine_version":ql.__version__,"price_per_share":price,"independent_formula_price":local,"absolute_difference":diff,"tolerance":tol,"input_hash":digest({"s":s,"k":k,"r":r,"q":q,"v":v,"t":t,"right":right}),"can_trade":False,"limitations":["European exercise, constant supplied volatility/rates/dividend yield, continuous compounding; no market price, implied volatility, American exercise or broker margin validation"]}
