from datetime import datetime,timezone
import json, sqlite3
from pathlib import Path
import pytest
from atlas_pro.committee import Committee, STAGES
from atlas_pro.ledger import EvidenceLedger,digest
from atlas_pro.shadow import ShadowJournal
from atlas_pro.models import ModelGateway
from atlas_pro.runtime import FixedModelTransport,ResearchModelRunner
from test_fusion import AT, LIMITS, CLUSTERS, snapshot, returns, stress, output
from atlas_pro.portfolio import portfolio_review

ROOT=Path(__file__).resolve().parents[1]
REG=json.loads((ROOT/'config/model registry.json').read_text());ROLES=json.loads((ROOT/'config/50 agent manifest.json').read_text())
TARGET={'A':.3,'B':.2,'CASH':.5}
ANCHOR='2026-11-23T21:00:00+00:00';CLOSE1='2026-11-24T21:00:00+00:00';CLOSE2='2026-11-25T21:00:00+00:00';CLOSE3='2026-11-27T18:00:00+00:00'
BINDINGS={s:{'source_id':'fixture_returns','license_id':'FIXTURE','data_class':'public'} for s in ('A','B','BENCH')}
POLICY={'license_id':'FIXTURE','permitted_for_personal_analysis':True,'cloud_allowed':True}

class Clock:
    at=AT
    def __call__(self):return self.at

def setup(tmp_path):
    c=Committee(tmp_path/'committee');rid=c.start(security_id='A',at=AT,policy_hash='p',strategy_version='s')
    risk=portfolio_review(snapshot(),TARGET,returns(),CLUSTERS,LIMITS,at=AT,stress_scenarios=stress())
    for stage in STAGES:
        r=output(stage,c.state(rid)[1]);r=risk if stage=='portfolio_risk' else r|{'risk_id':risk['risk_id']} if stage=='decision' else r
        c.append(rid,stage,r)
    clock=Clock();j=ShadowJournal(tmp_path/'shadow',clock=clock);ledger=EvidenceLedger(tmp_path/'evidence')
    return c,rid,clock,j,ledger

def start(c,rid,j,**patch):
    return j.start(c,rid,**({'targets':TARGET,'benchmark':'BENCH','source_bindings':BINDINGS,'anchor':'2026-11-23','end':'2026-11-27','cost_bps':10,'operator_confirmed':True,'synthetic':True}|patch))

def add(ledger,prev,close,vals,**patch):
    ids={}
    for name,r in vals.items():
        payload={'kind':'daily_total_return','security_id':name,'currency':'USD','corporate_actions_verified':True,'synthetic':True,'from_close':prev,'to_close':close,'total_return':r}|patch
        rid=digest(payload);ledger.add_evidence({'record_id':rid,'document_id':rid,'security_id':name,'observed_at':close,'published_at':close,'available_at':close,'payload':payload}|BINDINGS[name],policy=POLICY);ids[name]=rid
    return ids

def test_prospective_closed_loop(tmp_path):
    c,rid,clock,j,ledger=setup(tmp_path);pid=start(c,rid,j);assert j.report(pid)['planned_sessions']==3 and j.report(pid)['performance'] is None
    vals={'A':.1,'B':0,'BENCH':.01};ids=add(ledger,ANCHOR,CLOSE1,vals);clock.at=CLOSE1
    assert j.append(pid,ledger,session_close=CLOSE1,evidence_by_security=ids)['status']=='RECORDED'
    assert j.append(pid,ledger,session_close=CLOSE1,evidence_by_security=ids)['status']=='DUPLICATE'
    # Reopen persistent journal; the second day must use drifted weights, not fixed daily rebalancing.
    j=ShadowJournal(tmp_path/'shadow',clock=clock);clock.at=CLOSE2
    j.append(pid,ledger,session_close=CLOSE2,evidence_by_security=add(ledger,CLOSE1,CLOSE2,{'A':-.1,'B':0,'BENCH':.02}))
    clock.at=CLOSE3;j.append(pid,ledger,session_close=CLOSE3,evidence_by_security=add(ledger,CLOSE2,CLOSE3,{'A':0,'B':.2,'BENCH':0}))
    r=j.report(pid);assert r['status']=='COMPLETE' and r['synthetic'] and not r['promotion_allowed'] and not r['can_trade']
    assert r['performance']['net_total_return']==pytest.approx((1-.0003)*(.3*1.1*.9+.2*1.2+.5)-1)
    assert r['performance']['benchmark_total_return']==pytest.approx(1.01*1.02-1)

