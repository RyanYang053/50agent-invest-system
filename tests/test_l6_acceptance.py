"""Synthetic cryptographic fixtures exercise rejection and routing, never certify L6."""
from pathlib import Path
import json,copy,hashlib
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from atlas_pro.skill_contracts import catalog,contract,task_id,validate_catalog,runtime_hash
from atlas_pro.role_jobs import PUBLIC_TASKS,LOCAL_TASKS,RoleExecutor
from atlas_pro.independent_review import strict_json,role_grade,verify_review
from atlas_pro.models import ModelGateway
from atlas_pro.ledger import digest
from atlas_pro.l6_acceptance import evaluate,GATES
ROOT=Path(__file__).resolve().parents[1];ROLES=json.loads((ROOT/'config/50 agent manifest.json').read_text());BYID={r['agent_id']:r for r in ROLES};REG=json.loads((ROOT/'config/model registry.json').read_text())
AT='2026-11-23T20:00:00Z';RID='A011';MID='gpt-6.2-sol';H='a'*64

@pytest.fixture
def signer():
    keys=[Ed25519PrivateKey.generate(),Ed25519PrivateKey.generate()]
    trust={str(i):{'public_key':k.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw).hex(),'role':r,'identity':'reviewer-'+str(i),'organization':'external-'+str(i),'revoked':False} for i,(k,r) in enumerate(zip(keys,['domain_reviewer','independent_validator']))}
    def sign(p):return {'payload':p,'signatures':[{'reviewer_id':str(i),'signature':k.sign(strict_json(p)).hex()} for i,k in enumerate(keys)]}
    return trust,sign

def payload():
    return {'kind':'ROLE_COMPETENCE_V1','role_id':RID,'model_id':MID,'task_set':task_id(RID),'skill_hash':digest(contract(RID)),'runtime_hash':runtime_hash(RID),'role_hash':digest(BYID[RID]),'model_hash':digest(REG[MID]),'synthetic':False,'data_rights_verified':True,'holdout_independence_verified':True,'producer_organization':'developer','locked_at':'2026-11-01T00:00:00Z','evaluated_at':'2026-11-20T00:00:00Z','reviewed_at':'2026-11-22T00:00:00Z','valid_until':'2026-12-22T00:00:00Z',**{x:hashlib.sha256(x.encode()).hexdigest() for x in ('testset_hash','answers_hash','rubric_hash','raw_review_hash')},'cases':[{'id':str(i),'negative':i<20,'critical_failure':False,'evidence_hash':H,'checks':dict.fromkeys(['task_correctness','source_entailment','numeric_consistency','uncertainty','boundary_compliance'],True)} for i in range(100)]}

def grade(e,t):return role_grade(e,t,role_id=RID,model_id=MID,role=BYID[RID],model=REG[MID],at=AT)

def test_catalog_exact_and_distinct():
    c=validate_catalog(ROLES,PUBLIC_TASKS,LOCAL_TASKS);assert len(c)==50 and len({task_id(r) for r in c})==50
    assert all(x['status']=='DEFINED_NOT_CERTIFIED' for x in c.values())
    assert sum(x['kind']=='public_memo' for x in c.values())==29
    assert 'skill' in RoleExecutor(ROLES,None).catalog()[0]

@pytest.mark.parametrize('rid',sorted(BYID))
def test_role_contract_permissions(rid):
    s=contract(rid);r=BYID[rid];assert s['tool_groups']==r['allowed_tool_groups'] and s['scope']==r['data_scope']
    assert all(s[k] is False for k in ('can_trade','can_promote','can_change_policy'))
    assert s['challenge_case'] and s['critical_failure'] and s['deliverable']

def test_manifest_drift():
    r=copy.deepcopy(ROLES);r[0]['allowed_tool_groups'].append('broker')
    with pytest.raises(ValueError):validate_catalog(r,PUBLIC_TASKS,LOCAL_TASKS)

@pytest.mark.parametrize('patch',[{'synthetic':True},{'skill_hash':'a'*64},{'task_set':'legacy'},{'model_hash':'a'*64},{'holdout_independence_verified':False},{'locked_at':'2026-11-21T00:00:00Z'},{'valid_until':'2026-11-22T01:00:00Z'}])
def test_wrong_evidence_rejected(signer,patch):
    t,s=signer
    with pytest.raises((PermissionError,ValueError)):grade(s(payload()|patch),t)

