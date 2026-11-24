"""Developer fixtures exercise recomputation and rejection; not actual evidence."""
import hashlib,json,math,copy
import pytest
from atlas_pro.performance_evidence import audit_performance,check_signed_metrics,full_session_closes,_hac
from atlas_pro.rag_evidence import audit_rag,check_rag_metrics
from atlas_pro.ledger import digest
from datetime import timedelta


def store(root,obj):
    b=json.dumps(obj,sort_keys=True,allow_nan=False).encode();h=hashlib.sha256(b).hexdigest();(root/h).write_bytes(b);return h


@pytest.fixture
def perf(tmp_path):
    start='2023-01-01T00:00:00Z';end='2025-01-01T00:00:00Z';review='2025-01-04T00:00:00Z'
    closes=full_session_closes(start,end)
    raw=store(tmp_path,{'synthetic_fixture':'daily observations'});trialraw=store(tmp_path,{'synthetic_fixture':'completed attempt'});failed=store(tmp_path,{'synthetic_fixture':'failed attempt'})
    rr=[];br=[];cr=[]
    for i,t in enumerate(closes):
        row={'at':t.isoformat(),'recorded_at':(t+timedelta(hours=1)).isoformat(),'evidence_hash':raw}
        b=.01*math.sin(i*.91)+.0002
        rr.append(row|{'gross_return':.0015+1.1*b+.003*math.cos(i*.71),'cash_flow_adjusted':True})
        br.append(row|{'return':b,'risk_free_return':.0001,'total_return':True});cr.append(row|{'cost_fraction':.0002,'all_costs_included':True})
    a={'kind':'BENCHMARK_DAILY_V1','benchmark_id':'SYNTHETIC','currency':'USD','rows':br};b={'kind':'COST_DAILY_V1','currency':'USD','rows':cr}
    p={'period_start':start,'period_end':end,'reviewed_at':review,'benchmark_hash':store(tmp_path,a),'cost_model_hash':store(tmp_path,b)}
    ret={'kind':'PORTFOLIO_DAILY_V1','currency':'USD','mode':'forward_paper','frozen_at':start,'trial_id':'a','rows':rr,'benchmark_hash':p['benchmark_hash'],'cost_model_hash':p['cost_model_hash']}
    p['returns_hash']=store(tmp_path,ret)
    trials={'kind':'PERFORMANCE_TRIALS_V1','registered_at':start,'selected_trial_id':'a','returns_hash':p['returns_hash'],'trials':[{'id':'a','status':'COMPLETED','result_hash':trialraw},{'id':'b','status':'FAILED','result_hash':failed}]}
    p['trial_registry_hash']=store(tmp_path,trials);p['artifact_hashes']=[p[k] for k in ('benchmark_hash','cost_model_hash','returns_hash','trial_registry_hash')]+[raw,trialraw,failed]
    return p,ret,trials,a,b,tmp_path


def update(perf,ret=None,trials=None):
    p,old,t,a,b,root=perf;p=copy.deepcopy(p);ret=old if ret is None else ret;trials=t if trials is None else trials
    h=store(root,ret);p['returns_hash']=h;trials=trials|{'returns_hash':h};p['trial_registry_hash']=store(root,trials);p['artifact_hashes'] += [h,p['trial_registry_hash']];return p


def test_recompute_all_daily(perf):
    p,*_,root=perf;r=audit_performance(p,root,gate='G9_forward_performance');assert r['n']>480 and r['trial_count']==2 and r['net_excess_lower_ci']>0 and r['risk_adjusted_excess_lower_ci']>0 and r['multiple_test_adjusted_p']<.05 and not r['can_trade']
    p['metrics']={'net_excess_lower_ci':r['net_excess_lower_ci'],'risk_adjusted_excess_lower_ci':r['risk_adjusted_excess_lower_ci'],'max_drawdown':r['max_drawdown'],'prospective_sessions':r['n']}
    assert check_signed_metrics(p,root,gate='G9_forward_performance')==[]
    p['metrics']['net_excess_lower_ci']+=.001
    assert 'recomputed_metric_mismatch:net_excess_lower_ci' in check_signed_metrics(p,root,gate='G9_forward_performance')

