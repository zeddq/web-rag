#!/usr/bin/env python3
"""
Debug script for investigating specific issues found in end-to-end tests.
This script diagnoses and potentially fixes issues discovered during validation.
"""

import sys
import os
import time
from typing import Any, Dict

# Set the multi-collection config path to our example config before importing
os.environ["MULTI_COLLECTION_CONFIG_PATH"] = "ingest/multi-collection.example.yml"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def investigate_mcp_tool_field_names():
    """Investigate the MCP tool field naming issue."""
    print("=" * 60)
    print("INVESTIGATING MCP TOOL FIELD NAMES")
    print("=" * 60)

    try:
        from rag_mcp.server import get_collection_info

        print("=== Testing get_collection_info return structure ===")
        result = get_collection_info("roo")

        print(f"✅ get_collection_info returned successfully")
        print(f"Type: {type(result)}")
        print(
            f'Keys: {list(result.keys()) if isinstance(result, dict) else "Not a dict"}'
        )

        # Check for expected fields
        expected_fields = ["document_count", "statistics", "name", "id"]
        found_fields = []
        missing_fields = []

        for field in expected_fields:
            if field in result:
                found_fields.append(field)
                print(f"   ✅ Found field: {field} = {result[field]}")
            else:
                missing_fields.append(field)
                print(f"   ❌ Missing field: {field}")

        # Look for alternative field names
        print(f"\n=== Available fields analysis ===")
        if isinstance(result, dict):
            for key, value in result.items():
                if isinstance(value, dict):
                    print(
                        f"   {key}: {type(value).__name__} with keys: {list(value.keys())}"
                    )
                else:
                    print(f"   {key}: {type(value).__name__} = {value}")

        # Specific check for document count location
        if "statistics" in result and isinstance(result["statistics"], dict):
            stats = result["statistics"]
            if "document_count" in stats:
                print(
                    f'   🔍 Found document_count in statistics: {stats["document_count"]}'
                )
            else:
                print(f"   🔍 Statistics keys: {list(stats.keys())}")

        return True, result

    except Exception as e:
        print(f"❌ get_collection_info investigation failed: {e}")
        import traceback

        traceback.print_exc()
        return False, None


def investigate_performance_issue():
    """Investigate collection selection performance."""
    print("\n" + "=" * 60)
    print("INVESTIGATING COLLECTION SELECTION PERFORMANCE")
    print("=" * 60)

    try:
        from rag_mcp.server import select_collection

        # Test multiple queries and measure timing
        test_queries = [
            "jujutsu version control",
            "python programming language",
            "fastapi web framework",
            "simple test query",
        ]

        print("=== Performance measurement ===")
        times = []

        for i, query in enumerate(test_queries):
            print(f'Testing query {i+1}: "{query}"')

            start_time = time.time()
            result = select_collection(query)
            end_time = time.time()

            elapsed_ms = (end_time - start_time) * 1000
            times.append(elapsed_ms)

            print(f"   Time: {elapsed_ms:.2f}ms")
            print(f'   Selected: {result.get("collection_id", "None")}')
            print(f'   Confidence: {result.get("confidence", 0):.3f}')
            print()

        avg_time = sum(times) / len(times)
        max_time = max(times)
        min_time = min(times)

        print(f"Performance summary:")
        print(f"   Average time: {avg_time:.2f}ms")
        print(f"   Maximum time: {max_time:.2f}ms")
        print(f"   Minimum time: {min_time:.2f}ms")
        print(f"   Expected: < 1000ms")

        performance_issue = max_time > 1000
        if performance_issue:
            print(f"   ❌ Performance issue detected: {max_time:.2f}ms > 1000ms")
        else:
            print(f"   ✅ Performance is acceptable")

        return not performance_issue, times

    except Exception as e:
        print(f"❌ Performance investigation failed: {e}")
        import traceback

        traceback.print_exc()
        return False, []