@pytest.mark.parametrize('patch',[{'operator_confirmed':False},{'targets':{'A':.4,'B':.2,'CASH':.4}},{'anchor':'2026-11-22'},{'end':'2026-11-26'},{'source_bindings':{}},{'cost_bps':-1}])
def test_shadow_plan_reject(tmp_path,patch):
    c,rid,clock,j,ledger=setup(tmp_path)
    with pytest.raises((ValueError,PermissionError)):start(c,rid,j,**patch)

def test_shadow_cannot_backdate(tmp_path):
    c,rid,clock,j,ledger=setup(tmp_path);clock.at=ANCHOR
    with pytest.raises(ValueError,match='before anchor'):start(c,rid,j)

def test_shadow_future_or_gap(tmp_path):
    c,rid,clock,j,ledger=setup(tmp_path);pid=start(c,rid,j);ids=add(ledger,ANCHOR,CLOSE1,{'A':0,'B':0,'BENCH':0})
    with pytest.raises(ValueError,match='future'):j.append(pid,ledger,session_close=CLOSE1,evidence_by_security=ids)
    clock.at=CLOSE2
    with pytest.raises(ValueError,match='missing session'):j.append(pid,ledger,session_close=CLOSE2,evidence_by_security=ids)

@pytest.mark.parametrize('patch',[{'currency':'CAD'},{'corporate_actions_verified':False},{'synthetic':False},{'from_close':CLOSE1},{'total_return':-2}])
def test_shadow_bad_evidence(tmp_path,patch):
    c,rid,clock,j,ledger=setup(tmp_path);pid=start(c,rid,j);clock.at=CLOSE1;ids=add(ledger,ANCHOR,CLOSE1,{'A':0,'B':0,'BENCH':0},**patch)
    with pytest.raises(ValueError):j.append(pid,ledger,session_close=CLOSE1,evidence_by_security=ids)

def test_shadow_wrong_security(tmp_path):
    c,rid,clock,j,ledger=setup(tmp_path);pid=start(c,rid,j);clock.at=CLOSE1;ids=add(ledger,ANCHOR,CLOSE1,{'A':0,'B':0,'BENCH':0});ids['A'],ids['B']=ids['B'],ids['A']
    with pytest.raises(ValueError):j.append(pid,ledger,session_close=CLOSE1,evidence_by_security=ids)

def test_shadow_detects_tampering(tmp_path):
    c,rid,clock,j,ledger=setup(tmp_path);pid=start(c,rid,j);clock.at=CLOSE1;j.append(pid,ledger,session_close=CLOSE1,evidence_by_security=add(ledger,ANCHOR,CLOSE1,{'A':0,'B':0,'BENCH':0}))
    with sqlite3.connect(j.path) as db:db.execute("UPDATE shadow_days SET payload='{}'")
    with pytest.raises(ValueError,match='integrity'):j.report(pid)

FUT='2026-12-23T18:00:00Z'
def eval_fixture(synthetic=False):
    # Unit fixtures exercise the operator-attested code path; NOT a real certification.
    cases=[{'case_id':str(i),'evaluation_rights_verified':True,'synthetic':synthetic,'allowed_evidence_ids':['e'],'expected_values':{'x':i}} for i in range(100)]
    answers={str(i):{'returned_model':'gpt-6.2-sol','evidence_ids':['e'],'values':{'x':i},'abstain':False} for i in range(100)}
    return cases,answers

def reserve(g,**patch):return g.select_and_reserve(**({'request_id':'r','role_id':'A011','task_set':'finance','data_scope':'public_only','at':AT,'input_tokens':1000,'output_tokens':100,'require_measured':True}|patch))

def test_measured_certification_and_legacy_block(tmp_path):
    g=ModelGateway(tmp_path/'model',REG,ROLES);g.certify('A011','gpt-6.2-sol','finance',1,.9,at=AT,valid_until=FUT,provenance={'external_eval_report':'self-reported','locked_testset_hash':'self-reported'})
    assert reserve(g)['status']=='NO_CURRENT_CERTIFIED_MODEL'
    cases,answers=eval_fixture();r=g.certify_measured('A011','gpt-6.2-sol','finance',cases,answers,locked_hash=digest(cases),at=AT,valid_until=FUT,operator_verified=True)
    assert r['passed'] and reserve(g)['status']=='RESERVED'
    changed={**REG,'gpt-6.2-sol':REG['gpt-6.2-sol']|{'model_id':'different'}}
    assert reserve(ModelGateway(tmp_path/'model',changed,ROLES),request_id='new')['status']=='NO_CURRENT_CERTIFIED_MODEL'

