from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .chroma_store import build_embedding_function, get_client, get_or_create_collection
from .collection_selector import create_selector
from .config import (
    CollectionConfig,
    ConfigurationError,
    MultiCollectionConfig,
    load_multi_config,
)
from .config_manager import get_config_manager
from .ingest import crawl, ingest_into_chroma
from .server import CollectionInstance

logger = logging.getLogger(__name__)


class CLIErrorHandler:
    """Consistent error handling for CLI with structured error codes."""

    ERROR_CODES = {
        "CONFIG_NOT_FOUND": 10,
        "CONFIG_INVALID": 11,
        "COLLECTION_NOT_FOUND": 20,
        "COLLECTION_EXISTS": 21,
        "INGESTION_FAILED": 30,
        "NETWORK_ERROR": 40,
        "DISK_SPACE_ERROR": 50,
        "MODEL_LOADING_ERROR": 60,
        "PERMISSION_ERROR": 70,
        "UNKNOWN_ERROR": 99,
    }

    def handle_error(
        self,
        error_type: str,
        message: str,
        context: dict = None,
        exception: Exception = None,
    ) -> int:
        """Handle errors with consistent formatting and return appropriate error code."""
        error_code = self.ERROR_CODES.get(error_type, 1)

        # Format error message
        error_msg = f"\n❌ Error [{error_type}]: {message}"

        # Add exception details if available
        if exception:
            error_msg += f"\n   Details: {str(exception)}"

        # Add context if provided
        if context:
            error_msg += f"\n📋 Context:"
            for key, value in context.items():
                error_msg += f"\n   • {key}: {value}"

        # Get and add suggestion
        suggestion = self._get_suggestion(error_type, context)
        if suggestion:
            error_msg += f"\n💡 Suggestion: {suggestion}"

        print(error_msg, file=sys.stderr)
        return error_code

    def _get_suggestion(self, error_type: str, context: dict = None) -> Optional[str]:
        """Get helpful suggestion based on error type."""
        suggestions = {
            "CONFIG_NOT_FOUND": (
                "Check that the configuration file exists at the specified path. "
                "Default location: ingest/multi-collection.yml"
            ),
            "CONFIG_INVALID": (
                "Verify the YAML syntax and structure. "
                "Use 'rag_mcp collection validate' to check configuration."
            ),
            "COLLECTION_NOT_FOUND": (
                "Use 'rag_mcp collection list' to see available collections. "
                "Check the collection ID spelling."
            ),
            "COLLECTION_EXISTS": (
                "Collection already exists. Use --force to overwrite or choose a different ID."
            ),
            "INGESTION_FAILED": (
                "Check network connectivity and source URLs. "
                "Try with --resume flag to continue from last checkpoint."
            ),
            "NETWORK_ERROR": (
                "Verify internet connection and firewall settings. "
                "Consider using --retry flag or adjusting timeout settings."
            ),
            "DISK_SPACE_ERROR": (
                "Free up disk space or specify a different storage location. "
                "Current usage can be checked with 'df -h'."
            ),
            "MODEL_LOADING_ERROR": (
                "Clear model cache with 'rm -rf ~/.cache/huggingface' and retry. "
                "Ensure you have enough memory for the model."
            ),
            "PERMISSION_ERROR": (
                "Check file/directory permissions. "
                "You may need to run with appropriate permissions or change ownership."
            ),
        }

        base_suggestion = suggestions.get(
            error_type, "Check the error details and try again."
        )

        # Add context-specific suggestions
        if context:
            if (
                error_type == "COLLECTION_NOT_FOUND"
                and "available_collections" in context
            ):
                collections = context["available_collections"]
                if collections:
                    base_suggestion += (
                        f"\nAvailable collections: {', '.join(collections[:5])}"
                    )
                    if len(collections) > 5:
                        base_suggestion += f" (and {len(collections) - 5} more)"

            if "config_path" in context:
                base_suggestion += f"\nConfig file: {context['config_path']}"

        return base_suggestion


class CLICompatibility:
    """Maintain backward compatibility for deprecated commands."""

    LEGACY_COMMANDS = {
        "ingest-multi": "ingest --all",
        "ingest-collection": "ingest --collection",
    }

    @classmethod
    def check_and_warn_deprecated(cls, command: str) -> bool:
        """Check if command is deprecated and warn user."""
        if command in cls.LEGACY_COMMANDS:
            new_command = cls.LEGACY_COMMANDS[command]
            logger.warning(
                f"Command '{command}' is deprecated and will be removed in a future version. "
                f"Please use '{new_command}' instead."
            )
            print(
                f"\n⚠️  Warning: '{command}' is deprecated.\n"
                f"   Please use 'rag_mcp {new_command}' instead.\n",
                file=sys.stderr,
            )
            return True
        return False

    @classmethod
    def transform_args(cls, args: argparse.Namespace) -> argparse.Namespace:
        """Transform legacy command arguments to new structure."""
        if args.command == "ingest-multi":
            args.command = "ingest"
            args.all = True
            args.collection = None
            args.fail_fast = False
        elif args.command == "ingest-collection":
            args.command = "ingest"
            args.all = False
            if hasattr(args, "collection") and args.collection:
                args.collection = [args.collection]
            else:
                raise ValueError("--collection is required for ingest-collection")
            args.fail_fast = False

        return args


