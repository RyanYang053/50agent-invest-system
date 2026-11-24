"""Recompute G3 from an independently adjudicated real corpus and case-level logs.
Does not independently decide natural-language entailment. Human grades are
still required; raw documents and supporting citations must be content-addressed.
"""
from __future__ import annotations
import math
from .ledger import digest,iso
from .independent_review import verify_artifacts,ishash
from .performance_evidence import read_artifact


def audit_rag(p,root):
    keys=('rag_cases_hash','rag_results_hash','rag_claim_judgments_hash','rag_corpus_hash')
    hs=[p[k] for k in keys]
    if len(set(hs))!=4 or not set(hs).issubset(p['artifact_hashes']):raise ValueError('missing distinct RAG evidence artifacts')
    cases,results,grades,corpus=[read_artifact(root,h) for h in hs]
    if [x.get('kind') for x in (cases,results,grades,corpus)]!=['RAG_CASES_V1','RAG_RESULTS_V1','RAG_JUDGMENTS_V1','RAG_CORPUS_V1']:raise ValueError('RAG artifact kinds mismatch')
    if results.get('cases_hash')!=hs[0] or results.get('corpus_hash')!=hs[3] or grades.get('results_hash')!=hs[1]:raise ValueError('RAG evidence binding mismatch')
    if cases.get('independently_adjudicated') is not True or cases.get('synthetic') is not False or cases.get('corpus_complete_for_benchmark') is not True:raise ValueError('real complete adjudicated benchmark required')
    locked=iso(cases['locked_at']);run=iso(results['run_at']);graded=iso(grades['graded_at']);reviewed=iso(p['reviewed_at'])
    if not iso(p['period_start'])<=locked<run<=graded<=reviewed or run>iso(p['period_end']):raise ValueError('RAG evaluation chronology')
    if results.get('top_k')!=10:raise ValueError('Recall@10 requires exact top_k')
    docs={};sources=set()
    for d in corpus['documents']:
        if not isinstance(d.get('id'),str) or not d['id'] or d['id'] in docs or d.get('scope') not in ('public','private') or not isinstance(d.get('security_id'),str) or not d['security_id'] or not ishash(d.get('raw_hash')):raise ValueError('invalid document identity or scope')
        iso(d['available_at']);docs[d['id']]=d;sources.add(d['raw_hash'])
    if not docs or len(docs)>100000 or sources&set(hs) or not sources.issubset(p['artifact_hashes']):raise ValueError('unreviewed RAG corpus sources')
    verify_artifacts(sources,root)
    cs=cases['cases'];rs=results['results'];gs=grades['judgments'];seen=set();by={};judgments={}
    if not 500<=len(cs)<=10000 or len(rs)!=len(cs):raise ValueError('incomplete RAG case coverage')
    for c in cs:
        if not isinstance(c.get('id'),str) or not c['id'] or c['id'] in by or not isinstance(c.get('query'),str) or not c['query'].strip() or not isinstance(c.get('security_id'),str) or not c['security_id'] or c.get('scope') not in ('public_only','private_local'):raise ValueError('invalid RAG case')
        at=iso(c['decision_at']);gold=c['gold_ids'];key=digest({'query':' '.join(c['query'].casefold().split()),'security_id':c['security_id'],'decision_at':at.isoformat(),'scope':c['scope']})
        if key in seen or at>run or not isinstance(gold,list) or len(set(gold))!=len(gold) or any(i not in docs for i in gold):raise ValueError('duplicate or invalid gold case')
        if any(docs[i]['security_id']!=c['security_id'] or iso(docs[i]['available_at'])>at or (c['scope']=='public_only' and docs[i]['scope']!='public') for i in gold):raise ValueError('gold outside case boundary')
        seen.add(key);by[c['id']]=c
    for g in gs:
        key=(g['case_id'],g['claim_id'])
        if key in judgments or g['case_id'] not in by or type(g.get('material')) is not bool or type(g.get('entailed')) is not bool or not isinstance(g.get('reviewer_rationale'),str) or not g['reviewer_rationale'].strip():raise ValueError('invalid claim judgment')
        judgments[key]=g
    answerable=0;recalls=[];no_answer=0;no_answer_abstained=0;private=future=wrong_entity=0;material=entailed=0;seen_results=set();seen_claims=set();answered_answerable=0
    for r in rs:
        rid=r['case_id']
        if rid not in by or rid in seen_results:raise ValueError('result/case join mismatch')
        seen_results.add(rid);c=by[rid];at=iso(c['decision_at']);gold=set(c['gold_ids']);retrieved=r['retrieved_ids'];claims=r['claims']
        if not isinstance(retrieved,list) or len(retrieved)>10 or len(set(retrieved))!=len(retrieved) or any(i not in docs for i in retrieved) or type(r.get('abstained')) is not bool or not isinstance(claims,list):raise ValueError('invalid retrieval output')
        if r['abstained'] and claims:raise ValueError('abstention cannot include substantive claims')
        for i in retrieved:
            d=docs[i];private+=int(c['scope']=='public_only' and d['scope']!='public');future+=int(iso(d['available_at'])>at);wrong_entity+=int(d['security_id']!=c['security_id'])
        if gold:
            answerable+=1;recalls.append(len(gold.intersection(retrieved))/len(gold));answered_answerable+=int(not r['abstained'] and bool(claims))
        else:no_answer+=1;no_answer_abstained+=int(r['abstained'])
        if not r['abstained'] and not claims:raise ValueError('missing claims from nonabstaining answer')
        for cl in claims:
            key=(rid,cl['id']);cited=cl['citation_ids']
            if key in seen_claims or key not in judgments or not isinstance(cl['text'],str) or not cl['text'].strip() or not isinstance(cited,list) or not cited or len(set(cited))!=len(cited) or not set(cited).issubset(retrieved):raise ValueError('claim/citation/judgment mismatch')
            g=judgments[key]
            if g.get('claim_hash')!=digest(cl):raise ValueError('judgment does not bind actual claim')
            seen_claims.add(key)
            if g['material']:material+=1;entailed+=int(g['entailed'])
    if seen_claims!=set(judgments) or answerable<450 or material<450:raise ValueError('insufficient answerable or material claim coverage')
    # Abstaining on every difficult question must not inflate claim precision.
    if answered_answerable/answerable<.95 or (no_answer and no_answer_abstained/no_answer<.95):raise ValueError('insufficient answer or abstention coverage')
    return {'real_holdout_cases':len(cs),'recall_at_10':sum(recalls)/answerable,'material_claim_entailment':entailed/material,'private_leaks':private,'future_leaks':future,'cross_entity_leaks':wrong_entity,'answerable_cases':answerable,'answered_answerable':answered_answerable,'no_answer_cases':no_answer,'material_claims':material,'can_trade':False,'limitations':['entailment grades and corpus completeness are reviewer attestations, not machine-proven','public dataset exposure and paraphrased duplicates require separate review']}


def check_rag_metrics(p,root):
    actual=audit_rag(p,root);reasons=[]
    for k,v in p['metrics'].items():
        if not math.isclose(v,actual[k],rel_tol=1e-9,abs_tol=1e-10):reasons.append('recomputed_metric_mismatch:'+k)
    if actual['cross_entity_leaks']:reasons.append('cross_entity_leaks')
    return reasons
