"""Explicit job catalog for all 50 logical roles, not a model certification.
Public model tasks use fixed queries and public evidence only. Local jobs never
call a model or broker. A missing input/certificate is a visible blocked job.
"""
from __future__ import annotations
import math,re,sqlite3,json
from contextlib import closing
from .ledger import digest,iso
from .research import dcf,reverse_dcf,scenario_grid,annual_snapshot,sec_annual_facts,num
from .ttm import ttm_snapshot
from .pipeline import market_evidence_matches
from .account_risk import review_accounts
from .portfolio import tail_loss
from .experiments import purged_panel_folds
from .skill_contracts import validate_catalog,task_id,contract

# Task IDs version the prompt contract. Do not reuse certifications for another task.
PUBLIC_TASKS={
'A011':('company','Synthesize independent business, valuation and risk research. Identify unresolved conflicts, decision blockers and required evidence. Do not recommend an order.'),
'A013':('company','Plan research tasks for the issuer. Identify missing primary sources, disconfirming tests, and relevant financial periods.'),
'A014':('company','Audit evidence dates, reported versus adjusted metrics, units, contradictions and source sufficiency.'),
'A015':('company','Summarize the evidence record, material disagreements, unknowns and follow-up questions without inventing committee approval.'),
'A023':('company','Identify dated issuer events and original disclosures. Separate confirmed changes from rumors, and distinguish event date and publication date.'),
'A031':('company','Analyze business model, segment revenue, customers, distribution, revenue drivers and material dependencies.'),
'A032':('company','Analyze revenue growth, recurring revenue, unit economics, pricing, volumes and margins. Distinguish disclosed from estimated figures.'),
'A033':('company','Evaluate competitive moat, switching costs, pricing power, substitutes and evidence that advantages may erode.'),
'A034':('company','Review management incentives, acquisitions, capital allocation, stock compensation, repurchases and dilution.'),
'A035':('company','Investigate accounting quality, cash conversion, accruals, working capital, restatements and off-balance-sheet obligations.'),
'A043':('company','Identify comparable companies and explain business mix, accounting and growth differences. Do not invent peer multiples or prices.'),
'A044':('company','Identify downside, base and upside drivers and falsifiers. Do not claim calibrated probabilities or derive them from intrinsic value.'),
'A051':('company','Apply Buffett-Graham quality and margin of safety: durable economics, reinvestment, financial strength and valuation risk.'),
'A052':('company','Apply Munger inversion: identify failure paths, incentives, confirmation bias and evidence against the thesis.'),
'A053':('company','Apply Howard Marks cycle lens: financing conditions, valuation, investor expectations, cyclical risk and downside.'),
'A054':('company','Apply Damodaran story-to-numbers: link revenue, margins, reinvestment, dilution and risk assumptions to testable evidence.'),
'A055':('macro','Analyze growth, inflation, policy regimes and diversification tradeoffs. Do not assume regime forecasts are certain.'),
'A061':('macro','Review policy rates, yield curve, credit spreads and financing conditions. Distinguish observations and vintage revisions.'),
'A062':('macro','Review liquidity, financial conditions, balance-sheet constraints and credit transmission.'),
'A063':('macro','Review inflation and growth releases, publication dates, revisions and missing observations.'),
'A064':('macro','Review FX and commodity exposures, currency denomination, drivers and sensitivity; distinguish spot and total returns.'),
'A071':('company','Propose measurable factor hypotheses, economic rationale, controls, leakage tests and null hypotheses. No code execution.'),
'A072':('company','Audit potential feature leakage, label availability, selection bias, overlapping observations and training/test separation.'),
'A073':('company','Propose event study design, event timestamp, confounders, windows, benchmark and multiple-testing controls.'),
'A074':('company','Evaluate alternative data quality, legality, publication latency, representativeness and confounding.'),
'A101':('company','Construct the strongest independent bear case, failure conditions, disconfirming primary evidence and downside risks.'),
'A102':('company','Independently audit financial claims, dates, units, assumptions, conflicts and unsupported conclusions.'),
'A103':('company','Challenge causal claims, confounding, survivorship, multiple testing and alternative explanations.'),
'A105':('company','Propose testable research-process improvements and preregister evaluation criteria. Never modify policy or promote a strategy.'),
}