class ProgressIndicator:
    """Simple progress indicator for CLI operations."""

    def __init__(self, total: int = None, description: str = "Processing"):
        self.total = total
        self.current = 0
        self.description = description
        self.start_time = time.time()
        self.last_update = 0

    def update(self, current: int = None, increment: int = 1, status: str = None):
        """Update progress indicator."""
        if current is not None:
            self.current = current
        else:
            self.current += increment

        # Update at most once per second to avoid spam
        now = time.time()
        if now - self.last_update < 1.0 and self.current < self.total:
            return

        self.last_update = now
        elapsed = now - self.start_time

        if self.total:
            percentage = (self.current / self.total) * 100
            remaining = (self.total - self.current) * (elapsed / max(self.current, 1))

            status_text = (
                f"{self.description}: {self.current}/{self.total} ({percentage:.1f}%)"
            )
            if remaining > 0 and self.current > 0:
                if remaining > 3600:
                    eta = f"{remaining/3600:.1f}h"
                elif remaining > 60:
                    eta = f"{remaining/60:.1f}m"
                else:
                    eta = f"{remaining:.0f}s"
                status_text += f" - ETA: {eta}"
        else:
            status_text = f"{self.description}: {self.current} items"

        if status:
            status_text += f" - {status}"

        # Use carriage return to overwrite the line
        print(f"\r{status_text}", end="", flush=True)

    def finish(self, message: str = None):
        """Complete the progress indicator."""
        elapsed = time.time() - self.start_time
        if message:
            print(f"\r{message} (took {elapsed:.1f}s)")
        else:
            print(f"\r{self.description}: Complete! (took {elapsed:.1f}s)")


# Initialize error handler
error_handler = CLIErrorHandler()


class BaseCommand:
    """Base class for CLI commands."""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.error_handler = error_handler

    def execute(self) -> int:
        """Execute the command. Returns exit code (0 for success)."""
        raise NotImplementedError


