from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

import httpx
import yaml
from tqdm import tqdm

from .chroma_store import build_embedding_function, get_client, get_or_create_collection

try:
    import trafilatura  # type: ignore
except Exception as e:  # pragma: no cover - optional import
    trafilatura = None


@dataclass
class IngestConfig:
    base_urls: List[str]
    allow_patterns: List[str]
    deny_patterns: List[str]
    max_pages: int = 500
    concurrency: int = 8
    chunk_chars: int = 1000
    chunk_overlap: int = 200
    # Chroma settings
    chroma_persist_dir: str = "data/chroma"
    chroma_collection: str = "web_rag"
    # Embeddings
    embedding_provider: str = "sentence-transformers"  # or "openai"
    embedding_model: str = "all-MiniLM-L6-v2"


def load_config(path: str) -> IngestConfig:
    with open(path, "r", encoding="utf-8") as f:
        y = yaml.safe_load(f)
    return IngestConfig(
        base_urls=y.get("base_urls", []),
        allow_patterns=y.get("allow_patterns", [".*"]),
        deny_patterns=y.get("deny_patterns", []),
        max_pages=y.get("max_pages", 500),
        concurrency=y.get("concurrency", 8),
        chunk_chars=y.get("chunk_chars", 1000),
        chunk_overlap=y.get("chunk_overlap", 200),
        chroma_persist_dir=y.get("chroma", {}).get("persist_dir", y.get("chroma_persist_dir", "data/chroma")),
        chroma_collection=y.get("chroma", {}).get("collection", y.get("chroma_collection", "web_rag")),
        embedding_provider=y.get("embedding_provider", "sentence-transformers"),
        embedding_model=y.get("embedding_model", "all-MiniLM-L6-v2"),
    )


def _allowed(url: str, allow: List[str], deny: List[str]) -> bool:
    if any(re.search(p, url) for p in deny):
        return False
    return any(re.search(p, url) for p in allow)


async def crawl(config: IngestConfig) -> List[Tuple[str, str, str]]:
    """Fetch pages and return list of (url, title, text)."""
    if trafilatura is None:
        raise RuntimeError("trafilatura is required for crawling; please install it")

    visited: Set[str] = set()
    to_visit: List[str] = list(dict.fromkeys(config.base_urls))
    results: List[Tuple[str, str, str]] = []

    async def fetch(client: httpx.AsyncClient, url: str) -> Optional[Tuple[str, str, str, List[str]]]:
        try:
            r = await client.get(url, timeout=20.0)
            r.raise_for_status()
        except Exception:
            return None
        html = r.text
        extracted = trafilatura.extract(html, url=url, include_comments=False, include_tables=False, favor_recall=True)
        if not extracted:
            return None
        title = None
        try:
            m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            if m:
                import re as _re
                title = _re.sub(r"\s+", " ", m.group(1)).strip()
        except Exception:
            title = None
        text = extracted.strip()
        links = re.findall(r"href=\"(.*?)\"", html)
        abs_links: List[str] = []
        from urllib.parse import urljoin
        for l in links:
            if l.startswith("javascript:") or l.startswith("#"):
                continue
            abs_links.append(urljoin(url, l))
        return url, (title or url), text, abs_links

    async with httpx.AsyncClient(follow_redirects=True, headers={"User-Agent": "web-rag-mcp/0.2"}) as client:
        pbar = tqdm(total=config.max_pages, desc="Crawling", unit="page")
        while to_visit and len(results) < config.max_pages:
            batch = []
            while to_visit and len(batch) < config.concurrency:
                u = to_visit.pop(0)
                if u in visited:
                    continue
                if not _allowed(u, config.allow_patterns, config.deny_patterns):
                    continue
                visited.add(u)
                batch.append(u)
            if not batch:
                break
            tasks = [fetch(client, u) for u in batch]
            fetched = await asyncio.gather(*tasks)
            for item in fetched:
                if not item:
                    continue
                url, title, text, links = item
                results.append((url, title, text))
                pbar.update(1)
                for l in links:
                    if l not in visited and _allowed(l, config.allow_patterns, config.deny_patterns):
                        to_visit.append(l)
        pbar.close()
    return results


def _chunk(text: str, size: int, overlap: int) -> List[Tuple[int, str]]:
    chunks = []
    i = 0
    n = len(text)
    while i < n:
        j = min(n, i + size)
        chunks.append((i, text[i:j]))
        if j == n:
            break
        i = j - overlap
        if i < 0:
            i = 0
    return chunks


def ingest_into_chroma(pages: List[Tuple[str, str, str]], cfg: IngestConfig) -> None:
    emb_fn = build_embedding_function(cfg.embedding_provider, cfg.embedding_model)
    client = get_client(cfg.chroma_persist_dir)
    col = get_or_create_collection(client, cfg.chroma_collection, emb_fn)

    ids: List[str] = []
    docs: List[str] = []
    metas: List[Dict[str, str | int]] = []

    for url, title, text in pages:
        for offset, chunk in _chunk(text, cfg.chunk_chars, cfg.chunk_overlap):
            cid = f"{abs(hash(url))}_{offset}"
            ids.append(cid)
            docs.append(chunk)
            metas.append({
                "url": url,
                "title": title,
                "offset": offset,
            })

    if not ids:
        raise RuntimeError("No data to add to Chroma.")

    B = 200
    for i in tqdm(range(0, len(ids), B), desc="Chroma add", unit="batch"):
        col.upsert(ids=ids[i:i+B], documents=docs[i:i+B], metadatas=metas[i:i+B])


def ingest_from_config(config_path: str) -> None:
    cfg = load_config(config_path)
    pages = asyncio.run(crawl(cfg))
    ingest_into_chroma(pages, cfg)
