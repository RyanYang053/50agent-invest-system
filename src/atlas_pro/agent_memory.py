"""Role-bound learning memory: local-first, explicit promotion, no model DB access.

Trust boundary: the operator/service binds a role before calling this API. Role
handles are not a sandbox for hostile Python in the same process or OS user.
Public source evidence remains separate; memories are untrusted annotations.
"""
from __future__ import annotations
import json, os, re, sqlite3, stat
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .ledger import digest, iso, canonical
from .skill_contracts import catalog, task_id
from .independent_review import verify_review

KINDS=("semantic","procedural","failure","performance","episodic")
DOMAINS={
"A011":"investment_synthesis","A012":"policy_compliance","A013":"research_planning","A014":"evidence_quality","A015":"committee_records",
"A021":"market_feed_quality","A022":"financial_normalization","A023":"event_verification","A024":"provider_reconciliation","A025":"privacy_lineage",
"A031":"business_models","A032":"unit_economics","A033":"competitive_moats","A034":"capital_allocation","A035":"accounting_forensics",
"A041":"fcff_valuation","A042":"reverse_valuation","A043":"peer_valuation","A044":"scenario_probabilities","A045":"option_valuation",
"A051":"quality_value","A052":"inversion_bias","A053":"credit_cycles","A054":"story_to_numbers","A055":"macro_diversification",
"A061":"rates_credit","A062":"liquidity_conditions","A063":"inflation_growth","A064":"fx_commodities","A065":"regime_classification",
"A071":"factor_research","A072":"feature_leakage","A073":"event_studies","A074":"alternative_data","A075":"walk_forward",
"A081":"portfolio_exposure","A082":"tail_risk","A083":"kelly_sizing","A084":"stress_hedging","A085":"tax_account_location",
"A091":"order_proposals","A092":"execution_costs","A093":"margin_leverage","A094":"fill_reconciliation","A095":"execution_authorization",
"A101":"bear_theses","A102":"financial_source_audit","A103":"causal_bias","A104":"forecast_calibration","A105":"skill_improvement"}
MAX_NOTES=10000
def _now():return datetime.now(timezone.utc).isoformat()
def _token(x):return isinstance(x,str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}",x) is not None
def _hash(x):return isinstance(x,str) and re.fullmatch(r"[a-f0-9]{64}",x) is not None

class MemoryStore:
    def __init__(self,root,ledger,*,trust=None,clock=_now):
        self.root=Path(root);self.ledger=ledger;self.trust=trust if trust is not None else {};self.clock=clock
        self.skills=catalog()
        if set(self.skills)!=set(DOMAINS) or len(set(DOMAINS.values()))!=50:raise ValueError("memory domain catalog drift")
        if self.root.is_symlink():raise PermissionError("symlink memory root")
        self.root.mkdir(parents=True,mode=0o700,exist_ok=True)
        if os.name=="posix" and stat.S_IMODE(self.root.stat().st_mode)&0o077:raise PermissionError("memory root must be private")
    def bind(self,role_id):
        if role_id not in DOMAINS:raise PermissionError("unknown memory role")
        return RoleMemory(self,role_id)
    @contextmanager
    def _db(self,role_id):
        if role_id not in DOMAINS:raise PermissionError("unknown memory role")
        p=self.root/(role_id+".sqlite")
        if p.is_symlink() or (p.exists() and not p.is_file()):raise PermissionError("unsafe memory path")
        if p.exists() and os.name=="posix" and stat.S_IMODE(p.stat().st_mode)&0o077:raise PermissionError("memory file must be private")
        if not p.exists():
            try:
                fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
            except FileExistsError:pass
        c=sqlite3.connect(p,timeout=10);c.row_factory=sqlite3.Row
        try:
            c.execute("PRAGMA journal_mode=WAL");c.execute("PRAGMA synchronous=FULL")
            c.executescript("""CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,payload TEXT NOT NULL,prev TEXT NOT NULL,hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS episodes(id TEXT PRIMARY KEY,payload TEXT NOT NULL);""")
            yield c;c.commit()
        except Exception:c.rollback();raise
        finally:c.close()

