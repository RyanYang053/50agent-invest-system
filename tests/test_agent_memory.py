import itertools
import json
from datetime import datetime,timezone,timedelta
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from atlas_pro.agent_memory import MemoryStore,DOMAINS
from atlas_pro.independent_review import strict_json
from atlas_pro.ledger import digest
from atlas_pro.skill_contracts import task_id
from atlas_pro.role_jobs import RoleJournal

class Ledger:
    def resolve_ids(self,ids,*,security_id,decision_at,include_private=False):
        if ids!=["public-source"] and not (ids==["private-source"] and include_private):raise ValueError("missing or private evidence")
        return [{"data_class":"public" if ids==["public-source"] else "private","payload_sha256":digest({"ids":ids,"sid":security_id})}]

@pytest.fixture
def env(tmp_path):
    now=[datetime(2026,11,24,12,tzinfo=timezone.utc)]
    trust={};keys={}
    for i,role in enumerate(("domain_reviewer","independent_validator")):
        key=Ed25519PrivateKey.generate();rid=f"reviewer-{i}";keys[rid]=key
        trust[rid]={"role":role,"organization":f"independent-{i}","identity":rid,"public_key":key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw).hex(),"revoked":False}
    store=MemoryStore(tmp_path/"memory",Ledger(),trust=trust,clock=lambda:now[0].isoformat())
    def review(m,nid,cloud=False,**override):
        p={"kind":"ROLE_MEMORY_V1","role_id":m.role_id,"note_id":nid,"domain":m.domain,"skill":task_id(m.role_id),"producer_organization":"producer","reviewed_at":now[0].isoformat(),"valid_until":(now[0]+timedelta(days=30)).isoformat(),"relevance_verified":True,"evidence_entailment_verified":True,"data_rights_verified":True,"no_sensitive_content_verified":True,"safe_annotation_verified":True,"cloud_allowed":cloud}|override
        return {"payload":p,"signatures":[{"reviewer_id":rid,"signature":key.sign(strict_json(p)).hex()} for rid,key in keys.items()]}
    return store,now,trust,review

def propose(m,**kwargs):
    p={"domain":m.domain,"kind":"semantic","topic":"method","security_id":"CIK:1","text":"valuation method source","evidence_ids":["public-source"]}
    return m.propose(**(p|kwargs))

def test_all_50_role_storage_and_2450_cross_reads(env):
    store,now,trust,review=env
    ids={}
    for role in DOMAINS:
        m=store.bind(role);nid=propose(m,text=f"unique valuation {role}");m.approve(nid,review(m,nid));ids[role]=nid
    for role in DOMAINS:
        m=store.bind(role);r=m.search("valuation",security_id="CIK:1")
        assert [v["memory_id"] for v in r]==[ids[role]]
        for other in DOMAINS:
            if other!=role:
                with pytest.raises(KeyError):m.revoke(ids[other])
    assert len(list(store.root.glob("*.sqlite")))==50

def test_all_domains_reject_other_role_labels(env):
    store,*_=env
    for role,other in itertools.permutations(DOMAINS,2):
        with pytest.raises(ValueError):propose(store.bind(role),domain=DOMAINS[other])

def test_quarantine_and_cloud_boundary(env):
    s,now,trust,review=env;m=s.bind("A031")
    n=propose(m,visibility="public_reviewed")
    assert not m.search("valuation",security_id="CIK:1",cloud=True)
    m.approve(n,review(m,n,True))
    assert m.search("valuation",security_id="CIK:1",cloud=True)[0]["not_evidence"]
    assert not m.search("valuation",security_id="CIK:2",cloud=True)
    private=s.bind("A081");p=propose(private,visibility="private_local",evidence_ids=["private-source"])
    private.approve(p,review(private,p))
    assert private.search("valuation",security_id="CIK:1")
    with pytest.raises(PermissionError):private.search("valuation",security_id="CIK:1",cloud=True)
    with pytest.raises(PermissionError):propose(m,visibility="private_local")
    with pytest.raises(ValueError):propose(m,evidence_ids=["private-source"])

def test_review_replay_and_revocation(env):
    s,now,trust,review=env;m=s.bind("A031");n=propose(m,visibility="public_reviewed")
    with pytest.raises(PermissionError):m.approve(n,review(m,n,True,role_id="A033"))
    with pytest.raises(PermissionError):m.approve(n,review(m,n,True,relevance_verified=False))
    with pytest.raises(PermissionError):m.approve(n,review(m,n,False))
    m.approve(n,review(m,n,True))
    trust["reviewer-0"]["revoked"]=True
    assert not m.search("valuation",security_id="CIK:1",cloud=True)

def test_conflict_and_supersession(env):
    s,now,trust,review=env;m=s.bind("A031");n=propose(m);m.approve(n,review(m,n))
    now[0]+=timedelta(seconds=1);n2=propose(m,text="valuation new")
    with pytest.raises(ValueError):m.approve(n2,review(m,n2))
    n3=propose(m,text="valuation revised",supersedes=n);m.approve(n3,review(m,n3))
    assert [r["memory_id"] for r in m.search("valuation",security_id="CIK:1")]==[n3]
    m.revoke(n3)
    assert not m.search("valuation",security_id="CIK:1")

