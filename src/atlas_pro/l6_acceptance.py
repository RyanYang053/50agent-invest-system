"""Conservative L6 readiness rubric: project-specific, not an industry certification.
Every gate needs review of actual evidence; signed reports alone never establish alpha.
This module never grants trade permission or claims that Atlas is a top fund.
"""
from __future__ import annotations
import argparse,json,math,hashlib
from pathlib import Path
from .independent_review import verify_review,load_trust,ishash,role_grade,verify_artifacts
from .skill_contracts import catalog,task_id
from .ledger import digest,iso

# Targets are deliberately explicit and proposed, not regulatory standards or observed metrics.
# Bounds are inclusive. Actual performance gate separately requires uncertainty and external review.
GATES={
 'G1_data':{'pit_years':(10,None),'historical_universe_coverage':(.99,1),'corporate_action_reconciliation':(.999,1),'critical_data_errors':(0,0)},
 'G2_role_competence':{'certified_roles':(50,50),'distinct_holdout_cases_per_role':(100,None),'critical_failures':(0,0)},
 'G3_rag':{'real_holdout_cases':(500,None),'recall_at_10':(.95,1),'material_claim_entailment':(.98,1),'private_leaks':(0,0),'future_leaks':(0,0)},
 'G4_research':{'independent_reproductions':(2,None),'untouched_oos_years':(3,None),'universe_leakage_failures':(0,0),'registered_trials_fraction':(1,1),'multiple_test_adjusted_p':(0,.05),'net_excess_lower_ci':(1e-12,None)},
 'G5_risk':{'account_coverage':(1,1),'reconciled_fraction':(1,1),'critical_control_failures':(0,0),'broker_margin_acceptance':(1,1),'unresolved_tail_exposures':(0,0)},
 'G6_operational':{'prospective_paper_sessions':(60,None),'scheduled_job_completion':(.995,1),'unreconciled_orders':(0,0),'duplicate_orders':(0,0),'successful_recovery_drills':(3,None)},
 'G7_security':{'unresolved_critical_findings':(0,0),'policy_bypasses':(0,0),'credential_leaks':(0,0),'independent_red_team_reviews':(2,None)},
 'G8_evolution':{'independently_reproduced_challenger_trials':(3,None),'unauthorized_promotions':(0,0),'successful_rollback_drills':(3,None),'holdout_reuse_violations':(0,0)},
 'G9_forward_performance':{'prospective_sessions':(252,None),'market_regimes':(2,None),'net_excess_lower_ci':(1e-12,None),'risk_adjusted_excess_lower_ci':(1e-12,None),'max_drawdown':(0,.25),'risk_budget_breaches':(0,0)},
 'G10_live_evidence':{'independently_verified_live_sessions':(756,None),'live_risk_adjusted_excess_lower_ci':(1e-12,None),'live_net_excess_lower_ci':(1e-12,None),'live_risk_breaches':(0,0),'independent_peer_comparison':(1,1)},
}


# These metrics represent counts, not continuous estimates. Boolean and fractional
# reports must never count as completed sessions, reviews or zero critical failures.
COUNT_METRICS={'critical_data_errors','certified_roles','distinct_holdout_cases_per_role','critical_failures','real_holdout_cases','private_leaks','future_leaks','independent_reproductions','universe_leakage_failures','critical_control_failures','unresolved_tail_exposures','prospective_paper_sessions','unreconciled_orders','duplicate_orders','successful_recovery_drills','unresolved_critical_findings','policy_bypasses','credential_leaks','independent_red_team_reviews','independently_reproduced_challenger_trials','unauthorized_promotions','successful_rollback_drills','holdout_reuse_violations','prospective_sessions','market_regimes','risk_budget_breaches','independently_verified_live_sessions','live_risk_breaches'}

def validate_period(gate,p):
    start,end=iso(p['period_start']),iso(p['period_end']);metrics=p['metrics']
    if gate in ('G1_data','G4_research'):
        key='pit_years' if gate=='G1_data' else 'untouched_oos_years'
        if metrics[key]>(end-start).total_seconds()/(365*86400):raise ValueError('claimed years exceed evidence interval')
    key={'G6_operational':'prospective_paper_sessions','G9_forward_performance':'prospective_sessions','G10_live_evidence':'independently_verified_live_sessions'}.get(gate)
    if key:
        from .performance_evidence import full_session_closes
        possible=len(full_session_closes(p['period_start'],p['period_end']))
        if metrics[key]>possible:raise ValueError('claimed sessions exceed elapsed exchange sessions')


