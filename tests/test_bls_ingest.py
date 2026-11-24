"""Offline contract tests for BLS public series and the scoped RAG."""
from datetime import datetime,timezone
from copy import deepcopy
import pytest
from atlas_pro.bls_ingest import ingest_bls,SOURCE
from atlas_pro.feeds import PublicFeedClient
from atlas_pro.ledger import EvidenceLedger
from atlas_pro.retrieval import ResearchIndex
from atlas_pro.runtime import ResearchModelRunner

SERIES="LNS14000000"
AT="2026-11-24T12:00:00+00:00"
def clock():return datetime.fromisoformat(AT)
POL={"series_id":SERIES,"license_id":"BLS_PUBLIC","permitted_for_personal_analysis":True,"allow_local_retention":True,"allow_rag_indexing":True,"cloud_allowed":True}
def response():
    return {"status":"REQUEST_SUCCEEDED","message":[],"Results":{"series":[{"seriesID":SERIES,"data":[
      {"year":"2026","period":"M10","value":"4.2","footnotes":[{}]},
      {"year":"2026","period":"M09","value":"4.1","footnotes":[{}]},
      {"year":"2025","period":"M13","value":"4.0","footnotes":[{}]}
    ]}]}}
@pytest.fixture
def db(tmp_path):return EvidenceLedger(tmp_path/"e"),ResearchIndex(tmp_path/"i")
def test_fixed_bls_endpoint():
    calls=[]
    c=PublicFeedClient(lambda url,headers:calls.append(url) or response())
    assert c.bls_series(SERIES)==response()
    assert calls==["https://api.bls.gov/publicAPI/v2/timeseries/data/LNS14000000"]
    with pytest.raises(ValueError):c.bls_series("../other")
    assert len(calls)==1
def test_receipt_scope_and_replay(db):
    l,i=db;c=PublicFeedClient(lambda *args:response())
    r=ingest_bls(c,l,i,series=SERIES,policy=POL,clock=clock)
    assert r["status"]=="BLS_INDEXED" and len(r["evidence_ids"])==2
    assert r==ingest_bls(c,l,i,series=SERIES,policy=POL,clock=clock)
    assert not i.search("unemployment",decision_at="2026-11-24T11:59:59Z",security_id="MACRO:US")
    docs=i.search("unemployment",decision_at=AT,security_id="MACRO:US")
    assert len(docs)==2 and all(d["source_id"]==SOURCE for d in docs)
    assert not i.search("unemployment",decision_at=AT,security_id="MACRO:US",exclude_sources=(SOURCE,))
    assert l.verify_evidence_integrity()
    assert len(l.resolve_ids(r["evidence_ids"],security_id="MACRO:US",decision_at=AT))==2
@pytest.mark.parametrize("field",["permitted_for_personal_analysis","allow_local_retention","allow_rag_indexing","cloud_allowed","series_id"])
def test_rights_before_network(db,field):
    l,i=db;c=PublicFeedClient(lambda *args:pytest.fail("network must not run"))
    with pytest.raises(PermissionError):ingest_bls(c,l,i,series=SERIES,policy=POL|{field:False},clock=clock)
@pytest.mark.parametrize("mode",["bad_status","warning","wrong_series","duplicate","future","bad_period","nonfinite","negative","over_100","malformed_footnotes"])
def test_bad_provider_response(db,mode):
    l,i=db;raw=response();s=raw["Results"]["series"][0];r=s["data"][0]
    if mode=="bad_status":raw["status"]="REQUEST_FAILED"
    elif mode=="warning":raw["message"]=["warning"]
    elif mode=="wrong_series":s["seriesID"]="OTHER"
    elif mode=="duplicate":s["data"].append(deepcopy(r))
    elif mode=="future":r["period"]="M12"
    elif mode=="bad_period":r["period"]="M00"
    elif mode=="nonfinite":r["value"]="NaN"
    elif mode=="negative":r["value"]="-2"
    elif mode=="over_100":r["value"]="101"
    else:r["footnotes"]=["bad"]
    c=PublicFeedClient(lambda *args:raw)
    with pytest.raises(ValueError):ingest_bls(c,l,i,series=SERIES,policy=POL,clock=clock)
    assert not l.asof("MACRO:US",AT)
def test_other_public_role_cannot_receive_bls():
    class G:
        roles={"A061":{"role":"rates","data_scope":"public_only"}}
    class I:
        def search(self,*args,**kwargs):
            assert kwargs["exclude_sources"]==(SOURCE,)
            return [{"doc_id":"x","source_id":SOURCE}]
    r=ResearchModelRunner(G(),I(),lambda *args:pytest.fail("must not call model"))
    assert r.run(role_id="A061",task_set="fixture",request_id="r",security_id="MACRO:US",query="unemployment",at=AT)["status"]=="BLOCKED_SOURCE_SCOPE"
