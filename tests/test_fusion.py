from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from atlas_pro.ledger import digest
from atlas_pro.portfolio import tail_loss,portfolio_review
from atlas_pro.optimizer import minimum_cvar
from atlas_pro.experiments import purged_folds,experiment_request,review_experiment
from atlas_pro.committee import Committee,STAGES
from atlas_pro.discovery import rank_factors
from atlas_pro.rag_eval import evaluate_retrieval
from atlas_pro.retrieval import ResearchIndex
from atlas_pro.evaluation import grade_locked

AT='2026-11-23T18:00:00Z'; FUT='2026-11-24T18:00:00Z'; OLD='2026-11-20T18:00:00Z'
LIMITS={'max_single_stock_weight':.5,'max_correlated_cluster_weight':.7,'max_gross_economic_leverage':1.,'max_economic_leverage':1.,'min_cash_reserve_weight':.2,'max_turnover':1.,'max_cvar':.2,'max_stress_loss':.2}
CLUSTERS={'A':'tech','B':'tech'}

def snapshot():return {'as_of':AT,'complete':True,'reconciled':True,'currency':'USD','account_type':'cash','cash':800,'nav':1000,'evidence_ids':['e'],'positions':[{'security_id':'A','quantity':2,'price':100,'price_asof':AT,'asset_type':'common_equity','unlevered':True,'evidence_ids':['q']}]}

def returns():return [{'at':(datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(days=i)).isoformat(),'available_at':(datetime(2025,1,2,tzinfo=timezone.utc)+timedelta(days=i)).isoformat(),'returns':{'A':-.1 if i%10==0 else .02,'B':-.02 if i%10==0 else .01,'CASH':0},'evidence_ids':['fixture']} for i in range(120)]

def stress():return {str(i):{'A':-i*.1,'B':-i*.05,'CASH':0} for i in range(1,4)}

def test_fractional_tail():assert tail_loss([-.3,-.1,.2,.3],.625)==pytest.approx((.3+.05)/1.5)

def test_portfolio_recalculation():
    r=portfolio_review(snapshot(),{'A':.3,'B':.2,'CASH':.5},returns(),CLUSTERS,LIMITS,at=AT,stress_scenarios=stress());assert r['status']=='SHADOW_RISK_REVIEW' and r['metrics']['turnover']==pytest.approx(.3) and r['metrics']['cluster']==pytest.approx(.5) and r['metrics']['worst_stress_loss']==pytest.approx(.12) and not r['can_trade']

def test_risk_aggregate_cluster():
    r=portfolio_review(snapshot(),{'A':.4,'B':.4,'CASH':.2},returns(),CLUSTERS,LIMITS,at=AT,stress_scenarios=stress());assert 'max_correlated_cluster_weight' in r['reasons']

@pytest.mark.parametrize('patch',[{'as_of':FUT},{'as_of':OLD},{'nav':999},{'cash':-1},{'account_type':'margin'},{'reconciled':'true'},{'currency':'CAD'}])
def test_risk_snapshot_reject(patch):
    with pytest.raises(ValueError):portfolio_review(snapshot()|patch,{'A':.4,'CASH':.6},returns(),CLUSTERS,LIMITS,at=AT,stress_scenarios=stress())

@pytest.mark.parametrize('patch',[{'available_at':FUT},{'evidence_ids':[]},{'returns':{'CASH':0}},{'returns':{'A':-2,'CASH':0}}])
def test_risk_returns_reject(patch):
    rows=returns();rows[0]|=patch
    with pytest.raises(ValueError):portfolio_review(snapshot(),{'A':.4,'CASH':.6},rows,CLUSTERS,LIMITS,at=AT,stress_scenarios=stress())

def test_scipy_optimizer():
    pytest.importorskip('scipy'); r=minimum_cvar([x['returns'] for x in returns()],limits=LIMITS,clusters=CLUSTERS,expected_return_floor=.002)
    assert r['status']=='RESEARCH_CANDIDATE' and r['sample_mean']>=.002-1e-9 and not r['can_trade']
    assert sum(r['weights'].values())==pytest.approx(1)
    assert portfolio_review(snapshot(),r['weights'],returns(),CLUSTERS,LIMITS,at=AT,stress_scenarios=stress())['status']=='SHADOW_RISK_REVIEW'

def test_scipy_infeasible():
    pytest.importorskip('scipy');assert minimum_cvar([x['returns'] for x in returns()],limits=LIMITS,clusters=CLUSTERS,expected_return_floor=1)['status']=='NO_FEASIBLE_SOLUTION'

