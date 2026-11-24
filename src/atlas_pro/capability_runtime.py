"""Version-pinned, role-scoped reference loading at task dispatch.

Raw reference text stays local. Only developer-authored method adaptations
bound to exact source blobs may enter a public model's instruction context.
A source route is not evidence of live connectivity or engine execution.
"""
from __future__ import annotations
import hashlib,re
from importlib.resources import files
from .employee_packs import pack, reference_plan, guidance
from .skill_contracts import contract
from .role_reference import local_reference
from .ledger import digest

# Original, bounded method adaptations, reviewed against the indicated bundled
# reference. Do not inherit upstream tool permissions or executable instructions.
METHODS={
    "dcf":("cc17fc002b7e739d00e6b62c4c7a3a806b6f3f22","Separate sourced historical inputs from assumptions; reconcile enterprise and equity value; expose WACC and terminal-value sensitivity."),
    "comps":("8eea74c4f9c91e449657ca51d8e2c7f106f601dd","Use economically comparable peers, normalize period and enterprise-value conventions, and identify outliers rather than averaging incomparable firms."),
    "competitive":("2632b3d1507424ac2d81578c7e05f81e7d54791d","Define competitive scope and peer set; compare on consistent dimensions and state strategic implications with evidence."),
    "earnings":("447de2f9ec277f976eb2b52501465250c80e1adf","Separate new reported results from prior expectations and guidance; quantify only supported variances and explain their thesis implications."),
    "unit":("52a3ed8dcb6e6cb296b35f7fb46620cbc7edb21f","Select metrics appropriate to revenue model; reconcile cohort, retention and acquisition economics with explicitly aligned definitions."),
    "ic":("70cb5d2bcd45309e335bcc3638392c752aa9da0b","Synthesize business, historical financials, thesis, scenarios and risks while retaining dissent and unresolved inputs; never imply approval."),
    "nav":("fa0824343cdba6ac995958cafcd80952fcbd95c0","Independently recompute roll-forward and reconcile component totals to the authoritative statement; preserve differences for review."),
    "qlib":("eeddaec60d01f510160c6555e38af0c4fbbba772","Separate raw market data, feature transformations, fitted preprocessing and model datasets; check temporal availability."),
    "rd":("d5c87919e040af97811d2c20ff27565d7963fede","Translate a research hypothesis into a reproducible candidate experiment; record baseline, implementation and evaluation feedback without self-promotion."),
    "lean":("b352780b83e4da76837cdac623d3d36597639852","Treat simulation as event-driven research; distinguish historical event order, modeled fills and real execution. No order access."),
    "skfolio":("139a567f4109a9cf420477ba49eef72b3a066e2b","Report portfolio risk on aligned return observations; distinguish periodic inputs from annualized reporting and keep drawdown conventions explicit."),
    "edgar":("06dc6dff89629a389d59eca12eee152d66f69fcd","Trace structured financial statements and extracted text back to the original SEC filing; preserve filing identity and context."),
    "quantlib":("6f6c9ca80df9415e62b6a09971b3b31190e2941d","Separate instrument conventions, market inputs and valuation model; do not claim external pricing or risk-engine execution without an actual validated run."),
    "qlibworkflow":("f2fbc14e6f7b829ad4400eb7d8004eff1d55b723","Version data loading, processing, train/test slices, model artifacts and backtest settings; record all experimental outputs."),
    "skfoliobacktest":("004f72450629e7d93de521035ef92dca4d8a76a4","Distinguish target from drifted weights, geometric compounding and transaction costs; compare competing allocations over matched out-of-sample dates."),
    "atlas_cycle_review":("babd61a85add0098ef86a93f0c43fdde5b36d3cc","Diagnose credit and valuation cycles using only pre-cutoff observations; distinguish percentile ranks from forecast probabilities."),
    "atlas_rates_credit":("8fc5dc61a68b3e396cad4cd9a664ba77977a10d4","Match currency, tenor and units; separate duration and credit sensitivity and preserve uncertainty about term premium."),
    "atlas_liquidity_conditions":("b809a4e28ca994db2f30c8856ffc913361033d63","Distinguish funding liquidity, market depth and aggregate financial conditions; use lagged proxies and test alternative explanations."),
    "atlas_release_vintage":("300baa835081ea68aa532788ef98e87b9d39d6c4","Keep first releases and revisions distinct; compare surprises only against verified pre-release expectations."),
    "atlas_fx_commodity":("073a32a7d51b1843da16c6845b7295c1b3e2254f","Verify currency orientation and contract maturity; combine asset and FX returns consistently and distinguish spot from rolled futures."),
    "atlas_canadian_tax_review":("62c5cd4fd10f21968a508fd920ee2a006341d25c","Verify current rules for the actual account and transaction date; never infer contribution room from NAV or losses. Keep records local."),
    "atlas_forecast_calibration":("a40f81c71e5d6a6be5305e6488a2356190083cfc","Freeze probability, event, horizon and baseline before resolution; measure calibration and account for dependent observations."),
}
# Route descriptions report existing implementation or missing integration.
# No URL, API credential, dataset, or engine is accessed by this loader.
ROUTES={
    "sec":"existing_adapter_requires_rights_and_live_validation",
    "damodaran":"external_method_not_ingested_rights_review_required",
    "french":"existing_research_archive_workflow_not_live_or_pit_certified",
    "cra":"official_guidance_not_ingested_current_rule_review_required",
    "financebench":"evaluation_only_never_learning_or_prompt",
    "atlas":"internal_runtime_present_not_independent_certification",
    "alfred":"existing_vintage_adapter_requires_rights_and_live_validation",
    "bls":"bls_adapter_implemented_requires_rights_and_live_validation",
    "boc":"existing_valet_adapter_requires_rights_and_live_validation",
    "occ":"official_guidance_not_ingested_rights_review_required",
    "nist":"official_guidance_not_ingested_rights_review_required",
}

