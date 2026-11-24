from pathlib import Path
from datetime import datetime,timedelta,timezone
import json,sqlite3,copy
import pytest
from atlas_pro.account_risk import review_accounts
from atlas_pro.role_jobs import RoleExecutor,RoleJournal,PUBLIC_TASKS,LOCAL_TASKS
from atlas_pro.core_service import execute_batch,readiness
from atlas_pro.ledger import EvidenceLedger,digest
from atlas_pro.retrieval import ResearchIndex
from atlas_pro.filing_ingest import filing_uri,ingest_recent_filings,FilingText
from atlas_pro.macro_ingest import ingest_macro
from atlas_pro.runtime import FixedModelTransport,ResearchModelRunner

ROOT=Path(__file__).resolve().parents[1];ROLES=json.loads((ROOT/'config/50 agent manifest.json').read_text())
AT='2026-11-23T18:00:00Z';OLD='2026-11-23T17:59:30Z';FUT='2026-11-24T18:00:00Z'
POL={'license_id':'SEC_PUBLIC','permitted_for_personal_analysis':True,'allow_local_retention':True,'allow_rag_indexing':True,'cloud_allowed':True}
LIM={'max_gross_economic_leverage':3,'max_single_stock_weight':2,'max_correlated_cluster_weight':3,'max_stress_loss':.8,'max_economic_leverage':3,'min_cash_reserve_weight':0}

def risk_fixture():
    p={'security_id':'TEST','asset_type':'equity','currency':'USD','quantity':10,'price':100,'price_asof':AT,'evidence_ids':['q'],'cluster_map':{'TEST':'tech'}}
    etf={'security_id':'LEV','asset_type':'etf','currency':'USD','quantity':10,'price':50,'price_asof':AT,'evidence_ids':['q'],'factor_exposure':{'TEST':3},'factor_evidence_ids':['factor'],'cluster_map':{'TEST':'tech'}}
    opt={'security_id':'OPT','asset_type':'option','currency':'USD','quantity':1,'price':2,'multiplier':100,'price_asof':AT,'evidence_ids':['q'],'right':'call','style':'american','underlying_id':'TEST','underlying_price':100,'underlying_asof':AT,'strike':105,'delta':.4,'risk_free_rate':.04,'rate_evidence_ids':['rate'],'greeks_asof':AT,'greek_evidence_ids':['g'],'expiry':FUT,'cluster_map':{'TEST':'tech'}}
    # 1000 USD equity + 500 USD ETF + 200 USD option; CAD FX 1.4; CAD cash 620 => 3000 CAD.
    a={'account_id':'M','as_of':AT,'account_type':'margin','nav_base':3000,'cash_by_currency':{'CAD':620},'positions':[p,etf,opt],'maintenance_margin_base':500,'excess_liquidity_base':2000,'margin_as_of':AT,'margin_evidence_ids':['m'],'evidence_ids':['a']}
    b={'account_id':'R','as_of':AT,'account_type':'registered','nav_base':1000,'cash_by_currency':{'CAD':1000},'positions':[],'maintenance_margin_base':0,'excess_liquidity_base':1000,'evidence_ids':['b']}
    snap={'as_of':AT,'complete':True,'reconciled':True,'base_currency':'CAD','evidence_ids':['root'],'fx':{'USD':{'rate_to_base':1.4,'as_of':AT,'evidence_ids':['fx']}},'accounts':[a,b]}
    stress={str(i):{'price_shocks':{'TEST':-.1*i,'LEV':-.2*i},'fx_shocks':{'USD':-.05*i},'maintenance_multiplier':1+.1*i} for i in range(1,4)}
    return snap,stress

def risk(snap=None,stress=None,limits=None,expected=None):
    s,t=risk_fixture();return review_accounts(snap or s,expected_accounts=expected or ['M','R'],scenarios=stress or t,limits=limits or LIM,at=AT)

def test_multicurrency_leveraged_etf_option_risk():
    r=risk();assert r['nav_base']==4000;assert r['metrics']['gross_economic_leverage']==pytest.approx((1000+1500+4000)*1.4/4000);assert r['metrics']['cash_weight']==pytest.approx(1620/4000);assert not r['can_trade'] and not r['broker_margin_verified'];assert 'M' in r['stress']['3']['accounts']

def test_margin_is_not_cross_collateralized():
    s,t=risk_fixture();s['accounts'][0]['excess_liquidity_base']=10
    r=risk(s,t);assert any(x.startswith('STRESS_MARGIN_DEFICIT:M:') for x in r['reasons']);assert r['stress']['3']['accounts']['R']['estimated_excess_liquidity_base'] is None

