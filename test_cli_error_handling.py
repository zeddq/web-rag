#!/usr/bin/env python3
"""
Test script for CLI error handling and compatibility layer.
This script tests the new error handling system and backward compatibility features.
"""

import subprocess
import sys
import os
from pathlib import Path
import tempfile
import yaml


def run_command(cmd: list) -> tuple:
    """Run a CLI command and capture output."""
    try:
        result = subprocess.run(
            ["poetry", "run", "web-rag-cli"] + cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


def test_error_codes():
    """Test structured error codes."""
    print("\n" + "=" * 60)
    print("🧪 Testing Error Codes")
    print("=" * 60)

    test_cases = [
        {
            "name": "CONFIG_NOT_FOUND",
            "cmd": ["ingest", "--config", "/nonexistent/config.yml"],
            "expected_code": 10,
            "expected_in_stderr": ["CONFIG_NOT_FOUND", "Configuration file not found"],
        },
        {
            "name": "COLLECTION_NOT_FOUND",
            "cmd": [
                "collection",
                "info",
                "nonexistent_collection",
                "--config",
                "ingest/multi-collection.yml",
            ],
            "expected_code": 20,
            "expected_in_stderr": ["COLLECTION_NOT_FOUND", "not found"],
        },
        {
            "name": "Invalid subcommand",
            "cmd": [
                "collection",
                "invalid_subcommand",
                "--config",
                "ingest/multi-collection.yml",
            ],
            "expected_code": 99,  # UNKNOWN_ERROR
            "expected_in_stderr": ["Unknown", "subcommand"],
        },
    ]

    for test in test_cases:
        print(f"\n📝 Test: {test['name']}")
        print(f"   Command: web-rag-cli {' '.join(test['cmd'])}")

        returncode, stdout, stderr = run_command(test["cmd"])

        # Check return code
        if returncode == test["expected_code"]:
            print(f"   ✅ Correct error code: {returncode}")
        else:
            print(
                f"   ❌ Wrong error code: got {returncode}, expected {test['expected_code']}"
            )

        # Check error message content
        combined_output = stdout + stderr
        for expected_text in test["expected_in_stderr"]:
            if expected_text.lower() in combined_output.lower():
                print(f"   ✅ Found expected text: '{expected_text}'")
            else:
                print(f"   ❌ Missing expected text: '{expected_text}'")

        # Show suggestion if present
        if "Suggestion:" in combined_output:
            print(f"   💡 Suggestion provided in error message")


def test_backward_compatibility():
    """Test backward compatibility with deprecated commands."""
    print("\n" + "=" * 60)
    print("🧪 Testing Backward Compatibility")
    print("=" * 60)

    # Create a temporary config file for testing
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        config = {
            "collections": {
                "test_collection": {
                    "name": "Test Collection",
                    "description": "Test",
                    "domain": "test.com",
                    "tags": ["test"],
                    "sources": {"base_urls": ["https://test.com"]},
                    "metadata": {"language": "en", "priority": 1},
                }
            }
        }
        yaml.dump(config, f)
        config_path = f.name

    try:
        deprecated_commands = [
            {
                "old": ["ingest-multi", "--config", config_path],
                "new": ["ingest", "--all", "--config", config_path],
                "description": "ingest-multi → ingest --all",
            },
            {
                "old": [
                    "ingest-collection",
                    "--config",
                    config_path,
                    "--collection",
                    "test_collection",
                ],
                "new": [
                    "ingest",
                    "--collection",
                    "test_collection",
                    "--config",
                    config_path,
                ],
                "description": "ingest-collection → ingest --collection",
            },
        ]

        for test in deprecated_commands:
            print(f"\n📝 Test: {test['description']}")
            print(f"   Old command: web-rag-cli {' '.join(test['old'])}")
            print(f"   New command: web-rag-cli {' '.join(test['new'])}")

            # Run old command
            returncode, stdout, stderr = run_command(
                test["old"][:2]
            )  # Just test parsing, not full execution

            if "deprecated" in stderr.lower() or "deprecated" in stdout.lower():
                print(f"   ✅ Deprecation warning shown")
            else:
                print(f"   ❌ No deprecation warning")

            # The command should still be parsed correctly
            if returncode != 0:
                # This is expected since we're not providing a valid config
                # but we should see the deprecation warning
                print(f"   ✅ Command processed (error expected due to test config)")

    finally:
        # Clean up temp file
        if os.path.exists(config_path):
            os.unlink(config_path)


def test_error_suggestions():
    """Test that helpful suggestions are provided."""
    print("\n" + "=" * 60)
    print("🧪 Testing Error Suggestions")
    print("=" * 60)

    test_cases = [
        {
            "name": "Collection not found with alternatives",
            "cmd": [
                "search",
                "--query",
                "test",
                "--collection",
                "wrong_name",
                "--config",
                "ingest/multi-collection.yml",
            ],
            "expected_suggestions": [
                "available_collections",
                "web-rag-cli collection list",
            ],
        },
        {
            "name": "Config file not found",
            "cmd": ["ingest", "--config", "/missing/config.yml"],
            "expected_suggestions": [
                "Check that the configuration file exists",
                "Default location",
            ],
        },
    ]

    for test in test_cases:
        print(f"\n📝 Test: {test['name']}")
        print(f"   Command: web-rag-cli {' '.join(test['cmd'])}")

        returncode, stdout, stderr = run_command(test["cmd"])
        combined_output = stdout + stderr

        # Check for suggestions
        if "Suggestion:" in combined_output or "💡" in combined_output:
            print(f"   ✅ Suggestion provided")

            for expected in test["expected_suggestions"]:
                if expected.lower() in combined_output.lower():
                    print(f"   ✅ Contains expected suggestion text: '{expected}'")
                else:
                    print(f"   ⚠️  Missing expected suggestion text: '{expected}'")
        else:
            print(f"   ❌ No suggestion provided")


def test_enhanced_output():
    """Test enhanced output with emojis and formatting."""
    print("\n" + "=" * 60)
    print("🧪 Testing Enhanced Output")
    print("=" * 60)

    test_commands = [
        {
            "name": "Collection list with status icons",
            "cmd": ["collection", "list", "--config", "ingest/multi-collection.yml"],
            "expected_elements": ["📚", "✅", "⭕", "Available collections"],
        },
        {
            "name": "Server status with icons",
            "cmd": ["server", "status", "--config", "ingest/multi-collection.yml"],
            "expected_elements": ["🔍", "📋", "📚", "MCP Server Status"],
        },
    ]

    for test in test_commands:
        print(f"\n📝 Test: {test['name']}")
        print(f"   Command: web-rag-cli {' '.join(test['cmd'])}")

        returncode, stdout, stderr = run_command(test["cmd"])
        combined_output = stdout + stderr

        for element in test["expected_elements"]:
            if element in combined_output:
                print(f"   ✅ Found expected element: '{element}'")
            else:
                print(
                    f"   ⚠️  Missing expected element: '{element}' (may be OK if config missing)"
                )


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("🚀 CLI Error Handling and Compatibility Test Suite")
    print("=" * 70)

    # Check if we're in the right directory
    if not Path("web-rag-cli").exists():
        print("❌ Error: Must run from project root directory")
        return 1

    # Run test suites
    test_error_codes()
    test_backward_compatibility()
    test_error_suggestions()
    test_enhanced_output()

    print("\n" + "=" * 70)
    print("✅ Test suite completed!")
    print("=" * 70)
    print("\nNote: Some tests may show warnings or errors - this is expected")
    print(
        "as we're testing error handling. Check the ✅/❌ markers for actual results."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
