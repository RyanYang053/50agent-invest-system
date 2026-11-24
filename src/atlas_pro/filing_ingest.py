"""Bounded SEC primary filing text retrieval for current research only.
SEC Company Facts remains the authoritative numerical parser. HTML extraction
preserves row/cell separators but does not certify complex financial tables.
"""
from __future__ import annotations
import hashlib,re,ssl,threading,time
from html.parser import HTMLParser
from datetime import datetime,timezone
from urllib.request import Request,build_opener,HTTPSHandler,ProxyHandler
from urllib.error import HTTPError,URLError
from .transport import NoRedirect
from .ledger import digest,iso
from .documents import index_document
from .feeds import ProviderUnavailable


class FilingText(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.skip=[];self.parts=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        hidden=tag in ('script','style','head','ix:hidden') or 'hidden' in attrs or re.search(r'display\s*:\s*none',attrs.get('style','') or '',re.I)
        if hidden:self.skip.append(tag)
        if not self.skip and tag in ('p','div','tr','br','li','h1','h2','h3','h4'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if self.skip:
            if tag==self.skip[-1]:self.skip.pop()
            return
        if tag in ('td','th'):self.parts.append(' | ')
        if tag in ('p','div','tr','li','h1','h2','h3','h4'):self.parts.append('\n')
    def handle_data(self,data):
        if not self.skip:self.parts.append(re.sub(r'\s+',' ',data))
    def text(self):return '\n'.join(line.strip() for line in ''.join(self.parts).splitlines() if line.strip())


class SECArchiveTransport:
    _lock=threading.Lock();_last=0.
    def __init__(self,user_agent,*,timeout=20,max_bytes=20_000_000):
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',user_agent.split()[-1] if user_agent else ''):raise ValueError('SEC contact identity required')
        if not 1<=timeout<=60 or not 1<=max_bytes<=25_000_000:raise ValueError('transport bounds')
        self.ua=user_agent;self.timeout=timeout;self.max_bytes=max_bytes;self.opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
    def __call__(self,cik,accession,filename):
        url=filing_uri(cik,accession,filename)
        with self._lock:
            pause=.5-(time.monotonic()-type(self)._last)
            if pause>0:time.sleep(pause)
            type(self)._last=time.monotonic()
        try:
            with self.opener.open(Request(url,headers={'User-Agent':self.ua,'Accept':'text/html','Accept-Encoding':'identity'},method='GET'),timeout=self.timeout) as r:
                data=r.read(self.max_bytes+1)
                if len(data)>self.max_bytes:raise ProviderUnavailable('FILING_TOO_LARGE')
                return data
        except HTTPError as e:
            code=e.code;e.close();raise ProviderUnavailable(f'SEC_ARCHIVE_HTTP_{code}') from None
        except (URLError,OSError,TimeoutError):raise ProviderUnavailable('SEC_ARCHIVE_NETWORK_UNAVAILABLE') from None


def filing_uri(cik,accession,filename):
    if type(cik) is not int or not 0<cik<10**10 or not re.fullmatch(r'\d{10}-\d{2}-\d{6}',accession) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,180}\.html?',filename,re.I) or '..' in filename:raise ValueError('invalid filing locator')
    return f'https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace("-","")}/{filename}'


def ingest_recent_filings(submissions,*,cik,ledger,index,policy,transport,received_at=None,limit=3):
    """Fetch latest 10-K/Q/8-K primary docs; no historical availability inference.
    Every observed copy has its own immutable provenance. Explicit permissions
    required for public/cloud index; local-only sources stay local.
    """
    if int(submissions['cik'])!=cik or type(limit) is not int or not 1<=limit<=5:raise ValueError('filing identity/bounds')
    if policy.get('license_id')!='SEC_PUBLIC' or any(policy.get(k) is not True for k in ('permitted_for_personal_analysis','allow_local_retention','allow_rag_indexing','cloud_allowed')):raise PermissionError('filing indexing rights not approved')
    cols=submissions['filings']['recent'];keys=('accessionNumber','acceptanceDateTime','form','primaryDocument')
    if len({len(cols[k]) for k in keys})!=1:raise ValueError('submission columns mismatch')
    cutoff=iso(received_at) if received_at else datetime.now(timezone.utc)
    chosen=[]
    for acc,stamp,form,filename in zip(*(cols[k] for k in keys)):
        if form not in ('10-K','10-Q','8-K','10-K/A','10-Q/A','8-K/A'):continue
        try:
            accepted=iso(stamp);uri=filing_uri(cik,acc,filename)
            if accepted<=cutoff:chosen.append((accepted,acc,form,filename,uri))
        except (ValueError,TypeError,AttributeError):continue
    chosen.sort(reverse=True);result=[]
    for accepted,acc,form,filename,uri in chosen[:limit]:
        raw=transport(cik,acc,filename);receipt=iso(received_at) if received_at else datetime.now(timezone.utc)
        if not isinstance(raw,bytes) or not 1<=len(raw)<=25_000_000:raise ValueError('invalid filing bytes')
        parser=FilingText();parser.feed(raw.decode('utf-8',errors='replace'));parser.close();body=parser.text()
        if len(body)<200 or len(body)>5_000_000:raise ValueError('filing text unavailable/too large')
        payload={'cik':cik,'accession':acc,'form':form,'uri':uri,'raw_sha256':hashlib.sha256(raw).hexdigest(),'text_sha256':hashlib.sha256(body.encode()).hexdigest(),'retrieved_at':receipt.isoformat(),'parser':'atlas_html_text_v1'}
        rid=digest(payload)
        ledger.add_evidence({'record_id':rid,'source_id':'sec_filing_text','document_id':acc,'security_id':f'CIK:{cik}','observed_at':accepted.isoformat(),'published_at':accepted.isoformat(),'available_at':receipt.isoformat(),'payload':payload,'data_class':'public','license_id':'SEC_PUBLIC'},policy=policy)
        doc={'doc_id':rid,'source_id':'sec_filing_text','source_uri':uri,'security_id':f'CIK:{cik}','available_at':receipt.isoformat(),'scope':'public','license_id':'SEC_PUBLIC','content':body}
        indexed=index_document(index,doc,policy)
        result.append({'record_id':rid,'accession':acc,'form':form,'chunks':len(indexed['chunk_ids']),'available_at':receipt.isoformat()})
    return {'status':'CURRENT_FILINGS_INDEXED','filings':result,'can_trade':False,'limitations':['primary filing only; exhibits, XBRL context and tables not validated','current receipt timestamps, no historical backfill claim']}
