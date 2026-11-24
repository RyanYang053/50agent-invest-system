"""Bounded daily IEX history adapter, receipt-time local-only evidence."""
from __future__ import annotations
import argparse,json,os,re
from datetime import datetime,timedelta,timezone,date
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
from pathlib import Path
from .market_data import AlpacaResearchQuotes
from .ledger import iso,digest,EvidenceLedger
from .research import num

NY=ZoneInfo("America/New_York")
SOURCE="alpaca_iex_daily"
def now():return datetime.now(timezone.utc)

def sessions(start,end):
    import exchange_calendars as xc
    cal=xc.get_calendar("XNYS")
    return {d.date():cal.session_close(d).to_pydatetime().astimezone(timezone.utc) for d in cal.sessions_in_range(start.isoformat(),end.isoformat())}

def ingest_daily(client,ledger,*,symbol,security_id,start,end,policy,clock=now):
    if not isinstance(symbol,str) or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}",symbol) or not isinstance(security_id,str) or not re.fullmatch(r"CIK:[1-9][0-9]{0,9}",security_id):raise ValueError("symbol or issuer identity")
    if policy.get('license_id')!='ALPACA_PERSONAL' or policy.get('cloud_allowed') is not False or any(policy.get(k) is not True for k in ('permitted_for_personal_analysis','allow_local_retention')):raise PermissionError('local research entitlement required')
    if policy!=client.policy or policy.get("symbol")!=symbol or policy.get("security_id")!=security_id or policy.get("symbol_mapping_reviewed") is not True or policy.get("allow_historical_research") is not True:raise PermissionError("explicit historical rights and issuer mapping required")
    a,b=date.fromisoformat(start),date.fromisoformat(end);before=iso(clock().isoformat())
    if not 0<=(b-a).days<=365 or b>=before.astimezone(NY).date():raise ValueError("bounded completed historical dates only")
    expected=sessions(a,b)
    if not 61<=len(expected)<=200:raise ValueError("61–200 exchange sessions required")
    q=urlencode({"symbols":symbol,"timeframe":"1Day","start":datetime.combine(a,datetime.min.time(),NY).isoformat(),"end":(datetime.combine(b+timedelta(days=1),datetime.min.time(),NY)-timedelta(microseconds=1)).isoformat(),"limit":1000,"adjustment":"split","feed":"iex","sort":"asc","asof":"-"})
    raw=client.transport("https://data.alpaca.markets/v2/stocks/bars?"+q,{"APCA-API-KEY-ID":client.key,"APCA-API-SECRET-KEY":client.secret})
    received=iso(clock().isoformat())
    if received<before or raw.get("next_page_token") is not None or not isinstance(raw.get("bars"),dict) or set(raw["bars"])!={symbol}:raise ValueError("incomplete history or identity mismatch")
    rows=raw["bars"][symbol]
    if not isinstance(rows,list) or len(rows)!=len(expected):raise ValueError("incomplete exchange session coverage")
    records=[];seen=set();last=None
    for r in rows:
        ts=iso(r["t"]).astimezone(NY);d=ts.date()
        if ts.time()!=datetime.min.time() or d not in expected or d in seen or (last is not None and d<=last):raise ValueError("invalid daily session label")
        seen.add(d);last=d
        o,h,l,c,v=map(num,(r["o"],r["h"],r["l"],r["c"],r["v"]))
        if not 0<l<=min(o,c)<=max(o,c)<=h or v<0:raise ValueError("invalid OHLCV")
        # Provider daily aggregate may include eligible prints outside regular session.
        # Use completed local day boundary, NOT its timestamp or assumed closing print.
        bar_end=datetime.combine(d+timedelta(days=1),datetime.min.time(),NY).astimezone(timezone.utc)
        if not expected[d]<bar_end<=received:raise ValueError("incomplete day")
        p={"kind":"daily_ohlcv","symbol":symbol,"closed":True,"adjustment":"split_adjusted","currency":"USD","venue":"IEX_PARTIAL_FEED","session_date":d.isoformat(),"bar_end":bar_end.isoformat(),"regular_session_close":expected[d].isoformat(),"open":o,"high":h,"low":l,"close":c,"volume":v,"received_at":received.isoformat(),"provider_response_hash":digest(raw),"availability":"receipt_only_retrospective_adjustment","calendar":"XNYS"}
        rid=digest({"security_id":security_id,"payload":p})
        records.append({"record_id":rid,"source_id":SOURCE,"document_id":symbol+":"+d.isoformat(),"security_id":security_id,"observed_at":p["bar_end"],"published_at":received.isoformat(),"available_at":received.isoformat(),"payload":p,"data_class":"private","license_id":policy["license_id"]})
    if seen!=set(expected):raise ValueError("missing exchange session")
    for record in records:ledger.add_evidence(record,policy=policy)
    return {"status":"DAILY_BARS_STORED","security_id":security_id,"record_ids":[x["record_id"] for x in records],"receipt_at":received.isoformat(),"sessions":len(records),"point_in_time_history":False,"can_trade":False}

