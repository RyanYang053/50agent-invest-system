"""Atlas Investment OS 2.0 reference router.

READ-ONLY research and safety prototype. No broker trading API, no credentials,
no agent-generated policy mutations. Stdlib only; suitable for offline tests.

This is a proposal implementation, not an audited production risk engine.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

CONFIG = Path(__file__).resolve().parent.parent / "config"


def load(name: str) -> Any:
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


class ConfigurationError(ValueError):
    pass


def validate_manifest(agents: list[dict], models: Mapping[str, dict], rules: list[dict]) -> None:
    ids = [a['agent_id'] for a in agents]
    if len(ids) != 50 or len(set(ids)) != 50:
        raise ConfigurationError("Exactly 50 unique roles must be registered")
    if len({a['team'] for a in agents}) != 10:
        raise ConfigurationError("Expected 10 teams")
    if len({x['event_type'] for x in rules}) != len(rules):
        raise ConfigurationError("Duplicate event type")
    for a in agents:
        primary = a['primary_model']
        fallback = a['fallback_model']
        if primary not in models or (fallback and fallback not in models):
            raise ConfigurationError(f"Unregistered model for {a['agent_id']}")
        if a['can_place_live_orders'] or a['can_change_investment_policy'] or a['can_promote_strategy']:
            raise ConfigurationError("Agent rights escalation forbidden")
        if a['data_scope'] == 'private_only' and models[primary]['data_scope'] not in ('private_only', 'local_only'):
            raise ConfigurationError(f"Private data may not route to public model: {a['agent_id']}")
        if a['data_scope'] == 'local_only' and primary != 'deterministic':
            raise ConfigurationError("Local deterministic role may not route externally")
        if a['data_scope'] == 'private_only' and fallback and models[fallback]['data_scope'] not in ('private_only', 'local_only'):
            raise ConfigurationError("Private role has unsafe fallback")
    for rule in rules:
        if rule['priority'] not in ('P0','P1','P2','P3','P4'):
            raise ConfigurationError('Unknown priority')
        for aid in rule['primary_agents']:
            if aid not in ids:
                raise ConfigurationError(f"Unknown agent in event rule: {aid}")
        if not rule['cannot_directly_trigger_live_order']:
            raise ConfigurationError('Event rule cannot place live trades')


def estimate_call_cost_usd(model: str, input_tokens: int, output_tokens: int,
                           *, as_of: str = '2026-11-23', offpeak: bool = False) -> Decimal | None:
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError('Negative token counts invalid')
    registry = load('model registry.json')
    if model not in registry:
        raise ConfigurationError(f'Unknown model {model}')
    info = registry[model]
    if info['provider'] == 'alibaba' and info.get('billing_currency')=='CNY':
        raise ConfigurationError('FX quote and billing region required for CNY model pricing')
    if info['provider'] == 'self_hosted':
        return None  # API $0 does NOT imply zero compute/electricity cost
    rate_in = info['input_usd_per_m']
    rate_out = info['output_usd_per_m']
    if offpeak and info['provider'] == 'deepseek':
        rate_in = info['offpeak_input_usd_per_m']
        rate_out = info['offpeak_output_usd_per_m']
    if info.get('price_valid_through') and as_of > info['price_valid_through']:
        if 'next_price_input_usd_per_m' not in info:
            raise ConfigurationError('Price refresh required')
        rate_in = info['next_price_input_usd_per_m']
        rate_out = info['next_price_output_usd_per_m']
    if info.get('price_cap_input_tokens') and input_tokens > info['price_cap_input_tokens']:
        rate_in = info['higher_price_input_usd_per_m']
        rate_out = info['higher_price_output_usd_per_m']
    return (Decimal(str(rate_in)) * input_tokens + Decimal(str(rate_out)) * output_tokens) / 1_000_000


def assign_models(agent_id: str, requested_data_scope: str, *, cloud_available: bool=True) -> dict:
    agents = {a['agent_id']:a for a in load('50 agent manifest.json')}
    models = load('model registry.json')
    if agent_id not in agents:
        raise ConfigurationError('Unknown agent')
    a = agents[agent_id]
    primary = a['primary_model']
    if requested_data_scope not in ('public_only', 'private_only'):
        raise ConfigurationError('Invalid data scope')
    if requested_data_scope == 'private_only' and models[primary]['data_scope'] == 'public_only':
        return {'status':'BLOCKED_PRIVACY', 'agent_id':agent_id, 'model':None}
    if not cloud_available and models[primary]['data_scope'] == 'public_only':
        return {'status':'DEFERRED_PROVIDER_UNAVAILABLE', 'agent_id':agent_id, 'model':None}
    return {'status':'READY','agent_id':agent_id,'model':primary,'effort':a['minimum_effort'],
            'permissions':'analysis_or_read_only','live_execution':False}


def route_event(event: Mapping[str,Any], previous: Mapping[str,int]|None=None,
                *, now_epoch: int=0, verified: bool=False, cloud_available:bool=True) -> dict:
    """Select *which roles to ask*, not trade, not make a live quote claim.

    `previous` is the caller's durable last-accepted dedupe-key to UNIX-second map.
    The caller must save idempotently in its own database.
    """
    rules = {e['event_type']:e for e in load('event rules.json')}
    kind = event.get('event_type')
    if kind not in rules:
        return {'status':'UNKNOWN_EVENT', 'agents':[], 'can_trade':False}
    rule = rules[kind]
    dedupe = f"{kind}|{event.get('instrument_id','ALL')}|{event.get('source_event_id','') or 'NO_SOURCE'}"
    prior = (previous or {}).get(dedupe)
    if rule['priority']!='P0' and prior is not None and now_epoch-prior < rule['cooldown_seconds']:
        return {'status':'COOLDOWN', 'dedupe_key':dedupe, 'agents':[], 'can_trade':False}
    if rule['requires_verified_event'] and not verified:
        return {'status':'NEEDS_VERIFICATION','dedupe_key':dedupe, 'agents':[], 'can_trade':False}
    if rule['requires_verified_event'] and not event.get('source_event_id'):
        return {'status':'NEEDS_SOURCE_ID','dedupe_key':dedupe, 'agents':[], 'can_trade':False}
    selected = []
    for aid in rule['primary_agents']:
        agent = assign_models(aid,'private_only' if aid.startswith(('A08','A09')) and aid not in ('A092',) else 'public_only',
                              cloud_available=cloud_available)
        # Local-only deterministic roles are always callable; their data authority remains local.
        if agent['status'] == 'READY':
            selected.append(agent)
    if rule['priority']=='P0':
        # Important: P0 is a deterministic path. LLM explanation is optional and non-blocking.
        selected=[a for a in selected if a['model']=='deterministic']
    return {'status':'READY' if selected else 'DEFERRED','priority':rule['priority'],
            'dedupe_key':dedupe,'agents':selected,'can_trade':False,
            'precheck_required':True,'max_ai_agents':rule['max_ai_agents']}


def budget_and_capability_admission(agent_id: str, *, data_scope: str,
                                    certified_models: Mapping[str,bool],
                                    spent_today_usd: float,
                                    estimated_input_tokens: int,
                                    estimated_output_tokens: int,
                                    as_of: str='2026-11-23') -> dict:
    """Cost-aware, eval-gated *research* admission. No provider calls occur.

    A model must be certified on this role's financial evaluation set before
    automatic admission. Fallback requires its own certification; a failure
    must not silently route a private task to a public provider.
    """
    role = next((r for r in load('50 agent manifest.json') if r['agent_id']==agent_id),None)
    if role is None: raise ConfigurationError('Unknown role')
    first = assign_models(agent_id,data_scope)
    if first['status']!='READY': return first
    models = load('model registry.json')
    budget = load('operating budget.json')
    if first['model']=='deterministic':
        return {'status':'READY','model':'deterministic','estimated_cost_usd':0.0,'can_trade':False}
    choices=[role['primary_model']]+([role['fallback_model']] if role['fallback_model'] else [])
    viable=[]
    for model in choices:
        if not certified_models.get(f'{agent_id}:{model}',False): continue
        if data_scope=='private_only' and models[model]['data_scope'] not in ('private_only','local_only'): continue
        estimate=estimate_call_cost_usd(model,estimated_input_tokens,estimated_output_tokens,as_of=as_of)
        if estimate is None:
            viable.append((Decimal(0),model,None)) # API cost unknown locally, not free total cost
        else:
            viable.append((estimate,model,float(estimate)))
    if not viable: return {'status':'TASK_EVAL_REQUIRED', 'model':None,'can_trade':False}
    viable.sort(key=lambda x:x[0])
    cheapest=viable[0]
    if cheapest[2] is not None and spent_today_usd+cheapest[2]>budget['daily_usd_hard_cap']:
        return {'status':'DAILY_BUDGET_BLOCK','model':None,'can_trade':False}
    return {'status':'READY','model':cheapest[1],'estimated_cost_usd':cheapest[2],
            'can_trade':False,'reasoning_effort':role['minimum_effort'],
            'approval_to_change_policy':False}


def policy_change_request(origin: str, proposed_changes: Mapping[str,Any]) -> dict:
    """Policy always belongs to an out-of-band privileged OWNER workflow.

    Even caller claiming origin 'human' is not proof of identity. Caller must verify
    true operator authentication/approval outside this library.
    """
    return {'status':'DENIED_TO_AGENT' if origin != 'privileged_owner_workflow' else 'REQUIRES_OUT_OF_BAND_OWNER_AUTH',
            'applied':False,'proposed_fields':sorted(proposed_changes.keys())}


def pre_trade_research_gate(mandate:Mapping[str,Any], snapshot:Mapping[str,Any],
                            proposal:Mapping[str,Any]) -> dict:
    """Fail-closed advisory gate; never authorizes or places an order.

    This is not a broker-equivalent margin model. Broker margin, borrow, order,
    tax and market permissions require additional execution-time checks.
    """
    failures=[]
    if mandate.get('status')!='ACTIVE_APPROVED' or not mandate.get('owner_approval',{}).get('approved',False):
        failures.append('OWNER_MANDATE_NOT_APPROVED')
    if mandate.get('permissions',{}).get('live_execution',False):
        # Even where a future user grants live execution, it is outside this research router.
        failures.append('RESEARCH_ROUTER_CANNOT_EXECUTE')
    if not snapshot.get('all_accounts_complete',False): failures.append('ACCOUNTS_INCOMPLETE')
    if not snapshot.get('same_statement_date',False): failures.append('ACCOUNT_DATES_MISMATCH')
    if not snapshot.get('base_currency_consistent',False): failures.append('FX_OR_CURRENCY_MISMATCH')
    if not snapshot.get('market_quote_qualified',False): failures.append('QUOTE_NOT_QUALIFIED')
    if not snapshot.get('margin_data_current',False): failures.append('MARGIN_DATA_STALE')
    lim=mandate['limits']
    checks=[('post_single_stock_weight','max_single_stock_weight','SINGLE_STOCK_LIMIT'),
            ('post_cluster_weight','max_correlated_cluster_weight','CLUSTER_LIMIT'),
            ('post_economic_leverage','max_economic_leverage','ECONOMIC_LEVERAGE_LIMIT'),
            ('post_gross_economic_leverage','max_gross_economic_leverage','GROSS_LEVERAGE_LIMIT')]
    for metric, bound, code in checks:
        if metric not in proposal: failures.append(f'MISSING_{metric.upper()}')
        elif Decimal(str(proposal[metric])) > Decimal(str(lim[bound])): failures.append(code)
    if 'post_cash_weight' not in proposal: failures.append('MISSING_POST_CASH_WEIGHT')
    elif Decimal(str(proposal['post_cash_weight'])) < Decimal(str(lim['min_cash_reserve_weight'])):
        failures.append('CASH_FLOOR')
    if 'order_notional_usd' not in proposal: failures.append('MISSING_ORDER_NOTIONAL')
    elif Decimal(str(proposal['order_notional_usd'])) > Decimal(str(lim['max_new_order_notional_usd'])):
        failures.append('ORDER_NOTIONAL_LIMIT')
    return {'status':'BLOCK' if failures else 'RESEARCH_GATE_PASSED_NOT_TRADE_APPROVED',
            'failures':failures,'can_place_live_order':False,
            'next_step':'Independent broker/tax/market + owner authorization gateway required.'}


def verify_point_in_time_evidence(record: Mapping[str,Any], decision_at: str) -> dict:
    """Minimal time-travel guard for an individual record.

    A production PIT warehouse needs full effective-dated revision metadata and
    provider availability vintages in addition to this timestamp check.
    """
    from datetime import datetime, timezone
    if not record.get('available_at') or not record.get('source_document_id'):
        return {'status':'REJECT','reason':'MISSING_TIME_OR_SOURCE'}
    try:
        available=datetime.fromisoformat(record['available_at'].replace('Z','+00:00'))
        decision=datetime.fromisoformat(decision_at.replace('Z','+00:00'))
    except (TypeError,ValueError):
        return {'status':'REJECT','reason':'INVALID_TIMESTAMP'}
    if available.tzinfo is None or decision.tzinfo is None:
        return {'status':'REJECT','reason':'NAIVE_TIMESTAMP'}
    if available.astimezone(timezone.utc)>decision.astimezone(timezone.utc):
        return {'status':'REJECT','reason':'FUTURE_INFORMATION'}
    return {'status':'ELIGIBLE','reason':'BASIC_CUTOFF_PASS_ONLY'}


def sample_monthly_cost() -> dict:
    """Illustrative high-activity month, NOT observed usage or a billing quote."""
    workloads=[
      ('gpt-6-luna',10008,3000,600),('deepseek-flash',4000,8000,1200),
      ('gemini-3.8-flash',1000,20000,3000),('gpt-6.2-sol',300,25000,4000),
      ('claude-sonnet-5-5',80,25000,3500),('gpt-6.2-astra',12,30000,5000)
    ]
    rows=[]
    for model,calls,t_in,t_out in workloads:
        one=estimate_call_cost_usd(model,t_in,t_out)
        rows.append({'model':model,'calls':calls,'avg_input_tokens':t_in,'avg_output_tokens':t_out,
                     'monthly_usd':str((one*calls).quantize(Decimal('0.01')))})
    return {'rows':rows,'total_usd':str(sum(Decimal(x['monthly_usd']) for x in rows).quantize(Decimal('0.01'))),
            'excluded':'data licenses, market feeds, web tools, provider retries, cache, tax, and local hosting'}

if __name__=='__main__':
    validate_manifest(load('50 agent manifest.json'),load('model registry.json'),load('event rules.json'))
    print(json.dumps(sample_monthly_cost(),ensure_ascii=False,indent=2))