class IngestCommand(BaseCommand):
    """Unified ingestion command handler."""

    def execute(self) -> int:
        """Execute the ingestion command."""
        try:
            # Load configuration
            config = self._load_config(self.args.config)

            # Determine collections to process
            collections_to_process = self._get_collections_to_process(config)

            if not collections_to_process:
                print("ℹ️  No collections to process.")
                return 0

            print(
                f"\n📦 Processing {len(collections_to_process)} collection(s): "
                f"{', '.join(collections_to_process)}\n"
            )

            # Create progress indicator for multi-collection processing
            progress = ProgressIndicator(
                total=len(collections_to_process), description="Ingesting collections"
            )

            # Process collections
            failed_collections = []
            successful_collections = []

            for i, collection_id in enumerate(collections_to_process):
                progress.update(current=i, status=f"Processing {collection_id}")

                if collection_id not in config.collections:
                    available = list(config.collections.keys())
                    error_code = self.error_handler.handle_error(
                        "COLLECTION_NOT_FOUND",
                        f"Collection '{collection_id}' not found in configuration",
                        context={
                            "requested_collection": collection_id,
                            "available_collections": available,
                            "config_path": self.args.config,
                        },
                    )
                    if self.args.fail_fast:
                        progress.finish(f"❌ Failed at collection {collection_id}")
                        return error_code
                    failed_collections.append(collection_id)
                    continue

                success = self._ingest_collection(config, collection_id, progress)
                if success:
                    successful_collections.append(collection_id)
                else:
                    failed_collections.append(collection_id)
                    if self.args.fail_fast:
                        progress.finish(f"❌ Failed at collection {collection_id}")
                        return self.error_handler.ERROR_CODES["INGESTION_FAILED"]

            # Finish progress and report results
            progress.finish()

            print(f"\n📊 Ingestion Summary:")
            print(f"   ✅ Successful: {len(successful_collections)} collection(s)")
            if successful_collections:
                for coll in successful_collections:
                    print(f"      • {coll}")

            if failed_collections:
                print(f"   ❌ Failed: {len(failed_collections)} collection(s)")
                for coll in failed_collections:
                    print(f"      • {coll}")
                return self.error_handler.ERROR_CODES["INGESTION_FAILED"]

            print(f"\n✨ All collections processed successfully!")
            return 0

        except ConfigurationError as e:
            return self.error_handler.handle_error(
                "CONFIG_INVALID",
                str(e),
                context={"config_path": self.args.config},
                exception=e,
            )
        except FileNotFoundError as e:
            return self.error_handler.handle_error(
                "CONFIG_NOT_FOUND",
                f"Configuration file not found: {self.args.config}",
                context={"config_path": self.args.config},
                exception=e,
            )
        except PermissionError as e:
            return self.error_handler.handle_error(
                "PERMISSION_ERROR",
                f"Permission denied accessing configuration",
                context={"config_path": self.args.config},
                exception=e,
            )
        except Exception as e:
            return self.error_handler.handle_error(
                "UNKNOWN_ERROR", "Unexpected error during ingestion", exception=e
            )

    def _load_config(self, config_path: str) -> MultiCollectionConfig:
        """Load the configuration file with hierarchical support."""
        try:
            # Check if file exists
            if not Path(config_path).exists():
                raise FileNotFoundError(f"Configuration file not found: {config_path}")

            # Extract CLI configuration overrides
            cli_config = self._extract_cli_config()

            # Use hierarchical configuration if environment variable is set
            use_hierarchy = (
                os.environ.get("USE_HIERARCHICAL_CONFIG", "true").lower() != "false"
            )

            if use_hierarchy and cli_config:
                logger.debug(f"Loading config with CLI overrides: {cli_config}")

            return load_multi_config(config_path, cli_args=cli_config)
        except FileNotFoundError:
            raise
        except PermissionError:
            raise
        except Exception as e:
            raise ConfigurationError(f"Failed to load config from {config_path}: {e}")

    def _extract_cli_config(self) -> dict:
        """Extract configuration overrides from CLI arguments."""
        cli_config = {}

        # Extract common CLI arguments that should override config
        if hasattr(self.args, "max_pages") and self.args.max_pages is not None:
            cli_config.setdefault("defaults", {})["max_pages"] = self.args.max_pages

        if hasattr(self.args, "concurrency") and self.args.concurrency is not None:
            cli_config.setdefault("defaults", {})["concurrency"] = self.args.concurrency

        if hasattr(self.args, "chunk_chars") and self.args.chunk_chars is not None:
            cli_config.setdefault("defaults", {})["chunk_chars"] = self.args.chunk_chars

        if hasattr(self.args, "chunk_overlap") and self.args.chunk_overlap is not None:
            cli_config.setdefault("defaults", {})[
                "chunk_overlap"
            ] = self.args.chunk_overlap

        return cli_config

    def _get_collections_to_process(self, config: MultiCollectionConfig) -> List[str]:
        """Determine which collections to process based on command arguments."""
        if self.args.collection:
            # Parse collection IDs (support comma-separated list)
            collection_ids = []
            for item in self.args.collection:
                collection_ids.extend([c.strip() for c in item.split(",")])
            return collection_ids
        else:
            # Default: process all collections
            return list(config.collections.keys())

    def _ingest_collection(
        self,
        config: MultiCollectionConfig,
        collection_id: str,
        progress: ProgressIndicator = None,
    ) -> bool:
        """Ingest a single collection. Returns True on success."""
        try:
            collection_config = config.collections[collection_id]
            print(
                f"\n🔄 Ingesting collection: {collection_config.name} (ID: {collection_id})"
            )

            # Crawl pages with progress updates
            print(f"   📡 Crawling {collection_config.domain}...")
            start_time = time.time()
            pages = asyncio.run(crawl(collection_config))
            crawl_time = time.time() - start_time
            print(f"   ✅ Crawled {len(pages)} pages in {crawl_time:.1f}s")

            # Ingest into Chroma with progress
            print(f"   💾 Storing in Chroma database...")
            ingest_start = time.time()
            ingest_into_chroma(pages, collection_config)
            ingest_time = time.time() - ingest_start

            print(
                f"   ✅ Successfully ingested {len(pages)} pages in {ingest_time:.1f}s"
            )
            return True

        except asyncio.TimeoutError as e:
            self.error_handler.handle_error(
                "NETWORK_ERROR",
                f"Timeout while crawling collection '{collection_id}'",
                context={
                    "collection_id": collection_id,
                    "domain": collection_config.domain,
                },
                exception=e,
            )
            return False
        except PermissionError as e:
            self.error_handler.handle_error(
                "PERMISSION_ERROR",
                f"Permission denied for collection '{collection_id}'",
                context={
                    "collection_id": collection_id,
                    "persist_dir": collection_config.chroma_persist_dir,
                },
                exception=e,
            )
            return False
        except OSError as e:
            if "No space left" in str(e):
                self.error_handler.handle_error(
                    "DISK_SPACE_ERROR",
                    f"Insufficient disk space for collection '{collection_id}'",
                    context={
                        "collection_id": collection_id,
                        "persist_dir": collection_config.chroma_persist_dir,
                    },
                    exception=e,
                )
            else:
                self.error_handler.handle_error(
                    "INGESTION_FAILED",
                    f"OS error for collection '{collection_id}'",
                    exception=e,
                )
            return False
        except Exception as e:
            self.error_handler.handle_error(
                "INGESTION_FAILED",
                f"Failed to ingest collection '{collection_id}'",
                context={"collection_id": collection_id},
                exception=e,
            )
            return False


