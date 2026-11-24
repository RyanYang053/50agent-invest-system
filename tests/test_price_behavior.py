from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import pytest
from atlas_pro.price_behavior import diagnose,continuity
from atlas_pro.ledger import EvidenceLedger,digest
from atlas_pro.role_jobs import RoleExecutor

START=datetime(2026,7,1,20,tzinfo=timezone.utc)
POL={"license_id":"fixture","permitted_for_personal_analysis":True,"cloud_allowed":False}
SID="CIK:1"
def put(ledger,i,*,close=None,high=None,low=None,closed=True,adjustment="split_adjusted"):
    t=(START+timedelta(days=i)).isoformat();c=100+i*.1 if close is None else close
    p={"kind":"daily_ohlcv","closed":closed,"adjustment":adjustment,"currency":"USD","venue":"fixture","bar_end":t,"open":c,"high":c+.5 if high is None else high,"low":c-.5 if low is None else low,"close":c,"volume":1000 if close is None else 2000}
    key=digest(p)
    ledger.add_evidence({"record_id":key,"source_id":"fixture","document_id":str(i),"security_id":SID,"observed_at":t,"published_at":t,"available_at":t,"payload":p,"data_class":"private","license_id":"fixture"},policy=POL)
    return key
@pytest.fixture
def data(tmp_path):
    l=EvidenceLedger(tmp_path/"e");ids=[put(l,i) for i in range(61)]
    return l,ids
def at(i):return (START+timedelta(days=i,hours=1)).isoformat()
def test_diagnostic_role_breakout(data):
    l,ids=data;ids.append(put(l,61,close=110))
    r=diagnose(l,security_id=SID,record_ids=ids,at=at(61))
    assert r["review"]["route"]=="REVIEW_BREAKOUT" and not r["can_trade"]
    roles=json.loads((Path(__file__).resolve().parents[1]/"config/50 agent manifest.json").read_text())
    out=RoleExecutor(roles,l).run("A065",at=at(61),run_id="price",inputs={"price_behavior":{"security_id":SID,"record_ids":ids}})
    assert out["diagnosis"]==r["diagnosis"] and not out["can_trade"]
def test_future_open_and_mixed_bars(data):
    l,ids=data
    with pytest.raises(ValueError):diagnose(l,security_id=SID,record_ids=ids,at=at(59))
    bad=put(l,61,closed=False)
    with pytest.raises(ValueError):diagnose(l,security_id=SID,record_ids=ids+[bad],at=at(61))
    mixed=put(l,62,adjustment="unadjusted")
    with pytest.raises(ValueError):diagnose(l,security_id=SID,record_ids=ids+[mixed],at=at(62))
def test_continuity_same_bar_ambiguity(data):
    l,ids=data;r=diagnose(l,security_id=SID,record_ids=ids,at=at(60))["diagnosis"]
    prior={"security_id":SID,"diagnosis_id":r["diagnosis_id"],"last_closed_bar":r["last_closed_bar"],"expires_after_observations":3,"watch_above":110,"invalidate_below":100}
    prior["plan_hash"]=digest(prior)
    untouched=continuity(l,security_id=SID,record_ids=ids,prior=prior,at=at(60))
    assert untouched["continuity"]["state"]=="UNCHANGED"
    ids.append(put(l,61,close=105,high=112,low=99))
    out=continuity(l,security_id=SID,record_ids=ids,prior=prior,at=at(61))
    assert out["continuity"]["state"]=="AMBIGUOUS_INTRABAR_REVIEW" and not out["continuity"]["fill_verified"]
    with pytest.raises(ValueError):continuity(l,security_id=SID,record_ids=ids,prior=prior|{"watch_above":111},at=at(61))
