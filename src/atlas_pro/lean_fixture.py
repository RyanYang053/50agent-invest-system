"""Prepare and verify a deterministic synthetic LEAN accounting fixture.
No data download, real securities, executable strategy import or broker access.
"""
from __future__ import annotations
import argparse,hashlib,json,math,os,re,zipfile
from pathlib import Path
from decimal import Decimal,InvalidOperation
from .ledger import digest

SYMBOL="ATLASFICT"
DAYS={"2020-01-02":100,"2020-01-03":110}
KIND="ATLAS_LEAN_SYNTHETIC_ACCOUNTING_V1"
MARKER="ATLAS_LEAN_RECEIPT:"

def prepare(root):
    root=Path(root)
    if not root.is_dir() or root.is_symlink() or any(root.iterdir()):raise ValueError("empty staging directory required")
    root.chmod(0o755)
    for rel in ("minute/atlasfict","daily","map_files","factor_files"):
        p=root/rel;p.mkdir(parents=True,exist_ok=True);p.chmod(0o755)
        if rel.startswith("minute/"):(root/"minute").chmod(0o755)
    daily=[]
    for date,price in DAYS.items():
        day=date.replace("-","");scaled=price*10000
        rows=[f"{(9*60+30+i)*60000},{scaled},{scaled},{scaled},{scaled},1000" for i in range(10)]
        _zip(root/"minute/atlasfict"/(day+"_trade.zip"),day+"_atlasfict_minute_trade.csv","\n".join(rows)+"\n")
        daily.append(f"{day} 00:00,{scaled},{scaled},{scaled},{scaled},10000")
    _zip(root/"daily/atlasfict.zip","atlasfict.csv","\n".join(daily)+"\n")
    # Fictional symbol, no corporate actions. Never copy a provider security master.
    (root/"map_files/atlasfict.csv").write_text("20190101,atlasfict,Q\n20501231,atlasfict,Q\n",encoding="ascii")
    (root/"factor_files/atlasfict.csv").write_text("20190101,1,1,0\n20501231,1,1,0\n",encoding="ascii")
    for p in root.rglob("*"):
        if p.is_file():p.chmod(0o444)
    return manifest(root)

def _zip(path,name,body):
    with zipfile.ZipFile(path,"w") as z:
        i=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));i.compress_type=zipfile.ZIP_DEFLATED
        z.writestr(i,body.encode("ascii"))

def manifest(root):
    root=Path(root)
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}

def number(value):
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError("nonfinite/non-numeric receipt")
    return Decimal(str(value))

def verify(receipt):
    if not isinstance(receipt,dict) or set(receipt)!={"kind","live_mode","bars","fills","ending_quantity","ending_cash","ending_nav"} or receipt["kind"]!=KIND or receipt["live_mode"] is not False:raise ValueError("wrong runtime receipt")
    bars=receipt["bars"]
    if not isinstance(bars,dict) or set(bars)!=set(DAYS):raise ValueError("missing fixture observations")
    for day,expected in DAYS.items():
        row=bars[day]
        if set(row)!={"count","close_min","close_max"} or type(row["count"]) is not int or row["count"]!=10 or number(row["close_min"])!=expected or number(row["close_max"])!=expected:raise ValueError("unexpected observed synthetic bars")
    fills=receipt["fills"]
    if not isinstance(fills,list) or len(fills)!=2:raise ValueError("exactly two simulated fills required")
    cash=Decimal(10000);quantity=Decimal(0);ids=set();fees=Decimal(0)
    for row,(date,price),qty in zip(fills,DAYS.items(),(10,-10)):
        if set(row)!={"order_id","symbol","quantity","price","fee","fee_currency","date"} or type(row["order_id"]) is not int or row["order_id"]<=0 or row["order_id"] in ids or row["symbol"]!=SYMBOL or row["fee_currency"]!="USD" or row["date"]!=date:raise ValueError("fill identity mismatch")
        ids.add(row["order_id"]);q,p,f=map(number,(row["quantity"],row["price"],row["fee"]))
        if q!=qty or p!=price or f!=1:raise ValueError("unexpected fixture fill or fee")
        cash-=q*p+f;quantity+=q;fees+=f
    if quantity!=0 or number(receipt["ending_quantity"])!=quantity or number(receipt["ending_cash"])!=cash or number(receipt["ending_nav"])!=cash:raise ValueError("cash/NAV reconciliation failure")
    return {"status":"LEAN_SYNTHETIC_ACCOUNTING_CHECKED","receipt_hash":digest(receipt),"initial_cash":10000,"ending_cash":float(cash),"simulated_net_pnl":float(cash-10000),"fees":float(fees),"simulated_fill_count":len(ids),"observations":sum(row["count"] for row in bars.values()),"synthetic":True,"can_trade":False,"promotion_allowed":False,"limitations":["fixed synthetic accounting check only","no market-data rights, historical strategy performance, real broker fill or margin evidence","no general LEAN execution certification"]}

def read_receipt(log_path):
    path=Path(log_path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>16_000_000:raise ValueError("invalid LEAN log artifact")
    raw=path.read_text(encoding="utf-8",errors="strict")
    # Engine may emit the same debug receipt more than once. Conflicting receipts
    # or a missing/invalid payload are a failure, not permission to fabricate one.
    rows=[]
    for line in raw.splitlines():
        if MARKER in line:
            value,_=json.JSONDecoder().raw_decode(line.split(MARKER,1)[1])
            rows.append(value)
    if not rows or any(r!=rows[0] for r in rows):raise ValueError("missing or conflicting LEAN receipt")
    return rows[0],hashlib.sha256(raw.encode()).hexdigest()

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest="cmd",required=True)
    a=s.add_parser("prepare");a.add_argument("directory",type=Path)
    b=s.add_parser("verify");b.add_argument("log",type=Path);b.add_argument("--image-id",required=True);b.add_argument("--fixture-dir",type=Path,required=True);b.add_argument("--algorithm",type=Path,required=True);b.add_argument("--config",type=Path,required=True)
    args=p.parse_args(argv)
    if args.cmd=="prepare":out=prepare(args.directory)
    else:
        if not re.fullmatch("sha256:[0-9a-f]{64}",args.image_id):raise ValueError("immutable image ID required")
        receipt,h=read_receipt(args.log);out=verify(receipt)
        out.update(image_id=args.image_id,log_sha256=h,fixture_hashes=manifest(args.fixture_dir),algorithm_sha256=hashlib.sha256(args.algorithm.read_bytes()).hexdigest(),config_sha256=hashlib.sha256(args.config.read_bytes()).hexdigest(),receipt=receipt)
    print(json.dumps(out,indent=2,allow_nan=False));return 0
if __name__=="__main__":raise SystemExit(main())
