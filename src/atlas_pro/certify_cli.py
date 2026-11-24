"""Operator-only regrading of an external locked model evaluation.
No inference, no brokerage, no automatic certification of synthetic fixtures.
Run the provider evaluation in an isolated external environment (e.g. Inspect AI).
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
from datetime import datetime,timezone
from .models import ModelGateway
from .oss_adapters import artifact_json


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry',type=Path,required=True);p.add_argument('--roles',type=Path,required=True);p.add_argument('--journal',type=Path,required=True)
    p.add_argument('--cases',type=Path,required=True);p.add_argument('--cases-sha256',required=True);p.add_argument('--answers',type=Path,required=True);p.add_argument('--answers-sha256',required=True)
    p.add_argument('--locked-hash',required=True,help='Precommitted canonical case-set SHA-256, not a hash selected after evaluation')
    p.add_argument('--role',required=True);p.add_argument('--model',required=True);p.add_argument('--task-set',required=True);p.add_argument('--valid-until',required=True);p.add_argument('--confirm-independent-evaluation',action='store_true')
    a=p.parse_args(argv)
    if not a.confirm_independent_evaluation:raise PermissionError('operator confirmation of independent evaluation and data rights required')
    cases=artifact_json(a.cases,a.cases_sha256);answers=artifact_json(a.answers,a.answers_sha256)
    g=ModelGateway(a.journal,json.loads(a.registry.read_text()),json.loads(a.roles.read_text()))
    result=g.certify_measured(a.role,a.model,a.task_set,cases,answers,locked_hash=a.locked_hash,at=datetime.now(timezone.utc).isoformat(),valid_until=a.valid_until,operator_verified=True)
    print(json.dumps(result,indent=2,allow_nan=False));return 0 if result['passed'] else 2

if __name__=='__main__':raise SystemExit(main())
