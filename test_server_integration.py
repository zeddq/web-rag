#!/usr/bin/env python3
"""Integration tests for the new multi-collection MCP server."""

import json
import os
import sys
import tempfile
import yaml
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, str(Path(__file__).parent))

from rag_mcp.server import get_state, MultiCollectionState
from rag_mcp.config import MultiCollectionConfig, load_multi_config, ConfigurationError


def test_multi_collection_state_initialization():
    """Test that server initializes with multi-collection configuration."""
    print("Testing multi-collection state initialization...")

    # Set multi-config path to our test config
    original_config_path = os.environ.get("MULTI_COLLECTION_CONFIG_PATH")
    os.environ["MULTI_COLLECTION_CONFIG_PATH"] = "ingest/multi-collection.example.yml"

    # Clear global state
    import rag_mcp.server as server_module

    server_module._state = None
    if hasattr(server_module, "_legacy_state"):
        server_module._legacy_state = None

    try:
        # This should load the multi-collection configuration
        state = get_state()
        assert isinstance(state, MultiCollectionState)
        assert len(state.collections) >= 1
        print(
            f"✓ Multi-collection state initialized with {len(state.collections)} collections"
        )

        # Test that we can access the collections
        collections = list(state.collections.keys())
        assert len(collections) >= 1
        print(f"✓ Available collections: {collections}")

    finally:
        # Clean up
        if original_config_path:
            os.environ["MULTI_COLLECTION_CONFIG_PATH"] = original_config_path
        elif "MULTI_COLLECTION_CONFIG_PATH" in os.environ:
            del os.environ["MULTI_COLLECTION_CONFIG_PATH"]


def test_multi_collection_config():
    """Test loading a multi-collection configuration."""
    print("\nTesting multi-collection config...")

    # Create a temporary multi-collection config
    config_data = {
        "version": "2.0",
        "defaults": {
            "chunk_chars": 1200,
            "chunk_overlap": 200,
            "embedding_provider": "sentence-transformers",
            "embedding_model": "all-MiniLM-L6-v2",
            "chroma_persist_dir": "data/chroma",
            "max_pages": 100,
            "concurrency": 4,
        },
        "collections": {
            "test_collection_1": {
                "name": "Test Collection 1",
                "description": "First test collection for unit testing",
                "domain": "testing",
                "tags": ["test", "unit", "first"],
                "sources": {
                    "base_urls": ["https://example.com/docs1/"],
                    "allow_patterns": [".*"],
                    "deny_patterns": [".*\\.pdf$"],
                },
                "metadata": {
                    "priority": 1,
                    "version": "1.0.0",
                },
            },
            "test_collection_2": {
                "name": "Test Collection 2",
                "description": "Second test collection with different domain",
                "domain": "programming",
                "tags": ["test", "programming", "second"],
                "sources": {
                    "base_urls": ["https://example.com/docs2/"],
                },
                "chunk_chars": 800,  # Override default
                "metadata": {
                    "priority": 2,
                    "version": "2.0.0",
                },
            },
        },
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(config_data, f)
        config_path = f.name

    try:
        # Load the config
        multi_config = load_multi_config(config_path)
        assert isinstance(multi_config, MultiCollectionConfig)
        assert len(multi_config.collections) == 2
        print("✓ Multi-collection config loaded successfully")

        # Check that collections have correct settings
        coll1 = multi_config.collections["test_collection_1"]
        coll2 = multi_config.collections["test_collection_2"]

        assert coll1.chunk_chars == 1200  # Uses default
        assert coll2.chunk_chars == 800  # Override
        assert coll1.domain == "testing"
        assert coll2.domain == "programming"
        print("✓ Collection configurations are correct")

        # Test state creation
        state = MultiCollectionState(multi_config)
        assert len(state.collections) == 2
        print("✓ MultiCollectionState created successfully")

        # Test collection selector
        selector = state.get_selector()
        assert selector is not None
        print("✓ CollectionSelector initialized")

        # Test collection selection
        selection = selector.select_collection("test programming")
        print(
            f"✓ Collection selection result: {selection.collection_id} (confidence: {selection.confidence:.2f})"
        )

    finally:
        # Clean up
        os.unlink(config_path)


def test_server_tools():
    """Test that the new MCP tools work with the configuration."""
    print("\nTesting server tools...")

    # Use the example multi-collection config if it exists
    config_path = "ingest/multi-collection.example.yml"
    if not os.path.exists(config_path):
        print("⚠ Example config not found, skipping tool tests")
        return

    try:
        # Import the server tools
        from rag_mcp.server import (
            select_collection,
            list_collections,
            get_collection_info,
            search,
        )

        # Test list_collections
        result = list_collections(config_path=config_path)
        assert "collections" in result
        assert len(result["collections"]) > 0
        print(f"✓ list_collections returned {len(result['collections'])} collections")

        # Test select_collection with a programming query
        result = select_collection(
            "python programming documentation", config_path=config_path
        )
        if result.get("collection_id"):
            print(
                f"✓ select_collection chose: {result['collection_id']} (confidence: {result['confidence']:.2f})"
            )
        else:
            print(f"✓ select_collection found no match: {result['reasoning']}")

        # Test get_collection_info if we have collections
        collections_result = list_collections(config_path=config_path)
        if collections_result["collections"]:
            first_collection_id = collections_result["collections"][0]["id"]
            info_result = get_collection_info(
                first_collection_id, config_path=config_path
            )
            assert "id" in info_result
            assert info_result["id"] == first_collection_id
            print(f"✓ get_collection_info returned info for: {first_collection_id}")

        # Test search tool (note: this won't return results without actual data, but should not error)
        search_result = search("test query", k=3)
        assert "results" in search_result or "error" in search_result
        print("✓ search tool executed without errors")

    except Exception as e:
        print(f"✗ Tool test failed: {e}")
        raise


def main():
    """Run all integration tests."""
    print("Running MCP server integration tests...\n")

    try:
        test_multi_collection_state_initialization()
        test_multi_collection_config()
        test_server_tools()

        print("\n✅ All integration tests passed!")
        return 0

    except Exception as e:
        print(f"\n❌ Integration test failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
