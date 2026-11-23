"""Bounded public JSON HTTPS transport; no redirects or proxy env by default.
Operator-owned fixed provider URLs only. Do not expose as a generic Agent fetch tool.
"""
from __future__ import annotations
import json, ssl, threading, time
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler, ProxyHandler
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from .feeds import ProviderUnavailable

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

class PublicJSONTransport:
    HOSTS=frozenset({'data.sec.gov','api.stlouisfed.org','www.bankofcanada.ca'})
    _lock=threading.Lock()
    _last={}
    def __init__(self, *, timeout=20, max_bytes=25_000_000, attempts=3):
        if not 1<=attempts<=4 or not 0<timeout<=60 or not 1<=max_bytes<=50_000_000:raise ValueError('transport bounds')
        self.timeout=timeout;self.max_bytes=max_bytes;self.attempts=attempts
        self.opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
    def __call__(self,url,headers):
        p=urlsplit(url)
        if p.scheme!='https' or p.hostname not in self.HOSTS or p.username or p.password or p.port or p.fragment:raise ValueError('URL_DENIED')
        # One process-wide conservative SEC throttle; external multi-process quota still needed.
        for attempt in range(self.attempts):
            with self._lock:
                pause=.25-(time.monotonic()-self._last.get(p.hostname,0))
                if pause>0:time.sleep(pause)
                self._last[p.hostname]=time.monotonic()
            try:
                req=Request(url,headers=headers|{'Accept':'application/json','Accept-Encoding':'identity'},method='GET')
                with self.opener.open(req,timeout=self.timeout) as response:
                    body=response.read(self.max_bytes+1)
                    if len(body)>self.max_bytes:raise ProviderUnavailable('RESPONSE_TOO_LARGE')
                    result=json.loads(body)
                    if not isinstance(result,dict):raise ProviderUnavailable('INVALID_PROVIDER_JSON')
                    return result
            except HTTPError as exc:
                status=exc.code;exc.close()
                if status not in (429,500,502,503,504) or attempt+1==self.attempts:raise ProviderUnavailable(f'HTTP_{status}') from None
            except (URLError,TimeoutError,OSError):
                if attempt+1==self.attempts:raise ProviderUnavailable('NETWORK_UNAVAILABLE') from None
            except (UnicodeError,json.JSONDecodeError):raise ProviderUnavailable('INVALID_PROVIDER_JSON') from None
            time.sleep(min(2**attempt,4))
