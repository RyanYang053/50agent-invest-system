import itertools
import pytest
from atlas_pro.employee_packs import load,pack,search,reference_plan,guidance
from atlas_pro.skill_contracts import catalog,runtime_hash

def test_all_employee_packs():
    p=load()
    assert set(p["packs"])==set(catalog())
    cards=[c["text"] for v in p["packs"].values() for c in v["cards"]]
    assert len(cards)==len(set(cards))==150
    for rid,v in p["packs"].items():
        assert len(reference_plan(rid))>=2
        assert all(not s["automatic_ingestion"] for s in reference_plan(rid))
        assert len(runtime_hash(rid))==64
        assert v["cards"][0]["text"] in guidance(rid)
        assert not v["can_trade"]

@pytest.mark.parametrize("rid",sorted(catalog()))
def test_role_retrieval_boundary(rid):
    r=search(rid,"valuation risk evidence",limit=3)
    assert len(r)==3 and all(x["role_id"]==rid and x["not_financial_evidence"] for x in r)
    assert {x["text"] for x in r}=={x["text"] for x in pack(rid)["cards"]}
    other={c["text"] for k,v in load()["packs"].items() if k!=rid for c in v["cards"]}
    assert not {x["text"] for x in r}&other

def test_unknown_and_bad_query():
    with pytest.raises(PermissionError):search("A999","valuation")
    with pytest.raises(ValueError):search("A041","x",limit=10)

def test_benchmark_is_not_learning_source():
    assert load()["sources"]["financebench"]["kind"]=="evaluation_only"
    assert all(not s["automatic_ingestion"] for s in reference_plan("A102"))


def test_upstream_reference_is_actual_pinned_text_and_isolated():
    from atlas_pro.role_reference import local_reference
    from importlib.resources import files
    import hashlib
    p=load()
    for rid,role in p["packs"].items():
        for hit in local_reference(rid,"cash flow valuation financial capital"):
            assert hit["source_id"] in role["source_ids"]
            assert hit["local_only"] and hit["untrusted_source_text"] and hit["not_financial_evidence"]
            source=p["sources"][hit["source_id"]]
            body=files("atlas_pro").joinpath("reference_library",source["local_reference"]).read_text(encoding="utf8")
            assert body[hit["excerpt_start"]:hit["excerpt_end"]]==hit["text"]
            assert hashlib.sha256(hit["text"].encode()).hexdigest()==hit["excerpt_sha256"]
    results=local_reference("A041","WACC terminal value")
    assert results and {x["source_id"] for x in results}=={"dcf"}
    assert all(x["source_id"]!="dcf" for x in local_reference("A082","WACC terminal value"))
    assert not local_reference("A085","tax")
