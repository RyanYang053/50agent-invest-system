"""Read-only Tiingo EOD adapter for the prospective shadow ledger.
Adjusted-close ratio is a provider-specific total-return proxy, not a fill.
Credentials are local; source rights and corporate-action coverage must be
explicitly confirmed by the data operator. No training or cloud transfer.
"""
from __future__ import annotations
from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
import json, os, re, ssl
from .transport import NoRedirect
from .ledger import digest, iso
from .research import num

SOURCE='tiingo_eod';LICENSE='TIINGO_EOD_PERSONAL'

def _now():return datetime.now(timezone.utc).isoformat()

class TiingoEOD:
    def __init__(self,policy,*,network=False,transport=None,clock=_now):
        required={'license_id':LICENSE,'permitted_for_personal_analysis':True,'allow_local_retention':True,'cloud_allowed':False,'adjustment_coverage_reviewed':True}
        if any(policy.get(k) is not v if isinstance(v,bool) else policy.get(k)!=v for k,v in required.items()):raise PermissionError('reviewed local Tiingo EOD licence required')
        self.policy=policy;self.clock=clock
        if transport is None:
            if network is not True:raise PermissionError('network disabled')
            self.key=os.getenv('TIINGO_API_KEY')
            if not self.key:raise PermissionError('TIINGO_API_KEY required')
            self.opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
        self.transport=transport or self._fetch
    def _fetch(self,ticker,start,end):
        # Caller validates ticker and dates; no arbitrary URLs or redirects.
        url=f'https://api.tiingo.com/tiingo/daily/{ticker}/prices?'+urlencode({'startDate':start,'endDate':end,'resampleFreq':'daily','format':'json'})
        req=Request(url,headers={'Authorization':'Token '+self.key,'Accept':'application/json','Accept-Encoding':'identity'},method='GET')
        try:
            with self.opener.open(req,timeout=20) as r:
                body=r.read(1_000_001)
                if len(body)>1_000_000:raise ValueError('EOD response too large')
                return json.loads(body)
        except HTTPError as e:
            code=e.code;e.close();raise RuntimeError(f'TIINGO_HTTP_{code}') from None
        except (URLError,OSError,ValueError):raise RuntimeError('TIINGO_DATA_UNAVAILABLE') from None
    def evidence(self,ledger,*,security_id,ticker,from_close,to_close):
        if not isinstance(ticker,str) or not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,11}',ticker):raise ValueError('invalid Tiingo ticker')
        a,b=iso(from_close),iso(to_close);et=ZoneInfo('America/New_York');d1=a.astimezone(et).date();d2=b.astimezone(et).date()
        now=iso(self.clock())
        # Provider documents corrections until about 20:00 ET. Do not pretend
        # these are final at 16:00. Later revisions can still occur.
        not_before=datetime.combine(d2,time(20,15),tzinfo=et).astimezone(timezone.utc)
        if not a<b or not d1<d2 or now<not_before:raise ValueError('EOD correction window not elapsed')
        raw=self.transport(ticker,d1.isoformat(),d2.isoformat())
        received=iso(self.clock())
        if received<now or not isinstance(raw,list) or len(raw)!=2:raise ValueError('exact two-session EOD coverage required')
        bars={}
        for x in raw:
            stamp=iso(x['date']);date=stamp.date().isoformat()
            if date in bars or stamp.time()!=time(0):raise ValueError('unexpected or duplicate provider date')
            close,adjusted,div,split=(num(x[k]) for k in ('close','adjClose','divCash','splitFactor'))
            if min(close,adjusted,split)<=0 or div<0:raise ValueError('invalid adjusted EOD observation')
            bars[date]={'date':date,'close':close,'adjClose':adjusted,'divCash':div,'splitFactor':split}
        if set(bars)!={d1.isoformat(),d2.isoformat()}:raise ValueError('wrong EOD dates or missing asset')
        before,after=bars[d1.isoformat()],bars[d2.isoformat()]
        value={'kind':'daily_total_return','security_id':security_id,'ticker':ticker,'currency':'USD','from_close':a.isoformat(),'to_close':b.isoformat(),'total_return':num(after['adjClose']/before['adjClose']-1),'corporate_actions_verified':True,'synthetic':False,'return_basis':'TIINGO_ADJUSTED_CLOSE_PROXY_OPERATOR_ATTESTED','raw_response_hash':digest(raw),'before':before,'after':after,'received_at':received.isoformat()}
        rid=digest(value)
        ledger.add_evidence({'record_id':rid,'source_id':SOURCE,'document_id':rid,'security_id':security_id,'observed_at':b.isoformat(),'published_at':received.isoformat(),'available_at':received.isoformat(),'payload':value,'data_class':'licensed','license_id':LICENSE},policy=self.policy)
        return rid

    def existing_evidence(self,ledger,*,security_id,ticker,from_close,to_close):
        """Reuse the original qualified observation across plans, even after restart.

        Never choose silently between conflicting stored revisions. This is an
        operator-managed single writer, not a concurrent provider quota service.
        """
        now=iso(self.clock()).isoformat(); end=iso(to_close).isoformat()
        with ledger._db() as c:
            ids=[r[0] for r in c.execute("SELECT record_id FROM evidence WHERE security_id=? AND source_id=? AND license_id=? AND data_class='licensed' AND observed_at=? AND available_at<=? AND json_extract(payload_json,'$.ticker')=? AND json_extract(payload_json,'$.from_close')=? AND json_extract(payload_json,'$.to_close')=?",(security_id,SOURCE,LICENSE,end,now,ticker,iso(from_close).isoformat(),end))]
        if len(ids)>1:raise ValueError('ambiguous existing return evidence; independent review required')
        if not ids:return None
        r=ledger.resolve_ids(ids,security_id=security_id,decision_at=now,include_private=True)[0]
        v=r['payload']
        if (r['record_id']!=digest(v) or v.get('kind')!='daily_total_return' or v.get('security_id')!=security_id or v.get('currency')!='USD' or v.get('synthetic') is not False or v.get('corporate_actions_verified') is not True or num(v['total_return'])< -1):raise ValueError('unqualified cached evidence')
        return ids[0]

    def tick(self,journal,ledger,pid,*,fetch_budget=None):
        w=journal.next_window(pid)
        if w is None:return journal.report(pid)
        if w['synthetic'] is not False:raise ValueError('synthetic plans cannot ingest real data')
        for binding in w['source_bindings'].values():
            if binding!={'source_id':SOURCE,'license_id':LICENSE,'data_class':'licensed','ticker':binding.get('ticker')} or not binding.get('ticker'):raise ValueError('plan is not bound to Tiingo EOD')
        requests={s:{'security_id':s,'ticker':b['ticker'],'from_close':w['from_close'],'to_close':w['to_close']} for s,b in sorted(w['source_bindings'].items())}
        ids={s:self.existing_evidence(ledger,**r) for s,r in requests.items()}
        missing=[s for s,r in ids.items() if r is None]
        if fetch_budget is not None:
            if len(missing)>fetch_budget[0]:return {'status':'FETCH_BUDGET_EXHAUSTED','can_trade':False}
        for s in missing:
            if fetch_budget is not None:fetch_budget[0]-=1
            ids[s]=self.evidence(ledger,**requests[s])
        return journal.append(pid,ledger,session_close=w['to_close'],evidence_by_security=ids)

    def tick_batch(self,journal,ledger,plan_ids,*,max_fetches=20):
        """One next-window per explicitly approved plan; scheduler may invoke daily.
        Shared source observations are reused; failures isolated, no blind retries.
        No automatic plan creation, no broker access, no strategy promotion.
        """
        if not isinstance(plan_ids,list) or not 1<=len(plan_ids)<=50 or any(not isinstance(p,str) or not re.fullmatch('[a-f0-9]{64}',p) for p in plan_ids) or len(set(plan_ids))!=len(plan_ids) or type(max_fetches) is not int or not 0<=max_fetches<=200:raise ValueError('invalid batch allowlist or fetch budget')
        budget=[max_fetches];results={}
        for pid in plan_ids:
            try:
                w=journal.next_window(pid)
                if w is None:results[pid]={'status':'COMPLETE','can_trade':False};continue
                end=iso(w['to_close']);ready=datetime.combine(end.astimezone(ZoneInfo('America/New_York')).date(),time(20,15),tzinfo=ZoneInfo('America/New_York'))
                if iso(self.clock())<ready:results[pid]={'status':'NOT_DUE','can_trade':False};continue
                results[pid]=self.tick(journal,ledger,pid,fetch_budget=budget)
            except (ValueError,KeyError,PermissionError,RuntimeError) as exc:
                # No provider body, secrets, or raw exception message in the report.
                results[pid]={'status':'BLOCKED','error_type':type(exc).__name__,'can_trade':False}
        return {'status':'BATCH_COMPLETE','plans':results,'fetches_reserved':max_fetches-budget[0],'can_trade':False}
