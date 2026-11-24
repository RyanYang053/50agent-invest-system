from datetime import datetime,timezone,timedelta
from pathlib import Path
import hashlib,json
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from atlas_pro.skill_evolution import Evolution,paired_grade,CHECKS
from atlas_pro.skill_contracts import catalog,runtime_hash
from atlas_pro.employee_packs import load
from atlas_pro.ledger import digest
from atlas_pro.independent_review import strict_json

T=datetime(2026,11,24,12,tzinfo=timezone.utc)
@pytest.fixture
def state(tmp_path):
    clock=[T];return Evolution(tmp_path/"e",clock=lambda:clock[0].isoformat()),clock,tmp_path
def reasons():return [digest(i) for i in range(3)]
@pytest.mark.parametrize("rid",sorted(catalog()))
def test_propose_isolation(state,rid):
    e,clock,_=state
    rows=[{"role_id":rid,"status":"NO_EVIDENCE","result_hash":h} for h in reasons()]
    ids=e.reflect(rid,rows);assert len(ids)==1
    assert e.reflect(rid,rows)==ids
    p=e.preview(ids[0]);orig=load();changed=p["employee_packs"]
    assert [k for k in orig["packs"] if orig["packs"][k]!=changed["packs"][k]]==[rid]
    assert orig["sources"]==changed["sources"] and not changed["packs"][rid]["can_trade"]
    assert CHECKS["evidence"] in next(x["text"] for x in changed["packs"][rid]["cards"] if x["kind"]=="quality")
    with pytest.raises(PermissionError):e.reflect(rid,[rows[0]|{"role_id":"BAD"}])
def blob(root,value):
    raw=strict_json(value);h=hashlib.sha256(raw).hexdigest();(root/h).write_bytes(raw);return h
def campaign(state):
    e,clock,root=state;pid=e.propose("A041","numeric",reasons());p=e.preview(pid)["proposal"]
    cases=[{"id":str(i),"negative":i<20,"input_hash":digest({"input":i})} for i in range(100)]
    test=blob(root,{"cases":cases});rubric=blob(root,{"rubric":"fixture"})
    lid=e.lock(pid,cases,testset_hash=test,rubric_hash=rubric,confirmed=True)
    clock[0]+=timedelta(seconds=1)
    rows=[]
    for i,c in enumerate(cases):
        rows.append({"id":c["id"],"baseline_pass":i<90,"challenger_pass":True,"challenger_boundary_pass":True,"baseline_answer_hash":blob(root,{"baseline":i}),"challenger_answer_hash":blob(root,{"challenger":i})})
    return pid,p,lid,cases,rows
def test_paired_grade_safety(state):
    _,_,_,cases,rows=campaign(state)
    g=paired_grade(cases,rows);assert g["passes"] and g["wins"]==10 and g["p_one_sided"]==pytest.approx(1/1024)
    rows[0]["challenger_boundary_pass"]=False
    assert not paired_grade(cases,rows)["passes"]
    rows[0]["challenger_boundary_pass"]=True;rows[21]["challenger_pass"]=False
    assert not paired_grade(cases,rows)["passes"]
def test_staged_release_signed_and_rollback(state):
    e,clock,root=state;pid,p,lid,cases,rows=campaign(state)
    r=e.evaluate(lid,rows,artifact_dir=root);assert r["passes"] and not r["promotion_allowed"]
    with pytest.raises(ValueError):e.evaluate(lid,rows,artifact_dir=root)
    clock[0]+=timedelta(seconds=1)
    payload={"kind":"SKILL_CHALLENGER_V1","role_id":"A041","proposal_id":pid,"lock_id":lid,"evaluation_hash":r["evaluation_hash"],"base_runtime":p["base_runtime"],"candidate_pack_hash":p["candidate_pack_hash"],"holdout_independence_verified":True,"real_tasks_verified":True,"data_rights_verified":True,"candidate_executed_verified":True,"baseline_executed_verified":True,"no_privilege_change_verified":True,"producer_organization":"producer","reviewed_at":clock[0].isoformat(),"valid_until":(clock[0]+timedelta(days=1)).isoformat()}
    trust={};sigs=[]
    for i,role in enumerate(("domain_reviewer","independent_validator")):
        key=Ed25519PrivateKey.generate();rid=str(i)
        trust[rid]={"revoked":False,"role":role,"organization":"org"+rid,"identity":"person"+rid,"public_key":key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw).hex()}
        sigs.append({"reviewer_id":rid,"signature":key.sign(strict_json(payload)).hex()})
    envelope={"payload":payload,"signatures":sigs}
    with pytest.raises(PermissionError):e.stage(lid,envelope,trust,artifact_dir=root)
    assert e.stage(lid,envelope,trust,artifact_dir=root,owner_confirmed=True)["status"]=="STAGED_REVIEWED_RELEASE"
    out=e.export("A041",trust);assert digest(out["employee_packs"])==p["candidate_pack_hash"] and not out["live_activation"]
    with pytest.raises(ValueError):e.export("A042",trust)
    trust["0"]["revoked"]=True
    with pytest.raises(PermissionError):e.export("A041",trust)
    assert e.rollback("A041",owner_confirmed=True)["status"]=="STAGING_ROLLED_BACK"
    assert not e.status()["staged_roles"]
def test_holdout_cannot_be_reused(state):
    e,clock,root=state;pid,p,lid,cases,rows=campaign(state)
    other=e.propose("A041","uncertainty",reasons())
    with pytest.raises(ValueError):e.lock(other,cases,testset_hash=digest("x"),rubric_hash=digest("y"),confirmed=True)
    changed=[x|{"id":"alias"+x["id"]} for x in cases]
    with pytest.raises(ValueError):e.lock(other,changed,testset_hash=digest("x"),rubric_hash=digest("y"),confirmed=True)
