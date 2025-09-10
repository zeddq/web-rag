"""Multi-level embedding cache system for performance optimization.

This module provides a high-performance caching system for embeddings with:
- L1 in-memory LRU cache with TTL
- Optional L2 disk-based persistence
- Thread-safe operations
- Cache statistics and monitoring
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pickle
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Single cache entry with embedding and metadata."""

    embedding: np.ndarray
    timestamp: float
    text_hash: str
    access_count: int = 0
    last_access: float = field(default_factory=time.time)


@dataclass
class CacheStatistics:
    """Cache performance statistics."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    total_requests: int = 0
    l1_size: int = 0
    l2_size: int = 0
    avg_hit_time_ms: float = 0.0
    avg_miss_time_ms: float = 0.0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests

    def to_dict(self) -> Dict:
        """Convert statistics to dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "total_requests": self.total_requests,
            "hit_rate": f"{self.hit_rate:.2%}",
            "l1_size": self.l1_size,
            "l2_size": self.l2_size,
            "avg_hit_time_ms": f"{self.avg_hit_time_ms:.2f}",
            "avg_miss_time_ms": f"{self.avg_miss_time_ms:.2f}",
        }


class EmbeddingCache:
    """Multi-level cache for embeddings with LRU eviction and TTL.

    This cache provides:
    - Fast L1 in-memory cache with LRU eviction
    - Optional L2 disk-based cache for persistence
    - TTL-based expiration
    - Thread-safe operations
    - Comprehensive statistics
    """

    def __init__(
        self,
        max_size: int = 10000,
        ttl_seconds: int = 3600,
        l2_cache_dir: Optional[str] = None,
        enable_stats: bool = True,
    ):
        """Initialize the embedding cache.

        Args:
            max_size: Maximum number of entries in L1 cache
            ttl_seconds: Time-to-live for cache entries in seconds
            l2_cache_dir: Optional directory for L2 disk cache
            enable_stats: Whether to track cache statistics
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.enable_stats = enable_stats

        # L1 cache: In-memory LRU cache
        self.l1_cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()

        # L2 cache: Optional disk-based cache
        self.l2_cache_dir = None
        if l2_cache_dir:
            self.l2_cache_dir = Path(l2_cache_dir)
            self.l2_cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"L2 cache enabled at: {self.l2_cache_dir}")

        # Statistics
        self.stats = CacheStatistics()
        self._hit_times = []
        self._miss_times = []

        logger.info(
            f"EmbeddingCache initialized: max_size={max_size}, "
            f"ttl={ttl_seconds}s, l2_enabled={l2_cache_dir is not None}"
        )

    def get_embedding(self, text: str, model_name: str) -> Optional[np.ndarray]:
        """Get cached embedding if available.

        Args:
            text: Text that was embedded
            model_name: Name of the model used for embedding

        Returns:
            Cached embedding array or None if not found/expired
        """
        start_time = time.time()
        cache_key = self._generate_key(text, model_name)

        with self._lock:
            if self.enable_stats:
                self.stats.total_requests += 1

            # Check L1 cache
            if cache_key in self.l1_cache:
                entry = self.l1_cache[cache_key]

                # Check TTL
                if time.time() - entry.timestamp < self.ttl_seconds:
                    # Move to end (LRU)
                    self.l1_cache.move_to_end(cache_key)
                    entry.access_count += 1
                    entry.last_access = time.time()

                    if self.enable_stats:
                        self.stats.hits += 1
                        elapsed_ms = (time.time() - start_time) * 1000
                        self._hit_times.append(elapsed_ms)
                        if len(self._hit_times) > 100:
                            self._hit_times.pop(0)
                        self.stats.avg_hit_time_ms = np.mean(self._hit_times)

                    logger.debug(f"L1 cache hit for key: {cache_key[:16]}...")
                    return entry.embedding.copy()
                else:
                    # Expired entry, remove it
                    del self.l1_cache[cache_key]
                    logger.debug(f"L1 cache entry expired: {cache_key[:16]}...")

            # Check L2 cache if enabled
            if self.l2_cache_dir:
                embedding = self._get_from_l2(cache_key)
                if embedding is not None:
                    # Promote to L1
                    self._add_to_l1(cache_key, embedding, text)

                    if self.enable_stats:
                        self.stats.hits += 1
                        elapsed_ms = (time.time() - start_time) * 1000
                        self._hit_times.append(elapsed_ms)
                        if len(self._hit_times) > 100:
                            self._hit_times.pop(0)
                        self.stats.avg_hit_time_ms = np.mean(self._hit_times)

                    logger.debug(f"L2 cache hit for key: {cache_key[:16]}...")
                    return embedding.copy()

            # Cache miss
            if self.enable_stats:
                self.stats.misses += 1
                elapsed_ms = (time.time() - start_time) * 1000
                self._miss_times.append(elapsed_ms)
                if len(self._miss_times) > 100:
                    self._miss_times.pop(0)
                self.stats.avg_miss_time_ms = np.mean(self._miss_times)

            logger.debug(f"Cache miss for key: {cache_key[:16]}...")
            return None

    def store_embedding(
        self, text: str, model_name: str, embedding: np.ndarray
    ) -> None:
        """Store embedding in cache.

        Args:
            text: Text that was embedded
            model_name: Name of the model used for embedding
            embedding: Embedding vector to cache
        """
        cache_key = self._generate_key(text, model_name)

        with self._lock:
            # Add to L1 cache
            self._add_to_l1(cache_key, embedding, text)

            # Add to L2 cache if enabled
            if self.l2_cache_dir:
                self._add_to_l2(cache_key, embedding)

            logger.debug(f"Stored embedding for key: {cache_key[:16]}...")

    def _generate_key(self, text: str, model_name: str) -> str:
        """Generate cache key from text and model name.

        Args:
            text: Input text
            model_name: Model name

        Returns:
            Unique cache key
        """
        combined = f"{model_name}:{text}"
        return hashlib.sha256(combined.encode()).hexdigest()

    def _add_to_l1(self, cache_key: str, embedding: np.ndarray, text: str) -> None:
        """Add entry to L1 cache with LRU eviction.

        Args:
            cache_key: Cache key
            embedding: Embedding vector
            text: Original text (for hash verification)
        """
        # Check if we need to evict
        if len(self.l1_cache) >= self.max_size:
            # Remove least recently used item
            evicted_key = next(iter(self.l1_cache))
            del self.l1_cache[evicted_key]
            if self.enable_stats:
                self.stats.evictions += 1
            logger.debug(f"Evicted L1 entry: {evicted_key[:16]}...")

        # Add new entry
        text_hash = hashlib.md5(text.encode()).hexdigest()
        entry = CacheEntry(
            embedding=embedding.copy(),
            timestamp=time.time(),
            text_hash=text_hash,
        )
        self.l1_cache[cache_key] = entry

        if self.enable_stats:
            self.stats.l1_size = len(self.l1_cache)

    def _get_from_l2(self, cache_key: str) -> Optional[np.ndarray]:
        """Get embedding from L2 disk cache.

        Args:
            cache_key: Cache key

        Returns:
            Embedding array or None if not found/expired
        """
        if not self.l2_cache_dir:
            return None

        cache_file = self.l2_cache_dir / f"{cache_key}.pkl"
        if not cache_file.exists():
            return None

        try:
            with open(cache_file, "rb") as f:
                data = pickle.load(f)

            # Check TTL
            if time.time() - data["timestamp"] < self.ttl_seconds:
                return data["embedding"]
            else:
                # Expired, remove file
                cache_file.unlink()
                logger.debug(f"L2 cache entry expired: {cache_key[:16]}...")
                return None

        except Exception as e:
            logger.warning(f"Error reading L2 cache: {e}")
            return None

    def _add_to_l2(self, cache_key: str, embedding: np.ndarray) -> None:
        """Add embedding to L2 disk cache.

        Args:
            cache_key: Cache key
            embedding: Embedding vector
        """
        if not self.l2_cache_dir:
            return

        cache_file = self.l2_cache_dir / f"{cache_key}.pkl"

        try:
            data = {
                "embedding": embedding.copy(),
                "timestamp": time.time(),
            }
            with open(cache_file, "wb") as f:
                pickle.dump(data, f)

            if self.enable_stats:
                # Update L2 size (count files)
                self.stats.l2_size = len(list(self.l2_cache_dir.glob("*.pkl")))

        except Exception as e:
            logger.warning(f"Error writing L2 cache: {e}")

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self.l1_cache.clear()

            if self.l2_cache_dir:
                for cache_file in self.l2_cache_dir.glob("*.pkl"):
                    try:
                        cache_file.unlink()
                    except Exception as e:
                        logger.warning(f"Error clearing L2 cache file: {e}")

            if self.enable_stats:
                self.stats.l1_size = 0
                self.stats.l2_size = 0

            logger.info("Cache cleared")

    def get_statistics(self) -> CacheStatistics:
        """Get cache performance statistics.

        Returns:
            Current cache statistics
        """
        with self._lock:
            return self.stats

    def warm_up(
        self, texts: list[str], model_name: str, embeddings: np.ndarray
    ) -> None:
        """Pre-populate cache with embeddings.

        Args:
            texts: List of texts
            model_name: Model name used for embeddings
            embeddings: Array of embeddings corresponding to texts
        """
        for text, embedding in zip(texts, embeddings):
            self.store_embedding(text, model_name, embedding)

        logger.info(f"Cache warmed up with {len(texts)} entries")


# Global cache instance (singleton pattern)
_global_cache: Optional[EmbeddingCache] = None
_cache_lock = threading.Lock()


def get_embedding_cache(
    max_size: int = 10000,
    ttl_seconds: int = 3600,
    l2_cache_dir: Optional[str] = None,
) -> EmbeddingCache:
    """Get or create the global embedding cache instance.

    Args:
        max_size: Maximum number of entries in L1 cache
        ttl_seconds: Time-to-live for cache entries
        l2_cache_dir: Optional directory for L2 disk cache

    Returns:
        Global EmbeddingCache instance
    """
    global _global_cache

    if _global_cache is None:
        with _cache_lock:
            if _global_cache is None:
                _global_cache = EmbeddingCache(
                    max_size=max_size,
                    ttl_seconds=ttl_seconds,
                    l2_cache_dir=l2_cache_dir,
                )

    return _global_cache
