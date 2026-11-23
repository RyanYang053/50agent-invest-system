"""Quality checks for proposed Skills and research contracts.
No live services, broker credentials or market data required.
"""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class MethodSkillsAndContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skills = sorted((ROOT/'skills').iterdir())
        cls.decision = json.loads((ROOT/'schemas'/'decision contract.schema.json').read_text(encoding='utf-8'))
        cls.evidence = json.loads((ROOT/'schemas'/'evidence record.schema.json').read_text(encoding='utf-8'))
        cls.plan = json.loads((ROOT/'config'/'model evaluation plan.json').read_text(encoding='utf-8'))

    def test_exact_five_method_skills(self):
        self.assertEqual(len(self.skills),5)
    def test_method_skills_are_non_executable(self):
        for d in self.skills:
            m=json.loads((d/'skill manifest.json').read_text(encoding='utf-8'))
            self.assertFalse(m['can_place_live_orders'],d.name)
            self.assertFalse(m['can_change_investment_policy'],d.name)
            self.assertTrue(m['requires_eval_before_activation'],d.name)
    def test_method_source_status_never_falsely_verified(self):
        for d in self.skills:
            m=json.loads((d/'skill manifest.json').read_text(encoding='utf-8'))
            self.assertFalse(m['sources_ingested_and_verified'],d.name)
            self.assertEqual(m['status'],'RESEARCH_ONLY_NOT_CERTIFIED')
    def test_methods_have_specific_checks_and_abstentions(self):
        for d in self.skills:
            m=json.loads((d/'skill manifest.json').read_text(encoding='utf-8'))
            self.assertGreaterEqual(len(m['required_checks']),10)
            self.assertTrue(m['abstention_conditions'])
            self.assertIn('temporal_cutoff',m['required_evals'])
    def test_decision_contract_forbids_orders_and_policy_override(self):
        p=self.decision['properties']['privileges']['properties']
        self.assertIs(p['can_place_live_order']['const'],False)
        self.assertIs(p['can_override_policy']['const'],False)
        self.assertTrue(self.decision['additionalProperties'] is False)
    def test_decision_requires_audit_evidence_and_falsifiers(self):
        self.assertIn('source_snapshot_ids',self.decision['required'])
        self.assertIn('audit',self.decision['required'])
        self.assertIn('thesis_falsifiers',self.decision['properties']['analysis']['required'])
    def test_evidence_contract_requires_point_in_time_fields(self):
        for k in ('event_time','published_at','available_at','ingested_at','source_provider','license_status'):
            self.assertIn(k,self.evidence['required'])
    def test_model_benchmarks_are_planned_not_claimed(self):
        self.assertEqual(self.plan['status'],'PLANNED_NOT_EXECUTED')
        self.assertGreaterEqual(self.plan['minimum_locked_eval_examples_per_task'],100)
        self.assertTrue(self.plan['no_already_measured_scores'])
        self.assertTrue(self.plan['promotion_policy']['requires_human_signoff'])
    def test_json_schema_metaschema(self):
        try: from jsonschema import Draft202012Validator
        except ImportError: self.skipTest('Optional jsonschema not installed')
        Draft202012Validator.check_schema(self.decision)
        Draft202012Validator.check_schema(self.evidence)
    def test_research_decision_schema_rejects_unapproved_order_authorization(self):
        try: from jsonschema import Draft202012Validator
        except ImportError: self.skipTest('Optional jsonschema not installed')
        sample={
          'decision_id':'decision-12345','as_of_utc':'2026-11-23T18:00:00Z',
          'instrument_id':'US123','scope':'public_only','mandate_version':1,
          'source_snapshot_ids':['official-1'],
          'calculations':{'engine_version':'1.0','data_snapshot_hash':'abc',
                          'valuation_methods':['FCFF'], 'risk_methods':['CVaR']},
          'analysis':{'facts_with_citations':[{'claim':'a','source_ids':['official-1']}],
                      'assumptions':[],'counterarguments':[],'unknowns':[],
                      'thesis_falsifiers':[]},
          'decision':{'status':'RESEARCH_ONLY','recommended_action':'WAIT',
                      'requires_owner_review':True},
          'audit':{'audit_status':'PENDING','red_team_model_id':'other-provider',
                   'tool_trace_id':'trace-1'},
          'privileges':{'can_place_live_order':False,'can_override_policy':False}
        }
        self.assertTrue(Draft202012Validator(self.decision).is_valid(sample))
        sample['privileges']['can_place_live_order']=True
        self.assertFalse(Draft202012Validator(self.decision).is_valid(sample))

if __name__=='__main__':unittest.main()
