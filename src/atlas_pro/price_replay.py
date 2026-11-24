"""Descriptive price-behavior reference replay, NOT a PIT trading backtest."""
from __future__ import annotations
import statistics
from .ledger import digest,iso
from .research import num
from .price_behavior import diagnose,VERSION

HORIZONS=(5,20)
GROUPS=("all","breakout","rebound","breakdown","other")

def retrospective(ledger,*,security_id,record_ids,at):
    current=diagnose(ledger,security_id=security_id,record_ids=record_ids,at=at)
    if current["diagnosis"]["adjustment"]!="split_adjusted":raise ValueError("split-adjusted basis required")
    rows=ledger.resolve_ids(record_ids,security_id=security_id,decision_at=at,include_private=True)
    if len(rows)<100:raise ValueError("100 observations required for reference replay")
    prices=[num(r["payload"]["close"]) for r in rows]
    reports={}
    for horizon in HORIZONS:
        events=[]
        # Predeclared disjoint outcome windows. Start with 61 observations.
        # Do not move the sampling grid to match an observed signal.
        for i in range(60,len(rows)-horizon-1,horizon+1):
            hist=diagnose(ledger,security_id=security_id,record_ids=record_ids[i-60:i+1],at=at)["diagnosis"]
            f=hist["flags"]
            group="breakdown" if f["breakdown"] else "breakout" if f["breakout_candidate"] else "rebound" if f["rebound_candidate"] else "other"
            # Next day's close to terminal close, not an assumed executable fill.
            entry=i+1;end=entry+horizon
            change=prices[end]/prices[entry]-1
            events.append({"signal_bar":rows[i]["observed_at"],"reference_start":rows[entry]["observed_at"],"reference_end":rows[end]["observed_at"],"group":group,"price_return":change,"signal_input_hash":hist["bar_hash"]})
        summary={}
        for g in GROUPS:
            x=[e["price_return"] for e in events if g=="all" or e["group"]==g]
            summary[g]={"n":len(x),"mean_price_return":statistics.mean(x) if x else None,"median_price_return":statistics.median(x) if x else None,"positive_fraction":sum(v>0 for v in x)/len(x) if x else None}
        reports[str(horizon)]={"summary":summary,"observations":events}
    return {"status":"RETROSPECTIVE_PRICE_REFERENCE_ONLY","security_id":security_id,"receipt_cutoff":iso(at).isoformat(),"bar_hash":current["diagnosis"]["bar_hash"],"method_version":VERSION,"sample_rule":"fixed disjoint outcome windows, first signal index 60, next daily close reference, no optimizing","horizons":reports,"point_in_time_history":False,"promotion_allowed":False,"can_trade":False,"limitations":["current reconstructed split-adjusted history, not historical vintages","partial venue price return only, not dividends, costs or execution","all-sample comparator is descriptive and includes signal cases","small samples, no independent test or calibrated probability","no alpha or profitability claim"]}
