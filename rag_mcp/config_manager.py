"""Hierarchical Configuration Management System.

This module provides centralized configuration management with clear precedence
between CLI arguments, environment variables, file settings, and defaults.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import yaml

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Exception raised for configuration errors."""

    pass


class ConfigSource(Enum):
    """Configuration source types with precedence order."""

    DEFAULTS = 0  # Lowest priority
    FILE = 1
    ENVIRONMENT = 2
    CLI = 3  # Highest priority


@dataclass
class ValidationResult:
    """Result of configuration validation."""

    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_error(self, error: str):
        """Add an error to the validation result."""
        self.errors.append(error)
        self.is_valid = False

    def add_warning(self, warning: str):
        """Add a warning to the validation result."""
        self.warnings.append(warning)


@dataclass
class ConfigDebugInfo:
    """Debug information for configuration sources."""

    source: ConfigSource
    path: Optional[str] = None
    values: Dict[str, Any] = field(default_factory=dict)
    applied_keys: Set[str] = field(default_factory=set)


class ConfigMerger:
    """Smart configuration merging with precedence and type preservation."""

    def __init__(self, preserve_types: bool = True, debug: bool = False):
        """Initialize the configuration merger.

        Args:
            preserve_types: Whether to preserve original data types during merge
            debug: Enable debug logging for merge operations
        """
        self.preserve_types = preserve_types
        self.debug = debug
        self.debug_info: List[ConfigDebugInfo] = []

    def merge(
        self, cli_config: dict, env_config: dict, file_config: dict, defaults: dict
    ) -> dict:
        """Merge configurations respecting precedence.

        Args:
            cli_config: Configuration from command-line arguments (highest priority)
            env_config: Configuration from environment variables
            file_config: Configuration from file
            defaults: Default configuration (lowest priority)

        Returns:
            Merged configuration dictionary
        """
        # Clear debug info for new merge
        self.debug_info = []

        # Start with defaults (lowest priority)
        merged = deepcopy(defaults)
        self._record_debug(ConfigSource.DEFAULTS, None, defaults, set(defaults.keys()))

        # Apply file configuration
        if file_config:
            applied_keys = self._deep_merge(merged, file_config)
            self._record_debug(
                ConfigSource.FILE, "config_file", file_config, applied_keys
            )
            if self.debug:
                logger.debug(
                    f"Applied {len(applied_keys)} keys from file configuration"
                )

        # Apply environment configuration
        if env_config:
            applied_keys = self._deep_merge(merged, env_config)
            self._record_debug(
                ConfigSource.ENVIRONMENT, "environment", env_config, applied_keys
            )
            if self.debug:
                logger.debug(
                    f"Applied {len(applied_keys)} keys from environment variables"
                )

        # Apply CLI configuration (highest priority)
        if cli_config:
            applied_keys = self._deep_merge(merged, cli_config)
            self._record_debug(ConfigSource.CLI, "cli_args", cli_config, applied_keys)
            if self.debug:
                logger.debug(f"Applied {len(applied_keys)} keys from CLI arguments")

        return merged

    def _deep_merge(self, base: dict, override: dict) -> Set[str]:
        """Deep merge dictionaries preserving types.

        Args:
            base: Base dictionary to merge into
            override: Dictionary with values to override

        Returns:
            Set of keys that were applied from override
        """
        applied_keys = set()

        for key, value in override.items():
            if value is None:
                # Skip None values to allow lower precedence values to show through
                continue

            if key in base:
                if isinstance(base[key], dict) and isinstance(value, dict):
                    # Recursively merge dictionaries
                    sub_keys = self._deep_merge(base[key], value)
                    if sub_keys:
                        applied_keys.add(key)
                elif isinstance(base[key], list) and isinstance(value, list):
                    # For lists, replace entirely (could be made configurable)
                    base[key] = self._preserve_type(base[key], value)
                    applied_keys.add(key)
                else:
                    # Replace scalar values, preserving type if needed
                    base[key] = self._preserve_type(base[key], value)
                    applied_keys.add(key)
            else:
                # New key, add it
                base[key] = deepcopy(value)
                applied_keys.add(key)

        return applied_keys

    def _preserve_type(self, original: Any, new_value: Any) -> Any:
        """Preserve the type of the original value if configured to do so.

        Args:
            original: Original value with desired type
            new_value: New value to convert

        Returns:
            New value with preserved type if possible
        """
        if not self.preserve_types:
            return new_value

        # If types match, no conversion needed
        if type(original) == type(new_value):
            return new_value

        # Try to convert to original type
        try:
            if isinstance(original, bool):
                # Special handling for booleans
                if isinstance(new_value, str):
                    return new_value.lower() in ("true", "yes", "1", "on")
                return bool(new_value)
            elif isinstance(original, int):
                return int(new_value)
            elif isinstance(original, float):
                return float(new_value)
            elif isinstance(original, str):
                return str(new_value)
            else:
                # For other types, just return the new value
                return new_value
        except (ValueError, TypeError):
            # If conversion fails, log warning and return original type
            if self.debug:
                logger.warning(
                    f"Could not convert {new_value} to type {type(original).__name__}, "
                    f"using original value"
                )
            return new_value

    def _record_debug(
        self,
        source: ConfigSource,
        path: Optional[str],
        values: dict,
        applied_keys: Set[str],
    ):
        """Record debug information about configuration sources."""
        self.debug_info.append(
            ConfigDebugInfo(
                source=source,
                path=path,
                values=deepcopy(values),
                applied_keys=applied_keys.copy(),
            )
        )

    def get_debug_info(self) -> List[ConfigDebugInfo]:
        """Get debug information about the last merge operation."""
        return self.debug_info