class CollectionCommand(BaseCommand):
    """Collection management command handler."""

    def execute(self) -> int:
        """Execute the collection command."""
        subcommand = self.args.collection_cmd

        try:
            if subcommand == "list":
                return self._list_collections()
            elif subcommand == "info":
                return self._show_collection_info()
            elif subcommand == "validate":
                return self._validate_collection()
            elif subcommand == "stats":
                return self._show_collection_stats()
            else:
                print(f"Unknown collection subcommand: {subcommand}")
                return 1

        except ConfigurationError as e:
            print(f"Configuration error: {e}")
            return 1
        except Exception as e:
            print(f"Collection command failed: {e}")
            return 1

    def _list_collections(self) -> int:
        """List all available collections."""
        config = load_multi_config(self.args.config)

        print(f"Available collections ({len(config.collections)}):")
        print("-" * 60)

        for collection_id, collection_config in config.collections.items():
            status = self._get_collection_status(collection_config)
            print(f"  {collection_id}:")
            print(f"    Name: {collection_config.name}")
            print(f"    Description: {collection_config.description}")
            print(f"    Domain: {collection_config.domain}")
            print(f"    Tags: {', '.join(collection_config.tags)}")
            print(f"    Status: {status}")
            print(f"    Language: {collection_config.metadata.language}")
            print()

        return 0

    def _show_collection_info(self) -> int:
        """Show detailed information about a specific collection."""
        config = load_multi_config(self.args.config)
        collection_id = self.args.collection_id

        if collection_id not in config.collections:
            available = list(config.collections.keys())
            return self.error_handler.handle_error(
                "COLLECTION_NOT_FOUND",
                f"Collection '{collection_id}' not found",
                context={
                    "requested_collection": collection_id,
                    "available_collections": available,
                    "config_path": self.args.config,
                },
            )

        collection_config = config.collections[collection_id]
        status = self._get_collection_status(collection_config)
        status_icon = "✅" if status == "Ingested" else "⭕"

        print(f"\n📋 Collection Details: {collection_id}")
        print("=" * 60)
        print(f"Status: {status_icon} {status}")
        print(f"Name: {collection_config.name}")
        print(f"Description: {collection_config.description}")
        print(f"Domain: {collection_config.domain}")
        print(f"Tags: {', '.join(collection_config.tags)}")
        print(f"\n🌐 Sources:")
        print(f"  Base URLs:")
        for url in collection_config.sources.base_urls:
            print(f"    • {url}")
        if collection_config.sources.allow_patterns:
            print(f"  Allow patterns: {collection_config.sources.allow_patterns}")
        if collection_config.sources.deny_patterns:
            print(f"  Deny patterns: {collection_config.sources.deny_patterns}")
        print(f"\n⚙️  Configuration:")
        print(f"  Max pages: {collection_config.max_pages}")
        print(f"  Concurrency: {collection_config.concurrency}")
        print(f"  Chunk size: {collection_config.chunk_chars}")
        print(f"  Chunk overlap: {collection_config.chunk_overlap}")
        print(f"\n🔤 Embeddings:")
        print(f"  Provider: {collection_config.embedding_provider}")
        print(f"  Model: {collection_config.embedding_model}")
        print(f"\n💾 Storage:")
        print(f"  Chroma persist dir: {collection_config.chroma_persist_dir}")
        print(f"  Chroma collection: {collection_config.chroma_collection}")
        print(f"\n📊 Metadata:")
        print(f"  Language: {collection_config.metadata.language}")
        print(f"  Priority: {collection_config.metadata.priority}")
        if collection_config.metadata.version:
            print(f"  Version: {collection_config.metadata.version}")
        if collection_config.metadata.last_updated:
            print(f"  Last updated: {collection_config.metadata.last_updated}")

        return 0

    def _validate_collection(self) -> int:
        """Validate a collection configuration."""
        config = load_multi_config(self.args.config)
        collection_id = self.args.collection_id

        if collection_id not in config.collections:
            available = list(config.collections.keys())
            return self.error_handler.handle_error(
                "COLLECTION_NOT_FOUND",
                f"Collection '{collection_id}' not found",
                context={
                    "requested_collection": collection_id,
                    "available_collections": available,
                    "config_path": self.args.config,
                },
            )

        collection_config = config.collections[collection_id]
        issues = []
        warnings = []

        print(f"\n🔍 Validating collection: {collection_id}")
        print("=" * 60)

        # Validate sources
        if not collection_config.sources.base_urls:
            issues.append("❌ No base URLs configured")
        else:
            print(
                f"✅ Base URLs: {len(collection_config.sources.base_urls)} configured"
            )

        # Validate storage
        persist_dir = Path(collection_config.chroma_persist_dir)
        if not persist_dir.exists():
            warnings.append(
                f"⚠️  Chroma persist directory does not exist yet: {persist_dir}"
            )
        else:
            print(f"✅ Storage directory exists: {persist_dir}")

        # Validate embedding settings
        if collection_config.embedding_provider == "openai":
            if not os.environ.get("OPENAI_API_KEY"):
                issues.append(
                    "❌ OpenAI embedding provider requires OPENAI_API_KEY environment variable"
                )
            else:
                print("✅ OpenAI API key configured")
        else:
            print(f"✅ Embedding provider: {collection_config.embedding_provider}")

        # Check for required fields
        if not collection_config.name:
            issues.append("❌ Collection name is required")
        else:
            print(f"✅ Collection name: {collection_config.name}")

        if not collection_config.domain:
            issues.append("❌ Domain is required")
        else:
            print(f"✅ Domain: {collection_config.domain}")

        # Display warnings
        if warnings:
            print("\n⚠️  Warnings:")
            for warning in warnings:
                print(f"  {warning}")

        # Report results
        if issues:
            print(f"\n❌ Validation failed for collection '{collection_id}':")
            for issue in issues:
                print(f"  {issue}")
            return self.error_handler.ERROR_CODES["CONFIG_INVALID"]
        else:
            print(f"\n✅ Collection '{collection_id}' configuration is valid!")
            return 0

    def _show_collection_stats(self) -> int:
        """Show statistics for a collection."""
        config = load_multi_config(self.args.config)
        collection_id = self.args.collection_id

        if collection_id not in config.collections:
            available = list(config.collections.keys())
            return self.error_handler.handle_error(
                "COLLECTION_NOT_FOUND",
                f"Collection '{collection_id}' not found",
                context={
                    "requested_collection": collection_id,
                    "available_collections": available,
                    "config_path": self.args.config,
                },
            )

        collection_config = config.collections[collection_id]

        try:
            # Get Chroma client and collection
            client = get_client(collection_config.chroma_persist_dir)

            # Check if collection exists
            try:
                chroma_collection = client.get_collection(
                    name=collection_config.chroma_collection or collection_id
                )

                # Get collection stats
                count = chroma_collection.count()

                print(f"\n📊 Statistics for collection '{collection_id}':")
                print("=" * 60)
                print(f"📚 Documents in index: {count}")
                print(
                    f"🗄️  Chroma collection: {collection_config.chroma_collection or collection_id}"
                )
                print(f"💾 Persist directory: {collection_config.chroma_persist_dir}")

                # Calculate storage size if possible
                persist_dir = Path(collection_config.chroma_persist_dir)
                if persist_dir.exists():
                    size_mb = sum(
                        f.stat().st_size for f in persist_dir.rglob("*") if f.is_file()
                    ) / (1024 * 1024)
                    print(f"💿 Storage size: {size_mb:.2f} MB")

                # Sample a few documents if available
                if count > 0:
                    sample = chroma_collection.peek(limit=3)
                    print(f"\n📄 Sample documents:")
                    for i, (doc_id, metadata) in enumerate(
                        zip(sample.get("ids", []), sample.get("metadatas", []))
                    ):
                        print(f"  {i+1}. ID: {doc_id[:50]}...")
                        if metadata:
                            print(f"     🌐 URL: {metadata.get('url', 'N/A')}")
                            print(
                                f"     📝 Title: {metadata.get('title', 'N/A')[:60]}..."
                            )
                else:
                    print("\n⚠️  No documents in collection yet")

            except Exception as e:
                print(f"\n⚠️  Collection '{collection_id}' has not been ingested yet")
                print(
                    f"   Use 'rag_mcp ingest --collection {collection_id}' to populate it"
                )
                return self.error_handler.ERROR_CODES["COLLECTION_NOT_FOUND"]

        except PermissionError as e:
            return self.error_handler.handle_error(
                "PERMISSION_ERROR",
                f"Permission denied accessing collection data",
                context={
                    "collection_id": collection_id,
                    "persist_dir": collection_config.chroma_persist_dir,
                },
                exception=e,
            )
        except Exception as e:
            return self.error_handler.handle_error(
                "UNKNOWN_ERROR",
                f"Failed to get statistics for collection '{collection_id}'",
                exception=e,
            )

        return 0

    def _get_collection_status(self, collection_config: CollectionConfig) -> str:
        """Get the status of a collection (ingested/not ingested)."""
        try:
            client = get_client(collection_config.chroma_persist_dir)
            client.get_collection(name=collection_config.chroma_collection)
            return "Ingested"
        except Exception:
            return "Not ingested"


