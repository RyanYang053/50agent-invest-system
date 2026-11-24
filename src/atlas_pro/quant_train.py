"""Actual sklearn cross-sectional walk-forward research, no network or broker.

Fixed feature schema and two fixed learners. Labels and features must be supplied
as qualified, versioned data. Synthetic inputs are for integration tests only.
This is not a licensed historical data vendor or an executable trading strategy.
"""
from __future__ import annotations
import math, statistics, json, argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone
from .ledger import iso, digest
from .experiments import purged_panel_folds
from .research import num
from .oss_adapters import artifact_json

MODELS = ('ridge', 'hist_gradient_boosting')


def synthetic_panel(days=100):
    """Deterministic artificial panel, deliberately not market data."""
    rows=[]
    start=datetime(2020,1,1,tzinfo=timezone.utc)
    for day in range(days):
        stamp=start+timedelta(days=day)
        for asset in range(8):
            v=math.sin(day*.17+asset*.79)
            q=math.cos(day*.11-asset*.43)
            y=.002*v+.001*q+.0002*math.sin(day+asset)
            rows.append({'id':f'synth-{day}-{asset}','security_id':f'FICTIONAL-{asset}',
                         'signal_at':stamp.isoformat(),'feature_available_at':stamp.isoformat(),
                         'label_end_at':(stamp+timedelta(days=1)).isoformat(),
                         'label_available_at':(stamp+timedelta(days=1,hours=1)).isoformat(),
                         'features':{'momentum':v,'quality':q},'label':y,
                         'feature_evidence_ids':['synthetic-fixture'],'label_evidence_ids':['synthetic-fixture']})
    return {'rows':rows,'feature_names':['momentum','quality'],'synthetic':True,
            'training_authorized':False,'dataset_version':'synthetic-v1'}