def refresh_daily(root,ledger,policies,roles,*,clock=now,client_factory=AlpacaResearchQuotes):
    """Operator-configured watchlist; dispatch actual A065 tasks, not model calls."""
    from .role_jobs import RoleExecutor,RoleJournal
    from .agent_memory import MemoryStore
    from .skill_evolution import Evolution
    from .external_references import ReferenceStore
    if not isinstance(policies,list) or not 1<=len(policies)<=20 or any(not isinstance(p,dict) or not isinstance(p.get("symbol"),str) or not isinstance(p.get("security_id"),str) for p in policies):raise ValueError("invalid bounded watchlist")
    if len({p["security_id"] for p in policies})!=len(policies) or len({p["symbol"] for p in policies})!=len(policies):raise ValueError("duplicate watchlist identity")
    memory=MemoryStore(root/"agent-memory",ledger)
    executor=RoleExecutor(roles,ledger,reference_store=ReferenceStore(root/"external-references"))
    journal=RoleJournal(root/"role_jobs.sqlite",memory=memory,evolution=Evolution(root/"skill-evolution"))
    end=clock().astimezone(NY).date()-timedelta(days=1)
    start=end-timedelta(days=180);out=[]
    for policy in policies:
        try:
            report=ingest_daily(client_factory(policy=policy),ledger,symbol=policy["symbol"],security_id=policy["security_id"],start=start.isoformat(),end=end.isoformat(),policy=policy,clock=clock)
            args={"security_id":report["security_id"],"record_ids":report["record_ids"]}
            result=journal.execute(executor,"A065",at=report["receipt_at"],run_id=digest(report),inputs={"price_behavior":args})
            out.append({"symbol":policy["symbol"],"ingestion":report,"role_result":result,"can_trade":False})
        except (ValueError,PermissionError,RuntimeError,OSError,KeyError,TypeError,ImportError) as e:
            out.append({"symbol":policy["symbol"],"status":"DAILY_RESEARCH_BLOCKED","error_type":type(e).__name__,"can_trade":False})
    return out

def main(argv=None):
    from .core_service import private_dir
    from .price_behavior import diagnose
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--data-dir",type=Path,required=True);p.add_argument("--policy",type=Path,required=True);p.add_argument("--start",required=True);p.add_argument("--end",required=True);p.add_argument("--network",action="store_true");p.add_argument("--retrospective",action="store_true")
    a=p.parse_args(argv)
    if not a.network:raise PermissionError("explicit network consent required")
    os.umask(0o077);root=private_dir(a.data_dir);policy=json.loads(a.policy.read_text());l=EvidenceLedger(root/"evidence.sqlite")
    result=ingest_daily(AlpacaResearchQuotes(policy=policy),l,symbol=policy["symbol"],security_id=policy["security_id"],start=a.start,end=a.end,policy=policy)
    result["diagnostic"]=diagnose(l,security_id=result["security_id"],record_ids=result["record_ids"],at=result["receipt_at"])
    if a.retrospective:
        from .price_replay import retrospective
        result['retrospective']=retrospective(l,security_id=result['security_id'],record_ids=result['record_ids'],at=result['receipt_at'])
    print(json.dumps(result,indent=2,allow_nan=False));return 0
if __name__=="__main__":raise SystemExit(main())
