"""Comprehensive test suite for collection selection logic."""

import pytest
from unittest.mock import Mock, patch
import numpy as np

from rag_mcp.config import (
    CollectionConfig,
    CollectionMetadata,
    CollectionSources,
    GlobalDefaults,
    MultiCollectionConfig,
)
from rag_mcp.collection_selector import (
    CollectionSelector,
    CollectionSelection,
    CollectionScore,
    create_selector,
)


@pytest.fixture
def sample_collections():
    """Create sample collection configurations for testing."""
    collections = {}

    # JJ Documentation Collection
    collections["jj_docs"] = CollectionConfig(
        id="jj_docs",
        name="JJ Documentation",
        description="Jujutsu VCS documentation and guides",
        domain="version-control",
        tags=["vcs", "jj", "jujutsu", "git-alternative"],
        sources=CollectionSources(
            base_urls=["https://jj-vcs.github.io/jj/latest/"],
            allow_patterns=[r"^https://jj-vcs\.github\.io/jj/latest/.*"],
        ),
        metadata=CollectionMetadata(priority=1, version="0.32.0"),
    )

    # Python Documentation Collection
    collections["python_docs"] = CollectionConfig(
        id="python_docs",
        name="Python Documentation",
        description="Official Python language documentation",
        domain="programming-language",
        tags=["python", "programming", "language", "stdlib"],
        sources=CollectionSources(
            base_urls=["https://docs.python.org/3/"],
            allow_patterns=[r"^https://docs\.python\.org/3/.*"],
        ),
        metadata=CollectionMetadata(priority=2, version="3.12"),
    )

    # LangChain Documentation Collection
    collections["langchain_docs"] = CollectionConfig(
        id="langchain_docs",
        name="LangChain Documentation",
        description="LangChain framework documentation for LLM applications",
        domain="ai-framework",
        tags=["langchain", "llm", "ai", "rag", "agents", "chains"],
        sources=CollectionSources(
            base_urls=["https://python.langchain.com/docs/"],
            allow_patterns=[r"^https://python\.langchain\.com/docs/.*"],
        ),
        metadata=CollectionMetadata(priority=1),
    )

    # FastAPI Documentation Collection
    collections["fastapi_docs"] = CollectionConfig(
        id="fastapi_docs",
        name="FastAPI Documentation",
        description="FastAPI web framework documentation",
        domain="web-framework",
        tags=["fastapi", "python", "web", "api", "async"],
        sources=CollectionSources(
            base_urls=["https://fastapi.tiangolo.com/"],
            allow_patterns=[r"^https://fastapi\.tiangolo\.com/.*"],
        ),
        metadata=CollectionMetadata(priority=2, version="0.104.0"),
    )

    return collections


@pytest.fixture
def multi_config(sample_collections):
    """Create multi-collection configuration for testing."""
    return MultiCollectionConfig(
        version="2.0",
        defaults=GlobalDefaults(),
        collections=sample_collections,
    )


@pytest.fixture
def selector(multi_config):
    """Create collection selector for testing."""
    return CollectionSelector(
        config=multi_config,
        confidence_threshold=0.4,
        semantic_weight=0.6,
        keyword_weight=0.4,
    )


class TestCollectionSelection:
    """Test CollectionSelection dataclass."""

    def test_successful_selection(self):
        """Test successful collection selection."""
        selection = CollectionSelection(
            collection_id="test_collection",
            confidence=0.8,
            reasoning="Test match",
        )

        assert selection.is_successful
        assert selection.collection_id == "test_collection"
        assert selection.confidence == 0.8

    def test_failed_selection(self):
        """Test failed collection selection."""
        selection = CollectionSelection(
            collection_id=None,
            confidence=0.2,
            reasoning="No match found",
        )

        assert not selection.is_successful
        assert selection.collection_id is None
        assert selection.confidence == 0.2

    def test_to_dict(self):
        """Test conversion to dictionary."""
        scores = [
            CollectionScore(
                collection_id="test_1",
                keyword_score=0.5,
                semantic_score=0.7,
                combined_score=0.6,
                reasoning="Test score",
            )
        ]

        selection = CollectionSelection(
            collection_id="test_1",
            confidence=0.6,
            reasoning="Best match",
            all_scores=scores,
        )

        result = selection.to_dict()

        assert result["collection_id"] == "test_1"
        assert result["confidence"] == 0.6
        assert result["is_successful"] is True
        assert len(result["all_scores"]) == 1
        assert result["all_scores"][0]["keyword_score"] == 0.5


