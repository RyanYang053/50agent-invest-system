"""Trusted local operator console; never expose this CLI as a model tool."""
from __future__ import annotations
import argparse,json,os
from pathlib import Path
from .core_service import private_dir
from .ledger import EvidenceLedger
from .agent_memory import MemoryStore,DOMAINS
from .independent_review import load_trust

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir",required=True,type=Path)
    p.add_argument("--trust",type=Path)
    s=p.add_subparsers(dest="cmd",required=True)
    s.add_parser("catalog")
    for name in ("stats","propose","approve","revoke","search","share"):
        x=s.add_parser(name);x.add_argument("role",choices=sorted(DOMAINS))
        if name=="propose":x.add_argument("--input",type=Path,required=True)
        if name=="approve":x.add_argument("note");x.add_argument("--review",type=Path,required=True)
        if name=="revoke":x.add_argument("note")
        if name=="search":x.add_argument("query");x.add_argument("--security",required=True)
        if name=="share":x.add_argument("--from-role",choices=sorted(DOMAINS),required=True);x.add_argument("note");x.add_argument("--topic",required=True)
    a=p.parse_args();os.umask(0o077);d=private_dir(a.data_dir)
    store=MemoryStore(d/"agent-memory",EvidenceLedger(d/"evidence.sqlite"),trust=load_trust(a.trust) if a.trust else {})
    if a.cmd=="catalog":out=[store.bind(r).stats() for r in sorted(DOMAINS)]
    else:
        m=store.bind(a.role)
        if a.cmd=="stats":out=m.stats()
        elif a.cmd=="propose":out={"note_id":m.propose(**json.loads(a.input.read_text())),"status":"QUARANTINED"}
        elif a.cmd=="approve":m.approve(a.note,json.loads(a.review.read_text()));out={"status":"APPROVED"}
        elif a.cmd=="revoke":m.revoke(a.note);out={"status":"REVOKED"}
        elif a.cmd=="share":out={"note_id":m.propose_share(store.bind(a.from_role),a.note,topic=a.topic),"status":"QUARANTINED"}
        else:out=m.search(a.query,security_id=a.security)
    print(json.dumps(out,indent=2,allow_nan=False));return 0
if __name__=="__main__":raise SystemExit(main())
