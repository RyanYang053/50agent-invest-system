import copy
from pathlib import Path
import pytest
from atlas_pro.paper import AlpacaPaperTransport,PaperGateway,PaperBlocked,normalize_order,validate_policy,PaperHTTPError,PAPER_HOST
from atlas_pro.paper_replay import PaperReplay,demo

AT='2026-11-23T15:00:00Z'; CLOSE='2026-11-23T21:00:00Z'; ACCOUNT='11111111-1111-4111-8111-111111111111'; BROKER='22222222-2222-4222-8222-222222222222'
POL={'mode':'ALPACA_PAPER_ONLY','live_execution':False,'owner_confirmed_paper_only':True,'account_id':ACCOUNT,'allowed_symbols':['TEST'],'max_order_usd':1000,'max_position_weight':.1,'min_cash_weight':.2,'max_gross_weight':.8}
ORDER={'client_order_id':'atlas-paper-test1','symbol':'TEST','side':'buy','qty':5,'limit_price':'100.00'}
class Fake:
    def __init__(self):
        self.a={'id':ACCOUNT,'currency':'USD','status':'ACTIVE','trading_blocked':False,'account_blocked':False,'trade_suspended_by_user':False,'equity':'10000','cash':'10000'}
        self.clock={'is_open':True,'timestamp':AT,'next_close':CLOSE};self.asset={'symbol':'TEST','class':'us_equity','status':'active','tradable':True}
        self.pos=[];self.open=[];self.calls=[];self.remote=None;self.fail_post=False;self.bad_response=False
    def __call__(self,m,p,*,query=None,body=None):
        self.calls.append((m,p))
        if p=='/v2/account':return self.a
        if p=='/v2/clock':return self.clock
        if p=='/v2/assets/TEST':return self.asset
        if p=='/v2/positions':return self.pos
        if m=='GET' and p=='/v2/orders':return self.open
        if m=='POST':
            self.remote=body|{'id':BROKER,'status':'new','filled_qty':'0'}
            if self.fail_post:raise TimeoutError()
            return self.remote|({'symbol':'WRONG'} if self.bad_response else {})
        if p=='/v2/orders:by_client_order_id':
            if self.remote is None:raise PaperHTTPError(404)
            return self.remote
        if m=='DELETE':return None
        raise AssertionError((m,p))
@pytest.fixture
def f():return Fake()
@pytest.fixture
def g(tmp_path,f):return PaperGateway(tmp_path/'paper.sqlite',POL,f,clock=lambda:AT)

def test_paper_default_off(g,f):
    assert g.inspect()['armed'] is False
    with pytest.raises(PaperBlocked,match='KILL_SWITCH'):g.submit(ORDER,operator_confirmed=True)
    assert ('POST','/v2/orders') not in f.calls

def test_operator_confirm(g):
    with pytest.raises(PaperBlocked):g.arm()
    g.arm(confirmed=True)
    with pytest.raises(PaperBlocked):g.submit(ORDER)

def test_paper_account_mismatch(g,f):
    f.a['id']=BROKER
    with pytest.raises(PaperBlocked,match='MISMATCH'):g.arm(confirmed=True)

@pytest.mark.parametrize('patch',[{'live_execution':True},{'owner_confirmed_paper_only':False},{'account_id':'not-valid'},{'max_order_usd':10001},{'max_position_weight':.5},{'min_cash_weight':.01},{'max_gross_weight':1},{'allowed_symbols':[]},{'allowed_symbols':['TEST','TEST']},{'mode':'LIVE'}])
def test_policies(patch):
    with pytest.raises((PaperBlocked,ValueError)):validate_policy(POL|patch)

@pytest.mark.parametrize('patch',[{'qty':1.5},{'qty':True},{'qty':0},{'limit_price':'nan'},{'limit_price':'1.001'},{'limit_price':'0.99'},{'side':'short'},{'client_order_id':'foreign'},{'symbol':'../TEST'},{'type':'market'}])
def test_orders(patch):
    with pytest.raises(ValueError):normalize_order(ORDER|patch)

