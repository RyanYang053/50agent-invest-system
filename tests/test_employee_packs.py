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