@pytest.mark.parametrize('mode',['missing_account','future_quote','stale_fx','wrong_nav','missing_greeks','missing_etf_map','missing_margin','future_snapshot','missing_price_shock','wrong_fx_shock','unknown_type','duplicate_position'])
def test_account_rejects_bad_inputs(mode):
    s,t=risk_fixture();a=s['accounts'][0];p=a['positions']
    if mode=='missing_account':s['accounts'].pop()
    elif mode=='future_quote':p[0]['price_asof']=FUT
    elif mode=='stale_fx':s['fx']['USD']['as_of']='2026-11-22T18:00:00Z'
    elif mode=='wrong_nav':a['nav_base']=3001
    elif mode=='missing_greeks':p[2]['greek_evidence_ids']=[]
    elif mode=='missing_etf_map':p[1]['factor_exposure']={}
    elif mode=='missing_margin':a['margin_evidence_ids']=[]
    elif mode=='future_snapshot':s['as_of']=FUT
    elif mode=='missing_price_shock':del t['1']['price_shocks']['LEV']
    elif mode=='wrong_fx_shock':t['1']['fx_shocks']={}
    elif mode=='unknown_type':p[0]['asset_type']='future'
    else:p.append(p[0])
    with pytest.raises((ValueError,KeyError)):risk(s,t)

def test_account_roster_requires_exact():
    with pytest.raises(ValueError):risk(expected=['M'])

def test_risk_policy_limit_rejects():
    r=risk(limits=LIM|{'max_gross_economic_leverage':1});assert 'LIMIT:max_gross_economic_leverage' in r['reasons']

@pytest.fixture
def jobs(tmp_path):return RoleExecutor(ROLES,EvidenceLedger(tmp_path/'evidence')),RoleJournal(tmp_path/'jobs')

def test_role_catalog(jobs):
    e,j=jobs;c=e.catalog();assert len(c)==50 and len({x['role_id'] for x in c})==50 and all(x['can_trade'] is False for x in c)

@pytest.mark.parametrize('role_id',sorted(PUBLIC_TASKS))
def test_public_job_explicitly_blocks_without_runner(role_id,jobs):
    e,j=jobs;sid='MACRO:US' if PUBLIC_TASKS[role_id][0]=='macro' else 'CIK:1';r=j.execute(e,role_id,at=AT,run_id='run',inputs={'security_id':sid});assert r['status']=='BLOCKED_MODEL_RUNTIME' and r['can_trade'] is False

def test_public_scope_rejects_private_inputs(jobs):
    e,j=jobs;assert j.execute(e,'A031',at=AT,run_id='x',inputs={'security_id':'CIK:1','account':'private'})['status']=='BLOCKED_INPUT'

def test_public_model_fixed_task_and_query(jobs):
    e,j=jobs
    class Runner:
        def run(self,**kwargs):
            assert kwargs['security_id']=='CIK:1' and kwargs['query']==PUBLIC_TASKS['A031'][1] and kwargs['task_set']=='atlas-role-a031-v1'
            return {'status':'UNVERIFIED_RESEARCH_MEMO','can_trade':False}
    e.model_runner=Runner();assert j.execute(e,'A031',at=AT,run_id='x',inputs={'security_id':'CIK:1'})['status']=='UNVERIFIED_RESEARCH_MEMO'

def test_journal_idempotency_conflict_and_recovery(jobs):
    e,j=jobs;r=j.execute(e,'A095',at=AT,run_id='x',inputs={});assert r['status']=='DENIED';assert j.execute(e,'A095',at=AT,run_id='x',inputs={})==r
    with pytest.raises(ValueError):j.execute(e,'A095',at=AT,run_id='x',inputs={'new':1})
    k=digest({'role':'A095','run_id':'crash'});rh=digest({'at':'2026-11-23T18:00:00+00:00','inputs':{}})
    with sqlite3.connect(j.path) as db:db.execute('insert into role_jobs values(?,?,NULL,NULL)',(k,rh))
    assert j.execute(e,'A095',at=AT,run_id='crash',inputs={})['status']=='UNRESOLVED_JOB_NO_RESEND'

def test_local_job_risk_calculation(jobs):
    e,j=jobs;s,t=risk_fixture();r=j.execute(e,'A093',at=AT,run_id='x',inputs={'snapshot':s,'expected_accounts':['M','R'],'scenarios':t,'limits':LIM});assert r['nav_base']==4000 and not r['can_trade']