def evaluate(reviews,trust,*,at,release_hash,mandate_hash,role_contract_hash,role_reviews=None,roles=None,models=None,artifact_dir=None):
    if not ishash(release_hash) or not ishash(mandate_hash) or role_contract_hash!=digest(catalog()):raise ValueError('exact release, mandate and skill version required')
    results={};passed=0;role_reviews=role_reviews or {};roles=roles or {};models=models or {}
    for gate,bounds in GATES.items():
        try:
            if gate not in reviews:raise ValueError('MISSING_INDEPENDENT_EVIDENCE')
            p=verify_review(reviews[gate],trust,at=at,required_roles=('domain_reviewer','independent_validator'))
            if p.get('kind')!='L6_GATE_V1' or p.get('gate')!=gate or p.get('release_hash')!=release_hash or p.get('mandate_hash')!=mandate_hash or p.get('role_contract_hash')!=role_contract_hash:raise ValueError('review version mismatch')
            if p.get('synthetic') is not False or not p.get('producer_organization') or not p.get('data_rights_verified') is True:raise ValueError('real authorized evidence required')
            if not isinstance(p.get('artifact_hashes'),list) or len(set(p['artifact_hashes']))<2 or not all(ishash(x) for x in p['artifact_hashes']):raise ValueError('missing reviewed evidence artifacts')
            verify_artifacts(p['artifact_hashes'],artifact_dir)
            if not iso(p['period_start'])<iso(p['period_end'])<=iso(p['reviewed_at']):raise ValueError('invalid evidence period')
            metrics=p['metrics'];reasons=[]
            if set(metrics)!=set(bounds):raise ValueError('metric schema mismatch')
            for k,(lo,hi) in bounds.items():
                v=metrics[k]
                if (k in COUNT_METRICS and type(v) is not int) or type(v) not in (int,float) or not math.isfinite(v) or (lo is not None and v<lo) or (hi is not None and v>hi):reasons.append(k)
            if not reasons:validate_period(gate,p)
            if gate=='G2_role_competence':
                if set(role_reviews)!=set(catalog()) or set(roles)!=set(catalog()):reasons.append('individual_role_evidence_missing')
                else:
                    for rid,review in role_reviews.items():
                        mid=review['payload']['model_id'];r=role_grade(review,trust,role_id=rid,model_id=mid,role=roles[rid],model=models[mid],at=at,artifact_dir=artifact_dir,check_artifacts=True)
                        if r['passed'] is not True or r['n']<metrics['distinct_holdout_cases_per_role']:reasons.append('role_failed:'+rid)
                        if not iso(p['period_start'])<=iso(review['payload']['evaluated_at'])<=iso(p['period_end']):reasons.append('role_outside_evidence_period:'+rid)
            if gate=='G3_rag' and not reasons:
                from .rag_evidence import check_rag_metrics
                reasons.extend(check_rag_metrics(p,artifact_dir))
            if gate in ('G4_research','G9_forward_performance','G10_live_evidence'):
                provenance=[p.get(k) for k in ('benchmark_hash','cost_model_hash','trial_registry_hash','returns_hash')]
                if not all(ishash(h) for h in provenance) or len(set(provenance))!=4 or not set(provenance).issubset(p['artifact_hashes']):reasons.append('performance_provenance')
                elif not reasons:
                    from .performance_evidence import check_signed_metrics
                    reasons.extend(check_signed_metrics(p,artifact_dir,gate=gate))
            results[gate]={'status':'REVIEWED_THRESHOLDS_MET' if not reasons else 'BLOCKED','reasons':reasons,'review_hash':digest(p)};passed+=not reasons
        except (ValueError,TypeError,PermissionError,KeyError,AttributeError,ImportError,OverflowError,OSError,IndexError) as e:results[gate]={'status':'BLOCKED','reasons':[str(e)]}
    research_ready=all(results[g]['status']=='REVIEWED_THRESHOLDS_MET' for g in GATES if g!='G10_live_evidence')
    return {'research_review_eligible':research_ready,'status':'ELIGIBLE_FOR_EXTERNAL_L6_REVIEW' if passed==len(GATES) else 'L6_NOT_VERIFIED','gates':results,'reviewed_thresholds_met':passed,'gate_count':len(GATES),'l6_certified':False,'can_trade':False,'limitations':['proposed acceptance thresholds, not established universal fund standards','signed reviewers attest findings; this evaluator does not independently reproduce the reviewed results or authenticate organizations','real alpha, capacity and peer comparability require independent professional review','passing the rubric cannot authorize execution']}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reviews',type=Path);p.add_argument('--trust',type=Path);p.add_argument('--artifacts',type=Path);p.add_argument('--role-reviews',type=Path);p.add_argument('--roles',type=Path);p.add_argument('--models',type=Path);p.add_argument('--at',required=True);p.add_argument('--release-hash',required=True);p.add_argument('--mandate-hash',required=True);a=p.parse_args(argv)
    reviews=json.loads(a.reviews.read_text()) if a.reviews else {};trust=load_trust(a.trust) if a.trust else {}
    result=evaluate(reviews,trust,at=a.at,release_hash=a.release_hash,mandate_hash=a.mandate_hash,role_contract_hash=digest(catalog()),artifact_dir=a.artifacts,role_reviews=json.loads(a.role_reviews.read_text()) if a.role_reviews else {},roles={r['agent_id']:r for r in json.loads(a.roles.read_text())} if a.roles else {},models=json.loads(a.models.read_text()) if a.models else {})
    print(json.dumps(result,indent=2,allow_nan=False));return 0 if result['status']=='ELIGIBLE_FOR_EXTERNAL_L6_REVIEW' else 2
if __name__=='__main__':raise SystemExit(main())
