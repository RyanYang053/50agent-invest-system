"""Private, role-scoped external reference snapshots. Never model instructions.
Operator attests rights and provenance; no model can write or promote this store.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, ssl, sqlite3, stat
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,ProxyHandler,HTTPSHandler
from .transport import NoRedirect
from .employee_packs import reference_plan
from .skill_contracts import contract
from .ledger import digest,iso
from .query_terms import terms,excerpt

HOSTS={"damodaran":{"pages.stern.nyu.edu"},"cra":{"www.canada.ca"},"occ":{"www.theocc.com"},"nist":{"airc.nist.gov","www.nist.gov","nvlpubs.nist.gov"}}
NIST_URL="https://airc.nist.gov/docs/playbook.json"
MAX_BYTES=4_000_000
MAX_SNAPSHOTS=200

def now():return datetime.now(timezone.utc)
def sha(raw):return hashlib.sha256(raw).hexdigest()

def validate_policy(source,url,policy):
    if source not in HOSTS:raise PermissionError("source not eligible for method learning")
    u=urlsplit(url)
    if u.scheme!="https" or u.hostname not in HOSTS[source] or u.username or u.password or u.port or u.fragment or u.query:
        raise PermissionError("source URL denied")
    if source=="cra" and not u.path.startswith("/en/revenue-agency/"):raise PermissionError("CRA path denied")
    if policy.get("source_id")!=source or policy.get("source_url")!=url or any(policy.get(k) is not True for k in ("rights_reviewed","allow_local_retention","allow_local_rag")) or policy.get("cloud_allowed") is not False:
        raise PermissionError("explicit local-only source rights required")
    if not isinstance(policy.get("license_note"),str) or not 1<=len(policy["license_note"])<=2000:
        raise ValueError("license note required")

def parse_body(raw,source,url):
    if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_BYTES:raise ValueError("snapshot bounds")
    s=raw.decode("utf-8")
    if source=="nist" and url==NIST_URL:
        data=json.loads(s)
        if not isinstance(data,list) or not 1<=len(data)<=150:raise ValueError("NIST schema")
        records=[];seen=set()
        for row in data:
            title=row["title"]
            if not isinstance(title,str) or not re.fullmatch(r"(GOVERN|MAP|MEASURE|MANAGE) [0-9]+\.[0-9]+",title) or title in seen:raise ValueError("NIST title")
            seen.add(title)
            fields=[row[k] for k in ("description","section_about","section_actions","section_doc")]
            if any(not isinstance(v,str) or len(v)>100000 for v in fields):raise ValueError("NIST text bounds")
            records.append(title+"\n"+"\n".join(fields))
        if not {"GOVERN","MAP","MEASURE","MANAGE"}<={x.split()[0] for x in seen}:raise ValueError("incomplete NIST functions")
        return "\n\n".join(records)
    if "\x00" in s or not s.strip() or s.lstrip().startswith(("<html","<!DOCTYPE","%PDF")):raise ValueError("provide plain UTF-8 extracted text, not HTML/PDF")
    return s

class ReferenceStore:
    def __init__(self,root,*,clock=now):
        self.root=Path(root);self.clock=clock
        if self.root.is_symlink():raise PermissionError("symlink reference root")
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        if os.name=="posix" and stat.S_IMODE(self.root.stat().st_mode)&0o077:raise PermissionError("reference root must be private")
        self.path=self.root/"references.sqlite"
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):raise PermissionError("unsafe reference DB")
        if not self.path.exists():
            try:os.close(os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600))
            except FileExistsError:pass
        if os.name=="posix" and stat.S_IMODE(self.path.stat().st_mode)&0o077:raise PermissionError("reference DB must be private")
        with closing(sqlite3.connect(self.path)) as c,c:
            c.execute("CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY,source TEXT NOT NULL,url TEXT NOT NULL,received TEXT NOT NULL,raw BLOB NOT NULL,meta TEXT NOT NULL)")
    def ingest(self,source,url,raw,policy):
        validate_policy(source,url,policy)
        parse_body(raw,source,url)
        stamp=iso(self.clock().isoformat()).isoformat()
        meta={"source_id":source,"source_url":url,"sha256":sha(raw),"received_at":stamp,"license_note":policy["license_note"],"cloud_allowed":False}
        nid=digest(meta)
        with closing(sqlite3.connect(self.path,timeout=10)) as c,c:
            c.execute("BEGIN IMMEDIATE")
            old=c.execute("SELECT id,raw,meta FROM snapshots WHERE source=? AND url=? ORDER BY received DESC,id LIMIT 1",(source,url)).fetchone()
            if old and sha(old[1])==meta["sha256"]:
                m=json.loads(old[2])
                if digest(m)!=old[0] or m["sha256"]!=sha(old[1]) or m["license_note"]!=meta["license_note"]:raise ValueError("snapshot integrity or rights conflict")
                return {"status":"UNCHANGED","snapshot_id":old[0],"sha256":meta["sha256"]}
            if c.execute("SELECT count(*) FROM snapshots").fetchone()[0]>=MAX_SNAPSHOTS:raise ValueError("reference capacity reached")
            c.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?)",(nid,source,url,stamp,raw,json.dumps(meta,sort_keys=True)))
        return {"status":"STORED","snapshot_id":nid,"sha256":meta["sha256"]}
    def search(self,role_id,query,*,at,limit=5):
        if not isinstance(query,str) or not 1<=len(query)<=500 or type(limit) is not int or not 1<=limit<=10:raise ValueError("query bounds")
        t=iso(at)
        if t>iso(self.clock().isoformat()):raise ValueError("future reference cutoff")
        allowed=sorted({x["source_id"] for x in reference_plan(role_id)}&HOSTS.keys())
        if not allowed:return []
        tokens=terms(query)
        if not tokens:return []
        with closing(sqlite3.connect(self.path)) as c:
            rows=c.execute("SELECT id,source,url,received,raw,meta FROM snapshots WHERE source IN ("+",".join("?" for _ in allowed)+") AND received<=? ORDER BY received DESC,id",allowed+[t.isoformat()]).fetchall()
        latest=set();chunks=[];total=0
        for nid,source,url,received,raw,metadata in rows:
            if (source,url) in latest:continue
            latest.add((source,url));m=json.loads(metadata)
            if digest(m)!=nid or m["sha256"]!=sha(raw) or m["source_id"]!=source or m["source_url"]!=url or m["received_at"]!=received or m["cloud_allowed"] is not False:raise ValueError("reference integrity failure")
            body=parse_body(raw,source,url);total+=len(body)
            if total>12_000_000:raise ValueError("reference retrieval capacity")
            for start in range(0,len(body),2400):
                text=body[start:start+3000]
                if text.strip():chunks.append((nid,m,start,text))
        if not chunks:return []
        with closing(sqlite3.connect(":memory:")) as c:
            c.execute("CREATE VIRTUAL TABLE corpus USING fts5(content, tokenize='unicode61')")
            c.executemany("INSERT INTO corpus(rowid,content) VALUES(?,?)",[(i+1,x[3]) for i,x in enumerate(chunks)])
            hits=c.execute("SELECT rowid FROM corpus WHERE corpus MATCH ? ORDER BY bm25(corpus),rowid LIMIT ?",(" OR ".join('"'+x.replace('"','')+'"' for x in tokens),limit)).fetchall()
        out=[]
        for (i,) in hits:
            nid,m,start,chunk=chunks[i-1];text,a,b=excerpt(chunk,tokens)
            out.append({"role_id":role_id,"snapshot_id":nid,**m,"normalized_excerpt_start":start+a,"normalized_excerpt_end":start+b,"excerpt_sha256":sha(text.encode()),"text":text,"local_only":True,"not_financial_evidence":True,"untrusted_source_text":True})
        return out

def fetch_nist(store,policy,*,network=False):
    validate_policy("nist",NIST_URL,policy)
    if network is not True:raise PermissionError("explicit network consent required")
    opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(Request(NIST_URL,headers={"Accept":"application/json","Accept-Encoding":"identity"},method="GET"),timeout=30) as r:
        raw=r.read(MAX_BYTES+1)
    return store.ingest("nist",NIST_URL,raw,policy)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--data-dir",type=Path,required=True)
    sub=p.add_subparsers(dest="cmd",required=True)
    i=sub.add_parser("import");i.add_argument("--file",type=Path,required=True);i.add_argument("--policy",type=Path,required=True)
    n=sub.add_parser("fetch-nist");n.add_argument("--policy",type=Path,required=True);n.add_argument("--network",action="store_true")
    q=sub.add_parser("search");q.add_argument("role_id");q.add_argument("query");q.add_argument("--at",default=None)
    a=p.parse_args(argv);os.umask(0o077);store=ReferenceStore(a.data_dir/"external-references")
    if a.cmd=="search":out=store.search(a.role_id,a.query,at=a.at or now().isoformat())
    else:
        policy=json.loads(a.policy.read_text())
        if a.cmd=="fetch-nist":out=fetch_nist(store,policy,network=a.network)
        else:
            with a.file.open("rb") as f:raw=f.read(MAX_BYTES+1)
            out=store.ingest(policy["source_id"],policy["source_url"],raw,policy)
    print(json.dumps(out,indent=2,ensure_ascii=False,allow_nan=False));return 0
if __name__=="__main__":raise SystemExit(main())
