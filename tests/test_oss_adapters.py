import hashlib,json
from datetime import datetime,timedelta,timezone
import pytest
from atlas_pro.ledger import digest
from atlas_pro.oss_adapters import artifact_json,qlib_predictions,lean_equity_review,inspect_responses,duckdb_pit,LocalQdrantSnapshot,docling_markdown,skfolio_cvar
from atlas_pro.experiments import experiment_request
from atlas_pro.performance import paired_performance
from atlas_pro.promotion import compare_challenger
from atlas_pro.retrieval import ResearchIndex

OLD='2025-01-01T00:00:00+00:00';AT='2025-02-01T00:00:00+00:00';FUT='2025-03-01T00:00:00+00:00'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def day(i):return (datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(days=i)).isoformat()

@pytest.mark.parametrize('data',[b'{"a":1,"a":2}',b'{"a":NaN}',b'not json'])
def test_artifact_reject(tmp_path,data):
    p=tmp_path/'a.json';p.write_bytes(data)
    with pytest.raises(ValueError):artifact_json(p,sha(p))

def test_artifact(tmp_path):
    p=tmp_path/'a.json';p.write_text('{"a":1}');assert artifact_json(p,sha(p))=={'a':1}
    with pytest.raises(ValueError):artifact_json(p,'a'*64)

def pred():return {'security_id':'A','signal_at':AT,'training_label_end_at':OLD,'model_sha256':'a'*64,'data_sha256':'b'*64,'score':.2,'evidence_ids':['f']}
def lookup(ids,*,security_id,decision_at):return [{'record_id':'f','available_at':OLD,'security_id':security_id}]
def rank(rows):return qlib_predictions(rows,universe=['A','B'],decision_at=AT,model_hash='a'*64,data_hash='b'*64,evidence_lookup=lookup)
def test_qlib():assert rank([pred()])['missing']==['B'] and rank([pred()])['can_trade'] is False
@pytest.mark.parametrize('patch',[{'signal_at':FUT},{'training_label_end_at':AT},{'model_sha256':'bad'},{'security_id':'Z'},{'score':float('nan')},{'evidence_ids':['wrong']}])
def test_qlib_reject(patch):
    with pytest.raises(ValueError):rank([pred()|patch])

def test_lean_curve():
    ids=['1','2'];r=experiment_request(engine='lean',artifact_sha256='a'*64,data_sha256='b'*64,split_sha256=digest(ids),policy_sha256='c'*64,budget_usd=2,at=OLD)
    equity=[{'id':str(i),'at':day(i),'net_equity':100*(1.1**i),'external_flow':0,'evidence_ids':['e']} for i in range(3)]
    benchmark=[{'id':str(i),'at':day(i),'total_return_index':100,'evidence_ids':['b']} for i in range(3)]
    result=lean_equity_review(r,equity_rows=equity,benchmark_rows=benchmark,locked_test_ids=ids,cost_usd=0,synthetic=True)
    assert result['net_return']==pytest.approx(.21) and result['status']=='REJECTED'
    with pytest.raises(ValueError):lean_equity_review(r,equity_rows=[equity[0]|{'external_flow':10},*equity[1:]],benchmark_rows=benchmark,locked_test_ids=ids,cost_usd=0,synthetic=True)

def test_inspect_independent_grading():
    cases=[{'case_id':'1','allowed_evidence_ids':['e'],'expected_values':{'x':10},'evaluation_rights_verified':True,'synthetic':True}]
    good={'case_id':'1','completed':True,'completion':json.dumps({'values':{'x':10},'evidence_ids':['e'],'abstain':False}),'score':0}
    assert inspect_responses([good],cases,expected_hash=digest(cases),min_cases=1)['quality']==1
    assert inspect_responses([good|{'completion':'{"values":{"x":11},"evidence_ids":["e"],"abstain":false}','score':1}],cases,expected_hash=digest(cases))['quality']==0
    assert inspect_responses([good|{'completed':False}],cases,expected_hash=digest(cases))['quality']==0

def test_docling_refuses_without_sandbox(tmp_path):
    with pytest.raises(PermissionError):docling_markdown(tmp_path/'x.pdf',sha256='a'*64,artifact_directory=tmp_path)

