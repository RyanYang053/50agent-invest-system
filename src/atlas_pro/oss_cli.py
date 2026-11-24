"""Operator-only import of normalized upstream artifacts; no network, no execution."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from .oss_adapters import artifact_json,qlib_predictions,lean_equity_review,inspect_responses,duckdb_pit
from .ledger import EvidenceLedger
from .performance import paired_performance
from .promotion import compare_challenger


def run_job(job,*,evidence=None):
    kind=job['kind'];p=job['payload']
    if kind=='qlib':
        if evidence is None:raise ValueError('authoritative ledger required')
        return qlib_predictions(**p,evidence_lookup=evidence.resolve_ids)
    if kind=='lean':return lean_equity_review(**p)
    if kind=='inspect':return inspect_responses(**p)
    if kind=='performance':return paired_performance(**p)
    if kind=='challenger':return compare_challenger(**p)
    if kind=='duckdb':return duckdb_pit(**p)
    raise ValueError('unknown research import kind')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('artifact',type=Path);ap.add_argument('--sha256',required=True);ap.add_argument('--evidence',type=Path)
    a=ap.parse_args();job=artifact_json(a.artifact,a.sha256);result=run_job(job,evidence=EvidenceLedger(a.evidence) if a.evidence else None)
    print(json.dumps(result,indent=2,allow_nan=False));return 0

if __name__=='__main__':raise SystemExit(main())