@pytest.mark.parametrize('attack',['missing_session','duplicate_session','late_record','unadjusted','wrong_mode','posthoc','missing_evidence','no_cost_hash','invalid_return','unfinished_trial','duplicate_result','wrong_currency'])
def test_perf_refusals(perf,attack):
    p,ret,trials,a,b,root=perf;ret=copy.deepcopy(ret);trials=copy.deepcopy(trials)
    if attack=='missing_session':ret['rows'].pop()
    elif attack=='duplicate_session':ret['rows'][1]=ret['rows'][0]
    elif attack=='late_record':ret['rows'][0]['recorded_at']='2024-01-01T00:00:00Z'
    elif attack=='unadjusted':ret['rows'][0]['cash_flow_adjusted']=False
    elif attack=='wrong_mode':ret['mode']='historical_oos'
    elif attack=='posthoc':trials['registered_at']='2024-01-01T00:00:00Z'
    elif attack=='missing_evidence':ret['rows'][0]['evidence_hash']='a'*64
    elif attack=='no_cost_hash':ret['cost_model_hash']='a'*64
    elif attack=='invalid_return':ret['rows'][0]['gross_return']=-1
    elif attack=='unfinished_trial':trials['trials'][1]['status']='RUNNING'
    elif attack=='duplicate_result':trials['trials'][1]['result_hash']=trials['trials'][0]['result_hash']
    else:ret['currency']='CAD'
    with pytest.raises(ValueError):audit_performance(update(perf,ret,trials),root,gate='G9_forward_performance')


def test_losing_strategy_rejected(perf):
    p,ret,*_,root=perf;ret=copy.deepcopy(ret)
    for row in ret['rows']:row['gross_return']-=.003
    p=update(perf,ret);r=audit_performance(p,root,gate='G9_forward_performance');assert r['net_excess_lower_ci']<0
    p['metrics']={'net_excess_lower_ci':.01,'risk_adjusted_excess_lower_ci':.01,'max_drawdown':0,'prospective_sessions':r['n']}
    assert 'no_adjusted_net_advantage' in check_signed_metrics(p,root,gate='G9_forward_performance')


def test_hac_against_statsmodels():
    sm=pytest.importorskip('statsmodels.api');import numpy as np
    from statsmodels.stats.sandwich_covariance import cov_hac
    from scipy.stats import norm
    t=np.arange(500);x=np.column_stack([np.ones(len(t)),np.sin(t*.3)*.01]);y=.001+1.2*x[:,1]+.003*np.cos(t*.75)
    r=_hac(y,x,2);fit=sm.OLS(y,x).fit();ses=[math.sqrt(cov_hac(fit,nlags=k,use_correction=True)[0,0]) for k in (5,10,20)]
    assert r['estimate']==pytest.approx(fit.params[0]);assert r['max_hac_se']==pytest.approx(max(ses));assert r['lower_ci']==pytest.approx(min(fit.params[0]-norm.isf(.025)*s for s in ses))


@pytest.fixture
def rag(tmp_path):
    raw=store(tmp_path,{'synthetic':'raw source'});ds=[{'id':'public','scope':'public','security_id':'A','available_at':'2024-01-01T00:00:00Z','raw_hash':raw},{'id':'other','scope':'public','security_id':'B','available_at':'2024-01-01T00:00:00Z','raw_hash':raw},{'id':'future','scope':'public','security_id':'A','available_at':'2026-01-01T00:00:00Z','raw_hash':raw},{'id':'private','scope':'private','security_id':'A','available_at':'2024-01-01T00:00:00Z','raw_hash':raw}]
    cs=[];rs=[];gs=[]
    for i in range(500):
        cid=str(i);cl={'id':'1','text':'fixture claim','citation_ids':['public']};cs.append({'id':cid,'query':'fixture question '+cid,'security_id':'A','scope':'public_only','decision_at':'2024-06-01T00:00:00Z','gold_ids':['public'] if i<480 else []});rs.append({'case_id':cid,'retrieved_ids':['public'] if i<480 else [],'claims':[cl] if i<480 else [],'abstained':i>=480})
        if i<480:gs.append({'case_id':cid,'claim_id':'1','claim_hash':digest(cl),'material':True,'entailed':True,'reviewer_rationale':'synthetic test'})
    c={'kind':'RAG_CASES_V1','cases':cs,'synthetic':False,'independently_adjudicated':True,'corpus_complete_for_benchmark':True,'locked_at':'2025-01-01T00:00:00Z'}
    r={'kind':'RAG_RESULTS_V1','results':rs,'top_k':10,'run_at':'2025-01-02T00:00:00Z'};g={'kind':'RAG_JUDGMENTS_V1','judgments':gs,'graded_at':'2025-01-03T00:00:00Z'};d={'kind':'RAG_CORPUS_V1','documents':ds}
    return c,r,g,d,raw,tmp_path


def pack(rag):
    c,r,g,d,raw,root=rag;p={'period_start':'2024-01-01T00:00:00Z','period_end':'2025-01-04T00:00:00Z','reviewed_at':'2025-01-05T00:00:00Z','rag_cases_hash':store(root,c),'rag_corpus_hash':store(root,d)};p['rag_results_hash']=store(root,r|{'cases_hash':p['rag_cases_hash'],'corpus_hash':p['rag_corpus_hash']});p['rag_claim_judgments_hash']=store(root,g|{'results_hash':p['rag_results_hash']});p['artifact_hashes']=[p[k] for k in ('rag_cases_hash','rag_corpus_hash','rag_results_hash','rag_claim_judgments_hash')]+[raw];return p


