"""Operator-driven real-data research batch. No automated orders or paid calls by default.
Each run freezes screened candidates and role outputs in private local state.
All model memos remain unverified; independent committee review is still required.
"""
from __future__ import annotations
import argparse,json,os,re,stat
from datetime import datetime,timezone
from pathlib import Path
from .ledger import EvidenceLedger,digest,iso
from .retrieval import ResearchIndex
from .models import ModelGateway
from .runtime import ResearchModelRunner,FixedModelTransport
from .role_jobs import RoleExecutor,RoleJournal,PUBLIC_TASKS
from .pipeline import run_screen
from .feeds import PublicFeedClient
from .transport import PublicJSONTransport
from .market_data import AlpacaResearchQuotes
from .learning import ForecastJournal
from .agent_memory import MemoryStore
from .independent_review import load_trust
from .filing_ingest import ingest_recent_filings,SECArchiveTransport
from .macro_ingest import ingest_macro
from .bls_ingest import ingest_bls,SERIES as BLS_SERIES
from .external_references import ReferenceStore


def execute_batch(screen_result,executor,journal,*,run_id,at,max_candidates=3,roles=None,macro=False):
    """Process only exact screen outputs, not user-supplied ticker recommendations.
    Never treat model memo success as verification or order permission.
    """
    if screen_result.get('can_trade') is not False or not run_id or not 1<=max_candidates<=10:raise ValueError('invalid batch')
    now=iso(at);selected=screen_result['candidates'][:max_candidates]
    requested=list(roles if roles is not None else ('A013','A031','A032','A033','A034','A035','A044','A052','A054','A101','A102','A011'))
    if not requested or len(set(requested))!=len(requested) or any(r not in PUBLIC_TASKS for r in requested):raise ValueError('public research roles required')
    journal.bind_batch(run_id,{'screen_hash':digest(screen_result),'at':now.isoformat(),'max_candidates':max_candidates,'roles':requested,'macro':macro})
    results=[];seen=set();expected=0
    for candidate in selected:
        if candidate.get('status')!='CANDIDATE' or candidate.get('can_trade') is not False or not candidate.get('fundamental_evidence_ids') or not candidate.get('market_evidence_ids') or iso(candidate['decision_at'])>now:raise ValueError('unqualified screen result')
        cik=int(candidate['cik']);sid=f'CIK:{cik}'
        if sid in seen:raise ValueError('duplicate issuer in selected candidates')
        seen.add(sid)
        executor.ledger.resolve_ids(candidate['fundamental_evidence_ids'],security_id=sid,decision_at=candidate['decision_at'])
        executor.ledger.resolve_ids(candidate['market_evidence_ids'],security_id=sid,decision_at=candidate['decision_at'],include_private=True)
        jobs=[];child=digest({'run':run_id,'candidate':digest(candidate)})
        for rid in requested:
            if PUBLIC_TASKS[rid][0]!='company':continue
            jobs.append(journal.execute(executor,rid,at=at,run_id=child,inputs={'security_id':sid}));expected+=1
        results.append({'security_id':sid,'symbol':candidate['symbol'],'candidate_hash':digest(candidate),'screen_asof':candidate['decision_at'],'research_asof':now.isoformat(),'jobs':jobs,'decision':'WAIT'})
    macro_jobs=[]
    if macro:
        for rid in requested:
            if PUBLIC_TASKS[rid][0]=='macro':
                macro_jobs.append(journal.execute(executor,rid,at=at,run_id=digest({'run':run_id,'scope':'macro'}),inputs={'security_id':'MACRO:US'}));expected+=1
    all_jobs=[j for r in results for j in r['jobs']]+macro_jobs
    memos=sum(j.get('status')=='UNVERIFIED_RESEARCH_MEMO' for j in all_jobs)
    return {'status':'RESEARCH_BATCH_ONLY','run_id':run_id,'screen_hash':digest(screen_result),'selected_count':len(selected),'expected_jobs':expected,'unverified_memos':memos,'blocked_or_other_jobs':len(all_jobs)-memos,'companies':results,'macro':macro_jobs,'decision':'WAIT','can_trade':False,'limitations':['no claim-entailment certification or automatic order construction','numerical DCF assumptions and private account risk require separate reviewed inputs','operator must use a private data directory and licensed data']}