def load_role_context(role_id):
    """Return trusted method context and a non-sensitive, locally generated receipt.

    Queries are fixed by the role contract, never free-form account inputs.
    All assigned packaged documents are verified even if retrieval finds no match.
    Retrieved raw text is never returned to the model or persisted in job receipts.
    """
    p=pack(role_id); c=contract(role_id)
    query=(c.get("research_query") or c["method"])[:500]
    root=files("atlas_pro").joinpath("reference_library")
    methods=[]; verified=[]; routes=[]
    for s in reference_plan(role_id):
        sid=s["source_id"]; name=s.get("local_reference")
        if not name:
            if sid not in ROUTES:raise ValueError("unclassified external source")
            routes.append({"source_id":sid,"status":ROUTES[sid]})
            continue
        if s.get("license") not in ("Apache-2.0","MIT","BSD-3-Clause","Atlas-authored") or not re.fullmatch(r"[a-z0-9_]+\.(md|rst)",name):
            raise PermissionError("reference license or filename")
        raw=root.joinpath(name).read_bytes()
        if len(raw)>250000:raise ValueError("reference too large")
        actual=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
        if actual!=s["git_blob_sha1"] or sid not in METHODS or METHODS[sid][0]!=actual:
            raise ValueError("reference or method adaptation version mismatch")
        raw.decode("utf8")
        methods.append({"source_id":sid,"method":METHODS[sid][1]})
        verified.append({"source_id":sid,"blob_sha1":actual})
    if not verified:raise ValueError("role lacks verified reference")
    hits=local_reference(role_id,query,limit=5)
    if any(h["role_id"]!=role_id or h["source_id"] not in {v["source_id"] for v in verified} for h in hits):
        raise PermissionError("reference scope violation")
    receipt={"role_id":role_id,"pack_version":p["version"],"verified_references":verified,
             "method_ids":[m["source_id"] for m in methods],
             "retrieved_excerpts":[{k:h[k] for k in ("source_id","excerpt_start","excerpt_end","excerpt_sha256")} for h in hits],
             "unbundled_routes":routes,"raw_reference_cloud_allowed":False,
             "external_engine_executed":False,"professional_competence_verified":False}
    receipt["context_hash"]=digest(receipt)
    return {"instructions":guidance(role_id)+" Reference-informed Atlas method checks (not financial evidence; apply only within assigned scope): "+" ".join(m["method"] for m in methods),
            "receipt":receipt}