def test_rag_recompute(rag):
    p=pack(rag);root=rag[-1];a=audit_rag(p,root);assert a['real_holdout_cases']==500 and a['answerable_cases']==480 and a['recall_at_10']==1 and a['material_claim_entailment']==1
    p['metrics']={k:a[k] for k in ('real_holdout_cases','recall_at_10','material_claim_entailment','private_leaks','future_leaks')};assert not check_rag_metrics(p,root)
    p['metrics']['recall_at_10']=.99;assert 'recomputed_metric_mismatch:recall_at_10' in check_rag_metrics(p,root)

@pytest.mark.parametrize('attack',['duplicate_case','missing_judgment','uncited_claim','changed_claim','no_answer_overclaim','bad_gold','wrong_entity','future','private'])
def test_rag_refusals(rag,attack):
    c,r,g,d,raw,root=rag
    if attack=='duplicate_case':c['cases'][1]['query']=c['cases'][0]['query']
    elif attack=='missing_judgment':g['judgments'].pop()
    elif attack=='uncited_claim':r['results'][0]['claims'][0]['citation_ids']=[]
    elif attack=='changed_claim':r['results'][0]['claims'][0]['text']='changed'
    elif attack=='no_answer_overclaim':r['results'][-1]['abstained']=False
    elif attack=='bad_gold':c['cases'][0]['gold_ids']=['other']
    else:r['results'][0]['retrieved_ids'].append({'wrong_entity':'other','future':'future','private':'private'}[attack])
    p=pack(rag)
    if attack in ('wrong_entity','future','private'):
        a=audit_rag(p,root);assert a[{'wrong_entity':'cross_entity_leaks','future':'future_leaks','private':'private_leaks'}[attack]]==1
    else:
        with pytest.raises(ValueError):audit_rag(p,root)


def test_financebench_reference_fixture():
    from atlas_pro.financebench_reference import run_reference
    a={'financebench_id':'a','company':'A','doc_name':'A_2024_10K','question':'capital spending','answer':'not indexed','evidence':[{'doc_name':'A_2024_10K','evidence_page_num':1,'evidence_text_full_page':'capital spending 12'}]}
    b={'financebench_id':'b','company':'B','doc_name':'B_2024_10K','question':'liabilities','answer':'not indexed','evidence':[{'doc_name':'B_2024_10K','evidence_page_num':2,'evidence_text_full_page':'liabilities 23'}]}
    r=run_reference([a,b]);assert r['questions']==2 and r['benchmark']['global']['r1']==1 and r['can_trade'] is False
    with pytest.raises(ValueError):run_reference([a,a])


def test_weekend_and_holiday_closes():
    # Thanksgiving 2024 closed, Friday early close at 18:00 UTC.
    r=full_session_closes('2024-11-28T00:00:00Z','2024-12-01T00:00:00Z')
    assert [x.isoformat() for x in r]==['2024-11-29T18:00:00+00:00']


def test_signed_performance_gate_recomputes(perf):
    from atlas_pro.l6_acceptance import evaluate
    from atlas_pro.independent_review import strict_json
    from atlas_pro.skill_contracts import catalog
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
    p,*_,root=perf;gate='G9_forward_performance';r=audit_performance(p,root,gate=gate)
    keys=[Ed25519PrivateKey.generate() for _ in range(2)];trust={str(i):{'public_key':k.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw).hex(),'role':role,'identity':str(i),'organization':'fixture-'+str(i),'revoked':False} for i,(k,role) in enumerate(zip(keys,('domain_reviewer','independent_validator')))}
    p=p|{'kind':'L6_GATE_V1','gate':gate,'release_hash':'a'*64,'mandate_hash':'b'*64,'role_contract_hash':digest(catalog()),'synthetic':False,'producer_organization':'fixture','data_rights_verified':True,'valid_until':'2025-02-01T00:00:00Z','metrics':{'prospective_sessions':r['n'],'market_regimes':2,'net_excess_lower_ci':r['net_excess_lower_ci'],'risk_adjusted_excess_lower_ci':r['risk_adjusted_excess_lower_ci'],'max_drawdown':r['max_drawdown'],'risk_budget_breaches':0}}
    def review():
        return evaluate({gate:{'payload':p,'signatures':[{'reviewer_id':str(i),'signature':k.sign(strict_json(p)).hex()} for i,k in enumerate(keys)]}},trust,at='2025-01-05T00:00:00Z',release_hash='a'*64,mandate_hash='b'*64,role_contract_hash=digest(catalog()),artifact_dir=root)
    result=review();assert result['gates'][gate]['status']=='REVIEWED_THRESHOLDS_MET',result['gates'][gate]
    p['metrics']['net_excess_lower_ci']+=.01
    a=review();assert a['gates'][gate]['status']=='BLOCKED' and 'recomputed_metric_mismatch:net_excess_lower_ci' in a['gates'][gate]['reasons'] and a['l6_certified'] is False
