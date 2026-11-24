"""Prospective, broker-free shadow investment ledger.

The frozen target is a hypothetical research experiment, NOT a conversion of a
WAIT decision into an order. No broker, API keys, order APIs or model tools.
Operator attestation and the local filesystem boundary remain trusted. Return
observations must be imported under a valid data licence by a separate operator.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import re
import sqlite3
from .committee import STAGES
from .ledger import canonical, digest, iso
from .performance import paired_performance
from .research import num
from .portfolio import portfolio_review
from .promotion import compare_challenger


def _now():
    return datetime.now(timezone.utc).isoformat()


def _closes(anchor, end):
    import exchange_calendars as xc
    cal=xc.get_calendar('XNYS')
    if not cal.is_session(anchor) or not cal.is_session(end):
        raise ValueError('anchor and end must be exchange sessions')
    dates=cal.sessions_in_range(anchor,end)
    if not 2<=len(dates)<=367:raise ValueError('invalid experiment horizon')
    return [cal.session_close(d).to_pydatetime().astimezone(timezone.utc).isoformat() for d in dates]


class ShadowJournal:
    """One immutable buy-and-hold total-return experiment; no execution model.

    Session closes, weights, benchmark, source bindings and the research packet
    are frozen before the anchor close. Costs are an explicit inception haircut;
    cash earns zero. Returns use a drifting, dividend-reinvested notional, not
    actual shares, fills, commissions or tax lots. No retrospective editing.
    """
    def __init__(self,path,*,clock=_now):
        self.path=str(path);self.clock=clock
        with self._db() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS shadow_plans(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS shadow_days(plan_id TEXT NOT NULL,step INTEGER NOT NULL,payload TEXT NOT NULL,sha TEXT NOT NULL,
            PRIMARY KEY(plan_id,step),FOREIGN KEY(plan_id) REFERENCES shadow_plans(id));''')
    @contextmanager
    def _db(self):
        c=sqlite3.connect(self.path,timeout=15,isolation_level=None)
        c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA synchronous=FULL')
        try:
            yield c
            if c.in_transaction:c.commit()
        except Exception:
            if c.in_transaction:c.rollback()
            raise
        finally:c.close()
    def start(self,committee,run_id,*,targets,benchmark,source_bindings,anchor,end,cost_bps,operator_confirmed=False,synthetic=True,forecast=None,risk_refresh=None):
        if operator_confirmed is not True or type(synthetic) is not bool:raise PermissionError('explicit shadow experiment approval required')
        now=iso(self.clock());closes=_closes(anchor,end)
        if now>=iso(closes[0]):raise ValueError('experiment must be frozen before anchor close')
        request,stages=committee.state(run_id)
        if set(stages)!=set(STAGES) or stages['decision'].get('decision')!='WAIT':raise ValueError('complete research-only decision required')
        risk=stages['portfolio_risk'];decision=stages['decision']
        weights={k:num(v) for k,v in targets.items()}
        if not 2<=len(weights)<=101 or 'CASH' not in weights or any(not isinstance(k,str) or not k or v<0 for k,v in weights.items()) or abs(sum(weights.values())-1)>1e-8:raise ValueError('invalid shadow weights')
        if (risk.get('status')!='SHADOW_RISK_REVIEW' or risk.get('can_trade') is not False or risk.get('reasons')!=[] or risk.get('target_hash')!=digest(weights) or risk.get('risk_id')!=digest({k:v for k,v in risk.items() if k!='risk_id'}) or decision.get('risk_id')!=risk.get('risk_id')):raise ValueError('independent risk approval must match targets')
        original_risk_id=risk['risk_id']
        if risk_refresh is not None:
            if set(risk_refresh)!={'policy','snapshot','returns','clusters','stress_scenarios'}:raise ValueError('invalid risk refresh fields')
            policy=risk_refresh['policy']
            if digest(policy)!=request['policy_hash'] or policy.get('status')!='ACTIVE_APPROVED' or policy.get('owner_approval',{}).get('approved') is not True:raise ValueError('risk refresh requires same approved policy')
            risk=portfolio_review(risk_refresh['snapshot'],weights,risk_refresh['returns'],risk_refresh['clusters'],policy['limits'],at=now.isoformat(),stress_scenarios=risk_refresh['stress_scenarios'])
            if risk['status']!='SHADOW_RISK_REVIEW' or risk['limits_hash']!=stages['portfolio_risk']['limits_hash']:raise ValueError('refreshed portfolio risk blocked or limits changed')
        age=(now-iso(risk['as_of'])).total_seconds()
        if not 0<=age<=300 or iso(request['decision_at'])>now:raise ValueError('stale or future research risk')
        names={k for k,v in weights.items() if k!='CASH' and v>0}
        if not names or not isinstance(benchmark,str) or not benchmark or benchmark=='CASH':raise ValueError('benchmark and risky allocation required')
        if set(source_bindings)!=names|{benchmark}:raise ValueError('source bindings must cover exact asset and benchmark set')
        for b in source_bindings.values():
            if set(b) not in ({'source_id','license_id','data_class'},{'source_id','license_id','data_class','ticker'}) or not b['source_id'] or not b['license_id'] or b['data_class'] not in ('public','licensed'):raise ValueError('invalid local return source binding')
            if 'ticker' in b and (not isinstance(b['ticker'],str) or not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,11}',b['ticker'])):raise ValueError('invalid return ticker binding')
        bps=num(cost_bps);turnover=num(risk['metrics']['turnover'])
        if not 0<=bps<=100 or not 0<=turnover<=2+1e-8:raise ValueError('invalid experiment costs')
        if forecast is not None:
            if set(forecast)!={'probability','baseline_probability','excess_return_threshold'}:raise ValueError('invalid forecast fields')
            forecast={k:num(v) for k,v in forecast.items()}
            if not 0<=forecast['probability']<=1 or not 0<=forecast['baseline_probability']<=1:raise ValueError('invalid forecast probability')
        payload={'run_id':run_id,'decision_hash':digest(decision),'original_risk_id':original_risk_id,'risk_id':risk['risk_id'],'policy_hash':request['policy_hash'],'strategy_version':request['strategy_version'],'created_at':now.isoformat(),'closes':closes,'weights':weights,'benchmark':benchmark,'source_bindings':source_bindings,'cost_bps':bps,'inception_cost_fraction':turnover*bps/10000,'synthetic':synthetic,'can_trade':False,'mode':'SHADOW_TOTAL_RETURN_ONLY','forecast':forecast}
        pid=digest(payload)
        with self._db() as c,c:
            c.execute('INSERT OR IGNORE INTO shadow_plans VALUES(?,?)',(pid,canonical(payload)))
        return pid
    def _load(self,c,pid):
        row=c.execute('SELECT payload FROM shadow_plans WHERE id=?',(pid,)).fetchone()
        if row is None:raise KeyError('unknown shadow experiment')
        p=json.loads(row[0]);prev=pid;days=[]
        if digest(p)!=pid:raise ValueError('shadow plan integrity failure')
        for step,raw,sha in c.execute('SELECT step,payload,sha FROM shadow_days WHERE plan_id=? ORDER BY step',(pid,)):
            day=json.loads(raw)
            if step!=len(days)+1 or day.get('prev_hash')!=prev or digest(day)!=sha:raise ValueError('shadow day integrity failure')
            days.append(day);prev=sha
        return p,days,prev
    def append(self,pid,ledger,*,session_close,evidence_by_security):
        now=iso(self.clock());stamp=iso(session_close).isoformat()
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE');p,days,prev=self._load(c,pid)
            if stamp not in p['closes'][1:]:raise ValueError('not a planned session close')
            step=p['closes'].index(stamp)
            if step<=len(days):
                if days[step-1]['evidence_by_security']!=evidence_by_security:raise ValueError('shadow observation immutable')
                return {'status':'DUPLICATE','can_trade':False}
            if step!=len(days)+1 or now<iso(stamp):raise ValueError('future or missing session')
            if set(evidence_by_security)!=set(p['source_bindings']) or len(set(evidence_by_security.values()))!=len(evidence_by_security):raise ValueError('exact return evidence coverage required')
            returns={}
            for name,rid in evidence_by_security.items():
                row=ledger.resolve_ids([rid],security_id=name,decision_at=now.isoformat(),include_private=True)[0]
                binding=p['source_bindings'][name];value=row['payload']
                if any(row[k]!=v for k,v in binding.items() if k!='ticker') or ('ticker' in binding and value.get('ticker')!=binding['ticker']) or iso(row['observed_at'])!=iso(stamp) or iso(row['published_at'])<iso(stamp):raise ValueError('return source or timestamp mismatch')
                if (value.get('kind')!='daily_total_return' or value.get('security_id')!=name or value.get('currency')!='USD' or value.get('corporate_actions_verified') is not True or value.get('synthetic') is not p['synthetic'] or iso(value['from_close'])!=iso(p['closes'][step-1]) or iso(value['to_close'])!=iso(stamp)):raise ValueError('unqualified daily total return')
                r=num(value['total_return'])
                if r< -1:raise ValueError('invalid total return')
                returns[name]=r
            weights=days[-1]['ending_weights'] if days else p['weights']
            if not weights:raise ValueError('experiment insolvent; no subsequent returns')
            returns['CASH']=0.
            gross=sum(w*returns[k] for k,w in weights.items() if w>0)
            factor=1+gross
            if not math.isfinite(factor) or factor<0:raise ValueError('invalid portfolio return')
            cost=p['inception_cost_fraction'] if step==1 else 0.
            ending={k:w*(1+returns[k])/factor if w>0 else 0. for k,w in weights.items()} if factor>0 else {}
            if ending and (any(not math.isfinite(v) or v<0 for v in ending.values()) or abs(sum(ending.values())-1)>1e-8):raise ValueError('invalid ending weights')
            day={'at':stamp,'recorded_at':now.isoformat(),'net_return':(1-cost)*factor-1,'benchmark_total_return':returns[p['benchmark']],'cash_flow_adjusted':True,'net_of_costs':True,'ending_weights':ending,'evidence_ids':sorted(evidence_by_security.values()),'evidence_by_security':evidence_by_security,'prev_hash':prev,'can_trade':False}
            c.execute('INSERT INTO shadow_days VALUES(?,?,?,?)',(pid,step,canonical(day),digest(day)))
            return {'status':'RECORDED','step':step,'can_trade':False}
    def next_window(self,pid):
        with self._db() as c:
            c.execute('BEGIN');p,days,_=self._load(c,pid)
        if len(days)==len(p['closes'])-1:return None
        return {'from_close':p['closes'][len(days)],'to_close':p['closes'][len(days)+1],'source_bindings':p['source_bindings'],'synthetic':p['synthetic']}
    def report(self,pid):
        with self._db() as c:
            c.execute('BEGIN');p,days,head=self._load(c,pid)
        status='COMPLETE' if len(days)==len(p['closes'])-1 else 'IN_PROGRESS'
        performance=paired_performance(days,expected_sessions=p['closes'][1:len(days)+1]) if days else None
        forecast=p.get('forecast');assessment=None
        if forecast is not None and status=='COMPLETE':
            excess=performance['net_total_return']-performance['benchmark_total_return'];hit=int(excess>=forecast['excess_return_threshold'])
            assessment={'forecast':forecast,'realized_excess_return':excess,'hit':hit,'brier':(forecast['probability']-hit)**2,'baseline_brier':(forecast['baseline_probability']-hit)**2,'synthetic':p['synthetic'],'calibration_certified':False}
        return {'plan_id':pid,'status':status,'synthetic':p['synthetic'],'run_id':p['run_id'],'decision_hash':p['decision_hash'],'risk_id':p['risk_id'],'completed_sessions':len(days),'planned_sessions':len(p['closes'])-1,'last_hash':head,'performance':performance,'forecast':forecast,'forecast_assessment':assessment,'next_close':p['closes'][len(days)+1] if status=='IN_PROGRESS' else None,'promotion_allowed':False,'can_trade':False,'limitations':['frozen notional target, not actual fills or broker P&L','cash return assumed zero; inception cost estimate only','source authenticity, data licence and strategy validity require independent review; provider adjusted closes may be proxies','synthetic observations never establish performance']}

    def compare(self,champion_id,challenger_id,*,trial_count,max_drawdown,block_size=10,resamples=2000):
        """Compare two completed, pre-frozen shadow experiments on identical
        sessions and benchmark evidence. Output is a review proposal only.
        No release registry mutation or strategy deployment.
        """
        if champion_id==challenger_id:raise ValueError('distinct experiment IDs required')
        with self._db() as c:
            c.execute('BEGIN');a,ar,ah=self._load(c,champion_id);b,br,bh=self._load(c,challenger_id)
        if a['synthetic'] is not False or b['synthetic'] is not False:raise ValueError('synthetic plans cannot qualify a strategy')
        if any(a[k]!=b[k] for k in ('closes','policy_hash','benchmark','cost_bps')) or a['strategy_version']==b['strategy_version']:
            raise ValueError('comparison requires matching calendar, policy, costs and benchmark; distinct strategy versions')
        if len(ar)!=len(br) or len(ar)!=len(a['closes'])-1:raise ValueError('incomplete prospective comparison')
        for key in set(a['source_bindings'])&set(b['source_bindings']):
            if a['source_bindings'][key]!=b['source_bindings'][key]:raise ValueError('different data source bindings')
        for x,y in zip(ar,br):
            bench=a['benchmark']
            if x['at']!=y['at'] or x['benchmark_total_return']!=y['benchmark_total_return'] or x['evidence_by_security'][bench]!=y['evidence_by_security'][bench]:raise ValueError('same benchmark evidence version required')
        ids=a['closes'][1:]
        def rows(rs):return [x|{'id':x['at'],'synthetic':False} for x in rs]
        result=compare_challenger(rows(ar),rows(br),locked_ids=ids,trial_count=trial_count,block_size=block_size,resamples=resamples,max_drawdown=max_drawdown)
        return result|{'champion_plan_id':champion_id,'challenger_plan_id':challenger_id,'champion_journal_hash':ah,'challenger_journal_hash':bh,'requires_independent_data_qualification':True,'promotion_allowed':False,'can_trade':False}
