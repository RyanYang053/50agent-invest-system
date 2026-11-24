"""Current macro evidence ingestion with explicit series-specific rights.
ALFRED's date-level vintage does not establish intraday historical availability.
No old date backfill into the point-in-time index from today's response.
"""
from datetime import datetime,timezone,date
from .ledger import iso,digest
from .research import num

# Only these defined series; rights must still be checked for each provider series.
FRED_SERIES={'DFF':'Effective federal funds rate, percent','DGS10':'US 10-year Treasury yield, percent',
 'CPIAUCSL':'US CPI index','UNRATE':'US unemployment rate, percent','GDPC1':'US real GDP, billions of chained dollars'}

def ingest_macro(client,ledger,index,*,series,policy,received_at=None,recent=6):
    if series not in FRED_SERIES and series!='FXUSDCAD':raise ValueError('unsupported macro series')
    if not 1<=recent<=30 or policy.get('series_id')!=series or any(policy.get(k) is not True for k in ('permitted_for_personal_analysis','allow_local_retention','allow_rag_indexing','cloud_allowed')) or not policy.get('license_id'):
        raise PermissionError('explicit series-specific cloud/retention rights required')
    now=iso(received_at) if received_at else datetime.now(timezone.utc)
    if series=='FXUSDCAD':
        source='boc_valet';uri='https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json';raw=client.boc_observations(series,recent=recent)
        rows=[(r['d'],r[series]['v']) for r in raw['observations'] if r.get(series,{}).get('v') not in (None,'')];label='CAD per USD'
    else:
        source='alfred';uri=f'https://fred.stlouisfed.org/series/{series}';raw=client.alfred_vintage(series,now.date().isoformat(),observation_start=str(now.date().replace(year=now.year-3,day=1)))
        if raw.get('realtime_start')!=now.date().isoformat() or raw.get('realtime_end')!=now.date().isoformat():raise ValueError('unexpected vintage')
        rows=[(r['date'],r['value']) for r in raw['observations'] if r.get('value') not in (None,'.','')];label=FRED_SERIES[series]
    receipt=iso(received_at) if received_at else datetime.now(timezone.utc);seen=set();ids=[]
    for day,value in sorted(rows)[-recent:]:
        obs=date.fromisoformat(day)
        if obs>receipt.date() or day in seen:raise ValueError('future or duplicate macro observation')
        seen.add(day);val=num(value)
        payload={'series_id':series,'observation_date':day,'value':val,'unit_description':label,'retrieved_at':receipt.isoformat(),'vintage_date':now.date().isoformat(),'availability':'actual receipt, not historic intraday release'}
        rid=digest(payload);ledger.add_evidence({'record_id':rid,'source_id':source,'document_id':series+':'+day,'security_id':'MACRO:US','observed_at':day+'T00:00:00Z','published_at':receipt.isoformat(),'available_at':receipt.isoformat(),'payload':payload,'data_class':'public','license_id':policy['license_id']},policy=policy)
        index.add({'doc_id':rid,'source_id':source,'source_uri':uri,'security_id':'MACRO:US','available_at':receipt.isoformat(),'scope':'public','license_id':policy['license_id'],'content':f'{series}: {label}; observation {day}; value {val}; retrieved {receipt.isoformat()}. Current vintage, no historic release-time claim.'},policy)
        ids.append(rid)
    return {'status':'MACRO_INDEXED' if ids else 'NO_DATA','series_id':series,'evidence_ids':ids,'can_trade':False}
