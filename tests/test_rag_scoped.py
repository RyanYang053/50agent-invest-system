import hashlib
import pytest
from atlas_pro.retrieval import ResearchIndex
from atlas_pro.query_terms import terms,resolve_company,excerpt
from atlas_pro.financebench_atlas import evaluate

AT='2026-11-01T00:00:00Z';FUT='2026-12-01T00:00:00Z'
def add(idx,id,text,scope='public',at=AT,security='A'):
    idx.add(dict(doc_id=id,source_id='source',source_uri='https://example.com',security_id=security,available_at=at,scope=scope,license_id='l',content=text),dict(license_id='l',permitted_for_personal_analysis=True,allow_local_retention=True,allow_rag_indexing=True,cloud_allowed=scope=='public'))

def test_query_keeps_late_financial_terms():
    assert 'capex' in terms('What is the answer to the following question relying on the details shown in the financial statement about CAPEX?')
    assert terms('gross gross margin')==['gross','margin']
    with pytest.raises(ValueError):terms('a'*4097)

@pytest.mark.parametrize('query,expected',[('Apple revenue','A'),('Apple and Microsoft revenue',None),('Pineapple revenue',None),('APPLE INC revenue','A'),('unrelated',None)])
def test_entity(query,expected):
    assert resolve_company(query,{'A':['Apple','Apple Inc'],'M':['Microsoft']})==expected

def test_scope_and_pit_ranking_invariance(tmp_path):
    idx=ResearchIndex(tmp_path/'db');add(idx,'a','revenue revenue earnings');add(idx,'b','earnings earnings revenue')
    before=idx.search('revenue earnings',decision_at=AT,security_id='A')
    for i in range(12):
        add(idx,f'private-{i}','revenue '*100,'private');add(idx,f'future-{i}','earnings '*100,at=FUT);add(idx,f'other-{i}','revenue '*100,security='B')
    assert idx.search('revenue earnings',decision_at=AT,security_id='A')==before
    assert all(x['scope']=='public' for x in idx.search('revenue',decision_at=AT))

def test_late_excerpt_is_exact(tmp_path):
    idx=ResearchIndex(tmp_path/'db');body='generic text '*400+'Operating margin and capital expenditure 987 million.';add(idx,'a',body)
    result=idx.search('capital expenditure 987',decision_at=AT)[0]
    assert '987 million' in result['text'] and result['excerpt_start']>0
    assert result['text']==body[result['excerpt_start']:result['excerpt_end']]
    assert result['excerpt_sha256']==hashlib.sha256(result['text'].encode()).hexdigest()
    assert result['evidence_sha256']==hashlib.sha256(body.encode()).hexdigest()

def test_local_financebench_smoke():
    rows=[{'financebench_id':str(i),'company':company,'question':company+' revenue','evidence':[{'doc_name':company,'evidence_page_num':0,'evidence_text':'revenue 100','evidence_text_full_page':('other '*500)+'revenue 100'}]} for i,company in enumerate(('Apple','Microsoft'))]
    r=evaluate(rows);assert r['questions']==2 and r['entity_resolution']['correct']==2
    assert r['benchmark']['auto_company']['recall1']==1 and r['l6_certified'] is False
