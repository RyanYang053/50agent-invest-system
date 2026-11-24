"""BLS public monthly observations; current-receipt evidence, not historic vintages."""
from datetime import datetime, timezone, date
from calendar import monthrange
from .ledger import iso,digest
from .research import num

SERIES={
    "LNS14000000":"US civilian unemployment rate, seasonally adjusted, percent",
    "CUSR0000SA0":"US CPI-U all items, seasonally adjusted, index 1982-84=100",
}
SOURCE="bls_public"
SECURITY="MACRO:US"
ROLE="A063"

def ingest_bls(client,ledger,index,*,series,policy,recent=12,clock=lambda:datetime.now(timezone.utc)):
    if series not in SERIES or type(recent) is not int or not 1<=recent<=24:
        raise ValueError("unsupported BLS series or observation limit")
    if policy.get("series_id")!=series or not policy.get("license_id") or any(policy.get(k) is not True for k in ("permitted_for_personal_analysis","allow_local_retention","allow_rag_indexing","cloud_allowed")):
        raise PermissionError("explicit series-specific rights required")
    raw=client.bls_series(series)
    now=iso(clock().isoformat()); stamp=now.isoformat()
    if raw.get("status")!="REQUEST_SUCCEEDED":raise ValueError("BLS request unsuccessful")
    # Reject provider warnings, including incomplete results and quota errors.
    if raw.get("message") not in ([],None):raise ValueError("BLS returned warning")
    items=raw["Results"]["series"]
    if len(items)!=1 or items[0]["seriesID"]!=series:raise ValueError("BLS series mismatch")
    data=items[0]["data"]
    if not isinstance(data,list) or len(data)>100:raise ValueError("BLS row bounds")
    rows={}; raw_hash=digest(raw)
    for r in data:
        y,p=r["year"],r["period"]
        if not isinstance(y,str) or not y.isascii() or len(y)!=4 or not y.isdecimal() or not isinstance(p,str) or p not in {f"M{i:02}" for i in range(1,13)}|{"M13"}:
            raise ValueError("BLS malformed period")
        if p=="M13":continue # annual average is not a monthly observation
        year,month=int(y),int(p[1:])
        obs=date(year,month,monthrange(year,month)[1])
        if obs>now.date() or obs in rows:raise ValueError("future or duplicate BLS observation")
        val=num(r["value"])
        if val<0 or (series=="LNS14000000" and val>100) or (series=="CUSR0000SA0" and val<=0):raise ValueError("BLS invalid observation value")
        footnotes=r.get("footnotes",[])
        if not isinstance(footnotes,list) or len(footnotes)>20 or any(not isinstance(x,dict) for x in footnotes):raise ValueError("invalid footnotes")
        # Do not forward arbitrary provider strings; mark presence for verification.
        rows[obs]=(val,any(bool(x) for x in footnotes))
    ids=[]; uri=f"https://api.bls.gov/publicAPI/v2/timeseries/data/{series}"
    for obs,(val,flagged) in sorted(rows.items())[-recent:]:
        payload={"series_id":series,"observation_month":obs.strftime("%Y-%m"),"value":val,"unit_description":SERIES[series],"retrieved_at":stamp,"provider_response_hash":raw_hash,"has_footnotes":flagged,"availability":"actual receipt, latest available version, not first-release vintage"}
        rid=digest(payload)
        ledger.add_evidence({"record_id":rid,"source_id":SOURCE,"document_id":series+":"+obs.strftime("%Y-%m"),"security_id":SECURITY,"observed_at":obs.isoformat()+"T00:00:00Z","published_at":stamp,"available_at":stamp,"payload":payload,"data_class":"public","license_id":policy["license_id"]},policy=policy)
        index.add({"doc_id":rid,"source_id":SOURCE,"source_uri":uri,"security_id":SECURITY,"available_at":stamp,"scope":"public","license_id":policy["license_id"],"content":f"BLS {series}: {SERIES[series]}; month {obs:%Y-%m}; value {val}; retrieved {stamp}; footnotes present: {flagged}. Current receipt only; not a historical first release or a consensus surprise."},policy)
        ids.append(rid)
    return {"status":"BLS_INDEXED" if ids else "NO_DATA","series_id":series,"evidence_ids":ids,"can_trade":False}