@pytest.mark.parametrize('mode',['one_signature','tampered','revoked','duplicate_key','same_organization','same_identity','producer'])
def test_signature_rejection(signer,mode):
    t,s=signer;e=s(payload())
    if mode=='one_signature':e['signatures'].pop()
    elif mode=='tampered':e['payload']['testset_hash']='b'*64
    elif mode=='revoked':t['0']['revoked']=True
    elif mode=='duplicate_key':t['1']['public_key']=t['0']['public_key']
    elif mode=='same_organization':t['1']['organization']=t['0']['organization']
    elif mode=='same_identity':t['1']['identity']=t['0']['identity']
    else:t['0']['organization']='developer'
    with pytest.raises((PermissionError,ValueError)):grade(e,t)

@pytest.mark.parametrize('mode',['negative_failure','critical','insufficient_negative','too_many_errors'])
def test_role_grade_fails(signer,mode):
    t,s=signer;p=payload()
    if mode=='negative_failure':p['cases'][0]['checks']['task_correctness']=False
    elif mode=='critical':p['cases'][40]['critical_failure']=True
    elif mode=='insufficient_negative':p['cases'][0]['negative']=False
    else:
        for x in p['cases'][40:45]:x['checks']['task_correctness']=False
    assert grade(s(p),t)['passed'] is False

def test_numeric_not_role_and_revocation(tmp_path,signer):
    t,s=signer;g=ModelGateway(tmp_path/'model.db',REG,ROLES,review_trust=t)
    with pytest.raises(PermissionError):g.certify(RID,MID,task_id(RID),1,.9,at=AT,valid_until='2026-12-01T00:00:00Z',provenance={})
    with pytest.raises(PermissionError):g.certify_measured(RID,MID,task_id(RID),[],{},locked_hash=H,at=AT,valid_until='2026-12-01T00:00:00Z',operator_verified=True)
    kw=dict(role_id=RID,task_set=task_id(RID),data_scope='public_only',at=AT,input_tokens=1000,output_tokens=100,require_measured=True)
    assert g.select_and_reserve(request_id='before',**kw)['status']=='NO_CURRENT_CERTIFIED_MODEL'
    with pytest.raises(ValueError):g.certify_role_review(RID,MID,s(payload()),at=AT)
    p=payload();write_benchmark_artifacts(p,tmp_path)
    assert g.certify_role_review(RID,MID,s(p),at=AT,artifact_dir=tmp_path)['passed']
    assert g.select_and_reserve(request_id='after',**kw)['status']=='RESERVED'
    t['1']['revoked']=True
    assert g.select_and_reserve(request_id='revoked',**kw)['status']=='NO_CURRENT_CERTIFIED_MODEL'
    assert ModelGateway(tmp_path/'model.db',REG,ROLES).select_and_reserve(request_id='no-trust',**kw)['status']=='NO_CURRENT_CERTIFIED_MODEL'

def test_l6_defaults_no_pass():
    r=evaluate({}, {},at=AT,release_hash=H,mandate_hash=H,role_contract_hash=digest(catalog()))
    assert r['reviewed_thresholds_met']==0 and r['gate_count']==10 and r['l6_certified'] is False and r['can_trade'] is False

def test_l6_signed_artifact_gate(tmp_path,signer):
    t,s=signer;hashes=[]
    for b in (b'fixture1',b'fixture2'):
        h=hashlib.sha256(b).hexdigest();(tmp_path/h).write_bytes(b);hashes.append(h)
    gate='G1_data';p={'kind':'L6_GATE_V1','gate':gate,'release_hash':H,'mandate_hash':H,'role_contract_hash':digest(catalog()),'producer_organization':'developer','synthetic':False,'data_rights_verified':True,'reviewed_at':'2026-11-22T00:00:00Z','valid_until':'2026-12-22T00:00:00Z','artifact_hashes':hashes,'period_start':'2010-01-01T00:00:00Z','period_end':'2025-01-01T00:00:00Z','metrics':{'pit_years':10,'historical_universe_coverage':.99,'corporate_action_reconciliation':.999,'critical_data_errors':0}}
    kw=dict(at=AT,release_hash=H,mandate_hash=H,role_contract_hash=digest(catalog()),artifact_dir=tmp_path)
    r=evaluate({gate:s(p)},t,**kw);assert r['reviewed_thresholds_met']==1 and not r['l6_certified']
    (tmp_path/hashes[0]).write_bytes(b'altered');assert evaluate({gate:s(p)},t,**kw)['reviewed_thresholds_met']==0