def test_purge():
    start=datetime(2020,1,1,tzinfo=timezone.utc); rows=[{'id':str(i),'signal_at':(start+timedelta(days=i)).isoformat(),'feature_available_at':(start+timedelta(days=i)).isoformat(),'label_end_at':(start+timedelta(days=i+2)).isoformat()} for i in range(20)]
    fs=purged_folds(rows,min_train=4,test_size=4,embargo_seconds=86400);assert fs and all(max(map(int,f['train_ids']))+3<min(map(int,f['test_ids'])) for f in fs)
    with pytest.raises(ValueError):purged_folds([rows[0]|{'feature_available_at':FUT}]+rows[1:],min_train=4,test_size=4)

def experiment():
    ids=[str(i) for i in range(120)];req=experiment_request(engine='qlib',artifact_sha256='a'*64,data_sha256='b'*64,split_sha256=digest(ids),policy_sha256='c'*64,budget_usd=2,at=AT)
    report={k:req[k] for k in ('experiment_id','artifact_sha256','data_sha256','split_sha256','policy_sha256','engine')}|{'execution_mode':'OFFLINE_ISOLATED_RESEARCH','can_trade':False,'cost_usd':1,'synthetic':True,'observations':[{'id':i,'at':(datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(days=int(i))).isoformat(),'net_return':.001,'benchmark_return':0,'evidence_ids':['e']} for i in ids]}
    return req,report,ids

def test_experiment_synthetic_not_promoted():
    q,r,ids=experiment(); v=review_experiment(q,r,locked_test_ids=ids);assert v['status']=='REJECTED' and 'SYNTHETIC_OR_UNKNOWN_DATA' in v['blockers'] and not v['promotion_allowed']

def test_experiment_independent_review():
    q,r,ids=experiment();v=review_experiment(q,r|{'synthetic':False},locked_test_ids=ids);assert v['status']=='INDEPENDENT_REVIEW_REQUIRED' and not v['promotion_allowed']

@pytest.mark.parametrize('patch',[{'cost_usd':3},{'policy_sha256':'changed'},{'can_trade':True},{'engine':'unknown'}])
def test_experiment_mismatch(patch):
    q,r,ids=experiment()
    with pytest.raises(ValueError):review_experiment(q,r|patch,locked_test_ids=ids)

def test_experiment_missing_holdout():
    q,r,ids=experiment()
    with pytest.raises(ValueError):review_experiment(q,r|{'observations':r['observations'][1:]},locked_test_ids=ids)

def setup_committee(tmp_path):
    c=Committee(tmp_path/'committee.sqlite');rid=c.start(security_id='A',at=AT,policy_hash='p',strategy_version='s');return c,rid

def output(stage,prior):
    r={'status':'OK','can_trade':False}
    if stage in ('bull','bear'):r['researcher_id']=stage
    if stage=='verification':r|={'reviewer_id':'reviewer','reviewed_hashes':{k:digest(prior[k]) for k in ('fundamental','valuation','bull','bear')}}
    if stage=='decision':r|={'decision':'WAIT','position_size':None}
    return r

def test_committee_recover(tmp_path):
    c,rid=setup_committee(tmp_path);handlers={s:(lambda key,req,prior,stage=s:output(stage,prior)) for s in STAGES}
    for i in range(10):
        c=Committee(tmp_path/'committee.sqlite');assert c.advance(rid,handlers)['status']=='CHECKPOINTED'
    assert c.advance(rid,handlers)['status']=='COMPLETE_RESEARCH_ONLY'

def test_committee_missing_handler(tmp_path):
    c,rid=setup_committee(tmp_path);assert c.advance(rid,{})['status']=='BLOCKED_MISSING_HANDLER'

def test_committee_unsafe_or_order(tmp_path):
    c,rid=setup_committee(tmp_path)
    with pytest.raises(ValueError):c.append(rid,'evidence',{'can_trade':True})
    with pytest.raises(ValueError):c.append(rid,'bear',{'can_trade':False})
    c.append(rid,'evidence',{'can_trade':False});assert c.append(rid,'evidence',{'can_trade':False})=='DUPLICATE'
    with pytest.raises(ValueError):c.append(rid,'evidence',{'can_trade':False,'changed':True})

def test_committee_independence(tmp_path):
    c,rid=setup_committee(tmp_path)
    for s in STAGES[:5]:c.append(rid,s,output(s,c.state(rid)[1]))
    with pytest.raises(ValueError):c.append(rid,'bear',{'can_trade':False,'researcher_id':'bull'})
    c.append(rid,'bear',output('bear',{}))
    with pytest.raises(ValueError):c.append(rid,'verification',{'can_trade':False,'reviewer_id':'other','reviewed_hashes':{}})

def test_factor_rank():
    rows=[{'security_id':str(i),'sector':'tech','available_at':AT,'can_trade':False,'factors':{'quality':i,'value':i},'evidence_ids':['e']} for i in range(6)]
    r=rank_factors(rows,at=AT,weights={'quality':.5,'value':.5});assert r['ranked'][0]['security_id']=='5' and not r['can_trade']
    rows[0]['available_at']=FUT;assert '0' in rank_factors(rows,at=AT,weights={'quality':1})['rejected']

