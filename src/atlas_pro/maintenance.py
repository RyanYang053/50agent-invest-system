"""Local operator tick: refresh allowed sources and generate role-local proposals.

Designed for cron/Task Scheduler. No scheduler is installed, no paid model
or broker access. A slot is consumed before network operations; ambiguous
crashes require explicit operator inspection, never blind retry.
"""
from __future__ import annotations
import argparse,json,os,sqlite3
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
from .ledger import digest,iso,EvidenceLedger
from .retrieval import ResearchIndex
from .core_service import private_dir,refresh_macro_sources
from .feeds import PublicFeedClient
from .transport import PublicJSONTransport
from .external_references import ReferenceStore,fetch_nist
from .agent_memory import MemoryStore
from .skill_evolution import Evolution
from .skill_contracts import catalog

def utcnow():return datetime.now(timezone.utc)
def tick(root,config,*,network=False,clock=utcnow,macro_runner=None,nist_runner=None,roles=None,daily_runner=None):
    if network is not True:raise PermissionError("explicit network consent required")
    if not isinstance(config,dict) or set(config)-{"macro_policies","nist_policy","reflect","daily_bar_policies"} or type(config.get("reflect",True)) is not bool:raise ValueError("invalid maintenance config")
    policies=config.get("macro_policies",[])
    daily=config.get('daily_bar_policies',[])
    if not isinstance(daily,list) or len(daily)>20 or (daily and not isinstance(roles,list)):raise ValueError('daily bars require a bounded watchlist and role manifest')
    if not isinstance(policies,list) or len(policies)>20 or (not policies and not daily and not config.get("nist_policy") and not config.get("reflect",True)):raise ValueError("empty/invalid schedule")
    root=private_dir(root);stamp=iso(clock().isoformat());slot=stamp.date().isoformat()
    path=root/"maintenance.sqlite"
    if path.is_symlink():raise PermissionError("unsafe maintenance journal")
    with closing(sqlite3.connect(path,timeout=10)) as c,c:
        c.execute("CREATE TABLE IF NOT EXISTS ticks(slot TEXT PRIMARY KEY,config_hash TEXT NOT NULL,state TEXT NOT NULL,result TEXT,result_hash TEXT)")
        c.execute("BEGIN IMMEDIATE")
        prev=c.execute("SELECT config_hash,state,result,result_hash FROM ticks WHERE slot=?",(slot,)).fetchone()
        if prev:
            if prev[0]!=digest({'config':config,'roles':roles if daily else None}):raise ValueError("daily slot already used with another configuration")
            if prev[1]=="RUNNING":return {"status":"UNRESOLVED_TICK_NO_RETRY","slot":slot,"can_trade":False}
            result=json.loads(prev[2])
            if digest(result)!=prev[3]:raise ValueError("maintenance result integrity")
            return result
        if c.execute("SELECT 1 FROM ticks WHERE state='RUNNING'").fetchone():return {"status":"PRIOR_TICK_UNRESOLVED","can_trade":False}
        c.execute("INSERT INTO ticks VALUES(?,?,'RUNNING',NULL,NULL)",(slot,digest({'config':config,'roles':roles if daily else None})))
    ledger=EvidenceLedger(root/"evidence.sqlite");index=ResearchIndex(root/"research.sqlite");reports=[]
    if policies:
        run=macro_runner or (lambda p:refresh_macro_sources(PublicFeedClient(PublicJSONTransport(),fred_api_key=os.getenv("FRED_API_KEY","")),ledger,index,p))
        try:reports.append({"type":"macro","result":run(policies)})
        except (ValueError,PermissionError,RuntimeError,OSError,KeyError,TypeError) as e:reports.append({"type":"macro","status":"BLOCKED","error_type":type(e).__name__})
    if config.get("nist_policy"):
        run=nist_runner or (lambda p:fetch_nist(ReferenceStore(root/"external-references"),p,network=True))
        try:reports.append({"type":"nist","result":run(config["nist_policy"])})
        except (ValueError,PermissionError,RuntimeError,OSError,KeyError,TypeError) as e:reports.append({"type":"nist","status":"BLOCKED","error_type":type(e).__name__})
    if daily:
        from .daily_bars import refresh_daily
        run=daily_runner or (lambda p:refresh_daily(root,ledger,p,roles,clock=clock))
        try:reports.append({'type':'daily_price_behavior','result':run(daily)})
        except (ValueError,PermissionError,RuntimeError,OSError,KeyError,TypeError,ImportError) as e:reports.append({'type':'daily_price_behavior','status':'BLOCKED','error_type':type(e).__name__})
    if config.get("reflect",True):
        memory=MemoryStore(root/"agent-memory",ledger);evolution=Evolution(root/"skill-evolution")
        for rid in sorted(catalog()):
            try:reports.append({"type":"reflection","role_id":rid,"proposals":evolution.reflect(rid,memory.bind(rid).recent_episodes())})
            except (ValueError,PermissionError,RuntimeError,OSError,KeyError,TypeError) as e:reports.append({"type":"reflection","role_id":rid,"status":"BLOCKED","error_type":type(e).__name__})
    result={"status":"MAINTENANCE_TICK_RECORDED","slot":slot,"reports":reports,"can_trade":False}
    with closing(sqlite3.connect(path,timeout=10)) as c,c:
        c.execute("UPDATE ticks SET state='RECORDED',result=?,result_hash=? WHERE slot=? AND state='RUNNING'",(json.dumps(result,allow_nan=False),digest(result),slot))
    return result

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--data-dir",type=Path,required=True);p.add_argument("--config",type=Path,required=True);p.add_argument("--network",action="store_true");p.add_argument('--roles',type=Path)
    a=p.parse_args(argv);os.umask(0o077)
    out=tick(a.data_dir,json.loads(a.config.read_text()),network=a.network,roles=json.loads(a.roles.read_text()) if a.roles else None)
    print(json.dumps(out,indent=2,allow_nan=False));return 0
if __name__=="__main__":raise SystemExit(main())
