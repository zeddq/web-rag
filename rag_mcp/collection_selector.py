"""Collection selection logic for multi-collection RAG system.

This module provides intelligent collection selection based on query analysis,
using a hybrid approach combining keyword matching and semantic similarity.

Performance optimizations include:
- Multi-level embedding cache (L1 in-memory, optional L2 disk)
- Collection precomputation at startup
- Fast path optimization (<100ms target)
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sentence_transformers import SentenceTransformer

from .collection_preprocessor import CollectionPreprocessor, get_collection_preprocessor
from .config import CollectionConfig, MultiCollectionConfig
from .embedding_cache import EmbeddingCache, get_embedding_cache
from .model_manager import ModelManager

logger = logging.getLogger(__name__)


@dataclass
class CollectionScore:
    """Score details for a single collection."""

    collection_id: str
    keyword_score: float
    semantic_score: float
    combined_score: float
    reasoning: str


@dataclass
class CollectionSelection:
    """Result of collection selection process."""

    collection_id: Optional[str]
    confidence: float
    reasoning: str
    all_scores: List[CollectionScore] = field(default_factory=list)

    @property
    def is_successful(self) -> bool:
        """Check if a suitable collection was selected."""
        return self.collection_id is not None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "collection_id": self.collection_id,
            "confidence": float(self.confidence),
            "reasoning": self.reasoning,
            "is_successful": self.is_successful,
            "all_scores": [
                {
                    "collection_id": score.collection_id,
                    "keyword_score": float(score.keyword_score),
                    "semantic_score": float(score.semantic_score),
                    "combined_score": float(score.combined_score),
                    "reasoning": score.reasoning,
                }
                for score in self.all_scores
            ],
        }


class CollectionSelector:
    """Intelligent collection selector using hybrid matching strategies.

    Features fast path optimization with:
    - Cache hit check (< 10ms target)
    - Keyword match fallback (< 20ms target)
    - Full embedding computation only when needed (< 100ms target)
    """

    def __init__(
        self,
        config: MultiCollectionConfig,
        confidence_threshold: float = 0.4,
        semantic_weight: float = 0.6,
        keyword_weight: float = 0.4,
        enable_cache: bool = True,
        enable_preprocessor: bool = True,
        cache_ttl: int = 3600,
        cache_size: int = 10000,
    ):
        """Initialize the collection selector.

        Args:
            config: Multi-collection configuration
            confidence_threshold: Minimum confidence required for selection (0-1)
            semantic_weight: Weight for semantic similarity in hybrid scoring
            keyword_weight: Weight for keyword matching in hybrid scoring
            enable_cache: Whether to enable embedding cache
            enable_preprocessor: Whether to enable collection preprocessor
            cache_ttl: Cache TTL in seconds
            cache_size: Maximum cache size
        """
        self.config = config
        self.confidence_threshold = confidence_threshold
        self.semantic_weight = semantic_weight
        self.keyword_weight = keyword_weight
        self.enable_cache = enable_cache
        self.enable_preprocessor = enable_preprocessor

        # Use ModelManager for shared model instance
        self._model_manager = ModelManager()

        # Initialize embedding cache if enabled
        if enable_cache:
            self._embedding_cache = get_embedding_cache(
                max_size=cache_size,
                ttl_seconds=cache_ttl,
            )
        else:
            self._embedding_cache = None

        # Initialize collection preprocessor if enabled
        if enable_preprocessor:
            self._preprocessor = CollectionPreprocessor(
                config=config,
                cache_embeddings=enable_cache,
                precompute_async=True,
            )
            # Get global instance for reuse
            get_collection_preprocessor(config)
        else:
            self._preprocessor = None

        # Build keyword index for fast matching
        self._keyword_index = self._build_keyword_index()

        # Performance metrics
        self._selection_times = []
        self._cache_hit_count = 0
        self._cache_miss_count = 0

        logger.info(
            f"CollectionSelector initialized with {len(self.config.collections)} collections, "
            f"threshold={confidence_threshold}, cache={enable_cache}, preprocessor={enable_preprocessor}"
        )

    def select_collection(self, query: str) -> CollectionSelection:
        """Select the most appropriate collection for a query.

        Uses fast path optimization:
        1. Check cache for precomputed results (<10ms)
        2. Try keyword-only matching (<20ms)
        3. Fall back to full hybrid selection (<100ms)

        Args:
            query: User query string

        Returns:
            CollectionSelection with the best match and detailed scoring
        """
        start_time = time.time()

        if not query.strip():
            return CollectionSelection(
                collection_id=None,
                confidence=0.0,
                reasoning="Empty query provided",
            )

        # Fast Path 1: Check for explicit collection reference (@collection_name syntax)
        explicit_match = self._check_explicit_reference(query)
        if explicit_match:
            elapsed_ms = (time.time() - start_time) * 1000
            self._record_selection_time(elapsed_ms)
            logger.debug(f"Explicit reference matched in {elapsed_ms:.2f}ms")
            return explicit_match

        # Fast Path 2: If only one collection, return it with high confidence
        if len(self.config.collections) == 1:
            collection_id = next(iter(self.config.collections.keys()))
            elapsed_ms = (time.time() - start_time) * 1000
            self._record_selection_time(elapsed_ms)
            logger.debug(f"Single collection selected in {elapsed_ms:.2f}ms")
            return CollectionSelection(
                collection_id=collection_id,
                confidence=1.0,
                reasoning="Only one collection available",
            )

        # Fast Path 3: Try keyword-only matching first
        keyword_result = self._fast_keyword_selection(query)
        if keyword_result and keyword_result.confidence >= self.confidence_threshold:
            elapsed_ms = (time.time() - start_time) * 1000
            self._record_selection_time(elapsed_ms)
            logger.debug(f"Fast keyword selection succeeded in {elapsed_ms:.2f}ms")
            return keyword_result

        # Full Path: Perform hybrid selection with embeddings
        result = self._hybrid_selection(query)

        elapsed_ms = (time.time() - start_time) * 1000
        self._record_selection_time(elapsed_ms)
        logger.debug(f"Hybrid selection completed in {elapsed_ms:.2f}ms")

        return result

    def _check_explicit_reference(self, query: str) -> Optional[CollectionSelection]:
        """Check for explicit collection reference in query using @syntax.

        Args:
            query: User query string

        Returns:
            CollectionSelection if explicit reference found, None otherwise
        """
        # Look for @collection_name pattern
        pattern = r"@(\w+)"
        matches = re.findall(pattern, query)

        if not matches:
            return None

        # Use the first match
        collection_name = matches[0].lower()

        # Try exact ID match first
        if collection_name in self.config.collections:
            logger.info(f"Explicit collection reference found: @{collection_name}")
            return CollectionSelection(
                collection_id=collection_name,
                confidence=1.0,
                reasoning=f"Explicit collection reference: @{collection_name}",
            )

        # Try partial name matching
        for coll_id, collection in self.config.collections.items():
            if (
                collection_name in coll_id.lower()
                or collection_name in collection.name.lower()
                or collection_name in [tag.lower() for tag in collection.tags]
            ):
                logger.info(
                    f"Partial explicit collection match: @{collection_name} -> {coll_id}"
                )
                return CollectionSelection(
                    collection_id=coll_id,
                    confidence=0.9,
                    reasoning=f"Partial explicit reference match: @{collection_name} -> {coll_id}",
                )

        # No matching collection found
        logger.warning(f"Explicit collection reference @{collection_name} not found")
        return CollectionSelection(
            collection_id=None,
            confidence=0.0,
            reasoning=f"Explicit collection reference @{collection_name} not found",
        )

    def _fast_keyword_selection(self, query: str) -> Optional[CollectionSelection]:
        """Fast keyword-only selection without embeddings.

        This is a fast path that avoids embedding computation.

        Args:
            query: User query string

        Returns:
            CollectionSelection if confident match found, None otherwise
        """
        if not self._preprocessor:
            return None

        # Wait for preprocessor to be ready (should be instant if already done)
        if not self._preprocessor.wait_until_ready(timeout=0.1):
            return None

        # Extract keywords from query
        query_words = set(query.lower().split())

        # Find collections matching keywords
        matches = self._preprocessor.find_collections_by_keywords(
            list(query_words), min_matches=1
        )

        if not matches:
            return None

        # Check if we have a strong keyword match
        best_match = matches[0]
        collection_id, match_count = best_match

        # Calculate confidence based on match count
        # Higher match count = higher confidence
        confidence = min(match_count * 0.3, 1.0)

        if confidence >= self.confidence_threshold:
            return CollectionSelection(
                collection_id=collection_id,
                confidence=confidence,
                reasoning=f"Fast keyword match ({match_count} keywords)",
                all_scores=[],
            )

        return None

    def _hybrid_selection(self, query: str) -> CollectionSelection:
        """Perform hybrid selection combining keyword and semantic matching.

        Optimized with caching and precomputed embeddings.

        Args:
            query: User query string

        Returns:
            CollectionSelection with best hybrid match
        """
        scores = []

        for coll_id, collection in self.config.collections.items():
            keyword_score = self._keyword_score(query, collection)
            semantic_score = self._semantic_score_optimized(query, collection, coll_id)

            # Calculate combined score (cast to native float)
            combined_score = float(
                self.keyword_weight * keyword_score
                + self.semantic_weight * semantic_score
            )

            reasoning_parts = []
            if keyword_score > 0:
                reasoning_parts.append(f"keyword: {keyword_score:.2f}")
            if semantic_score > 0:
                reasoning_parts.append(f"semantic: {semantic_score:.2f}")

            reasoning = f"Hybrid match ({', '.join(reasoning_parts)})"

            scores.append(
                CollectionScore(
                    collection_id=coll_id,
                    keyword_score=float(keyword_score),
                    semantic_score=float(semantic_score),
                    combined_score=float(combined_score),
                    reasoning=reasoning,
                )
            )

        # Sort by combined score
        scores.sort(key=lambda x: x.combined_score, reverse=True)

        if not scores or scores[0].combined_score < self.confidence_threshold:
            return CollectionSelection(
                collection_id=None,
                confidence=scores[0].combined_score if scores else 0.0,
                reasoning=(
                    f"No collection meets confidence threshold "
                    f"({self.confidence_threshold:.2f})"
                ),
                all_scores=scores,
            )

        best_score = scores[0]
        return CollectionSelection(
            collection_id=best_score.collection_id,
            confidence=float(best_score.combined_score),
            reasoning=best_score.reasoning,
            all_scores=scores,
        )

    def _keyword_score(self, query: str, collection: CollectionConfig) -> float:
        """Calculate keyword-based matching score.

        Args:
            query: User query string
            collection: Collection configuration

        Returns:
            Keyword matching score (0-1)
        """
        if not query.strip():
            return 0.0

        query_lower = query.lower()
        query_tokens = set(query_lower.split())
        score = 0.0

        # Score based on tags (highest weight)
        for tag in collection.tags:
            tag_lower = tag.lower()
            if tag_lower in query_lower:
                score += 2.0
                logger.debug(f"Tag match: {tag} in query")

        # Score based on domain (handle hyphens/spaces)
        if collection.domain:
            domain_normalized = collection.domain.lower().replace("-", " ")
            domain_tokens = set(domain_normalized.split())
            domain_overlap = len(query_tokens & domain_tokens)
            if domain_overlap > 0:
                score += 1.5 * (domain_overlap / len(domain_tokens))
                logger.debug(
                    f"Domain match: {domain_overlap} tokens from {collection.domain}"
                )

        # Score based on collection name
        name_tokens = set(collection.name.lower().split())
        name_overlap = len(query_tokens & name_tokens)
        if name_overlap > 0:
            score += name_overlap * 0.8
            logger.debug(f"Name overlap: {name_overlap} tokens")

        # Score based on description
        desc_tokens = set(collection.description.lower().split())
        desc_overlap = len(query_tokens & desc_tokens)
        if desc_overlap > 0:
            score += desc_overlap * 0.3
            logger.debug(f"Description overlap: {desc_overlap} tokens")

        # Normalize to 0-1 range (max theoretical score ~10)
        normalized_score = min(score / 10.0, 1.0)

        logger.debug(
            f"Keyword score for {collection.id}: {normalized_score:.3f} "
            f"(raw: {score:.1f})"
        )

        return normalized_score

    def _semantic_score(self, query: str, collection: CollectionConfig) -> float:
        """Calculate semantic similarity score using embeddings (legacy method).

        Args:
            query: User query string
            collection: Collection configuration

        Returns:
            Semantic similarity score (0-1)
        """
        return self._semantic_score_optimized(query, collection, collection.id)

    def _semantic_score_optimized(
        self, query: str, collection: CollectionConfig, collection_id: str
    ) -> float:
        """Calculate semantic similarity score using embeddings with optimization.

        Uses caching and precomputed embeddings for performance.

        Args:
            query: User query string
            collection: Collection configuration
            collection_id: Collection identifier

        Returns:
            Semantic similarity score (0-1)
        """
        if not query.strip():
            return 0.0

        try:
            # Get query embedding (with caching)
            query_embedding = self._get_embedding_optimized(query)

            # Try to get precomputed collection embedding first
            collection_embedding = None
            if self._preprocessor:
                collection_embedding = self._preprocessor.get_collection_embedding(
                    collection_id
                )

            # Fall back to computing collection embedding if not precomputed
            if collection_embedding is None:
                collection_text = self._build_collection_text(collection)
                collection_embedding = self._get_embedding_optimized(collection_text)

            # Calculate cosine similarity
            similarity = self._cosine_similarity(query_embedding, collection_embedding)

            logger.debug(f"Semantic score for {collection_id}: {similarity:.3f}")

            return float(similarity)

        except Exception as e:
            logger.warning(f"Error calculating semantic score: {e}")
            return 0.0

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
            collection.domain,
            " ".join(collection.tags),
        ]
        return " ".join(part for part in parts if part)

    def _get_embedding(self, text: str) -> np.ndarray:
        """Get embedding for text (legacy method without optimization).

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        return self._get_embedding_optimized(text)

    def _get_embedding_optimized(self, text: str) -> np.ndarray:
        """Get embedding for text with multi-level caching.

        Checks cache first, then computes if needed.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        model_name = self.config.defaults.embedding_model or "all-MiniLM-L6-v2"

        # Check embedding cache if enabled
        if self._embedding_cache:
            cached_embedding = self._embedding_cache.get_embedding(text, model_name)
            if cached_embedding is not None:
                self._cache_hit_count += 1
                logger.debug(f"Cache hit for text (len={len(text)})")
                return cached_embedding
            else:
                self._cache_miss_count += 1

        # Get model from ModelManager (singleton pattern ensures efficient reuse)
        model = self._model_manager.get_model(model_name)

        # Compute embedding
        embedding = model.encode(text, convert_to_numpy=True, show_progress_bar=False)

        # Store in cache if enabled
        if self._embedding_cache:
            self._embedding_cache.store_embedding(text, model_name, embedding)
            logger.debug(f"Computed and cached embedding for text (len={len(text)})")

        return embedding

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors.

        Args:
            vec1: First vector
            vec2: Second vector

        Returns:
            Cosine similarity (-1 to 1, normalized to 0-1)
        """
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        cosine_sim = dot_product / (norm1 * norm2)

        # Normalize from [-1, 1] to [0, 1]
        return float((cosine_sim + 1) / 2)

    def _build_keyword_index(self) -> Dict[str, List[str]]:
        """Build inverted index for fast keyword matching.

        Returns:
            Dictionary mapping keywords to collection IDs
        """
        index = {}

        for coll_id, collection in self.config.collections.items():
            # Index tags
            for tag in collection.tags:
                for word in tag.lower().split():
                    if word not in index:
                        index[word] = []
                    if coll_id not in index[word]:
                        index[word].append(coll_id)

            # Index domain
            if collection.domain:
                for word in collection.domain.lower().split():
                    if word not in index:
                        index[word] = []
                    if coll_id not in index[word]:
                        index[word].append(coll_id)

            # Index name
            for word in collection.name.lower().split():
                if word not in index:
                    index[word] = []
                if coll_id not in index[word]:
                    index[word].append(coll_id)

        logger.debug(f"Built keyword index with {len(index)} terms")
        return index

    def _record_selection_time(self, time_ms: float) -> None:
        """Record selection time for performance monitoring.

        Args:
            time_ms: Selection time in milliseconds
        """
        self._selection_times.append(time_ms)
        if len(self._selection_times) > 100:
            self._selection_times.pop(0)

    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get performance metrics for monitoring.

        Returns:
            Dictionary of performance metrics
        """
        metrics = {
            "avg_selection_time_ms": 0.0,
            "min_selection_time_ms": 0.0,
            "max_selection_time_ms": 0.0,
            "cache_hit_rate": 0.0,
            "cache_hits": self._cache_hit_count,
            "cache_misses": self._cache_miss_count,
        }

        if self._selection_times:
            metrics["avg_selection_time_ms"] = np.mean(self._selection_times)
            metrics["min_selection_time_ms"] = np.min(self._selection_times)
            metrics["max_selection_time_ms"] = np.max(self._selection_times)

        total_cache_requests = self._cache_hit_count + self._cache_miss_count
        if total_cache_requests > 0:
            metrics["cache_hit_rate"] = self._cache_hit_count / total_cache_requests

        # Add cache statistics if available
        if self._embedding_cache:
            cache_stats = self._embedding_cache.get_statistics()
            metrics["cache_stats"] = cache_stats.to_dict()

        # Add preprocessor statistics if available
        if self._preprocessor:
            preprocessor_stats = self._preprocessor.get_statistics()
            metrics["preprocessor_stats"] = preprocessor_stats.to_dict()

        return metrics


def create_selector(
    config: MultiCollectionConfig,
    **kwargs,
) -> CollectionSelector:
    """Factory function to create a CollectionSelector.

    Args:
        config: Multi-collection configuration
        **kwargs: Additional arguments for CollectionSelector

    Returns:
        Initialized CollectionSelector instance
    """
    return CollectionSelector(config, **kwargs)
