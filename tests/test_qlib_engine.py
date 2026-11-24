"""Actual Qlib integration, executed in its dedicated network-isolated CI image."""
import pytest
from atlas_pro.quant_train import synthetic_panel,train_panel
from atlas_pro.qlib_engine import fit_predict
from atlas_pro.ledger import digest

def test_optional_qlib_engine():
    pytest.importorskip("qlib")
    p=synthetic_panel()
    r=train_panel(p,include_qlib=True)
    assert r["synthetic"] and not r["promotion_allowed"] and not r["can_trade"]
    assert len(r["external_engine_receipts"])==r["folds"]
    q=r["models"]["qlib_ridge"]["predictions"];b=r["models"]["ridge"]["predictions"]
    assert len(q)==len(b)>0
    assert [v["id"] for v in q]==[v["id"] for v in b]
    assert max(abs(v["prediction"]-w["prediction"]) for v,w in zip(q,b))<1e-8
    assert all(v["test_labels_supplied"] is False and v["engine"]=="qlib" and v["version"]=="0.9.7" for v in r["external_engine_receipts"])

def test_test_labels_rejected_and_train_availability():
    pytest.importorskip("qlib")
    p=synthetic_panel(10);rows=p["rows"]
    train=rows[:8];test=rows[24:32]
    with pytest.raises(ValueError,match="test labels"):fit_predict(train,test,p["feature_names"])
    valid=[{k:r[k] for k in ("id","security_id","signal_at","features")} for r in test]
    invalid=[dict(r,label_available_at=test[0]["signal_at"]) for r in train]
    with pytest.raises(ValueError,match="leakage"):fit_predict(invalid,valid,p["feature_names"])