@pytest.mark.parametrize('mode',['synthetic','missing','wrong_citation','incorrect','no_operator','wrong_model'])
def test_measured_cert_rejects(tmp_path,mode):
    g=ModelGateway(tmp_path/'model',REG,ROLES);cases,answers=eval_fixture(mode=='synthetic')
    if mode=='missing':del answers['1']
    if mode=='wrong_citation':answers['1']['evidence_ids']=['made-up']
    if mode=='incorrect':
        for i in ('1','2','3'):answers[i]['values']={'x':-1}
    if mode=='wrong_model':answers['1']['returned_model']='unknown'
    args=dict(locked_hash=digest(cases),at=AT,valid_until=FUT,operator_verified=mode!='no_operator')
    if mode in ('no_operator','wrong_model'):
        with pytest.raises((ValueError,PermissionError)):g.certify_measured('A011','gpt-6.2-sol','finance',cases,answers,**args)
    else:assert not g.certify_measured('A011','gpt-6.2-sol','finance',cases,answers,**args)['passed']
    assert reserve(g)['status']=='NO_CURRENT_CERTIFIED_MODEL'

def test_real_transport_uses_real_billing_clock(monkeypatch):
    class G:
        roles={'role':{'role':'research','data_scope':'public_only'}};registry={}
        def select_and_reserve(self,**kwargs):
            assert kwargs['at']!='2020-01-01T00:00:00Z' and kwargs['require_measured'] is True
            return {'status':'BLOCKED','can_trade':False}
    class Index:
        def search(self,*a,**k):return [{'doc_id':'a'}]
    r=ResearchModelRunner(G(),Index(),FixedModelTransport())
    assert r.run(role_id='role',task_set='finance',request_id='r',security_id='A',query='income',at='2020-01-01T00:00:00Z')['status']=='BLOCKED'

TII_POLICY={'license_id':'TIINGO_EOD_PERSONAL','permitted_for_personal_analysis':True,'allow_local_retention':True,'cloud_allowed':False,'adjustment_coverage_reviewed':True}
def tiingo_bars():return [{'date':'2026-11-23T00:00:00Z','close':100,'adjClose':50,'divCash':0,'splitFactor':1},{'date':'2026-11-24T00:00:00Z','close':55,'adjClose':55,'divCash':0,'splitFactor':2}]

def test_tiingo_shadow_tick(tmp_path):
    from atlas_pro.return_feed import TiingoEOD
    c,rid,clock,j,ledger=setup(tmp_path)
    binds={s:{'source_id':'tiingo_eod','license_id':'TIINGO_EOD_PERSONAL','data_class':'licensed','ticker':s} for s in BINDINGS}
    pid=start(c,rid,j,source_bindings=binds,synthetic=False);clock.at='2026-11-25T01:16:00Z'
    def transport(ticker,start,end):
        assert ticker in binds and start=='2026-11-23' and end=='2026-11-24';return tiingo_bars()
    feed=TiingoEOD(TII_POLICY,transport=transport,clock=clock)
    assert feed.tick(j,ledger,pid)['status']=='RECORDED'
    r=j.report(pid);assert not r['synthetic'] and r['performance']['net_total_return']==pytest.approx((1-.0003)*1.05-1)
    assert r['performance']['benchmark_total_return']==pytest.approx(.1) and not r['promotion_allowed']
    assert not ledger.asof('A',clock.at) # licensed data not public

@pytest.mark.parametrize('patch',[{'allow_local_retention':False},{'cloud_allowed':True},{'adjustment_coverage_reviewed':False}])
def test_tiingo_permission(patch):
    from atlas_pro.return_feed import TiingoEOD
    with pytest.raises(PermissionError):TiingoEOD(TII_POLICY|patch,transport=lambda *a:[])

def test_tiingo_pre_correction(tmp_path):
    from atlas_pro.return_feed import TiingoEOD
    _,_,clock,_,ledger=setup(tmp_path);clock.at=CLOSE1
    feed=TiingoEOD(TII_POLICY,transport=lambda *a:pytest.fail('early network request'),clock=clock)
    with pytest.raises(ValueError,match='correction window'):feed.evidence(ledger,security_id='A',ticker='A',from_close=ANCHOR,to_close=CLOSE1)

