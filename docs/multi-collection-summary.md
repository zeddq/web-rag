# Multi-Collection RAG System - Executive Summary

## Overview

This architectural design extends the current single-collection RAG system to support multiple, domain-specific document collections with intelligent routing and management capabilities.

## Key Design Decisions

### 1. Architecture Principles
- **Backwards Compatibility**: Existing single-collection configurations continue to work
- **Lazy Loading**: Collections are loaded only when accessed to optimize memory usage
- **Scalability**: Designed to handle 100+ collections efficiently
- **Modularity**: Clear separation between collection management, selection, and querying

### 2. Core Innovations

#### Intelligent Collection Selection
- **Hybrid Approach**: Combines keyword matching with semantic similarity
- **Confidence Scoring**: Returns confidence levels for collection matches
- **Fallback Mechanism**: Configurable default/fallback collections for unmatched queries
- **Explicit Selection**: Users can override auto-selection with @collection syntax

#### Flexible Configuration
- **Two-Tier System**: Supports both single-file and distributed configurations
- **Collection Templates**: Standardized format for easy collection addition
- **Environment Overrides**: Environment variables for deployment flexibility
- **Hot Reload**: Collections can be updated without server restart

#### Enhanced MCP API
- **New Tools**: `select_collection`, `list_collections`, `get_collection_info`
- **Modified Search**: Auto-selects appropriate collection while maintaining compatibility
- **Resource URIs**: Collection-specific resource paths (e.g., `web-rag://jj_docs/chunk/123`)
- **Metadata Access**: Rich metadata exposure for client-side intelligence

## Implementation Roadmap

### Phase 1: Foundation (Week 1)
✅ Configuration schema design
✅ Collection metadata structure
✅ Backwards compatibility layer
✅ Registry pattern implementation

### Phase 2: Collection Management (Week 2)
- [ ] Multi-collection state manager
- [ ] Lazy loading mechanism
- [ ] Collection discovery system
- [ ] Chroma integration updates

### Phase 3: Selection Logic (Week 3)
- [ ] Keyword matching algorithm
- [ ] Semantic similarity computation
- [ ] Confidence scoring system
- [ ] Query analysis pipeline

### Phase 4: MCP Enhancement (Week 4)
- [ ] New tool implementations
- [ ] Resource URI updates
- [ ] API documentation
- [ ] Client integration guides

### Phase 5: Ingestion Pipeline (Week 5)
- [ ] Multi-collection ingestion
- [ ] Incremental updates
- [ ] Collection management CLI
- [ ] Batch processing optimization

### Phase 6: Testing & Polish (Week 6)
- [ ] Unit test coverage
- [ ] Integration testing
- [ ] Performance benchmarks
- [ ] Documentation finalization

## Technical Specifications

### Collection Selection Algorithm
```python
# Pseudocode for collection selection
def select_collection(query):
    # 1. Check explicit reference (@collection_name)
    if has_explicit_reference(query):
        return get_explicit_collection(query)
    
    # 2. Keyword matching (fast)
    keyword_scores = compute_keyword_scores(query)
    
    # 3. Semantic matching (if needed)
    if max(keyword_scores) < THRESHOLD:
        semantic_scores = compute_semantic_scores(query)
        
    # 4. Combine scores
    final_scores = combine_scores(keyword_scores, semantic_scores)
    
    # 5. Return best match or None
    return get_best_match(final_scores)
```

### Performance Targets
- Collection selection: < 50ms
- Collection loading: < 500ms (first access)
- Search within collection: < 200ms
- Support for 100+ collections
- Memory usage: < 100MB base + 50MB per active collection

### Storage Architecture
```
data/
├── chroma/
│   ├── jj_docs/           # Collection-specific storage
│   ├── python_docs/
│   └── langchain_docs/
├── configs/
│   ├── collections.yml     # Main registry
│   └── collections/        # Individual configs
└── cache/
    ├── embeddings/        # Cached embeddings
    └── queries/           # Query result cache
```

## Migration Strategy

### For Existing Users
1. **Zero-Impact Default**: System detects old format and wraps as single collection
2. **Gradual Migration**: Tools to split existing collection into multiple
3. **Rollback Support**: Can revert to single-collection mode if needed

