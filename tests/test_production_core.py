import sys, json, tempfile, unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from atlas_pro.ledger import EvidenceLedger
from atlas_pro.retrieval import ResearchIndex
from atlas_pro.events import EventBus
from atlas_pro.feeds import PublicFeedClient
from atlas_pro.risk import ResearchRiskGate
from atlas_pro.models import ModelGateway
from atlas_pro.release import ReleaseRegistry
from atlas_pro.licenses import LicenseGate
from atlas_pro.ibkr_bridge import IBKRReadOnlyBridge

ROOT=Path(__file__).resolve().parents[1]
REG=json.loads((ROOT/'config/model registry.json').read_text())
ROLES=json.loads((ROOT/'config/50 agent manifest.json').read_text())
RULES=json.loads((ROOT/'config/event rules.json').read_text())
PUBLIC={'license_id':'SEC_PUBLIC','permitted_for_personal_analysis':True,'allow_local_retention':True,'allow_rag_indexing':True,'cloud_allowed':True}
PRIVATE={'license_id':'OWNER_PRIVATE','permitted_for_personal_analysis':True,'allow_local_retention':True,'allow_rag_indexing':True,'cloud_allowed':False}
FMP={'license_id':'FMP_PERSONAL','permitted_for_personal_analysis':True,'allow_local_retention':False,'allow_rag_indexing':False,'cloud_allowed':False}
NOW='2026-11-23T18:00:00Z'

