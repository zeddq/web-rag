"""Collection preprocessor for precomputing embeddings and building indexes.

This module handles:
- Precomputing collection embeddings at startup
- Building inverted index for keywords/tags
- Storing precomputed embeddings in cache
- Fast lookup for collection metadata
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
from sentence_transformers import SentenceTransformer

from .config import CollectionConfig, MultiCollectionConfig
from .embedding_cache import get_embedding_cache
from .model_manager import ModelManager

logger = logging.getLogger(__name__)


@dataclass
class CollectionMetadata:
    """Precomputed metadata for a collection."""

    collection_id: str
    embedding: Optional[np.ndarray] = None
    keywords: Set[str] = field(default_factory=set)
    tags: List[str] = field(default_factory=list)
    domain: Optional[str] = None
    description: str = ""
    precomputed_at: float = field(default_factory=time.time)


@dataclass
class IndexStatistics:
    """Statistics about the preprocessed index."""

    total_collections: int = 0
    precomputed_embeddings: int = 0
    total_keywords: int = 0
    total_tags: int = 0
    preprocessing_time_ms: float = 0.0

    def to_dict(self) -> Dict:
        """Convert statistics to dictionary."""
        return {
            "total_collections": self.total_collections,
            "precomputed_embeddings": self.precomputed_embeddings,
            "total_keywords": self.total_keywords,
            "total_tags": self.total_tags,
            "preprocessing_time_ms": f"{self.preprocessing_time_ms:.2f}",
        }


class CollectionPreprocessor:
    """Precompute and index collection metadata for fast lookup.

    This preprocessor:
    - Precomputes embeddings for all collections at startup
    - Builds inverted indexes for fast keyword/tag matching
    - Stores precomputed data in the embedding cache
    - Provides fast lookup methods for collection selection
    """

    def __init__(
        self,
        config: MultiCollectionConfig,
        model_name: Optional[str] = None,
        cache_embeddings: bool = True,
        precompute_async: bool = True,
    ):
        """Initialize the collection preprocessor.

        Args:
            config: Multi-collection configuration
            model_name: Model to use for embeddings (defaults to config)
            cache_embeddings: Whether to cache precomputed embeddings
            precompute_async: Whether to precompute asynchronously
        """
        self.config = config
        self.model_name = model_name or config.defaults.embedding_model
        self.cache_embeddings = cache_embeddings

        # Storage for precomputed data
        self.metadata: Dict[str, CollectionMetadata] = {}
        self.keyword_index: Dict[str, Set[str]] = {}  # keyword -> collection_ids
        self.tag_index: Dict[str, Set[str]] = {}  # tag -> collection_ids

        # Get shared instances
        self._model_manager = ModelManager()
        self._cache = get_embedding_cache() if cache_embeddings else None

        # Thread safety
        self._lock = threading.RLock()
        self._precompute_thread: Optional[threading.Thread] = None
        self._is_ready = threading.Event()

        # Statistics
        self.stats = IndexStatistics()

        # Start preprocessing
        if precompute_async:
            self._start_async_preprocessing()
        else:
            self.preprocess_collections()

        logger.info(
            f"CollectionPreprocessor initialized with {len(config.collections)} collections"
        )

    def preprocess_collections(self) -> None:
        """Precompute all collection embeddings and build indexes."""
        start_time = time.time()

        try:
            logger.info("Starting collection preprocessing...")

            # Get model from ModelManager (will be preloaded)
            model = self._model_manager.get_model(self.model_name)

            # Process each collection
            for collection_id, collection in self.config.collections.items():
                self._preprocess_single_collection(collection_id, collection, model)

            # Update statistics
            self.stats.total_collections = len(self.config.collections)
            self.stats.precomputed_embeddings = sum(
                1 for m in self.metadata.values() if m.embedding is not None
            )
            self.stats.total_keywords = len(self.keyword_index)
            self.stats.total_tags = len(self.tag_index)
            self.stats.preprocessing_time_ms = (time.time() - start_time) * 1000

            # Mark as ready
            self._is_ready.set()

            logger.info(
                f"Collection preprocessing completed in {self.stats.preprocessing_time_ms:.2f}ms: "
                f"{self.stats.precomputed_embeddings} embeddings, "
                f"{self.stats.total_keywords} keywords, "
                f"{self.stats.total_tags} tags"
            )

        except Exception as e:
            logger.error(f"Error during collection preprocessing: {e}")
            # Still mark as ready (with partial data)
            self._is_ready.set()
            raise

    def _preprocess_single_collection(
        self,
        collection_id: str,
        collection: CollectionConfig,
        model: SentenceTransformer,
    ) -> None:
        """Preprocess a single collection.

        Args:
            collection_id: Collection identifier
            collection: Collection configuration
            model: Model for computing embeddings
        """
        with self._lock:
            # Create metadata entry
            metadata = CollectionMetadata(
                collection_id=collection_id,
                tags=collection.tags,
                domain=collection.domain,
                description=collection.description,
            )

            # Build collection text for embedding
            collection_text = self._build_collection_text(collection)

            # Compute embedding
            try:
                # Check cache first
                if self._cache:
                    cached_embedding = self._cache.get_embedding(
                        collection_text, self.model_name
                    )
                    if cached_embedding is not None:
                        metadata.embedding = cached_embedding
                        logger.debug(
                            f"Using cached embedding for collection {collection_id}"
                        )
                    else:
                        # Compute and cache
                        embedding = model.encode(
                            collection_text,
                            convert_to_numpy=True,
                            show_progress_bar=False,
                        )
                        metadata.embedding = embedding
                        self._cache.store_embedding(
                            collection_text, self.model_name, embedding
                        )
                        logger.debug(
                            f"Computed and cached embedding for collection {collection_id}"
                        )
                else:
                    # No cache, just compute
                    embedding = model.encode(
                        collection_text, convert_to_numpy=True, show_progress_bar=False
                    )
                    metadata.embedding = embedding
                    logger.debug(f"Computed embedding for collection {collection_id}")

            except Exception as e:
                logger.warning(
                    f"Failed to compute embedding for collection {collection_id}: {e}"
                )

            # Extract keywords from collection
            keywords = self._extract_keywords(collection)
            metadata.keywords = keywords

            # Build keyword index
            for keyword in keywords:
                if keyword not in self.keyword_index:
                    self.keyword_index[keyword] = set()
                self.keyword_index[keyword].add(collection_id)

            # Build tag index
            for tag in collection.tags:
                tag_lower = tag.lower()
                if tag_lower not in self.tag_index:
                    self.tag_index[tag_lower] = set()
                self.tag_index[tag_lower].add(collection_id)

            # Store metadata
            self.metadata[collection_id] = metadata

    def _build_collection_text(self, collection: CollectionConfig) -> str:
        """Build text representation of collection for embedding.

        Args:
            collection: Collection configuration

        Returns:
            Combined text representation
        """
        parts = [
            collection.name,
            collection.description,
            collection.domain or "",
            " ".join(collection.tags),
        ]
        return " ".join(part for part in parts if part)

    def _extract_keywords(self, collection: CollectionConfig) -> Set[str]:
        """Extract keywords from collection metadata.

        Args:
            collection: Collection configuration

        Returns:
            Set of extracted keywords
        """
        keywords = set()

        # Add tags as keywords
        for tag in collection.tags:
            keywords.add(tag.lower())
            # Also add individual words from multi-word tags
            for word in tag.lower().split():
                if len(word) > 2:  # Skip very short words
                    keywords.add(word)

        # Add domain words
        if collection.domain:
            for word in collection.domain.lower().replace("-", " ").split():
                if len(word) > 2:
                    keywords.add(word)

        # Add name words
        for word in collection.name.lower().split():
            if len(word) > 2:
                keywords.add(word)

        # Add key words from description (simple approach)
        desc_words = collection.description.lower().split()
        # Focus on nouns/important words (simple heuristic)
        for word in desc_words:
            if len(word) > 4 and word.isalpha():
                keywords.add(word)

        return keywords

    def _start_async_preprocessing(self) -> None:
        """Start asynchronous preprocessing in background thread."""

        def preprocess_async():
            """Background preprocessing function."""
            try:
                self.preprocess_collections()
            except Exception as e:
                logger.error(f"Async preprocessing failed: {e}")

        self._precompute_thread = threading.Thread(
            target=preprocess_async, daemon=True, name="collection-preprocessor"
        )
        self._precompute_thread.start()
        logger.info("Started async collection preprocessing")

    def wait_until_ready(self, timeout: Optional[float] = 30.0) -> bool:
        """Wait until preprocessing is complete.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if ready, False if timeout
        """
        return self._is_ready.wait(timeout)

    def get_collection_embedding(self, collection_id: str) -> Optional[np.ndarray]:
        """Get precomputed embedding for a collection.

        Args:
            collection_id: Collection identifier

        Returns:
            Precomputed embedding or None if not available
        """
        with self._lock:
            metadata = self.metadata.get(collection_id)
            if metadata and metadata.embedding is not None:
                return metadata.embedding.copy()
            return None

    def get_collections_by_keyword(self, keyword: str) -> Set[str]:
        """Get collections that match a keyword.

        Args:
            keyword: Keyword to search for

        Returns:
            Set of collection IDs that match the keyword
        """
        with self._lock:
            return self.keyword_index.get(keyword.lower(), set()).copy()

    def get_collections_by_tag(self, tag: str) -> Set[str]:
        """Get collections that have a specific tag.

        Args:
            tag: Tag to search for

        Returns:
            Set of collection IDs with the tag
        """
        with self._lock:
            return self.tag_index.get(tag.lower(), set()).copy()

    def find_collections_by_keywords(
        self, keywords: List[str], min_matches: int = 1
    ) -> List[Tuple[str, int]]:
        """Find collections matching keywords with match count.

        Args:
            keywords: List of keywords to search for
            min_matches: Minimum number of keyword matches required

        Returns:
            List of (collection_id, match_count) tuples, sorted by match count
        """
        with self._lock:
            match_counts: Dict[str, int] = {}

            for keyword in keywords:
                keyword_lower = keyword.lower()

                # Check keyword index
                for collection_id in self.keyword_index.get(keyword_lower, []):
                    match_counts[collection_id] = match_counts.get(collection_id, 0) + 1

                # Check tag index
                for collection_id in self.tag_index.get(keyword_lower, []):
                    match_counts[collection_id] = match_counts.get(collection_id, 0) + 1

            # Filter by minimum matches and sort by count
            results = [
                (cid, count)
                for cid, count in match_counts.items()
                if count >= min_matches
            ]
            results.sort(key=lambda x: x[1], reverse=True)

            return results

    def get_all_embeddings(self) -> Dict[str, np.ndarray]:
        """Get all precomputed embeddings.

        Returns:
            Dictionary mapping collection IDs to embeddings
        """
        with self._lock:
            return {
                cid: metadata.embedding.copy()
                for cid, metadata in self.metadata.items()
                if metadata.embedding is not None
            }

    def preload_collection_embeddings(self) -> None:
        """Ensure all collection embeddings are loaded.

        This method can be called to force immediate loading of all embeddings,
        useful for warming up the cache before handling requests.
        """
        if not self._is_ready.is_set():
            logger.info("Waiting for preprocessing to complete...")
            self.wait_until_ready()

        # Access all embeddings to ensure they're in cache
        with self._lock:
            loaded_count = 0
            for collection_id, metadata in self.metadata.items():
                if metadata.embedding is not None:
                    loaded_count += 1

            logger.info(f"Preloaded {loaded_count} collection embeddings")

    def get_statistics(self) -> IndexStatistics:
        """Get preprocessing statistics.

        Returns:
            Current statistics
        """
        return self.stats

    def clear(self) -> None:
        """Clear all precomputed data."""
        with self._lock:
            self.metadata.clear()
            self.keyword_index.clear()
            self.tag_index.clear()
            self.stats = IndexStatistics()
            logger.info("Preprocessor data cleared")


# Global preprocessor instance (singleton pattern)
_global_preprocessor: Optional[CollectionPreprocessor] = None
_preprocessor_lock = threading.Lock()


def get_collection_preprocessor(
    config: Optional[MultiCollectionConfig] = None,
    reset: bool = False,
) -> Optional[CollectionPreprocessor]:
    """Get or create the global collection preprocessor instance.

    Args:
        config: Configuration for creating new instance
        reset: Whether to reset existing instance

    Returns:
        Global CollectionPreprocessor instance or None if no config provided
    """
    global _global_preprocessor

    if reset and _global_preprocessor:
        _global_preprocessor.clear()
        _global_preprocessor = None

    if _global_preprocessor is None and config is not None:
        with _preprocessor_lock:
            if _global_preprocessor is None:
                _global_preprocessor = CollectionPreprocessor(config)

    return _global_preprocessor
