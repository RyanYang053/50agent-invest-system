"""Role-bound skill challenger registry. Promotion stages a reviewed release, never live code.

No model, source text, or candidate can execute commands, edit policy or grant tools.
Operator must independently evaluate, review and deploy the resulting release.
"""
from __future__ import annotations
import argparse,json,math,os,re,sqlite3,stat
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from .ledger import canonical,digest,iso
from .skill_contracts import contract,catalog,runtime_hash
from .employee_packs import pack,load
from .independent_review import verify_review,verify_artifacts,ishash,load_trust

def now():return datetime.now(timezone.utc).isoformat()
CHECKS={
 "evidence":"Before finalizing the assigned deliverable, explicitly list missing or conflicting evidence, verify its identity and availability, and abstain where necessary.",
 "numeric":"Independently recompute each material numerical claim from traceable inputs; state units, assumptions and reconciliation differences.",
 "uncertainty":"Present an alternative explanation or failure case and state the observable evidence that would invalidate the conclusion.",
}
STATUS_CHECK={"NO_EVIDENCE":"evidence","BLOCKED_INPUT":"numeric","MODEL_OUTPUT_REJECTED":"uncertainty"}

def paired_grade(cases,rows):
    if not isinstance(rows,list) or len(rows)!=len(cases):raise ValueError("incomplete paired results")
    expected={x["id"]:x for x in cases};seen=set();wins=losses=base=challenger=critical=negative=0
    for r in rows:
        if set(r)!={"id","baseline_pass","challenger_pass","challenger_boundary_pass","baseline_answer_hash","challenger_answer_hash"} or r["id"] not in expected or r["id"] in seen:raise ValueError("paired result mismatch")
        if any(type(r[k]) is not bool for k in ("baseline_pass","challenger_pass","challenger_boundary_pass")) or not all(ishash(r[k]) for k in ("baseline_answer_hash","challenger_answer_hash")):raise ValueError("invalid paired results")
        seen.add(r["id"]);a,b=r["baseline_pass"],r["challenger_pass"];n=expected[r["id"]]["negative"]
        base+=a;challenger+=b;wins+=b and not a;losses+=a and not b;negative+=n;critical+=not r["challenger_boundary_pass"] or (n and not b)
    # Exact one-sided paired sign test. Independence of cases is externally reviewed.
    d=wins+losses
    p=sum(math.comb(d,k) for k in range(wins,d+1))/(2**d) if d else 1.0
    improvement=(challenger-base)/len(rows)
    return {"n":len(rows),"baseline_quality":base/len(rows),"challenger_quality":challenger/len(rows),"wins":wins,"losses":losses,"p_one_sided":p,"improvement":improvement,"negative_cases":negative,"critical_failures":critical,"passes":negative>=20 and critical==0 and improvement>=.05 and p<=.01 and losses==0 and challenger/len(rows)>=.95}