class RoleMemory:
    def __init__(self,store,role_id):self._store=store;self._role=role_id
    @property
    def role_id(self):return self._role
    @property
    def domain(self):return DOMAINS[self._role]
    def _time(self,at=None):
        now=iso(self._store.clock());t=iso(at) if at is not None else now
        if t>now:raise ValueError("future memory cutoff")
        return t
    def _note(self,c,nid):
        row=c.execute("SELECT payload FROM notes WHERE id=?",(nid,)).fetchone()
        if row is None:raise KeyError("unknown role memory")
        n=json.loads(row[0])
        if digest(n)!=nid or n["role_id"]!=self._role or n["domain"]!=self.domain:raise ValueError("memory integrity failure")
        return n
    def _events(self,c):
        prev="GENESIS";out=[]
        for r in c.execute("SELECT * FROM events ORDER BY seq"):
            e=json.loads(r["payload"])
            if e["role_id"]!=self._role or r["prev"]!=prev or digest({"prev":prev,"event":e})!=r["hash"]:raise ValueError("memory event integrity failure")
            prev=r["hash"];out.append(e)
        return out
    def _append(self,c,e):
        last=c.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        prev=last[0] if last else "GENESIS"
        c.execute("INSERT INTO events(payload,prev,hash) VALUES(?,?,?)",(canonical(e),prev,digest({"prev":prev,"event":e})))
    def _state(self,c,t):
        state={}
        for e in self._events(c):
            if iso(e["at"])<=t:state[e["note_id"]]=e
        return state
    def _evidence(self,n,t):
        rows=self._store.ledger.resolve_ids(n["evidence_ids"],security_id=n["security_id"],decision_at=t.isoformat(),include_private=n["visibility"]=="private_local")
        scopes={r["data_class"] for r in rows}
        if n["visibility"]=="public_reviewed" and scopes!={"public"}:raise PermissionError("nonpublic source")
        if n["visibility"]=="private_local" and (self._store.skills[self._role]["scope"]!="private_only" or not scopes<={"private","public"}):raise PermissionError("private or licensed evidence denied")
        if [r["payload_sha256"] for r in rows]!=n["evidence_hashes"]:raise ValueError("memory evidence changed")
    def propose(self,*,domain,kind,topic,security_id,text,evidence_ids,visibility="local",supersedes=None,shared_from=None):
        """Explicit operator proposal; never accepts instructions from a model as facts."""
        if domain!=self.domain or kind not in KINDS or not _token(topic) or not _token(security_id) or not isinstance(text,str) or not 1<=len(text.strip())<=4000:raise ValueError("out-of-domain or invalid memory")
        if visibility not in ("local","private_local","public_reviewed"):raise ValueError("invalid visibility")
        if visibility=="public_reviewed" and self._store.skills[self._role]["scope"]!="public_only":raise PermissionError("cloud memory forbidden for local role")
        if visibility=="private_local" and self._store.skills[self._role]["scope"]!="private_only":raise PermissionError("private memory forbidden for role")
        now=self._time()
        rows=self._store.ledger.resolve_ids(evidence_ids,security_id=security_id,decision_at=now.isoformat(),include_private=visibility=="private_local")
        scopes={r["data_class"] for r in rows}
        if not scopes<=({"private","public"} if visibility=="private_local" else {"public"}):raise PermissionError("restricted evidence")
        if shared_from is not None:raise PermissionError("use explicit share proposal")
        n={"role_id":self._role,"domain":domain,"kind":kind,"topic":topic,"security_id":security_id,"text":text.strip(),"evidence_ids":list(evidence_ids),"evidence_hashes":[r["payload_sha256"] for r in rows],"visibility":visibility,"skill":task_id(self._role),"created_at":now.isoformat(),"supersedes":supersedes,"shared_from":None}
        return self._insert(n)
    def _insert(self,n):
        nid=digest(n)
        with self._store._db(self._role) as c:
            c.execute("BEGIN IMMEDIATE")
            self._events(c)
            if c.execute("SELECT 1 FROM notes WHERE id=?",(nid,)).fetchone():return nid
            if c.execute("SELECT count(*) FROM notes").fetchone()[0]>=MAX_NOTES:raise ValueError("memory capacity reached; operator retention review required")
            if n["supersedes"] is not None:
                old=self._note(c,n["supersedes"])
                if any(old[k]!=n[k] for k in ("topic","security_id","kind","visibility")):raise ValueError("invalid revision lineage")
            c.execute("INSERT INTO notes VALUES(?,?)",(nid,canonical(n)))
            self._append(c,{"role_id":self._role,"note_id":nid,"action":"PROPOSED","at":n["created_at"]})
        return nid
    def _verify(self,nid,n,envelope,t):
        p=verify_review(envelope,self._store.trust,at=t.isoformat())
        expected={"kind":"ROLE_MEMORY_V1","role_id":self._role,"note_id":nid,"domain":self.domain,"skill":task_id(self._role),"relevance_verified":True,"evidence_entailment_verified":True,"data_rights_verified":True,"no_sensitive_content_verified":True,"safe_annotation_verified":True}
        if any(p.get(k)!=v for k,v in expected.items()) or not p.get("producer_organization") or p.get("cloud_allowed") is not (n["visibility"]=="public_reviewed"):raise PermissionError("review not bound to role and memory")
        if iso(p["reviewed_at"])<iso(n["created_at"]):raise ValueError("review predates note")
        self._evidence(n,t)
        return p
    def approve(self,nid,envelope):
        now=self._time()
        with self._store._db(self._role) as c:
            c.execute("BEGIN IMMEDIATE");n=self._note(c,nid);state=self._state(c,now)
            if state.get(nid,{}).get("action")!="PROPOSED":raise ValueError("candidate not pending")
            self._verify(nid,n,envelope,now)
            conflicts=[]
            for k,e in state.items():
                if e["action"]!="APPROVED" or k==nid:continue
                old=self._note(c,k)
                if all(old[f]==n[f] for f in ("kind","topic","security_id","visibility")):conflicts.append(k)
            if conflicts!=([n["supersedes"]] if n["supersedes"] else []):raise ValueError("conflicting topic; explicit active revision required")
            if conflicts:self._append(c,{"role_id":self._role,"note_id":conflicts[0],"action":"SUPERSEDED","at":now.isoformat(),"successor":nid})
            self._append(c,{"role_id":self._role,"note_id":nid,"action":"APPROVED","at":now.isoformat(),"review":envelope})
    def revoke(self,nid):
        now=self._time()
        with self._store._db(self._role) as c:
            c.execute("BEGIN IMMEDIATE");self._note(c,nid);s=self._state(c,now)
            if s.get(nid,{}).get("action") not in ("APPROVED","PROPOSED"):raise ValueError("not active")
            self._append(c,{"role_id":self._role,"note_id":nid,"action":"REVOKED","at":now.isoformat()})
    def search(self,query,*,security_id,at=None,cloud=False,limit=5):
        """Scope and authorization filtering precede scoring; only reviewed notes."""
        if not isinstance(query,str) or not 1<=len(query)<=500 or not _token(security_id) or type(limit) is not int or not 1<=limit<=20 or type(cloud) is not bool:raise ValueError("invalid memory query")
        if cloud and self._store.skills[self._role]["scope"]!="public_only":raise PermissionError("cloud access denied")
        t=self._time(at);now=self._time();terms=set(re.findall(r"[a-z0-9]+",query.lower()));out=[]
        with self._store._db(self._role) as c:
            state=self._state(c,t);current=self._state(c,now)
            for nid,e in state.items():
                if e["action"]!="APPROVED" or current.get(nid,{}).get("action")!="APPROVED":continue
                n=self._note(c,nid)
                if n["skill"]!=task_id(self._role) or n["security_id"]!=security_id or (cloud and n["visibility"]!="public_reviewed"):continue
                try:self._verify(nid,n,e["review"],now)
                except (ValueError,PermissionError,KeyError,TypeError):continue
                words=set(re.findall(r"[a-z0-9]+",(n["topic"]+" "+n["text"]).lower()));score=len(terms&words)
                if score:out.append((score,nid,{"memory_id":nid,"role_id":self._role,"domain":self.domain,"kind":n["kind"],"text":n["text"],"source_record_ids":n["evidence_ids"],"untrusted_annotation":True,"not_evidence":True}))
        return [v for _,_,v in sorted(out,key=lambda x:(-x[0],x[1]))[:limit]]
    def propose_share(self,source,nid,*,topic):
        """Operator-only reviewed public source -> new destination quarantine."""
        if not isinstance(source,RoleMemory) or source._store is not self._store or source.role_id==self._role or not _token(topic):raise PermissionError("invalid share source")
        now=self._time()
        with self._store._db(source.role_id) as c:
            n=source._note(c,nid);e=source._state(c,now).get(nid,{})
            if e.get("action")!="APPROVED" or n["visibility"]!="public_reviewed":raise PermissionError("only reviewed public memory may be proposed for sharing")
            source._verify(nid,n,e["review"],now)
        # No inherited approval; even public notes require recipient-specific review.
        new=n|{"role_id":self._role,"domain":self.domain,"topic":topic,"visibility":"local","skill":task_id(self._role),"created_at":now.isoformat(),"supersedes":None,"shared_from":{"role_id":source.role_id,"note_id":nid}}
        return self._insert(new)
    def record_episode(self,*,task_id_value,result_hash,status,at):
        """Trusted journal metadata only; no raw prompt, holdings, or memo retained."""
        if not _token(task_id_value) or not _hash(result_hash) or not _token(status):raise ValueError("invalid episode")
        observed=self._time(at)
        p={"role_id":self._role,"skill":task_id(self._role),"task":task_id_value,"result_hash":result_hash,"status":status,"observed_at":observed.isoformat()}
        eid=digest({"role":self._role,"task":task_id_value})
        with self._store._db(self._role) as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT payload FROM episodes WHERE id=?",(eid,)).fetchone()
            if row and json.loads(row[0])!=p:raise ValueError("episode conflict")
            c.execute("INSERT OR IGNORE INTO episodes VALUES(?,?)",(eid,canonical(p)))
        return eid
    def stats(self):
        now=self._time()
        with self._store._db(self._role) as c:
            state=self._state(c,now)
            counts={k:0 for k in ("PROPOSED","APPROVED","SUPERSEDED","REVOKED")}
            for nid,e in state.items():self._note(c,nid);counts[e["action"]]+=1
            episodes=c.execute("SELECT count(*) FROM episodes").fetchone()[0]
        return {"role_id":self._role,"domain":self.domain,"counts":counts,"episodes":episodes,"can_trade":False,"promotion_allowed":False}
