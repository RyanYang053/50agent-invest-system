"""Deterministic single-session paper replay, deliberately not a live fill engine.
Limit orders use the next observed bid/ask and available displayed size, not
future prices or midpoint. No borrowing, shorting, or unapproved strategies.
"""
from dataclasses import dataclass
from decimal import Decimal
from .paper import money,quantity,normalize_order,PaperBlocked
from .ledger import iso

@dataclass
class ReplayOrder:
    request: dict
    placed_at: str
    expires_at: str
    remaining: int
    status: str='open'

class PaperReplay:
    def __init__(self, cash, *, max_order_usd, min_cash_usd=0, fee_per_share='0.01'):
        self.cash=money(cash);self.max_order=money(max_order_usd);self.floor=money(min_cash_usd);self.fee=money(fee_per_share)
        if not 0<=self.floor<self.cash or not 0<self.max_order<=self.cash or self.fee<0:raise ValueError('invalid simulator policy')
        self.positions={};self.orders={};self.last_tick=None;self.fills=[];self.stopped=False
    def stop(self):self.stopped=True
    def submit(self, order, *, at, expires_at):
        if self.stopped:raise PaperBlocked('REPLAY_STOPPED')
        req=normalize_order(order);cid=req['client_order_id'];start=iso(at);end=iso(expires_at)
        if end<=start or (end-start).total_seconds()>86400 or (self.last_tick and start<self.last_tick):raise ValueError('invalid replay order time')
        if cid in self.orders:
            if self.orders[cid].request!=req:raise ValueError('client ID collision')
            return self.orders[cid].status
        if any(o.status in ('open','partially_filled') for o in self.orders.values()):raise PaperBlocked('REPLAY_ONE_OPEN_ORDER')
        q=quantity(req['qty']);price=money(req['limit_price'])
        if q*price>self.max_order:raise PaperBlocked('REPLAY_ORDER_CAP')
        if req['side']=='buy' and self.cash-q*(price+self.fee)<self.floor:raise PaperBlocked('REPLAY_CASH_FLOOR')
        if req['side']=='sell' and (self.positions.get(req['symbol'],0)<q or self.cash<self.floor+q*self.fee):raise PaperBlocked('REPLAY_SHORT_OR_FEE_CASH_DENIED')
        self.orders[cid]=ReplayOrder(req,start.isoformat(),end.isoformat(),q);return 'open'
    def cancel(self,cid):
        o=self.orders[cid]
        if o.status in ('open','partially_filled'):o.status='canceled'
        return o.status
    def tick(self, *, symbol, bid, ask, bid_size, ask_size, observed_at, available_at):
        observed=iso(observed_at);available=iso(available_at);b=money(bid);a=money(ask)
        if observed>available or self.last_tick and available<=self.last_tick:raise ValueError('duplicate or out-of-order replay tick')
        if not 0<b<=a:raise ValueError('crossed or invalid quote')
        if type(bid_size) is not int or type(ask_size) is not int or bid_size<0 or ask_size<0:raise ValueError('invalid displayed size')
        self.last_tick=available;out=[]
        for cid,o in self.orders.items():
            if o.status not in ('open','partially_filled'):continue
            if available>=iso(o.expires_at):o.status='expired';continue
            # Even a later arrival of an old quote cannot simulate a new fill.
            if o.request['symbol']!=symbol or observed<=iso(o.placed_at):continue
            buy=o.request['side']=='buy';price=a if buy else b;limit=money(o.request['limit_price']);size=ask_size if buy else bid_size
            if (buy and price>limit) or (not buy and price<limit) or not size:continue
            qty=min(o.remaining,size);fee=self.fee*qty;cost=price*qty
            if buy:
                if self.cash-cost-fee<self.floor:raise PaperBlocked('REPLAY_CASH_FLOOR')
                self.cash-=cost+fee;self.positions[symbol]=self.positions.get(symbol,0)+qty
            else:
                if self.positions.get(symbol,0)<qty or self.cash+cost-fee<self.floor:raise PaperBlocked('REPLAY_SHORT_OR_CASH_DENIED')
                self.cash+=cost-fee;self.positions[symbol]-=qty
            o.remaining-=qty;o.status='filled' if not o.remaining else 'partially_filled'
            fill={'client_order_id':cid,'side':o.request['side'],'symbol':symbol,'qty':qty,'price':str(price),'fee':str(fee),'available_at':available.isoformat(),'mode':'OFFLINE_SYNTHETIC_REPLAY'}
            self.fills.append(fill);out.append(fill)
        return out
    def mark(self, bids):
        value=Decimal(0)
        for symbol,qty in self.positions.items():
            if qty:
                px=money(bids[symbol])
                if px<=0:raise ValueError('invalid mark')
                value+=qty*px
        return {'cash':str(self.cash),'equity_at_bid':str(self.cash+value),'positions':dict(self.positions),'fills':len(self.fills),'paper_only':True,'live_execution':False}

def demo():
    sim=PaperReplay('10000',max_order_usd='1000',min_cash_usd='2000')
    start='2026-11-23T15:00:00Z';close='2026-11-23T21:00:00Z'
    order={'client_order_id':'atlas-paper-fixture-buy','symbol':'TEST','side':'buy','qty':5,'limit_price':'100.00'}
    sim.submit(order,at=start,expires_at=close)
    for minute,bid,ask,size in [(1,'100.00','100.05',10),(2,'99.90','100.00',2),(3,'99.80','99.95',3)]:
        t=f'2026-11-23T15:{minute:02}:00Z';sim.tick(symbol='TEST',bid=bid,ask=ask,bid_size=size,ask_size=size,observed_at=t,available_at=t)
    return {'fixture_only':True,'network_calls':0,'broker_orders':0,'orders':{k:v.status for k,v in sim.orders.items()},'fills':sim.fills,'portfolio':sim.mark({'TEST':'99.80'})}

if __name__=='__main__':
    import json
    print(json.dumps(demo(),indent=2))