def test_unvalidated_kelly(jobs):
    e,j=jobs;sc={'bear':{'probability':.3,'terminal_price':5},'base':{'probability':.4,'terminal_price':12},'bull':{'probability':.3,'terminal_price':20}}
    r=j.execute(e,'A083',at=AT,run_id='x',inputs={'scenarios':sc,'price':10,'benchmark_return':.08,'probabilities_validated':True});assert r['kelly_capped_single_asset'] is None and r['decision']=='WAIT'

def test_option_bounds(jobs):
    e,j=jobs;r=j.execute(e,'A045',at=AT,run_id='x',inputs={'spot':100,'strike':90,'mark':5,'risk_free_rate':.05,'dividend_yield':0,'expiry':FUT,'right':'call','style':'american'});assert r['lower']==10 and not r['mark_inside']

def test_fill_reconcile(jobs):
    e,j=jobs;x={'execution_id':'a','security_id':'x','side':'buy','quantity':1,'price':10,'commission':1,'currency':'USD','evidence_id':'e'}
    assert j.execute(e,'A094',at=AT,run_id='x',inputs={'local_fills':[x],'broker_fills':[x|{'price':11}]})['status']=='BLOCK'

@pytest.mark.parametrize('role',sorted(LOCAL_TASKS))
def test_local_routes_never_call_model(role,jobs):
    e,j=jobs
    class Forbidden:
        def run(self,**kw):raise AssertionError('local role must never call LLM')
    e.model_runner=Forbidden();r=j.execute(e,role,at=AT,run_id='missing',inputs={});assert r['can_trade'] is False

def _record(ledger,rid):
    ledger.add_evidence({'record_id':rid,'source_id':'sec_edgar','document_id':rid,'security_id':'CIK:1','observed_at':OLD,'published_at':OLD,'available_at':OLD,'payload':{'value':1},'data_class':'public','license_id':'SEC_PUBLIC'},policy=POL)

def test_batch_runs_screened_candidate_and_freezes(jobs):
    e,j=jobs;_record(e.ledger,'f');_record(e.ledger,'m');screen={'can_trade':False,'candidates':[{'status':'CANDIDATE','can_trade':False,'cik':1,'symbol':'TEST','fundamental_evidence_ids':['f'],'market_evidence_ids':['m'],'decision_at':OLD}]}
    r=execute_batch(screen,e,j,run_id='b',at=AT,roles=['A031','A101']);assert r['expected_jobs']==2 and r['blocked_or_other_jobs']==2 and r['decision']=='WAIT';assert execute_batch(screen,e,j,run_id='b',at=AT,roles=['A031','A101'])==r
    with pytest.raises(ValueError):execute_batch(screen,e,j,run_id='b',at=FUT,roles=['A031','A101'])

def test_batch_rejects_future(jobs):
    e,j=jobs;s={'can_trade':False,'candidates':[{'status':'CANDIDATE','can_trade':False,'cik':1,'symbol':'TEST','fundamental_evidence_ids':['f'],'market_evidence_ids':['m'],'decision_at':FUT}]}
    with pytest.raises(ValueError):execute_batch(s,e,j,run_id='b',at=AT)

def test_filing_ingest_and_cutoff(tmp_path):
    ledger=EvidenceLedger(tmp_path/'e');index=ResearchIndex(tmp_path/'r');sub={'cik':1,'filings':{'recent':{'accessionNumber':['0000000001-26-000001'],'acceptanceDateTime':[OLD],'form':['10-K'],'primaryDocument':['test.htm']}}}
    raw=b'<html><head><script>ignore this</script></head><body><p>'+b'Company revenue and risk factors. '*30+b'</p><table><tr><td>Revenue</td><td>100</td></tr></table></body></html>'
    r=ingest_recent_filings(sub,cik=1,ledger=ledger,index=index,policy=POL,transport=lambda *x:raw,received_at=AT);assert len(r['filings'])==1 and r['filings'][0]['chunks']>=1
    assert not index.search('revenue',decision_at=OLD,security_id='CIK:1');docs=index.search('revenue',decision_at=AT,security_id='CIK:1');assert docs and all('ignore this' not in d['text'] for d in docs)
    assert ledger.verify_chain() and ledger.verify_evidence_integrity()

@pytest.mark.parametrize('filename',['../../bad.htm','https://bad.htm','file.pdf','evil?x.htm'])
def test_filing_uri_rejects(filename):
    with pytest.raises(ValueError):filing_uri(1,'0000000001-26-000001',filename)

