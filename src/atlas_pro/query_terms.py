"""Conservative financial lexical planning, without model or provider calls."""
from __future__ import annotations
import re
import unicodedata

STOP=frozenset('a an and are as at be by can could did do does for from had has have how i in is it of on or should that the their this to was were what when where which who will with would you your answer assume using give response question primarily shown relying details following'.split())

def terms(query):
    if not isinstance(query,str) or len(query)>4096:raise ValueError('QUERY_BOUNDS')
    raw=list(dict.fromkeys(t.casefold() for t in re.findall(r'\w+',query,flags=re.UNICODE) if len(t)>=2))
    useful=[t for t in raw if t not in STOP]
    return (useful or raw)[:32]

def _words(value):
    return ' '.join(re.findall(r'[^\W_]+',unicodedata.normalize('NFKC',value).casefold()))

def resolve_company(query, directory):
    """Unique full-name/explicit alias match only. No guesses on ambiguous names.
    Directory must be operator-provided, public and PIT-qualified in production.
    Never override an explicit security ID in a research request.
    """
    if not isinstance(query,str) or len(query)>4096 or not isinstance(directory,dict) or len(directory)>10000:raise ValueError('ENTITY_BOUNDS')
    q=' '+_words(query)+' '; matches=set()
    for security,aliases in directory.items():
        if not isinstance(security,str) or not security or not isinstance(aliases,(list,tuple)) or len(aliases)>64:raise ValueError('INVALID_DIRECTORY')
        for alias in aliases:
            if not isinstance(alias,str) or len(alias)>200:raise ValueError('INVALID_ALIAS')
            a=_words(alias)
            if len(a)>=2 and ' '+a+' ' in q:matches.add(security)
    return next(iter(matches)) if len(matches)==1 else None

def excerpt(body,query_terms,limit=1600):
    """Return a bounded contiguous source excerpt with exact character offsets.
    Select by lexical coverage, not a generated summary. No entailment claim.
    """
    if len(body)<=limit:return body,0,len(body)
    # Candidate windows around hits; prefer distinct query terms and frequency.
    if not query_terms:return body[:limit],0,limit
    pattern=re.compile(r'(?<!\w)(?:'+'|'.join(re.escape(t) for t in sorted(query_terms,key=len,reverse=True))+r')(?!\w)',re.I)
    hits=list(pattern.finditer(body))[:4096]
    if not hits:return body[:limit],0,limit
    starts={0,max(0,len(body)-limit)}
    for h in hits:
        starts.add(min(max(0,h.start()-limit//4),len(body)-limit))
    def rank(start):
        match=list(pattern.finditer(body,start,start+limit));return (len({m.group().casefold() for m in match}),len(match),-start)
    start=max(starts,key=rank)
    return body[start:start+limit],start,start+limit
