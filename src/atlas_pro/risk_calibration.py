"""Predeclared developer risk diagnostic on daily market returns, never trade authority.
Only past observations enter each forecast. Archive revisions mean this is not PIT.
"""
from __future__ import annotations
import argparse,csv,hashlib,io,json,math,re,statistics,zipfile
from datetime import date
from pathlib import Path
from statistics import NormalDist
from .portfolio import tail_loss

SOURCE='https://mba.tuck.dartmouth.edu/pages/Faculty/ken.french/ftp_202412/F-F_Research_Data_Factors_daily_CSV.zip'
START='2004-01-02';END='2024-12-31';WINDOW=252
ALPHAS=(.95,.99);DECAY=.94


def parse_archive(raw):
    if not isinstance(raw,bytes) or not 1<=len(raw)<=2_000_000:raise ValueError('archive size')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        members=z.infolist()
        if len(members)!=1 or not members[0].filename.lower().endswith('.csv') or not 0<members[0].file_size<=8_000_000:raise ValueError('archive shape')
        data=z.read(members[0]).decode('utf-8-sig')
    header=False;rows=[]
    for r in csv.reader(io.StringIO(data)):
        r=[x.strip() for x in r]
        if r==['','Mkt-RF','SMB','HML','RF']:
            if header:raise ValueError('duplicate factor header')
            header=True;continue
        if not header or not r or not re.fullmatch(r'\d{8}',r[0]):continue
        if len(r)!=5:raise ValueError('daily row shape')
        d=date.fromisoformat(r[0][:4]+'-'+r[0][4:6]+'-'+r[0][6:]).isoformat()
        if not START<=d<=END:continue
        a,b=float(r[1]),float(r[4])
        if any(not math.isfinite(x) or x in (-99.99,-999.) for x in (a,b)):raise ValueError('missing factor value')
        market=(a+b)/100
        if not -1<market<1:raise ValueError('market return out of bounds')
        rows.append((d,market))
    if not header:raise ValueError('factor header not found')
    return rows


def validate_rows(rows):
    if len(rows)<WINDOW+252 or len(rows)>10000:raise ValueError('sample bounds')
    dates=[];returns=[]
    for d,r in rows:
        if not isinstance(d,str) or date.fromisoformat(d).isoformat()!=d or type(r) not in (int,float) or not math.isfinite(r) or not -1<r<1:raise ValueError('invalid daily observation')
        dates.append(d);returns.append(float(r))
    if dates!=sorted(set(dates)):raise ValueError('duplicate/unordered dates')
    import exchange_calendars as xc
    calendar=xc.get_calendar('XNYS',start=dates[0],end=dates[-1])
    sessions=[d.date().isoformat() for d in calendar.sessions_in_range(dates[0],dates[-1])]
    if dates!=sessions:raise ValueError('incomplete XNYS sessions')
    return dates,returns


def _ll(n0,n1,p):
    return (n1*math.log(p) if n1 else 0.)+(n0*math.log1p(-p) if n0 else 0.)


def coverage(hits,alpha):
    if len(hits)<252 or any(type(x) is not bool for x in hits) or not 0<alpha<1:raise ValueError('coverage inputs')
    n=len(hits);k=sum(hits);p=1-alpha
    uc=max(0.,2*(_ll(n-k,k,k/n)-_ll(n-k,k,p)))
    pairs=[[0,0],[0,0]]
    for a,b in zip(hits,hits[1:]):pairs[int(a)][int(b)]+=1
    r0=sum(pairs[0]);r1=sum(pairs[1]);ind=cc=None
    if r0 and r1:
        n00,n01=pairs[0];n10,n11=pairs[1]
        pooled=(n01+n11)/(r0+r1)
        ind=max(0.,2*(_ll(n00,n01,n01/r0)+_ll(n10,n11,n11/r1)-_ll(n00+n10,n01+n11,pooled)))
        cc=uc+ind
    return {'observations':n,'breaches':k,'breach_rate':k/n,'expected_breaches':n*p,'kupiec_lr':uc,'kupiec_p':math.erfc(math.sqrt(uc/2)),'transition_counts':pairs,'independence_lr':ind,'independence_p':None if ind is None else math.erfc(math.sqrt(ind/2)),'conditional_coverage_p':None if cc is None else math.exp(-cc/2)}


def forecasts(rows):
    dates,rs=validate_rows(rows);norm=NormalDist();variance=statistics.mean(x*x for x in rs[:WINDOW]);out=[]
    for i in range(WINDOW,len(rs)):
        past=rs[i-WINDOW:i];losses=sorted(-v for v in past);loss=-rs[i];sigma=math.sqrt(variance)
        for a in ALPHAS:
            z=norm.inv_cdf(a)
            for model,var,es in [('historical_252',losses[math.ceil(a*WINDOW)-1],tail_loss(past,a)),('ewma_normal_094',z*sigma,norm.pdf(z)*sigma/(1-a))]:
                out.append({'date':dates[i],'through':dates[i-1],'model':model,'alpha':a,'loss':loss,'var':var,'es':es,'breach':loss>var})
        variance=DECAY*variance+(1-DECAY)*rs[i]**2
    return out


def summarize(records):
    models={}
    for m in ('historical_252','ewma_normal_094'):
        models[m]={}
        for a in ALPHAS:
            seq=[r for r in records if r['model']==m and r['alpha']==a];hits=[r for r in seq if r['breach']]
            result=coverage([r['breach'] for r in seq],a)
            result['quantile_loss_mean']=statistics.mean((a-(r['loss']<r['var']))*(r['loss']-r['var']) for r in seq)
            result['breach_mean_loss']=statistics.mean(r['loss'] for r in hits) if hits else None
            result['breach_mean_forecast_es']=statistics.mean(r['es'] for r in hits) if hits else None
            result['crisis_windows']={}
            for name,start,end in [('GFC','2007-01-01','2009-12-31'),('COVID','2020-01-01','2020-12-31'),('2022','2022-01-01','2022-12-31')]:
                group=[r for r in seq if start<=r['date']<=end]
                result['crisis_windows'][name]={'observations':len(group),'breaches':sum(r['breach'] for r in group)}
            models[m][str(a)]=result
    return {'status':'DEVELOPER_RISK_CALIBRATION_ONLY','forecasts_per_model_confidence':len(records)//4,'first_forecast':records[0]['date'],'last_forecast':records[-1]['date'],'models':models,'l6_certified':False,'promotion_allowed':False,'can_trade':False,'limitations':['archival reconstructed research returns, not historical PIT vintages','aggregate market portfolio, not user holdings or executable prices','conditional coverage is diagnostic; ties, parameter estimation and dependence matter','breach severity comparison is descriptive, not a formal ES calibration test','no strategy return, margin model, trading authorization or alpha claim']}


def evaluate_archive(raw):
    rows=parse_archive(raw)
    if not rows or rows[0][0]!=START or rows[-1][0]!=END:raise ValueError('archive window incomplete')
    return summarize(forecasts(rows))|{'source':SOURCE,'archive_sha256':hashlib.sha256(raw).hexdigest(),'observations':len(rows),'window':WINDOW,'decay':DECAY}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--zip',type=Path,required=True);p.add_argument('--confirm-research-rights',action='store_true');a=p.parse_args()
    if not a.confirm_research_rights:raise PermissionError('explicit personal research rights confirmation required')
    with a.zip.open('rb') as f:raw=f.read(2_000_001)
    print(json.dumps(evaluate_archive(raw),indent=2,allow_nan=False));return 0
if __name__=='__main__':raise SystemExit(main())
