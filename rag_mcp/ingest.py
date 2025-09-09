from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple, Mapping, Any

import httpx
import yaml
from tqdm import tqdm

from .chroma_store import build_embedding_function, get_client, get_or_create_collection
from .config import (
    CollectionConfig,
    MultiCollectionConfig,
    load_config,
    load_multi_config,
    ConfigurationError,
)

try:
    import trafilatura  # type: ignore
except Exception as e:  # pragma: no cover - optional import
    trafilatura = None


def _allowed(url: str, allow: List[str], deny: List[str]) -> bool:
    if any(re.search(p, url) for p in deny):
        return False
    return any(re.search(p, url) for p in allow)


async def crawl(
    config: CollectionConfig,
) -> List[Tuple[str, str, str]]:
    """Fetch pages and return list of (url, title, text)."""
    if trafilatura is None:
        raise RuntimeError("trafilatura is required for crawling; please install it")

    # Extract config values
    base_urls = config.sources.base_urls
    allow_patterns = config.sources.allow_patterns
    deny_patterns = config.sources.deny_patterns
    max_pages = config.max_pages
    concurrency = config.concurrency

    visited: Set[str] = set()
    to_visit: List[str] = list(dict.fromkeys(base_urls))
    results: List[Tuple[str, str, str]] = []

    async def fetch(
        client: httpx.AsyncClient, url: str
    ) -> Optional[Tuple[str, str, str, List[str]]]:
        try:
            r = await client.get(url, timeout=20.0)
            r.raise_for_status()
        except Exception:
            return None
        html = r.text
        extracted = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=False,
            favor_recall=True,
        )
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

    async with httpx.AsyncClient(
        follow_redirects=True, headers={"User-Agent": "web-rag-mcp/0.2"}
    ) as client:
        pbar = tqdm(total=max_pages, desc="Crawling", unit="page")
        while to_visit and len(results) < max_pages:
            batch: List[str] = []
            while to_visit and len(batch) < concurrency:
                u = to_visit.pop(0)
                if u in visited:
                    continue
                if not _allowed(u, allow_patterns, deny_patterns):
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
                    if l not in visited and _allowed(l, allow_patterns, deny_patterns):
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


def ingest_into_chroma(
    pages: List[Tuple[str, str, str]], cfg: CollectionConfig
) -> None:
    """Ingest pages into Chroma database."""
    # Extract config values
    embedding_provider = cfg.embedding_provider
    embedding_model = cfg.embedding_model
    chroma_persist_dir = cfg.chroma_persist_dir
    chroma_collection = cfg.chroma_collection or cfg.id
    chunk_chars = cfg.chunk_chars
    chunk_overlap = cfg.chunk_overlap
    collection_id = cfg.id

    emb_fn = build_embedding_function(embedding_provider, embedding_model)
    client = get_client(chroma_persist_dir)
    col = get_or_create_collection(client, chroma_collection, emb_fn)

    ids: List[str] = []
    docs: List[str] = []
    metas: List[Mapping[str, Any]] = []

    for url, title, text in pages:
        for offset, chunk in _chunk(text, chunk_chars, chunk_overlap):
            cid = f"{abs(hash(url))}_{offset}"
            ids.append(cid)
            docs.append(chunk)
            metas.append(
                {
                    "url": url,
                    "title": title,
                    "offset": offset,
                    "collection_id": collection_id,  # Add collection metadata
                }
            )

    if not ids:
        raise RuntimeError("No data to add to Chroma.")

    B = 200
    for i in tqdm(
        range(0, len(ids), B), desc=f"Chroma add ({collection_id})", unit="batch"
    ):
        col.upsert(
            ids=ids[i : i + B], documents=docs[i : i + B], metadatas=metas[i : i + B]
        )


def ingest_from_config(config_path: str, collection_id: str) -> None:
    """Ingest a specific collection from multi-collection configuration file.

    Args:
        config_path: Path to configuration file
        collection_id: ID of the collection to ingest

    Raises:
        ConfigurationError: If configuration is invalid or collection not found
    """
    try:
        config = load_config(config_path)

        if collection_id not in config.collections:
            raise ConfigurationError(
                f"Collection '{collection_id}' not found in configuration"
            )

        collection_config = config.collections[collection_id]
        print(f"Ingesting collection: {collection_config.name} (ID: {collection_id})")
        pages = asyncio.run(crawl(collection_config))
        ingest_into_chroma(pages, collection_config)
        print(
            f"Successfully ingested {len(pages)} pages into collection '{collection_id}'"
        )

    except ConfigurationError as e:
        print(f"Configuration error: {e}")
        raise
    except Exception as e:
        print(f"Ingestion failed: {e}")
        raise


def ingest_from_multi_config(
    config_path: str, collection_ids: Optional[List[str]] = None
) -> None:
    """Ingest from multi-collection configuration file.

    Args:
        config_path: Path to configuration file
        collection_ids: Optional list of specific collection IDs to ingest (all if None)

    Raises:
        ConfigurationError: If configuration is invalid
    """
    try:
        config = load_multi_config(config_path)

        # Determine which collections to process
        if collection_ids is None:
            collections_to_process = list(config.collections.keys())
        else:
            collections_to_process = collection_ids
            # Validate collection IDs exist
            for coll_id in collection_ids:
                if coll_id not in config.collections:
                    raise ConfigurationError(
                        f"Collection '{coll_id}' not found in configuration"
                    )

        print(
            f"Processing {len(collections_to_process)} collection(s): {', '.join(collections_to_process)}"
        )

        # Process each collection
        for coll_id in collections_to_process:
            collection_config = config.collections[coll_id]
            print(f"\nIngesting collection: {collection_config.name} (ID: {coll_id})")

            try:
                pages = asyncio.run(crawl(collection_config))
                ingest_into_chroma(pages, collection_config)
                print(
                    f"Successfully ingested {len(pages)} pages into collection '{coll_id}'"
                )

            except Exception as e:
                print(f"Failed to ingest collection '{coll_id}': {e}")
                # Continue with other collections
                continue

        print(f"\nCompleted ingestion for {len(collections_to_process)} collection(s)")

    except ConfigurationError as e:
        print(f"Configuration error: {e}")
        raise
    except Exception as e:
        print(f"Multi-collection ingestion failed: {e}")
        raise


def ingest_collection_by_id(config_path: str, collection_id: str) -> None:
    """Ingest a specific collection by ID from a multi-collection config.

    Args:
        config_path: Path to configuration file
        collection_id: ID of the collection to ingest

    Raises:
        ConfigurationError: If configuration is invalid or collection not found
    """
    ingest_from_multi_config(config_path, [collection_id])
