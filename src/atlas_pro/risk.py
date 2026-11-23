"""Advisory multi-account risk gate, never a broker order approval.

Broker margin methodology and security-specific permission must be validated
again in the broker's authenticated execution context. All actions read-only.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from datetime import datetime,timedelta,timezone
from .ledger import iso

class ResearchRiskGate:
    def __init__(self,*,hard_no_live_orders=True):
        if not hard_no_live_orders:raise ValueError('RESEARCH_GATE_MUST_REMAIN_READ_ONLY')

    def review(self, mandate:dict, account_state:dict, proposal:dict, *, at:str):
        now=iso(at); errors=[]
        if mandate.get('status')!='ACTIVE_APPROVED' or mandate.get('owner_approval',{}).get('approved') is not True:
            errors.append('MANDATE_UNAPPROVED')
        if proposal.get('action') not in ('BUY','SELL','HOLD','REDUCE','WAIT'):
            errors.append('UNKNOWN_ACTION')
        if account_state.get('all_configured_accounts_present') is not True:errors.append('INCOMPLETE_ACCOUNTS')
        if account_state.get('reconciled') is not True:errors.append('UNRECONCILED_ACCOUNTS')
        if account_state.get('same_asof') is not True:errors.append('DATE_MISMATCH')
        if account_state.get('fx_converted_to_base') is not True:errors.append('FX_UNVERIFIED')
        if account_state.get('quote_entitled_and_qualified') is not True:errors.append('QUOTE_NOT_QUALIFIED')
        if account_state.get('broker_permissions_verified') is not True:errors.append('BROKER_MARKET_PERMISSIONS_UNKNOWN')
        for field,max_age in [('balances_asof',900),('positions_asof',900),('margin_asof',180),('quote_asof',90)]:
            try:
                then=iso(account_state[field]); age=(now-then).total_seconds()
                if age<0 or age>max_age:errors.append('STALE_'+field.upper())
            except (KeyError,ValueError,TypeError):errors.append('MISSING_'+field.upper())
        limits=mandate.get('limits') or {}
        constraints=[('post_single_stock_weight','max_single_stock_weight','CONCENTRATION'),
                     ('post_cluster_weight','max_correlated_cluster_weight','CLUSTER'),
                     ('post_economic_leverage','max_economic_leverage','ECONOMIC_LEVERAGE'),
                     ('post_gross_economic_leverage','max_gross_economic_leverage','GROSS_LEVERAGE')]
        for post,lim,err in constraints:
            try:
                v=Decimal(str(proposal[post])); bound=Decimal(str(limits[lim]))
                if not v.is_finite() or not bound.is_finite() or v<0 or bound<0:raise ValueError()
                if v>bound:errors.append('LIMIT_'+err)
            except (KeyError,InvalidOperation,ValueError,TypeError):errors.append('INVALID_'+post)
        for post,lim,err in [('post_cash_weight','min_cash_reserve_weight','CASH_FLOOR')]:
            try:
                v=Decimal(str(proposal[post])); bound=Decimal(str(limits[lim]))
                if not v.is_finite() or not bound.is_finite() or not 0<=bound<=1:raise ValueError()
                if v<bound:errors.append(err)
            except (KeyError,InvalidOperation,ValueError,TypeError):errors.append('INVALID_'+post)
        if not proposal.get('evidence_ids') or not proposal.get('risk_engine_version'):
            errors.append('MISSING_DECISION_PROVENANCE')
        if proposal.get('independent_countercase_passed') is not True:errors.append('COUNTERCASE_NOT_VERIFIED')
        if proposal.get('action') in ('BUY','SELL','REDUCE') and proposal.get('tax_review_complete') is not True:
            errors.append('TAX_REVIEW_REQUIRED')
        if account_state.get('stress_tests_complete') is not True:
            errors.append('STRESS_TESTS_REQUIRED')
        return {'status':'BLOCK' if errors else 'ADVISORY_RESEARCH_PASSED',
                'reasons':sorted(set(errors)),
                'can_place_order':False,'order_gateway':'DISABLED',
                'requires_revalidation_at_execution':True}
