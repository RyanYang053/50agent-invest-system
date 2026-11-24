"""Role-scoped local-only upstream reference retrieval.

No external fetch or provider submission. Upstream instructions are untrusted.
Exact pinned git blob validation before search; no financial citation authority.
"""
from __future__ import annotations
import hashlib,re,sqlite3
from importlib.resources import files
from .employee_packs import reference_plan
from .query_terms import terms,excerpt

def local_reference(role_id,query,*,limit=5):
    if not isinstance(query,str) or not 1<=len(query)<=500 or type(limit) is not int or not 1<=limit<=10:raise ValueError("reference query bounds")
    tokens=terms(query)
    if not tokens:return []
    eligible=[]
    root=files("atlas_pro").joinpath("reference_library")
    for s in reference_plan(role_id):
        name=s.get("local_reference")
        if not name:continue
        if s.get("license") not in ("Apache-2.0","MIT","BSD-3-Clause") or not re.fullmatch(r"[a-z0-9_]+\.(md|rst)",name):raise PermissionError("reference license or filename")
        raw=root.joinpath(name).read_bytes()
        if len(raw)>250000:raise ValueError("reference too large")
        actual=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
        if actual!=s["git_blob_sha1"]:raise ValueError("upstream reference integrity failure")
        body=raw.decode("utf8")
        # Bounded overlapping character windows; no cross-role ranking corpus.
        for start in range(0,len(body),2400):
            chunk=body[start:start+3000]
            if chunk.strip():eligible.append((s,start,chunk))
    if not eligible:return []
    with sqlite3.connect(":memory:") as c:
        c.execute("CREATE VIRTUAL TABLE corpus USING fts5(content, tokenize='unicode61')")
        c.executemany("INSERT INTO corpus(rowid,content) VALUES(?,?)",[(i+1,x[2]) for i,x in enumerate(eligible)])
        q=" OR ".join('"'+t.replace('"','')+'"' for t in tokens)
        hits=c.execute("SELECT rowid,bm25(corpus) FROM corpus WHERE corpus MATCH ? ORDER BY bm25(corpus),rowid LIMIT ?",(q,limit)).fetchall()
    result=[]
    for rowid,score in hits:
        s,start,chunk=eligible[rowid-1];text,a,b=excerpt(chunk,tokens)
        result.append({"role_id":role_id,"source_id":s["source_id"],"source_url":s["url"],"license":s["license"],"upstream_blob":s["git_blob_sha1"],"excerpt_start":start+a,"excerpt_end":start+b,"excerpt_sha256":hashlib.sha256(text.encode()).hexdigest(),"text":text,"local_only":True,"untrusted_source_text":True,"not_financial_evidence":True})
    return result