class TestCollectionSelector:
    """Test CollectionSelector class."""

    def test_initialization(self, multi_config):
        """Test selector initialization."""
        selector = CollectionSelector(multi_config)

        assert selector.config == multi_config
        assert selector.confidence_threshold == 0.4
        assert selector.semantic_weight == 0.6
        assert selector.keyword_weight == 0.4
        assert len(selector._keyword_index) > 0

    def test_empty_query(self, selector):
        """Test handling of empty queries."""
        result = selector.select_collection("")

        assert not result.is_successful
        assert result.confidence == 0.0
        assert "Empty query" in result.reasoning

    def test_single_collection(self):
        """Test selection with only one collection available."""
        single_config = MultiCollectionConfig(
            collections={
                "only_collection": CollectionConfig(
                    id="only_collection",
                    name="Only Collection",
                    description="The only available collection",
                )
            }
        )

        selector = CollectionSelector(single_config)
        result = selector.select_collection("test query")

        assert result.is_successful
        assert result.collection_id == "only_collection"
        assert result.confidence == 1.0
        assert "Only one collection" in result.reasoning


class TestExplicitReferences:
    """Test explicit collection references using @syntax."""

    def test_exact_id_match(self, selector):
        """Test exact collection ID match with @ syntax."""
        result = selector.select_collection("@jj_docs how do I rebase?")

        assert result.is_successful
        assert result.collection_id == "jj_docs"
        assert result.confidence == 1.0
        assert "Explicit collection reference" in result.reasoning

    def test_partial_name_match(self, selector):
        """Test partial name matching with @ syntax."""
        result = selector.select_collection("@python what is a list?")

        assert result.is_successful
        assert result.collection_id == "python_docs"
        assert result.confidence == 0.9
        assert "Partial explicit reference" in result.reasoning

    def test_tag_match(self, selector):
        """Test tag matching with @ syntax."""
        result = selector.select_collection("@fastapi how to create endpoints?")

        assert result.is_successful
        assert result.collection_id == "fastapi_docs"
        assert result.confidence == 0.9
        assert "Partial explicit reference" in result.reasoning

    def test_nonexistent_reference(self, selector):
        """Test nonexistent collection reference."""
        result = selector.select_collection("@nonexistent what is this?")

        assert not result.is_successful
        assert result.confidence == 0.0
        assert "not found" in result.reasoning

    def test_multiple_references(self, selector):
        """Test query with multiple @ references (should use first)."""
        result = selector.select_collection("@jj_docs and @python_docs comparison")

        assert result.is_successful
        assert result.collection_id == "jj_docs"
        assert result.confidence == 1.0


class TestKeywordMatching:
    """Test keyword-based matching."""

    def test_tag_matching(self, selector):
        """Test matching based on collection tags."""
        # Test exact tag match
        keyword_score = selector._keyword_score(
            "python programming", selector.config.collections["python_docs"]
        )
        assert keyword_score > 0.4  # Should have high score due to tag matches

        # Test jj-specific query
        keyword_score = selector._keyword_score(
            "jujutsu vcs", selector.config.collections["jj_docs"]
        )
        assert keyword_score > 0.4

    def test_domain_matching(self, selector):
        """Test matching based on domain."""
        keyword_score = selector._keyword_score(
            "version control system", selector.config.collections["jj_docs"]
        )
        assert keyword_score > 0.1  # Should get some score for version-control domain

    def test_name_matching(self, selector):
        """Test matching based on collection name."""
        keyword_score = selector._keyword_score(
            "LangChain documentation", selector.config.collections["langchain_docs"]
        )
        assert keyword_score > 0.2  # Should match name tokens

    def test_description_matching(self, selector):
        """Test matching based on description."""
        keyword_score = selector._keyword_score(
            "web framework", selector.config.collections["fastapi_docs"]
        )
        assert keyword_score > 0.1  # Should get some score from description

    def test_no_matching(self, selector):
        """Test query with no keyword matches."""
        keyword_score = selector._keyword_score(
            "completely unrelated query about astronomy",
            selector.config.collections["python_docs"],
        )
        assert keyword_score == 0.0


