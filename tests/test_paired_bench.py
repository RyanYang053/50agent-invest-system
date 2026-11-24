from pathlib import Path
import json
import pytest
from atlas_pro.models import ModelGateway
from atlas_pro.skill_evolution import Evolution,CHECKS
from atlas_pro.paired_bench import run_pair
from atlas_pro.ledger import digest

ROOT=Path(__file__).resolve().parents[1]
AT="2026-11-23T18:00:00Z"
def test_paired_bench_uses_two_distinct_prompts_and_budget(tmp_path):
    roles=json.loads((ROOT/"config/50 agent manifest.json").read_text());reg=json.loads((ROOT/"config/model registry.json").read_text())
    g=ModelGateway(tmp_path/"m",reg,roles);e=Evolution(tmp_path/"e")
    pid=e.propose("A011","numeric",[digest(i) for i in range(3)])
    cases=[{"case_id":"fixture","question":"What is reported revenue?","documents":[{"doc_id":"e","text":"Reported revenue is 42.","scope":"public","available_at":"2026-11-23T17:59:30Z"}],"decision_at":AT,"evaluation_rights_verified":True,"cloud_evaluation_allowed":True,"synthetic":True,"expected_values":{"revenue":42},"allowed_evidence_ids":["e"]}]
    calls=[]
    def transport(provider,body):
        calls.append(body)
        assert "expected_values" not in body["input"] and body["tools"]==[]
        return {"model":body["model"],"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":'{"values":{"revenue":42},"evidence_ids":["e"],"abstain":false}'}]}],"usage":{"input_tokens":100,"output_tokens":20}}
    kw=dict(proposal_id=pid,locked_hash=digest(cases),model_id="gpt-6.2-sol",run_id="pair",journal_path=tmp_path/"eval",total_budget_usd="2",at=AT)
    with pytest.raises(PermissionError):run_pair(g,transport,e,cases,**kw)
    r=run_pair(g,transport,e,cases,**kw,confirmed=True)
    assert r["status"]=="PAIRED_NUMERIC_REVIEW_ONLY" and len(calls)==2
    assert CHECKS["numeric"] not in calls[0]["instructions"] and CHECKS["numeric"] in calls[1]["instructions"]
    assert not r["promotion_allowed"] and r["baseline"]["grade"]["synthetic_or_unspecified"]
    assert run_pair(g,transport,e,cases,**kw,confirmed=True)==r and len(calls)==2
    with pytest.raises(PermissionError):run_pair(g,transport,e,cases,**(kw|{"run_id":"too-low","total_budget_usd":"0"}),confirmed=True)
