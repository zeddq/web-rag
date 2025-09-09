from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence

import chromadb
from chromadb import PersistentClient
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.utils import embedding_functions


def build_embedding_function(provider: str, model: str) -> Any:
    provider = provider.lower()
    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY required for OpenAI embeddings")
        return embedding_functions.OpenAIEmbeddingFunction(
            api_key=api_key,
            model_name=model or "text-embedding-3-small",
        )
    elif provider in {"sentence-transformers", "st"}:
        return embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=model or "all-MiniLM-L6-v2"
        )
    else:
        raise ValueError(f"Unsupported embedding provider: {provider}")


def get_client(persist_dir: str) -> ClientAPI:
    os.makedirs(persist_dir, exist_ok=True)
    return PersistentClient(path=persist_dir)


def get_or_create_collection(
    client: ClientAPI,
    name: str,
    embedding_fn: Any,
) -> Collection:
    try:
        col = client.get_collection(name=name)
        # If an existing collection has a different embedding fn, we still can query,
        # but for correctness, recreate or ensure you used the same settings.
        return col
    except Exception:
        return client.create_collection(name=name, embedding_function=embedding_fn)

