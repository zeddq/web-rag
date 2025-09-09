from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from mcp.server.fastmcp import FastMCP

from .chroma_store import build_embedding_function, get_client, get_or_create_collection

PERSIST_DIR = os.environ.get("CHROMA_PERSIST_DIR", os.environ.get("WEB_RAG_INDEX_DIR", "data/chroma"))
COLLECTION = os.environ.get("CHROMA_COLLECTION", "web_rag")
PROVIDER = os.environ.get("WEB_RAG_QUERY_PROVIDER", os.environ.get("EMBEDDING_PROVIDER", "sentence-transformers"))
MODEL = os.environ.get("WEB_RAG_QUERY_MODEL", os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))


class WebRAGState:
    def __init__(self) -> None:
        self.client = get_client(PERSIST_DIR)
        self.emb_fn = build_embedding_function(PROVIDER, MODEL)
        self.col = get_or_create_collection(self.client, COLLECTION, self.emb_fn)

    def has_data(self) -> bool:
        try:
            # If count is expensive, just try a tiny query as a ping
            r = self.col.peek(limit=1)
            return len(r.get("ids", [])) > 0
        except Exception:
            return False


server = FastMCP(
    "web-rag",
    instructions=(
        "MCP server providing semantic search over a local Chroma collection. "
        "Use the 'search' tool and read 'web-rag://chunk/<id>' resources."
    ),
)
_state: WebRAGState | None = None

def get_state() -> WebRAGState:
    global _state
    if _state is None:
        _state = WebRAGState()
    return _state


@server.resource(
    "web-rag://index/manifest",
    name="Web RAG Index Manifest",
    title="Web RAG Index Manifest",
    description="Summary of Chroma collection (sample URLs).",
    mime_type="application/json",
)
def manifest() -> str:
    st = get_state()
    sample = st.col.peek(limit=100)
    urls = []
    for m in sample.get("metadatas", []):
        if isinstance(m, dict) and "url" in m:
            urls.append(m["url"])  # type: ignore[index]
    body = {
        "collection": COLLECTION,
        "persist_dir": PERSIST_DIR,
        "sample_urls": sorted(list(set(urls)))[:100],
    }
    return json.dumps(body, ensure_ascii=False, indent=2)


@server.resource(
    "web-rag://chunk/{id}",
    name="Web RAG Chunk",
    title="Web RAG Chunk",
    description="Retrieve a specific chunk by id",
    mime_type="text/plain",
)
def read_chunk(id: str) -> str:
    st = get_state()
    res = st.col.get(ids=[id])
    if not res.get("ids"):
        raise ValueError(f"Chunk not found: {id}")
    doc = res["documents"][0]
    meta = res["metadatas"][0]
    return f"Title: {meta.get('title','')}\nURL: {meta.get('url','')}\nOffset: {meta.get('offset','')}\n\n{doc}"


@server.tool()
def search(query: str, k: int = 5) -> Dict[str, Any]:
    st = get_state()
    if not st.has_data():
        return {"results": []}
    qr = st.col.query(query_texts=[query], n_results=k)
    # qr fields: ids, distances or embeddings, documents, metadatas
    results: List[Dict[str, Any]] = []
    ids = qr.get("ids", [[]])[0]
    docs = qr.get("documents", [[]])[0]
    metas = qr.get("metadatas", [[]])[0]
    dists = qr.get("distances", [[]])
    scores = None
    if dists and dists[0]:
        # Convert Chroma distances to similarity-ish scores
        scores = [float(1.0 / (1.0 + float(d))) for d in dists[0]]
    for i, cid in enumerate(ids):
        meta = metas[i] if i < len(metas) else {}
        preview = docs[i][:320] if i < len(docs) and docs[i] else ""
        item = {
            "id": cid,
            "score": (scores[i] if scores and i < len(scores) else None),
            "title": meta.get("title"),
            "url": meta.get("url"),
            "offset": meta.get("offset"),
            "resource": f"web-rag://chunk/{cid}",
            "preview": preview,
        }
        results.append(item)
    return {"results": results}


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
