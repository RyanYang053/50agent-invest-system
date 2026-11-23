"""Append-only prospective forecasts, outcome scoring and non-deployable lessons."""
from __future__ import annotations
import json, sqlite3, math
from contextlib import closing
from .ledger import iso, digest, canonical
from .research import num

class ForecastJournal:
    def __init__(self,path):
        self.path=str(path)
        with closing(sqlite3.connect(self.path)) as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS predictions(id TEXT PRIMARY KEY,payload TEXT NOT NULL,created TEXT NOT NULL,due TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS outcomes(id TEXT PRIMARY KEY,payload TEXT NOT NULL,observed TEXT NOT NULL,FOREIGN KEY(id) REFERENCES predictions(id));''')
    def record(self, *, security_id, created_at, due_at, probability, threshold, baseline_probability, evidence_ids, model_version, strategy_version):
        start,end=iso(created_at),iso(due_at); p,b,t=map(num,(probability,baseline_probability,threshold))
        if end<=start or not 0<=p<=1 or not 0<=b<=1 or t<=-1:raise ValueError('invalid prospective forecast')
        if not security_id or not model_version or not strategy_version or not evidence_ids:raise ValueError('missing forecast provenance')
        row={'security_id':security_id,'created_at':start.isoformat(),'due_at':end.isoformat(),'probability':p,'threshold':t,'baseline_probability':b,'evidence_ids':list(evidence_ids),'model_version':model_version,'strategy_version':strategy_version,'event':'terminal_total_return_at_least_threshold'}
        rid=digest(row)
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute('INSERT OR IGNORE INTO predictions VALUES(?,?,?,?)',(rid,canonical(row),row['created_at'],row['due_at']))
        return rid
    def due(self,at):
        now=iso(at).isoformat()
        with closing(sqlite3.connect(self.path)) as c:
            return [r[0] for r in c.execute('SELECT p.id FROM predictions p LEFT JOIN outcomes o ON p.id=o.id WHERE o.id IS NULL AND p.due<=? ORDER BY p.due,p.id',(now,))]
    def resolve(self,rid,*,terminal_total_return,benchmark_total_return,observed_at,measurement_at,evidence_ids):
        actual,bench=map(num,(terminal_total_return,benchmark_total_return)); observed,measurement=iso(observed_at),iso(measurement_at)
        if min(actual,bench)<-1 or not evidence_ids:raise ValueError('invalid outcome')
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute('BEGIN IMMEDIATE')
            raw=c.execute('SELECT payload FROM predictions WHERE id=?',(rid,)).fetchone()
            if not raw:raise KeyError('unknown forecast')
            p=json.loads(raw[0]); due=iso(p['due_at'])
            # Caller must pick a market session-adjusted due date when creating forecasts.
            if measurement!=due or observed<due:raise ValueError('wrong or premature outcome horizon')
            row={'observed_at':observed.isoformat(),'measurement_at':measurement.isoformat(),'actual':actual,'benchmark':bench,'hit':int(actual>=p['threshold']),'evidence_ids':list(evidence_ids)}
            prior=c.execute('SELECT payload FROM outcomes WHERE id=?',(rid,)).fetchone()
            if prior:
                if prior[0]!=canonical(row):raise ValueError('outcome immutable')
                return 'DUPLICATE'
            c.execute('INSERT INTO outcomes VALUES(?,?,?)',(rid,canonical(row),observed.isoformat()))
            return 'RESOLVED'
    def report(self, *, at, strategy_version=None, model_version=None):
        stamp=iso(at).isoformat()
        with closing(sqlite3.connect(self.path)) as c:
            rows=[(json.loads(p),json.loads(o)) for p,o in c.execute('SELECT p.payload,o.payload FROM predictions p JOIN outcomes o ON p.id=o.id WHERE o.observed<=?',(stamp,))]
        if strategy_version:rows=[x for x in rows if x[0]['strategy_version']==strategy_version]
        if model_version:rows=[x for x in rows if x[0]['model_version']==model_version]
        n=len(rows)
        if not n:return {'status':'INSUFFICIENT_OUTCOMES','n':0,'promotion_allowed':False}
        brier=sum((p['probability']-o['hit'])**2 for p,o in rows)/n
        baseline=sum((p['baseline_probability']-o['hit'])**2 for p,o in rows)/n
        bins=[]
        for i in range(5):
            group=[(p,o) for p,o in rows if min(4,int(p['probability']*5))==i]
            if group:bins.append({'bin':i,'n':len(group),'mean_predicted':sum(p['probability'] for p,o in group)/len(group),'observed_frequency':sum(o['hit'] for p,o in group)/len(group)})
        return {'status':'REVIEW_CANDIDATE' if n>=100 else 'INSUFFICIENT_OUTCOMES','n':n,'brier':brier,'baseline_brier':baseline,'mean_excess':sum(o['actual']-o['benchmark'] for p,o in rows)/n,'calibration_bins':bins,
            'proposed_research':['inspect overconfidence, missed events, and regime effects'] if brier>=baseline else ['test whether skill persists in locked prospective data'],
            'promotion_allowed':False,'limitations':['overlapping observations not independent; no statistical significance claim','results generate proposals only']}