LOCAL_TASKS={
'A012':'policy_gate','A021':'market_check','A022':'financial_snapshot','A024':'reconcile_sources','A025':'evidence_audit',
'A041':'dcf','A042':'reverse_dcf','A045':'option_bounds','A065':'regime_diagnostic','A075':'purged_panel',
'A081':'account_exposures','A082':'historical_tail','A083':'scenario_kelly','A084':'account_stress','A085':'tax_review',
'A091':'paper_proposal_gate','A092':'spread_diagnostic','A093':'account_margin','A094':'fill_reconcile','A095':'authorization_gate','A104':'calibration',
}


def _safe(result):
    if not isinstance(result,dict):raise ValueError('job result not a mapping')
    if result.get('can_trade',False) is not False:raise PermissionError('unsafe result')
    return result|{'can_trade':False}


def _source_reconcile(ledger,p,at):
    records=ledger.resolve_ids(p['record_ids'],security_id=p['security_id'],decision_at=at,include_private=True)
    field=p['field'];tol=num(p['absolute_tolerance'])
    if tol<0 or len({r['source_id'] for r in records})<2:raise ValueError('independent provider records required')
    if len({r['observed_at'] for r in records})!=1:raise ValueError('observation timestamps differ')
    if len({r['payload']['currency'] for r in records})!=1 or len({r['payload']['unit'] for r in records})!=1:raise ValueError('currency or unit mismatch')
    values=[num(r['payload'][field]) for r in records]
    return {'status':'CONSISTENT' if max(values)-min(values)<=tol else 'CONFLICT','spread':max(values)-min(values),'evidence_ids':p['record_ids'],'limitations':['agreement is not independent proof of accuracy']}


def _option_bounds(p,at):
    spot,strike,mark,rate,dividend=map(num,(p['spot'],p['strike'],p['mark'],p['risk_free_rate'],p['dividend_yield']))
    t=(iso(p['expiry'])-iso(at)).total_seconds()/(365.25*86400)
    if not 0<t<=20 or min(spot,strike)<=0 or mark<0 or p['right'] not in ('call','put') or p['style'] not in ('american','european') or not -0.1<=rate<=1 or not 0<=dividend<=1:raise ValueError('invalid option inputs')
    if p['style']=='american':
        lo=max(0,spot-strike) if p['right']=='call' else max(0,strike-spot);hi=spot if p['right']=='call' else strike*math.exp(max(0,-rate)*t)
    else:
        s=spot*math.exp(-dividend*t);k=strike*math.exp(-rate*t);lo=max(0,s-k) if p['right']=='call' else max(0,k-s);hi=s if p['right']=='call' else k
    return {'status':'OPTION_BOUND_DIAGNOSTIC','lower':lo,'upper':hi,'mark_inside':lo-.01<=mark<=hi+.01,'limitations':['no-arbitrage sanity bounds; not implied volatility, American exercise valuation or broker margin']}


def _fills(p):
    def norm(rows):
        out={}
        for r in rows:
            k=r['execution_id'];q=num(r['quantity']);price=num(r['price']);fee=num(r['commission'])
            if not k or k in out or q<=0 or price<0 or fee<0 or r['side'] not in ('buy','sell') or not r.get('evidence_id'):raise ValueError('invalid fill record')
            out[k]=(r['security_id'],r['side'],q,price,fee,r['currency'])
        return out
    a,b=norm(p['local_fills']),norm(p['broker_fills']);missing=set(a)^set(b);diff=[k for k in set(a)&set(b) if a[k]!=b[k]]
    return {'status':'BLOCK' if missing or diff else 'RECONCILED_INPUTS','missing_execution_ids':sorted(missing),'different_execution_ids':sorted(diff),'limitations':['operator-provided exports; not an authenticated broker session']}


