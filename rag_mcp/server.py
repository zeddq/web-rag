from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from .chroma_store import build_embedding_function, get_client, get_or_create_collection
from .collection_selector import CollectionSelector, create_selector
from .config import (
    CollectionConfig,
    MultiCollectionConfig,
    load_multi_config,
    ConfigurationError,
)

logger = logging.getLogger(__name__)

# Multi-collection config path
MULTI_CONFIG_PATH = os.environ.get(
    "MULTI_COLLECTION_CONFIG_PATH", "ingest/multi-collection.yml"
)


class CollectionInstance:
    """Wrapper for a single collection's Chroma resources."""

    def __init__(self, config: CollectionConfig):
        self.config = config
        self._client = None
        self._collection = None
        self._embedding_function = None

    @property
    def client(self):
        """Lazy-loaded Chroma client."""
        if self._client is None:
            self._client = get_client(self.config.chroma_persist_dir)
        return self._client

    @property
    def embedding_function(self):
        """Lazy-loaded embedding function."""
        if self._embedding_function is None:
            self._embedding_function = build_embedding_function(
                self.config.embedding_provider, self.config.embedding_model
            )
        return self._embedding_function

    @property
    def collection(self):
        """Lazy-loaded Chroma collection."""
        if self._collection is None:
            self._collection = get_or_create_collection(
                self.client,
                self.config.chroma_collection or self.config.id,
                self.embedding_function,
            )
        return self._collection

    def has_data(self) -> bool:
        """Check if collection has data."""
        try:
            r = self.collection.peek(limit=1)
            return len(r.get("ids", [])) > 0
        except Exception:
            return False

    def search(self, query: str, k: int = 5) -> Dict[str, Any]:
        """Search in this collection."""
        if not self.has_data():
            return {"results": []}

        qr = self.collection.query(query_texts=[query], n_results=k)
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
                "collection_id": self.config.id,
                "collection_name": self.config.name,
            }
            results.append(item)

        return {"results": results}

    def get_chunk(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific chunk by ID."""
        try:
            res = self.collection.get(ids=[chunk_id])
            if not res.get("ids"):
                return None

            doc = res["documents"][0]
            meta = res["metadatas"][0]
            return {
                "id": chunk_id,
                "document": doc,
                "metadata": meta,
                "collection_id": self.config.id,
                "collection_name": self.config.name,
            }
        except Exception as e:
            logger.warning(f"Error retrieving chunk {chunk_id}: {e}")
            return None

    def get_document_count(self) -> int:
        """Get total document count in collection."""
        try:
            return self.collection.count()
        except Exception:
            return 0

    def peek(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get sample documents from collection."""
        try:
            sample = self.collection.peek(limit=limit)
            results = []
            ids = sample.get("ids", [])
            metas = sample.get("metadatas", [])

            for i, chunk_id in enumerate(ids):
                meta = metas[i] if i < len(metas) else {}
                results.append(
                    {
                        "id": chunk_id,
                        "url": meta.get("url"),
                        "title": meta.get("title"),
                    }
                )

            return results
        except Exception:
            return []


class MultiCollectionState:
    """State manager for multi-collection RAG system."""

    def __init__(self, config: MultiCollectionConfig):
        self.config = config
        self.collections: Dict[str, CollectionInstance] = {}
        self.selector: Optional[CollectionSelector] = None

        # Initialize collection instances (lazy loading)
        for coll_id, coll_config in config.collections.items():
            self.collections[coll_id] = CollectionInstance(coll_config)

        logger.info(
            f"MultiCollectionState initialized with {len(self.collections)} collections"
        )

    def get_collection(self, collection_id: str) -> Optional[CollectionInstance]:
        """Get collection instance by ID."""
        return self.collections.get(collection_id)

    def get_selector(self) -> CollectionSelector:
        """Get collection selector (lazy initialization)."""
        if self.selector is None:
            self.selector = create_selector(self.config)
        return self.selector

    def search_collection(
        self, collection_id: str, query: str, k: int = 5
    ) -> Dict[str, Any]:
        """Search in a specific collection."""
        collection = self.get_collection(collection_id)
        if collection is None:
            return {"error": f"Collection '{collection_id}' not found", "results": []}

        return collection.search(query, k)

    def search_auto(self, query: str, k: int = 5) -> Dict[str, Any]:
        """Search with automatic collection selection."""
        selector = self.get_selector()
        selection = selector.select_collection(query)

        if not selection.is_successful:
            return {
                "error": "No suitable collection found",
                "selection_info": selection.to_dict(),
                "results": [],
            }

        # Search in selected collection
        search_results = self.search_collection(selection.collection_id, query, k)

        # Add selection info to results
        search_results["selection_info"] = selection.to_dict()

        return search_results

    def get_chunk_from_any_collection(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Find and return a chunk from any collection."""
        for collection in self.collections.values():
            chunk = collection.get_chunk(chunk_id)
            if chunk is not None:
                return chunk
        return None


# Initialize FastMCP server
server = FastMCP(
    "web-rag",
    instructions=(
        "MCP server providing semantic search over local Chroma collections. "
        "Use collection tools to explore and search across different document collections."
    ),
)

# Global state
_state: Optional[MultiCollectionState] = None


def get_state() -> MultiCollectionState:
    """Get multi-collection state, initializing if needed."""
    global _state

    if _state is not None:
        return _state

    # Try to load multi-collection config
    config_paths = [
        MULTI_CONFIG_PATH,
        "ingest/multi-collection.yml",
        "ingest/web_rag.yml",
    ]

    for config_path in config_paths:
        if os.path.exists(config_path):
            try:
                logger.info(f"Loading configuration from {config_path}")
                config = load_multi_config(config_path)
                _state = MultiCollectionState(config)
                return _state
            except ConfigurationError as e:
                logger.warning(f"Failed to load config from {config_path}: {e}")
                continue

    # No valid configuration found
    raise ConfigurationError(
        f"No valid multi-collection configuration found. "
        f"Tried paths: {config_paths}. "
        f"Please ensure a valid multi-collection configuration exists at one of these locations."
    )


# MCP Resources


@server.resource(
    "web-rag://index/manifest",
    name="Web RAG Index Manifest",
    title="Web RAG Index Manifest",
    description="Summary of all available collections and their sample URLs",
    mime_type="application/json",
)
def manifest() -> str:
    """Get manifest of all collections."""
    state = get_state()

    collections_info = []

    for coll_id, collection in state.collections.items():
        sample_docs = collection.peek(limit=50)
        sample_urls = list(
            set([doc.get("url", "") for doc in sample_docs if doc.get("url")])
        )

        collections_info.append(
            {
                "id": coll_id,
                "name": collection.config.name,
                "description": collection.config.description,
                "domain": collection.config.domain,
                "tags": collection.config.tags,
                "document_count": collection.get_document_count(),
                "sample_urls": sorted(sample_urls)[:20],
                "chroma_collection": collection.config.chroma_collection,
                "persist_dir": collection.config.chroma_persist_dir,
            }
        )

    body = {
        "collections": collections_info,
        "total_collections": len(collections_info),
        "config_version": state.config.version,
    }

    return json.dumps(body, ensure_ascii=False, indent=2)


@server.resource(
    "web-rag://chunk/{id}",
    name="Web RAG Chunk",
    title="Web RAG Chunk",
    description="Retrieve a specific chunk by ID from any collection",
    mime_type="text/plain",
)
def read_chunk(id: str) -> str:
    """Get chunk content by ID from any collection."""
    state = get_state()

    chunk = state.get_chunk_from_any_collection(id)
    if chunk is None:
        raise ValueError(f"Chunk not found: {id}")

    meta = chunk["metadata"]
    doc = chunk["document"]
    coll_name = chunk["collection_name"]

    return (
        f"Collection: {coll_name}\n"
        f"Title: {meta.get('title', '')}\n"
        f"URL: {meta.get('url', '')}\n"
        f"Offset: {meta.get('offset', '')}\n"
        f"\n{doc}"
    )


@server.resource(
    "web-rag://collection/{id}/info",
    name="Collection Info",
    title="Collection Information",
    description="Detailed information about a specific collection",
    mime_type="application/json",
)
def collection_info(id: str) -> str:
    """Get detailed information about a collection."""
    state = get_state()

    collection = state.get_collection(id)
    if collection is None:
        raise ValueError(f"Collection not found: {id}")

    config = collection.config
    sample_docs = collection.peek(limit=10)

    info = {
        "id": config.id,
        "name": config.name,
        "description": config.description,
        "domain": config.domain,
        "tags": config.tags,
        "config": {
            "chunk_chars": config.chunk_chars,
            "chunk_overlap": config.chunk_overlap,
            "embedding_provider": config.embedding_provider,
            "embedding_model": config.embedding_model,
            "max_pages": config.max_pages,
            "concurrency": config.concurrency,
        },
        "chroma": {
            "persist_dir": config.chroma_persist_dir,
            "collection": config.chroma_collection,
        },
        "stats": {
            "document_count": collection.get_document_count(),
            "has_data": collection.has_data(),
        },
        "metadata": config.metadata.to_dict(),
        "sources": config.sources.to_dict(),
        "sample_documents": sample_docs,
    }

    return json.dumps(info, ensure_ascii=False, indent=2)


# MCP Tools


@server.tool()
def search(
    query: str, k: int = 5, collection_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Search for relevant documents across collections.

    Args:
        query: Search query
        k: Number of results to return (default: 5)
        collection_id: Specific collection to search (optional)
                      If not provided, automatically selects best collection

    Returns:
        Dictionary with search results and metadata
    """
    state = get_state()

    # Handle explicit @collection syntax in query
    if query.startswith("@") and " " in query:
        parts = query.split(" ", 1)
        collection_ref = parts[0][1:]  # Remove @
        actual_query = parts[1]

        # Try to find collection by ID or name
        target_collection = None
        for coll_id, collection in state.collections.items():
            if (
                coll_id.lower() == collection_ref.lower()
                or collection.config.name.lower() == collection_ref.lower()
                or collection_ref.lower()
                in [tag.lower() for tag in collection.config.tags]
            ):
                target_collection = coll_id
                break

        if target_collection:
            collection_id = target_collection
            query = actual_query
            logger.info(
                f"Explicit collection reference: @{collection_ref} -> {collection_id}"
            )

    if collection_id is not None:
        # Search specific collection
        results = state.search_collection(collection_id, query, k)
        if "error" not in results:
            results["selection_info"] = {
                "collection_id": collection_id,
                "auto_selected": False,
                "confidence": 1.0,
                "reasoning": "Explicitly specified collection",
            }
        return results
    else:
        # Auto-select collection
        return state.search_auto(query, k)


@server.tool()
def select_collection(query: str, config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Analyze a query and select the most appropriate collection.

    Args:
        query: Search query to analyze
        config_path: Optional path to configuration file (uses default if not provided)

    Returns:
        Collection selection results with confidence and reasoning
    """
    if config_path:
        # Load custom config
        try:
            custom_config = load_multi_config(config_path)
            custom_state = MultiCollectionState(custom_config)
            selector = custom_state.get_selector()
        except ConfigurationError as e:
            return {
                "error": f"Failed to load config from {config_path}: {e}",
                "collection_id": None,
                "confidence": 0.0,
            }
    else:
        # Use current state
        state = get_state()
        selector = state.get_selector()

    selection = selector.select_collection(query)

    result = selection.to_dict()

    # Add collection info if successful
    if selection.is_successful:
        state = get_state()
        collection = state.get_collection(selection.collection_id)
        if collection:
            result["collection_info"] = {
                "id": collection.config.id,
                "name": collection.config.name,
                "description": collection.config.description,
                "domain": collection.config.domain,
                "tags": collection.config.tags,
            }

    return result


@server.tool()
def list_collections(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    List all available collections with metadata.

    Args:
        config_path: Optional path to configuration file (uses default if not provided)

    Returns:
        List of collections with their metadata
    """
    if config_path:
        # Load custom config
        try:
            custom_config = load_multi_config(config_path)
            custom_state = MultiCollectionState(custom_config)
            collections = custom_state.collections
        except ConfigurationError as e:
            return {
                "error": f"Failed to load config from {config_path}: {e}",
                "collections": [],
            }
    else:
        # Use current state
        state = get_state()
        collections = state.collections

    collection_list = []

    for coll_id, collection in collections.items():
        config = collection.config
        collection_list.append(
            {
                "id": coll_id,
                "name": config.name,
                "description": config.description,
                "domain": config.domain,
                "tags": config.tags,
                "document_count": collection.get_document_count(),
                "has_data": collection.has_data(),
                "embedding_provider": config.embedding_provider,
                "embedding_model": config.embedding_model,
                "chroma_collection": config.chroma_collection,
                "metadata": config.metadata.to_dict(),
            }
        )

    # Sort by priority and name
    collection_list.sort(key=lambda x: (x["metadata"].get("priority", 999), x["name"]))

    return {"collections": collection_list, "total": len(collection_list)}


@server.tool()
def get_collection_info(
    collection_id: str, config_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get detailed information about a specific collection.

    Args:
        collection_id: ID of the collection to inspect
        config_path: Optional path to configuration file (uses default if not provided)

    Returns:
        Detailed collection information including stats and sample documents
    """
    if config_path:
        # Load custom config
        try:
            custom_config = load_multi_config(config_path)
            custom_state = MultiCollectionState(custom_config)
        except ConfigurationError as e:
            return {"error": f"Failed to load config from {config_path}: {e}"}
    else:
        # Use current state
        custom_state = get_state()

    collection = custom_state.get_collection(collection_id)
    if collection is None:
        return {
            "error": f"Collection '{collection_id}' not found",
            "available_collections": list(custom_state.collections.keys()),
        }

    config = collection.config
    sample_docs = collection.peek(limit=10)
    sample_urls = list(
        set([doc.get("url", "") for doc in sample_docs if doc.get("url")])
    )

    return {
        "id": config.id,
        "name": config.name,
        "description": config.description,
        "domain": config.domain,
        "tags": config.tags,
        "configuration": {
            "chunk_chars": config.chunk_chars,
            "chunk_overlap": config.chunk_overlap,
            "embedding_provider": config.embedding_provider,
            "embedding_model": config.embedding_model,
            "max_pages": config.max_pages,
            "concurrency": config.concurrency,
        },
        "chroma": {
            "persist_dir": config.chroma_persist_dir,
            "collection": config.chroma_collection,
        },
        "sources": config.sources.to_dict(),
        "metadata": config.metadata.to_dict(),
        "statistics": {
            "document_count": collection.get_document_count(),
            "has_data": collection.has_data(),
        },
        "sample_urls": sorted(sample_urls)[:20],
        "sample_documents": sample_docs[:5],  # Limit sample docs
    }


def main() -> None:
    """Run the MCP server."""
    server.run()


if __name__ == "__main__":
    main()