class SearchCommand(BaseCommand):
    """Search command handler."""

    def execute(self) -> int:
        """Execute the search command."""
        try:
            config = load_multi_config(self.args.config)

            print(f"\n🔍 Searching for: '{self.args.query}'")

            # Determine target collection
            if self.args.collection:
                # Search specific collection
                if self.args.collection not in config.collections:
                    available = list(config.collections.keys())
                    return self.error_handler.handle_error(
                        "COLLECTION_NOT_FOUND",
                        f"Collection '{self.args.collection}' not found",
                        context={
                            "requested_collection": self.args.collection,
                            "available_collections": available,
                            "config_path": self.args.config,
                        },
                    )

                print(f"   📚 Target collection: {self.args.collection}")
                results = self._search_collection(
                    config.collections[self.args.collection],
                    self.args.query,
                    self.args.limit,
                )
            else:
                # Search across all collections using selector
                print(f"   🤖 Auto-selecting best collection...")
                results = self._search_all_collections(
                    config, self.args.query, self.args.limit
                )

            # Display results
            self._display_results(results)
            return 0

        except ConfigurationError as e:
            return self.error_handler.handle_error(
                "CONFIG_INVALID",
                str(e),
                context={"config_path": self.args.config},
                exception=e,
            )
        except FileNotFoundError as e:
            return self.error_handler.handle_error(
                "CONFIG_NOT_FOUND",
                f"Configuration file not found",
                context={"config_path": self.args.config},
                exception=e,
            )
        except Exception as e:
            return self.error_handler.handle_error(
                "UNKNOWN_ERROR",
                "Search operation failed",
                context={"query": self.args.query},
                exception=e,
            )

    def _search_collection(
        self, collection_config: CollectionConfig, query: str, limit: int
    ) -> Dict[str, Any]:
        """Search a specific collection."""
        try:
            # Get Chroma client and collection
            client = get_client(collection_config.chroma_persist_dir)
            embedding_fn = build_embedding_function(
                collection_config.embedding_provider, collection_config.embedding_model
            )

            chroma_collection = client.get_collection(
                name=collection_config.chroma_collection,
                embedding_function=embedding_fn,
            )

            # Perform search with progress indicator
            print(f"   ⚡ Querying collection...")
            results = chroma_collection.query(query_texts=[query], n_results=limit)

            return {
                "collection": collection_config.id,
                "collection_name": collection_config.name,
                "results": results,
            }

        except ValueError as e:
            if "does not exist" in str(e):
                self.error_handler.handle_error(
                    "COLLECTION_NOT_FOUND",
                    f"Collection '{collection_config.id}' has not been ingested yet",
                    context={
                        "collection_id": collection_config.id,
                        "suggestion": f"Run 'rag_mcp ingest --collection {collection_config.id}' first",
                    },
                )
            else:
                self.error_handler.handle_error(
                    "UNKNOWN_ERROR",
                    f"Invalid query for collection '{collection_config.id}'",
                    exception=e,
                )
            return {"collection": collection_config.id, "results": None}
        except Exception as e:
            self.error_handler.handle_error(
                "UNKNOWN_ERROR",
                f"Failed to search collection '{collection_config.id}'",
                exception=e,
            )
            return {"collection": collection_config.id, "results": None}

    def _search_all_collections(
        self, config: MultiCollectionConfig, query: str, limit: int
    ) -> Dict[str, Any]:
        """Search across all collections using the selector."""
        try:
            selector = create_selector(config)

            # Select best collection for query
            selection = selector.select_collection(query)

            if not selection.collection_id:
                self.error_handler.handle_error(
                    "COLLECTION_NOT_FOUND",
                    "No suitable collection found for the query",
                    context={
                        "query": query,
                        "available_collections": list(config.collections.keys()),
                    },
                )
                return {"results": None}

            print(
                f"   ✅ Selected: {selection.collection_id} (confidence: {selection.confidence:.2f})"
            )

            # Search the selected collection
            collection_config = config.collections[selection.collection_id]
            results = self._search_collection(collection_config, query, limit)

            # Add selection metadata
            results["selection_confidence"] = selection.confidence
            results["selection_reasoning"] = selection.reasoning

            return results
        except Exception as e:
            self.error_handler.handle_error(
                "UNKNOWN_ERROR",
                "Failed to select collection for search",
                context={"query": query},
                exception=e,
            )
            return {"results": None}

    def _display_results(self, results: Dict[str, Any]) -> None:
        """Display search results."""
        if not results or not results.get("results"):
            print("\n⚠️  No results found")
            return

        print(f"\n📊 Search Results")
        print("=" * 60)

        if "collection_name" in results:
            print(
                f"📚 Collection: {results['collection_name']} ({results['collection']})"
            )

        if "selection_confidence" in results:
            confidence_bar = "█" * int(results["selection_confidence"] * 10)
            print(
                f"🎯 Confidence: {confidence_bar} {results['selection_confidence']:.2f}"
            )
            print(f"💭 Reasoning: {results['selection_reasoning']}")

        print()

        # Extract and display results
        query_results = results["results"]
        documents = query_results.get("documents", [[]])[0]
        metadatas = query_results.get("metadatas", [[]])[0]
        distances = query_results.get("distances", [[]])[0]

        if not documents:
            print("⚠️  No matching documents found in the collection")
            return

        print(f"Found {len(documents)} result(s):\n")

        for i, (doc, metadata, distance) in enumerate(
            zip(documents, metadatas, distances)
        ):
            score = 1 - distance
            score_bar = "●" * min(int(score * 10), 10)
            print(f"{i+1}. {score_bar} [Score: {score:.3f}]")
            if metadata:
                print(f"   🌐 URL: {metadata.get('url', 'N/A')}")
                print(f"   📝 Title: {metadata.get('title', 'N/A')}")

            # Format content with wrapping
            content_preview = doc[:300] if len(doc) > 300 else doc
            print(f"   📄 Content: {content_preview}...")
            print()