class ConfigManager:
    """Centralized configuration management with hierarchical precedence."""

    # System-wide defaults
    SYSTEM_DEFAULTS = {
        "version": "2.0",
        "defaults": {
            "chunk_chars": 1200,
            "chunk_overlap": 200,
            "embedding_provider": "sentence-transformers",
            "embedding_model": "all-MiniLM-L6-v2",
            "chroma_persist_dir": "data/chroma",
            "max_pages": 500,
            "concurrency": 8,
        },
        "logging": {
            "level": "INFO",
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "file": None,
        },
        "performance": {
            "cache_enabled": True,
            "cache_ttl": 3600,
            "batch_size": 32,
            "timeout": 30,
        },
        "paths": {
            "config_dir": "ingest",
            "data_dir": "data",
            "log_dir": "logs",
        },
        "mcp": {
            "enabled": True,
            "host": "localhost",
            "port": 5000,
        },
        "collections": {},
    }

    # Environment variable schema
    ENV_SCHEMA = {
        "MULTI_COLLECTION_CONFIG_PATH": {
            "type": "path",
            "config_key": "config_path",
            "required": False,
            "default": "ingest/multi-collection.yml",
        },
        "CHROMA_PERSIST_DIR": {
            "type": "path",
            "config_key": "defaults.chroma_persist_dir",
            "required": False,
            "default": "data/chroma",
            "create_if_missing": True,
        },
        "CHROMA_COLLECTION": {
            "type": "str",
            "config_key": "defaults.chroma_collection",
            "required": False,
        },
        "EMBEDDING_PROVIDER": {
            "type": "str",
            "config_key": "defaults.embedding_provider",
            "required": False,
            "choices": ["sentence-transformers", "openai", "huggingface"],
        },
        "EMBEDDING_MODEL": {
            "type": "str",
            "config_key": "defaults.embedding_model",
            "required": False,
        },
        "LOG_LEVEL": {
            "type": "str",
            "config_key": "logging.level",
            "required": False,
            "default": "INFO",
            "choices": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        },
        "MAX_PAGES": {
            "type": "int",
            "config_key": "defaults.max_pages",
            "required": False,
            "default": 500,
        },
        "CONCURRENCY": {
            "type": "int",
            "config_key": "defaults.concurrency",
            "required": False,
            "default": 8,
        },
    }

    def __init__(self, debug: bool = False):
        """Initialize the configuration manager.

        Args:
            debug: Enable debug mode for detailed logging
        """
        self.merger = ConfigMerger(preserve_types=True, debug=debug)
        self.defaults = deepcopy(self.SYSTEM_DEFAULTS)
        self._config = {}
        self._lock = threading.RLock()
        self.debug = debug
        self.validation_result = ValidationResult(is_valid=True)

    def load_configuration(
        self,
        cli_config: dict = None,
        env_config: dict = None,
        file_config: dict = None,
        validate: bool = True,
    ) -> dict:
        """Load and merge configurations with precedence.

        Args:
            cli_config: Configuration from CLI arguments
            env_config: Configuration from environment variables
            file_config: Configuration from file
            validate: Whether to validate the final configuration

        Returns:
            Final merged configuration

        Raises:
            ConfigurationError: If configuration is invalid
        """
        with self._lock:
            # Load environment variables if not provided
            if env_config is None:
                env_config = self._load_environment_config()

            # Merge configurations
            self._config = self.merger.merge(
                cli_config or {}, env_config or {}, file_config or {}, self.defaults
            )

            # Validate if requested
            if validate:
                self.validation_result = self.validate_configuration(self._config)
                if not self.validation_result.is_valid:
                    raise ConfigurationError(
                        f"Configuration validation failed:\n"
                        + "\n".join(self.validation_result.errors)
                    )

            return deepcopy(self._config)

    def _load_environment_config(self) -> dict:
        """Load configuration from environment variables.

        Returns:
            Configuration dictionary from environment variables
        """
        env_config = {}

        for env_var, schema in self.ENV_SCHEMA.items():
            value = os.environ.get(env_var)

            if value is not None:
                # Validate and convert value
                try:
                    converted_value = self._convert_env_value(value, schema)

                    # Apply to configuration using the config_key path
                    config_key = schema.get("config_key", env_var.lower())
                    self._set_nested_value(env_config, config_key, converted_value)

                    if self.debug:
                        logger.debug(
                            f"Loaded {env_var}={value} -> {config_key}={converted_value}"
                        )

                except ValueError as e:
                    logger.warning(f"Invalid environment variable {env_var}: {e}")

        return env_config

    def _convert_env_value(self, value: str, schema: dict) -> Any:
        """Convert environment variable value according to schema.

        Args:
            value: String value from environment
            schema: Schema definition for the variable

        Returns:
            Converted value

        Raises:
            ValueError: If value cannot be converted or is invalid
        """
        var_type = schema.get("type", "str")

        # Check choices if specified
        if "choices" in schema and value not in schema["choices"]:
            raise ValueError(
                f"Value '{value}' not in allowed choices: {schema['choices']}"
            )

        # Convert based on type
        if var_type == "str":
            return value
        elif var_type == "int":
            return int(value)
        elif var_type == "float":
            return float(value)
        elif var_type == "bool":
            return value.lower() in ("true", "yes", "1", "on")
        elif var_type == "path":
            path = Path(value)
            if schema.get("create_if_missing") and not path.exists():
                path.mkdir(parents=True, exist_ok=True)
            return str(path)
        else:
            return value

    def _set_nested_value(self, config: dict, key_path: str, value: Any):
        """Set a value in a nested dictionary using dot notation.

        Args:
            config: Configuration dictionary
            key_path: Dot-separated path to the key
            value: Value to set
        """
        keys = key_path.split(".")
        current = config

        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]

        current[keys[-1]] = value

    def get_effective_config(self) -> dict:
        """Get the current effective configuration.

        Returns:
            Copy of the current configuration
        """
        with self._lock:
            return deepcopy(self._config)

    def validate_configuration(self, config: dict) -> ValidationResult:
        """Validate the final configuration.

        Args:
            config: Configuration to validate

        Returns:
            ValidationResult with any errors or warnings
        """
        result = ValidationResult(is_valid=True)

        # Check required fields
        if "version" not in config:
            result.add_warning("No version specified in configuration")

        # Validate collections if present
        if "collections" in config and config["collections"]:
            for coll_id, coll_config in config["collections"].items():
                self._validate_collection(coll_id, coll_config, result)

        # Validate numeric ranges
        defaults = config.get("defaults", {})
        if defaults.get("chunk_chars", 0) <= 0:
            result.add_error("chunk_chars must be positive")
        if defaults.get("chunk_overlap", 0) < 0:
            result.add_error("chunk_overlap cannot be negative")
        if defaults.get("max_pages", 0) <= 0:
            result.add_error("max_pages must be positive")
        if defaults.get("concurrency", 0) <= 0:
            result.add_error("concurrency must be positive")

        # Check overlap vs chunk size
        chunk_chars = defaults.get("chunk_chars", 1200)
        chunk_overlap = defaults.get("chunk_overlap", 200)
        if chunk_overlap >= chunk_chars:
            result.add_error(
                f"chunk_overlap ({chunk_overlap}) must be less than chunk_chars ({chunk_chars})"
            )

        return result

    def _validate_collection(
        self, coll_id: str, collection: dict, result: ValidationResult
    ):
        """Validate a collection configuration.

        Args:
            coll_id: Collection ID
            collection: Collection configuration
            result: ValidationResult to add errors/warnings to
        """
        # Check required fields
        if not collection.get("name"):
            result.add_error(f"Collection '{coll_id}': name is required")

        # Check sources
        sources = collection.get("sources", {})
        if not sources.get("base_urls"):
            result.add_error(
                f"Collection '{coll_id}': at least one base URL is required"
            )

        # Validate numeric fields
        if collection.get("max_pages", 1) <= 0:
            result.add_error(f"Collection '{coll_id}': max_pages must be positive")
        if collection.get("concurrency", 1) <= 0:
            result.add_error(f"Collection '{coll_id}': concurrency must be positive")

    def get_config_sources(self) -> Dict[str, List[str]]:
        """Get information about which source each configuration value came from.

        Returns:
            Dictionary mapping configuration keys to their sources
        """
        sources = {}

        for debug_info in self.merger.get_debug_info():
            for key in debug_info.applied_keys:
                if key not in sources:
                    sources[key] = []
                sources[key].append(debug_info.source.name)

        return sources

    def print_config_debug(self):
        """Print debug information about configuration sources."""
        print("\n" + "=" * 60)
        print("Configuration Debug Information")
        print("=" * 60)

        for debug_info in self.merger.get_debug_info():
            print(f"\n📍 Source: {debug_info.source.name}")
            if debug_info.path:
                print(f"   Path: {debug_info.path}")
            print(f"   Applied {len(debug_info.applied_keys)} keys:")
            for key in sorted(debug_info.applied_keys):
                print(f"     • {key}")

        print("\n" + "-" * 60)
        print("Final Configuration Sources:")
        print("-" * 60)

        sources = self.get_config_sources()
        for key in sorted(sources.keys()):
            source_list = sources[key]
            print(f"  {key}: {' -> '.join(source_list)}")

        print("=" * 60 + "\n")

    def export_config(self, format: str = "yaml") -> str:
        """Export the current configuration as a string.

        Args:
            format: Export format ('yaml' or 'json')

        Returns:
            Configuration as a string in the specified format
        """
        config = self.get_effective_config()

        if format == "json":
            return json.dumps(config, indent=2, default=str)
        elif format == "yaml":
            return yaml.dump(config, default_flow_style=False, sort_keys=False)
        else:
            raise ValueError(f"Unsupported format: {format}")

    def _load_defaults(self) -> dict:
        """Load system defaults.

        Returns:
            System default configuration
        """
        return deepcopy(self.SYSTEM_DEFAULTS)


# Global instance for convenience
_global_config_manager: Optional[ConfigManager] = None


def get_config_manager(debug: bool = False) -> ConfigManager:
    """Get or create the global configuration manager instance.

    Args:
        debug: Enable debug mode

    Returns:
        Global ConfigManager instance
    """
    global _global_config_manager

    if _global_config_manager is None:
        _global_config_manager = ConfigManager(debug=debug)

    return _global_config_manager


def load_hierarchical_config(
    cli_args: dict = None, config_file: str = None, debug: bool = False
) -> dict:
    """Convenience function to load configuration with hierarchy.

    Args:
        cli_args: Command-line arguments as dictionary
        config_file: Path to configuration file
        debug: Enable debug mode

    Returns:
        Final merged configuration
    """
    manager = get_config_manager(debug=debug)

    # Load file configuration if provided
    file_config = None
    if config_file and os.path.exists(config_file):
        with open(config_file, "r") as f:
            if config_file.endswith(".json"):
                file_config = json.load(f)
            else:
                file_config = yaml.safe_load(f)

    # Load and return configuration
    config = manager.load_configuration(cli_config=cli_args, file_config=file_config)

    if debug:
        manager.print_config_debug()

    return config
