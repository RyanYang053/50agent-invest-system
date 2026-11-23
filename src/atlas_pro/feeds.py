"""Strict public-source adapters; dependency-injected HTTP transport for tests.

No keys are stored. A production caller supplies its own network client with
rate limiting, retries, TLS verification, User-Agent and API quotas.
"""
from __future__ import annotations
import json,re
from datetime import date
from urllib.parse import urlencode,urlparse

class ProviderUnavailable(RuntimeError):pass

class PublicFeedClient:
    HOSTS={'data.sec.gov','api.stlouisfed.org','www.bankofcanada.ca'}
    def __init__(self, transport,*,sec_user_agent:str='',fred_api_key:str=''):
        self.transport=transport
        self.sec_ua=sec_user_agent
        self.fred_key=fred_api_key

    def _fetch(self,url,headers=None):
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname not in self.HOSTS or parsed.username or parsed.password or parsed.port:
            raise ValueError('UNTRUSTED_HOST')
        result=self.transport(url,headers or {})
        if not isinstance(result,dict):raise ProviderUnavailable('INVALID_PROVIDER_JSON')
        return result

    def sec_companyfacts(self,cik:int):
        if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', self.sec_ua.split()[-1] if self.sec_ua else ''):
            raise ValueError('SEC_IDENTIFYING_USER_AGENT_REQUIRED')
        if not isinstance(cik,int) or cik<=0 or cik>=10**10:raise ValueError('INVALID_CIK')
        url=f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json'
        return self._fetch(url,{'User-Agent':self.sec_ua,'Accept':'application/json'})

    def sec_submissions(self,cik:int):
        if not isinstance(cik,int) or cik<=0 or cik>=10**10:raise ValueError('INVALID_CIK')
        if not self.sec_ua:raise ValueError('SEC_IDENTIFYING_USER_AGENT_REQUIRED')
        return self._fetch(f'https://data.sec.gov/submissions/CIK{cik:010d}.json',{'User-Agent':self.sec_ua})

    def alfred_vintage(self,series:str,asof:str,*,observation_start='1990-01-01'):
        if not self.fred_key:raise ValueError('FRED_KEY_REQUIRED')
        if not re.fullmatch(r'[A-Za-z0-9_]{1,60}',series):raise ValueError('BAD_FRED_SERIES')
        day=date.fromisoformat(asof);date.fromisoformat(observation_start)
        q=urlencode({'series_id':series,'api_key':self.fred_key,'file_type':'json',
            'realtime_start':asof,'realtime_end':asof,'observation_start':observation_start})
        return self._fetch('https://api.stlouisfed.org/fred/series/observations?'+q)

    def boc_observations(self,series='FXUSDCAD',*,recent=30):
        if not re.fullmatch('[A-Z0-9]{1,35}',series):raise ValueError('BAD_BOC_SERIES')
        if not 1<=recent<=365:raise ValueError('BAD_RECENT_COUNT')
        return self._fetch(f'https://www.bankofcanada.ca/valet/observations/{series}/json?recent={recent}')
