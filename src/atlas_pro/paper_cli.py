"""Explicit local operator CLI. No model calls; never connect to a live endpoint."""
import argparse, json
from pathlib import Path
from .paper import AlpacaPaperTransport, PaperGateway, PaperBlocked, PaperHTTPError

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--policy',type=Path,required=True);p.add_argument('--journal',type=Path,required=True)
    p.add_argument('--network-paper-only',action='store_true',help='allow calls to fixed Alpaca paper host only')
    sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('inspect');sub.add_parser('stop')
    sub.add_parser('arm').add_argument('--confirm',action='store_true')
    s=sub.add_parser('submit');s.add_argument('--order',type=Path,required=True);s.add_argument('--confirm',action='store_true')
    r=sub.add_parser('reconcile');r.add_argument('client_order_id')
    c=sub.add_parser('cancel');c.add_argument('client_order_id');c.add_argument('--confirm',action='store_true')
    args=p.parse_args()
    try:
        # Stop remains usable if keys/network are unavailable.
        transport=(lambda *a,**k: (_ for _ in ()).throw(PaperBlocked('NETWORK_DISABLED'))) if args.cmd=='stop' else AlpacaPaperTransport(enabled=args.network_paper_only)
        g=PaperGateway(args.journal,json.loads(args.policy.read_text()),transport)
        if args.cmd=='inspect':result=g.inspect()
        elif args.cmd=='arm':g.arm(confirmed=args.confirm);result={'status':'armed','live_execution':False}
        elif args.cmd=='stop':g.stop();result={'status':'stopped','live_execution':False}
        elif args.cmd=='submit':result=g.submit(json.loads(args.order.read_text()),operator_confirmed=args.confirm)
        elif args.cmd=='cancel':result=g.cancel(args.client_order_id,operator_confirmed=args.confirm)
        else:result=g.reconcile(args.client_order_id)
        print(json.dumps(result,indent=2));return 2 if result.get('status') in ('unknown','reconcile_failed','local_blocked','cancel_uncertain') else 0
    except (PaperBlocked,PaperHTTPError,ValueError,KeyError,TypeError,OSError) as e:
        # Never print arbitrary provider error payloads or credentials.
        print(json.dumps({'status':'blocked','reason':str(e) if isinstance(e,(PaperBlocked,PaperHTTPError)) else type(e).__name__,'live_execution':False}));return 2

if __name__=='__main__':raise SystemExit(main())