def test_time_boundary_and_expiry(env):
    s,now,trust,review=env;m=s.bind("A031");before=now[0].isoformat()
    now[0]+=timedelta(seconds=1);n=propose(m);m.approve(n,review(m,n))
    assert not m.search("valuation",security_id="CIK:1",at=before)
    now[0]+=timedelta(days=31)
    assert not m.search("valuation",security_id="CIK:1")

def test_share_quarantine_and_parent_revocation(env):
    s,now,trust,review=env;a=s.bind("A031");b=s.bind("A032")
    n=propose(a,visibility="public_reviewed");a.approve(n,review(a,n,True))
    x=b.propose_share(a,n,topic="unit_economics")
    assert not b.search("valuation",security_id="CIK:1")
    b.approve(x,review(b,x))
    assert b.search("valuation",security_id="CIK:1")
    assert not b.search("valuation",security_id="CIK:1",cloud=True)
    a.revoke(n);assert not b.search("valuation",security_id="CIK:1")

def test_tamper_refused(env):
    s,now,trust,review=env;m=s.bind("A031");n=propose(m);m.approve(n,review(m,n))
    with s._db(m.role_id) as c:c.execute("UPDATE notes SET payload='{}'")
    with pytest.raises(ValueError):m.search("valuation",security_id="CIK:1")

def test_role_journal_automatic_episode_and_restart(env,tmp_path):
    s,now,trust,review=env;m=s.bind("A031")
    class Executor:
        def run(self,*a,**kw):return {"status":"UNVERIFIED_RESEARCH_MEMO","can_trade":False}
    j=RoleJournal(tmp_path/"jobs.sqlite",memory=s)
    kw={"at":now[0].isoformat(),"run_id":"run1","inputs":{"security_id":"CIK:1"}}
    j.execute(Executor(),"A031",**kw)
    now[0]+=timedelta(seconds=1)
    RoleJournal(tmp_path/"jobs.sqlite",memory=s).execute(Executor(),"A031",**kw)
    assert m.stats()["episodes"]==1
    assert s.bind("A032").stats()["episodes"]==0


def test_runner_uses_only_own_approved_public_annotations(env):
    from atlas_pro.runtime import ResearchModelRunner
    from atlas_pro.skill_contracts import contract
    s,now,trust,review=env
    m=s.bind("A031");other=s.bind("A033")
    query=contract("A031")["research_query"]
    text="business model evidence economics "+query[:200]
    a=propose(m,visibility="public_reviewed",text=text);m.approve(a,review(m,a,True))
    b=propose(other,visibility="public_reviewed",text=text+" other role");other.approve(b,review(other,b,True))
    pending=propose(m,topic="pending",visibility="public_reviewed",text=text+" quarantine")
    class Gateway:
        roles={"A031":{"role":"Business Model Analyst","data_scope":"public_only","minimum_effort":"low"}}
        registry={"model":{"provider":"openai","model_id":"mock"}}
        def select_and_reserve(self,**kw):
            return {"status":"RESERVED","model":"model"}
    class Index:
        def search(self,*a,**kw):return [{"doc_id":"filing","text":"public source evidence"}]
    calls=[]
    def transport(provider,body):
        calls.append(json.loads(body["input"]))
        return {"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":json.dumps({"claims":[{"claim":"claim","evidence_ids":["filing"]}],"uncertainties":[],"countercase":""})}]}],"usage":{"input_tokens":100,"output_tokens":100}}
    runner=ResearchModelRunner(Gateway(),Index(),transport,memory=s)
    args=dict(role_id="A031",task_set=task_id("A031"),request_id="run",security_id="CIK:1",query=query,at=now[0].isoformat())
    result=runner.run(**args)
    assert result["status"]=="UNVERIFIED_RESEARCH_MEMO"
    assert result["evidence_ids"]==["filing"]
    assert [x["memory_id"] for x in calls[0]["role_memory_annotations"]]==[a]
    assert b not in json.dumps(calls[0]) and pending not in json.dumps(calls[0])
    def bad_transport(provider,body):
        return {"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":json.dumps({"claims":[{"claim":"claim","evidence_ids":[a]}],"uncertainties":[],"countercase":""})}]}],"usage":{"input_tokens":100,"output_tokens":100}}
    runner=ResearchModelRunner(Gateway(),Index(),bad_transport,memory=s)
    assert runner.run(**args)["status"]=="MODEL_OUTPUT_REJECTED"

def test_real_ledger_source_scope_and_integrity(tmp_path):
    from atlas_pro.ledger import EvidenceLedger
    at="2026-11-24T12:00:00Z"
    ledger=EvidenceLedger(tmp_path/"ledger.sqlite")
    policy={"license_id":"public","permitted_for_personal_analysis":True,"cloud_allowed":True}
    ledger.add_evidence({"record_id":"public-source","source_id":"test","document_id":"test","security_id":"CIK:1","observed_at":at,"published_at":at,"available_at":at,"payload":{"revenue":42},"data_class":"public","license_id":"public"},policy=policy)
    s=MemoryStore(tmp_path/"memory",ledger,clock=lambda:at)
    m=s.bind("A031");assert len(propose(m))==64
    with pytest.raises(ValueError):propose(m,security_id="CIK:2")
    with ledger._db() as c:c.execute("UPDATE evidence SET payload_json='{}'")
    with pytest.raises(ValueError):propose(m,topic="different")
