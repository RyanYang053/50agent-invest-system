import json, math
from pathlib import Path
from datetime import datetime,timezone
import pytest
from atlas_pro.research import sec_annual_facts, annual_snapshot, screen, dcf, reverse_dcf, scenario_grid
from atlas_pro.ledger import EvidenceLedger,digest
from atlas_pro.retrieval import ResearchIndex
from atlas_pro.market_data import AlpacaResearchQuotes,outstanding_shares
from atlas_pro.pipeline import run_screen
from atlas_pro.runtime import ToolRegistry,ResearchModelRunner,FixedModelTransport
from atlas_pro.models import ModelGateway
from atlas_pro.events import EventBus
from atlas_pro.risk import ResearchRiskGate
from atlas_pro.learning import ForecastJournal
from atlas_pro.documents import index_document
from atlas_pro.decision import decision_grid
from atlas_pro.backtest import replay_periods

ROOT=Path(__file__).resolve().parents[1]
ROLES=json.loads((ROOT/'config/50 agent manifest.json').read_text())
REG=json.loads((ROOT/'config/model registry.json').read_text())
RULES=json.loads((ROOT/'config/event rules.json').read_text())
NOW='2026-11-23T18:00:00Z'; FUT='2026-11-24T18:00:00Z'; OLD='2026-11-20T18:00:00Z'
PUBLIC={'license_id':'SEC_PUBLIC','permitted_for_personal_analysis':True,'allow_local_retention':True,'allow_rag_indexing':True,'cloud_allowed':True}
ALPACA={'license_id':'ALPACA_PERSONAL','permitted_for_personal_analysis':True,'allow_local_retention':True,'cloud_allowed':False}

@pytest.fixture
def issuer():
    data={'RevenueFromContractWithCustomerExcludingAssessedTax':1000,'OperatingIncomeLoss':200,'NetCashProvidedByUsedInOperatingActivities':220,'PaymentsToAcquirePropertyPlantAndEquipment':50,'NetIncomeLoss':140,'StockholdersEquity':500,'Assets':900,'CashAndCashEquivalentsAtCarryingValue':100,'LongTermDebtNoncurrent':120,'LongTermDebtCurrent':20}
    flows=set(list(data)[:5]); facts={}
    for k,v in data.items():
        f={'end':'2026-09-30','accn':'0000000001-26-000001','form':'10-K','val':v}
        if k in flows:f['start']='2025-10-01'
        facts[k]={'units':{'USD':[f]}}
    facts[next(iter(data))]['units']['USD'].append({'end':'2025-09-30','start':'2024-10-01','accn':'0000000001-26-000001','form':'10-K','val':800})
    cf={'cik':1,'facts':{'us-gaap':facts,'dei':{'EntityCommonStockSharesOutstanding':{'units':{'shares':[{'end':'2026-11-18','accn':'0000000001-26-000001','form':'10-K','val':100}]}}}}}
    sub={'cik':'0000000001','filings':{'recent':{'accessionNumber':['0000000001-26-000001'],'acceptanceDateTime':[OLD]}}}
    return cf,sub

@pytest.fixture
def snapshot(issuer):return annual_snapshot(sec_annual_facts(*issuer,at=NOW,received_at=NOW),at=NOW)

@pytest.fixture
def market():return {'symbol':'TEST','cik':1,'price':10,'shares':100,'price_asof':NOW,'shares_asof':OLD,'available_at':NOW,'currency':'USD','security_type':'common_equity','sector_class':'operating_company','qualified_research_data':True,'evidence_ids':['quote','shares'],'price_basis':'FIXTURE'}

@pytest.fixture
def assumptions():return dict(revenue=1000,growth=[.08]*5,margin=[.20]*5,tax=.25,da_rate=[.04]*5,capex_rate=[.05]*5,nwc_rate=[.1]*5,wacc=.10,terminal_growth=.025,net_debt=40,diluted_shares=100)