def test_duckdb_license():
    with pytest.raises(PermissionError):duckdb_pit('a.parquet',sha256='a'*64,security_id='A',decision_at=AT,license_policy={})

def test_duckdb_actual(tmp_path):
    duckdb=pytest.importorskip('duckdb');p=tmp_path/'facts.parquet';c=duckdb.connect(':memory:')
    c.execute('CREATE TABLE f(security_id VARCHAR, field VARCHAR, period_end VARCHAR, available_at VARCHAR, revision INTEGER, value DOUBLE, evidence_id VARCHAR)')
    c.executemany('INSERT INTO f VALUES(?,?,?,?,?,?,?)',[('A','rev','2024-12-31',OLD,1,10,'old'),('A','rev','2024-12-31',AT,2,12,'new'),('A','rev','2024-12-31',FUT,3,99,'future'),('B','rev','2024-12-31',AT,1,100,'b')]);c.table('f').write_parquet(str(p));c.close()
    r=duckdb_pit(p,sha256=sha(p),security_id='A',decision_at=AT,license_policy={'permitted_for_personal_analysis':True,'allow_local_retention':True});assert len(r['rows'])==1 and r['rows'][0]['value']==12 and r['rows'][0]['evidence_id']=='new'

class Embed:
    local_only=True;model_id='model1'
    def __call__(self,text):return [1.,0.] if 'target' in text else [0.,1.]
def doc(i,**patch):return {'doc_id':i,'source_id':'sec','source_uri':'https://www.sec.gov/','security_id':'A','available_at':OLD,'scope':'public','license_id':'SEC','content':'target'}|patch
def pol(**patch):return {'license_id':'SEC','permitted_for_personal_analysis':True,'allow_local_retention':True,'allow_rag_indexing':True,'cloud_allowed':True}|patch

def test_qdrant_actual(tmp_path):
    pytest.importorskip('qdrant_client');idx=ResearchIndex(tmp_path/'r.sqlite');e=Embed();idx.add(doc('a'),pol(),embed=e);idx.add(doc('b',scope='private'),pol(cloud_allowed=False),embed=e);idx.add(doc('c',available_at=FUT),pol(),embed=e);idx.add(doc('d',security_id='B'),pol(),embed=e)
    backend=LocalQdrantSnapshot(idx,model_id=e.model_id,dimension=2)
    try:
        hits=idx.search('target',decision_at=AT,security_id='A',embed=e,vector_backend=backend);assert [r['doc_id'] for r in hits]==['a']
        assert {r['doc_id'] for r in idx.search('target',decision_at=AT,security_id='A',scope='private_local',embed=e,vector_backend=backend)}=={'a','b'}
        idx.add(doc('new'),pol(),embed=e)
        with pytest.raises(ValueError,match='STALE'):idx.search('target',decision_at=AT,security_id='A',embed=e,vector_backend=backend)
    finally:backend.close()

def test_vector_backend_cannot_leak(tmp_path):
    idx=ResearchIndex(tmp_path/'r.sqlite');e=Embed();idx.add(doc('secret',scope='private'),pol(cloud_allowed=False),embed=e)
    class Bad:
        local_only=True;index=idx
        def search(self,*args,**kwargs):return [(1.,{'doc_id':'secret','text_sha256':'x'})]
    with pytest.raises(ValueError,match='AUTHORIZED'):idx.search('target',decision_at=AT,security_id='A',embed=e,vector_backend=Bad())

def test_vector_backend_no_external(tmp_path):
    idx=ResearchIndex(tmp_path/'r.sqlite')
    with pytest.raises(PermissionError):idx.search('target',decision_at=AT,embed=Embed(),vector_backend=object())

def test_performance():
    stamps=[day(i) for i in range(3)];rows=[{'at':t,'net_return':r,'benchmark_total_return':0.,'cash_flow_adjusted':True,'net_of_costs':True,'evidence_ids':['e']} for t,r in zip(stamps,[.1,-.2,.1])]
    x=paired_performance(rows,expected_sessions=stamps);assert x['net_total_return']==pytest.approx(-.032) and x['max_drawdown']==pytest.approx(.2) and x['annualized_return'] is None
    with pytest.raises(ValueError):paired_performance(rows[:-1],expected_sessions=stamps)
    with pytest.raises(ValueError):paired_performance([rows[0]|{'cash_flow_adjusted':False},*rows[1:]],expected_sessions=stamps)