### Migration Script Example
```bash
# Analyze existing collection
python -m rag_mcp.cli analyze --collection web_rag

# Generate migration plan
python -m rag_mcp.cli plan-migration --output migration.yml

# Execute migration
python -m rag_mcp.cli migrate --plan migration.yml --dry-run
python -m rag_mcp.cli migrate --plan migration.yml --execute
```

## API Examples

### Collection Selection
```python
# Client request
result = mcp.tool("select_collection", {
    "query": "How do I rebase in jj?"
})
# Returns: {"collection_id": "jj_docs", "confidence": 0.92}
```

### Multi-Collection Search
```python
# Auto-select collection
results = mcp.tool("search", {
    "query": "How to use async functions",
    "k": 5
})

# Explicit collection
results = mcp.tool("search_collection", {
    "query": "async functions",
    "collection_id": "python_docs",
    "k": 5
})
```

### Collection Management
```python
# List all collections
collections = mcp.tool("list_collections")

# Get collection details
info = mcp.tool("get_collection_info", {
    "collection_id": "langchain_docs"
})
```

## Benefits

### For Users
- **Better Search Results**: Queries route to the most relevant documentation
- **Reduced Noise**: No mixing of unrelated documentation domains
- **Explicit Control**: Can specify which collection to search when needed
- **Collection Discovery**: Can explore available collections and their contents

### For Administrators
- **Scalable Management**: Easy to add/remove collections
- **Flexible Configuration**: Multiple configuration strategies
- **Resource Optimization**: Lazy loading reduces memory footprint
- **Monitoring**: Collection-level metrics and usage tracking

### For Developers
- **Clean API**: Well-defined interfaces for collection operations
- **Extensibility**: Easy to add new selection strategies
- **Testing**: Collection isolation simplifies testing
- **Documentation**: Clear examples and templates

## Risk Mitigation

### Technical Risks
- **Performance Degradation**: Mitigated by lazy loading and caching
- **Memory Pressure**: Collections unloaded after inactivity
- **Selection Accuracy**: Fallback mechanisms and confidence thresholds
- **Migration Issues**: Comprehensive testing and rollback support

### Operational Risks
- **Configuration Complexity**: Templates and validation tools
- **Collection Proliferation**: Registry limits and governance
- **Inconsistent Embeddings**: Per-collection embedding configuration
- **Version Conflicts**: Collection versioning support

## Success Metrics

### Quantitative
- Collection selection accuracy > 90%
- Query latency < 200ms (p95)
- Memory usage < 1GB for 50 collections
- Zero downtime migrations

### Qualitative
- Improved user satisfaction with search results
- Reduced support tickets for "wrong documentation"
- Easier onboarding of new documentation sources
- Simplified collection management workflow

## Next Steps

1. **Review & Approval**: Stakeholder review of architecture
2. **Prototype Development**: Build proof-of-concept for collection selection
3. **Performance Testing**: Validate scalability assumptions
4. **Implementation Planning**: Detailed sprint planning
5. **Documentation Preparation**: API docs and migration guides

## Conclusion

This multi-collection architecture provides a robust, scalable solution for managing diverse documentation sources while maintaining simplicity for end users. The design prioritizes backwards compatibility, performance, and extensibility, ensuring the system can grow with future needs.

The phased implementation approach allows for iterative development with regular validation checkpoints, reducing risk and ensuring quality delivery.

## Appendices

### A. File Structure
- [`multi-collection-architecture.md`](./multi-collection-architecture.md) - Detailed technical architecture
- [`multi-collection-diagrams.md`](./multi-collection-diagrams.md) - Visual architecture diagrams
- [`multi-collection-examples.md`](./multi-collection-examples.md) - Configuration examples

### B. Key Design Patterns
- **Registry Pattern**: Central collection management
- **Strategy Pattern**: Pluggable selection algorithms
- **Lazy Loading**: On-demand resource allocation
- **Factory Pattern**: Collection instance creation
- **Observer Pattern**: Configuration hot-reload

### C. Technology Stack
- **Vector Database**: ChromaDB
- **Embeddings**: OpenAI / Sentence Transformers
- **MCP Framework**: FastMCP
- **Configuration**: YAML with schema validation
- **Caching**: Redis (optional) or in-memory

### D. Glossary
- **Collection**: A logical grouping of related documents
- **Registry**: Central catalog of available collections
- **Selector**: Component that matches queries to collections
- **Confidence Score**: Probability that a collection matches a query
- **Lazy Loading**: Loading resources only when accessed
