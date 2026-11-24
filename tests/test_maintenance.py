from datetime import datetime,timezone,timedelta
import sqlite3
import pytest
from atlas_pro.maintenance import tick

T=datetime(2026,11,24,12,tzinfo=timezone.utc)
def test_tick_scope_and_idempotence(tmp_path):
    root=tmp_path/"private";calls=[]
    config={"macro_policies":[{"series_id":"fixture"}],"nist_policy":{"fixture":True},"reflect":True}
    def m(p):calls.append("macro");return [{"status":"fixture"}]
    def n(p):calls.append("nist");return {"status":"fixture"}
    kw={"network":True,"clock":lambda:T,"macro_runner":m,"nist_runner":n}
    with pytest.raises(PermissionError):tick(root,config)
    r=tick(root,config,**kw);assert len([x for x in r["reports"] if x["type"]=="reflection"])==50
    assert tick(root,config,**kw)==r and calls==["macro","nist"]
    with pytest.raises(ValueError):tick(root,config|{"reflect":False},**kw)
def test_prior_crash_no_blind_retry(tmp_path):
    root=tmp_path/"private";config={"macro_policies":[{"series_id":"fixture"}],"reflect":False}
    def crash(p):raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):tick(root,config,network=True,clock=lambda:T,macro_runner=crash)
    assert tick(root,config,network=True,clock=lambda:T)["status"]=="UNRESOLVED_TICK_NO_RETRY"
    assert tick(root,config,network=True,clock=lambda:T+timedelta(days=1))["status"]=="PRIOR_TICK_UNRESOLVED"
