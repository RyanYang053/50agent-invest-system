"""Offline integration smoke test. No providers, LLMs, or brokers contacted."""
from __future__ import annotations
import json,tempfile
from pathlib import Path
from .ledger import EvidenceLedger
from .retrieval import ResearchIndex
from .events import EventBus
from .licenses import LicenseGate
from .risk import ResearchRiskGate

BASE=Path(__file__).resolve().parents[2]

def main():
    now='2026-11-23T18:00:00Z'
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        lic={'license_id':'SEC_PUBLIC','permitted_for_personal_analysis':True,'allow_local_retention':True,'allow_rag_indexing':True,'cloud_allowed':True}
        ledger=EvidenceLedger(root/'ev.sqlite')
        ev={'record_id':'fixture-filing-1','source_id':'sec','document_id':'fixture-only','security_id':'NASDAQ:TEST',
           'observed_at':'2026-09-30T00:00:00Z','published_at':'2026-11-22T12:00:00Z','available_at':'2026-11-22T12:00:00Z',
           'payload':{'reported_revenue_usd':10000000},'data_class':'public','license_id':'SEC_PUBLIC'}
        ledger.add_evidence(ev,policy=lic)
        rag=ResearchIndex(root/'rag.sqlite')
        rag.add({'doc_id':'fixture-paragraph','source_id':'sec','source_uri':'https://www.sec.gov/','security_id':'NASDAQ:TEST',
                 'available_at':'2026-11-22T12:00:00Z','scope':'public','license_id':'SEC_PUBLIC',
                 'content':'Fixture-only: financial report contained documented revenue figures.'},lic)
        rules=json.loads((BASE/'config/event rules.json').read_text())
        roles=json.loads((BASE/'config/50 agent manifest.json').read_text())
        bus=EventBus(root/'events.sqlite',rules,roles=roles)
        event=bus.submit({'event_type':'unauthorized_policy_change','signal_id':'fixture-policy'},verified=False,at=now)
        policy=json.loads((BASE/'config/investment policy template.json').read_text())
        risk=ResearchRiskGate().review(policy,{}, {'action':'BUY'},at=now)
        result={'fixture_only':True,'network_calls':0,'llm_calls':0,'broker_calls':0,
            'evidence_chain_valid':ledger.verify_evidence_integrity(),
            'citation_retrieval_count':len(rag.search('revenue',decision_at=now)),
            'p0_event_status':event['status'],'p0_agents':event['agents'],
            'thanksgiving_exchange_closed':not bus.market_status('2026-11-26T15:00:00Z')['is_open'],
            'draft_policy_advisory_trade_blocked':risk['status']=='BLOCK',
            'live_orders_enabled':False}
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if (result['evidence_chain_valid'] and result['citation_retrieval_count']==1 and result['p0_event_status']=='QUEUED' and result['thanksgiving_exchange_closed'] and result['draft_policy_advisory_trade_blocked']) else 2

if __name__=='__main__':raise SystemExit(main())
