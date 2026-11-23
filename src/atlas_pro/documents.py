"""Bounded deterministic text chunking and optional offline embedding model.
Only operator-authorized sources may be indexed; no bulk copyrighted crawling.
"""
from __future__ import annotations
from pathlib import Path
import hashlib, re, os
from .ledger import digest


def index_document(index, document, policy, *, embed=None, chunk_chars=1200, overlap=160):
    if not isinstance(chunk_chars,int) or not isinstance(overlap,int) or not 200<=chunk_chars<=1600 or not 0<=overlap<chunk_chars//2:
        raise ValueError('chunk bounds')
    body=document['content']
    if not isinstance(body,str) or not body.strip() or len(body)>5_000_000:raise ValueError('document bounds')
    parent=document['doc_id']; parent_hash=hashlib.sha256(body.encode()).hexdigest()
    ids=[]; start=0
    while start<len(body):
        end=min(len(body),start+chunk_chars)
        if end<len(body):
            split=body.rfind('\n',start+chunk_chars//2,end)
            if split>start:end=split
        chunk=body[start:end]
        cid=digest({'parent':parent,'source_hash':parent_hash,'start':start,'end':end})
        # Chunk location is kept in the source URI fragment so citation offsets survive retrieval.
        index.add(document|{'doc_id':cid,'source_uri':document['source_uri'].split('#')[0]+f'#atlas-chars={start}-{end}', 'content':chunk},policy,embed=embed)
        ids.append(cid)
        if end==len(body):break
        start=end-overlap
    return {'parent_id':parent,'parent_sha256':parent_hash,'chunk_ids':ids}

class LocalEmbedding:
    """Load a pinned local sentence-transformer folder. Never download at runtime.
    Use a separate index file per model ID/revision. This is not a sandbox: run
    in an egress-denied process for private data. No remote custom code permitted.
    """
    local_only=True
    def __init__(self,model_directory,*,expected_manifest_sha256):
        root=Path(model_directory).resolve(strict=True)
        if not root.is_dir():raise ValueError('local model folder required')
        manifest=[]
        for p in sorted(root.rglob('*')):
            if p.is_symlink():raise ValueError('symlinks forbidden in pinned model folder')
            if p.is_file():
                h=hashlib.sha256()
                with p.open('rb') as f:
                    for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
                manifest.append([p.relative_to(root).as_posix(),h.hexdigest()])
        if digest(manifest)!=expected_manifest_sha256:raise ValueError('MODEL_ARTIFACT_HASH_MISMATCH')
        from sentence_transformers import SentenceTransformer
        self.model=SentenceTransformer(str(root),local_files_only=True,trust_remote_code=False)
        self.model_id=expected_manifest_sha256
    def __call__(self,text):
        return self.model.encode(text,normalize_embeddings=True,convert_to_numpy=True).tolist()