@pytest.fixture
def scenarios():return {'bear':{'probability':.25,'terminal_price':7},'base':{'probability':.50,'terminal_price':12},'bull':{'probability':.25,'terminal_price':16}}

def test_pit_annual(snapshot):
    assert snapshot['metrics']['revenue_growth']==.25
    assert snapshot['metrics']['ocf']==220
    assert snapshot['basis']=='annual_us_gaap_usd_not_ttm'

def test_pit_future_and_receipt(issuer):
    assert sec_annual_facts(*issuer,at='2026-11-19T18:00:00Z',received_at=NOW,replay=True)==[]
    with pytest.raises(ValueError):sec_annual_facts(*issuer,at=OLD,received_at=NOW)
    assert all(r['available_at'].startswith('2026-11-20') for r in sec_annual_facts(*issuer,at=NOW,received_at=FUT,replay=True))

def test_quarter_not_mixed(issuer):
    cf,sub=issuer; cf['facts']['us-gaap']['OperatingIncomeLoss']['units']['USD'][0]['start']='2026-07-01'
    assert 'operating_income' not in annual_snapshot(sec_annual_facts(cf,sub,at=NOW,received_at=NOW),at=NOW)['metrics']

def test_unknown_filing_skipped(issuer):
    cf,sub=issuer;sub['filings']['recent']['accessionNumber']=['unknown']; assert sec_annual_facts(cf,sub,at=NOW,received_at=NOW)==[]

def test_conflicting_facts_skipped(issuer):
    cf,sub=issuer; fs=cf['facts']['us-gaap']['OperatingIncomeLoss']['units']['USD']; fs.append(fs[0]|{'val':999}); assert not any(r['field']=='operating_income' for r in sec_annual_facts(cf,sub,at=NOW,received_at=NOW))

def test_screen_research_only(snapshot,market):
    r=screen(snapshot,market,at=NOW); assert r['status']=='CANDIDATE' and not r['can_trade']; assert r['metrics']['fcf_yield']==.17

@pytest.mark.parametrize('patch',[{'price':float('nan')},{'shares':0},{'cik':2},{'price_asof':FUT},{'qualified_research_data':'true'},{'evidence_ids':[]},{'sector_class':'bank'},{'currency':'CAD'}])
def test_bad_market_inputs(snapshot,market,patch):assert screen(snapshot,market|patch,at=NOW)['status']=='INSUFFICIENT_DATA'

def test_no_missing_debt_imputation(snapshot,market):
    snapshot['metrics'].pop('current_debt');assert screen(snapshot,market,at=NOW)['status']=='INSUFFICIENT_DATA'

def test_dcf_reverse(assumptions):
    v=dcf(**assumptions); rev=reverse_dcf(v['value_per_share'],assumptions)
    assert v['enterprise_value']>0 and rev['status']=='SOLVED' and abs(rev['implied_growth']-.08)<1e-8

@pytest.mark.parametrize('patch',[{'wacc':.025},{'diluted_shares':0},{'tax':float('nan')},{'growth':[.1]},{'capex_rate':[-1]*5}])
def test_dcf_input_bounds(assumptions,patch):
    with pytest.raises(ValueError):dcf(**(assumptions|patch))

def test_scenario_no_unvalidated_kelly(scenarios):
    r=scenario_grid(scenarios,price=10,benchmark_return=.08);assert r['expected_return']==pytest.approx(.175);assert r['kelly_capped_single_asset'] is None and r['decision']=='WAIT'
    r=scenario_grid(scenarios,price=10,benchmark_return=.08,probabilities_validated='true');assert r['decision']=='WAIT'

def test_scenario_probability_bounds(scenarios):
    scenarios['bear']['probability']=.50
    with pytest.raises(ValueError):scenario_grid(scenarios,price=10,benchmark_return=.08)