def investigate_confidence_type_issue():
    """Investigate confidence field type issue."""
    print("\n" + "=" * 60)
    print("INVESTIGATING CONFIDENCE TYPE ISSUE")
    print("=" * 60)

    try:
        from rag_mcp.collection_selector import create_selector
        from rag_mcp.config import load_config

        print("=== Testing collection selector confidence types ===")
        config = load_config("ingest/multi-collection.example.yml")
        selector = create_selector(config)

        test_queries = [
            "valid query with results",
            "jujutsu version control rebase",
            "very obscure query that might not match anything",
            "",  # Empty query edge case
        ]

        for query in test_queries:
            print(f'Testing query: "{query}"')

            try:
                selection = selector.select_collection(query)

                print(f"   Selection result type: {type(selection)}")
                print(f"   Selection attributes: {dir(selection)}")

                # Check confidence field
                if hasattr(selection, "confidence"):
                    confidence = selection.confidence
                    print(f"   Confidence value: {confidence}")
                    print(f"   Confidence type: {type(confidence)}")
                    print(f"   Is float: {isinstance(confidence, float)}")
                    print(f"   Is number: {isinstance(confidence, (int, float))}")
                else:
                    print(f"   ❌ No confidence attribute found")

                # Check other key attributes
                key_attrs = ["collection_id", "is_successful", "reasoning"]
                for attr in key_attrs:
                    if hasattr(selection, attr):
                        value = getattr(selection, attr)
                        print(f"   {attr}: {value} (type: {type(value).__name__})")
                    else:
                        print(f"   ❌ Missing attribute: {attr}")

                print()

            except Exception as e:
                print(f"   ❌ Query failed: {e}")
                print()
                continue

        return True

    except Exception as e:
        print(f"❌ Confidence investigation failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def investigate_test_configuration_mismatch():
    """Check if test configuration matches actual available collections."""
    print("\n" + "=" * 60)
    print("INVESTIGATING TEST CONFIGURATION MISMATCH")
    print("=" * 60)

    try:
        from rag_mcp.config import load_config
        from rag_mcp.server import get_state

        print("=== Comparing expected vs actual collections ===")

        # Load config directly
        config = load_config("ingest/multi-collection.example.yml")
        config_collections = list(config.collections.keys())
        print(f"Config collections: {config_collections}")

        # Get server state collections
        state = get_state()
        server_collections = list(state.collections.keys())
        print(f"Server collections: {server_collections}")

        # Check if test is looking for collections that don't exist
        test_expected_collections = ["jj_docs", "langchain_docs", "python_docs"]
        actual_collections = server_collections

        print(f"Test expects: {test_expected_collections}")
        print(f"Actually available: {actual_collections}")

        missing_collections = [
            c for c in test_expected_collections if c not in actual_collections
        ]
        extra_collections = [
            c for c in actual_collections if c not in test_expected_collections
        ]

        if missing_collections:
            print(f"❌ Missing collections: {missing_collections}")
        if extra_collections:
            print(f"ℹ️  Extra collections: {extra_collections}")

        if not missing_collections:
            print(f"✅ All expected collections are available")

        # Check individual collection details
        print(f"\n=== Available collection details ===")
        for coll_id in actual_collections:
            coll_instance = state.get_collection(coll_id)
            if coll_instance:
                config = coll_instance.config
                print(f"{coll_id}:")
                print(f"   Name: {config.name}")
                print(f"   Domain: {config.domain}")
                print(f"   Tags: {config.tags}")
                print(f"   Has data: {coll_instance.has_data()}")
                print(f"   Document count: {coll_instance.get_document_count()}")
                print()

        return len(missing_collections) == 0

    except Exception as e:
        print(f"❌ Configuration mismatch investigation failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("Investigating Issues Found in End-to-End Tests")
    print("=" * 60)

    # Run all investigations
    issues_found = []

    print("\n1. MCP Tool Field Names Issue")
    field_ok, mcp_result = investigate_mcp_tool_field_names()
    if not field_ok:
        issues_found.append("MCP tool field names")

    print("\n2. Performance Issue")
    perf_ok, perf_times = investigate_performance_issue()
    if not perf_ok:
        issues_found.append("Collection selection performance")

    print("\n3. Confidence Type Issue")
    conf_ok = investigate_confidence_type_issue()
    if not conf_ok:
        issues_found.append("Selection confidence type")

    print("\n4. Test Configuration Mismatch")
    config_ok = investigate_test_configuration_mismatch()
    if not config_ok:
        issues_found.append("Test configuration mismatch")

    # Summary
    print("\n" + "=" * 60)
    print("INVESTIGATION SUMMARY")
    print("=" * 60)

    if not issues_found:
        print("✅ All investigations completed successfully")
        print("   The issues may be related to test expectations vs implementation")
    else:
        print("❌ Issues found that need attention:")
        for i, issue in enumerate(issues_found, 1):
            print(f"   {i}. {issue}")

    print(f'\nOverall result: {"✅ GOOD" if not issues_found else "⚠️ NEEDS ATTENTION"}')
    sys.exit(0 if not issues_found else 1)