class RoleExecutor:
    def __init__(self,roles,ledger,*,model_runner=None,forecast_journal=None,reference_store=None):
        self.roles={r['agent_id']:r for r in roles};self.ledger=ledger;self.model_runner=model_runner;self.forecast_journal=forecast_journal;self.reference_store=reference_store
        self.skills=validate_catalog(roles,PUBLIC_TASKS,LOCAL_TASKS)
        if set(self.roles)!=set(PUBLIC_TASKS)|set(LOCAL_TASKS) or set(PUBLIC_TASKS)&set(LOCAL_TASKS):raise ValueError('role manifest mismatch')
        for r in PUBLIC_TASKS:
            if self.roles[r]['data_scope']!='public_only' or self.roles[r]['primary_model']=='deterministic':raise ValueError('public role mismatch')
        for r in LOCAL_TASKS:
            if self.roles[r]['primary_model'] not in ('deterministic','local-private'):raise ValueError('local role mismatch')
    def catalog(self):
        return [{'role_id':r,'role':self.roles[r]['role'],'task_set':task_id(r),'skill':self.skills[r],'kind':'certified_public_memo' if r in PUBLIC_TASKS else LOCAL_TASKS[r], 'can_trade':False} for r in sorted(self.roles)]
    def run(self,role_id,*,at,run_id,inputs):
        if role_id not in self.roles or not run_id or not isinstance(inputs,dict):raise ValueError('invalid role job')
        iso(at)
        from .capability_runtime import load_role_context
        try:
            context=load_role_context(role_id)
            if self.reference_store is not None:
                query=(contract(role_id).get('research_query') or contract(role_id)['method'])[:500]
                hits=self.reference_store.search(role_id,query,at=at)
                context['receipt']['local_external_reference_hits']=[{k:h[k] for k in ('source_id','snapshot_id','sha256','excerpt_sha256','normalized_excerpt_start','normalized_excerpt_end')} for h in hits]
                del context['receipt']['context_hash']
                context['receipt']['context_hash']=digest(context['receipt'])
        except (ValueError,KeyError,PermissionError,OSError):
            return _safe({'status':'BLOCKED_ROLE_REFERENCE_INTEGRITY','role_id':role_id})
        receipt=context['receipt']
        if role_id in PUBLIC_TASKS:
            # No free-text user/portfolio inputs cross this boundary. The query is static.
            kind,query=PUBLIC_TASKS[role_id];sid=inputs.get('security_id')
            if set(inputs)!={'security_id'} or not isinstance(sid,str) or (kind=='company' and not re.fullmatch(r'CIK:[1-9][0-9]{0,9}',sid)) or (kind=='macro' and sid!='MACRO:US'):
                raise PermissionError('public role only accepts canonical public identifier')
            if self.model_runner is None:return _safe({'status':'BLOCKED_MODEL_RUNTIME','role_id':role_id,'reference_context':receipt})
            result=self.model_runner.run(role_id=role_id,task_set=task_id(role_id),request_id=digest({'run':run_id,'role':role_id,'security':sid,'at':iso(at).isoformat()}),security_id=sid,query=query,at=at)
        else:result=self._local(LOCAL_TASKS[role_id],inputs,at)
        return _safe(result)|{'reference_context':receipt,'role_id':role_id,'skill_task_set':task_id(role_id),'task_id':digest({'role':role_id,'skill':task_id(role_id),'run':run_id,'inputs':inputs,'at':iso(at).isoformat()})}
    def _local(self,task,p,at):
        if task=='policy_gate':
            pol=p['policy'];ok=pol.get('status')=='ACTIVE_APPROVED' and pol.get('owner_approval',{}).get('approved') is True and pol.get('permissions',{}).get('live_execution') is False
            return {'status':'RESEARCH_POLICY_PRESENT' if ok else 'BLOCK','policy_hash':digest(pol),'execution_authorized':False}
        if task=='market_check':
            m=p['market'];age=(iso(at)-iso(m['price_asof'])).total_seconds();ok=0<=age<=90 and market_evidence_matches(self.ledger,m,cik=p['cik'],at=at)
            return {'status':'RESEARCH_QUOTE_CHECKED' if ok else 'BLOCK','age_seconds':age,'execution_qualified':False}
        if task=='financial_snapshot':
            sid=p['security_id'];rec=self.ledger.resolve_ids(p['record_ids'],security_id=sid,decision_at=at)
            if any(r['source_id']!='sec_edgar' or r['record_id']!=digest(r['payload']) or sid!=f"CIK:{r['payload']['cik']}" or iso(r['payload']['available_at'])!=iso(r['available_at']) for r in rec):raise ValueError('SEC provenance mismatch')
            basis=p['basis'];fn={'annual':annual_snapshot,'ttm':ttm_snapshot}[basis];snap=fn([r['payload'] for r in rec],at=at)
            return {'status':'FINANCIAL_SNAPSHOT' if snap else 'INSUFFICIENT_DATA','snapshot':snap}
        if task=='reconcile_sources':return _source_reconcile(self.ledger,p,at)
        if task=='evidence_audit':
            rows=self.ledger.resolve_ids(p['record_ids'],security_id=p['security_id'],decision_at=at,include_private=True)
            return {'status':'INTEGRITY_CHECKED','records':len(rows),'scopes':sorted({r['data_class'] for r in rows})}
        if task=='dcf':return dcf(**p['assumptions'])
        if task=='reverse_dcf':return reverse_dcf(p['price'],p['assumptions'])
        if task=='option_bounds':return _option_bounds(p,at)
        if task=='regime_diagnostic' or task=='historical_tail':
            rows=p['returns'];values=[];previous=None
            if len(rows)<100:raise ValueError('insufficient history')
            for row in rows:
                t,avail=iso(row['at']),iso(row['available_at']);v=num(row['return'])
                if t>avail or avail>iso(at) or (previous and t<=previous) or v< -1 or not row.get('evidence_ids'):raise ValueError('unqualified historical return')
                previous=t;values.append(v)
            import statistics
            if task=='historical_tail':return {'status':'CONDITIONAL_TAIL_RISK','observations':len(values),'cvar95':max(0,tail_loss(values,.95)),'limitations':['operator-supplied aligned account total returns; not maximum loss']}
            trend=math.prod(1+x for x in values[-60:])-1;vol=statistics.stdev(values[-60:])*math.sqrt(252)
            return {'status':'REGIME_DIAGNOSTIC','trailing_60_session_return':trend,'annualized_volatility':vol,'classification':'negative_trend' if trend<0 else 'nonnegative_trend','limitations':['descriptive trailing data, not a macroeconomic regime forecast']}
        if task=='purged_panel':
            rows=[]
            for row in p['samples']:
                available=iso(row['label_available_at'])
                if available<iso(row['label_end_at']) or available>iso(at):raise ValueError('label availability not established at cutoff')
                rows.append(row|{'label_end_at':available.isoformat()})
            if any(iso(r['signal_at'])>iso(at) for r in rows):raise ValueError('future panel signal')
            folds=purged_panel_folds(rows,**p['settings'])
            return {'status':'SPLITS_CHECKED' if folds else 'INSUFFICIENT_DATA','folds':len(folds),'split_hash':digest(folds)}
        if task in ('account_exposures','account_stress','account_margin'):
            return review_accounts(p['snapshot'],expected_accounts=p['expected_accounts'],scenarios=p['scenarios'],limits=p['limits'],at=at)
        if task=='scenario_kelly':return scenario_grid(p['scenarios'],price=p['price'],benchmark_return=p['benchmark_return'],cost_fraction=p.get('cost_fraction',0),probabilities_validated=False)
        if task=='tax_review':
            return {'status':'BLOCKED_TAX_REVIEW','account_types':sorted(set(p['account_types'])),'reason':'jurisdiction, cost basis, tax lots, registered-account eligibility and professional review required'}
        if task=='paper_proposal_gate':return {'status':'WAIT','reason':'research-only role cannot generate executable orders; operator-only paper gateway remains separate'}
        if task=='spread_diagnostic':
            b,a=map(num,(p['bid'],p['ask']));age=(iso(at)-iso(p['price_asof'])).total_seconds()
            if not 0<b<=a or not 0<=age<=90 or not p.get('evidence_ids'):raise ValueError('unqualified spread')
            return {'status':'SPREAD_DIAGNOSTIC','spread_bps':(a-b)/((a+b)/2)*10000,'limitations':['quoted spread is not a fill or slippage guarantee']}
        if task=='fill_reconcile':return _fills(p)
        if task=='authorization_gate':return {'status':'DENIED','reason':'no execution authority in role runtime','execution_authorized':False}
        if task=='calibration':
            if self.forecast_journal is None:return {'status':'BLOCKED_FORECAST_JOURNAL'}
            return self.forecast_journal.report(at=at,strategy_version=p.get('strategy_version'),model_version=p.get('model_version'))
        raise ValueError('unmapped job')