def test_challenger():
    ids=[str(i) for i in range(120)];a=[{'id':k,'at':day(i),'net_return':.001,'evidence_ids':['e'],'net_of_costs':True,'synthetic':False} for i,k in enumerate(ids)];b=[x|{'net_return':.002} for x in a]
    r=compare_challenger(a,b,locked_ids=ids,trial_count=1);assert r['status']=='INDEPENDENT_REVIEW_REQUIRED' and r['lower_bootstrap_bound']>0 and not r['promotion_allowed']
    assert compare_challenger(a,a,locked_ids=ids,trial_count=1)['status']=='REJECTED'
    assert 'INSUFFICIENT_RESAMPLES_FOR_TRIAL_COUNT' in compare_challenger(a,b,locked_ids=ids,trial_count=100)['reasons']
    with pytest.raises(ValueError):compare_challenger(a,[b[0]|{'synthetic':True},*b[1:]],locked_ids=ids,trial_count=1)

def test_skfolio_optional():
    pytest.importorskip('skfolio');samples=[{'A':-.1 if i%10==0 else .02,'CASH':0.} for i in range(100)]
    result=skfolio_cvar(samples,{'A':.5,'CASH':.5});assert result['cvar']==pytest.approx(.05) and result['can_trade'] is False


def test_ttm_fiscal_bridge():
    from atlas_pro.ttm import ttm_snapshot
    from atlas_pro.research import TAGS,FLOWS
    rows=[]
    def add(field,start,end,value):
        rows.append({'cik':1,'field':field,'tag':TAGS[field][0],'unit':'USD','start':start,'end':end,'value':value,'published_at':'2025-11-01T00:00:00Z','available_at':'2025-11-01T00:00:00Z','accession':'a'+str(len(rows))})
    for field in FLOWS:
        # FY 2023, FY 2024, comparative YTD 2023/2024 and current YTD 2025.
        for st,en,value in [('2023-01-01','2023-12-31',100),('2024-01-01','2024-12-31',120),('2023-01-01','2023-09-30',75),('2024-01-01','2024-09-30',90),('2025-01-01','2025-09-30',110)]:add(field,st,en,value)
    for field in set(TAGS)-FLOWS:add(field,None,'2025-09-30',20)
    at='2025-11-02T00:00:00Z';r=ttm_snapshot(rows,at=at)
    assert r['metrics']['revenue']==140 and r['metrics']['revenue_growth']==pytest.approx(140/115-1)
    assert r['metrics']['ocf']==140 and len(r['sources'])>len(TAGS)
    assert ttm_snapshot([x for x in rows if not (x['field']=='ocf' and x['end']=='2025-09-30')],at=at) is None
    assert ttm_snapshot([x|{'available_at':'2025-12-01T00:00:00Z'} if x['end']=='2025-09-30' else x for x in rows],at=at) is None


def test_cross_section_purging():
    from atlas_pro.experiments import purged_panel_folds
    samples=[{'id':f'{i}:{s}','security_id':s,'signal_at':day(i),'label_end_at':day(i+2),'feature_available_at':day(i)} for i in range(15) for s in ('A','B')]
    fs=purged_panel_folds(samples,min_train_dates=3,test_dates=3)
    assert fs and all(len(f['test_ids'])==6 and len(f['train_ids'])%2==0 for f in fs)
    for f in fs:assert max(int(s.split(':')[0]) for s in f['train_ids'])+2<min(int(s.split(':')[0]) for s in f['test_ids'])
    with pytest.raises(ValueError):purged_panel_folds([samples[0],samples[0]|{'id':'different'}]+samples[1:],min_train_dates=3,test_dates=3)


def test_import_job_no_broker():
    from atlas_pro.oss_cli import run_job
    with pytest.raises(ValueError):run_job({'kind':'order','payload':{}})
    with pytest.raises(ValueError):run_job({'kind':'qlib','payload':{}})


def test_research_runtime_refuses_cloud_embedding():
    from atlas_pro.runtime import ResearchModelRunner
    with pytest.raises(PermissionError):ResearchModelRunner(None,None,None,embed=lambda x:[1])
