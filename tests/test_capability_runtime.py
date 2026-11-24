"""Developer integration tests; no external model, data or broker calls."""
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from atlas_pro.capability_runtime import load_role_context, METHODS, ROUTES
from atlas_pro.employee_packs import load, reference_plan
from atlas_pro.role_jobs import RoleExecutor, PUBLIC_TASKS, LOCAL_TASKS
from atlas_pro.runtime import ResearchModelRunner
from atlas_pro.skill_contracts import catalog, task_id
from atlas_pro.ledger import EvidenceLedger

ROOT=Path(__file__).resolve().parents[1]
ROLES=json.loads((ROOT/"config/50 agent manifest.json").read_text())
AT="2026-11-23T18:00:00Z"

@pytest.mark.parametrize("role_id",sorted(catalog()))
def test_role_reference_context(role_id):
    ctx=load_role_context(role_id); r=ctx["receipt"]
    sources=reference_plan(role_id)
    expected={x["source_id"] for x in sources if x.get("local_reference")}
    assert expected and expected==set(r["method_ids"])=={x["source_id"] for x in r["verified_references"]}
    assert {x["source_id"] for x in r["unbundled_routes"]}=={x["source_id"] for x in sources if not x.get("local_reference")}
    assert all(h["source_id"] in expected for h in r["retrieved_excerpts"])
    assert r["role_id"]==role_id and r["raw_reference_cloud_allowed"] is False
    assert r["professional_competence_verified"] is False and r["external_engine_executed"] is False
    assert all(METHODS[k][1] in ctx["instructions"] for k in expected)
    assert load_role_context(role_id)==ctx

def test_all_sources_classified_and_eval_isolated():
    sources=load()["sources"]
    assert set(sources)==set(METHODS)|set(ROUTES)
    assert not set(METHODS)&set(ROUTES)
    assert ROUTES["financebench"]=="evaluation_only_never_learning_or_prompt"

@pytest.mark.parametrize("role_id",sorted(PUBLIC_TASKS))
def test_actual_public_prompt_role_scoped(role_id):
    role=next(x for x in ROLES if x["agent_id"]==role_id)
    class Gateway:
        roles={role_id:role}
        registry={"fake":{"provider":"openai","model_id":"fixture"}}
        def select_and_reserve(self,**kwargs):
            assert kwargs["role_id"]==role_id
            return {"status":"RESERVED","model":"fake"}
    class Index:
        def search(self,*args,**kwargs):return [{"doc_id":"e","text":"synthetic evidence"}]
    calls=[]
    def transport(provider,body):
        calls.append(body)
        return {"status":"completed","model":"fixture","output":[{"type":"message","content":[{"type":"output_text","text":json.dumps({"claims":[],"uncertainties":[],"countercase":"fixture"})}]}],"usage":{"input_tokens":10,"output_tokens":10}}
    kind,query=PUBLIC_TASKS[role_id]
    r=ResearchModelRunner(Gateway(),Index(),transport).run(role_id=role_id,task_set=task_id(role_id),request_id="r",security_id="MACRO:US" if kind=="macro" else "CIK:1",query=query,at=AT)
    assert r["status"]=="UNVERIFIED_RESEARCH_MEMO" and len(calls)==1
    allowed=set(r["reference_context"]["method_ids"])
    for source,(_,method) in METHODS.items():
        assert (method in calls[0]["instructions"])==(source in allowed)
    assert calls[0]["tools"]==[] and calls[0]["store"] is False
    assert set(json.loads(calls[0]["input"]))=={"question","documents","role_memory_annotations"}
    assert "excerpt_sha256" not in calls[0]["input"]

@pytest.mark.parametrize("role_id",sorted(LOCAL_TASKS))
def test_local_dispatch_loads_context_before_handler(role_id,tmp_path):
    executor=RoleExecutor(ROLES,EvidenceLedger(tmp_path/"e"))
    with patch.object(executor,"_local",return_value={"status":"FIXTURE"}) as handler:
        r=executor.run(role_id,at=AT,run_id="fixture",inputs={})
    handler.assert_called_once_with(LOCAL_TASKS[role_id],{},AT)
    assert r["reference_context"]["role_id"]==role_id and not r["can_trade"]

def test_reference_failure_blocks_handler(tmp_path):
    executor=RoleExecutor(ROLES,EvidenceLedger(tmp_path/"e"))
    with patch("atlas_pro.capability_runtime.load_role_context",side_effect=ValueError("bad hash")),patch.object(executor,"_local") as handler:
        r=executor.run("A041",at=AT,run_id="fixture",inputs={})
    handler.assert_not_called()
    assert r["status"]=="BLOCKED_ROLE_REFERENCE_INTEGRITY" and not r["can_trade"]
