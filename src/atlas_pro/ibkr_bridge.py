"""Read-only bridge into the existing personal_agent IBKR harness.

Does not sync, authenticate, place orders, or modify broker state. Only reads
already captured snapshots. Live permissions are not inferred from paper/replay.
"""
from __future__ import annotations
from .ledger import iso
from datetime import datetime, timezone

class IBKRReadOnlyBridge:
    def __init__(self, finance_module=None, broker_module=None):
        if finance_module is None or broker_module is None:
            from personal_agent import finance,broker
            finance_module=finance_module or finance
            broker_module=broker_module or broker
        self.finance=finance_module
        self.broker=broker_module

    def inspect(self, *, at=None, max_broker_age_seconds=300):
        if type(max_broker_age_seconds) is not int or not 1<=max_broker_age_seconds<=300:
            raise ValueError("broker age limit must be 1–300 seconds")
        now=iso(at) if at else datetime.now(timezone.utc)
        flex=self.finance.load_full_portfolio_snapshot()
        state=self.broker.latest_broker_snapshot()
        reconciliation=self.broker.reconcile_live_to_flex()
        live=bool(state.get('status')=='ok' and state.get('capture_status')=='ok' and state.get('live_verified') and state.get('adapter')=='ibkr_tws_readonly')
        age=None
        if live:
            try:
                age=(now-iso(state['as_of'])).total_seconds()
                live=0<=age<=max_broker_age_seconds and bool(state.get('snapshot_id'))
            except (KeyError,ValueError,TypeError,AttributeError):live=False
        # Verify the reconciliation belongs to these exact snapshots, not a race.
        matched=(reconciliation.get('status')=='reconciled' and
                 reconciliation.get('broker_snapshot_id')==state.get('snapshot_id') and
                 reconciliation.get('flex_snapshot_id')==flex.snapshot_id and
                 bool(state.get('snapshot_id')))
        # Flex reporting date is not the live broker timestamp; label that honestly.
        complete=bool(flex.positions_complete and flex.advice_allowed and flex.status=='ok' and flex.accounts)
        return {'status':'READ_ONLY_READY' if (live and matched and complete) else 'RESTRICTED',
            'all_configured_accounts_present':complete,
            'reconciled':matched,
            'same_asof':False,
            'reporting_date_aligned':bool(flex.as_of and flex.positions_complete and flex.status=='ok'),
            'broker_age_seconds':age,
            'fx_converted_to_base':bool(flex.currency and flex.positions_complete and matched),
            'broker_capture_live_verified':live,
            'broker_snapshot_id':state.get('snapshot_id') if live else None,
            'broker_asof':state.get('as_of') if live else None,
            'flex_asof':flex.as_of,
            'flex_snapshot_id':flex.snapshot_id,
            'can_place_order':False,
            'message':'Read-only reporting comparison, not atomic live portfolio state. Quote entitlement, option margin and market permissions require separate trade-specific checks.'}