def test_macro_current_only(tmp_path):
    ledger=EvidenceLedger(tmp_path/'e');index=ResearchIndex(tmp_path/'r')
    class Client:
        def boc_observations(self,*a,**kw):return {'observations':[{'d':'2026-11-20','FXUSDCAD':{'v':'1.4'}}]}
    pol=POL|{'license_id':'BOC_TEST','series_id':'FXUSDCAD'};r=ingest_macro(Client(),ledger,index,series='FXUSDCAD',policy=pol,received_at=AT);assert len(r['evidence_ids'])==1
    assert not index.search('CAD',decision_at=OLD,security_id='MACRO:US');assert index.search('CAD',decision_at=AT,security_id='MACRO:US')
    with pytest.raises(PermissionError):ingest_macro(Client(),ledger,index,series='FXUSDCAD',policy=pol|{'cloud_allowed':False},received_at=AT)

def test_disabled_transport_no_reservation():
    class G:
        roles={'role':{'role':'research','data_scope':'public_only'}};registry={}
        def select_and_reserve(self,**kwargs):raise AssertionError('no budget reservation')
    class Index:
        def search(self,*a,**kw):return [{'doc_id':'a'}]
    r=ResearchModelRunner(G(),Index(),FixedModelTransport());assert r.run(role_id='role',task_set='test',request_id='r',security_id='CIK:1',query='income',at='2020-01-01T00:00:00Z')['status']=='PAID_INFERENCE_DISABLED'

from atlas_pro.bench_runner import run_numeric_eval
from atlas_pro.models import ModelGateway

def test_benchmark_no_gold_and_no_duplicate(tmp_path):
    registry=json.loads((ROOT/'config/model registry.json').read_text());g=ModelGateway(tmp_path/'models',registry,ROLES);c=[{'case_id':'fixture','question':'What is reported revenue?','documents':[{'doc_id':'e','text':'Reported revenue is 42.','scope':'public','available_at':OLD}], 'decision_at':AT,'evaluation_rights_verified':True,'cloud_evaluation_allowed':True,'synthetic':True,'expected_values':{'revenue':42},'allowed_evidence_ids':['e']}]
    calls=[]
    def fake(provider,body):
        calls.append(body);assert 'expected_values' not in body['input'] and 'synthetic' not in body['input']
        return {'model':body['model'],'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{"values":{"revenue":42},"evidence_ids":["e"],"abstain":false}'}]}],'usage':{'input_tokens':100,'output_tokens':20}}
    kw=dict(locked_hash=digest(c),role_id='A011',model_id='gpt-6.2-sol',run_id='run',journal_path=tmp_path/'bench',max_budget_usd='1',at=AT,confirmed=True)
    a=run_numeric_eval(g,fake,c,**kw);assert a['grade']['quality']==1 and not a['grade']['eligible_for_external_review'] and not a['promotion_allowed'];assert run_numeric_eval(g,fake,c,**kw)==a and len(calls)==1
    with pytest.raises(PermissionError):run_numeric_eval(g,fake,c,**(kw|{'run_id':'new','max_budget_usd':'0'}))
    with pytest.raises(ValueError):run_numeric_eval(g,fake,c,**(kw|{'locked_hash':'wrong'}))
    c[0]['cloud_evaluation_allowed']=False
    with pytest.raises(PermissionError):run_numeric_eval(g,fake,c,**(kw|{'run_id':'new','locked_hash':digest(c)}))

from atlas_pro.runtime import google_body,google_output,ModelCallError
from atlas_pro.evaluation import grade_locked

def test_google_usage_includes_thinking_and_no_tools():
    body=google_body('gemini-example','instructions','prompt',100,'low');assert body['generationConfig']['thinkingConfig']['thinkingLevel']=='LOW' and 'tools' not in body
    r={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'thought','thought':True},{'text':'{}'}]}}],'usageMetadata':{'promptTokenCount':10,'candidatesTokenCount':3,'thoughtsTokenCount':40,'totalTokenCount':53}}
    assert google_output(r)==('{}',10,43)
    r['usageMetadata']['totalTokenCount']=13
    with pytest.raises(ModelCallError):google_output(r)

def test_google_rejects_tool_call():
    r={'candidates':[{'finishReason':'STOP','content':{'parts':[{'functionCall':{'name':'trade'}}]}}]}
    with pytest.raises(ModelCallError):google_output(r)

def test_numeric_evaluation_abstention_and_tolerance():
    c=[{'case_id':'a','evaluation_rights_verified':True,'must_abstain':True,'allowed_evidence_ids':[]}];answers={'a':{'abstain':True,'values':{},'evidence_ids':['fake']}}
    assert grade_locked(c,answers,expected_hash=digest(c))['critical_failures']==1
    c[0]['relative_tolerance']=100
    with pytest.raises(ValueError):grade_locked(c,answers,expected_hash=digest(c))