class TestSemanticMatching:
    """Test semantic similarity matching."""

    @patch("rag_mcp.collection_selector.SentenceTransformer")
    def test_semantic_scoring(self, mock_transformer_class, selector):
        """Test semantic similarity scoring."""
        # Mock the transformer
        mock_model = Mock()
        mock_transformer_class.return_value = mock_model

        # Mock embeddings (cosine similarity of 0.8)
        query_embedding = np.array([1.0, 0.0, 0.0])
        collection_embedding = np.array([0.8, 0.6, 0.0])  # Normalized to unit vector
        collection_embedding = collection_embedding / np.linalg.norm(
            collection_embedding
        )

        mock_model.encode.side_effect = [query_embedding, collection_embedding]

        # Test semantic scoring
        score = selector._semantic_score(
            "test query", selector.config.collections["python_docs"]
        )

        # Expected cosine similarity: 0.8, normalized: (0.8 + 1) / 2 = 0.9
        assert abs(score - 0.9) < 0.1

    def test_empty_query_semantic(self, selector):
        """Test semantic scoring with empty query."""
        score = selector._semantic_score("", selector.config.collections["python_docs"])
        assert score == 0.0

    @patch("rag_mcp.collection_selector.SentenceTransformer")
    def test_semantic_error_handling(self, mock_transformer_class, selector):
        """Test error handling in semantic scoring."""
        mock_transformer_class.side_effect = Exception("Model loading failed")

        score = selector._semantic_score(
            "test query", selector.config.collections["python_docs"]
        )
        assert score == 0.0


class TestHybridSelection:
    """Test hybrid selection strategy."""

    def test_python_query_selection(self, selector):
        """Test selection for Python-related query."""
        result = selector.select_collection("How to use Python dictionaries?")

        # Should select python_docs due to strong keyword match
        assert result.is_successful
        assert result.collection_id == "python_docs"
        assert result.confidence > 0.4
        assert len(result.all_scores) == len(selector.config.collections)

    def test_version_control_query(self, selector):
        """Test selection for version control query."""
        result = selector.select_collection("How to create a new branch in jujutsu?")

        # Should select jj_docs due to jujutsu keyword
        assert result.is_successful
        assert result.collection_id == "jj_docs"
        assert result.confidence > 0.4

    def test_ai_framework_query(self, selector):
        """Test selection for AI framework query."""
        result = selector.select_collection(
            "How to build a RAG application with LangChain?"
        )

        # Should select langchain_docs due to keyword matches
        assert result.is_successful
        assert result.collection_id == "langchain_docs"
        assert result.confidence > 0.4

    def test_web_framework_query(self, selector):
        """Test selection for web framework query."""
        result = selector.select_collection(
            "How to create async API endpoints with FastAPI?"
        )

        # Should select fastapi_docs
        assert result.is_successful
        assert result.collection_id == "fastapi_docs"
        assert result.confidence > 0.4