@pytest.mark.parametrize('patch',[{'date':'2026-11-25T00:00:00Z'},{'adjClose':0},{'splitFactor':0},{'divCash':-1}])
def test_tiingo_invalid_data(tmp_path,patch):
    from atlas_pro.return_feed import TiingoEOD
    _,_,clock,_,ledger=setup(tmp_path);clock.at='2026-11-25T01:16:00Z'
    bars=tiingo_bars();bars[1]|=patch
    feed=TiingoEOD(TII_POLICY,transport=lambda *a:bars,clock=clock)
    with pytest.raises(ValueError):feed.evidence(ledger,security_id='A',ticker='A',from_close=ANCHOR,to_close=CLOSE1)

def test_cheapest_certified_challenger_not_limited_to_static_pair(tmp_path):
    g=ModelGateway(tmp_path/'model',REG,ROLES);cases,answers=eval_fixture()
    assert g.certify_measured('A011','gpt-6.2-sol','finance',cases,answers,locked_hash=digest(cases),at=AT,valid_until=FUT,operator_verified=True)['passed']
    challenger='deepseek-flash';answers={k:v|{'returned_model':REG[challenger]['model_id']} for k,v in answers.items()}
    assert g.certify_measured('A011',challenger,'finance',cases,answers,locked_hash=digest(cases),at=AT,valid_until=FUT,operator_verified=True)['passed']
    assert reserve(g,provider_available={'gpt-6.2-sol':True,challenger:True})['model']==challenger


def test_frozen_forecast_scored_only_on_completion(tmp_path):
    c,rid,clock,j,ledger=setup(tmp_path);f={'probability':.7,'baseline_probability':.5,'excess_return_threshold':.02};pid=start(c,rid,j,end='2026-11-24',forecast=f)
    assert j.report(pid)['forecast_assessment'] is None
    clock.at=CLOSE1;j.append(pid,ledger,session_close=CLOSE1,evidence_by_security=add(ledger,ANCHOR,CLOSE1,{'A':.1,'B':.1,'BENCH':0}))
    score=j.report(pid)['forecast_assessment'];assert score['hit']==1 and score['brier']==pytest.approx(.09) and score['baseline_brier']==pytest.approx(.25) and score['synthetic'] and not score['calibration_certified']


def test_forecast_invalid(tmp_path):
    c,rid,clock,j,ledger=setup(tmp_path)
    with pytest.raises(ValueError):start(c,rid,j,forecast={'probability':1.2,'baseline_probability':.5,'excess_return_threshold':.02})


def test_shadow_refresh_same_policy(tmp_path):
    c,rid,clock,j,ledger=setup(tmp_path);policy={'status':'ACTIVE_APPROVED','owner_approval':{'approved':True},'limits':LIMITS}
    rid=c.start(security_id='A',at=AT,policy_hash=digest(policy),strategy_version='s')
    risk=portfolio_review(snapshot(),TARGET,returns(),CLUSTERS,LIMITS,at=AT,stress_scenarios=stress())
    for stage in STAGES:
        r=output(stage,c.state(rid)[1]);r=risk if stage=='portfolio_risk' else r|{'risk_id':risk['risk_id']} if stage=='decision' else r;c.append(rid,stage,r)
    clock.at='2026-11-23T19:00:00Z'
    with pytest.raises(ValueError,match='stale'):start(c,rid,j)
    fresh=snapshot()|{'as_of':clock.at,'positions':[snapshot()['positions'][0]|{'price_asof':clock.at}]}
    refresh={'policy':policy,'snapshot':fresh,'returns':returns(),'clusters':CLUSTERS,'stress_scenarios':stress()}
    pid=start(c,rid,j,risk_refresh=refresh);assert j.report(pid)['risk_id']!=risk['risk_id']
    with pytest.raises(ValueError,match='same approved policy'):start(c,rid,j,risk_refresh=refresh|{'policy':policy|{'limits':LIMITS|{'max_single_stock_weight':1}}})


def test_real_route_rejects_wrong_model_identity():
    class FakeRealTransport(FixedModelTransport):
        def __init__(self):pass
        def __call__(self,*args):return {'model':'unknown-provider-snapshot','status':'completed'}
    class G:
        roles={'role':{'role':'research','data_scope':'public_only','minimum_effort':'low'}}
        registry={'candidate':{'provider':'openai','model_id':'expected'}}
        def select_and_reserve(self,**kwargs):return {'status':'RESERVED','model':'candidate'}
    class Index:
        def search(self,*a,**k):return [{'doc_id':'a'}]
    r=ResearchModelRunner(G(),Index(),FakeRealTransport())
    assert r.run(role_id='role',task_set='finance',request_id='r',security_id='A',query='income',at='2020-01-01T00:00:00Z')['status']=='MODEL_OUTPUT_REJECTED'