from atlas_pro.quant_validation import deflated_sharpe,cscv_pbo
import random

def test_deflated_sharpe_penalizes_trial_count():
    rng=random.Random(7);x=[rng.gauss(.001,.01) for _ in range(500)];trials=[rng.gauss(0,.1) for _ in range(50)]
    a=deflated_sharpe(x,trial_sharpes=trials,effective_trials=2,independent_observations=250);b=deflated_sharpe(x,trial_sharpes=trials,effective_trials=50,independent_observations=250)
    assert 0<=b['deflated_sharpe_probability']<=a['deflated_sharpe_probability']<=1 and not b['promotion_allowed']

def test_cscv_conditional_and_shape():
    rng=random.Random(9);m=[[rng.gauss(.001*(j+1),.02) for j in range(4)] for _ in range(160)]
    r=cscv_pbo(m,blocks=8);assert r['splits']==70 and 0<=r['pbo']<=1 and not r['promotion_allowed']
    with pytest.raises(ValueError):cscv_pbo(m[:-1],blocks=8)
    with pytest.raises(ValueError):deflated_sharpe([.01]*100,trial_sharpes=[0,.1],effective_trials=2,independent_observations=100)


def write_benchmark_artifacts(p,root):
    def store(obj):
        raw=strict_json(obj);h=hashlib.sha256(raw).hexdigest();(root/h).write_bytes(raw);return h
    h=store({'synthetic_fixture_source':True})
    for row in p['cases']:row['evidence_hash']=h
    p['testset_hash']=store({'cases':[{'id':r['id'],'input':{'synthetic_question':r['id']},'negative':r['negative'],'evidence_hash':h} for r in p['cases']]})
    p['answers_hash']=store({'answers':[{'id':r['id'],'output':{'synthetic_response':r['id']}} for r in p['cases']]})
    p['rubric_hash']=store({'version':'fixture-1','dimensions':sorted(p['cases'][0]['checks'])})
    p['raw_review_hash']=store({'cases':p['cases']})
    return store

@pytest.mark.parametrize('attack',['reused_artifact','duplicate_inputs','wrong_answer_id','missing_answer','grade_mismatch','mismatched_evidence','wrong_rubric'])
def test_certification_artifact_joins(tmp_path,signer,attack):
    t,s=signer;p=payload();store=write_benchmark_artifacts(p,tmp_path)
    if attack=='reused_artifact':p['answers_hash']=p['testset_hash']
    elif attack in ('duplicate_inputs','mismatched_evidence'):
        doc=json.loads((tmp_path/p['testset_hash']).read_text())
        if attack=='duplicate_inputs':doc['cases'][1]['input']=doc['cases'][0]['input']
        else:doc['cases'][1]['evidence_hash']=H
        p['testset_hash']=store(doc)
    elif attack in ('wrong_answer_id','missing_answer'):
        doc=json.loads((tmp_path/p['answers_hash']).read_text())
        if attack=='wrong_answer_id':doc['answers'][0]['id']='other'
        else:doc['answers'].pop()
        p['answers_hash']=store(doc)
    elif attack=='grade_mismatch':p['cases'][0]['checks']['uncertainty']=False
    else:p['rubric_hash']=store({'version':'invalid','dimensions':[]})
    with pytest.raises(ValueError):role_grade(s(p),t,role_id=RID,model_id=MID,role=BYID[RID],model=REG[MID],at=AT,artifact_dir=tmp_path,check_artifacts=True)

@pytest.mark.parametrize('gate', ['G1_data','G4_research','G6_operational','G9_forward_performance','G10_live_evidence'])
def test_impossible_period_blocked(gate):
    from atlas_pro.l6_acceptance import validate_period
    p={'period_start':'2026-11-23T14:00:00Z','period_end':'2026-11-24T21:00:00Z','metrics':{k:lo for k,(lo,hi) in GATES[gate].items()}}
    with pytest.raises(ValueError):validate_period(gate,p)
