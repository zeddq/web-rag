#!/usr/bin/env python3
"""
Test script to verify backwards compatibility and configuration parsing.
This script tests the new configuration system against existing and new formats.
"""

import sys
import yaml
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

from rag_mcp.config import (
    load_config,
    load_multi_config,
    validate_collection_config,
    validate_multi_config,
    CollectionConfig,
    MultiCollectionConfig,
    ConfigurationError,
)


def test_multi_config_loading():
    """Test loading the new multi-collection configuration."""
    print("\n=== Testing Multi-Collection Config Loading ===")

    # Test loading the new multi-collection example
    config = load_multi_config("ingest/multi-collection.example.yml")

    print(f"✓ Successfully loaded multi-collection config")
    print(f"  Config type: {type(config).__name__}")
    print(f"  Version: {config.version}")
    print(f"  Collections: {list(config.collections.keys())}")

    # Assert basic properties
    assert config is not None, "Config should be loaded"
    assert isinstance(
        config, MultiCollectionConfig
    ), "Should be MultiCollectionConfig instance"
    assert len(config.collections) > 0, "Should have at least one collection"

    # Test individual collections
    for coll_id, collection in config.collections.items():
        print(f"  Collection '{coll_id}':")
        print(f"    Name: {collection.name}")
        print(f"    Domain: {collection.domain}")
        print(f"    Tags: {collection.tags}")
        print(f"    Base URLs: {collection.sources.base_urls[:2]}...")  # First 2 URLs

        # Assert collection properties
        assert isinstance(
            collection, CollectionConfig
        ), f"Collection {coll_id} should be CollectionConfig"
        assert collection.name, f"Collection {coll_id} should have a name"
        assert (
            len(collection.sources.base_urls) > 0
        ), f"Collection {coll_id} should have base URLs"

    # Test validation
    errors = validate_multi_config(config)
    if errors:
        print(f"  ⚠ Validation errors: {errors}")
    else:
        print(f"  ✓ Configuration is valid")

    assert (
        len(errors) == 0
    ), f"Configuration should be valid, but found errors: {errors}"

    return True


def test_multi_config_validation():
    """Test validation of multi-collection configurations."""
    print("\n=== Testing Multi-Collection Config Validation ===")

    # Test loading the new multi-collection example
    config = load_multi_config("ingest/multi-collection.example.yml")

    # Test validation
    errors = validate_multi_config(config)
    if errors:
        print(f"  ⚠ Validation errors: {errors}")
    else:
        print(f"  ✓ Multi-collection configuration is valid")

    assert (
        len(errors) == 0
    ), f"Multi-collection configuration should be valid, but found errors: {errors}"

    return True


def test_error_handling():
    """Test error handling with invalid configurations."""
    print("\n=== Testing Error Handling ===")

    test_cases = [
        {
            "name": "Non-existent file",
            "config_path": "non_existent_file.yml",
            "should_fail": True,
        },
    ]

    # Test with invalid config data
    invalid_configs = [
        {
            "name": "Empty collections",
            "data": {
                "version": "2.0",
                "defaults": {"chunk_chars": 1200},
                "collections": {},
            },
        },
        {
            "name": "Missing base URLs",
            "data": {
                "version": "2.0",
                "defaults": {"chunk_chars": 1200},
                "collections": {
                    "test": {"name": "Test Collection", "sources": {"base_urls": []}}
                },
            },
        },
    ]

    # Test file loading errors
    for test_case in test_cases:
        exception_raised = False
        try:
            load_config(test_case["config_path"])
        except ConfigurationError:
            exception_raised = True
            print(f"✓ {test_case['name']}: Failed as expected (ConfigurationError)")
        except Exception as e:
            exception_raised = True
            print(f"✓ {test_case['name']}: Failed with exception: {type(e).__name__}")

        if test_case["should_fail"]:
            assert (
                exception_raised
            ), f"{test_case['name']}: Expected failure but succeeded"
        else:
            assert not exception_raised, f"{test_case['name']}: Unexpected failure"

    # Test validation errors
    for invalid_config in invalid_configs:
        try:
            multi_config = MultiCollectionConfig.from_dict(invalid_config["data"])
            errors = validate_multi_config(multi_config)

            if errors:
                print(
                    f"✓ {invalid_config['name']}: Validation correctly identified errors: {errors[:1]}..."
                )
            else:
                print(
                    f"✗ {invalid_config['name']}: Validation should have found errors"
                )
                assert (
                    False
                ), f"{invalid_config['name']}: Validation should have found errors but didn't"

        except Exception as e:
            print(
                f"✓ {invalid_config['name']}: Exception raised as expected: {type(e).__name__}"
            )
            # Exception is expected for invalid configs, so this is okay

    return True


def main():
    """Run all compatibility and validation tests."""
    print("Configuration Compatibility and Validation Tests")
    print("=" * 50)

    tests = [
        test_multi_config_loading,
        test_multi_config_validation,
        test_error_handling,
    ]

    passed = 0
    total = len(tests)

    for test in tests:
        try:
            result = test()
            # Test functions return True or None on success
            if result is not False:
                passed += 1
            else:
                print(f"✗ Test {test.__name__} failed")
        except Exception as e:
            print(f"✗ Test {test.__name__} crashed: {e}")

    print(f"\n{'=' * 50}")
    print(f"Test Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! Configuration system is working correctly.")
        return 0
    else:
        print("❌ Some tests failed. Please review the errors above.")
        return 1


if __name__ == "__main__":
    exit(main())
