"""Read-only bridge into the existing personal_agent IBKR harness.

Does not sync, authenticate, place orders, or modify broker state. Only reads
already captured snapshots. Live permissions are not inferred from paper/replay.
"""
from __future__ import annotations
from .ledger import iso

class IBKRReadOnlyBridge:
    def __init__(self, finance_module=None, broker_module=None):
        if finance_module is None or broker_module is None:
            from personal_agent import finance,broker
            finance_module=finance_module or finance
            broker_module=broker_module or broker
        self.finance=finance_module
        self.broker=broker_module

    def inspect(self):
        flex=self.finance.load_full_portfolio_snapshot()
        state=self.broker.latest_broker_snapshot()
        reconciliation=self.broker.reconcile_live_to_flex()
        live=bool(state.get('status')=='ok' and state.get('capture_status')=='ok' and state.get('live_verified') and state.get('adapter')=='ibkr_tws_readonly')
        if live:
            try:iso(state['as_of'])
            except (KeyError,ValueError,TypeError):live=False
        matched=reconciliation.get('status')=='reconciled'
        complete=bool(flex.positions_complete and flex.advice_allowed and flex.status=='ok' and flex.accounts)
        return {'status':'READ_ONLY_READY' if (live and matched and complete) else 'RESTRICTED',
            'all_configured_accounts_present':complete,
            'reconciled':matched,
            'same_asof':bool(flex.as_of and flex.positions_complete and flex.status=='ok'),
            'fx_converted_to_base':bool(flex.currency and flex.positions_complete and matched),
            'broker_capture_live_verified':live,
            'broker_snapshot_id':state.get('snapshot_id') if live else None,
            'broker_asof':state.get('as_of') if live else None,
            'flex_asof':flex.as_of,
            'flex_snapshot_id':flex.snapshot_id,
            'can_place_order':False,
            'message':'Quote entitlement, option margin and market permissions require separate trade-specific checks.'}
