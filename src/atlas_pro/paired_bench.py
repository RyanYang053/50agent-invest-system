"""Opt-in paired public numeric challenger evaluation (never role certification)."""
from __future__ import annotations
import argparse,json,os
from pathlib import Path
from decimal import Decimal
from .bench_runner import run_numeric_eval
from .skill_evolution import Evolution
from .core_service import private_dir
from .runtime import FixedModelTransport
from .models import ModelGateway
from .ledger import digest
from .oss_adapters import artifact_json

def run_pair(gateway,transport,evolution,cases,*,proposal_id,locked_hash,model_id,run_id,journal_path,total_budget_usd,at=None,confirmed=False):
    if confirmed is not True:raise PermissionError("explicit paired evaluation and spending approval")
    p=evolution.preview(proposal_id)["proposal"]
    if digest(cases)!=locked_hash:raise ValueError("locked numeric testset mismatch")
    total=Decimal(str(total_budget_usd))
    if not total.is_finite() or total<0:raise ValueError("invalid evaluation budget")
    # Fixed half budgets, no dynamic transfer and no second run after unresolved first.
    args=dict(locked_hash=locked_hash,role_id=p["role_id"],model_id=model_id,journal_path=journal_path,max_budget_usd=str(total/2),at=at,confirmed=True)
    variant={"check":p["check"],"base_runtime":p["base_runtime"]}
    base=run_numeric_eval(gateway,transport,cases,run_id=digest({"run":run_id,"proposal":proposal_id,"kind":"baseline"}),variant=variant|{"kind":"baseline"},**args)
    if base.get("status")!="EVALUATION_REVIEW_ONLY" or base.get("failed"):return {"status":"BASELINE_BLOCKED","baseline":base,"can_trade":False}
    challenger=run_numeric_eval(gateway,transport,cases,run_id=digest({"run":run_id,"proposal":proposal_id,"kind":"challenger"}),variant=variant|{"kind":"challenger"},**args)
    if challenger.get("status")!="EVALUATION_REVIEW_ONLY" or challenger.get("failed"):return {"status":"CHALLENGER_BLOCKED","baseline":base,"challenger":challenger,"can_trade":False}
    b={r["case_id"]:r for r in base["grade"]["results"]};c={r["case_id"]:r for r in challenger["grade"]["results"]}
    return {"status":"PAIRED_NUMERIC_REVIEW_ONLY","proposal_id":proposal_id,"candidate_pack_hash":p["candidate_pack_hash"],"locked_testset_hash":locked_hash,"baseline":base,"challenger":challenger,"wins":sum(c[k]["pass"] and not b[k]["pass"] for k in b),"losses":sum(b[k]["pass"] and not c[k]["pass"] for k in b),"promotion_allowed":False,"can_trade":False,"limitations":["numeric extraction only, not professional task certification","requires separately locked independent role benchmark and signed review"]}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("registry","roles","cases","data-dir"):p.add_argument("--"+k,type=Path,required=True)
    for k in ("cases-sha256","locked-hash","proposal-id","model","run-id","total-budget-usd"):p.add_argument("--"+k,required=True)
    p.add_argument("--confirm-evaluation-and-spend",action="store_true")
    a=p.parse_args(argv)
    if not a.confirm_evaluation_and_spend:raise PermissionError("explicit paired spending approval")
    os.umask(0o077);d=private_dir(a.data_dir)
    g=ModelGateway(d/"models.sqlite",json.loads(a.registry.read_text()),json.loads(a.roles.read_text()),daily_limit_usd="0",monthly_limit_usd="0")
    out=run_pair(g,FixedModelTransport(enabled=True),Evolution(d/"skill-evolution"),artifact_json(a.cases,a.cases_sha256),proposal_id=a.proposal_id,locked_hash=a.locked_hash,model_id=a.model,run_id=a.run_id,journal_path=d/"paired-eval.sqlite",total_budget_usd=a.total_budget_usd,confirmed=True)
    print(json.dumps(out,indent=2,allow_nan=False));return 0
if __name__=="__main__":raise SystemExit(main())