def test_decision_grid_keeps_wait(snapshot,market,assumptions,scenarios):
    r=decision_grid(candidate=screen(snapshot,market,at=NOW),assumptions={'bear':assumptions|{'growth':[.02]*5},'base':assumptions,'bull':assumptions|{'growth':[.15]*5}},terminal_scenarios=scenarios,quote_price=10,benchmark_return=.08,at=NOW)
    assert r['decision']=='WAIT' and r['position_size'] is None and len(r['sensitivity']['values'])==3 and r['decision_id']

class FakeSEC:
    def __init__(self,issuer):self.cf,self.sub=issuer
    def sec_companyfacts(self,cik):return self.cf
    def sec_submissions(self,cik):return self.sub

def quote(symbol='TEST',ts=NOW,bid=9.9,ask=10.1):return {'symbol':symbol,'quote':{'t':ts,'bp':bid,'ap':ask}}

def fake_quotes(data):return AlpacaResearchQuotes(policy=ALPACA,transport=lambda *args:data,api_key='fixture',api_secret='fixture')

def test_alpaca_iex_scope():
    r=fake_quotes(quote()).quote('TEST',at=NOW);assert r['price']==10 and r['execution_qualified'] is False and 'IEX' in r['price_basis']

@pytest.mark.parametrize('data',[quote(ts=FUT),quote(bid=11),quote(symbol='OTHER')])
def test_quote_invalid(data):
    with pytest.raises(ValueError):fake_quotes(data).quote('TEST',at=NOW)

def test_alpaca_license_required():
    with pytest.raises(PermissionError):AlpacaResearchQuotes(policy={})

def test_shares_available(issuer):assert outstanding_shares(*issuer,at=NOW)['shares']==100

def test_end_to_end_selection(issuer,tmp_path):
    l=EvidenceLedger(tmp_path/'ev');idx=ResearchIndex(tmp_path/'rag')
    u=[{'symbol':'TEST','cik':1,'security_type':'common_equity','sector_class':'operating_company'}]
    r=run_screen(u,client=FakeSEC(issuer),ledger=l,index=idx,policy=PUBLIC,at=NOW,received_at=NOW,quotes=fake_quotes(quote()))
    assert r['candidate_count']==1 and r['candidates'][0]['symbol']=='TEST' and l.verify_evidence_integrity()
    assert idx.search('revenue',decision_at=NOW,security_id='CIK:1')
    assert not any(x['source_id']=='alpaca_iex' for x in l.asof('CIK:1',NOW))

def test_unverified_external_market_rejected(issuer,market,tmp_path):
    r=run_screen([{'symbol':'TEST','cik':1,'market':market}],client=FakeSEC(issuer),ledger=EvidenceLedger(tmp_path/'ev'),index=ResearchIndex(tmp_path/'rag'),policy=PUBLIC,at=NOW,received_at=NOW)
    assert r['candidate_count']==0 and len(r['rejected'])==1

def doc(**kwargs):return {'doc_id':'test','source_id':'sec','source_uri':'https://www.sec.gov/','security_id':'CIK:1','available_at':OLD,'scope':'public','license_id':'SEC_PUBLIC','content':'revenue was reported; 公司营业收入增长。'}|kwargs

def test_rag_cjk_and_immutability(tmp_path):
    idx=ResearchIndex(tmp_path/'rag');idx.add(doc(),PUBLIC)
    assert idx.search('营业收入',decision_at=NOW)
    with pytest.raises(ValueError):idx.add(doc(security_id='CIK:2'),PUBLIC)
    with pytest.raises(PermissionError):idx.add(doc(doc_id='bad'),PUBLIC|{'cloud_allowed':False})

def test_rag_chunk_offsets(tmp_path):
    idx=ResearchIndex(tmp_path/'rag');r=index_document(idx,doc(content='revenue '+('financial data\n'*150)),PUBLIC,chunk_chars=300,overlap=30)
    assert len(r['chunk_ids'])>2 and all('#atlas-chars=' in d['source_uri'] for d in idx.search('financial',decision_at=NOW))

