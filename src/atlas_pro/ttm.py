"""PIT US-GAAP trailing-twelve-month fiscal bridge.
Do not sum cumulative quarterly cash-flow facts. TTM = prior full fiscal year
+ current fiscal YTD - comparable prior fiscal YTD. No invented missing values.
Not an EdgarTools parser; designed to accept Atlas's normalized SEC facts.
"""
from __future__ import annotations
from datetime import date,timedelta
from .ledger import iso
from .research import TAGS,FLOWS,num


def ttm_snapshot(rows,*,at,max_age_days=180):
    now=iso(at); rows=[r for r in rows if iso(r['available_at'])<=now]
    if not rows:return None
    ciks={r['cik'] for r in rows}
    if len(ciks)!=1:raise ValueError('mixed issuers')
    # Validate the basic period, unit and tag contracts rather than guessing.
    for r in rows:
        if r['field'] not in TAGS or r['tag'] not in TAGS[r['field']] or r.get('unit')!='USD' or date.fromisoformat(r['end'])>now.date() or iso(r['published_at'])>iso(r['available_at']):raise ValueError('invalid fact identity/time/unit')
        num(r['value'])
        if r['field'] in FLOWS and (not r.get('start') or date.fromisoformat(r['start'])>=date.fromisoformat(r['end'])):raise ValueError('invalid flow period')
    revenues=[r for r in rows if r['field']=='revenue'];ends=sorted({date.fromisoformat(r['end']) for r in revenues},reverse=True)
    if not ends:return None
    end=ends[0]
    if not 0<=(now.date()-end).days<=max_age_days:return None
    def select(field,start,end,tag):
        possible=[r for r in rows if r['field']==field and r.get('start')==(start.isoformat() if start else None) and r['end']==end.isoformat() and r['tag']==tag]
        if not possible:return None
        newest=max((iso(r['published_at']),iso(r['available_at'])) for r in possible);ties=[r for r in possible if (iso(r['published_at']),iso(r['available_at']))==newest]
        if len({num(r['value']) for r in ties})!=1:return None
        return sorted(ties,key=lambda r:r['accession'])[0]
    def annual_anchors(e):
        out=set()
        for r in revenues:
            st,en=date.fromisoformat(r['start']),date.fromisoformat(r['end'])
            if en<=e and 330<=(en-st).days<=380:out.add((st,en))
        return sorted(out,key=lambda x:(x[1],x[0]),reverse=True)
    def flow(field,e):
        anchors=annual_anchors(e)
        if not anchors:return None
        fy_start,fy_end=anchors[0]
        if len({x[0] for x in anchors if x[1]==fy_end})!=1:return None
        for tag in TAGS[field]:
            full=select(field,fy_start,fy_end,tag)
            if not full:continue
            if e==fy_end:return num(full['value']),{'fy':full}
            ytd_start=fy_end+timedelta(days=1);span=(e-ytd_start).days
            if not 70<=span<=300:continue
            current=select(field,ytd_start,e,tag)
            if not current:continue
            # Match a unique comparative fiscal YTD of the same tag and duration,
            # not an arbitrary previous calendar quarter or a different taxonomy tag.
            candidates={date.fromisoformat(r['end']) for r in rows if r['field']==field and r['tag']==tag and r['start']==fy_start.isoformat() and 350<=(e-date.fromisoformat(r['end'])).days<=380 and abs((date.fromisoformat(r['end'])-fy_start).days-span)<=7 and date.fromisoformat(r['end'])<fy_end}
            if len(candidates)!=1:continue
            previous=select(field,fy_start,next(iter(candidates)),tag)
            if previous:return num(full['value'])+num(current['value'])-num(previous['value']),{'fy':full,'current_ytd':current,'prior_ytd':previous}
        return None
    metrics={};sources={};derivations={}
    for field in FLOWS:
        v=flow(field,end)
        if not v:return None
        metrics[field],parts=v
        for k,r in parts.items():sources[field+':'+k]=r
        derivations[field]={'operation':'FY' if len(parts)==1 else 'FY_PLUS_CURRENT_YTD_MINUS_PRIOR_YTD','parts':list(parts)}
    previous_ends=[e for e in ends[1:] if 350<=(end-e).days<=380]
    # Fiscal-year comparable period must be unique. Missing growth blocks screening.
    if len(previous_ends)!=1:return None
    prev=flow('revenue',previous_ends[0])
    if not prev or prev[0]<=0 or metrics['revenue']<=0:return None
    metrics['revenue_growth']=metrics['revenue']/prev[0]-1
    for k,r in prev[1].items():sources['prior_ttm_revenue:'+k]=r
    for field in set(TAGS)-FLOWS:
        r=next((x for tag in TAGS[field] if (x:=select(field,None,end,tag))),None)
        if r is None:return None
        metrics[field]=num(r['value']);sources[field]=r
    return {'cik':next(iter(ciks)),'period_end':end.isoformat(),'metrics':metrics,'sources':sources,'derivations':derivations,'as_of':now.isoformat(),'basis':'ttm_us_gaap_usd_fiscal_bridge'}
