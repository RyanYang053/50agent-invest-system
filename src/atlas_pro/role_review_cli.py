"""Import an independently signed role competence report, not a numeric benchmark."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from datetime import datetime,timezone
from .models import ModelGateway
from .independent_review import load_trust
from .core_service import private_dir
from .skill_contracts import catalog


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--roles',type=Path,required=True);p.add_argument('--models',type=Path,required=True);p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--trust',type=Path,required=True);p.add_argument('--review',type=Path,required=True);p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--role',choices=sorted(catalog()),required=True);p.add_argument('--model',required=True);a=p.parse_args(argv)
    g=ModelGateway(private_dir(a.data_dir)/'models.sqlite',json.loads(a.models.read_text()),json.loads(a.roles.read_text()),review_trust=load_trust(a.trust))
    result=g.certify_role_review(a.role,a.model,json.loads(a.review.read_text()),at=datetime.now(timezone.utc).isoformat(),artifact_dir=a.artifacts);print(json.dumps(result,indent=2));return 0 if result['passed'] else 2
if __name__=='__main__':raise SystemExit(main())
