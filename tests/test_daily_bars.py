from datetime import datetime,timezone,timedelta
from urllib.parse import urlsplit,parse_qs
from zoneinfo import ZoneInfo
import pytest
from atlas_pro.daily_bars import ingest_daily,sessions
from atlas_pro.market_data import AlpacaResearchQuotes
from atlas_pro.ledger import EvidenceLedger
from atlas_pro.price_behavior import diagnose
from atlas_pro.price_replay import retrospective

NY=ZoneInfo("America/New_York")
START="2026-04-01";END="2026-10-30";AT=datetime(2026,11,2,15,tzinfo=timezone.utc)
POL={"license_id":"ALPACA_PERSONAL","permitted_for_personal_analysis":True,"allow_local_retention":True,"cloud_allowed":False,"symbol":"ABC","security_id":"CIK:1","symbol_mapping_reviewed":True,"allow_historical_research":True}

def fixture():
    from datetime import date
    dates=list(sessions(date.fromisoformat(START),date.fromisoformat(END)))
    rows=[]
    for i,d in enumerate(dates):
        c=100+i*.1
        rows.append({"t":datetime.combine(d,datetime.min.time(),NY).astimezone(timezone.utc).isoformat(),"o":c,"h":c+1,"l":c-1,"c":c,"v":1000})
    return {"bars":{"ABC":rows},"next_page_token":None}

def run(tmp_path,raw,policy=POL):
    ledger=EvidenceLedger(tmp_path/"e")
    calls=[]
    def transport(url,headers):
        q=parse_qs(urlsplit(url).query);assert q["feed"]==["iex"] and q["asof"]==["-"] and q["adjustment"]==["split"]
        assert urlsplit(url).hostname=="data.alpaca.markets"
        calls.append(url);return raw
    client=AlpacaResearchQuotes(policy=policy,transport=transport,api_key="fixture",api_secret="fixture")
    result=ingest_daily(client,ledger,symbol="ABC",security_id="CIK:1",start=START,end=END,policy=policy,clock=lambda:AT)
    return ledger,result,calls

def test_daily_ingestion_and_retrospective(tmp_path):
    pytest.importorskip("exchange_calendars")
    l,r,calls=run(tmp_path,fixture())
    assert len(calls)==1 and r["sessions"]>=100 and not r["point_in_time_history"]
    ids=r["record_ids"]
    assert not l.asof("CIK:1",AT.isoformat())
    with pytest.raises(ValueError):l.resolve_ids(ids,security_id="CIK:1",decision_at=(AT-timedelta(seconds=1)).isoformat(),include_private=True)
    d=diagnose(l,security_id="CIK:1",record_ids=ids,at=AT.isoformat())
    assert d["diagnosis"]["trend"]=="UP"
    out=retrospective(l,security_id="CIK:1",record_ids=ids,at=AT.isoformat())
    assert out["status"]=="RETROSPECTIVE_PRICE_REFERENCE_ONLY" and not out["promotion_allowed"]
    for horizon,v in out["horizons"].items():
        events=v["observations"]
        assert events and all(a["reference_end"]<b["reference_start"] for a,b in zip(events,events[1:]))
        assert all(e["signal_bar"]<e["reference_start"]<e["reference_end"] for e in events)
        assert v["summary"]["all"]["n"]==len(events)
    assert l.verify_evidence_integrity()

@pytest.mark.parametrize("problem",["missing","duplicate","pagination","wrong_symbol","bad_price","timestamp"])
def test_bad_snapshot_has_no_writes(tmp_path,problem):
    pytest.importorskip("exchange_calendars")
    raw=fixture();rows=raw["bars"]["ABC"]
    if problem=="missing":rows.pop()
    elif problem=="duplicate":rows[1]=rows[0]
    elif problem=="pagination":raw["next_page_token"]="next"
    elif problem=="wrong_symbol":raw["bars"]["XYZ"]=raw["bars"].pop("ABC")
    elif problem=="bad_price":rows[-1]["h"]=0
    else:rows[-1]["t"]="2026-10-30T20:00:00Z"
    with pytest.raises(ValueError):run(tmp_path,raw)
    assert not EvidenceLedger(tmp_path/"e").asof("CIK:1",AT.isoformat(),include_private=True)
def test_rights_before_network(tmp_path):
    p=POL|{"allow_historical_research":False}
    c=AlpacaResearchQuotes(policy=p,transport=lambda *a:pytest.fail("unexpected network"),api_key="fixture",api_secret="fixture")
    with pytest.raises(PermissionError):ingest_daily(c,EvidenceLedger(tmp_path/"e"),symbol="ABC",security_id="CIK:1",start=START,end=END,policy=p,clock=lambda:AT)