def train_panel(panel, *, min_train_dates=40, test_dates=10, embargo_seconds=0, top_k=2, include_qlib=False):
    """Train only on purged past labels. No model pickle; emit numeric predictions.

    For real data, an operator must separately verify data rights, PIT timestamps,
    universe coverage and evidence. A true flag is attestation, not authentication.
    Top-K label averages and rank IC are diagnostics, NOT backtested trading P&L.
    """
    import numpy as np
    from scipy.stats import spearmanr
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.ensemble import HistGradientBoostingRegressor
    from threadpoolctl import threadpool_limits
    import sklearn
    if set(panel)!={'rows','feature_names','synthetic','training_authorized','dataset_version'}:
        raise ValueError('unexpected panel fields')
    if type(panel['synthetic']) is not bool or type(panel['training_authorized']) is not bool or not panel['dataset_version']:
        raise ValueError('invalid panel provenance')
    if not panel['synthetic'] and panel['training_authorized'] is not True:
        raise PermissionError('training and evaluation rights required')
    names=panel['feature_names']; rows=panel['rows']
    if not isinstance(names,list) or not 1<=len(names)<=32 or any(not isinstance(n,str) or not n or len(n)>80 for n in names) or len(set(names))!=len(names):
        raise ValueError('invalid feature schema')
    if not isinstance(rows,list) or not 1<=len(rows)<=50000 or type(top_k) is not int or not 1<=top_k<=100:
        raise ValueError('panel bounds')
    fields={'id','security_id','signal_at','feature_available_at','label_end_at','label_available_at','features','label','feature_evidence_ids','label_evidence_ids'}
    by={}; split_rows=[]
    for row in rows:
        if set(row)!=fields or set(row['features'])!=set(names):raise ValueError('unexpected row fields')
        for k in ('id','security_id'):
            if not isinstance(row[k],str) or not row[k] or len(row[k])>120:raise ValueError('invalid identity')
        for k in ('feature_evidence_ids','label_evidence_ids'):
            ids=row[k]
            if not isinstance(ids,list) or not 1<=len(ids)<=100 or any(not isinstance(x,str) or not x or len(x)>128 for x in ids) or len(set(ids))!=len(ids):raise ValueError('missing evidence')
        y=num(row['label']);x=[num(row['features'][n]) for n in names]
        if y< -1 or y>10 or any(abs(v)>1e9 for v in x):raise ValueError('unqualified numeric input')
        available=iso(row['label_available_at'])
        if available<iso(row['label_end_at']):raise ValueError('label available before observation')
        # Purge to actual label availability, not merely the economic horizon.
        split_rows.append(row|{'label_end_at':available.isoformat()})
        by[row['id']]=(row,x,y)
    folds=purged_panel_folds(split_rows,min_train_dates=min_train_dates,test_dates=test_dates,embargo_seconds=embargo_seconds)
    if not folds or len(folds)>100:raise ValueError('no qualifying folds or too many folds')
    if type(include_qlib) is not bool:raise ValueError('invalid Qlib option')
    names_models=MODELS+('qlib_ridge',) if include_qlib else MODELS
    results={m:[] for m in names_models};seen=set();engine_receipts=[]
    with threadpool_limits(limits=1):
        for fold in folds:
            train,test=fold['train_ids'],fold['test_ids']
            if seen.intersection(test):raise ValueError('duplicate test rows')
            seen.update(test)
            X=np.array([by[k][1] for k in train]); Y=np.array([by[k][2] for k in train]); T=np.array([by[k][1] for k in test])
            models={'ridge':make_pipeline(StandardScaler(),Ridge(alpha=1.0)),
                    'hist_gradient_boosting':HistGradientBoostingRegressor(max_iter=50,max_leaf_nodes=15,early_stopping=False,random_state=42)}
            predictions={}
            for name,model in models.items():
                model.fit(X,Y)
                predictions[name]=model.predict(T)
            if include_qlib:
                from .qlib_engine import fit_predict
                qpred,receipt=fit_predict([by[k][0] for k in train],[{field:by[k][0][field] for field in ('id','security_id','signal_at','features')} for k in test],names)
                predictions['qlib_ridge']=qpred;engine_receipts.append(receipt)
            for name,preds in predictions.items():
                if len(preds)!=len(test):raise ValueError('prediction coverage mismatch')
                for k,p in zip(test,preds):
                    r,x,y=by[k]
                    prediction=num(p)
                    results[name].append({'id':k,'security_id':r['security_id'],'signal_at':r['signal_at'],'label_end_at':r['label_end_at'],'prediction':prediction,'actual_label':y,'feature_evidence_ids':r['feature_evidence_ids'],'label_evidence_ids':r['label_evidence_ids'],'train_hash':digest(train),'train_max_label_end_at':max(iso(by[j][0]['label_end_at']) for j in train).isoformat(),'train_max_label_available_at':max(iso(by[j][0]['label_available_at']) for j in train).isoformat()})
        reports={}
        for name,ps in results.items():
            groups={}
            for p in ps:groups.setdefault(iso(p['signal_at']),[]).append(p)
            ics=[];excess=[]
            for stamp,g in sorted(groups.items()):
                if len(g)<=top_k:raise ValueError('not enough cross-sectional candidates')
                # Constant predictions/labels have no defined rank IC.
                a=[p['prediction'] for p in g];b=[p['actual_label'] for p in g]
                if len(set(a))>1 and len(set(b))>1:
                    ic=float(spearmanr(a,b).statistic)
                    if math.isfinite(ic):ics.append(ic)
                selected=sorted(g,key=lambda p:(-p['prediction'],p['security_id']))[:top_k]
                excess.append(statistics.mean(p['actual_label'] for p in selected)-statistics.mean(b))
            reports[name]={'n_predictions':len(ps),'n_dates':len(groups),'n_defined_rank_ic':len(ics),'mean_rank_ic':statistics.mean(ics) if ics else None,
                           'mae':statistics.mean(abs(p['prediction']-p['actual_label']) for p in ps),
                           'mean_top_k_label_minus_universe':statistics.mean(excess),'predictions':ps}
    return {'status':'SYNTHETIC_RESEARCH_ONLY' if panel['synthetic'] else 'UNVERIFIED_RESEARCH_RESULT',
            'data_sha256':digest(panel),'split_sha256':digest(folds),'dataset_version':panel['dataset_version'],'sklearn_version':sklearn.__version__,
            'synthetic':panel['synthetic'],'folds':len(folds),'models':reports,'external_engine_receipts':engine_receipts,'can_trade':False,'promotion_allowed':False,
            'limitations':['no execution timing or cost accounting','label diagnostics not portfolio returns','no strategy selection from these holdout results without independent prospective validation','data rights and PIT provenance externally attested, not independently verified by trainer']}


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True);g.add_argument('--demo',action='store_true');g.add_argument('--panel',type=Path);p.add_argument('--sha256');p.add_argument('--min-train-dates',type=int,default=40);p.add_argument('--test-dates',type=int,default=10);p.add_argument('--embargo-seconds',type=int,default=0);p.add_argument('--top-k',type=int,default=2);p.add_argument('--qlib',action='store_true')
    a=p.parse_args()
    if a.panel and not a.sha256:p.error('--sha256 is required for panel')
    data=synthetic_panel() if a.demo else artifact_json(a.panel,a.sha256)
    report=train_panel(data,min_train_dates=a.min_train_dates,test_dates=a.test_dates,embargo_seconds=a.embargo_seconds,top_k=a.top_k,include_qlib=a.qlib)
    print(json.dumps(report,allow_nan=False,separators=(',',':')))
    return 0
if __name__=='__main__':raise SystemExit(main())
