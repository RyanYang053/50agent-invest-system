"""Offline scope, revision, rights and dispatch regression tests."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
import json,sqlite3
import pytest
from atlas_pro.external_references import ReferenceStore,NIST_URL,fetch_nist,HOSTS
from atlas_pro.employee_packs import reference_plan
from atlas_pro.skill_contracts import catalog
from atlas_pro.role_jobs import RoleExecutor
from atlas_pro.ledger import EvidenceLedger

T=datetime(2026,11,24,12,tzinfo=timezone.utc)
URLS={"damodaran":"https://pages.stern.nyu.edu/~adamodar/New_Home_Page/tools.html","cra":"https://www.canada.ca/en/revenue-agency/services/tax/individuals/topics/tax-free-savings-account/contributing/how.html","occ":"https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document","nist":"https://www.nist.gov/itl/ai-risk-management-framework"}
def policy(source,url):
    return {"source_id":source,"source_url":url,"rights_reviewed":True,"allow_local_retention":True,"allow_local_rag":True,"cloud_allowed":False,"license_note":"synthetic fixture only"}
@pytest.fixture
def state(tmp_path):
    clock=[T]
    return ReferenceStore(tmp_path/"ref",clock=lambda:clock[0]),clock
@pytest.mark.parametrize("role",sorted(catalog()))
def test_scope_all_roles(state,role):
    s,c=state
    for src,url in URLS.items():s.ingest(src,url,("fixture valuation tax risk governance "+src).encode(),policy(src,url))
    expected={x["source_id"] for x in reference_plan(role)}&set(HOSTS)
    rows=s.search(role,"fixture",at=T.isoformat(),limit=10)
    assert {x["source_id"] for x in rows}==expected
    assert all(x["role_id"]==role and x["local_only"] and not x["cloud_allowed"] for x in rows)
def test_versions_and_no_lookahead(state):
    s,c=state;src="cra";url=URLS[src];p=policy(src,url)
    old=s.ingest(src,url,b"tax old version",p);assert s.ingest(src,url,b"tax old version",p)["status"]=="UNCHANGED"
    c[0]+=timedelta(days=1)
    new=s.ingest(src,url,b"tax new version",p)
    assert old["snapshot_id"]!=new["snapshot_id"]
    assert s.search("A085","tax",at=T.isoformat())[0]["text"]=="tax old version"
    assert s.search("A085","tax",at=c[0].isoformat())[0]["text"]=="tax new version"
    assert not s.search("A085","tax",at=(T-timedelta(seconds=1)).isoformat())
    with pytest.raises(ValueError):s.search("A085","tax",at=(c[0]+timedelta(seconds=1)).isoformat())
@pytest.mark.parametrize("field",["rights_reviewed","allow_local_retention","allow_local_rag","cloud_allowed"])
def test_rights_required(state,field):
    s,c=state;p=policy("cra",URLS["cra"]);p[field]=not p[field]
    with pytest.raises(PermissionError):s.ingest("cra",URLS["cra"],b"tax",p)
def test_denied_sources_and_urls(state):
    s,c=state
    for src,url in [("financebench","https://github.com/patronus-ai/financebench"),("cra","https://www.canada.ca/en/other"),("nist","https://evil.test/playbook.json")]:
        with pytest.raises(PermissionError):s.ingest(src,url,b"test",policy(src,url))
    with pytest.raises(PermissionError):fetch_nist(s,policy("nist",NIST_URL))
def test_nist_schema(state):
    s,c=state;rows=[{"title":x+" 1.1","description":"governance fixture","section_about":"about","section_actions":"action","section_doc":"documentation"} for x in ("GOVERN","MAP","MEASURE","MANAGE")]
    p=policy("nist",NIST_URL)
    with pytest.raises(ValueError):s.ingest("nist",NIST_URL,json.dumps(rows[:1]).encode(),p)
    r=s.ingest("nist",NIST_URL,json.dumps(rows).encode(),p)
    hits=s.search("A105","governance",at=T.isoformat())
    assert hits and hits[0]["snapshot_id"]==r["snapshot_id"]
    assert not s.search("A085","governance",at=T.isoformat())
def test_integrity_and_receipt(state,tmp_path):
    s,c=state;url=URLS["cra"];r=s.ingest("cra",url,b"account tax fixture source",policy("cra",url))
    root=Path(__file__).resolve().parents[1]
    roles=json.loads((root/"config/50 agent manifest.json").read_text())
    e=RoleExecutor(roles,EvidenceLedger(tmp_path/"ledger"),reference_store=s)
    out=e.run("A085",at=T.isoformat(),run_id="tax",inputs={"account_types":["TFSA"]})
    hits=out["reference_context"]["local_external_reference_hits"]
    assert hits and hits[0]["snapshot_id"]==r["snapshot_id"] and "text" not in hits[0]
    assert out["status"]=="BLOCKED_TAX_REVIEW" and not out["can_trade"]
    with sqlite3.connect(s.path) as db:db.execute("update snapshots set raw=?",(b"tampered",))
    with pytest.raises(ValueError):s.search("A085","tax",at=T.isoformat())
    assert e.run("A085",at=T.isoformat(),run_id="tax2",inputs={"account_types":["TFSA"]})["status"]=="BLOCKED_ROLE_REFERENCE_INTEGRITY"
