"""Operator-only, long-only paper order lifecycle. No live broker endpoint exists.

The remote adapter is deliberately not registered as an Agent tool. An isolated
paper account, local policy, explicit order approval and durable journal are
required. A lost acknowledgement is never treated as permission to retry POST.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json, os, re, sqlite3, ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler
from .ledger import iso, digest, canonical
from .transport import NoRedirect

PAPER_HOST = 'https://paper-api.alpaca.markets'
TERMINAL = {'filled', 'canceled', 'expired', 'rejected', 'local_blocked'}
REMOTE_STATES = TERMINAL - {'local_blocked'} | {'new','accepted','pending_new','partially_filled','pending_cancel','done_for_day','accepted_for_bidding','stopped','suspended','calculated','pending_replace','replaced'}
SYMBOL = re.compile(r'[A-Z][A-Z0-9.\-]{0,11}\Z')
ID = re.compile(r'atlas-paper-[A-Za-z0-9_-]{1,80}\Z')
UUID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z')

class PaperBlocked(RuntimeError): pass
class PaperHTTPError(RuntimeError):
    def __init__(self, code): super().__init__(f'PAPER_HTTP_{code}'); self.code=code

def money(value):
    if isinstance(value, bool): raise ValueError('boolean numeric')
    try: n=Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError): raise ValueError('invalid number') from None
    if not n.is_finite() or abs(n)>Decimal('1000000000000'): raise ValueError('numeric bounds')
    return n

def quantity(value):
    n=money(value)
    if n<=0 or n!=n.to_integral_value() or n>100000: raise ValueError('whole positive shares required')
    return int(n)

def utcnow(): return datetime.now(timezone.utc).isoformat()

def validate_policy(policy):
    if not isinstance(policy,dict) or policy.get('mode')!='ALPACA_PAPER_ONLY' or policy.get('live_execution') is not False or policy.get('owner_confirmed_paper_only') is not True:
        raise PaperBlocked('PAPER_POLICY_NOT_CONFIRMED')
    if not isinstance(policy.get('account_id'),str) or not UUID.fullmatch(policy['account_id']):raise PaperBlocked('EXPECTED_PAPER_ACCOUNT_REQUIRED')
    symbols=policy.get('allowed_symbols')
    if not isinstance(symbols,list) or not 1<=len(symbols)<=100 or any(not isinstance(s,str) or not SYMBOL.fullmatch(s) for s in symbols) or len(set(symbols))!=len(symbols):raise PaperBlocked('EXPLICIT_SYMBOL_ALLOWLIST_REQUIRED')
    # This gateway is intentionally more restrictive than an ordinary paper account.
    limits={k:money(policy[k]) for k in ('max_order_usd','max_position_weight','min_cash_weight','max_gross_weight')}
    if not 0<limits['max_order_usd']<=10000 or not 0<limits['max_position_weight']<=Decimal('.25') or not Decimal('.10')<=limits['min_cash_weight']<1 or not 0<limits['max_gross_weight']<=1-limits['min_cash_weight']:
        raise PaperBlocked('PAPER_POLICY_LIMITS_OUTSIDE_HARD_BOUNDS')
    return limits

def normalize_order(order):
    if not isinstance(order,dict) or set(order)!={'client_order_id','symbol','side','qty','limit_price'}:raise ValueError('invalid order fields')
    if not isinstance(order['client_order_id'],str) or not ID.fullmatch(order['client_order_id']) or not isinstance(order['symbol'],str) or not SYMBOL.fullmatch(order['symbol']) or order['side'] not in ('buy','sell'):raise ValueError('invalid order identity')
    price=money(order['limit_price'])
    if price<Decimal('1') or price>Decimal('100000') or price!=price.quantize(Decimal('.01')):raise ValueError('limit price must be >= $1 and cents')
    return {'client_order_id':order['client_order_id'],'symbol':order['symbol'],'side':order['side'],'qty':str(quantity(order['qty'])),'limit_price':format(price,'.2f'),'type':'limit','time_in_force':'day','extended_hours':False}

class AlpacaPaperTransport:
    """Fixed TLS origin, no redirects/proxies, no automatic retries; paper keys only."""
    def __init__(self, *, enabled=False, timeout=15):
        if enabled is not True:raise PaperBlocked('PAPER_NETWORK_DISABLED')
        self.key=os.environ.get('ALPACA_PAPER_KEY'); self.secret=os.environ.get('ALPACA_PAPER_SECRET')
        if not self.key or not self.secret:raise PaperBlocked('PAPER_CREDENTIALS_REQUIRED')
        if not 0<timeout<=30:raise ValueError('timeout bounds')
        self.timeout=timeout
        self.opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
    def __call__(self, method, path, *, query=None, body=None):
        exact={('GET','/v2/account'),('GET','/v2/positions'),('GET','/v2/orders'),('GET','/v2/clock'),('GET','/v2/orders:by_client_order_id'),('POST','/v2/orders')}
        safe= (method,path) in exact or (method=='GET' and re.fullmatch(r'/v2/assets/[A-Z][A-Z0-9.\-]{0,11}',path)) or (method=='DELETE' and path.startswith('/v2/orders/') and UUID.fullmatch(path.removeprefix('/v2/orders/')))
        if not safe:raise PaperBlocked('PAPER_PATH_DENIED')
        if method=='POST':
            if not isinstance(body,dict) or set(body)!={'client_order_id','symbol','side','qty','limit_price','type','time_in_force','extended_hours'}:raise ValueError('strict limit order body required')
            if normalize_order({k:body[k] for k in ('client_order_id','symbol','side','qty','limit_price')})!=body or body['extended_hours'] is not False:raise PaperBlocked('PAPER_ORDER_BODY_DENIED')
        if method!='POST' and body is not None:raise ValueError('unexpected body')
        if query is not None and not ((path=='/v2/orders' and method=='GET' and query=={'status':'open','limit':500}) or (path=='/v2/orders:by_client_order_id' and set(query)=={'client_order_id'} and ID.fullmatch(query['client_order_id']))):raise PaperBlocked('PAPER_QUERY_DENIED')
        url=PAPER_HOST+path+('?' + urlencode(query) if query else '')
        req=Request(url,data=json.dumps(body,allow_nan=False).encode() if body is not None else None,headers={'APCA-API-KEY-ID':self.key,'APCA-API-SECRET-KEY':self.secret,'Accept':'application/json','Content-Type':'application/json','Accept-Encoding':'identity'},method=method)
        try:
            with self.opener.open(req,timeout=self.timeout) as resp:
                raw=resp.read(2_000_001)
                if len(raw)>2_000_000:raise PaperBlocked('PAPER_RESPONSE_TOO_LARGE')
                if not raw and method=='DELETE':return None
                result=json.loads(raw)
                if not isinstance(result,(dict,list)):raise PaperBlocked('PAPER_RESPONSE_INVALID')
                return result
        except HTTPError as exc:
            code=exc.code;exc.close();raise PaperHTTPError(code) from None
        except (URLError,TimeoutError,OSError,ValueError):raise PaperBlocked('PAPER_TRANSPORT_UNCERTAIN') from None

class PaperGateway:
    """Durable paper-only gate. Every POST is explicit and at most one per ID.

    SQLite serializes this process family, not outside broker clients. Use a
    dedicated paper account, no manual concurrent orders. Kill switch stops new
    sends; it does not retroactively cancel in-flight or already-open orders.
    """
    def __init__(self, path, policy, transport, *, clock=utcnow):
        self.limits=validate_policy(policy); self.policy=json.loads(canonical(policy));self.policy_hash=digest(policy)
        self.path=str(path); self.transport=transport; self.clock=clock
        with self._db() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS paper_control(id INTEGER PRIMARY KEY CHECK(id=1),account_id TEXT NOT NULL,policy_hash TEXT NOT NULL,armed INTEGER NOT NULL CHECK(armed IN (0,1)));
            CREATE TABLE IF NOT EXISTS paper_orders(client_id TEXT PRIMARY KEY,request_json TEXT NOT NULL,status TEXT NOT NULL,broker_id TEXT,filled_qty TEXT NOT NULL DEFAULT '0',updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS paper_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT NOT NULL,client_id TEXT NOT NULL,status TEXT NOT NULL,detail TEXT NOT NULL);''')
            c.execute('INSERT OR IGNORE INTO paper_control VALUES(1,?,?,0)',(policy['account_id'],self.policy_hash))
            cols={r[1] for r in c.execute('PRAGMA table_info(paper_orders)')}
            if 'filled_avg_price' not in cols:c.execute('ALTER TABLE paper_orders ADD COLUMN filled_avg_price TEXT')
            self._control(c)
    @contextmanager
    def _db(self):
        c=sqlite3.connect(self.path,timeout=60,isolation_level=None);c.row_factory=sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA synchronous=FULL')
        try:
            yield c
            if c.in_transaction:c.commit()
        except Exception:
            if c.in_transaction:c.rollback()
            raise
        finally:c.close()
    def _control(self,c):
        row=c.execute('SELECT * FROM paper_control WHERE id=1').fetchone()
        if row['account_id']!=self.policy['account_id'] or row['policy_hash']!=self.policy_hash:raise PaperBlocked('PAPER_ACCOUNT_OR_POLICY_CHANGED_USE_NEW_JOURNAL')
        return row
    def _event(self,c,client,status,detail):
        c.execute('INSERT INTO paper_events(at,client_id,status,detail) VALUES(?,?,?,?)',(self.clock(),client,status,detail))
    def _account(self):
        a=self.transport('GET','/v2/account')
        if not isinstance(a,dict) or a.get('id')!=self.policy['account_id'] or a.get('currency')!='USD':raise PaperBlocked('PAPER_ACCOUNT_MISMATCH')
        if a.get('status')!='ACTIVE' or any(a.get(k) is not False for k in ('trading_blocked','account_blocked','trade_suspended_by_user')):raise PaperBlocked('PAPER_ACCOUNT_NOT_TRADABLE')
        if money(a['equity'])<=0 or money(a['cash'])<0:raise PaperBlocked('PAPER_CASH_OR_EQUITY_INVALID')
        return a
    def _open_orders(self):
        rows=self.transport('GET','/v2/orders',query={'status':'open','limit':500})
        if not isinstance(rows,list) or len(rows)>=500:raise PaperBlocked('PAPER_OPEN_ORDER_COVERAGE_UNKNOWN')
        return rows
    def _positions(self, account):
        rows=self.transport('GET','/v2/positions')
        if not isinstance(rows,list):raise PaperBlocked('PAPER_POSITIONS_INVALID')
        pos={}
        for p in rows:
            s=p.get('symbol')
            if s not in self.policy['allowed_symbols'] or s in pos or p.get('asset_class')!='us_equity' or p.get('side')!='long':raise PaperBlocked('PAPER_UNSUPPORTED_OR_UNALLOWLISTED_POSITION')
            q=quantity(p['qty']);v=money(p['market_value'])
            if v<=0:raise PaperBlocked('PAPER_POSITION_VALUE_INVALID')
            pos[s]=(q,v)
        gross=sum((p[1] for p in pos.values()),Decimal(0)); equity=money(account['equity']); cash=money(account['cash'])
        # Serial snapshots are not atomic; reject large unexplained discrepancies.
        if abs(cash+gross-equity)>max(Decimal('2'),equity*Decimal('.001')):raise PaperBlocked('PAPER_ACCOUNT_NOT_RECONCILED')
        return pos,gross
    def inspect(self):
        a=self._account();orders=self._open_orders();pos,gross=self._positions(a)
        with self._db() as c:
            ctrl=self._control(c);pending=c.execute("SELECT count(*) FROM paper_orders WHERE status NOT IN ('filled','canceled','expired','rejected','local_blocked')").fetchone()[0]
        return {'mode':'PAPER_ONLY','account_verified':True,'armed':bool(ctrl['armed']),'open_orders':len(orders),'local_unresolved_orders':pending,'positions':len(pos),'equity_usd':str(money(a['equity'])),'gross_usd':str(gross),'live_execution':False}
    def arm(self, *, confirmed=False):
        if confirmed is not True:raise PaperBlocked('OPERATOR_ARM_REQUIRED')
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE');self._control(c);self._account();c.execute('UPDATE paper_control SET armed=1 WHERE id=1');self._event(c,'CONTROL','armed','operator confirmed paper account')
    def stop(self):
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE');self._control(c);c.execute('UPDATE paper_control SET armed=0 WHERE id=1');self._event(c,'CONTROL','stopped','new sends blocked; reconcile outstanding orders')
    def _preflight(self, req):
        if req['symbol'] not in self.policy['allowed_symbols']:raise PaperBlocked('PAPER_SYMBOL_NOT_ALLOWED')
        started=iso(self.clock());a=self._account(); clock=self.transport('GET','/v2/clock'); now=iso(self.clock()); stamp=iso(clock['timestamp'])
        if clock.get('is_open') is not True or abs((now-stamp).total_seconds())>30 or iso(clock['next_close'])<=now:raise PaperBlocked('PAPER_MARKET_CLOSED_OR_STALE_CLOCK')
        asset=self.transport('GET','/v2/assets/'+req['symbol'])
        if asset.get('symbol')!=req['symbol'] or asset.get('class')!='us_equity' or asset.get('status')!='active' or asset.get('tradable') is not True:raise PaperBlocked('PAPER_ASSET_NOT_TRADABLE')
        if self._open_orders():raise PaperBlocked('PAPER_EXISTING_OPEN_ORDERS')
        pos,gross=self._positions(a)
        if not 0<=(iso(self.clock())-started).total_seconds()<=30:raise PaperBlocked('PAPER_PREFLIGHT_TOO_SLOW')
        q,v=pos.get(req['symbol'],(0,Decimal(0))); qty=quantity(req['qty']); notional=money(req['limit_price'])*qty; equity=money(a['equity']); cash=money(a['cash']); lim=self.limits
        if notional>lim['max_order_usd']:raise PaperBlocked('PAPER_ORDER_NOTIONAL_LIMIT')
        if req['side']=='sell':
            if qty>q:raise PaperBlocked('PAPER_SHORT_SELL_DENIED')
        else:
            if cash-notional<equity*lim['min_cash_weight']:raise PaperBlocked('PAPER_CASH_FLOOR')
            if v+notional>equity*lim['max_position_weight']:raise PaperBlocked('PAPER_POSITION_CAP')
            if gross+notional>equity*lim['max_gross_weight']:raise PaperBlocked('PAPER_GROSS_CAP')
    def _record_response(self,c,row,remote):
        req=json.loads(row['request_json']);cid=req['client_order_id'];status=remote.get('status');bid=remote.get('id')
        if status not in REMOTE_STATES or not isinstance(bid,str) or not UUID.fullmatch(bid) or (row['broker_id'] and row['broker_id']!=bid):raise PaperBlocked('PAPER_BROKER_RESPONSE_ID_OR_STATUS_INVALID')
        if any(remote.get(k)!=req[k] for k in ('client_order_id','symbol','side','type','time_in_force')) or quantity(remote['qty'])!=quantity(req['qty']) or money(remote['limit_price'])!=money(req['limit_price']):raise PaperBlocked('PAPER_BROKER_ORDER_MISMATCH')
        fill=money(remote['filled_qty']);old=money(row['filled_qty']);qty=quantity(req['qty'])
        if fill<old or fill>qty or fill<0 or fill!=fill.to_integral_value() or (status=='filled' and fill!=qty) or (status=='partially_filled' and not 0<fill<qty):raise PaperBlocked('PAPER_FILL_QUANTITY_INVALID')
        avg=None
        if fill:
            avg=money(remote['filled_avg_price']);limit=money(req['limit_price'])
            if avg<=0 or (req['side']=='buy' and avg>limit) or (req['side']=='sell' and avg<limit):raise PaperBlocked('PAPER_LIMIT_FILL_MISMATCH')
        if row['status'] in TERMINAL and row['status']!=status:raise PaperBlocked('PAPER_TERMINAL_STATE_REGRESSION')
        c.execute('UPDATE paper_orders SET status=?,broker_id=?,filled_qty=?,filled_avg_price=?,updated_at=? WHERE client_id=?',(status,bid,str(fill),str(avg) if avg is not None else None,self.clock(),cid));self._event(c,cid,status,canonical({'filled_qty':str(fill),'filled_avg_price':str(avg) if avg is not None else None,'note':'broker cumulative response validated; not per-fill activity'}))
        return {'client_order_id':cid,'status':status,'filled_qty':str(fill),'filled_avg_price':str(avg) if avg is not None else None,'paper_only':True,'live_execution':False}
    def submit(self, order, *, operator_confirmed=False):
        if operator_confirmed is not True:raise PaperBlocked('EXPLICIT_PAPER_ORDER_CONFIRMATION_REQUIRED')
        req=normalize_order(order);cid=req['client_order_id']
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE');ctrl=self._control(c)
            if not ctrl['armed']:raise PaperBlocked('PAPER_KILL_SWITCH_OFF')
            prior=c.execute('SELECT * FROM paper_orders WHERE client_id=?',(cid,)).fetchone()
            if prior:
                if json.loads(prior['request_json'])!=req:raise PaperBlocked('PAPER_CLIENT_ID_COLLISION')
                return {'status':prior['status'],'client_order_id':cid,'duplicate':True,'paper_only':True,'live_execution':False}
            if c.execute("SELECT 1 FROM paper_orders WHERE status NOT IN ('filled','canceled','expired','rejected','local_blocked') LIMIT 1").fetchone():raise PaperBlocked('PAPER_UNRESOLVED_ORDER_RECONCILE_FIRST')
            self._preflight(req)
            c.execute('INSERT INTO paper_orders(client_id,request_json,status,broker_id,filled_qty,updated_at) VALUES(?,?,?,NULL,?,?)',(cid,canonical(req),'submitting','0',self.clock()));self._event(c,cid,'submitting','durable intent before POST')
        # Intention committed before network I/O. A crash leaves 'submitting' and
        # future invocations may query it but MUST NOT submit the same ID again.
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE');ctrl=self._control(c)
            row=c.execute('SELECT * FROM paper_orders WHERE client_id=?',(cid,)).fetchone()
            if not ctrl['armed']:
                c.execute("UPDATE paper_orders SET status='local_blocked' WHERE client_id=?",(cid,));self._event(c,cid,'local_blocked','stopped before POST');return {'status':'local_blocked','paper_only':True,'live_execution':False}
            # Revalidate clock/account/risk just before the first and only POST.
            # A local failure here has not sent an order and can safely block.
            try:self._preflight(req)
            except Exception as exc:
                c.execute("UPDATE paper_orders SET status='local_blocked',updated_at=? WHERE client_id=?",(self.clock(),cid));self._event(c,cid,'local_blocked',type(exc).__name__);return {'status':'local_blocked','paper_only':True,'live_execution':False}
            try:
                return self._record_response(c,row,self.transport('POST','/v2/orders',body=req))
            except Exception as exc:
                c.execute("UPDATE paper_orders SET status='unknown',updated_at=? WHERE client_id=?",(self.clock(),cid));self._event(c,cid,'unknown',type(exc).__name__)
                return {'status':'unknown','client_order_id':cid,'paper_only':True,'live_execution':False,'reconcile_required':True}
    def reconcile(self,cid):
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE');self._control(c);row=c.execute('SELECT * FROM paper_orders WHERE client_id=?',(cid,)).fetchone()
            if not row:raise PaperBlocked('PAPER_UNKNOWN_LOCAL_ORDER')
            if row['status']=='local_blocked':return {'status':'local_blocked','paper_only':True,'live_execution':False}
            self._account()
            try:return self._record_response(c,row,self.transport('GET','/v2/orders:by_client_order_id',query={'client_order_id':cid}))
            except Exception as exc:
                # A contradictory broker response on a previously terminal order
                # must not leave the system armed.
                if row['status'] in TERMINAL and isinstance(exc,PaperBlocked):c.execute('UPDATE paper_control SET armed=0 WHERE id=1')
                self._event(c,cid,'reconcile_failed',type(exc).__name__)
                return {'status':'reconcile_failed','previous_status':row['status'],'paper_only':True,'live_execution':False,'reconcile_required':True}
    def cancel(self,cid,*,operator_confirmed=False):
        if operator_confirmed is not True:raise PaperBlocked('EXPLICIT_PAPER_CANCEL_CONFIRMATION_REQUIRED')
        result=self.reconcile(cid)
        if result['status'] in TERMINAL or result['status']=='reconcile_failed':return result
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE');self._control(c);row=c.execute('SELECT * FROM paper_orders WHERE client_id=?',(cid,)).fetchone()
            if row['status'] in TERMINAL:return {'status':row['status'],'paper_only':True,'live_execution':False}
            self._account()
            try:self.transport('DELETE','/v2/orders/'+row['broker_id']);status='cancel_requested'
            except Exception:status='cancel_uncertain'
            c.execute('UPDATE paper_orders SET status=?,updated_at=? WHERE client_id=?',(status,self.clock(),cid));self._event(c,cid,status,'broker acknowledgement not a terminal fill/cancel result')
        return {'status':status,'paper_only':True,'live_execution':False,'reconcile_required':True}
