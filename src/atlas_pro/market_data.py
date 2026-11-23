"""Alpaca IEX research-only adapter, explicit operator entitlement.
No full-market or executable quote claim. Never send market entitlement data to a cloud model.
"""
from __future__ import annotations
import os,re
from datetime import datetime, timezone
from .ledger import iso,digest
from .research import num
from .transport import PublicJSONTransport

class AlpacaJSONTransport(PublicJSONTransport):
    HOSTS=frozenset({'data.alpaca.markets'})

class AlpacaResearchQuotes:
    def __init__(self, *, policy, transport=None, api_key=None, api_secret=None):
        if policy.get('license_id')!='ALPACA_PERSONAL' or policy.get('permitted_for_personal_analysis') is not True or policy.get('allow_local_retention') is not True or policy.get('cloud_allowed') is not False:
            raise PermissionError('ALPACA_LOCAL_RESEARCH_ENTITLEMENT_REQUIRED')
        self.policy=policy;self.transport=transport or AlpacaJSONTransport();self.key=api_key or os.getenv('ALPACA_API_KEY');self.secret=api_secret or os.getenv('ALPACA_API_SECRET')
        if not self.key or not self.secret:raise ValueError('ALPACA_CREDENTIALS_REQUIRED')
    def quote(self,symbol,*,at=None):
        if not isinstance(symbol,str) or not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,11}',symbol):raise ValueError('bad symbol')
        url=f'https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest?feed=iex'
        payload=self.transport(url,{'APCA-API-KEY-ID':self.key,'APCA-API-SECRET-KEY':self.secret})
        now=iso(at) if at else datetime.now(timezone.utc)
        q=payload['quote']; t=iso(q['t']); bid,ask=num(q['bp']),num(q['ap'])
        if payload.get('symbol')!=symbol or not 0<bid<=ask or not 0<=(now-t).total_seconds()<=7*86400:raise ValueError('invalid or stale research quote')
        return {'symbol':symbol,'price':(bid+ask)/2,'bid':bid,'ask':ask,'price_asof':t.isoformat(),'available_at':now.isoformat(),'currency':'USD','price_basis':'IEX_PARTIAL_MIDPOINT_RESEARCH_ONLY','execution_qualified':False,'source':'alpaca_iex'}


def outstanding_shares(cf, submissions, *, at):
    """DEI actual outstanding shares, not weighted-average diluted shares.
    Select latest available observation, not a future filing or future share date.
    """
    if int(cf['cik'])!=int(submissions['cik']):raise ValueError('CIK mismatch')
    now=iso(at); rec=submissions['filings']['recent']
    if len(rec['accessionNumber'])!=len(rec['acceptanceDateTime']):raise ValueError('submission mismatch')
    stamps={}
    for a,t in zip(rec['accessionNumber'],rec['acceptanceDateTime']):
        try:stamps[a]=iso(t)
        except (TypeError,ValueError,AttributeError):continue
    result=[]
    for f in cf.get('facts',{}).get('dei',{}).get('EntityCommonStockSharesOutstanding',{}).get('units',{}).get('shares',[]):
        if f.get('form') not in ('10-K','10-Q','10-K/A','10-Q/A') or f.get('accn') not in stamps:continue
        try:
            publication=stamps[f['accn']]; observed=iso(f['end']+'T00:00:00Z'); shares=num(f['val'])
            if not observed<=publication<=now or shares<=0 or (now-observed).days>180:continue
            result.append({'shares':shares,'shares_asof':observed.isoformat(),'published_at':publication.isoformat(),'accession':f['accn'],'cik':int(cf['cik'])})
        except (KeyError,TypeError,ValueError):continue
    if not result:return None
    result.sort(key=lambda r:(r['shares_asof'],r['published_at']),reverse=True)
    best=result[0]
    if any(r['shares']!=best['shares'] for r in result if (r['shares_asof'],r['published_at'])==(best['shares_asof'],best['published_at'])):return None
    return best