def test_submit_idempotency(g,f):
    g.arm(confirmed=True);assert g.submit(ORDER,operator_confirmed=True)['status']=='new'
    assert g.submit(ORDER,operator_confirmed=True)['duplicate']
    assert f.calls.count(('POST','/v2/orders'))==1
    with pytest.raises(PaperBlocked,match='COLLISION'):g.submit(ORDER|{'qty':4},operator_confirmed=True)
    with pytest.raises(PaperBlocked,match='UNRESOLVED'):g.submit(ORDER|{'client_order_id':'atlas-paper-test2'},operator_confirmed=True)

def test_unknown_ack_no_retry(g,f):
    g.arm(confirmed=True);f.fail_post=True
    assert g.submit(ORDER,operator_confirmed=True)['status']=='unknown'
    assert g.submit(ORDER,operator_confirmed=True)['duplicate']
    assert f.calls.count(('POST','/v2/orders'))==1
    assert g.reconcile(ORDER['client_order_id'])['status']=='new'
    f.remote=None
    assert g.reconcile(ORDER['client_order_id'])['status']=='reconcile_failed'

def test_reconcile_partial_and_full(g,f):
    g.arm(confirmed=True);g.submit(ORDER,operator_confirmed=True)
    f.remote.update(status='partially_filled',filled_qty='2',filled_avg_price='99.99')
    assert g.reconcile(ORDER['client_order_id'])['filled_qty']=='2'
    f.remote.update(status='filled',filled_qty='5')
    assert g.reconcile(ORDER['client_order_id'])['status']=='filled'
    f.remote.update(status='new',filled_qty='0')
    assert g.reconcile(ORDER['client_order_id'])['status']=='reconcile_failed'

def test_cancel_not_final(g,f):
    g.arm(confirmed=True);g.submit(ORDER,operator_confirmed=True)
    with pytest.raises(PaperBlocked):g.cancel(ORDER['client_order_id'])
    assert g.cancel(ORDER['client_order_id'],operator_confirmed=True)['status']=='cancel_requested'
    with pytest.raises(PaperBlocked):g.submit(ORDER|{'client_order_id':'atlas-paper-other'},operator_confirmed=True)
    f.remote.update(status='canceled');assert g.reconcile(ORDER['client_order_id'])['status']=='canceled'

def test_stop_persists(tmp_path,f):
    path=tmp_path/'j';x=PaperGateway(path,POL,f,clock=lambda:AT);x.arm(confirmed=True);x.stop()
    y=PaperGateway(path,POL,f,clock=lambda:AT)
    assert not y.inspect()['armed']
    with pytest.raises(PaperBlocked):y.submit(ORDER,operator_confirmed=True)
    with pytest.raises(PaperBlocked):PaperGateway(path,POL|{'max_order_usd':999},f)

@pytest.mark.parametrize('bad',['closed','clock','asset','open','reconcile','short','notional','position','currency','account_blocked','missing_flag','symbol'])
def test_preflight_block(g,f,bad):
    g.arm(confirmed=True);req=ORDER.copy()
    if bad=='closed':f.clock['is_open']=False
    elif bad=='clock':f.clock['timestamp']='2026-11-23T14:00:00Z'
    elif bad=='asset':f.asset['tradable']=False
    elif bad=='open':f.open=[{}]
    elif bad=='reconcile':f.a['cash']='9900'
    elif bad=='short':req['side']='sell'
    elif bad=='notional':req['qty']=11
    elif bad=='position':f.a['cash']='9300';f.pos=[{'symbol':'TEST','asset_class':'us_equity','side':'long','qty':'7','market_value':'700'}]
    elif bad=='currency':f.a['currency']='CAD'
    elif bad=='account_blocked':f.a['account_blocked']=True
    elif bad=='missing_flag':del f.a['trading_blocked']
    elif bad=='symbol':req['symbol']='OTHER'
    with pytest.raises(PaperBlocked):g.submit(req,operator_confirmed=True)
    assert ('POST','/v2/orders') not in f.calls

def test_cash_and_gross_limit(tmp_path,f):
    policy=POL|{'allowed_symbols':['TEST','ALT'],'min_cash_weight':.95,'max_gross_weight':.05}
    g=PaperGateway(tmp_path/'j',policy,f,clock=lambda:AT);g.arm(confirmed=True)
    with pytest.raises(PaperBlocked,match='CASH_FLOOR'):g.submit(ORDER|{'qty':6},operator_confirmed=True)

