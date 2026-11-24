"""Resumable research packet workflow, using Atlas's real deterministic modules.
Public research memos and independent review supplied separately by authorized
operators/validated model runtime. No credentials, orders or strategy promotion.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
from .ledger import EvidenceLedger,digest,iso
from .pipeline import market_evidence_matches
from .research import annual_snapshot,screen
from .decision import decision_grid
from .portfolio import portfolio_review
from .committee import Committee,STAGES


def run_packet(committee,ledger,packet,*,attachments=None):
    """Freeze all economic inputs, resume as independent artifacts become available.
    Attachments are not part of the base packet; once accepted they are immutable.
    Only WAIT can result. The operator, not a model, attests account/market inputs.
    """
    a=attachments or {}; at=iso(packet['decision_at']).isoformat(); cik=int(packet['cik']); sid=f'CIK:{cik}'
    if packet['market']['cik']!=cik:raise ValueError('security mismatch')
    rid=committee.start(security_id=sid,at=at,policy_hash=digest(packet['policy']),strategy_version=packet['strategy_version'],input_hash=digest(packet))
    safe=lambda x:x|{'can_trade':False}
    def evidence(key,req,prior):
        records=ledger.resolve_ids(packet['fundamental_ids'],security_id=sid,decision_at=at)
        for r in records:
            if r['source_id']!='sec_edgar' or r['record_id']!=digest(r['payload']) or r['payload'].get('cik')!=cik or iso(r['payload']['available_at'])!=iso(r['available_at']):raise ValueError('fundamental evidence mismatch')
        if not market_evidence_matches(ledger,packet['market'],cik=cik,at=at):raise ValueError('market evidence mismatch')
        return safe({'status':'OK','facts':[r['payload'] for r in records],'fundamental_ids':packet['fundamental_ids'],'market_ids':packet['market']['evidence_ids']})
    def discovery(key,req,prior):
        snap=annual_snapshot(prior['evidence']['facts'],at=at);candidate=screen(snap,packet['market'],at=at)
        return safe(candidate|{'snapshot':snap})
    def fundamental(key,req,prior):return safe({'status':'OK','snapshot':prior['discovery']['snapshot'],'evidence_ids':prior['discovery']['fundamental_evidence_ids']})
    def valuation(key,req,prior):
        return decision_grid(candidate=prior['discovery'],assumptions=packet['assumptions'],terminal_scenarios=packet['terminal_scenarios'],quote_price=packet['market']['price'],benchmark_return=packet['benchmark_return'],at=at,horizon_days=packet.get('horizon_days',365),cost_fraction=packet.get('cost_fraction',0))
    def memo(stage):
        def handler(key,req,prior):
            r=a[stage]
            if r.get('status')!='RESEARCH_MEMO' or not r.get('researcher_id') or not r.get('claim') or not r.get('evidence_ids') or r.get('can_trade') is not False:
                raise ValueError('invalid research memo')
            ledger.resolve_ids(r['evidence_ids'],security_id=sid,decision_at=at)
            return r
        return handler
    def verify(key,req,prior):
        r=a['verification']
        if r.get('status')!='VERIFIED' or r.get('claims_verified') is not True or r.get('can_trade') is not False:raise ValueError('independent verification required')
        return r
    def risk(key,req,prior):
        if packet['policy'].get('status')!='ACTIVE_APPROVED' or packet['policy'].get('owner_approval',{}).get('approved') is not True:return safe({'status':'BLOCK','reason':'POLICY_UNAPPROVED'})
        return portfolio_review(packet['portfolio'],packet['target_weights'],packet['aligned_returns'],packet['clusters'],packet['policy']['limits'],at=at,stress_scenarios=packet['stress_scenarios'])
    def decide(key,req,prior):return safe({'status':'RESEARCH_ONLY','decision':'WAIT','position_size':None,'valuation_id':prior['valuation']['decision_id'],'risk_id':prior['portfolio_risk']['risk_id'],'reason':'unvalidated scenario probabilities; independent execution approval not provided'})
    def post(key,req,prior):return safe({'status':'PLAN_ONLY','decision_hash':digest(prior['decision']),'forecast_horizon_days':packet.get('horizon_days',365),'forecast_recorded':False,'reason':'do not record unvalidated probabilities as certified forecasts'})
    handlers={'evidence':evidence,'discovery':discovery,'fundamental':fundamental,'valuation':valuation,'portfolio_risk':risk,'decision':decide,'postmortem_plan':post}
    handlers.update({s:memo(s) for s in ('bull','bear') if s in a})
    if 'verification' in a:handlers['verification']=verify
    for _ in range(len(STAGES)+1):
        result=committee.advance(rid,handlers)
        if result['status']!='CHECKPOINTED':break
    return result|{'run_id':rid,'completed_stages':[s for s in STAGES if s in committee.state(rid)[1]],'can_trade':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('packet',type=Path);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--journal',type=Path,required=True);p.add_argument('--attachments',type=Path)
    args=p.parse_args(); r=run_packet(Committee(args.journal),EvidenceLedger(args.evidence),json.loads(args.packet.read_text()),attachments=json.loads(args.attachments.read_text()) if args.attachments else None)
    print(json.dumps(r,indent=2,allow_nan=False));return 0 if r['status']=='COMPLETE_RESEARCH_ONLY' else 2
if __name__=='__main__':raise SystemExit(main())