class ProductionCore(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
    def ledger(self):return EvidenceLedger(self.base/'ev.sqlite')
    def index(self):return ResearchIndex(self.base/'rag.sqlite')
    def bus(self):return EventBus(self.base/'bus.sqlite',RULES,roles=ROLES)
    def gateway(self):return ModelGateway(self.base/'models.sqlite',REG,ROLES,daily_limit_usd='0.2',monthly_limit_usd='1')
    def evidence(self,record_id='r1',available_at='2026-11-21T18:00:00Z'):
        return {'record_id':record_id,'source_id':'edgar','document_id':'0000320193-26-001','security_id':'NASDAQ:AAPL',
            'observed_at':'2026-09-30T00:00:00Z','published_at':'2026-11-20T12:00:00Z','available_at':available_at,
            'payload':{'revenue':101.0},'data_class':'public','license_id':'SEC_PUBLIC'}
    def doc(self,doc_id='doc-1',scope='public'):
        return {'doc_id':doc_id,'source_id':'edgar','source_uri':'https://www.sec.gov/Archives/example','security_id':'NASDAQ:AAPL',
            'available_at':'2026-11-22T12:00:00Z','scope':scope,'license_id':'SEC_PUBLIC' if scope=='public' else 'OWNER_PRIVATE',
            'content':'Apple reports revenue from fiscal product sales; model estimates are not official forecasts.'}
    def test_bridge_replay_not_live(self):
        class Finance:
            @staticmethod
            def load_full_portfolio_snapshot():
                from types import SimpleNamespace
                return SimpleNamespace(positions_complete=True,advice_allowed=True,status='ok',accounts=('one','two'),as_of='2026-11-23',currency='CAD',snapshot_id='flex')
        class Broker:
            @staticmethod
            def latest_broker_snapshot():return {'status':'ok','capture_status':'replay','live_verified':False,'adapter':'offline_replay','as_of':NOW}
            @staticmethod
            def reconcile_live_to_flex():return {'status':'reconciled'}
        self.assertEqual(IBKRReadOnlyBridge(Finance,Broker).inspect()['status'],'RESTRICTED')
    def test_bridge_live_reconciled_readonly(self):
        from types import SimpleNamespace
        class Finance:
            @staticmethod
            def load_full_portfolio_snapshot():return SimpleNamespace(positions_complete=True,advice_allowed=True,status='ok',accounts=('one','two'),as_of='2026-11-23',currency='CAD',snapshot_id='flex')
        class Broker:
            @staticmethod
            def latest_broker_snapshot():return {'status':'ok','capture_status':'ok','live_verified':True,'adapter':'ibkr_tws_readonly','as_of':NOW,'snapshot_id':'broker'}
            @staticmethod
            def reconcile_live_to_flex():return {'status':'reconciled'}
        out=IBKRReadOnlyBridge(Finance,Broker).inspect()
        self.assertEqual(out['status'],'READ_ONLY_READY');self.assertFalse(out['can_place_order'])
    def test_bridge_broker_disconnected_restricts(self):
        from types import SimpleNamespace
        class Finance:
            @staticmethod
            def load_full_portfolio_snapshot():return SimpleNamespace(positions_complete=True,advice_allowed=True,status='ok',accounts=('one',),as_of='2026-11-23',currency='CAD',snapshot_id='flex')
        class Broker:
            @staticmethod
            def latest_broker_snapshot():return {'status':'unavailable','capture_status':'partial','live_verified':False}
            @staticmethod
            def reconcile_live_to_flex():return {'status':'unavailable'}
        self.assertEqual(IBKRReadOnlyBridge(Finance,Broker).inspect()['status'],'RESTRICTED')
    def test_fmp_license_cannot_train_or_archive_by_default(self):
        gate=LicenseGate({'fmp':{'query_personal':True,'index_persistent':False,'train_or_evaluate_model':False}})
        self.assertEqual(gate.authorize('fmp','query_personal')['status'],'ALLOW')
        self.assertEqual(gate.authorize('fmp','train_or_evaluate_model')['status'],'DENY')
        self.assertEqual(gate.authorize('fmp','index_persistent')['status'],'DENY')
    def test_unknown_data_provider_license_denied(self):
        self.assertEqual(LicenseGate({}).authorize('unknown','query_personal')['status'],'DENY')
    def test_personal_license_cannot_redistribute(self):
        g=LicenseGate({'data':{'query_personal':True,'redistribute':False}})
        self.assertEqual(g.authorize('data','query_personal',scope='commercial')['status'],'DENY')
    def test_append_asof_and_hashchain(self):
        l=self.ledger();self.assertEqual(l.add_evidence(self.evidence(),policy=PUBLIC)['status'],'ADDED')
        self.assertEqual(len(l.asof('NASDAQ:AAPL','2026-11-20T12:00:01Z')),0)
        self.assertEqual(len(l.asof('NASDAQ:AAPL',NOW)),1)
        self.assertTrue(l.verify_evidence_integrity())
    def test_duplicate_idempotent(self):
        l=self.ledger();r=self.evidence();l.add_evidence(r,policy=PUBLIC)
        self.assertEqual(l.add_evidence(r,policy=PUBLIC)['status'],'DUPLICATE')
    def test_duplicate_mutation_rejected(self):
        l=self.ledger();r=self.evidence();l.add_evidence(r,policy=PUBLIC);r['payload']['revenue']=300
        with self.assertRaises(ValueError):l.add_evidence(r,policy=PUBLIC)
    def test_revision_parent(self):
        l=self.ledger();r=self.evidence();r['revision_of']='missing'
        with self.assertRaises(ValueError):l.add_evidence(r,policy=PUBLIC)
    def test_revision_stored(self):
        l=self.ledger();l.add_evidence(self.evidence(),policy=PUBLIC)
        r=self.evidence('r2');r['revision_of']='r1';r['payload']={'revenue':102}
        l.add_evidence(r,policy=PUBLIC)
        self.assertEqual(len(l.asof('NASDAQ:AAPL',NOW)),2)
    def test_date_inconsistent(self):
        l=self.ledger();r=self.evidence();r['available_at']='2026-11-19T10:00:00Z'
        with self.assertRaises(ValueError):l.add_evidence(r,policy=PUBLIC)
    def test_naive_rejected(self):
        l=self.ledger();r=self.evidence();r['published_at']='2026-11-20T12:00:00'
        with self.assertRaises(ValueError):l.add_evidence(r,policy=PUBLIC)
    def test_fmp_data_retention_denied(self):
        l=self.ledger();r=self.evidence();r['license_id']='FMP_PERSONAL';r['data_class']='licensed'
        with self.assertRaises(PermissionError):l.add_evidence(r,policy=FMP)
    def test_unknown_license_denied(self):
        with self.assertRaises(PermissionError):self.ledger().add_evidence(self.evidence(),policy=PRIVATE)
    def test_private_no_cloud_policy(self):
        r=self.evidence();r['data_class']='private';r['license_id']='OWNER_PRIVATE'
        with self.assertRaises(PermissionError):self.ledger().add_evidence(r,policy=PUBLIC|{'license_id':'OWNER_PRIVATE'})
    def test_integrity_tamper_detected(self):
        import sqlite3
        l=self.ledger();l.add_evidence(self.evidence(),policy=PUBLIC)
        with sqlite3.connect(l.path) as c:c.execute("UPDATE evidence SET payload_json=? WHERE record_id='r1'",('{}',))
        self.assertFalse(l.verify_evidence_integrity())
    def test_rag_public_pit(self):
        idx=self.index();idx.add(self.doc(),PUBLIC)
        self.assertEqual(idx.search('revenue',decision_at='2026-11-21T00:00:00Z'),[])
        results=idx.search('revenue',decision_at=NOW)
        self.assertEqual(len(results),1);self.assertTrue(results[0]['untrusted_source_text']);self.assertIn('source_uri',results[0])
    def test_rag_license_deny(self):
        d=self.doc();d['license_id']='FMP_PERSONAL'
        with self.assertRaises(PermissionError):self.index().add(d,FMP)
    def test_rag_private_cloud_isolation(self):
        idx=self.index();d=self.doc('private-a','private');d['content']='confidential proprietary portfolio wealth'
        idx.add(d,PRIVATE)
        self.assertEqual(idx.search('confidential',decision_at=NOW,scope='public_only'),[])
        self.assertEqual(len(idx.search('confidential',decision_at=NOW,scope='private_local')),1)
    def test_rag_duplicate_immutability(self):
        idx=self.index();d=self.doc();idx.add(d,PUBLIC)
        self.assertEqual(idx.add(d,PUBLIC),'DUPLICATE')
        d['content']='new overwrite'
        with self.assertRaises(ValueError):idx.add(d,PUBLIC)
    def test_rag_private_embeddings_must_be_certified_local(self):
        idx=self.index();d=self.doc('private-embed','private')
        with self.assertRaises(PermissionError):idx.add(d,PRIVATE,embed=lambda text:[1.0,0.0])
        def local_embedding(text):return [1.0,0.0]
        local_embedding.local_only=True
        self.assertEqual(idx.add(d,PRIVATE,embed=local_embedding),'ADDED')
        with self.assertRaises(PermissionError):idx.search('revenue',decision_at=NOW,scope='private_local',embed=lambda text:[1.0,0.0])
        self.assertEqual(len(idx.search('revenue',decision_at=NOW,scope='private_local',embed=local_embedding)),1)
    def test_rag_sql_injection_like_query_safe(self):
        idx=self.index();idx.add(self.doc(),PUBLIC)
        self.assertIsInstance(idx.search('" OR SELECT * FROM docs;--',decision_at=NOW),list)
    def test_rag_optional_vector(self):
        idx=self.index();vec=lambda text: [1.0,0.0] if 'revenue' in text.lower() else [0.0,1.0]
        idx.add(self.doc(),PUBLIC,embed=vec)
        self.assertGreaterEqual(len(idx.search('revenue',decision_at=NOW,embed=vec)),1)
    def test_event_unauthorized_policy_p0_routes_only_deterministic(self):
        r=next(x for x in RULES if x['event_type']=='unauthorized_policy_change')
        b=self.bus();out=b.submit({'event_type':'unauthorized_policy_change','signal_id':'intrusion'},verified=False,at=NOW)
        self.assertEqual(out['status'],'QUEUED')
        self.assertEqual(set(out['agents']),set(r['primary_agents']))
        self.assertTrue(all(next(a for a in ROLES if a['agent_id']==aid)['primary_model']=='deterministic' for aid in out['agents']))
    def test_event_holiday(self):
        self.assertFalse(self.bus().market_status('2026-11-26T15:00:00Z')['is_open'])
    def test_event_early_close(self):
        s=self.bus().market_status('2026-11-27T17:00:00Z');self.assertTrue(s['early_close']);self.assertTrue(s['is_open'])
        self.assertFalse(self.bus().market_status('2026-11-27T19:00:00Z')['is_open'])
    def test_event_normal_day(self):
        self.assertTrue(self.bus().market_status('2026-11-23T15:00:00Z')['is_open'])
    def test_event_future_block(self):
        r=next(x for x in RULES if x['requires_verified_event'] and x['priority']!='P0')
        e={'event_type':r['event_type'],'source_event_id':'filing-x','published_at':'2026-12-01T00:00:00Z'}
        self.assertEqual(self.bus().submit(e,verified=True,at=NOW)['status'],'FUTURE_EVENT')
    def test_event_unverified_block(self):
        r=next(x for x in RULES if x['requires_verified_event'])
        self.assertEqual(self.bus().submit({'event_type':r['event_type'],'source_event_id':'event1'},verified=False,at=NOW)['status'],'UNVERIFIED')
    def test_event_idempotency(self):
        r=next(x for x in RULES if x['priority']=='P2')
        e={'event_type':r['event_type'],'source_event_id':'source123'}
        b=self.bus();first=b.submit(e,verified=True,at=NOW);second=b.submit(e,verified=True,at=NOW)
        self.assertEqual(first['status'],'QUEUED');self.assertEqual(second['status'],'DUPLICATE')
    def test_event_p0_reentry_after_window(self):
        r=next(x for x in RULES if x['priority']=='P0')
        e={'event_type':r['event_type'],'signal_id':'margin'}
        b=self.bus();first=b.submit(e,verified=False,at=NOW)
        self.assertEqual(first['status'],'QUEUED')
        self.assertEqual(b.submit(e,verified=False,at=NOW)['status'],'P0_ALREADY_ACTIVE')
        self.assertEqual(b.submit(e,verified=False,at='2026-11-23T18:00:20Z')['status'],'QUEUED')
    def test_event_unknown_rejected(self):
        self.assertEqual(self.bus().submit({'event_type':'NOPE'},verified=True,at=NOW)['status'],'UNKNOWN_EVENT')
    def test_event_priority(self):
        b=self.bus();r0=next(x for x in RULES if x['priority']=='P0');r2=next(x for x in RULES if x['priority']=='P2')
        b.submit({'event_type':r2['event_type'],'source_event_id':'x1'},verified=True,at=NOW)
        b.submit({'event_type':r0['event_type'],'signal_id':'risk'},verified=False,at=NOW)
        self.assertEqual(json.loads(b.fetch_pending()[0]['payload_json'])['priority'],'P0')
    def test_provider_sec_requires_ua(self):
        feed=PublicFeedClient(lambda url,h:{'ok':True})
        with self.assertRaises(ValueError):feed.sec_companyfacts(320193)
    def test_provider_sec_cik_normalized(self):
        seen=[];f=PublicFeedClient(lambda u,h: seen.append((u,h)) or {'ok':True},sec_user_agent='Atlas Research research@example.com')
        f.sec_companyfacts(320193)
        self.assertIn('CIK0000320193.json',seen[0][0]);self.assertIn('User-Agent',seen[0][1])
    def test_provider_alfred_pit(self):
        seen=[];f=PublicFeedClient(lambda u,h:seen.append(u) or {'observations':[]},fred_api_key='test-token')
        f.alfred_vintage('GDP','2024-11-01')
        self.assertIn('realtime_start=2024-11-01',seen[0]);self.assertIn('realtime_end=2024-11-01',seen[0])
    def test_provider_ssrf_block(self):
        f=PublicFeedClient(lambda url,h:{})
        for url in ('https://127.0.0.1/secret','http://data.sec.gov/private','https://api.stlouisfed.org.evil.com/q'):
            with self.subTest(url=url),self.assertRaises(ValueError):f._fetch(url)
    def test_provider_boc_validation(self):
        f=PublicFeedClient(lambda u,h:{'observations':[]})
        self.assertIn('FXUSDCAD',str(f.boc_observations())) if False else self.assertEqual(f.boc_observations()['observations'],[])
    def test_model_without_evals_fail_closed(self):
        g=self.gateway();role=next(x for x in ROLES if x['primary_model']=='gpt-6.2-sol')
        out=g.select_and_reserve(request_id='x',role_id=role['agent_id'],task_set='finance',data_scope='public_only',at=NOW,input_tokens=500,output_tokens=300)
        self.assertEqual(out['status'],'NO_CURRENT_CERTIFIED_MODEL')
    def test_model_certification_requires_external_report(self):
        g=self.gateway();role=next(x for x in ROLES if x['primary_model']=='gpt-6.2-sol')
        with self.assertRaises(ValueError):g.certify(role['agent_id'],'gpt-6.2-sol','finance',0.95,0.9,at=NOW,valid_until='2026-12-23T00:00:00Z',provenance={})
    def test_concurrent_model_cost_budget_fail_closed(self):
        role=next(x for x in ROLES if x['primary_model']=='gpt-6.2-sol')
        g=ModelGateway(self.base/'concurrent.sqlite',REG,ROLES,daily_limit_usd='0.05',monthly_limit_usd='1')
        g.certify(role['agent_id'],'gpt-6.2-sol','finance',0.97,0.9,at=NOW,valid_until='2026-12-23T00:00:00Z',provenance={'external_eval_report':'fixture','locked_testset_hash':'fixture'})
        def attempt(i):
            return g.select_and_reserve(request_id=f'concurrent-{i}',role_id=role['agent_id'],task_set='finance',data_scope='public_only',at=NOW,input_tokens=5000,output_tokens=3000)['status']
        with ThreadPoolExecutor(max_workers=8) as pool: statuses=list(pool.map(attempt,range(10)))
        self.assertEqual(statuses.count('RESERVED'),1)
        self.assertEqual(statuses.count('COST_BUDGET_BLOCK'),9)
    def test_model_certification_expiry(self):
        role=next(x for x in ROLES if x['primary_model']=='gpt-6.2-sol');g=self.gateway()
        g.certify(role['agent_id'],'gpt-6.2-sol','finance',0.97,0.9,at='2026-11-01T00:00:00Z',valid_until='2026-11-02T00:00:00Z',provenance={'external_eval_report':'fixture','locked_testset_hash':'fixture'})
        r=g.select_and_reserve(request_id='exp',role_id=role['agent_id'],task_set='finance',data_scope='public_only',at=NOW,input_tokens=1000,output_tokens=1000)
        self.assertEqual(r['status'],'NO_CURRENT_CERTIFIED_MODEL')
    def test_model_prices_change_after_2026(self):
        role=next(x for x in ROLES if x['primary_model']=='gemini-3.8-flash');g=self.gateway()
        x=g._quote('gemini-3.8-flash',1000000,1000000,__import__('datetime').datetime.fromisoformat('2026-11-23T00:00:00+00:00'))
        y=g._quote('gemini-3.8-flash',1000000,1000000,__import__('datetime').datetime.fromisoformat('2027-01-02T00:00:00+00:00'))
        self.assertEqual(y,2*x)
    def test_event_refuse_p0_without_manifest(self):
        r=next(x for x in RULES if x['priority']=='P0')
        bus=EventBus(self.base/'badbus.sqlite',RULES)
        with self.assertRaises(ValueError):bus.submit({'event_type':r['event_type'],'signal_id':'x'},verified=False,at=NOW)
    def test_stale_fts_never_leaks_future_docs(self):
        idx=self.index();d=self.doc();d['available_at']='2027-01-01T12:00:00Z';idx.add(d,PUBLIC)
        self.assertEqual(idx.search('revenue',decision_at=NOW),[])
    def test_private_local_model_requires_compute_cost(self):
        role=next(x for x in ROLES if x['primary_model']=='local-private')
        g=self.gateway()
        g.certify(role['agent_id'],'local-private','private_test',0.98,0.95,at=NOW,valid_until='2026-12-23T00:00:00Z',provenance={'external_eval_report':'fixture','locked_testset_hash':'fixture'})
        out=g.select_and_reserve(request_id='private1',role_id=role['agent_id'],task_set='private_test',data_scope='private_only',at=NOW,input_tokens=500,output_tokens=300)
        self.assertEqual(out['status'],'NO_CURRENT_CERTIFIED_MODEL')
        local=ModelGateway(self.base/'local.sqlite',REG,ROLES,daily_limit_usd='5',monthly_limit_usd='100',local_cost_input_usd_per_m='0.1',local_cost_output_usd_per_m='0.3')
        local.certify(role['agent_id'],'local-private','private_test',0.98,0.95,at=NOW,valid_until='2026-12-23T00:00:00Z',provenance={'external_eval_report':'fixture','locked_testset_hash':'fixture'})
        out=local.select_and_reserve(request_id='private1',role_id=role['agent_id'],task_set='private_test',data_scope='private_only',at=NOW,input_tokens=500,output_tokens=300)
        self.assertEqual(out['status'],'RESERVED');self.assertEqual(out['model'],'local-private')
    def test_model_cost_reservation(self):
        g=self.gateway();role=next(x for x in ROLES if x['primary_model']=='gpt-6.2-sol')
        g.certify(role['agent_id'],'gpt-6.2-sol','finance',0.97,0.9,at=NOW,valid_until='2026-12-23T00:00:00Z',provenance={'external_eval_report':'fixture','locked_testset_hash':'fixture'})
        d={'request_id':'x','role_id':role['agent_id'],'task_set':'finance','data_scope':'public_only','at':NOW,'input_tokens':1000,'output_tokens':1000}
        self.assertEqual(g.select_and_reserve(**d)['status'],'RESERVED')
        self.assertEqual(g.select_and_reserve(**d)['status'],'ALREADY_RESERVED')
    def test_model_cost_limit(self):
        g=self.gateway();role=next(x for x in ROLES if x['primary_model']=='gpt-6.2-sol')
        g.certify(role['agent_id'],'gpt-6.2-sol','finance',0.97,0.9,at=NOW,valid_until='2026-12-23T00:00:00Z',provenance={'external_eval_report':'fixture','locked_testset_hash':'fixture'})
        out=g.select_and_reserve(request_id='huge',role_id=role['agent_id'],task_set='finance',data_scope='public_only',at=NOW,input_tokens=300000,output_tokens=100000)
        self.assertEqual(out['status'],'COST_BUDGET_BLOCK')
    def test_release_requires_signed_approval(self):
        r=ReleaseRegistry(self.base/'rel.sqlite');p={'release_id':'v2','artifact_sha256':'x','evaluation_id':'e','shadow_id':'s','quality_pass':True,'risk_pass':True,'license_pass':True,'owner_approved':True}
        with self.assertRaises(PermissionError):r.promote(p,'bad',secret=b'owner-secret',at=NOW)
        sig=r.signature(b'owner-secret',p)
        self.assertEqual(r.promote(p,sig,secret=b'owner-secret',at=NOW),'PROMOTED')
    def test_release_kill_switch(self):
        r=ReleaseRegistry(self.base/'rel.sqlite');r.stop();self.assertFalse(r.enabled())
    def mandate(self):
        return {'status':'ACTIVE_APPROVED','owner_approval':{'approved':True},'limits':{'max_single_stock_weight':0.2,'max_correlated_cluster_weight':0.4,'max_economic_leverage':1.2,'max_gross_economic_leverage':1.4,'min_cash_reserve_weight':0.05}}
    def snap(self):
        return {'all_configured_accounts_present':True,'reconciled':True,'same_asof':True,'fx_converted_to_base':True,'quote_entitled_and_qualified':True,'broker_permissions_verified':True,'balances_asof':NOW,'positions_asof':NOW,'margin_asof':NOW,'quote_asof':NOW,'stress_tests_complete':True}
    def proposal(self):
        return {'action':'BUY','post_single_stock_weight':'0.1','post_cluster_weight':'0.2','post_economic_leverage':'1.1','post_gross_economic_leverage':'1.2','post_cash_weight':'0.1','evidence_ids':['ev-1'],'risk_engine_version':'unit','independent_countercase_passed':True,'tax_review_complete':True}
    def test_risk_gate_readonly(self):
        r=ResearchRiskGate().review(self.mandate(),self.snap(),self.proposal(),at=NOW)
        self.assertEqual(r['status'],'ADVISORY_RESEARCH_PASSED');self.assertFalse(r['can_place_order'])
    def test_risk_aged_margin_blocks(self):
        s=self.snap();s['margin_asof']='2026-11-23T17:00:00Z'
        self.assertIn('STALE_MARGIN_ASOF',ResearchRiskGate().review(self.mandate(),s,self.proposal(),at=NOW)['reasons'])
    def test_risk_stale_quote_blocks(self):
        s=self.snap();s['quote_asof']='2026-11-23T17:30:00Z'
        self.assertIn('STALE_QUOTE_ASOF',ResearchRiskGate().review(self.mandate(),s,self.proposal(),at=NOW)['reasons'])
    def test_risk_unapproved_mandate(self):
        m=self.mandate();m['owner_approval']['approved']=False
        self.assertEqual(ResearchRiskGate().review(m,self.snap(),self.proposal(),at=NOW)['status'],'BLOCK')
    def test_risk_concentration(self):
        p=self.proposal();p['post_single_stock_weight']='0.8'
        self.assertIn('LIMIT_CONCENTRATION',ResearchRiskGate().review(self.mandate(),self.snap(),p,at=NOW)['reasons'])
    def test_risk_missing_inputs(self):
        r=ResearchRiskGate().review(self.mandate(),{}, {}, at=NOW)
        self.assertEqual(r['status'],'BLOCK');self.assertFalse(r['can_place_order'])
    def test_risk_broker_permissions(self):
        s=self.snap();s['broker_permissions_verified']=False
        self.assertIn('BROKER_MARKET_PERMISSIONS_UNKNOWN',ResearchRiskGate().review(self.mandate(),s,self.proposal(),at=NOW)['reasons'])
    def test_risk_countercase(self):
        p=self.proposal();p['independent_countercase_passed']=False
        self.assertIn('COUNTERCASE_NOT_VERIFIED',ResearchRiskGate().review(self.mandate(),self.snap(),p,at=NOW)['reasons'])

if __name__=='__main__':unittest.main()
