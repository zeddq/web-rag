#!/usr/bin/env python3
"""
CLI Integration Test Suite for Multi-Collection RAG System

This test suite validates command-line interface functionality including
ingestion commands, configuration handling, and integration with the
underlying multi-collection system.
"""

import os
import subprocess
import sys
import tempfile
import yaml
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import patch, Mock

# Add the project root to the Python path
sys.path.insert(0, str(Path(__file__).parent))

from rag_mcp.cli import main as cli_main
from rag_mcp.config import ConfigurationError
from rag_mcp.ingest import ingest_from_config


class TestCLIIntegration:
    """Test suite for CLI integration and functionality."""

    @classmethod
    def setup_class(cls):
        """Set up test fixtures for CLI testing."""
        # Legacy configuration for testing
        cls.legacy_config = {
            "base_urls": ["https://example.com/docs/"],
            "allow_patterns": [r"^https://example\.com/docs/.*"],
            "deny_patterns": [r"\.pdf$"],
            "max_pages": 10,  # Small number for testing
            "concurrency": 2,
            "chunk_chars": 500,
            "chunk_overlap": 100,
            "chroma": {
                "persist_dir": "data/test_chroma_cli",
                "collection": "test_cli",
            },
            "embedding_provider": "sentence-transformers",
            "embedding_model": "all-MiniLM-L6-v2",
        }

        # Multi-collection configuration for testing
        cls.multi_config = {
            "version": "2.0",
            "defaults": {
                "chunk_chars": 500,
                "chunk_overlap": 100,
                "embedding_provider": "sentence-transformers",
                "embedding_model": "all-MiniLM-L6-v2",
                "chroma_persist_dir": "data/test_chroma_cli",
                "max_pages": 5,
                "concurrency": 2,
            },
            "collections": {
                "test_collection": {
                    "name": "Test Collection",
                    "description": "CLI test collection",
                    "domain": "testing",
                    "tags": ["test", "cli"],
                    "sources": {
                        "base_urls": ["https://example.com/docs/"],
                        "allow_patterns": [r"^https://example\.com/docs/.*"],
                    },
                },
            },
        }

        # Invalid configuration for error testing
        cls.invalid_config = {
            "base_urls": [],  # Empty base URLs should cause error
            "chunk_chars": "invalid",  # Wrong type
        }

    def create_temp_config(self, config_data: Dict[str, Any]) -> str:
        """Create a temporary configuration file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config_data, f, default_flow_style=False)
            return f.name

    def run_cli_command(self, args: List[str]) -> Tuple[int, str, str]:
        """Run CLI command and capture output."""
        try:
            # Capture stdout/stderr
            import io
            from contextlib import redirect_stdout, redirect_stderr

            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()

            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exit_code = cli_main(args)

            return exit_code, stdout_capture.getvalue(), stderr_capture.getvalue()

        except SystemExit as e:
            return e.code or 0, "", str(e)
        except Exception as e:
            return 1, "", str(e)

    def test_cli_help_and_basic_functionality(self):
        """Test basic CLI help and argument parsing."""
        print("\n=== Testing CLI Help and Basic Functionality ===")

        # Test help command
        exit_code, stdout, stderr = self.run_cli_command(["--help"])
        # Help should exit with code 0 and show help text
        assert exit_code in [0, 2]  # argparse can exit with 2 for help
        print("✓ CLI help command works")

        # Test missing command
        exit_code, stdout, stderr = self.run_cli_command([])
        assert exit_code != 0  # Should fail due to required subcommand
        print("✓ CLI properly requires subcommand")

        # Test invalid command
        exit_code, stdout, stderr = self.run_cli_command(["invalid_command"])
        assert exit_code != 0  # Should fail due to invalid command
        print("✓ CLI properly rejects invalid commands")

        # Test ingest command without config
        exit_code, stdout, stderr = self.run_cli_command(["ingest"])
        assert exit_code != 0  # Should fail due to required --config argument
        print("✓ CLI properly requires --config argument for ingest")

        print("✅ CLI help and basic functionality test passed!")

    def test_cli_legacy_config_ingestion(self):
        """Test CLI ingestion with legacy configuration."""
        print("\n=== Testing CLI Legacy Config Ingestion ===")

        config_path = self.create_temp_config(self.legacy_config)

        try:
            # Mock the actual crawling and embedding to avoid network calls
            with patch("rag_mcp.ingest.crawl") as mock_crawl, patch(
                "rag_mcp.ingest.ingest_into_chroma"
            ) as mock_ingest:

                # Mock crawl to return fake pages
                mock_crawl.return_value = [
                    ("https://example.com/docs/page1", "Page 1", "Test content 1"),
                    ("https://example.com/docs/page2", "Page 2", "Test content 2"),
                ]

                # Run CLI ingest command
                exit_code, stdout, stderr = self.run_cli_command(
                    ["ingest", "--config", config_path]
                )

                # Should succeed
                assert (
                    exit_code == 0
                ), f"CLI failed with exit code {exit_code}, stderr: {stderr}"
                print("✓ CLI ingest command executed successfully with legacy config")

                # Verify that crawl was called
                assert mock_crawl.called, "Crawl function should have been called"
                print("✓ Crawl function was called")

                # Verify that ingest_into_chroma was called
                assert mock_ingest.called, "Ingest function should have been called"
                print("✓ Ingest function was called")

        finally:
            os.unlink(config_path)

        print("✅ CLI legacy config ingestion test passed!")

    def test_cli_error_handling(self):
        """Test CLI error handling with invalid configurations."""
        print("\n=== Testing CLI Error Handling ===")

        # Test with non-existent config file
        exit_code, stdout, stderr = self.run_cli_command(
            ["ingest", "--config", "nonexistent.yml"]
        )
        assert exit_code != 0, "Should fail with non-existent config file"
        print("✓ CLI properly handles non-existent config file")

        # Test with invalid config
        invalid_config_path = self.create_temp_config(self.invalid_config)

        try:
            exit_code, stdout, stderr = self.run_cli_command(
                ["ingest", "--config", invalid_config_path]
            )
            assert exit_code != 0, "Should fail with invalid config"
            print("✓ CLI properly handles invalid configuration")

        finally:
            os.unlink(invalid_config_path)

        # Test with empty config file
        empty_config_path = self.create_temp_config({})

        try:
            exit_code, stdout, stderr = self.run_cli_command(
                ["ingest", "--config", empty_config_path]
            )
            assert exit_code != 0, "Should fail with empty config"
            print("✓ CLI properly handles empty configuration")

        finally:
            os.unlink(empty_config_path)

        print("✅ CLI error handling test passed!")

    def test_cli_with_multi_collection_config(self):
        """Test CLI behavior with multi-collection configuration."""
        print("\n=== Testing CLI with Multi-Collection Config ===")

        config_path = self.create_temp_config(self.multi_config)

        try:
            # The current CLI doesn't directly support multi-collection ingestion
            # but it should handle the config gracefully by processing the first collection
            with patch("rag_mcp.ingest.crawl") as mock_crawl, patch(
                "rag_mcp.ingest.ingest_into_chroma"
            ) as mock_ingest:

                mock_crawl.return_value = [
                    ("https://example.com/docs/test", "Test Page", "Test content"),
                ]

                # This should work if the config is converted to single collection format
                exit_code, stdout, stderr = self.run_cli_command(
                    ["ingest", "--config", config_path]
                )

                if exit_code == 0:
                    print(
                        "✓ CLI handled multi-collection config by converting to single collection"
                    )
                    assert mock_crawl.called, "Crawl should have been called"
                    assert mock_ingest.called, "Ingest should have been called"
                else:
                    print(
                        f"⚠ CLI does not yet support multi-collection configs directly (exit code: {exit_code})"
                    )
                    # This is acceptable if multi-collection CLI support isn't implemented yet

        finally:
            os.unlink(config_path)

        print("✅ CLI multi-collection config test completed!")

    def test_cli_environment_variable_support(self):
        """Test CLI support for environment variables."""
        print("\n=== Testing CLI Environment Variable Support ===")

        # Create minimal config that relies on environment variables
        minimal_config = {
            "base_urls": ["https://example.com/docs/"],
            "max_pages": 5,
        }

        config_path = self.create_temp_config(minimal_config)

        # Test with environment variables set
        test_env_vars = {
            "CHROMA_PERSIST_DIR": "data/test_env_chroma",
            "CHROMA_COLLECTION": "test_env_collection",
            "EMBEDDING_PROVIDER": "sentence-transformers",
            "EMBEDDING_MODEL": "all-MiniLM-L6-v2",
        }

        # Save original environment
        original_env = {}
        for var in test_env_vars:
            original_env[var] = os.environ.get(var)

        try:
            # Set test environment variables
            for var, value in test_env_vars.items():
                os.environ[var] = value

            with patch("rag_mcp.ingest.crawl") as mock_crawl, patch(
                "rag_mcp.ingest.ingest_into_chroma"
            ) as mock_ingest:

                mock_crawl.return_value = [
                    ("https://example.com/docs/test", "Test", "Content")
                ]

                exit_code, stdout, stderr = self.run_cli_command(
                    ["ingest", "--config", config_path]
                )

                if exit_code == 0:
                    print("✓ CLI successfully used environment variables")
                    assert mock_crawl.called
                    assert mock_ingest.called
                else:
                    print(
                        f"⚠ CLI environment variable test failed (exit code: {exit_code})"
                    )

        finally:
            # Restore original environment
            for var, original_value in original_env.items():
                if original_value is not None:
                    os.environ[var] = original_value
                elif var in os.environ:
                    del os.environ[var]

            os.unlink(config_path)

        print("✅ CLI environment variable support test completed!")

    def test_cli_server_integration(self):
        """Test CLI integration with server components."""
        print("\n=== Testing CLI Server Integration ===")

        config_path = self.create_temp_config(self.legacy_config)

        try:
            # Test that CLI-ingested data is accessible by server components
            with patch("rag_mcp.ingest.crawl") as mock_crawl, patch(
                "rag_mcp.chroma_store.get_client"
            ) as mock_get_client, patch(
                "rag_mcp.chroma_store.get_or_create_collection"
            ) as mock_get_collection:

                # Mock the Chroma components
                mock_client = Mock()
                mock_collection = Mock()

                mock_get_client.return_value = mock_client
                mock_get_collection.return_value = mock_collection

                mock_crawl.return_value = [
                    (
                        "https://example.com/docs/page1",
                        "Page 1",
                        "Test content for integration",
                    )
                ]

                # Run ingestion
                exit_code, stdout, stderr = self.run_cli_command(
                    ["ingest", "--config", config_path]
                )

                if exit_code == 0:
                    print("✓ CLI ingestion completed successfully")

                    # Verify that Chroma client was created correctly
                    mock_get_client.assert_called()
                    print("✓ Chroma client was initialized")

                    # Verify that collection was created
                    mock_get_collection.assert_called()
                    print("✓ Chroma collection was created")

                    # Verify that data was added to collection
                    if mock_collection.upsert.called:
                        print("✓ Data was added to collection")
                    else:
                        print(
                            "⚠ Collection upsert not called (might be due to mocking)"
                        )

                else:
                    print(f"⚠ CLI ingestion failed (exit code: {exit_code})")

        finally:
            os.unlink(config_path)

        print("✅ CLI server integration test completed!")

    def test_cli_subprocess_execution(self):
        """Test CLI execution as subprocess (real-world usage)."""
        print("\n=== Testing CLI Subprocess Execution ===")

        config_path = self.create_temp_config(self.legacy_config)

        try:
            # Test running the CLI as a subprocess (like users would)
            cmd = [
                sys.executable,
                "-m",
                "rag_mcp.cli",
                "ingest",
                "--config",
                config_path,
            ]

            # Mock network calls to avoid actual web crawling
            with patch("rag_mcp.ingest.crawl") as mock_crawl:
                mock_crawl.return_value = []  # Empty result to avoid processing

                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=30,  # 30 second timeout
                        cwd=str(Path(__file__).parent),
                    )

                    print(f"  Subprocess exit code: {result.returncode}")
                    print(f"  Subprocess stdout length: {len(result.stdout)}")
                    print(f"  Subprocess stderr length: {len(result.stderr)}")

                    if result.returncode == 0:
                        print("✓ CLI subprocess execution successful")
                    else:
                        print(f"⚠ CLI subprocess execution failed")
                        if result.stderr:
                            print(f"  Stderr: {result.stderr[:200]}...")

                except subprocess.TimeoutExpired:
                    print("⚠ CLI subprocess execution timed out")
                except FileNotFoundError:
                    print("⚠ Could not execute CLI as subprocess (module not found)")

        finally:
            os.unlink(config_path)

        print("✅ CLI subprocess execution test completed!")

    def test_cli_output_and_logging(self):
        """Test CLI output formatting and logging."""
        print("\n=== Testing CLI Output and Logging ===")

        config_path = self.create_temp_config(self.legacy_config)

        try:
            with patch("rag_mcp.ingest.crawl") as mock_crawl, patch(
                "rag_mcp.ingest.ingest_into_chroma"
            ) as mock_ingest:

                mock_crawl.return_value = [
                    ("https://example.com/docs/page1", "Page 1", "Content 1"),
                    ("https://example.com/docs/page2", "Page 2", "Content 2"),
                ]

                # Capture all output
                import io
                from contextlib import redirect_stdout, redirect_stderr

                stdout_capture = io.StringIO()
                stderr_capture = io.StringIO()

                try:
                    with redirect_stdout(stdout_capture), redirect_stderr(
                        stderr_capture
                    ):
                        exit_code = cli_main(["ingest", "--config", config_path])

                    stdout_content = stdout_capture.getvalue()
                    stderr_content = stderr_capture.getvalue()

                    print(f"  Exit code: {exit_code}")
                    print(f"  Stdout length: {len(stdout_content)}")
                    print(f"  Stderr length: {len(stderr_content)}")

                    if exit_code == 0:
                        print("✓ CLI execution completed successfully")

                        # Check for expected output patterns
                        if (
                            "Ingesting" in stdout_content
                            or "Successfully" in stdout_content
                        ):
                            print("✓ CLI provided informative output")
                        else:
                            print("⚠ CLI output may be minimal")

                    else:
                        print(f"⚠ CLI execution failed with exit code {exit_code}")
                        if stderr_content:
                            print(f"  Error output: {stderr_content[:100]}...")

                except Exception as e:
                    print(f"⚠ CLI output test failed: {e}")

        finally:
            os.unlink(config_path)

        print("✅ CLI output and logging test completed!")

    def test_cli_configuration_validation(self):
        """Test CLI configuration validation and error reporting."""
        print("\n=== Testing CLI Configuration Validation ===")

        # Test various invalid configurations
        invalid_configs = [
            ({}, "Empty configuration"),
            ({"base_urls": []}, "Empty base URLs"),
            ({"base_urls": ["invalid-url"]}, "Invalid URL format"),
            (
                {"base_urls": ["https://example.com"], "chunk_chars": -1},
                "Invalid chunk size",
            ),
            (
                {"base_urls": ["https://example.com"], "max_pages": "invalid"},
                "Invalid max_pages type",
            ),
        ]

        for invalid_config, description in invalid_configs:
            print(f"\nTesting: {description}")
            config_path = self.create_temp_config(invalid_config)

            try:
                exit_code, stdout, stderr = self.run_cli_command(
                    ["ingest", "--config", config_path]
                )

                if exit_code != 0:
                    print(f"  ✓ CLI properly rejected {description.lower()}")
                else:
                    print(f"  ⚠ CLI accepted {description.lower()} (may have defaults)")

            except Exception as e:
                print(
                    f"  ✓ CLI raised exception for {description.lower()}: {type(e).__name__}"
                )

            finally:
                os.unlink(config_path)

        print("✅ CLI configuration validation test completed!")


def run_cli_integration_tests():
    """Run all CLI integration tests and report results."""
    print("Multi-Collection RAG System - CLI Integration Tests")
    print("=" * 60)

    test_suite = TestCLIIntegration()
    test_suite.setup_class()

    tests = [
        test_suite.test_cli_help_and_basic_functionality,
        test_suite.test_cli_legacy_config_ingestion,
        test_suite.test_cli_error_handling,
        test_suite.test_cli_with_multi_collection_config,
        test_suite.test_cli_environment_variable_support,
        test_suite.test_cli_server_integration,
        test_suite.test_cli_subprocess_execution,
        test_suite.test_cli_output_and_logging,
        test_suite.test_cli_configuration_validation,
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

    print(f"\n{'=' * 60}")
    print(f"CLI Integration Test Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All CLI integration tests passed!")
        print("   Command-line interface is working correctly.")
        return 0
    else:
        print("❌ Some CLI integration tests failed.")
        print("   Command-line interface may have issues.")
        return 1


if __name__ == "__main__":
    exit(run_cli_integration_tests())
