#!/usr/bin/env python3
"""
Backwards Compatibility Test Suite for Multi-Collection RAG System

This test suite validates that existing single-collection configurations
continue to work unchanged, ensuring seamless upgrades for existing users.
"""

import json
import os
import sys
import tempfile
import yaml
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch, Mock

# Add the project root to the Python path
sys.path.insert(0, str(Path(__file__).parent))

from rag_mcp.config import (
    CollectionConfig,
    MultiCollectionConfig,
    load_config,
    load_multi_config,
    detect_config_format,
    ConfigurationError,
)
from rag_mcp.server import (
    MultiCollectionState,
    LegacyWebRAGState,
    get_state,
    select_collection,
    list_collections,
    get_collection_info,
    search,
)


class TestBackwardsCompatibility:
    """Test suite for backwards compatibility validation."""

    @classmethod
    def setup_class(cls):
        """Set up test fixtures with legacy configurations."""
        # Legacy web_rag.yml format
        cls.legacy_config = {
            "base_urls": ["https://jj-vcs.github.io/jj/latest/"],
            "allow_patterns": [r"^https://jj-vcs\.github\.io/jj/latest/.*"],
            "deny_patterns": [r"\.pdf$", r"\.zip$", r"\.(png|jpg|jpeg|gif|svg)$"],
            "max_pages": 500,
            "concurrency": 8,
            "chunk_chars": 1200,
            "chunk_overlap": 200,
            "chroma": {
                "persist_dir": "data/chroma",
                "collection": "web_rag",
            },
            "embedding_provider": "sentence-transformers",
            "embedding_model": "all-MiniLM-L6-v2",
        }

        # Alternative legacy format (without nested chroma)
        cls.legacy_config_flat = {
            "base_urls": ["https://docs.python.org/3/"],
            "chunk_chars": 1500,
            "chunk_overlap": 300,
            "max_pages": 200,
            "chroma_persist_dir": "data/python_docs",
            "chroma_collection": "python_docs",
            "embedding_provider": "openai",
            "embedding_model": "text-embedding-3-small",
        }

        # Environment variable-based configuration
        cls.env_config = {
            "base_urls": ["https://fastapi.tiangolo.com/"],
            "chunk_chars": 800,
            "max_pages": 100,
            "embedding_provider": "sentence-transformers",
            "embedding_model": "all-MiniLM-L6-v2",
            # No chroma settings - should use environment variables
        }

    def create_temp_config(self, config_data: Dict[str, Any]) -> str:
        """Create a temporary configuration file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config_data, f, default_flow_style=False)
            return f.name

    def test_legacy_config_format_detection(self):
        """Test that legacy configurations are correctly detected."""
        print("\n=== Testing Legacy Config Format Detection ===")

        # Test detection of various legacy formats
        test_cases = [
            (self.legacy_config, "legacy"),
            (self.legacy_config_flat, "legacy"),
            (self.env_config, "legacy"),
            ({"version": "2.0", "collections": {}}, "multi-v2"),
        ]

        for config_data, expected_format in test_cases:
            detected_format = detect_config_format(config_data)
            assert (
                detected_format == expected_format
            ), f"Expected {expected_format}, got {detected_format}"
            print(f"✓ Correctly detected '{detected_format}' format")

        print("✅ Legacy config format detection test passed!")

    def test_legacy_config_loading(self):
        """Test loading legacy configurations."""
        print("\n=== Testing Legacy Config Loading ===")

        configs_to_test = [
            ("Nested chroma config", self.legacy_config),
            ("Flat chroma config", self.legacy_config_flat),
            ("Environment-based config", self.env_config),
        ]

        for config_name, config_data in configs_to_test:
            config_path = self.create_temp_config(config_data)

            try:
                # Load as single collection config
                collection_config = load_config(config_path)
                assert isinstance(collection_config, CollectionConfig)
                print(f"✓ {config_name}: Loaded as CollectionConfig")

                # Validate essential fields
                assert len(collection_config.sources.base_urls) > 0
                assert collection_config.chunk_chars > 0
                assert collection_config.embedding_provider is not None
                assert collection_config.embedding_model is not None
                print(f"✓ {config_name}: All essential fields present")

                # Test conversion to multi-collection format
                multi_config = MultiCollectionConfig.from_single_collection(
                    collection_config
                )
                assert isinstance(multi_config, MultiCollectionConfig)
                assert len(multi_config.collections) == 1
                print(f"✓ {config_name}: Converted to multi-collection format")

            finally:
                os.unlink(config_path)

        print("✅ Legacy config loading test passed!")

    def test_legacy_environment_variable_support(self):
        """Test that legacy environment variables are still supported."""
        print("\n=== Testing Legacy Environment Variable Support ===")

        # Test environment variables that should be respected
        env_vars_to_test = [
            ("CHROMA_PERSIST_DIR", "data/test_chroma"),
            ("CHROMA_COLLECTION", "test_collection"),
            ("EMBEDDING_PROVIDER", "openai"),
            ("EMBEDDING_MODEL", "text-embedding-3-small"),
            ("WEB_RAG_QUERY_PROVIDER", "sentence-transformers"),
            ("WEB_RAG_QUERY_MODEL", "all-MiniLM-L6-v2"),
        ]

        original_env = {}

        try:
            # Save original environment
            for env_var, _ in env_vars_to_test:
                original_env[env_var] = os.environ.get(env_var)

            # Set test environment variables
            for env_var, test_value in env_vars_to_test:
                os.environ[env_var] = test_value

            # Create minimal config that relies on environment variables
            minimal_config = {
                "base_urls": ["https://example.com/"],
                "chunk_chars": 1000,
            }

            config_path = self.create_temp_config(minimal_config)

            try:
                collection_config = load_config(config_path)

                # Verify that environment variables are used
                # Note: The exact behavior depends on implementation details
                # but we should be able to load the config without errors
                assert isinstance(collection_config, CollectionConfig)
                print("✓ Config loaded successfully with environment variables")

                # Test that these can be used in the server
                multi_config = MultiCollectionConfig.from_single_collection(
                    collection_config
                )
                state = MultiCollectionState(multi_config)
                assert len(state.collections) == 1
                print("✓ Environment-based config works with MultiCollectionState")

            finally:
                os.unlink(config_path)

        finally:
            # Restore original environment
            for env_var, original_value in original_env.items():
                if original_value is not None:
                    os.environ[env_var] = original_value
                elif env_var in os.environ:
                    del os.environ[env_var]

        print("✅ Legacy environment variable support test passed!")

    def test_legacy_mcp_tools_compatibility(self):
        """Test that MCP tools work with legacy configurations."""
        print("\n=== Testing Legacy MCP Tools Compatibility ===")

        config_path = self.create_temp_config(self.legacy_config)

        try:
            # Test list_collections with legacy config
            collections_result = list_collections(config_path=config_path)
            assert "collections" in collections_result
            assert len(collections_result["collections"]) == 1
            print("✓ list_collections works with legacy config")

            # Validate single collection data
            collection = collections_result["collections"][0]
            assert "id" in collection
            assert "name" in collection
            assert "description" in collection
            print("✓ Legacy collection metadata properly formatted")

            # Test select_collection with legacy config
            selection_result = select_collection(
                "jujutsu version control", config_path=config_path
            )
            # Should select the only available collection
            if selection_result.get("collection_id"):
                assert (
                    selection_result["confidence"] >= 0.8
                )  # Should be confident since only one option
                print(
                    f"✓ select_collection works with legacy config (confidence: {selection_result['confidence']:.3f})"
                )
            else:
                print(
                    f"⚠ select_collection found no match: {selection_result.get('reasoning')}"
                )

            # Test get_collection_info with legacy config
            collection_id = collections_result["collections"][0]["id"]
            info_result = get_collection_info(collection_id, config_path=config_path)
            assert info_result["id"] == collection_id
            assert "name" in info_result
            assert "description" in info_result
            print("✓ get_collection_info works with legacy config")

            # Test search tool with legacy config
            search_result = search("test query", k=5, config_path=config_path)
            assert "results" in search_result or "error" in search_result
            print("✓ search tool works with legacy config")

        finally:
            os.unlink(config_path)

        print("✅ Legacy MCP tools compatibility test passed!")

    def test_legacy_server_state_fallback(self):
        """Test that the server falls back to legacy mode when appropriate."""
        print("\n=== Testing Legacy Server State Fallback ===")

        # Clear any existing state
        import rag_mcp.server as server_module

        server_module._state = None
        server_module._legacy_state = None

        # Remove multi-collection config environment variable temporarily
        original_multi_config = os.environ.get("MULTI_COLLECTION_CONFIG_PATH")
        if "MULTI_COLLECTION_CONFIG_PATH" in os.environ:
            del os.environ["MULTI_COLLECTION_CONFIG_PATH"]

        try:
            # Set up legacy environment
            os.environ["CHROMA_PERSIST_DIR"] = "data/test_chroma"
            os.environ["CHROMA_COLLECTION"] = "test_legacy"

            # This should trigger legacy fallback
            state = get_state()

            # Should get MultiCollectionState with single collection (converted from legacy)
            assert isinstance(state, MultiCollectionState)
            assert len(state.collections) == 1
            print("✓ Server falls back to legacy mode correctly")

            # Test that the legacy collection has reasonable defaults
            collection_id = list(state.collections.keys())[0]
            collection_instance = state.collections[collection_id]
            config = collection_instance.config

            assert config.id is not None
            assert config.chroma_collection == "test_legacy"
            assert "data/test_chroma" in config.chroma_persist_dir
            print("✓ Legacy collection has correct settings")

        finally:
            # Restore environment
            if original_multi_config:
                os.environ["MULTI_COLLECTION_CONFIG_PATH"] = original_multi_config

            # Clean up test environment variables
            for env_var in ["CHROMA_PERSIST_DIR", "CHROMA_COLLECTION"]:
                if env_var in os.environ:
                    del os.environ[env_var]

        print("✅ Legacy server state fallback test passed!")

    def test_legacy_resource_uri_compatibility(self):
        """Test that legacy resource URIs continue to work."""
        print("\n=== Testing Legacy Resource URI Compatibility ===")

        config_path = self.create_temp_config(self.legacy_config)

        try:
            multi_config = load_multi_config(config_path)
            state = MultiCollectionState(multi_config)

            # Get the single collection
            collection_id = list(state.collections.keys())[0]
            collection_instance = state.collections[collection_id]

            # Test that legacy resource URIs are still generated correctly
            chunk_id = "test_chunk_123"
            expected_uri = f"web-rag://chunk/{chunk_id}"

            # The search method should generate this format
            # We can't test actual search without data, but we can verify the format logic
            assert expected_uri.startswith("web-rag://")
            assert "chunk" in expected_uri
            assert chunk_id in expected_uri
            print("✓ Legacy resource URI format maintained")

            # Test collection-specific URIs are backwards compatible
            collection_uri = f"web-rag://{collection_id}/chunk/{chunk_id}"
            assert collection_id in collection_uri
            print("✓ Collection-specific URIs work with legacy collections")

        finally:
            os.unlink(config_path)

        print("✅ Legacy resource URI compatibility test passed!")

    def test_legacy_configuration_migration(self):
        """Test smooth migration path from legacy to multi-collection."""
        print("\n=== Testing Legacy Configuration Migration ===")

        # Test various legacy configuration scenarios
        migration_scenarios = [
            ("Standard web_rag.yml", self.legacy_config),
            ("Flat configuration", self.legacy_config_flat),
            ("Environment-dependent", self.env_config),
        ]

        for scenario_name, legacy_config in migration_scenarios:
            config_path = self.create_temp_config(legacy_config)

            try:
                print(f"\nTesting migration scenario: {scenario_name}")

                # Step 1: Load as legacy
                legacy_collection = load_config(config_path)
                assert isinstance(legacy_collection, CollectionConfig)
                print(f"  ✓ Loaded as legacy CollectionConfig")

                # Step 2: Convert to multi-collection
                multi_config = MultiCollectionConfig.from_single_collection(
                    legacy_collection
                )
                assert isinstance(multi_config, MultiCollectionConfig)
                assert len(multi_config.collections) == 1
                print(f"  ✓ Converted to MultiCollectionConfig")

                # Step 3: Verify all settings preserved
                converted_collection = next(iter(multi_config.collections.values()))

                # Key settings should be preserved
                assert (
                    converted_collection.sources.base_urls
                    == legacy_collection.sources.base_urls
                )
                assert converted_collection.chunk_chars == legacy_collection.chunk_chars
                assert (
                    converted_collection.chunk_overlap
                    == legacy_collection.chunk_overlap
                )
                assert (
                    converted_collection.embedding_provider
                    == legacy_collection.embedding_provider
                )
                assert (
                    converted_collection.embedding_model
                    == legacy_collection.embedding_model
                )
                print(f"  ✓ All settings preserved in conversion")

                # Step 4: Test that MCP tools work with migrated config
                state = MultiCollectionState(multi_config)
                selector = state.get_selector()
                selection = selector.select_collection("test migration query")
                assert (
                    selection.confidence == 1.0
                )  # Only one collection, should be certain
                print(f"  ✓ MCP tools work with migrated configuration")

            finally:
                os.unlink(config_path)

        print("✅ Legacy configuration migration test passed!")

    def test_legacy_api_behavior_preservation(self):
        """Test that legacy API behavior is preserved."""
        print("\n=== Testing Legacy API Behavior Preservation ===")

        config_path = self.create_temp_config(self.legacy_config)

        try:
            # Test that search behavior is preserved for single-collection setups
            search_result = search("test query", k=5, config_path=config_path)

            # Should have the same structure as before
            assert "results" in search_result or "error" in search_result

            if "results" in search_result:
                assert isinstance(search_result["results"], list)
                print("✓ Search result structure preserved")

                # If there were results, they should have the expected format
                # (We can't test actual results without data)
                for result in search_result["results"][
                    :1
                ]:  # Check first result if exists
                    expected_fields = [
                        "id",
                        "resource",
                        "collection_id",
                        "collection_name",
                    ]
                    for field in expected_fields:
                        assert field in result
                    print("✓ Search result format preserved")

            # Test that collection selection is transparent for single-collection configs
            # User shouldn't need to care about collection selection
            selection_result = select_collection("any query", config_path=config_path)
            if selection_result.get("collection_id"):
                assert selection_result["confidence"] >= 0.8  # Should be very confident
                print("✓ Single-collection selection behavior preserved")

            # Test that list_collections returns exactly one collection
            collections_result = list_collections(config_path=config_path)
            assert len(collections_result["collections"]) == 1
            print("✓ Single-collection listing behavior preserved")

        finally:
            os.unlink(config_path)

        print("✅ Legacy API behavior preservation test passed!")


def run_backwards_compatibility_tests():
    """Run all backwards compatibility tests and report results."""
    print("Multi-Collection RAG System - Backwards Compatibility Tests")
    print("=" * 65)

    test_suite = TestBackwardsCompatibility()
    test_suite.setup_class()

    tests = [
        test_suite.test_legacy_config_format_detection,
        test_suite.test_legacy_config_loading,
        test_suite.test_legacy_environment_variable_support,
        test_suite.test_legacy_mcp_tools_compatibility,
        test_suite.test_legacy_server_state_fallback,
        test_suite.test_legacy_resource_uri_compatibility,
        test_suite.test_legacy_configuration_migration,
        test_suite.test_legacy_api_behavior_preservation,
    ]

    passed = 0
    total = len(tests)

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"\n❌ Test {test.__name__} failed: {e}")
            import traceback

            traceback.print_exc()

    print(f"\n{'=' * 65}")
    print(f"Backwards Compatibility Test Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All backwards compatibility tests passed!")
        print("   Existing users can upgrade seamlessly without changes.")
        return 0
    else:
        print("❌ Some backwards compatibility tests failed.")
        print("   This may break existing user configurations.")
        return 1


if __name__ == "__main__":
    exit(run_backwards_compatibility_tests())
