"""Fixed offline research entry point. Fails closed outside a constrained Linux container.
Probe checks the current process, not host kernel security or Docker provenance.
Only vetted bundled code may run here; never execute generated code or load pickles.
"""
from __future__ import annotations
import os, socket, sys
from pathlib import Path
from .quant_train import main


def check_isolation():
    status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    root=[line.split() for line in Path('/proc/self/mountinfo').read_text().splitlines() if len(line.split())>5 and line.split()[4]=='/']
    if os.getuid()==0 or int(status.get('CapEff','1').strip(),16)!=0 or status.get('NoNewPrivs','0').strip()!='1':
        raise PermissionError('nonroot, zero effective capabilities and no-new-privileges required')
    if len(root)!=1 or 'ro' not in root[0][5].split(','):raise PermissionError('read-only root required')
    if {name for _,name in socket.if_nameindex()}!={'lo'}:raise PermissionError('network namespace is not loopback-only')
    if any(k.startswith(('ALPACA_', 'IBKR_', 'TWS_', 'TIINGO_', 'FRED_', 'OPENAI_', 'ANTHROPIC_', 'DEEPSEEK_','GOOGLE_API_','AWS_')) for k in os.environ):
        raise PermissionError('unexpected credential environment')
    if Path('/var/run/docker.sock').exists() or Path('/run/podman/podman.sock').exists():raise PermissionError('container control socket present')
    return True

if __name__=='__main__':
    check_isolation()
    raise SystemExit(main())
