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

    def tick(self,journal,ledger,pid):
        w=journal.next_window(pid)
        if w is None:return journal.report(pid)
        if w['synthetic'] is not False:raise ValueError('synthetic plans cannot ingest real data')
        # Validate every binding before spending a network request.
        for binding in w['source_bindings'].values():
            if binding!={'source_id':SOURCE,'license_id':LICENSE,'data_class':'licensed','ticker':binding.get('ticker')} or not binding.get('ticker'):raise ValueError('plan is not bound to Tiingo EOD')
        ids={s:self.evidence(ledger,security_id=s,ticker=b['ticker'],from_close=w['from_close'],to_close=w['to_close']) for s,b in sorted(w['source_bindings'].items())}
        return journal.append(pid,ledger,session_close=w['to_close'],evidence_by_security=ids)
