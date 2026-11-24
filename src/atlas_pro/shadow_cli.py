"""Local shadow experiment lifecycle; no broker or trading access."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from .committee import Committee
from .ledger import EvidenceLedger
from .shadow import ShadowJournal
from .return_feed import TiingoEOD


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--journal',type=Path,required=True)
    cmds=p.add_subparsers(dest='cmd',required=True)
    s=cmds.add_parser('start');s.add_argument('--committee',type=Path,required=True);s.add_argument('--run-id',required=True);s.add_argument('--plan',type=Path,required=True);s.add_argument('--confirm',action='store_true')
    for name in ('report','append','tick-tiingo'):
        q=cmds.add_parser(name);q.add_argument('plan_id')
        if name!='report':q.add_argument('--evidence',type=Path,required=True)
        if name=='append':q.add_argument('--observation',type=Path,required=True)
        if name=='tick-tiingo':q.add_argument('--licence',type=Path,required=True);q.add_argument('--network',action='store_true')
    compare=cmds.add_parser('compare');compare.add_argument('champion_id');compare.add_argument('challenger_id');compare.add_argument('--trial-count',type=int,required=True);compare.add_argument('--max-drawdown',type=float,required=True)
    a=p.parse_args(argv);j=ShadowJournal(a.journal)
    if a.cmd=='start':
        plan=json.loads(a.plan.read_text());expected={'targets','benchmark','source_bindings','anchor','end','cost_bps','synthetic'}
        if not expected.issubset(plan) or set(plan)-expected-{'forecast','risk_refresh'}:raise ValueError('invalid plan fields')
        result={'plan_id':j.start(Committee(a.committee),a.run_id,operator_confirmed=a.confirm,**plan),'can_trade':False}
    elif a.cmd=='report':result=j.report(a.plan_id)
    elif a.cmd=='compare':result=j.compare(a.champion_id,a.challenger_id,trial_count=a.trial_count,max_drawdown=a.max_drawdown)
    elif a.cmd=='append':
        row=json.loads(a.observation.read_text())
        if set(row)!={'session_close','evidence_by_security'}:raise ValueError('invalid observation fields')
        result=j.append(a.plan_id,EvidenceLedger(a.evidence),**row)
    else:result=TiingoEOD(json.loads(a.licence.read_text()),network=a.network).tick(j,EvidenceLedger(a.evidence),a.plan_id)
    print(json.dumps(result,indent=2,allow_nan=False));return 0

if __name__=='__main__':raise SystemExit(main())
