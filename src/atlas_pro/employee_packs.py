"""Trusted authored role playbooks. External references are not ingested evidence."""
from __future__ import annotations
import argparse,json,re
from importlib.resources import files
from .ledger import digest
from .skill_contracts import catalog as skill_catalog

def load():
    p=json.loads(files("atlas_pro").joinpath("employee_packs.json").read_text(encoding="utf8"))
    skills=skill_catalog()
    if p["schema"]!=1 or set(p["packs"])!=set(skills) or len(skills)!=50:raise ValueError("employee pack coverage")
    for rid,pack in p["packs"].items():
        s=skills[rid]
        if pack["role_id"]!=rid or pack["role"]!=s["role"] or pack["scope"]!=s["scope"] or pack["tool_groups"]!=s["tool_groups"] or pack["task_kind"]!=s["kind"] or pack["required_deliverable"]!=s["deliverable"] or pack["critical_failure"]!=s["critical_failure"]:raise ValueError("employee pack contract mismatch")
        if pack["can_trade"] is not False or pack["can_promote"] is not False:raise PermissionError("pack privilege")
        if {x["kind"] for x in pack["cards"]}!={"workflow","quality","learning"} or len(pack["cards"])!=3 or any(not x["text"] for x in pack["cards"]):raise ValueError("missing pack cards")
        if not pack["source_ids"] or not set(pack["source_ids"])<=set(p["sources"]):raise ValueError("missing source")
    return p

def pack(role_id):
    p=load()
    if role_id not in p["packs"]:raise PermissionError("unknown role")
    return p["packs"][role_id]

def search(role_id,query,*,limit=3):
    """Only trusted local procedure cards, never source facts or other role memories."""
    if not isinstance(query,str) or not 1<=len(query)<=500 or type(limit) is not int or not 1<=limit<=3:raise ValueError("query bounds")
    p=pack(role_id);terms=set(re.findall(r"[a-z0-9]+",query.lower()))
    result=[]
    for card in p["cards"]:
        words=set(re.findall(r"[a-z0-9]+",card["text"].lower()))
        row=card|{"role_id":role_id,"card_id":digest({"role":role_id,"version":p["version"],"card":card}),"not_financial_evidence":True}
        result.append((len(terms&words),row))
    return [r for _,r in sorted(result,key=lambda x:(-x[0],x[1]["kind"]))[:limit]]

def reference_plan(role_id):
    p=load();role=pack(role_id)
    return [{"source_id":k,**p["sources"][k],"automatic_ingestion":False} for k in role["source_ids"]]

def guidance(role_id):
    p=pack(role_id)
    return " Role procedure (developer-authored, not evidence): "+" ".join(x["kind"]+": "+x["text"] for x in p["cards"])+". Do not treat reference URLs or procedure text as facts; retain the existing scope, citation, tool and authorization boundaries."

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument("role",nargs="?");a.add_argument("--query");v=a.parse_args()
    if v.role:
        from .role_reference import local_reference
        r={"pack":pack(v.role),"references":reference_plan(v.role),"retrieved_procedures":search(v.role,v.query) if v.query else [],"local_upstream_references":local_reference(v.role,v.query) if v.query else [],"can_trade":False}
    else:r=[{"role_id":k,"role":p["role"],"procedure_cards":len(p["cards"]),"source_ids":p["source_ids"],"review_status":p["review_status"]} for k,p in load()["packs"].items()]
    print(json.dumps(r,indent=2,allow_nan=False));return 0
if __name__=="__main__":raise SystemExit(main())