def test_rag_future_never_visible(tmp_path):
    idx=ResearchIndex(tmp_path/'rag');idx.add(doc(available_at=FUT),PUBLIC);assert idx.search('revenue',decision_at=NOW)==[]

def test_tool_permissions():
    t=ToolRegistry(ROLES);t.register('evidence.get','evidence',lambda x:x)
    assert t.call('A011','evidence.get',{'x':1},run_id='r',data_scope='public_only')==1
    with pytest.raises(PermissionError):t.call('A012','evidence.get',{'x':1},run_id='r',data_scope='private_only')
    with pytest.raises(PermissionError):t.register('execution.order','execution',lambda:None)

def test_tool_budget():
    t=ToolRegistry(ROLES);t.register('evidence.get','evidence',lambda:1)
    n=next(r for r in ROLES if r['agent_id']=='A011')['tool_budget_calls']
    for _ in range(n):t.call('A011','evidence.get',{},run_id='r',data_scope='public_only')
    with pytest.raises(PermissionError):t.call('A011','evidence.get',{},run_id='r',data_scope='public_only')

def gateway(tmp_path):
    g=ModelGateway(tmp_path/'models',REG,ROLES);g.certify('A011','gpt-6.2-sol','finance',.97,.9,at=OLD,valid_until=FUT,provenance={'external_eval_report':'fixture','locked_testset_hash':'fixture'});return g