class ServerCommand(BaseCommand):
    """Server management command handler."""

    def execute(self) -> int:
        """Execute the server command."""
        subcommand = self.args.server_cmd

        try:
            if subcommand == "start":
                return self._start_server()
            elif subcommand == "status":
                return self._check_status()
            else:
                return self.error_handler.handle_error(
                    "UNKNOWN_ERROR", f"Unknown server subcommand: {subcommand}"
                )

        except ConfigurationError as e:
            return self.error_handler.handle_error(
                "CONFIG_INVALID",
                str(e),
                context={"config_path": self.args.config},
                exception=e,
            )
        except FileNotFoundError as e:
            return self.error_handler.handle_error(
                "CONFIG_NOT_FOUND",
                f"Configuration file not found",
                context={"config_path": self.args.config},
                exception=e,
            )
        except Exception as e:
            return self.error_handler.handle_error(
                "UNKNOWN_ERROR", "Server command failed", exception=e
            )

    def _start_server(self) -> int:
        """Start the MCP server."""
        print("\n🚀 Starting MCP server...")
        print("=" * 60)

        # Import and run the server
        import subprocess
        import sys

        try:
            # Check if configuration exists
            config_path = Path(self.args.config)
            if not config_path.exists():
                return self.error_handler.handle_error(
                    "CONFIG_NOT_FOUND",
                    f"Configuration file not found: {self.args.config}",
                    context={"config_path": self.args.config},
                )

            print(f"📋 Configuration: {self.args.config}")
            print(f"⚡ Starting server process...")
            print(f"\n{'─' * 60}")
            print("Server output will appear below. Press Ctrl+C to stop.")
            print(f"{'─' * 60}\n")

            # Run the server module
            subprocess.run(
                [sys.executable, "-m", "rag_mcp.server"],
                env={**os.environ, "MULTI_COLLECTION_CONFIG_PATH": self.args.config},
            )
            return 0
        except KeyboardInterrupt:
            print("\n\n✅ Server stopped gracefully")
            return 0
        except subprocess.CalledProcessError as e:
            return self.error_handler.handle_error(
                "UNKNOWN_ERROR",
                f"Server process failed with exit code {e.returncode}",
                exception=e,
            )
        except Exception as e:
            return self.error_handler.handle_error(
                "UNKNOWN_ERROR", "Failed to start server", exception=e
            )

    def _check_status(self) -> int:
        """Check the server status."""
        try:
            config = load_multi_config(self.args.config)

            print("\n🔍 MCP Server Status")
            print("=" * 60)
            print(f"📋 Configuration file: {self.args.config}")
            print(f"📚 Collections configured: {len(config.collections)}")

            # Check each collection
            print("\n📊 Collection Status:")
            print("-" * 60)

            ready_count = 0
            not_ready_count = 0

            for collection_id, collection_config in config.collections.items():
                try:
                    client = get_client(collection_config.chroma_persist_dir)
                    collection = client.get_collection(
                        name=collection_config.chroma_collection
                    )
                    doc_count = collection.count()
                    status = f"✅ Ready ({doc_count} docs)"
                    ready_count += 1
                except Exception:
                    status = "⭕ Not ingested"
                    not_ready_count += 1

                print(f"  {collection_id}: {status}")

            # Summary
            print("-" * 60)
            print(f"\n📈 Summary:")
            print(f"   ✅ Ready: {ready_count}")
            print(f"   ⭕ Not ingested: {not_ready_count}")
            print(f"   📊 Total: {len(config.collections)}")

            if not_ready_count > 0:
                print(f"\n💡 Tip: Run 'rag_mcp ingest --all' to ingest all collections")

            return 0

        except ConfigurationError as e:
            return self.error_handler.handle_error(
                "CONFIG_INVALID",
                str(e),
                context={"config_path": self.args.config},
                exception=e,
            )
        except FileNotFoundError as e:
            return self.error_handler.handle_error(
                "CONFIG_NOT_FOUND",
                f"Configuration file not found",
                context={"config_path": self.args.config},
                exception=e,
            )
        except Exception as e:
            return self.error_handler.handle_error(
                "UNKNOWN_ERROR", "Failed to check server status", exception=e
            )


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the CLI."""
    # Early compatibility check for old command syntax
    # This handles cases where users call the script directly with old commands
    if argv and len(argv) > 0 and argv[0] in ["ingest-multi", "ingest-collection"]:
        old_cmd = argv[0]
        print(
            f"\n⚠️  Note: Direct usage of '{old_cmd}' is deprecated.\n"
            f"   The command will still work but please update your scripts.\n",
            file=sys.stderr,
        )

    # Create main parser
    parser = argparse.ArgumentParser(
        prog="rag_mcp",
        description="RAG MCP - Multi-collection RAG system with MCP server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Add global config option (can be overridden by command-specific config)
    parser.add_argument(
        "--config",
        default="ingest/multi-collection.yml",
        help="Path to configuration file (default: ingest/multi-collection.yml)",
    )

    # Create subparsers for main commands
    subparsers = parser.add_subparsers(
        dest="command", required=True, help="Available commands"
    )
    # ===== INGEST COMMAND =====
    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Ingest collections from configuration",
        description="Ingest one or more collections defined in the configuration file",
    )
    ingest_parser.add_argument(
        "--config",
        required=True,
        help="Path to YAML configuration file",
    )
    ingest_parser.add_argument(
        "--collection",
        action="append",
        help="Specific collection(s) to ingest (can be used multiple times, supports comma-separated)",
    )
    ingest_parser.add_argument(
        "--all",
        action="store_true",
        help="Explicitly ingest all collections (default behavior)",
    )
    ingest_parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on first error when processing multiple collections",
    )
    # Add override options for hierarchical configuration
    ingest_parser.add_argument(
        "--max-pages",
        type=int,
        help="Override maximum pages to crawl per collection",
    )
    ingest_parser.add_argument(
        "--concurrency",
        type=int,
        help="Override concurrent requests",
    )
    ingest_parser.add_argument(
        "--chunk-chars",
        type=int,
        help="Override chunk size in characters",
    )
    ingest_parser.add_argument(
        "--chunk-overlap",
        type=int,
        help="Override chunk overlap in characters",
    )

    # ===== COLLECTION COMMAND =====
    collection_parser = subparsers.add_parser(
        "collection",
        help="Collection management commands",
        description="Manage and inspect collections",
    )
    collection_parser.add_argument(
        "--config",
        help="Path to YAML configuration file",
    )

    collection_subparsers = collection_parser.add_subparsers(
        dest="collection_cmd", required=True, help="Collection subcommands"
    )

    # collection list
    collection_list = collection_subparsers.add_parser(
        "list", help="List all available collections"
    )

    # collection info
    collection_info = collection_subparsers.add_parser(
        "info", help="Show detailed information about a collection"
    )
    collection_info.add_argument("collection_id", help="Collection ID to show info for")

    # collection validate
    collection_validate = collection_subparsers.add_parser(
        "validate", help="Validate a collection configuration"
    )
    collection_validate.add_argument("collection_id", help="Collection ID to validate")

    # collection stats
    collection_stats = collection_subparsers.add_parser(
        "stats", help="Show statistics for a collection"
    )
    collection_stats.add_argument(
        "collection_id", help="Collection ID to show stats for"
    )

    # ===== SEARCH COMMAND =====
    search_parser = subparsers.add_parser(
        "search",
        help="Search across collections",
        description="Search for content in one or all collections",
    )
    search_parser.add_argument(
        "--query",
        required=True,
        help="Search query text",
    )
    search_parser.add_argument(
        "--collection",
        help="Target specific collection (searches all if not specified)",
    )
    search_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of results to return (default: 5)",
    )
    search_parser.add_argument(
        "--config",
        help="Path to YAML configuration file",
    )

    # ===== SERVER COMMAND =====
    server_parser = subparsers.add_parser(
        "server",
        help="MCP server management",
        description="Start and manage the MCP server",
    )
    server_parser.add_argument(
        "--config",
        help="Path to YAML configuration file",
    )

    server_subparsers = server_parser.add_subparsers(
        dest="server_cmd", required=True, help="Server subcommands"
    )

    # server start
    server_start = server_subparsers.add_parser("start", help="Start the MCP server")

    # server status
    server_status = server_subparsers.add_parser(
        "status", help="Check server and collection status"
    )

    # ===== DEBUG COMMAND =====
    debug_parser = subparsers.add_parser(
        "debug",
        help="Debug configuration and system state",
        description="Debug tools for configuration and system inspection",
    )
    debug_subparsers = debug_parser.add_subparsers(
        dest="debug_cmd", required=True, help="Debug subcommands"
    )

    # debug config
    debug_config = debug_subparsers.add_parser(
        "config", help="Show configuration hierarchy and sources"
    )
    debug_config.add_argument(
        "--config",
        help="Path to configuration file",
    )
    debug_config.add_argument(
        "--format",
        choices=["yaml", "json"],
        default="yaml",
        help="Output format for configuration",
    )

    # ===== BACKWARD COMPATIBILITY: OLD COMMANDS =====
    # Add deprecated commands for backward compatibility

    # ingest-multi (deprecated)
    ingest_multi_parser = subparsers.add_parser(
        "ingest-multi",
        help="[DEPRECATED] Use 'ingest --all' instead",
        description="[DEPRECATED] Ingest all collections from a YAML config",
    )
    ingest_multi_parser.add_argument(
        "--config",
        required=True,
        help="Path to YAML config with crawl + embedding settings",
    )

    # ingest-collection (deprecated)
    ingest_collection_parser = subparsers.add_parser(
        "ingest-collection",
        help="[DEPRECATED] Use 'ingest --collection <id>' instead",
        description="[DEPRECATED] Ingest a specific collection from a YAML config",
    )
    ingest_collection_parser.add_argument(
        "--config",
        required=True,
        help="Path to YAML config with crawl + embedding settings",
    )
    ingest_collection_parser.add_argument(
        "--collection", help="Ingest a specific collection"
    )

    # Parse arguments
    args = parser.parse_args(argv)

    # If command doesn't have its own config, use global config
    if not hasattr(args, "config") or args.config is None:
        args.config = parser.get_default("config")

    # Handle deprecated commands using the compatibility layer
    if args.command in ["ingest-multi", "ingest-collection"]:
        # Check and warn about deprecated command
        CLICompatibility.check_and_warn_deprecated(args.command)

        try:
            # Transform arguments to new structure
            args = CLICompatibility.transform_args(args)
        except ValueError as e:
            return error_handler.handle_error(
                "CONFIG_INVALID", str(e), context={"command": args.command}
            )

    # Handle debug command separately
    if args.command == "debug":
        if args.debug_cmd == "config":
            return handle_debug_config(args)
        else:
            print(f"Unknown debug command: {args.debug_cmd}")
            return 1

    # Execute appropriate command
    command_map = {
        "ingest": IngestCommand,
        "collection": CollectionCommand,
        "search": SearchCommand,
        "server": ServerCommand,
    }

    command_class = command_map.get(args.command)
    if not command_class:
        return error_handler.handle_error(
            "UNKNOWN_ERROR",
            f"Unknown command: {args.command}",
            context={
                "available_commands": list(command_map.keys()),
                "suggestion": "Use 'rag_mcp --help' to see available commands",
            },
        )

    try:
        # Create and execute command
        command = command_class(args)
        return command.execute()
    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user")
        return 130  # Standard exit code for Ctrl+C
    except Exception as e:
        return error_handler.handle_error(
            "UNKNOWN_ERROR",
            f"Unexpected error while executing command '{args.command}'",
            exception=e,
        )


def handle_debug_config(args: argparse.Namespace) -> int:
    """Handle debug config command.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code
    """
    from .config_manager import get_config_manager, load_hierarchical_config

    config_path = args.config or "ingest/multi-collection.yml"

    # Enable debug mode
    os.environ["CONFIG_DEBUG"] = "true"

    try:
        # Load configuration with hierarchy
        print("\n" + "=" * 60)
        print("Loading Configuration with Hierarchy")
        print("=" * 60)

        config = load_hierarchical_config(config_file=config_path, debug=True)

        # Get the config manager to access debug info
        manager = get_config_manager(debug=True)

        # Print configuration sources
        print("\n" + "=" * 60)
        print("Configuration Export")
        print("=" * 60)

        if args.format == "json":
            print(manager.export_config(format="json"))
        else:
            print(manager.export_config(format="yaml"))

        # Print validation results
        validation = manager.validation_result
        if validation.errors:
            print("\n❌ Validation Errors:")
            for error in validation.errors:
                print(f"  • {error}")

        if validation.warnings:
            print("\n⚠️ Validation Warnings:")
            for warning in validation.warnings:
                print(f"  • {warning}")

        if validation.is_valid:
            print("\n✅ Configuration is valid")

        return 0

    except Exception as e:
        print(f"\n❌ Error loading configuration: {e}")
        return 1


if __name__ == "__main__":
    import os

    raise SystemExit(main())
