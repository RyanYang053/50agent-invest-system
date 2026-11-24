"""Fixed retrospective market-allocation reference study; no trade authority.

The French research market portfolio and RF are non-executable research returns,
not ETF prices. Results are descriptive, not independent holdout or Alpha proof.
Signal uses information through two sessions before each return observation.
"""
from __future__ import annotations
import argparse,csv,hashlib,io,json,math,statistics,zipfile
from datetime import date
from pathlib import Path
from .risk_calibration import SOURCE,START,END,parse_archive,validate_rows
from .performance_evidence import _hac

ARCHIVE_SHA256="2ea687afb4b1b8f75c67bcb8b414a6bc5510e42d36b8671335b0fced2ae3b985"
COSTS=(10,25,50)
STRATEGIES=("buy_hold","static_70_monthly","trend_200","vol_10_weekly")
EVAL_START="2005-01-03"
TRIAL_COUNT=(len(STRATEGIES)-1)*len(COSTS)
WINDOWS={"all":(EVAL_START,END),"2005_2014":("2005-01-03","2014-12-31"),"2015_2024":("2015-01-01",END),"GFC":("2007-01-01","2009-12-31"),"COVID":("2020-01-01","2020-12-31"),"2022":("2022-01-01","2022-12-31")}


def load_archive(raw):
    if not isinstance(raw,bytes) or hashlib.sha256(raw).hexdigest()!=ARCHIVE_SHA256:
        raise ValueError("unexpected research archive revision")
    market=parse_archive(raw)
    dates,_=validate_rows(market)
    if dates[0]!=START or dates[-1]!=END:
        raise ValueError("incomplete reference archive")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        content=z.read(z.infolist()[0]).decode("utf-8-sig")
    rf={}
    for row in csv.reader(io.StringIO(content)):
        row=[x.strip() for x in row]
        if len(row)!=5 or len(row[0])!=8 or not row[0].isdigit():
            continue
        d=row[0][:4]+"-"+row[0][4:6]+"-"+row[0][6:]
        if d not in dates:
            continue
        v=float(row[4])/100
        if d in rf or not math.isfinite(v) or not -.01<=v<=.01:
            raise ValueError("invalid or duplicate cash return")
        rf[d]=v
    if set(rf)!=set(dates):
        raise ValueError("cash return coverage mismatch")
    return [(d,r,rf[d]) for d,r in market]


def rebalance(current,target,rate):
    """Target weight is post-fee; traded notional and fees relative to pre-trade NAV."""
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in (current,target,rate)) or not (0<=current<=1 and 0<=target<=1 and 0<=rate<=.05):
        raise ValueError("invalid self-financing trade")
    if current==target:
        return 0.,0.
    delta=(target-current)/(1+rate*target if target>current else 1-rate*target)
    fee=rate*abs(delta)
    if abs(current+delta-target*(1-fee))>1e-12:
        raise ArithmeticError("self-financing invariant")
    return abs(delta),fee


def target_weight(name, dates, returns, i, current, first):
    if name not in STRATEGIES or not 201<=i<len(dates) or len(dates)!=len(returns):
        raise ValueError("invalid strategy or signal index")
    if name=="buy_hold":
        return 1. if first else current
    if name=="static_70_monthly":
        # Execution at previous close; month change known in advance.
        return .7 if first or dates[i][:7]!=dates[i-1][:7] else current
    # Last observed signal return is i-2. No current or prior execution-close return.
    if name=="trend_200":
        past=returns[i-201:i-1]
        return 1. if math.fsum(math.log1p(x) for x in past)>0 else 0.
    if first or date.fromisoformat(dates[i]).isocalendar()[:2]!=date.fromisoformat(dates[i-1]).isocalendar()[:2]:
        vol=statistics.stdev(returns[i-64:i-1])*math.sqrt(252)
        return min(1.,.10/max(vol,1e-8))
    return current


