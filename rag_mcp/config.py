"""Configuration management for multi-collection RAG system.

This module provides configuration classes and loading functions that support
both single-collection (legacy) and multi-collection configurations while
maintaining backwards compatibility.

Now integrated with the hierarchical configuration manager for clear precedence
between CLI arguments, environment variables, file settings, and defaults.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class CollectionMetadata:
    """Metadata for a collection."""

    language: str = "en"
    last_updated: Optional[str] = None
    version: Optional[str] = None
    priority: int = 1
    custom: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CollectionMetadata:
        """Create metadata from dictionary."""
        return cls(
            language=data.get("language", "en"),
            last_updated=data.get("last_updated"),
            version=data.get("version"),
            priority=data.get("priority", 1),
            custom={
                k: v
                for k, v in data.items()
                if k not in ["language", "last_updated", "version", "priority"]
            },
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "language": self.language,
            "priority": self.priority,
        }
        if self.last_updated:
            result["last_updated"] = self.last_updated
        if self.version:
            result["version"] = self.version
        result.update(self.custom)
        return result


@dataclass
class CollectionSources:
    """Source configuration for a collection."""

    base_urls: List[str] = field(default_factory=list)
    allow_patterns: List[str] = field(default_factory=lambda: [".*"])
    deny_patterns: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CollectionSources:
        """Create sources from dictionary."""
        return cls(
            base_urls=data.get("base_urls", []),
            allow_patterns=data.get("allow_patterns", [".*"]),
            deny_patterns=data.get("deny_patterns", []),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "base_urls": self.base_urls,
            "allow_patterns": self.allow_patterns,
            "deny_patterns": self.deny_patterns,
        }


@dataclass
class CollectionConfig:
    """Configuration for a single collection."""

    # Collection identification
    id: str
    name: str
    description: str = ""
    domain: str = ""
    tags: List[str] = field(default_factory=list)

    # Source configuration
    sources: CollectionSources = field(default_factory=CollectionSources)

    # Processing configuration
    max_pages: int = 500
    concurrency: int = 8
    chunk_chars: int = 1200
    chunk_overlap: int = 200

    # Chroma settings
    chroma_persist_dir: str = "data/chroma"
    chroma_collection: Optional[str] = None  # If None, defaults to collection id

    # Embeddings
    embedding_provider: str = "sentence-transformers"
    embedding_model: str = "all-MiniLM-L6-v2"

    # Metadata
    metadata: CollectionMetadata = field(default_factory=CollectionMetadata)

    def __post_init__(self):
        """Initialize computed fields."""
        if self.chroma_collection is None:
            self.chroma_collection = self.id

    @classmethod
    def from_dict(cls, collection_id: str, data: Dict[str, Any]) -> CollectionConfig:
        """Create collection config from dictionary."""
        # Handle sources
        sources_data = data.get("sources", {})
        if isinstance(sources_data, dict):
            sources = CollectionSources.from_dict(sources_data)
        else:
            # Legacy format - sources at top level
            sources = CollectionSources(
                base_urls=data.get("base_urls", []),
                allow_patterns=data.get("allow_patterns", [".*"]),
                deny_patterns=data.get("deny_patterns", []),
            )

        # Handle metadata
        metadata_data = data.get("metadata", {})
        metadata = CollectionMetadata.from_dict(metadata_data)

        # Handle chroma settings (support both nested and flat formats)
        chroma_data = data.get("chroma", {})
        chroma_persist_dir = chroma_data.get(
            "persist_dir", data.get("chroma_persist_dir", "data/chroma")
        )
        chroma_collection = chroma_data.get("collection", data.get("chroma_collection"))

        return cls(
            id=collection_id,
            name=data.get("name", collection_id),
            description=data.get("description", ""),
            domain=data.get("domain", ""),
            tags=data.get("tags", []),
            sources=sources,
            max_pages=data.get("max_pages", 500),
            concurrency=data.get("concurrency", 8),
            chunk_chars=data.get("chunk_chars", 1200),
            chunk_overlap=data.get("chunk_overlap", 200),
            chroma_persist_dir=chroma_persist_dir,
            chroma_collection=chroma_collection,
            embedding_provider=data.get("embedding_provider", "sentence-transformers"),
            embedding_model=data.get("embedding_model", "all-MiniLM-L6-v2"),
            metadata=metadata,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "domain": self.domain,
            "tags": self.tags,
            "sources": self.sources.to_dict(),
            "max_pages": self.max_pages,
            "concurrency": self.concurrency,
            "chunk_chars": self.chunk_chars,
            "chunk_overlap": self.chunk_overlap,
            "chroma": {
                "persist_dir": self.chroma_persist_dir,
                "collection": self.chroma_collection,
            },
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "metadata": self.metadata.to_dict(),
        }


@dataclass
class GlobalDefaults:
    """Global default settings for collections."""

    chunk_chars: int = 1200
    chunk_overlap: int = 200
    embedding_provider: str = "sentence-transformers"
    embedding_model: str = "all-MiniLM-L6-v2"
    chroma_persist_dir: str = "data/chroma"
    max_pages: int = 500
    concurrency: int = 8

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GlobalDefaults:
        """Create defaults from dictionary."""
        return cls(
            chunk_chars=data.get("chunk_chars", 1200),
            chunk_overlap=data.get("chunk_overlap", 200),
            embedding_provider=data.get("embedding_provider", "sentence-transformers"),
            embedding_model=data.get("embedding_model", "all-MiniLM-L6-v2"),
            chroma_persist_dir=data.get("chroma_persist_dir", "data/chroma"),
            max_pages=data.get("max_pages", 500),
            concurrency=data.get("concurrency", 8),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "chunk_chars": self.chunk_chars,
            "chunk_overlap": self.chunk_overlap,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "chroma_persist_dir": self.chroma_persist_dir,
            "max_pages": self.max_pages,
            "concurrency": self.concurrency,
        }


@dataclass
class CollectionRegistry:
    """Registry configuration for collection discovery."""

    auto_discover: bool = False
    collection_dir: str = "./collections"
    collections: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CollectionRegistry:
        """Create registry from dictionary."""
        return cls(
            auto_discover=data.get("auto_discover", False),
            collection_dir=data.get("collection_dir", "./collections"),
            collections=data.get("collections", []),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "auto_discover": self.auto_discover,
            "collection_dir": self.collection_dir,
            "collections": self.collections,
        }


@dataclass
class MultiCollectionConfig:
    """Configuration for multiple collections."""

    version: str = "2.0"
    defaults: GlobalDefaults = field(default_factory=GlobalDefaults)
    collections: Dict[str, CollectionConfig] = field(default_factory=dict)
    registry: Optional[CollectionRegistry] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MultiCollectionConfig:
        """Create multi-collection config from dictionary."""
        # Handle defaults
        defaults_data = data.get("defaults", {})
        defaults = GlobalDefaults.from_dict(defaults_data)

        # Handle collections
        collections = {}
        collections_data = data.get("collections", {})

        for coll_id, coll_data in collections_data.items():
            # Apply defaults to collection data
            merged_data = defaults.to_dict()
            merged_data.update(coll_data)
            collections[coll_id] = CollectionConfig.from_dict(coll_id, merged_data)

        # Handle registry
        registry = None
        if "registry" in data:
            registry = CollectionRegistry.from_dict(data["registry"])

        return cls(
            version=data.get("version", "2.0"),
            defaults=defaults,
            collections=collections,
            registry=registry,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "version": self.version,
            "defaults": self.defaults.to_dict(),
            "collections": {
                coll_id: coll.to_dict() for coll_id, coll in self.collections.items()
            },
        }

        if self.registry:
            result["registry"] = self.registry.to_dict()

        return result

    def get_collection(self, collection_id: str) -> Optional[CollectionConfig]:
        """Get a specific collection by ID."""
        return self.collections.get(collection_id)

    def list_collection_ids(self) -> List[str]:
        """List all collection IDs."""
        return list(self.collections.keys())


class ConfigurationError(Exception):
    """Exception raised for configuration errors."""

    pass


def load_config(
    config_path: str, cli_args: dict = None, use_hierarchy: bool = True
) -> MultiCollectionConfig:
    """Load multi-collection configuration from file with hierarchical support.

    Args:
        config_path: Path to configuration file
        cli_args: Optional CLI arguments to override configuration
        use_hierarchy: Whether to use the hierarchical configuration system

    Returns:
        MultiCollectionConfig instance

    Raises:
        ConfigurationError: If configuration is invalid or file not found
    """
    if use_hierarchy:
        # Use the new hierarchical configuration system
        try:
            # Load configuration through the ConfigManager
            config_data = load_hierarchical_config(
                cli_args=cli_args,
                config_file=config_path,
                debug=os.environ.get("CONFIG_DEBUG", "").lower() == "true",
            )

            # Convert to MultiCollectionConfig
            return MultiCollectionConfig.from_dict(config_data)

        except Exception as e:
            logger.warning(
                f"Hierarchical config failed, falling back to direct load: {e}"
            )
            # Fall back to direct loading if hierarchical fails
            use_hierarchy = False

    if not use_hierarchy:
        # Original implementation for backward compatibility
        if not os.path.exists(config_path):
            raise ConfigurationError(f"Configuration file not found: {config_path}")

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not isinstance(data, dict):
                raise ConfigurationError(
                    f"Configuration file must contain a dictionary, got {type(data)}"
                )

            return MultiCollectionConfig.from_dict(data)

        except yaml.YAMLError as e:
            raise ConfigurationError(f"Failed to parse YAML configuration: {e}")
        except Exception as e:
            raise ConfigurationError(f"Failed to load configuration: {e}")


def load_multi_config(config_path: str, cli_args: dict = None) -> MultiCollectionConfig:
    """Load multi-collection configuration from file.

    This function is now identical to load_config() since we only support
    multi-collection format. Kept for backwards compatibility.

    Args:
        config_path: Path to configuration file
        cli_args: Optional CLI arguments to override configuration

    Returns:
        MultiCollectionConfig instance

    Raises:
        ConfigurationError: If configuration is invalid or file not found
    """
    return load_config(config_path, cli_args=cli_args)


def validate_collection_config(config: CollectionConfig) -> List[str]:
    """Validate a collection configuration and return list of errors."""
    errors = []

    if not config.id:
        errors.append("Collection ID is required")

    if not config.name:
        errors.append("Collection name is required")

    if not config.sources.base_urls:
        errors.append("At least one base URL is required")

    if config.max_pages <= 0:
        errors.append("max_pages must be positive")

    if config.concurrency <= 0:
        errors.append("concurrency must be positive")

    if config.chunk_chars <= 0:
        errors.append("chunk_chars must be positive")

    if config.chunk_overlap < 0:
        errors.append("chunk_overlap cannot be negative")

    if config.chunk_overlap >= config.chunk_chars:
        errors.append("chunk_overlap must be less than chunk_chars")

    if not config.embedding_provider:
        errors.append("embedding_provider is required")

    if not config.embedding_model:
        errors.append("embedding_model is required")

    return errors


def validate_multi_config(config: MultiCollectionConfig) -> List[str]:
    """Validate a multi-collection configuration and return list of errors."""
    errors = []

    if not config.collections:
        errors.append("At least one collection is required")

    # Validate each collection
    for coll_id, collection in config.collections.items():
        if collection.id != coll_id:
            errors.append(
                f"Collection ID mismatch: key '{coll_id}' vs config.id '{collection.id}'"
            )

        coll_errors = validate_collection_config(collection)
        for error in coll_errors:
            errors.append(f"Collection '{coll_id}': {error}")

    # Check for duplicate chroma collection names
    chroma_collections: Dict[str, str] = {}
    for coll_id, collection in config.collections.items():
        chroma_name = collection.chroma_collection or collection.id
        if chroma_name in chroma_collections:
            errors.append(
                f"Duplicate chroma collection name '{chroma_name}' "
                f"used by collections '{chroma_collections[chroma_name]}' and '{coll_id}'"
            )
        else:
            chroma_collections[chroma_name] = coll_id

    return errors
