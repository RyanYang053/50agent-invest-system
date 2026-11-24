"""Role-specific capability contracts; definitions are not certifications."""
from __future__ import annotations
import json,hashlib
from importlib.resources import files
from .ledger import digest


def catalog():
    return json.loads(files('atlas_pro').joinpath('role_skills.json').read_text(encoding='utf-8'))


def contract(role_id):
    return catalog()[role_id]


def runtime_hash(role_id):
    """Bind reviews to packaged source, including the actual research/diagnostic path."""
    c=contract(role_id)
    names=['skill_contracts.py','role_jobs.py','ledger.py','independent_review.py','models.py','runtime.py','retrieval.py','research.py','ttm.py','account_risk.py','portfolio.py','experiments.py','learning.py','agent_memory.py','employee_packs.py','employee_packs.json']
    pkg=files('atlas_pro')
    return digest({'role':role_id,'files':{n:hashlib.sha256(pkg.joinpath(n).read_bytes()).hexdigest() for n in names}})


def task_id(role_id):
    c=contract(role_id)
    return f"atlas-skill-{role_id.lower()}-v{c['version']}-{digest(c)[:16]}"


def validate_catalog(roles,public_tasks,local_tasks):
    skills=catalog(); byid={r['agent_id']:r for r in roles}
    if len(roles)!=50 or len(byid)!=50 or set(skills)!=set(byid) or set(skills)!=set(public_tasks)|set(local_tasks):raise ValueError('SKILL_COVERAGE_MISMATCH')
    for field in ('skill_id','method','deliverable','critical_failure','challenge_case'):
        if len({s[field] for s in skills.values()})!=50:raise ValueError('DUPLICATE_SKILL_'+field)
    for rid,s in skills.items():
        r=byid[rid]
        if s['role_id']!=rid or s['role']!=r['role'] or s['tool_groups']!=r['allowed_tool_groups'] or s['scope']!=r['data_scope'] or s['default_model']!=r['primary_model'] or s['fallback_model']!=r.get('fallback_model') or s['minimum_effort']!=r['minimum_effort'] or s['max_tool_calls']!=r['tool_budget_calls']:raise ValueError('SKILL_MANIFEST_DRIFT:'+rid)
        if any(s[k] is not False for k in ('can_trade','can_change_policy','can_promote')):raise PermissionError('SKILL_PRIVILEGE_ESCALATION')
        if rid in public_tasks and (s['kind']!='public_memo' or s['research_query']!=public_tasks[rid][1] or s['required_inputs']!=['security_id']):raise ValueError('SKILL_QUERY_DRIFT:'+rid)
        if rid in local_tasks and (s['kind']!='local_diagnostic' or s['handler']!=local_tasks[rid]):raise ValueError('SKILL_HANDLER_DRIFT:'+rid)
    return skills


def instructions(role_id):
    s=contract(role_id)
    return ('Specialized method: '+s['method']+'. Required deliverable: '+s['deliverable']+'. Critical failure to avoid: '+s['critical_failure']+'. Scope limit: '+s['implementation_limit']+'. Explicitly identify missing inputs and abstain rather than fabricate.')
