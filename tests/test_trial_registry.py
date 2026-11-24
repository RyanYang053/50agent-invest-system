import sqlite3
import pytest
from atlas_pro.trial_registry import TrialRegistry
from atlas_pro.experiments import experiment_request
from atlas_pro.ledger import digest
AT='2026-11-23T20:00:00Z';IDS=['sample1','sample2']

def request(ids=IDS,artifact='a'):
    return experiment_request(engine='lean',artifact_sha256=artifact*64,data_sha256='b'*64,split_sha256=digest(ids),policy_sha256='c'*64,budget_usd=0,at=AT)

def report(r):
    return r|{'execution_mode':'OFFLINE_ISOLATED_RESEARCH','cost_usd':0,'synthetic':True,'observations':[{'id':k,'at':f'2020-01-0{i+1}T20:00:00Z','net_return':.01,'benchmark_return':0,'evidence_ids':['fixture']} for i,k in enumerate(IDS)]}

@pytest.fixture
def setup(tmp_path):
    reg=TrialRegistry(tmp_path/'trials',clock=lambda:AT);rs=[request(),request(artifact='d')];c=reg.register(rs,IDS,operator_confirmed=True);return reg,c,rs

def test_complete_and_failed_counted_no_promotion(setup):
    reg,c,rs=setup
    for r in rs:reg.start(c,r['experiment_id'])
    x=reg.finish(c,rs[0]['experiment_id'],report=report(rs[0]));assert x['status']=='REJECTED' and not x['promotion_allowed']
    reg.finish(c,rs[1]['experiment_id'],failure='TIMEOUT');a=reg.audit(c);assert a['all_attempts_accounted'] and a['counts']=={'PLANNED':0,'RUNNING':0,'FAILED':1,'COMPLETED':1} and not a['promotion_allowed']

@pytest.mark.parametrize('ids',[['sample2','sample1'],['sample2','new']])
def test_overlap_holdout_rejected(setup,ids):
    reg,c,rs=setup
    with pytest.raises(ValueError,match='holdout'):reg.register([request(ids,artifact='e')],ids,operator_confirmed=True)

def test_interrupted_trial_cannot_retry_after_restart(setup):
    reg,c,rs=setup;tid=rs[0]['experiment_id'];reg.start(c,tid);restored=TrialRegistry(reg.path,clock=lambda:AT)
    assert restored.audit(c)['counts']['RUNNING']==1
    with pytest.raises(ValueError,match='already attempted'):restored.start(c,tid)
    restored.finish(c,tid,failure='CRASH');assert restored.audit(c)['counts']['FAILED']==1

def test_unregistered_and_not_started_rejected(setup):
    reg,c,rs=setup
    with pytest.raises(KeyError):reg.start(c,'not-registered')
    with pytest.raises(ValueError):reg.finish(c,rs[0]['experiment_id'],failure='CRASH')

def test_mismatched_result_cannot_complete(setup):
    reg,c,rs=setup;tid=rs[0]['experiment_id'];reg.start(c,tid)
    with pytest.raises(ValueError):reg.finish(c,tid,report=report(rs[1]))
    assert reg.audit(c)['counts']['RUNNING']==1
    reg.finish(c,tid,failure='INVALID_REPORT')

def test_tampered_result_rejected(setup):
    reg,c,rs=setup;tid=rs[0]['experiment_id'];reg.start(c,tid);reg.finish(c,tid,failure='TIMEOUT')
    with sqlite3.connect(reg.path) as db:db.execute("UPDATE trials SET result='{}' WHERE id=?",(tid,))
    with pytest.raises(ValueError):reg.audit(c)

def test_requires_explicit_approval(tmp_path):
    reg=TrialRegistry(tmp_path/'db',clock=lambda:AT)
    with pytest.raises(PermissionError):reg.register([request()],IDS)