def test_response_mismatch_halts(g,f):
    g.arm(confirmed=True);f.bad_response=True
    assert g.submit(ORDER,operator_confirmed=True)['status']=='unknown'
    assert g.inspect()['local_unresolved_orders']==1

def test_transport_fixed_host(monkeypatch):
    assert PAPER_HOST=='https://paper-api.alpaca.markets'
    with pytest.raises(PaperBlocked):AlpacaPaperTransport()
    monkeypatch.setenv('ALPACA_PAPER_KEY','fixture');monkeypatch.setenv('ALPACA_PAPER_SECRET','fixture')
    t=AlpacaPaperTransport(enabled=True)
    with pytest.raises(PaperBlocked):t('GET','https://api.alpaca.markets/v2/account')
    with pytest.raises(PaperBlocked):t('POST','/v2/orders',query={'live':True},body=normalize_order(ORDER))
    with pytest.raises(PaperBlocked):t('POST','/v2/orders',body=normalize_order(ORDER)|{'type':'market'})
    with pytest.raises(ValueError):t('POST','/v2/orders',body={})
    with pytest.raises(PaperBlocked):t('DELETE','/v2/orders/../../account')

def test_offline_demo():
    r=demo();assert r['network_calls']==r['broker_orders']==0
    assert list(r['orders'].values())==['filled'];assert [x['qty'] for x in r['fills']]==[2,3]
    assert r['portfolio']['cash']=='9500.10' and r['portfolio']['equity_at_bid']=='9999.10'

def test_no_lookahead_replay():
    s=PaperReplay(10000,max_order_usd=1000);s.submit(ORDER,at=AT,expires_at=CLOSE)
    assert not s.tick(symbol='TEST',bid=99,ask=100,bid_size=5,ask_size=5,observed_at=AT,available_at=AT)
    with pytest.raises(ValueError):s.tick(symbol='TEST',bid=99,ask=100,bid_size=5,ask_size=5,observed_at=AT,available_at=AT)
    assert not s.tick(symbol='TEST',bid=99,ask=100,bid_size=5,ask_size=5,observed_at=AT,available_at='2026-11-23T15:01:00Z')
    assert not s.tick(symbol='TEST',bid=99,ask=100,bid_size=5,ask_size=5,observed_at=CLOSE,available_at=CLOSE)
    assert s.orders[ORDER['client_order_id']].status=='expired'

def test_replay_no_short_and_stop():
    s=PaperReplay(10000,max_order_usd=1000)
    with pytest.raises(PaperBlocked):s.submit(ORDER|{'side':'sell'},at=AT,expires_at=CLOSE)
    s.stop()
    with pytest.raises(PaperBlocked):s.submit(ORDER,at=AT,expires_at=CLOSE)


def test_concurrent_duplicate_submit(tmp_path,f):
    from concurrent.futures import ThreadPoolExecutor
    path=tmp_path/'concurrent';g=PaperGateway(path,POL,f,clock=lambda:AT);g.arm(confirmed=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:g.submit(ORDER,operator_confirmed=True),range(4)))
    assert f.calls.count(('POST','/v2/orders'))==1
    assert sum(bool(r.get('duplicate')) for r in results)==3

def test_revalidate_before_send(tmp_path,f):
    class ClockFlip:
        def __call__(self,m,p,**kw):
            if p=='/v2/clock' and f.calls.count(('GET','/v2/clock'))==1:f.clock['is_open']=False
            return f(m,p,**kw)
    g=PaperGateway(tmp_path/'j',POL,ClockFlip(),clock=lambda:AT);g.arm(confirmed=True)
    assert g.submit(ORDER,operator_confirmed=True)['status']=='local_blocked'
    assert ('POST','/v2/orders') not in f.calls

def test_terminal_contradiction_disarms(g,f):
    g.arm(confirmed=True);g.submit(ORDER,operator_confirmed=True)
    f.remote.update(status='filled',filled_qty='5',filled_avg_price='100.00')
    assert g.reconcile(ORDER['client_order_id'])['status']=='filled'
    f.remote.update(status='new',filled_qty='0')
    assert g.reconcile(ORDER['client_order_id'])['status']=='reconcile_failed'
    assert not g.inspect()['armed']
