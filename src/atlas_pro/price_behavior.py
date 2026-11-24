"""Independent daily price-behavior diagnostics, research only.

Closed, traceable OHLCV bars; explicit diagnosis then review routing. No
probability, trading signal certification, live execution or inferred fills.
"""
from __future__ import annotations
import math,statistics
from .ledger import digest,iso
from .research import num

VERSION="daily-price-behavior-v1"

def diagnose(ledger,*,security_id,record_ids,at):
    if not isinstance(record_ids,list) or not 61<=len(record_ids)<=200:raise ValueError("61–200 closed daily observations required")
    cutoff=iso(at)
    rows=ledger.resolve_ids(record_ids,security_id=security_id,decision_at=at,include_private=True)
    bars=[];identity=None;previous=None
    for row in rows:
        p=row["payload"]
        if p.get("kind")!="daily_ohlcv" or p.get("closed") is not True or p.get("adjustment") not in ("split_adjusted","unadjusted") or not isinstance(p.get("currency"),str) or not p["currency"] or not isinstance(p.get("venue"),str) or not p["venue"]:raise ValueError("bar schema")
        key=(row["source_id"],p["currency"],p["venue"],p["adjustment"])
        if identity is not None and key!=identity:raise ValueError("mixed bar provenance")
        identity=key
        end=iso(p["bar_end"]);available=iso(row["available_at"])
        if end!=iso(row["observed_at"]) or not end<=available<=cutoff or (previous and (end<=previous or end.date()==previous.date())):raise ValueError("invalid bar chronology")
        o,h,l,c,v=map(num,(p["open"],p["high"],p["low"],p["close"],p["volume"]))
        if not 0<l<=min(o,c)<=max(o,c)<=h or v<0:raise ValueError("invalid OHLCV")
        bars.append({"end":end.isoformat(),"open":o,"high":h,"low":l,"close":c,"volume":v,"record_id":row["record_id"]})
        previous=end
    closes=[b["close"] for b in bars];last=bars[-1];c=closes[-1]
    peak=max(closes[-61:-1]);floor=min(closes[-21:-1]);resistance=max(b["high"] for b in bars[-21:-1])
    support=min(b["low"] for b in bars[-21:-1]);sma20=statistics.mean(closes[-20:]);sma60=statistics.mean(closes[-60:])
    ranges=[max(b["high"]-b["low"],abs(b["high"]-bars[i-1]["close"]),abs(b["low"]-bars[i-1]["close"])) for i,b in enumerate(bars) if i>0]
    atr=statistics.mean(ranges[-14:]);vol=statistics.mean(b["volume"] for b in bars[-21:-1])
    relative_volume=last["volume"]/vol if vol>0 else None
    trend="UP" if c>sma20>sma60 else "DOWN" if c<sma20<sma60 else "MIXED"
    fresh=0<=(cutoff-previous).total_seconds()<=4*86400
    # This is a deliberately descriptive candidate classifier, not a fitted trading rule.
    rebound=c>closes[-2] and closes[-2]>closes[-3] and c>sma20 and min(closes[-10:])<sma20
    breakout=c>resistance and relative_volume is not None and relative_volume>=1.5
    breakdown=c<support
    flags={"fresh":fresh,"split_adjusted":identity[3]=="split_adjusted","trend_aligned":trend=="UP","rebound_candidate":rebound,"breakout_candidate":breakout,"breakdown":breakdown}
    stage1={"security_id":security_id,"as_of":cutoff.isoformat(),"last_closed_bar":last["end"],"source_id":identity[0],"currency":identity[1],"venue":identity[2],"adjustment":identity[3],"record_ids":record_ids,"bar_hash":digest(bars),"observations":len(bars),"trend":trend,"flags":flags,"metrics":{"close":c,"sma20":sma20,"sma60":sma60,"atr14":atr,"prior20_high":resistance,"prior20_low":support,"relative_volume":relative_volume,"return_5_observations":c/closes[-6]-1,"drawdown_from_prior60_close_peak":min(0,c/peak-1),"rebound_from_prior20_close_low":c/floor-1},"version":VERSION}
    stage1["diagnosis_id"]=digest(stage1)
    gates=[
        {"node":"data_freshness","state":"PASS" if fresh else "BLOCK"},
        {"node":"corporate_action_basis","state":"PASS" if flags["split_adjusted"] else "BLOCK"},
        {"node":"downside_structure","state":"BLOCK" if breakdown else "PASS"},
        {"node":"trend","state":"PASS" if trend=="UP" else "REVIEW"},
        {"node":"candidate","state":"PASS" if rebound or breakout else "REVIEW"},
    ]
    route="WAIT"
    if fresh and flags["split_adjusted"]:
        if breakdown:route="REASSESS_RISK"
        elif breakout:route="REVIEW_BREAKOUT"
        elif rebound:route="REVIEW_REBOUND"
    return {"status":"PRICE_BEHAVIOR_DIAGNOSTIC","diagnosis":stage1,"review":{"route":route,"gates":gates,"diagnosis_id":stage1["diagnosis_id"],"valuation_and_portfolio_review_required":True},"can_trade":False,"limitations":["observed bars only; exchange session completeness and corporate action accuracy require provider verification","heuristic thresholds unvalidated; no expected return or probability","price-return basis not total return; no orders or fill inference"]}

def continuity(ledger,*,security_id,record_ids,prior,at):
    """Recheck a prior immutable research watch against subsequently observed bars.
    Touches are observations, not executions. Do not reuse previously seen bars.
    """
    if not isinstance(prior,dict) or set(prior)!={"security_id","diagnosis_id","last_closed_bar","expires_after_observations","watch_above","invalidate_below","plan_hash"}:raise ValueError("watch schema")
    if digest({k:v for k,v in prior.items() if k!="plan_hash"})!=prior["plan_hash"] or prior["security_id"]!=security_id:raise ValueError("watch integrity")
    if not isinstance(prior["diagnosis_id"],str) or len(prior["diagnosis_id"])!=64 or type(prior["expires_after_observations"]) is not int or not 1<=prior["expires_after_observations"]<=20:raise ValueError("watch bounds")
    upper,lower=map(num,(prior["watch_above"],prior["invalidate_below"]))
    if not 0<lower<upper:raise ValueError("watch levels")
    result=diagnose(ledger,security_id=security_id,record_ids=record_ids,at=at)
    prior_end=iso(prior["last_closed_bar"])
    rows=ledger.resolve_ids(record_ids,security_id=security_id,decision_at=at,include_private=True)
    if not any(iso(r["observed_at"])==prior_end for r in rows):raise ValueError("prior bar absent from replay window")
    new=[r for r in rows if iso(r["observed_at"])>prior_end]
    state="UNCHANGED";events=[]
    for r in new[:prior["expires_after_observations"]]:
        p=r["payload"];above=num(p["high"])>=upper;below=num(p["low"])<=lower
        if above or below:events.append({"record_id":r["record_id"],"above":above,"below":below})
    if any(e["above"] and e["below"] for e in events):state="AMBIGUOUS_INTRABAR_REVIEW"
    elif any(e["below"] for e in events):state="INVALIDATED_REVIEW"
    elif len(new)>=prior["expires_after_observations"]:state="EXPIRED_REVIEW"
    elif any(e["above"] for e in events):state="LEVEL_OBSERVED_REVIEW"
    result["continuity"]={"prior_plan_hash":prior["plan_hash"],"new_observations":len(new),"state":state,"events":events,"fill_verified":False}
    return result
