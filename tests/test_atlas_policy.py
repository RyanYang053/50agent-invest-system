"""Offline tests for the standalone Atlas *reference* configuration and router.
Does not test the IBKR Agent Harness repository, any live broker, or model API.
"""
import unittest,sys
from decimal import Decimal
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from atlas_policy_router import (load, validate_manifest, estimate_call_cost_usd,
    assign_models, route_event, policy_change_request, pre_trade_research_gate, sample_monthly_cost,
    ConfigurationError, budget_and_capability_admission, verify_point_in_time_evidence)

class AtlasPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models=load('model registry.json'); cls.roles=load('50 agent manifest.json')
        cls.rules=load('event rules.json'); cls.mandate=load('investment policy template.json')
    def test_manifest_valid(self): validate_manifest(self.roles,self.models,self.rules)
    def test_exactly_fifty_roles(self): self.assertEqual(len(self.roles),50)
    def test_ten_teams(self): self.assertEqual(len({a['team'] for a in self.roles}),10)
    def test_distinct_ids(self): self.assertEqual(len({a['agent_id'] for a in self.roles}),50)
    def test_no_live_order_privileges(self): self.assertTrue(all(not a['can_place_live_orders'] for a in self.roles))
    def test_no_policy_mutation_privileges(self): self.assertTrue(all(not a['can_change_investment_policy'] for a in self.roles))
    def test_no_skill_promotion_privileges(self): self.assertTrue(all(not a['can_promote_strategy'] for a in self.roles))
    def test_critical_policy_deterministic(self): self.assertEqual(self.roles[1]['primary_model'],'deterministic')
    def test_private_agent_is_not_public_llm(self):
        self.assertEqual(assign_models('A083','private_only')['model'],'deterministic')
    def test_private_snapshot_cannot_go_to_cloud_cio(self):
        self.assertEqual(assign_models('A011','private_only')['status'],'BLOCKED_PRIVACY')
    def test_no_cloud_fail_closed(self):
        self.assertEqual(assign_models('A011','public_only',cloud_available=False)['status'],'DEFERRED_PROVIDER_UNAVAILABLE')
    def test_private_hedge_local_only(self):
        self.assertEqual(assign_models('A084','private_only')['model'],'local-private')
    def test_unknown_agent_denied(self):
        with self.assertRaises(ConfigurationError): assign_models('A999','public_only')
    def test_prices_sol(self): self.assertEqual(estimate_call_cost_usd('gpt-6.2-sol',25000,4000),Decimal('0.09'))
    def test_prices_luna(self): self.assertEqual(estimate_call_cost_usd('gpt-6-luna',3000,600),Decimal('0.0006'))
    def test_deepseek_offpeak(self):
        self.assertEqual(estimate_call_cost_usd('deepseek-flash',8000,1200,offpeak=True),Decimal('0.00192'))
    def test_gemini_2027_price_change(self):
        a=estimate_call_cost_usd('gemini-3.8-flash',100000,10000,as_of='2026-11-23')
        b=estimate_call_cost_usd('gemini-3.8-flash',100000,10000,as_of='2027-01-02')
        self.assertEqual(b,a*2)
    def test_claude_haiku_long_context_tier(self):
        cheap=estimate_call_cost_usd('claude-haiku-5-5',100000,1000)
        expensive=estimate_call_cost_usd('claude-haiku-5-5',100001,1000)
        self.assertGreater(expensive,cheap)
    def test_never_count_local_as_free_api(self): self.assertIsNone(estimate_call_cost_usd('local-private',100000,2000))
    def test_negative_tokens_rejected(self):
        with self.assertRaises(ValueError): estimate_call_cost_usd('gpt-6-luna',-1,100)
    def test_unknown_event_rejected(self): self.assertEqual(route_event({'event_type':'unknown'})['status'],'UNKNOWN_EVENT')
    def test_unverified_high_priority_requires_confirmation(self):
        self.assertEqual(route_event({'event_type':'filing_material_risk'},verified=False)['status'],'NEEDS_VERIFICATION')
    def test_verified_filing_can_route(self):
        self.assertEqual(route_event({'event_type':'filing_material_risk','source_event_id':'filing-123'},verified=True)['status'],'READY')
    def test_cooldown(self):
        ev={'event_type':'earnings_release','instrument_id':'MSFT','source_event_id':'42'}
        key='earnings_release|MSFT|42'
        self.assertEqual(route_event(ev,{key:101},now_epoch=200,verified=True)['status'],'COOLDOWN')
    def test_p0_cannot_be_cooled(self):
        ev={'event_type':'margin_cushion_breach','source_event_id':'x'}
        key='margin_cushion_breach|ALL|x'
        result=route_event(ev,{key:101},now_epoch=200)
        self.assertEqual(result['status'],'READY')
        self.assertTrue(all(x['model']=='deterministic' for x in result['agents']))
    def test_p0_never_orders(self):
        self.assertFalse(route_event({'event_type':'margin_cushion_breach'})['can_trade'])
    def test_agent_can_never_initiate_policy_change(self):
        self.assertEqual(policy_change_request('agent',{'max_drawdown_budget':.75})['status'],'DENIED_TO_AGENT')
    def test_even_claimed_owner_requires_external_auth(self):
        self.assertFalse(policy_change_request('privileged_owner_workflow',{'limits':{}})['applied'])
    def test_default_mandate_not_approved(self): self.assertEqual(self.mandate['status'],'DRAFT_NOT_AUTHORIZED')
    def test_unapproved_mandate_blocks(self):
        result=pre_trade_research_gate(self.mandate,{},{});
        self.assertEqual(result['status'],'BLOCK')
        self.assertIn('OWNER_MANDATE_NOT_APPROVED',result['failures'])
    def test_missing_quotes_block(self):
        tmp=dict(self.mandate);tmp['status']='ACTIVE_APPROVED';tmp['owner_approval']={'approved':True}
        self.assertIn('QUOTE_NOT_QUALIFIED',pre_trade_research_gate(tmp,{}, {})['failures'])
    def test_excess_stock_weight_block(self):
        tmp=dict(self.mandate);tmp['status']='ACTIVE_APPROVED';tmp['owner_approval']={'approved':True}
        snap=dict(all_accounts_complete=True,same_statement_date=True,base_currency_consistent=True,market_quote_qualified=True,margin_data_current=True)
        order={'post_single_stock_weight':.16,'post_cluster_weight':.2,'post_economic_leverage':1.1,
               'post_gross_economic_leverage':1.2,'post_cash_weight':.1,'order_notional_usd':0}
        self.assertIn('SINGLE_STOCK_LIMIT',pre_trade_research_gate(tmp,snap,order)['failures'])
    def test_cash_reserve_block(self):
        tmp=dict(self.mandate);tmp['status']='ACTIVE_APPROVED';tmp['owner_approval']={'approved':True}
        snap=dict(all_accounts_complete=True,same_statement_date=True,base_currency_consistent=True,market_quote_qualified=True,margin_data_current=True)
        order={'post_single_stock_weight':.1,'post_cluster_weight':.2,'post_economic_leverage':1.1,
               'post_gross_economic_leverage':1.2,'post_cash_weight':.01,'order_notional_usd':0}
        self.assertIn('CASH_FLOOR',pre_trade_research_gate(tmp,snap,order)['failures'])
    def test_even_research_gate_pass_cannot_trade(self):
        tmp=dict(self.mandate);tmp['status']='ACTIVE_APPROVED';tmp['owner_approval']={'approved':True}
        snap=dict(all_accounts_complete=True,same_statement_date=True,base_currency_consistent=True,market_quote_qualified=True,margin_data_current=True)
        order={'post_single_stock_weight':.1,'post_cluster_weight':.2,'post_economic_leverage':1.1,
               'post_gross_economic_leverage':1.2,'post_cash_weight':.1,'order_notional_usd':0}
        result=pre_trade_research_gate(tmp,snap,order)
        self.assertFalse(result['can_place_live_order'])
    def test_material_event_missing_source_id_rejected(self):
        result=route_event({'event_type':'earnings_release'},verified=True)
        self.assertEqual(result['status'],'NEEDS_SOURCE_ID')
    def test_model_not_certified_fails_closed(self):
        x=budget_and_capability_admission('A011',data_scope='public_only',certified_models={},
              spent_today_usd=0,estimated_input_tokens=10000,estimated_output_tokens=2000)
        self.assertEqual(x['status'],'TASK_EVAL_REQUIRED')
    def test_model_certified_admission(self):
        x=budget_and_capability_admission('A011',data_scope='public_only',
             certified_models={'A011:gpt-6.2-sol':True},spent_today_usd=0,
             estimated_input_tokens=10000,estimated_output_tokens=2000)
        self.assertEqual(x['model'],'gpt-6.2-sol')
    def test_cheaper_fallback_only_after_certification(self):
        x=budget_and_capability_admission('A011',data_scope='public_only',
             certified_models={'A011:gpt-6.2-sol':True,'A011:gemini-3.8-flash':True},
             spent_today_usd=0,estimated_input_tokens=10000,estimated_output_tokens=2000)
        self.assertEqual(x['model'],'gemini-3.8-flash')
    def test_budget_blocked(self):
        x=budget_and_capability_admission('A011',data_scope='public_only',
             certified_models={'A011:gpt-6.2-sol':True},spent_today_usd=12,
             estimated_input_tokens=10000,estimated_output_tokens=2000)
        self.assertEqual(x['status'],'DAILY_BUDGET_BLOCK')
    def test_privacy_remains_blocked_in_admission(self):
        x=budget_and_capability_admission('A011',data_scope='private_only',
             certified_models={'A011:gpt-6.2-sol':True},spent_today_usd=0,
             estimated_input_tokens=10000,estimated_output_tokens=2000)
        self.assertEqual(x['status'],'BLOCKED_PRIVACY')
    def test_local_private_requires_certification(self):
        x=budget_and_capability_admission('A084',data_scope='private_only',
             certified_models={'A084:local-private':True},spent_today_usd=0,
             estimated_input_tokens=10000,estimated_output_tokens=2000)
        self.assertEqual(x['status'],'READY')
        self.assertIsNone(x['estimated_cost_usd'])
    def test_deterministic_not_model_budget_blocked(self):
        x=budget_and_capability_admission('A083',data_scope='private_only',
             certified_models={},spent_today_usd=999,
             estimated_input_tokens=0,estimated_output_tokens=0)
        self.assertEqual(x['status'],'READY')
        self.assertEqual(x['model'],'deterministic')
    def test_cny_vendor_not_mispriced_as_usd(self):
        with self.assertRaises(ConfigurationError):
            estimate_call_cost_usd('qwen3.8-flash',1000,1000)
    def test_gemini4_hydrogen_price(self):
        self.assertEqual(estimate_call_cost_usd('gemini-4-hydrogen',1000000,1000000),Decimal('9.00'))
    def test_pit_future_information_block(self):
        r=verify_point_in_time_evidence({'source_document_id':'abc','available_at':'2026-11-23T18:15:00Z'},
                  '2026-11-23T18:00:00Z')
        self.assertEqual(r['reason'],'FUTURE_INFORMATION')
    def test_pit_prior_information_allowed(self):
        r=verify_point_in_time_evidence({'source_document_id':'abc','available_at':'2026-11-23T17:50:00Z'},
                  '2026-11-23T18:00:00Z')
        self.assertEqual(r['status'],'ELIGIBLE')
    def test_pit_missing_timestamp_block(self):
        r=verify_point_in_time_evidence({'source_document_id':'abc'},'2026-11-23T18:00:00Z')
        self.assertEqual(r['status'],'REJECT')
    def test_pit_naive_timestamp_block(self):
        r=verify_point_in_time_evidence({'source_document_id':'abc','available_at':'2026-11-23T17:00:00'},
                  '2026-11-23T18:00:00Z')
        self.assertEqual(r['reason'],'NAIVE_TIMESTAMP')
    def test_sample_monthly_estimate(self): self.assertEqual(sample_monthly_cost()['total_usd'],'86.69')
    def test_sample_respects_monthly_astra_cap(self):
        self.assertLessEqual(next(r['calls'] for r in sample_monthly_cost()['rows'] if r['model']=='gpt-6.2-astra'),
                             load('operating budget.json')['gpt-6.2-astra_max_calls_monthly'])

if __name__=='__main__': unittest.main(verbosity=2)
