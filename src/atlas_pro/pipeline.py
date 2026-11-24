"""A usable operator-side, research-only stock screen with SEC ingestion.
Explicit market snapshot JSON, no fabricated quotes/shares or full-universe claims.
"""
from __future__ import annotations
import json, os, argparse
from pathlib import Path
from datetime import datetime,timezone
from .feeds import PublicFeedClient, ProviderUnavailable
from .transport import PublicJSONTransport
from .research import sec_annual_facts,annual_snapshot,screen
from .ledger import EvidenceLedger,digest,iso
from .retrieval import ResearchIndex
from .market_data import AlpacaResearchQuotes,outstanding_shares


def run_screen(universe, *, client, ledger, index, policy, at, replay=False, received_at=None, quotes=None):
    if policy.get('license_id')!='SEC_PUBLIC' or policy.get('permitted_for_personal_analysis') is not True:
        raise PermissionError('explicit SEC data policy required')
    if not isinstance(universe,list) or not 1<=len(universe)<=100:raise ValueError('universe must contain 1–100 securities')
    if len({(u['cik'],u['symbol']) for u in universe})!=len(universe):raise ValueError('duplicate universe members')
    candidates=[]; rejected=[]
    for entry in universe:
        try:
            cik=int(entry['cik']); symbol=str(entry['symbol'])
            cf=client.sec_companyfacts(cik); sub=client.sec_submissions(cik)
            receipt=received_at or datetime.now(timezone.utc).isoformat()
            decision_at=at if replay or received_at else receipt
            rows=sec_annual_facts(cf,sub,at=decision_at,received_at=receipt,replay=replay)
            snap=annual_snapshot(rows,at=decision_at)
            if snap:
                for row in snap['sources'].values():
                    rid=digest(row)
                    ledger.add_evidence({'record_id':rid,'source_id':'sec_edgar','document_id':row['accession'],'security_id':f'CIK:{cik}',
                        'observed_at':row['end']+'T00:00:00Z','published_at':row['published_at'],'available_at':row['available_at'],
                        'payload':row,'data_class':'public','license_id':'SEC_PUBLIC'},policy=policy)
                    index.add({'doc_id':rid,'source_id':'sec_edgar','source_uri':f'https://www.sec.gov/Archives/edgar/data/{cik}/{row["accession"].replace("-", "")}/',
                        'security_id':f'CIK:{cik}','available_at':row['available_at'],'scope':'public','license_id':'SEC_PUBLIC',
                        'content':f'{symbol} annual {row["field"]} ({row["tag"]}) {row["value"]} USD for period ending {row["end"]}. Filing accession {row["accession"]}. Structured fact, not a verbatim filing quote.'},policy)
            market=entry.get('market') or {}
            if quotes is not None:
                if replay:raise ValueError('current quote forbidden in replay')
                q=quotes.quote(symbol,at=received_at)
                decision_at=q['available_at']
                shares=outstanding_shares(cf,sub,at=decision_at)
                if shares:
                    qid=digest(q); sid=digest(shares|{'available_at':receipt})
                    ledger.add_evidence({'record_id':qid,'source_id':'alpaca_iex','document_id':qid,'security_id':f'CIK:{cik}',
                        'observed_at':q['price_asof'],'published_at':q['price_asof'],'available_at':q['available_at'],
                        'payload':q,'data_class':'licensed','license_id':'ALPACA_PERSONAL'},policy=quotes.policy)
                    ledger.add_evidence({'record_id':sid,'source_id':'sec_edgar','document_id':shares['accession'],'security_id':f'CIK:{cik}',
                        'observed_at':shares['shares_asof'],'published_at':shares['published_at'],'available_at':receipt,
                        'payload':shares,'data_class':'public','license_id':'SEC_PUBLIC'},policy=policy)
                    market=q|shares|{'qualified_research_data':True,'security_type':entry.get('security_type'),'sector_class':entry.get('sector_class'),'evidence_ids':[qid,sid]}
                else:market={}
            if market.get('symbol')!=symbol or market.get('cik')!=cik:
                result={'status':'INSUFFICIENT_DATA','reasons':['market identity mismatch']}
            else:
                # External market evidence must have been registered by operator before screen.
                if quotes is None:
                    records=ledger.asof(f'CIK:{cik}',decision_at,include_private=True,max_rows=500)
                    ids={r['record_id'] for r in records}
                    if not market.get('evidence_ids') or not set(market['evidence_ids']).issubset(ids):
                        market=market|{'qualified_research_data':False}
                result=screen(snap,market,at=decision_at)
            if result['status']=='CANDIDATE':candidates.append(result|{'decision_at':decision_at})
            else:rejected.append({'symbol':symbol,'reasons':result['reasons']})
        except (ValueError,KeyError,TypeError,ProviderUnavailable) as exc:
            rejected.append({'symbol':entry.get('symbol','unknown'),'reasons':[type(exc).__name__]})
    return {'mode':'HISTORICAL_PROXY' if replay else 'LIVE_RESEARCH','candidate_count':len(candidates),'universe_count':len(universe),
        'candidates':sorted(candidates,key=lambda r:(-r['score'],r['symbol'])),'rejected':rejected,'can_trade':False,
        'limitations':['operator supplied universe; no claim of delisting or historical constituent coverage','SEC companyfacts/submissions coverage limited','market snapshot qualification and licensing must be independently verified','research rankings only; no broker calls']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('universe',type=Path);p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--policy',type=Path,required=True);p.add_argument('--alpaca-policy',type=Path)
    args=p.parse_args(); quotes=AlpacaResearchQuotes(policy=json.loads(args.alpaca_policy.read_text())) if args.alpaca_policy else None; args.data_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
    result=run_screen(json.loads(args.universe.read_text()),client=PublicFeedClient(PublicJSONTransport(),sec_user_agent=os.environ.get('SEC_USER_AGENT','')),
        ledger=EvidenceLedger(args.data_dir/'evidence.sqlite'),index=ResearchIndex(args.data_dir/'research.sqlite'),policy=json.loads(args.policy.read_text()),at=datetime.now(timezone.utc).isoformat(),quotes=quotes)
    print(json.dumps(result,indent=2,allow_nan=False))
    return 0 if result['candidate_count'] else 2

if __name__=='__main__':raise SystemExit(main())