def answer(ids):return {'status':'completed','model':'fixture','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'claims':[{'claim':'reported revenue','evidence_ids':ids}],'uncertainties':[],'countercase':'verify cashflow'})}]}],'usage':{'input_tokens':100,'output_tokens':40}}

def test_model_run_provenance_and_dedupe(tmp_path):
    g=gateway(tmp_path);idx=ResearchIndex(tmp_path/'rag');idx.add(doc(),PUBLIC);seen=[]
    def transport(provider,body):seen.append(body);return answer(['test'])
    r=ResearchModelRunner(g,idx,transport);kwargs=dict(role_id='A011',task_set='finance',request_id='q',security_id='CIK:1',query='revenue',at=NOW)
    a=r.run(**kwargs);assert a['status']=='UNVERIFIED_RESEARCH_MEMO' and not a['can_trade'] and seen[0]['store'] is False and seen[0]['tools']==[]
    assert r.run(**kwargs)['status']=='ALREADY_RESERVED' and len(seen)==1

def test_model_reject_fake_citation(tmp_path):
    idx=ResearchIndex(tmp_path/'rag');idx.add(doc(),PUBLIC);r=ResearchModelRunner(gateway(tmp_path),idx,lambda *a:answer(['made-up']))
    assert r.run(role_id='A011',task_set='finance',request_id='q',security_id='CIK:1',query='revenue',at=NOW)['status']=='MODEL_OUTPUT_REJECTED'

def test_paid_inference_disabled():
    with pytest.raises(PermissionError):FixedModelTransport()('openai',{})

def test_invalid_model_certification(tmp_path):
    g=gateway(tmp_path)
    with pytest.raises(ValueError):g.certify('A011','gpt-6.2-sol','finance',float('inf'),.9,at=OLD,valid_until=FUT,provenance={'external_eval_report':'fixture','locked_testset_hash':'fixture'})

def test_token_cap(tmp_path):
    g=gateway(tmp_path);assert g.select_and_reserve(request_id='x',role_id='A011',task_set='finance',data_scope='public_only',at=NOW,input_tokens=100001,output_tokens=100)['status']=='INVALID_TOKENS'

def test_event_lease_fencing(tmp_path):
    b=EventBus(tmp_path/'bus',RULES,roles=ROLES);b.submit({'event_type':'unauthorized_policy_change','signal_id':'one'},verified=False,at=NOW)
    j=b.claim(at=NOW,lease_seconds=1);assert j['payload']['priority']=='P0';assert b.claim(at=NOW) is None
    nextj=b.claim(at='2026-11-23T18:00:02Z');assert nextj['work_id']==j['work_id'] and nextj['lease_token']!=j['lease_token']
    with pytest.raises(ValueError):b.finish(j['work_id'],j['lease_token'],at='2026-11-23T18:00:02Z',success=True)
    assert b.finish(nextj['work_id'],nextj['lease_token'],at='2026-11-23T18:00:02Z',success=True)=='DONE'

def test_risk_truthy_approval_not_approved():
    r=ResearchRiskGate().review({'status':'ACTIVE_APPROVED','owner_approval':{'approved':'false'}},{'all_configured_accounts_present':'yes'},{'action':'BUY'},at=NOW);assert 'MANDATE_UNAPPROVED' in r['reasons'] and 'INCOMPLETE_ACCOUNTS' in r['reasons']

def test_learning_no_early_outcome(tmp_path):
    j=ForecastJournal(tmp_path/'f');rid=j.record(security_id='CIK:1',created_at=OLD,due_at=NOW,probability=.8,threshold=.1,baseline_probability=.5,evidence_ids=['x'],model_version='m',strategy_version='s')
    assert j.due(OLD)==[] and j.due(NOW)==[rid]
    with pytest.raises(ValueError):j.resolve(rid,terminal_total_return=.2,benchmark_total_return=.1,measurement_at=NOW,observed_at=OLD,evidence_ids=['y'])
    assert j.resolve(rid,terminal_total_return=.2,benchmark_total_return=.1,measurement_at=NOW,observed_at=NOW,evidence_ids=['y'])=='RESOLVED'
    assert j.report(at=OLD)['n']==0
    r=j.report(at=NOW);assert r['brier']==pytest.approx(.04) and r['baseline_brier']==.25 and not r['promotion_allowed']

def period():return {'signal_at':OLD,'start_at':NOW,'end_at':FUT,'historical_universe_verified':True,'corporate_actions_verified':True,'universe_evidence_id':'fixture','signal_evidence_available_at':[OLD],'weights':{'TEST':.8,'CASH':.2},'total_returns':{'TEST':.1,'CASH':0},'benchmark_total_return':.04}

def test_backtest_costs():
    r=replay_periods([period()],cost_bps=10);assert r['total_cost']==pytest.approx(.0008) and r['total_return']==pytest.approx(.9992*1.08-1)

@pytest.mark.parametrize('patch',[{'signal_at':NOW},{'signal_evidence_available_at':[FUT]},{'historical_universe_verified':False},{'total_returns':{'CASH':0}}])
def test_backtest_rejects_leakage_or_missing(patch):
    with pytest.raises(ValueError):replay_periods([period()|patch])

from atlas_pro.scheduler import tick,ResearchWorker
from atlas_pro.evaluation import grade_locked

def test_scheduler_idempotence_and_utc_rollover(tmp_path):
    b=EventBus(tmp_path/'bus',RULES,roles=ROLES)
    # 20:00 EST Monday is Tuesday UTC; exchange session must use NY date.
    at='2026-11-24T01:00:00Z'; r=tick(b,at=at)
    assert len(r)==1 and r[0]['status']=='QUEUED'
    assert tick(b,at='2026-11-24T01:01:00Z')[0]['status']=='DUPLICATE'

def test_worker_p0_requires_deterministic(tmp_path):
    b=EventBus(tmp_path/'bus',RULES,roles=ROLES); b.submit({'event_type':'unauthorized_policy_change','signal_id':'x'},verified=False,at=NOW)
    calls=[]
    def unsafe(*x):calls.append(1);return {'can_trade':False}
    w=ResearchWorker(b,{'unauthorized_policy_change':unsafe},clock=lambda:NOW)
    assert w.step()['status']=='FAILED' and not calls

def test_worker_idempotent_handler(tmp_path):
    b=EventBus(tmp_path/'bus',RULES,roles=ROLES); b.submit({'event_type':'unauthorized_policy_change','signal_id':'x'},verified=False,at=NOW)
    def safe(*x):return {'can_trade':False,'note':'blocked'}
    safe.deterministic_only=True
    w=ResearchWorker(b,{'unauthorized_policy_change':safe},clock=lambda:NOW)
    assert w.step()['status']=='DONE' and w.step() is None

def test_locked_eval_never_auto_promotes():
    c=[{'case_id':'1','expected_values':{'x':10},'allowed_evidence_ids':['e'],'evaluation_rights_verified':True,'synthetic':True}]
    r=grade_locked(c,{'1':{'values':{'x':10},'abstain':False,'evidence_ids':['e']}},expected_hash=digest(c),min_cases=1)
    assert r['quality']==1 and not r['promotion_allowed'] and not r['eligible_for_external_review']
    with pytest.raises(ValueError):grade_locked(c,{},expected_hash='bad')
    with pytest.raises(PermissionError):grade_locked([c[0]|{'evaluation_rights_verified':False}],{},expected_hash=digest([c[0]|{'evaluation_rights_verified':False}]))

def test_locked_eval_critical_citation_error():
    c=[{'case_id':'1','expected_values':{'x':10},'allowed_evidence_ids':['e'],'evaluation_rights_verified':True,'synthetic':False}]
    r=grade_locked(c,{'1':{'values':{'x':10},'abstain':False,'evidence_ids':['fake']}},expected_hash=digest(c),min_cases=1)
    assert r['quality']==0 and r['critical_failures']==1 and not r['eligible_for_external_review']

def test_fusion_workflow_resumes_on_independent_artifacts(issuer,market,assumptions,scenarios,tmp_path):
    from atlas_pro.workflow import run_packet
    from atlas_pro.committee import Committee
    from test_fusion import snapshot as portfolio_snapshot, returns, stress, LIMITS, CLUSTERS
    l=EvidenceLedger(tmp_path/'ev');idx=ResearchIndex(tmp_path/'rag');c=Committee(tmp_path/'committee')
    screen_result=run_screen([{'symbol':'TEST','cik':1,'security_type':'common_equity','sector_class':'operating_company'}],client=FakeSEC(issuer),ledger=l,index=idx,policy=PUBLIC,at=NOW,received_at=NOW,quotes=fake_quotes(quote()))
    candidate=screen_result['candidates'][0]
    m=market|{'evidence_ids':candidate['market_evidence_ids'],'price_asof':NOW,'shares_asof':'2026-11-18T00:00:00Z'}
    p={'cik':1,'decision_at':NOW,'strategy_version':'fixture','policy':{'status':'ACTIVE_APPROVED','owner_approval':{'approved':True},'limits':LIMITS},'fundamental_ids':candidate['fundamental_evidence_ids'],'market':m,'assumptions':{'bear':assumptions|{'growth':[.02]*5},'base':assumptions,'bull':assumptions|{'growth':[.15]*5}},'terminal_scenarios':scenarios,'benchmark_return':.08,'portfolio':portfolio_snapshot(),'target_weights':{'A':.3,'B':.2,'CASH':.5},'aligned_returns':returns(),'clusters':CLUSTERS,'stress_scenarios':stress()}
    r=run_packet(c,l,p);assert r['stage']=='bull' and r['status']=='BLOCKED_MISSING_HANDLER'
    memos={s:{'status':'RESEARCH_MEMO','researcher_id':s,'claim':'fixture claim','evidence_ids':[p['fundamental_ids'][0]],'can_trade':False} for s in ('bull','bear')}
    r=run_packet(c,l,p,attachments=memos);assert r['stage']=='verification'
    prior=c.state(r['run_id'])[1];review={'status':'VERIFIED','reviewer_id':'independent fixture','claims_verified':True,'reviewed_hashes':{s:digest(prior[s]) for s in ('fundamental','valuation','bull','bear')},'can_trade':False}
    r=run_packet(c,l,p,attachments=memos|{'verification':review});assert r['status']=='COMPLETE_RESEARCH_ONLY' and r['decision']['decision']=='WAIT' and len(r['completed_stages'])==10
