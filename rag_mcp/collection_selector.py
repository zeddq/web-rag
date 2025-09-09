"""Collection selection logic for multi-collection RAG system.

This module provides intelligent collection selection based on query analysis,
using a hybrid approach combining keyword matching and semantic similarity.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sentence_transformers import SentenceTransformer

from .config import CollectionConfig, MultiCollectionConfig

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
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "is_successful": self.is_successful,
            "all_scores": [
                {
                    "collection_id": score.collection_id,
                    "keyword_score": score.keyword_score,
                    "semantic_score": score.semantic_score,
                    "combined_score": score.combined_score,
                    "reasoning": score.reasoning,
                }
                for score in self.all_scores
            ],
        }


class CollectionSelector:
    """Intelligent collection selector using hybrid matching strategies."""

    def __init__(
        self,
        config: MultiCollectionConfig,
        confidence_threshold: float = 0.4,
        semantic_weight: float = 0.6,
        keyword_weight: float = 0.4,
    ):
        """Initialize the collection selector.

        Args:
            config: Multi-collection configuration
            confidence_threshold: Minimum confidence required for selection (0-1)
            semantic_weight: Weight for semantic similarity in hybrid scoring
            keyword_weight: Weight for keyword matching in hybrid scoring
        """
        self.config = config
        self.confidence_threshold = confidence_threshold
        self.semantic_weight = semantic_weight
        self.keyword_weight = keyword_weight

        # Initialize sentence transformer for semantic matching
        self._model: Optional[SentenceTransformer] = None
        self._embedding_cache: Dict[str, np.ndarray] = {}

        # Build keyword index for fast matching
        self._keyword_index = self._build_keyword_index()

        logger.info(
            f"CollectionSelector initialized with {len(self.config.collections)} collections, "
            f"threshold={confidence_threshold}"
        )

    def select_collection(self, query: str) -> CollectionSelection:
        """Select the most appropriate collection for a query.

        Args:
            query: User query string

        Returns:
            CollectionSelection with the best match and detailed scoring
        """
        if not query.strip():
            return CollectionSelection(
                collection_id=None,
                confidence=0.0,
                reasoning="Empty query provided",
            )

        # Check for explicit collection reference (@collection_name syntax)
        explicit_match = self._check_explicit_reference(query)
        if explicit_match:
            return explicit_match

        # If only one collection, return it with high confidence
        if len(self.config.collections) == 1:
            collection_id = next(iter(self.config.collections.keys()))
            return CollectionSelection(
                collection_id=collection_id,
                confidence=1.0,
                reasoning="Only one collection available",
            )

        # Perform hybrid selection
        return self._hybrid_selection(query)

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

    def _hybrid_selection(self, query: str) -> CollectionSelection:
        """Perform hybrid selection combining keyword and semantic matching.

        Args:
            query: User query string

        Returns:
            CollectionSelection with best hybrid match
        """
        scores = []

        for coll_id, collection in self.config.collections.items():
            keyword_score = self._keyword_score(query, collection)
            semantic_score = self._semantic_score(query, collection)

            # Calculate combined score
            combined_score = (
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
                    keyword_score=keyword_score,
                    semantic_score=semantic_score,
                    combined_score=combined_score,
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
            confidence=best_score.combined_score,
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
        """Calculate semantic similarity score using embeddings.

        Args:
            query: User query string
            collection: Collection configuration

        Returns:
            Semantic similarity score (0-1)
        """
        if not query.strip():
            return 0.0

        try:
            # Initialize model if needed
            if self._model is None:
                # Use a lightweight model for fast selection
                self._model = SentenceTransformer("all-MiniLM-L6-v2")
                logger.debug("Initialized SentenceTransformer for semantic matching")

            # Get query embedding
            query_embedding = self._get_embedding(query)

            # Build collection description for embedding
            collection_text = self._build_collection_text(collection)
            collection_embedding = self._get_embedding(collection_text)

            # Calculate cosine similarity
            similarity = self._cosine_similarity(query_embedding, collection_embedding)

            logger.debug(f"Semantic score for {collection.id}: {similarity:.3f}")

            return similarity

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
        """Get embedding for text with caching.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        if text in self._embedding_cache:
            return self._embedding_cache[text]

        if self._model is None:
            raise RuntimeError("SentenceTransformer model not initialized")

        embedding = self._model.encode(text, convert_to_numpy=True)
        self._embedding_cache[text] = embedding
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
        return (cosine_sim + 1) / 2

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