def test_legacy_cert_overwrite_revokes_measured_route(tmp_path):
    g=ModelGateway(tmp_path/'model',REG,ROLES);cases,answers=eval_fixture()
    assert g.certify_measured('A011','gpt-6.2-sol','finance',cases,answers,locked_hash=digest(cases),at=AT,valid_until=FUT,operator_verified=True)['passed']
    g.certify('A011','gpt-6.2-sol','finance',1,.9,at=AT,valid_until=FUT,provenance={'external_eval_report':'legacy','locked_testset_hash':'legacy'})
    assert reserve(g)['status']=='NO_CURRENT_CERTIFIED_MODEL'


def test_shadow_cli_reports_read_only(tmp_path,capsys):
    from atlas_pro.shadow_cli import main
    c,rid,clock,j,ledger=setup(tmp_path);pid=start(c,rid,j)
    assert main(['--journal',j.path,'report',pid])==0
    assert json.loads(capsys.readouterr().out)['plan_id']==pid


def test_certify_cli_requires_operator(tmp_path):
    from atlas_pro.certify_cli import main
    args=['--registry','unused','--roles','unused','--journal',str(tmp_path/'j'),'--cases','unused','--cases-sha256','unused','--answers','unused','--answers-sha256','unused','--locked-hash','unused','--role','role','--model','model','--task-set','finance','--valid-until',FUT]
    with pytest.raises(PermissionError):main(args)
    assert not (tmp_path/'j').exists()


def test_shadow_comparison_rejects_short_and_synthetic(tmp_path):
    c,rid,clock,j,ledger=setup(tmp_path)
    second=c.start(security_id='A',at=AT,policy_hash='p',strategy_version='challenger')
    for stage in STAGES:
        r=output(stage,c.state(second)[1]);r=c.state(rid)[1]['portfolio_risk'] if stage=='portfolio_risk' else r|{'risk_id':c.state(rid)[1]['portfolio_risk']['risk_id']} if stage=='decision' else r;c.append(second,stage,r)
    a=start(c,rid,j,end='2026-11-24',synthetic=False);b=start(c,second,j,end='2026-11-24',synthetic=False);s=start(c,second,j,end='2026-11-24',synthetic=True)
    with pytest.raises(ValueError,match='synthetic'):j.compare(a,s,trial_count=1,max_drawdown=.25)
    with pytest.raises(ValueError,match='incomplete'):j.compare(a,b,trial_count=1,max_drawdown=.25)
    clock.at=CLOSE1;ids=add(ledger,ANCHOR,CLOSE1,{'A':.01,'B':.02,'BENCH':.01},synthetic=False)
    for plan in (a,b):j.append(plan,ledger,session_close=CLOSE1,evidence_by_security=ids)
    r=j.compare(a,b,trial_count=1,max_drawdown=.25)
    assert 'INSUFFICIENT_DEPENDENT_OBSERVATIONS' in r['reasons'] and not r['promotion_allowed'] and r['requires_independent_data_qualification']

def test_shadow_shared_window_reuses_evidence(tmp_path):
    from atlas_pro.return_feed import TiingoEOD
    c,rid,clock,j,ledger=setup(tmp_path)
    binds={s:{'source_id':'tiingo_eod','license_id':'TIINGO_EOD_PERSONAL','data_class':'licensed','ticker':s} for s in BINDINGS}
    a=start(c,rid,j,source_bindings=binds,synthetic=False)
    b=start(c,rid,j,source_bindings=binds,synthetic=False,cost_bps=20)
    calls=[]
    def fetch(*args):calls.append(args);return tiingo_bars()
    feed=TiingoEOD(TII_POLICY,transport=fetch,clock=clock)
    assert feed.tick_batch(j,ledger,[a,b])['plans'][a]['status']=='NOT_DUE'
    assert not calls
    clock.at='2026-11-25T01:16:00Z'
    x=feed.tick_batch(j,ledger,[a,b],max_fetches=2)
    assert x['plans'][a]['status']=='FETCH_BUDGET_EXHAUSTED' and not calls
    x=feed.tick_batch(j,ledger,[a,b],max_fetches=3)
    assert x['fetches_reserved']==3 and len(calls)==3
    assert all(v['status']=='RECORDED' for v in x['plans'].values())
    with j._db() as db:
        _,ad,_=j._load(db,a);_,bd,_=j._load(db,b)
        assert ad[0]['evidence_by_security']==bd[0]['evidence_by_security']
