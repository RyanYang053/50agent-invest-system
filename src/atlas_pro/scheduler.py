"""Operator-driven periodic orchestration. Invoke tick via Task Scheduler/systemd.
No sleeping Agent loops, no paid calls, no execution. P0 signals are external
risk-engine events and are never suppressed by calendar or budget.
"""
from __future__ import annotations
from datetime import timedelta, time
from zoneinfo import ZoneInfo
from .ledger import iso

SCHEDULE=(('daily_portfolio_digest','daily',time(20)),('weekly_research_triage','weekly',time(9)),
          ('weekly_postmortem','weekly',time(10)),('monthly_attribution','monthly',time(11)),
          ('quarterly_thesis_review','quarterly',time(12)))

def tick(bus, *, at):
    now=iso(at); local=now.astimezone(ZoneInfo('America/New_York')); d=local.date(); results=[]
    market=bus.market_status(at)
    # Catch up within the local day. Week/month/quarter jobs use first Saturday,
    # avoiding duplicate runs across UTC midnight and avoiding paid overnight loops.
    for event,freq,when in SCHEDULE:
        if local.time().replace(tzinfo=None)<when:continue
        if freq=='daily' and market['session']=='CLOSED':continue
        if freq=='weekly' and d.weekday()!=5:continue
        if freq in ('monthly','quarterly') and (d.weekday()!=5 or d.day>7):continue
        if freq=='quarterly' and d.month not in (1,4,7,10):continue
        period=d.isoformat() if freq in ('daily','weekly') else (d.strftime('%Y-%m') if freq=='monthly' else f'{d.year}-Q{(d.month-1)//3+1}')
        results.append(bus.submit({'event_type':event,'source_event_id':f'schedule:{event}:{period}','scheduled_for_et':d.isoformat()},verified=False,at=at))
    return results

class ResearchWorker:
    """Operator registers event handlers; unknown work is explicit BLOCKED/FAILED.
    Handler must be idempotent by work_id. No generic shell, and P0 only receives
    deterministic handlers. This is a single-step worker, not an always-on daemon.
    """
    def __init__(self,bus,handlers,*,clock):
        self.bus=bus;self.handlers=handlers;self.clock=clock
    def step(self):
        j=self.bus.claim(at=self.clock())
        if j is None:return None
        event=j['payload']['event']; kind=event['event_type']; h=self.handlers.get(kind)
        if h is None or (j['payload']['priority']=='P0' and not getattr(h,'deterministic_only',False)):
            status=self.bus.finish(j['work_id'],j['lease_token'],at=self.clock(),success=False,result={'reason':'NO_CERTIFIED_HANDLER'})
            return {'work_id':j['work_id'],'status':status,'can_trade':False}
        try:
            result=h(j['work_id'],j['payload'])
            if not isinstance(result,dict) or result.get('can_trade') is not False:raise ValueError('unsafe handler result')
        except Exception as exc:
            status=self.bus.finish(j['work_id'],j['lease_token'],at=self.clock(),success=False,result={'reason':type(exc).__name__},retryable=True)
            return {'work_id':j['work_id'],'status':status,'can_trade':False}
        status=self.bus.finish(j['work_id'],j['lease_token'],at=self.clock(),success=True,result=result)
        return {'work_id':j['work_id'],'status':status,'result':result,'can_trade':False}