def private_dir(path):
    p=Path(path).expanduser()
    if p.is_symlink():raise PermissionError('symlink data directory')
    p.mkdir(mode=0o700,parents=True,exist_ok=True)
    if os.name=='posix' and stat.S_IMODE(p.stat().st_mode)&0o077:raise PermissionError('data directory must have mode 0700')
    return p


def readiness():
    groups={'sec':['SEC_USER_AGENT'],'fred':['FRED_API_KEY'],'alpaca_research':['ALPACA_API_KEY','ALPACA_API_SECRET'],'alpaca_paper':['ALPACA_PAPER_KEY','ALPACA_PAPER_SECRET'],'tiingo':['TIINGO_API_KEY'],'openai':['OPENAI_API_KEY'],'deepseek':['DEEPSEEK_API_KEY'],'anthropic':['ANTHROPIC_API_KEY'],'google':['GEMINI_API_KEY']}
    return {'status':'CONFIGURATION_CHECK_ONLY','credentials_present':{k:all(bool(os.getenv(v)) for v in vs) for k,vs in groups.items()},'network_verified':False,'broker_verified':False,'can_trade':False}


def refresh_macro_sources(client,ledger,index,policies):
    if not isinstance(policies,list) or not 1<=len(policies)<=20 or any(not isinstance(p,dict) or not isinstance(p.get('series_id'),str) for p in policies):raise ValueError('invalid macro policy list')
    if len({p['series_id'] for p in policies})!=len(policies):raise ValueError('duplicate macro series policy')
    reports=[]
    for pol in policies:
        try:
            fn=ingest_bls if pol['series_id'] in BLS_SERIES else ingest_macro
            reports.append(fn(client,ledger,index,series=pol['series_id'],policy=pol))
        except (RuntimeError,ValueError,PermissionError,KeyError,TypeError) as e:
            reports.append({'status':'MACRO_INGEST_BLOCKED','series_id':pol['series_id'],'error_type':type(e).__name__,'can_trade':False})
    return reports


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='cmd',required=True)
    sub.add_parser('readiness')
    m=sub.add_parser('refresh-macro');m.add_argument('--data-dir',type=Path,required=True);m.add_argument('--macro-policies',type=Path,required=True);m.add_argument('--network',action='store_true')
    c=sub.add_parser('catalog');c.add_argument('--roles',type=Path,required=True)
    r=sub.add_parser('screen-research');r.add_argument('--universe',type=Path,required=True);r.add_argument('--data-dir',type=Path,required=True);r.add_argument('--sec-policy',type=Path,required=True);r.add_argument('--alpaca-policy',type=Path);r.add_argument('--roles',type=Path,required=True);r.add_argument('--models',type=Path,required=True);r.add_argument('--max-candidates',type=int,default=3);r.add_argument('--daily-budget',default='0');r.add_argument('--monthly-budget',default='0');r.add_argument('--paid-models',action='store_true');r.add_argument('--network',action='store_true');r.add_argument('--basis',choices=['annual','ttm'],default='ttm');r.add_argument('--run-id',required=True);r.add_argument('--filings-per-company',type=int,default=0,choices=range(0,6));r.add_argument('--macro-policies',type=Path)
    j=sub.add_parser('run-role');j.add_argument('role_id');j.add_argument('--inputs',type=Path,required=True);j.add_argument('--data-dir',type=Path,required=True);j.add_argument('--roles',type=Path,required=True);j.add_argument('--models',type=Path,required=True);j.add_argument('--at',required=True);j.add_argument('--run-id',required=True);j.add_argument('--paid-models',action='store_true');j.add_argument('--daily-budget',default='0');j.add_argument('--monthly-budget',default='0')
    for cmd in (r,j):cmd.add_argument('--memory-trust',type=Path)
    a=parser.parse_args(argv)
    if a.cmd=='readiness':out=readiness()
    elif a.cmd=='catalog':out=RoleExecutor(json.loads(a.roles.read_text()),None).catalog()
    elif a.cmd=='refresh-macro':
        if not a.network:raise PermissionError('explicit network consent required')
        os.umask(0o077);d=private_dir(a.data_dir)
        policies=json.loads(a.macro_policies.read_text())
        client=PublicFeedClient(PublicJSONTransport(),fred_api_key=os.getenv('FRED_API_KEY',''))
        reports=refresh_macro_sources(client,EvidenceLedger(d/'evidence.sqlite'),ResearchIndex(d/'research.sqlite'),policies)
        out={'status':'MACRO_REFRESH_ONLY','ingestion':reports,'can_trade':False}
    elif a.cmd=='run-role':
        os.umask(0o077);d=private_dir(a.data_dir);load=lambda p:json.loads(p.read_text());roles=load(a.roles);models=load(a.models);ledger=EvidenceLedger(d/'evidence.sqlite');index=ResearchIndex(d/'research.sqlite')
        memory=MemoryStore(d/'agent-memory',ledger,trust=load_trust(a.memory_trust) if a.memory_trust else {})
        gateway=ModelGateway(d/'models.sqlite',models,roles,daily_limit_usd=a.daily_budget,monthly_limit_usd=a.monthly_budget)
        runner=ResearchModelRunner(gateway,index,FixedModelTransport(enabled=True),memory=memory) if a.paid_models else None
        out=RoleJournal(d/'role_jobs.sqlite',memory=memory).execute(RoleExecutor(roles,ledger,model_runner=runner,forecast_journal=ForecastJournal(d/'forecasts.sqlite'),reference_store=ReferenceStore(d/'external-references')),a.role_id,at=a.at,run_id=a.run_id,inputs=load(a.inputs))
    else:
        if not a.network:raise PermissionError('explicit network consent required')
        if not 1<=a.max_candidates<=10:raise ValueError('candidate bound')
        os.umask(0o077);d=private_dir(a.data_dir);load=lambda p:json.loads(p.read_text());roles=load(a.roles);models=load(a.models)
        ledger=EvidenceLedger(d/'evidence.sqlite');index=ResearchIndex(d/'research.sqlite')
        memory=MemoryStore(d/'agent-memory',ledger,trust=load_trust(a.memory_trust) if a.memory_trust else {})
        gateway=ModelGateway(d/'models.sqlite',models,roles,daily_limit_usd=a.daily_budget,monthly_limit_usd=a.monthly_budget)
        executor=RoleExecutor(roles,ledger,model_runner=ResearchModelRunner(gateway,index,FixedModelTransport(enabled=True),memory=memory) if a.paid_models else None,forecast_journal=ForecastJournal(d/'forecasts.sqlite'),reference_store=ReferenceStore(d/'external-references'))
        quotes=AlpacaResearchQuotes(policy=load(a.alpaca_policy)) if a.alpaca_policy else None
        client=PublicFeedClient(PublicJSONTransport(),sec_user_agent=os.getenv('SEC_USER_AGENT',''),fred_api_key=os.getenv('FRED_API_KEY',''))
        result=run_screen(load(a.universe),client=client,ledger=ledger,index=index,policy=load(a.sec_policy),at=datetime.now(timezone.utc).isoformat(),quotes=quotes,basis=a.basis)
        ingestion=[]
        if a.filings_per_company:
            transport=SECArchiveTransport(os.getenv('SEC_USER_AGENT',''))
            for c in result['candidates'][:a.max_candidates]:
                try:ingestion.append(ingest_recent_filings(client.sec_submissions(c['cik']),cik=c['cik'],ledger=ledger,index=index,policy=load(a.sec_policy),transport=transport,limit=a.filings_per_company))
                except (RuntimeError,ValueError,PermissionError,KeyError,TypeError) as e:ingestion.append({'status':'FILING_INGEST_BLOCKED','symbol':c['symbol'],'error_type':type(e).__name__})
        if a.macro_policies:
            ingestion.extend(refresh_macro_sources(client,ledger,index,load(a.macro_policies)))
        tasks=list(PUBLIC_TASKS) if a.macro_policies else None
        out={'screen':result,'ingestion':ingestion,'research':execute_batch(result,executor,RoleJournal(d/'role_jobs.sqlite',memory=memory),run_id=a.run_id,at=datetime.now(timezone.utc).isoformat(),max_candidates=a.max_candidates,roles=tasks,macro=bool(a.macro_policies)),'can_trade':False}
    print(json.dumps(out,indent=2,allow_nan=False));return 0
if __name__=='__main__':raise SystemExit(main())
