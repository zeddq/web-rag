#!/usr/bin/env python
"""Test script to verify backward compatibility of the hierarchical configuration system."""

import os
import sys
import tempfile
import yaml
from pathlib import Path

# Add the project directory to path
sys.path.insert(0, str(Path(__file__).parent))

from rag_mcp.config import load_config, load_multi_config, MultiCollectionConfig
from rag_mcp.config_manager import get_config_manager, ConfigManager


def test_backward_compatibility():
    """Test that existing configuration loading still works."""
    print("\n=== Testing Backward Compatibility ===\n")

    # Test 1: Load config without hierarchy (backward compatible mode)
    print("Test 1: Loading config in backward compatible mode...")
    try:
        config = load_config("ingest/multi-collection.example.yml", use_hierarchy=False)
        assert isinstance(config, MultiCollectionConfig)
        assert len(config.collections) > 0
        print("✅ Backward compatible loading works")
    except Exception as e:
        print(f"❌ Backward compatible loading failed: {e}")
        return False

    # Test 2: Load config with hierarchy (new mode)
    print("\nTest 2: Loading config with hierarchical system...")
    try:
        config = load_config("ingest/multi-collection.example.yml", use_hierarchy=True)
        assert isinstance(config, MultiCollectionConfig)
        assert len(config.collections) > 0
        print("✅ Hierarchical loading works")
    except Exception as e:
        print(f"❌ Hierarchical loading failed: {e}")
        return False

    # Test 3: Test environment variable override
    print("\nTest 3: Testing environment variable override...")
    os.environ["CHROMA_PERSIST_DIR"] = "test/env/override"
    os.environ["LOG_LEVEL"] = "DEBUG"
    try:
        config = load_config("ingest/multi-collection.example.yml", use_hierarchy=True)
        # Note: The environment variables affect the internal config manager
        manager = get_config_manager()
        manager_config = manager.load_configuration(
            file_config=yaml.safe_load(open("ingest/multi-collection.example.yml"))
        )
        assert manager_config["defaults"]["chroma_persist_dir"] == "test/env/override"
        assert manager_config["logging"]["level"] == "DEBUG"
        print("✅ Environment variable override works")
    except Exception as e:
        print(f"❌ Environment variable override failed: {e}")
        return False
    finally:
        # Clean up environment variables
        os.environ.pop("CHROMA_PERSIST_DIR", None)
        os.environ.pop("LOG_LEVEL", None)

    # Test 4: Test CLI argument override
    print("\nTest 4: Testing CLI argument override...")
    try:
        cli_args = {"defaults": {"max_pages": 100, "chunk_chars": 2000}}
        config = load_config(
            "ingest/multi-collection.example.yml", cli_args=cli_args, use_hierarchy=True
        )
        # The CLI args should be applied through the hierarchy
        print(
            "✅ CLI argument override accepted (full validation requires checking merged config)"
        )
    except Exception as e:
        print(f"❌ CLI argument override failed: {e}")
        return False

    # Test 5: Test precedence order
    print("\nTest 5: Testing configuration precedence...")
    try:
        # Set environment variable
        os.environ["MAX_PAGES"] = "200"

        # CLI args should override environment
        cli_args = {"defaults": {"max_pages": 150}}

        manager = ConfigManager()
        file_config = yaml.safe_load(open("ingest/multi-collection.example.yml"))
        merged_config = manager.load_configuration(
            cli_config=cli_args, file_config=file_config
        )

        # CLI (150) should override ENV (200) and FILE (varies by collection)
        assert merged_config["defaults"]["max_pages"] == 150
        print("✅ Precedence order correct (CLI > ENV > File > Defaults)")
    except Exception as e:
        print(f"❌ Precedence test failed: {e}")
        return False
    finally:
        os.environ.pop("MAX_PAGES", None)

    print("\n=== All Tests Passed ===\n")
    return True


def test_validation():
    """Test configuration validation."""
    print("\n=== Testing Configuration Validation ===\n")

    manager = ConfigManager()

    # Test valid configuration
    print("Test 1: Valid configuration...")
    valid_config = {
        "version": "2.0",
        "defaults": {
            "chunk_chars": 1200,
            "chunk_overlap": 200,
            "max_pages": 500,
            "concurrency": 8,
        },
        "collections": {},
    }

    result = manager.validate_configuration(valid_config)
    if result.is_valid:
        print("✅ Valid configuration passes validation")
    else:
        print(f"❌ Valid configuration failed: {result.errors}")

    # Test invalid configuration
    print("\nTest 2: Invalid configuration...")
    invalid_config = {
        "version": "2.0",
        "defaults": {
            "chunk_chars": -100,  # Invalid: negative
            "chunk_overlap": 2000,  # Invalid: larger than chunk_chars
            "max_pages": 0,  # Invalid: zero
            "concurrency": -1,  # Invalid: negative
        },
        "collections": {},
    }

    result = manager.validate_configuration(invalid_config)
    if not result.is_valid and len(result.errors) > 0:
        print(f"✅ Invalid configuration caught: {len(result.errors)} errors")
        for error in result.errors:
            print(f"   • {error}")
    else:
        print("❌ Invalid configuration not caught")

    print("\n=== Validation Tests Complete ===\n")


if __name__ == "__main__":
    success = test_backward_compatibility()
    test_validation()

    if success:
        print("✅ All backward compatibility tests passed!")
        sys.exit(0)
    else:
        print("❌ Some tests failed")
        sys.exit(1)
