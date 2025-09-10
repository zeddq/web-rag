"""Central ModelManager for shared SentenceTransformer models.

Implements a thread-safe singleton that preloads and caches models so the
first call to `CollectionSelector.select_collection()` does **not** incur
the multi-second model-loading penalty measured in performance tests.

This implementation uses background preloading to initialize models at startup,
reducing model loading time from ~3000ms to 0ms for preloaded models.
It includes warm-up embeddings to prevent first-request delays.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict

from sentence_transformers import SentenceTransformer

DEFAULT_MODEL = "all-MiniLM-L6-v2"

logger = logging.getLogger(__name__)


class ModelManager:
    """Thread-safe singleton managing a pool of SentenceTransformer models.

    Features:
    - Singleton pattern with thread-safe model pool
    - Asynchronous background model preloading during initialization
    - Model warm-up with sample embeddings
    - Thread-safe access with locks
    - Fallback to synchronous loading if async fails
    """

    _instance: "ModelManager | None" = None
    _models: Dict[str, SentenceTransformer]
    _lock = threading.Lock()
    _preload_threads: Dict[str, threading.Thread] = {}

    def __new__(cls) -> "ModelManager":  # noqa: D401
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._models = {}
                    cls._instance._preload_threads = {}
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Preload models on initialization.

        This method is called once during singleton creation to start
        background preloading of commonly used models.
        """
        logger.info("Initializing ModelManager with background preloading")

        # Preload the default model in background
        self._preload_model(DEFAULT_MODEL)

        logger.info(f"Started preloading default model: {DEFAULT_MODEL}")

    def _preload_model(self, model_name: str):
        """Preload model asynchronously in a background thread.

        Args:
            model_name: Name of the model to preload
        """
        if model_name in self._models or model_name in self._preload_threads:
            # Model already loaded or preloading
            return

        def load():
            """Background loading function."""
            try:
                logger.info(f"Starting background preload of model: {model_name}")

                # Load the model
                model = SentenceTransformer(model_name)

                # Warm up with sample embedding to prevent first-request delays
                model.encode(["warmup"], show_progress_bar=False)

                # Store the loaded model
                with self._lock:
                    self._models[model_name] = model
                    # Remove from preload threads dict
                    if model_name in self._preload_threads:
                        del self._preload_threads[model_name]

                logger.info(f"Successfully preloaded model: {model_name}")

            except Exception as e:
                logger.error(f"Failed to preload model {model_name}: {e}")
                # Clean up on failure
                with self._lock:
                    if model_name in self._preload_threads:
                        del self._preload_threads[model_name]

        # Create and start daemon thread for background loading
        thread = threading.Thread(
            target=load, daemon=True, name=f"preload-{model_name}"
        )
        self._preload_threads[model_name] = thread
        thread.start()

    # --------------------------------------------------------------------- #
    # Public helpers
    # --------------------------------------------------------------------- #

    def get_model(self, model_name: str | None = None) -> SentenceTransformer:
        """Return an already-loaded model or load it synchronously.

        This method provides fast access to preloaded models and falls back
        to synchronous loading if the model hasn't been preloaded yet.

        Args:
            model_name: HuggingFace SentenceTransformer model name.
                        If omitted, falls back to DEFAULT_MODEL.

        Returns:
            SentenceTransformer model instance
        """
        model_name = model_name or DEFAULT_MODEL

        # Fast path – model already cached
        if model_name in self._models:
            logger.debug(f"Model {model_name} retrieved from cache (preloaded)")
            return self._models[model_name]

        # Check if model is currently being preloaded
        if model_name in self._preload_threads:
            thread = self._preload_threads[model_name]
            if thread.is_alive():
                logger.info(
                    f"Waiting for background preload of {model_name} to complete"
                )
                # Wait for preload to complete (with timeout to prevent hanging)
                thread.join(timeout=30.0)

                # Check if model was successfully loaded
                if model_name in self._models:
                    logger.debug(
                        f"Model {model_name} retrieved after waiting for preload"
                    )
                    return self._models[model_name]

        # Fallback: load synchronously if not preloaded or preload failed
        logger.warning(f"Model {model_name} not preloaded, loading synchronously")
        with self._lock:
            # Double-check inside the lock
            if model_name not in self._models:
                logger.info(f"Loading model {model_name} synchronously")
                model = SentenceTransformer(model_name)
                # Warm up the model
                model.encode(["warmup"], show_progress_bar=False)
                self._models[model_name] = model
                logger.info(f"Model {model_name} loaded successfully")

        return self._models[model_name]