def replay(rows,name,cost_bps,start=EVAL_START):
    if name not in STRATEGIES or type(cost_bps) not in (int,float) or not 0<=cost_bps<=50:
        raise ValueError("invalid replay settings")
    dates,market=validate_rows([(d,r) for d,r,c in rows])
    cash=[c for _,_,c in rows]
    if any(type(c) not in (int,float) or not math.isfinite(c) or not -.01<=c<=.01 for c in cash):
        raise ValueError("invalid cash return")
    if start not in dates or dates.index(start)<201:
        raise ValueError("insufficient pre-start signal history")
    current=0.;wealth=1.;out=[]
    for i in range(dates.index(start),len(rows)):
        w=target_weight(name,dates,market,i,current,not out)
        turnover,fee=rebalance(current,w,cost_bps/10000)
        gross=w*(1+market[i])+(1-w)*(1+cash[i])
        net=(1-fee)*gross-1
        if gross<=0 or not math.isfinite(net):
            raise ValueError("invalid wealth evolution")
        wealth*=1+net
        if not math.isfinite(wealth) or wealth<=0:
            raise ValueError("invalid portfolio wealth")
        out.append({"date":dates[i],"signal_through":dates[i-2],"execution_close":dates[i-1],
                    "target":w,"pre_trade_weight":current,"turnover":turnover,
                    "fee_fraction":fee,"net_return":net,"market_return":market[i],
                    "cash_return":cash[i],"nav":wealth})
        current=min(1.,max(0.,w*(1+market[i])/gross))
    return out


def describe(rows):
    if len(rows)<2:
        raise ValueError("insufficient reporting period")
    r=[x["net_return"] for x in rows]
    e=[x["net_return"]-x["cash_return"] for x in rows]
    wealth=peak=1.;dd=0.;fee_paid=0.
    for x in rows:
        fee_paid+=wealth*x["fee_fraction"]
        wealth*=1+x["net_return"];peak=max(peak,wealth);dd=max(dd,1-wealth/peak)
    vol=statistics.stdev(r);evol=statistics.stdev(e)
    return {"sessions":len(rows),"total_return":wealth-1,
            "annualized_return":wealth**(252/len(rows))-1,
            "max_drawdown":dd,"annualized_volatility":vol*math.sqrt(252),
            "sharpe_excess_rf":statistics.mean(e)/evol*math.sqrt(252) if evol else None,
            "average_risky_weight":statistics.mean(x["target"] for x in rows),
            "annualized_turnover":sum(x["turnover"] for x in rows)*252/len(rows),
            "fees_paid_in_initial_nav_units":fee_paid}


def compare(rows,benchmark):
    import numpy as np
    if len(rows)!=len(benchmark) or any(a["date"]!=b["date"] for a,b in zip(rows,benchmark)):
        raise ValueError("benchmark date mismatch")
    p=np.array([x["net_return"] for x in rows]);b=np.array([x["net_return"] for x in benchmark])
    rf=np.array([x["cash_return"] for x in rows])
    # Correct for all planned active strategies and cost variants, not only the winner.
    result={}
    for name,y,x in (("net_excess",p-b,np.ones((len(p),1))),
                     ("market_adjusted",p-rf,np.column_stack([np.ones(len(p)),b-rf]))):
        try:
            result[name]=_hac(y,x,TRIAL_COUNT)
        except ValueError as e:
            result[name]={"status":"UNAVAILABLE","reason":str(e)}
    return result


def evaluate(rows):
    output={}
    for cost in COSTS:
        paths={s:replay(rows,s,cost) for s in STRATEGIES}
        by_strategy={}
        for s,path in paths.items():
            periods={name:describe([r for r in path if a<=r["date"]<=b]) for name,(a,b) in WINDOWS.items()}
            by_strategy[s]={"periods":periods,
                            "comparison":compare(path,paths["buy_hold"]) if s!="buy_hold" else None,
                            "promotion_allowed":False}
        output[str(cost)]=by_strategy
    return {"status":"RETROSPECTIVE_MARKET_ALLOCATION_REFERENCE","source":SOURCE,
            "cost_bps":list(COSTS),"strategy_count":len(STRATEGIES),"active_comparison_count":TRIAL_COUNT,
            "first_forecast":EVAL_START,"last_forecast":rows[-1][0],
            "results":output,"l6_certified":False,"can_trade":False,"promotion_allowed":False,
            "limitations":["research factor portfolio and RF are not executable securities",
                           "reconstructed archive, not vintage point-in-time data",
                           "fixed one-way proportional costs, no spread/impact/capacity/taxes",
                           "previously inspected history, not an independent holdout",
                           "daily close-to-close approximation with a full session signal delay",
                           "HAC single-market risk adjustment, not complete multi-factor attribution",
                           "subperiod results are descriptive; no parameter optimization or selection"]}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--zip",type=Path,required=True)
    p.add_argument("--confirm-research-rights",action="store_true")
    a=p.parse_args()
    if not a.confirm_research_rights:
        raise PermissionError("explicit research rights confirmation required")
    with a.zip.open("rb") as f:raw=f.read(2_000_001)
    result=evaluate(load_archive(raw))
    print(json.dumps(result|{"archive_sha256":hashlib.sha256(raw).hexdigest()},indent=2,allow_nan=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
