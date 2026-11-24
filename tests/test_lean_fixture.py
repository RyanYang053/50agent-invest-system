from copy import deepcopy
import json
import zipfile
import pytest
from atlas_pro.lean_fixture import prepare,verify,read_receipt,MARKER,KIND

def receipt():
    return {"kind":KIND,"live_mode":False,"bars":{
        "2020-01-02":{"count":10,"close_min":100,"close_max":100},
        "2020-01-03":{"count":10,"close_min":110,"close_max":110}},
        "fills":[{"order_id":1,"symbol":"ATLASFICT","quantity":10,"price":100,"fee":1,"fee_currency":"USD","date":"2020-01-02"},
                 {"order_id":2,"symbol":"ATLASFICT","quantity":-10,"price":110,"fee":1,"fee_currency":"USD","date":"2020-01-03"}],
        "ending_quantity":0,"ending_cash":10098,"ending_nav":10098}

def test_deterministic_fixture(tmp_path):
    a=tmp_path/"a";b=tmp_path/"b";a.mkdir();b.mkdir()
    assert prepare(a)==prepare(b)
    p=a/"minute/atlasfict/20200102_trade.zip"
    with zipfile.ZipFile(p) as z:
        rows=z.read("20200102_atlasfict_minute_trade.csv").decode().splitlines()
    assert len(rows)==10
    assert rows[0]=="34200000,1000000,1000000,1000000,1000000,1000"
    with pytest.raises(ValueError):prepare(a)

def test_independent_accounting():
    r=verify(receipt())
    assert r["ending_cash"]==10098 and r["fees"]==2
    assert r["simulated_net_pnl"]==98 and r["synthetic"]
    assert r["can_trade"] is False and r["promotion_allowed"] is False

@pytest.mark.parametrize("defect",["live","missing_bar","wrong_price","fee","quantity","missing_fill","duplicate_order","wrong_cash","wrong_nav","nonfinite"])
def test_bad_receipt_rejected(defect):
    r=receipt()
    if defect=="live":r["live_mode"]=True
    elif defect=="missing_bar":r["bars"]["2020-01-02"]["count"]=9
    elif defect=="wrong_price":r["fills"][0]["price"]=99
    elif defect=="fee":r["fills"][0]["fee"]=0
    elif defect=="quantity":r["fills"][1]["quantity"]=-9
    elif defect=="missing_fill":r["fills"].pop()
    elif defect=="duplicate_order":r["fills"][1]["order_id"]=1
    elif defect=="wrong_cash":r["ending_cash"]+=1
    elif defect=="wrong_nav":r["ending_nav"]+=1
    elif defect=="nonfinite":r["ending_cash"]=float("inf")
    with pytest.raises(ValueError):verify(r)

def test_log_receipt(tmp_path):
    p=tmp_path/"engine.log";r=receipt();line="DEBUG: "+MARKER+json.dumps(r)
    p.write_text(line+"\n"+line+"\n")
    observed,h=read_receipt(p)
    assert observed==r and len(h)==64
    p.write_text(line+"\n"+MARKER+json.dumps({**r,"ending_nav":0}))
    with pytest.raises(ValueError):read_receipt(p)
    p.write_text("no report")
    with pytest.raises(ValueError):read_receipt(p)