class TestConfidenceThreshold:
    """Test confidence threshold behavior."""

    def test_below_threshold_rejection(self, multi_config):
        """Test rejection when confidence is below threshold."""
        # Create selector with high threshold
        selector = CollectionSelector(multi_config, confidence_threshold=0.9)

        # Query that should have low confidence
        result = selector.select_collection("completely unrelated astronomy question")

        assert not result.is_successful
        assert result.confidence < 0.9
        assert "confidence threshold" in result.reasoning

    def test_above_threshold_acceptance(self, multi_config):
        """Test acceptance when confidence is above threshold."""
        # Create selector with low threshold
        selector = CollectionSelector(multi_config, confidence_threshold=0.1)

        # Query that should match something
        result = selector.select_collection("python programming")

        assert result.is_successful
        assert result.confidence > 0.1

    def test_custom_threshold(self, multi_config):
        """Test custom confidence threshold."""
        selector = CollectionSelector(multi_config, confidence_threshold=0.7)
        assert selector.confidence_threshold == 0.7


class TestWeightConfiguration:
    """Test custom weight configuration."""

    def test_keyword_heavy_weighting(self, multi_config):
        """Test selector with keyword-heavy weighting."""
        selector = CollectionSelector(
            multi_config,
            semantic_weight=0.2,
            keyword_weight=0.8,
        )

        assert selector.semantic_weight == 0.2
        assert selector.keyword_weight == 0.8

    def test_semantic_heavy_weighting(self, multi_config):
        """Test selector with semantic-heavy weighting."""
        selector = CollectionSelector(
            multi_config,
            semantic_weight=0.9,
            keyword_weight=0.1,
        )

        assert selector.semantic_weight == 0.9
        assert selector.keyword_weight == 0.1


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_no_collections(self):
        """Test behavior with no collections configured."""
        empty_config = MultiCollectionConfig(collections={})
        selector = CollectionSelector(empty_config)

        result = selector.select_collection("test query")

        assert not result.is_successful
        assert result.confidence == 0.0

    def test_whitespace_query(self, selector):
        """Test query with only whitespace."""
        result = selector.select_collection("   \t\n   ")

        assert not result.is_successful
        assert result.confidence == 0.0
        assert "Empty query" in result.reasoning

    def test_very_long_query(self, selector):
        """Test with very long query."""
        long_query = "python programming " * 100  # Very long query

        result = selector.select_collection(long_query)

        # Should still work, might select python_docs
        assert isinstance(result, CollectionSelection)
        # Don't assert success as it depends on scoring

    def test_special_characters_query(self, selector):
        """Test query with special characters."""
        result = selector.select_collection("How to use @decorators in #Python?!")

        # Should handle special characters gracefully
        assert isinstance(result, CollectionSelection)


class TestPerformance:
    """Test performance-related aspects."""

    def test_embedding_caching(self, selector):
        """Test that embeddings are cached."""
        # Mock the model to track calls
        with patch.object(selector, "_model") as mock_model:
            mock_model.encode.return_value = np.array([1.0, 0.0, 0.0])

            # First call
            selector._get_embedding("test query")
            first_call_count = mock_model.encode.call_count

            # Second call with same text
            selector._get_embedding("test query")
            second_call_count = mock_model.encode.call_count

            # Should not increase call count (cached)
            assert first_call_count == second_call_count

    def test_keyword_index_performance(self, selector):
        """Test that keyword index is built efficiently."""
        # Check that keyword index contains expected terms
        index = selector._keyword_index

        # Should contain terms from tags, domains, names
        assert "python" in index
        assert "jj" in index
        assert "langchain" in index
        assert "fastapi" in index

        # Terms should map to correct collections
        assert "python_docs" in index["python"]
        assert "jj_docs" in index["jj"]


class TestFactoryFunction:
    """Test the factory function."""

    def test_create_selector(self, multi_config):
        """Test factory function creates selector correctly."""
        selector = create_selector(multi_config)

        assert isinstance(selector, CollectionSelector)
        assert selector.config == multi_config

    def test_create_selector_with_args(self, multi_config):
        """Test factory function with custom arguments."""
        selector = create_selector(
            multi_config,
            confidence_threshold=0.7,
            semantic_weight=0.8,
        )

        assert selector.confidence_threshold == 0.7
        assert selector.semantic_weight == 0.8


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