PUBLIC={'license_id':'SEC_PUBLIC','permitted_for_personal_analysis':True,'allow_local_retention':True,'allow_rag_indexing':True,'cloud_allowed':True}
def doc(i,**patch):return {'doc_id':i,'source_id':'sec','source_uri':'https://www.sec.gov/','security_id':'CIK:1','available_at':OLD,'scope':'public','license_id':'SEC_PUBLIC','content':'revenue'}|patch
class Embed:
    local_only=True
    def __init__(self,id):self.model_id=id
    def __call__(self,text):return [1.,0.]

def test_vector_model_isolation(tmp_path):
    idx=ResearchIndex(tmp_path/'rag');idx.add(doc('a',content='semantic'),PUBLIC,embed=Embed('a'))
    assert idx.search('unrelated',decision_at=AT,embed=Embed('a'))[0]['doc_id']=='a'
    assert not idx.search('unrelated',decision_at=AT,embed=Embed('b'))
    with pytest.raises(ValueError):idx.add(doc('a',content='semantic'),PUBLIC,embed=Embed('b'))

def test_retrieval_evaluation(tmp_path):
    idx=ResearchIndex(tmp_path/'rag');idx.add(doc('a'),PUBLIC);idx.add(doc('future',available_at=FUT),PUBLIC)
    cases=[{'case_id':'1','query':'revenue','decision_at':AT,'relevant_doc_ids':['a'],'evaluation_rights_verified':True}]
    r=evaluate_retrieval(idx,cases,expected_hash=digest(cases));assert r['recall_at_k']==r['mrr']==r['ndcg_at_k']==1 and r['boundary_violations']==0
    with pytest.raises(ValueError):evaluate_retrieval(idx,cases,expected_hash='modified')

def test_missing_abstention_is_critical():
    cases=[{'case_id':'a','evaluation_rights_verified':True,'must_abstain':True,'allowed_evidence_ids':[]}]
    assert grade_locked(cases,{},expected_hash=digest(cases))['critical_failures']==1

def test_market_evidence_value_binding(tmp_path):
    from atlas_pro.ledger import EvidenceLedger
    from atlas_pro.pipeline import market_evidence_matches
    ledger=EvidenceLedger(tmp_path/'ev'); market={'symbol':'A','currency':'USD','price':10,'price_asof':AT,'shares':100,'shares_asof':OLD,'available_at':AT,'evidence_ids':['q','s']}
    for id,t,payload in [('q',AT,{'symbol':'A','currency':'USD','price':10,'price_asof':AT}),('s',OLD,{'cik':1,'shares':100,'shares_asof':OLD})]:
        ledger.add_evidence({'record_id':id,'source_id':'fixture','document_id':id,'security_id':'CIK:1','observed_at':t,'published_at':t,'available_at':t,'payload':payload,'data_class':'public','license_id':'SEC_PUBLIC'},policy=PUBLIC)
    assert market_evidence_matches(ledger,market,cik=1,at=AT)
    assert not market_evidence_matches(ledger,market|{'price':20},cik=1,at=AT)
    assert not market_evidence_matches(ledger,market|{'shares':20},cik=1,at=AT)
    assert not market_evidence_matches(ledger,market,cik=2,at=AT)
    assert not market_evidence_matches(ledger,market,cik=1,at=OLD)

def test_vector_capacity_explicit(tmp_path):
    idx=ResearchIndex(tmp_path/'rag'); e=Embed('a')
    # Construct a large eligible exact-search fixture in a transaction.
    with idx._db() as c:
        c.executemany('INSERT INTO docs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',[(str(i),'sec','https://www.sec.gov/','CIK:1',OLD.replace('Z','+00:00'),'public','SEC_PUBLIC','fixture',AT,'[1,0]','revenue','a') for i in range(5001)])
    with pytest.raises(ValueError,match='CAPACITY'):idx.search('revenue',decision_at=AT,embed=e)

def test_p0_continuous_signals_not_suppressed_forever(tmp_path):
    import json
    from atlas_pro.events import EventBus
    root=Path(__file__).resolve().parents[1]
    rules=json.loads((root/'config/event rules.json').read_text());roles=json.loads((root/'config/50 agent manifest.json').read_text())
    bus=EventBus(tmp_path/'events',rules,roles=roles)
    event={'event_type':next(r['event_type'] for r in rules if r['priority']=='P0'),'signal_id':'ongoing-risk'}
    t=datetime.fromisoformat(AT.replace('Z','+00:00'))
    states=[bus.submit(event,verified=False,at=(t+timedelta(seconds=i)).isoformat())['status'] for i in range(12)]
    assert [i for i,x in enumerate(states) if x=='QUEUED']==[0,5,10]
