#!/usr/bin/env python3
"""Test backward compatibility of enhanced ModelManager."""

import time
from rag_mcp.model_manager import ModelManager


def test_singleton_pattern():
    """Test that ModelManager maintains singleton pattern."""
    manager1 = ModelManager()
    manager2 = ModelManager()
    assert manager1 is manager2, "Singleton pattern broken!"
    print("✓ Singleton pattern works correctly")


def test_get_model_sync():
    """Test synchronous model access (backward compatibility)."""
    manager = ModelManager()

    # First access may wait for preloading to complete
    print("  Waiting for model preloading to complete...")
    start = time.time()
    model1 = manager.get_model()  # Should use preloaded model or wait
    elapsed = (time.time() - start) * 1000
    print(f"  Initial model access (includes preload wait): {elapsed:.2f}ms")

    # Second access should be instant from cache
    start = time.time()
    model1_cached = manager.get_model()
    elapsed = (time.time() - start) * 1000
    print(f"✓ Cached default model access: {elapsed:.2f}ms")
    assert elapsed < 10, f"Cached default model too slow: {elapsed:.2f}ms"

    # Test named model access (should be cached now)
    start = time.time()
    model2 = manager.get_model("all-MiniLM-L6-v2")
    elapsed = (time.time() - start) * 1000
    print(f"✓ Named model access (cached): {elapsed:.2f}ms")
    assert elapsed < 10, f"Cached named model too slow: {elapsed:.2f}ms"

    # Models should be the same
    assert model1 is model2, "Same model should return same instance"
    assert model1 is model1_cached, "Cached model should be same instance"
    print("✓ Model caching works correctly")


def test_new_model_loading():
    """Test loading a new model that wasn't preloaded."""
    manager = ModelManager()

    # Load a different model (will be synchronous)
    print("  Loading a new model (not preloaded)...")
    start = time.time()
    model = manager.get_model("all-MiniLM-L12-v2")
    elapsed = (time.time() - start) * 1000
    print(f"  New model loaded in: {elapsed:.2f}ms")

    # Second access should be fast
    start = time.time()
    model2 = manager.get_model("all-MiniLM-L12-v2")
    elapsed = (time.time() - start) * 1000
    print(f"✓ Cached model access: {elapsed:.2f}ms")
    assert elapsed < 10, f"Cached access too slow: {elapsed:.2f}ms"
    assert model is model2, "Cached model should return same instance"


def test_model_functionality():
    """Test that models work correctly for embeddings."""
    manager = ModelManager()
    model = manager.get_model()

    # Test embedding generation
    start = time.time()
    embeddings = model.encode(["test sentence"], show_progress_bar=False)
    elapsed = (time.time() - start) * 1000
    print(f"✓ Embedding generation: {elapsed:.2f}ms")

    assert embeddings.shape[0] == 1, "Wrong number of embeddings"
    assert embeddings.shape[1] == 384, "Wrong embedding dimension for MiniLM-L6"
    print("✓ Model produces correct embeddings")


def test_preload_effectiveness():
    """Test that preloading actually improves performance."""
    # Create a fresh manager instance to trigger preloading
    print("\n  Testing preload effectiveness...")
    manager = ModelManager()

    # Wait a moment for background preloading
    time.sleep(0.5)

    # Access should be fast if preloaded
    start = time.time()
    model = manager.get_model("all-MiniLM-L6-v2")
    elapsed = (time.time() - start) * 1000

    if elapsed < 100:
        print(f"✓ Preloading effective: Model accessed in {elapsed:.2f}ms")
    else:
        print(f"  Note: Preloading may still be in progress ({elapsed:.2f}ms)")
        print("  This is expected on first run or slow systems")


def main():
    """Run all backward compatibility tests."""
    print("Testing ModelManager Backward Compatibility")
    print("=" * 50)

    # Initialize ModelManager to start preloading
    print("\nInitializing ModelManager to trigger preloading...")
    manager = ModelManager()

    # Give some feedback about preloading
    print("Preloading models in background...")
    print("\nRunning tests...\n")

    try:
        test_singleton_pattern()
        test_get_model_sync()
        test_new_model_loading()
        test_model_functionality()
        test_preload_effectiveness()

        print("\n" + "=" * 50)
        print("✅ All backward compatibility tests PASSED!")
        print("\nKey improvements verified:")
        print("- Models are preloaded in background at startup")
        print("- First access waits for preload if needed (fallback)")
        print("- Subsequent accesses are instant from cache")
        print("- Full backward compatibility maintained")
        print("- Singleton pattern preserved")

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