class Evolution:
    def __init__(self,root,*,clock=now):
        self.root=Path(root);self.clock=clock
        if self.root.is_symlink():raise PermissionError("unsafe root")
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        if os.name=="posix" and stat.S_IMODE(self.root.stat().st_mode)&0o077:raise PermissionError("private root required")
        self.path=self.root/"evolution.sqlite"
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):raise PermissionError("unsafe database")
        if not self.path.exists():
            try:os.close(os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600))
            except FileExistsError:pass
        if os.name=="posix" and stat.S_IMODE(self.path.stat().st_mode)&0o077:raise PermissionError("private database required")
        with self.db() as c:
            c.executescript("""CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS locks(id TEXT PRIMARY KEY,payload TEXT NOT NULL,proposal_id TEXT UNIQUE);
            CREATE TABLE IF NOT EXISTS samples(role TEXT NOT NULL,sample_id TEXT NOT NULL,PRIMARY KEY(role,sample_id));
            CREATE TABLE IF NOT EXISTS evaluations(lock_id TEXT PRIMARY KEY,payload TEXT NOT NULL,hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS staged(role TEXT PRIMARY KEY,proposal_id TEXT NOT NULL,lock_id TEXT NOT NULL,review TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,payload TEXT NOT NULL,prev TEXT NOT NULL,hash TEXT NOT NULL);""")
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=15);c.execute("PRAGMA synchronous=FULL")
        try:yield c;c.commit()
        except Exception:c.rollback();raise
        finally:c.close()
    def _time(self):return iso(self.clock()).isoformat()
    def _get(self,c,table,key):
        if table not in ("proposals","locks"):raise ValueError("table")
        row=c.execute("SELECT payload FROM "+table+" WHERE id=?",(key,)).fetchone()
        if row is None:raise KeyError(key)
        p=json.loads(row[0])
        if digest(p)!=key:raise ValueError("record hash mismatch")
        return p
    def _events(self,c):
        prev="GENESIS"
        for raw,prior,h in c.execute("SELECT payload,prev,hash FROM events ORDER BY seq"):
            if prior!=prev or digest({"prev":prev,"event":json.loads(raw)})!=h:raise ValueError("event integrity")
            prev=h
        return prev
    def _append(self,c,action,data):
        prev=self._events(c);e={"action":action,"at":self._time(),"data":data}
        c.execute("INSERT INTO events(payload,prev,hash) VALUES(?,?,?)",(canonical(e),prev,digest({"prev":prev,"event":e})))
    def propose(self,role_id,check,reason_hashes):
        if role_id not in catalog() or check not in CHECKS or not isinstance(reason_hashes,list) or not 3<=len(reason_hashes)<=100 or len(set(reason_hashes))!=len(reason_hashes) or not all(ishash(x) for x in reason_hashes):raise ValueError("bounded role proposal required")
        p={"role_id":role_id,"base_runtime":runtime_hash(role_id),"base_pack":digest(pack(role_id)),"check":check,"reason_hashes":sorted(reason_hashes),"can_trade":False}
        key=digest(p)
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE");self._events(c)
            if not c.execute("SELECT 1 FROM proposals WHERE id=?",(key,)).fetchone():
                c.execute("INSERT INTO proposals VALUES(?,?)",(key,canonical(p)));self._append(c,"PROPOSED",{"id":key,"role":role_id})
        return key
    def reflect(self,role_id,episodes):
        """Blocked task counts generate hypotheses, never performance or competence claims."""
        if role_id not in catalog() or not isinstance(episodes,list) or len(episodes)>1000:raise ValueError("episode bounds")
        groups={k:set() for k in CHECKS}
        for e in episodes:
            if e.get("role_id")!=role_id or not ishash(e.get("result_hash")):raise PermissionError("episode scope or integrity")
            check=STATUS_CHECK.get(e.get("status"))
            if check:groups[check].add(e["result_hash"])
        return [self.propose(role_id,k,sorted(v)[:100]) for k,v in groups.items() if len(v)>=3]
    def lock(self,pid,cases,*,testset_hash,rubric_hash,confirmed=False):
        if confirmed is not True:raise PermissionError("independent holdout operator confirmation")
        if not all(ishash(x) for x in (testset_hash,rubric_hash)) or testset_hash==rubric_hash:raise ValueError("artifact hashes")
        if not isinstance(cases,list) or not 100<=len(cases)<=1000 or any(set(x)!={"id","negative","input_hash"} or not isinstance(x["id"],str) or not 1<=len(x["id"])<=160 or type(x["negative"]) is not bool or not ishash(x["input_hash"]) for x in cases):raise ValueError("invalid locked cases")
        if len({x["id"] for x in cases})!=len(cases) or len({x["input_hash"] for x in cases})!=len(cases) or sum(x["negative"] for x in cases)<20:raise ValueError("duplicate or inadequate holdout")
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE");p=self._get(c,"proposals",pid)
            if p["base_runtime"]!=runtime_hash(p["role_id"]):raise ValueError("stale proposal")
            m={"proposal_id":pid,"role_id":p["role_id"],"cases":cases,"testset_hash":testset_hash,"rubric_hash":rubric_hash,"locked_at":self._time()}
            key=digest(m)
            if c.execute("SELECT 1 FROM locks WHERE proposal_id=?",(pid,)).fetchone():raise ValueError("proposal already attempted")
            # Input hashes also consume the holdout; aliases do not reset it.
            for x in cases:
                for ident in ("id:"+x["id"],"hash:"+x["input_hash"]):
                    if c.execute("SELECT 1 FROM samples WHERE role=? AND sample_id=?",(p["role_id"],ident)).fetchone():raise ValueError("holdout already consumed")
                    c.execute("INSERT INTO samples VALUES(?,?)",(p["role_id"],ident))
            c.execute("INSERT INTO locks VALUES(?,?,?)",(key,canonical(m),pid));self._append(c,"LOCKED",{"id":key})
        return key
    def evaluate(self,lid,rows,*,artifact_dir):
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE");m=self._get(c,"locks",lid)
            if iso(self._time())<=iso(m["locked_at"]):raise ValueError("evaluation must follow lock")
            if c.execute("SELECT 1 FROM evaluations WHERE lock_id=?",(lid,)).fetchone():raise ValueError("one evaluation per lock")
            grade=paired_grade(m["cases"],rows)
            verify_artifacts([m["testset_hash"],m["rubric_hash"]]+[r[k] for r in rows for k in ("baseline_answer_hash","challenger_answer_hash")],artifact_dir)
            # Verify the locked testset itself joins to the preregistered cases.
            test=json.loads((Path(artifact_dir)/m["testset_hash"]).read_text())
            if test!={"cases":m["cases"]}:raise ValueError("locked testset mismatch")
            result={"lock_id":lid,"rows":rows,"grade":grade,"evaluated_at":self._time()}
            h=digest(result);c.execute("INSERT INTO evaluations VALUES(?,?,?)",(lid,canonical(result),h));self._append(c,"EVALUATED",{"id":lid,"hash":h})
        return {"evaluation_hash":h,**grade,"promotion_allowed":False}
    def stage(self,lid,envelope,trust,*,artifact_dir,owner_confirmed=False):
        if owner_confirmed is not True:raise PermissionError("owner confirmation required")
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE");m=self._get(c,"locks",lid);p=self._get(c,"proposals",m["proposal_id"])
            row=c.execute("SELECT payload,hash FROM evaluations WHERE lock_id=?",(lid,)).fetchone()
            if row is None:raise ValueError("evaluation required")
            result=json.loads(row[0]);grade=paired_grade(m["cases"],result["rows"])
            if digest(result)!=row[1] or grade!=result["grade"] or not grade["passes"]:raise ValueError("challenger not eligible")
            verify_artifacts([m["testset_hash"],m["rubric_hash"]]+[r[k] for r in result["rows"] for k in ("baseline_answer_hash","challenger_answer_hash")],artifact_dir)
            review=verify_review(envelope,trust,at=self._time())
            expected={"kind":"SKILL_CHALLENGER_V1","role_id":p["role_id"],"proposal_id":m["proposal_id"],"lock_id":lid,"evaluation_hash":row[1],"base_runtime":p["base_runtime"],"holdout_independence_verified":True,"real_tasks_verified":True,"data_rights_verified":True,"candidate_executed_verified":True,"baseline_executed_verified":True,"no_privilege_change_verified":True}
            if any(review.get(k)!=v for k,v in expected.items()) or iso(review["reviewed_at"])<iso(result["evaluated_at"]) or not review.get("producer_organization"):raise PermissionError("independent review not bound to comparison")
            if p["base_runtime"]!=runtime_hash(p["role_id"]) or p["base_pack"]!=digest(pack(p["role_id"])):raise ValueError("base revision changed")
            if c.execute("SELECT 1 FROM staged WHERE role=?",(p["role_id"],)).fetchone():raise ValueError("role already staged; rollback first")
            c.execute("INSERT INTO staged VALUES(?,?,?,?)",(p["role_id"],m["proposal_id"],lid,canonical(envelope)));self._append(c,"STAGED",{"role":p["role_id"],"id":m["proposal_id"]})
        return {"status":"STAGED_REVIEWED_RELEASE","role_id":p["role_id"],"live_activation":False,"can_trade":False}
    def export(self,role_id,trust):
        with self.db() as c:
            self._events(c);r=c.execute("SELECT proposal_id,lock_id,review FROM staged WHERE role=?",(role_id,)).fetchone()
            if r is None:raise ValueError("no staged candidate")
            p=self._get(c,"proposals",r[0]);m=self._get(c,"locks",r[1])
            review=verify_review(json.loads(r[2]),trust,at=self._time())
            if review.get("proposal_id")!=r[0] or review.get("lock_id")!=r[1] or review.get("role_id")!=role_id or p["role_id"]!=role_id or m["proposal_id"]!=r[0]:raise ValueError("staged scope")
            if p["base_runtime"]!=runtime_hash(role_id) or p["base_pack"]!=digest(pack(role_id)):raise ValueError("stale release")
            candidate=load();target=candidate["packs"][role_id]
            for card in target["cards"]:
                if card["kind"]=="quality":card["text"]+=" "+CHECKS[p["check"]]
            target["review_status"]="CANDIDATE_REQUIRES_RELEASE_AND_RECERTIFICATION"
            return {"proposal_id":r[0],"role_id":role_id,"base_runtime":p["base_runtime"],"employee_packs":candidate,"requires_new_runtime_certification":True,"live_activation":False,"can_trade":False}
    def rollback(self,role_id,*,owner_confirmed=False):
        if owner_confirmed is not True:raise PermissionError("owner confirmation required")
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE");r=c.execute("SELECT proposal_id FROM staged WHERE role=?",(role_id,)).fetchone()
            if r is None:raise ValueError("nothing staged")
            c.execute("DELETE FROM staged WHERE role=?",(role_id,));self._append(c,"ROLLED_BACK_STAGING",{"role":role_id,"id":r[0]})
        return {"status":"STAGING_ROLLED_BACK","live_activation":False,"can_trade":False}
    def status(self):
        with self.db() as c:
            self._events(c)
            return {"roles":len(catalog()),"proposals":c.execute("SELECT count(*) FROM proposals").fetchone()[0],"locked":c.execute("SELECT count(*) FROM locks").fetchone()[0],"evaluations":c.execute("SELECT count(*) FROM evaluations").fetchone()[0],"staged_roles":[r[0] for r in c.execute("SELECT role FROM staged ORDER BY role")],"live_activation":False,"can_trade":False}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--data-dir",type=Path,required=True);s=p.add_subparsers(dest="cmd",required=True)
    s.add_parser("status")
    for cmd in ("propose","reflect","lock","evaluate","stage","export","rollback"):
        q=s.add_parser(cmd);q.add_argument("--request",type=Path,required=True)
        if cmd in ("lock","stage","rollback"):q.add_argument("--confirm",action="store_true")
        if cmd in ("evaluate","stage"):q.add_argument("--artifacts",type=Path,required=True)
        if cmd in ("stage","export"):q.add_argument("--trust",type=Path,required=True)
    a=p.parse_args(argv);os.umask(0o077);e=Evolution(a.data_dir/"skill-evolution")
    if a.cmd=="status":out=e.status()
    else:
        r=json.loads(a.request.read_text())
        if a.cmd=="propose":out=e.propose(**r)
        elif a.cmd=="reflect":out=e.reflect(**r)
        elif a.cmd=="lock":out=e.lock(**r,confirmed=a.confirm)
        elif a.cmd=="evaluate":out=e.evaluate(**r,artifact_dir=a.artifacts)
        elif a.cmd=="stage":out=e.stage(**r,trust=load_trust(a.trust),artifact_dir=a.artifacts,owner_confirmed=a.confirm)
        elif a.cmd=="export":out=e.export(**r,trust=load_trust(a.trust))
        else:out=e.rollback(**r,owner_confirmed=a.confirm)
    print(json.dumps(out,indent=2,allow_nan=False));return 0
if __name__=="__main__":raise SystemExit(main())