class RoleJournal:
    """Append-only job intents/results. Interrupted paid calls require operator review.
    One transaction admits each job; no automatic resend after uncertain results.
    """
    def __init__(self,path,*,memory=None):
        self.path=str(path);self.memory=memory
        with closing(sqlite3.connect(self.path)) as c,c:
            c.executescript('CREATE TABLE IF NOT EXISTS role_jobs(id TEXT PRIMARY KEY,request_hash TEXT NOT NULL,result TEXT,result_hash TEXT); CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,request_hash TEXT NOT NULL);')
    def bind_batch(self,run_id,request):
        rh=digest(request)
        with closing(sqlite3.connect(self.path,timeout=10)) as c,c:
            c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT request_hash FROM batches WHERE id=?',(run_id,)).fetchone()
            if row and row[0]!=rh:raise ValueError('batch inputs changed; use a new run ID')
            c.execute('INSERT OR IGNORE INTO batches VALUES(?,?)',(run_id,rh))
    def _episode(self,role_id,jid,result,at):
        if self.memory is not None:self.memory.bind(role_id).record_episode(task_id_value=jid,result_hash=digest(result),status=result.get('status','UNKNOWN'),at=at)
    def execute(self,executor,role_id,*,at,run_id,inputs):
        jid=digest({'role':role_id,'run_id':run_id});rh=digest({'at':iso(at).isoformat(),'inputs':inputs,'skill':task_id(role_id)})
        with closing(sqlite3.connect(self.path,timeout=10)) as c,c:
            c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT request_hash,result,result_hash FROM role_jobs WHERE id=?',(jid,)).fetchone()
            if row:
                if row[0]!=rh:raise ValueError('job input conflict')
                if row[1] is None:return {'status':'UNRESOLVED_JOB_NO_RESEND','can_trade':False}
                result=json.loads(row[1]);
                if digest(result)!=row[2]:raise ValueError('job integrity failure')
                self._episode(role_id,jid,result,at)
                return result
            c.execute('INSERT INTO role_jobs VALUES(?,?,NULL,NULL)',(jid,rh))
        try:result=executor.run(role_id,at=at,run_id=run_id,inputs=inputs)
        except (ValueError,KeyError,PermissionError,TypeError,AttributeError,ArithmeticError) as e:result={'status':'BLOCKED_INPUT','error_type':type(e).__name__,'role_id':role_id,'can_trade':False}
        result=_safe(result);raw=json.dumps(result,sort_keys=True,allow_nan=False)
        with closing(sqlite3.connect(self.path,timeout=10)) as c,c:c.execute('UPDATE role_jobs SET result=?,result_hash=? WHERE id=? AND result IS NULL',(raw,digest(result),jid))
        self._episode(role_id,jid,result,at)
        return result
