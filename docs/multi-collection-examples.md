# Multi-Collection Configuration Examples

This document provides comprehensive examples of configuration files for the multi-collection RAG system.

## 1. Main Registry Configuration

### Option A: Single File Configuration

**File: `collections.yml`**

```yaml
# Multi-collection configuration with all collections in one file
version: "2.0"

# Global defaults that apply to all collections unless overridden
defaults:
  chunk_chars: 1200
  chunk_overlap: 200
  embedding_provider: sentence-transformers
  embedding_model: all-MiniLM-L6-v2
  chroma_persist_dir: data/chroma
  max_pages: 500
  concurrency: 8

# Collection definitions
collections:
  # JJ Version Control System Documentation
  jj_docs:
    name: "JJ Documentation"
    description: "Jujutsu VCS documentation and guides - a Git-compatible version control system"
    domain: "version-control"
    tags: ["vcs", "jj", "jujutsu", "git-alternative", "version-control", "cli-tool"]
    
    sources:
      base_urls:
        - https://jj-vcs.github.io/jj/latest/
      allow_patterns:
        - ^https://jj-vcs\.github\.io/jj/latest/.*
      deny_patterns:
        - \.pdf$
        - \.zip$
        - \.(png|jpg|jpeg|gif|svg)$
    
    # Collection-specific overrides
    chunk_chars: 1500
    chunk_overlap: 300
    
    metadata:
      language: en
      last_updated: "2024-01-15"
      version: "0.32.0"
      priority: 1
      maintainer: "jj-vcs team"

  # Python Official Documentation
  python_docs:
    name: "Python Documentation"
    description: "Official Python programming language documentation including standard library reference"
    domain: "programming-language"
    tags: ["python", "programming", "language", "stdlib", "reference", "tutorial"]
    
    sources:
      base_urls:
        - https://docs.python.org/3/
      allow_patterns:
        - ^https://docs\.python\.org/3/.*
      deny_patterns:
        - \.pdf$
        - /download/
        - \.(tar|gz|zip)$
    
    metadata:
      language: en
      version: "3.12"
      priority: 2
      last_updated: "2024-01-10"

  # LangChain Framework Documentation
  langchain_docs:
    name: "LangChain Documentation"
    description: "LangChain framework for building LLM applications with chains, agents, and RAG"
    domain: "ai-framework"
    tags: ["langchain", "llm", "ai", "rag", "agents", "chains", "embeddings", "vectordb"]
    
    sources:
      base_urls:
        - https://python.langchain.com/docs/
      allow_patterns:
        - ^https://python\.langchain\.com/docs/.*
      deny_patterns:
        - \.pdf$
        - /api_reference/  # Skip detailed API docs
    
    # Use OpenAI embeddings for AI-related content
    embedding_provider: openai
    embedding_model: text-embedding-3-small
    
    metadata:
      language: en
      priority: 1
      category: "ai-tools"

  # FastAPI Web Framework
  fastapi_docs:
    name: "FastAPI Documentation"
    description: "Modern, fast web framework for building APIs with Python based on standard type hints"
    domain: "web-framework"
    tags: ["fastapi", "api", "web", "async", "python", "rest", "openapi", "swagger"]
    
    sources:
      base_urls:
        - https://fastapi.tiangolo.com/
      allow_patterns:
        - ^https://fastapi\.tiangolo\.com/.*
      deny_patterns:
        - \.pdf$
        - /img/
    
    chunk_chars: 1000  # Smaller chunks for code examples
    chunk_overlap: 150
    
    metadata:
      language: en
      priority: 1
      framework_type: "web"

  # React Documentation
  react_docs:
    name: "React Documentation"
    description: "React JavaScript library for building user interfaces"
    domain: "frontend-framework"
    tags: ["react", "javascript", "frontend", "ui", "components", "hooks", "jsx"]
    
    sources:
      base_urls:
        - https://react.dev/
      allow_patterns:
        - ^https://react\.dev/.*
      deny_patterns:
        - \.pdf$
        - /blog/  # Skip blog posts
    
    metadata:
      language: en
      priority: 1
      framework_type: "frontend"

# Registry configuration
registry:
  auto_discover: false
  collection_dir: ./collections
  default_collection: null  # No default, always auto-select
  fallback_collection: python_docs  # Fallback if no match found
```

### Option B: Distributed Configuration (Recommended for Scale)

**File: `collections.yml` (Main Registry)**

```yaml
version: "2.0"

# Global defaults
defaults:
  chunk_chars: 1200
  chunk_overlap: 200
  embedding_provider: sentence-transformers
  embedding_model: all-MiniLM-L6-v2
  chroma_persist_dir: data/chroma

# Registry configuration
registry:
  # List of collection configuration files
  collections:
    - ./collections/jj_docs.yml
    - ./collections/python_docs.yml
    - ./collections/langchain_docs.yml
    - ./collections/fastapi_docs.yml
    - ./collections/react_docs.yml
    - ./collections/internal_docs.yml
  
  # Auto-discover collections in directory
  auto_discover: true
  collection_dir: ./collections
  
  # Collection selection settings
  selection:
    strategy: hybrid  # keyword, semantic, or hybrid
    confidence_threshold: 0.3
    default_collection: null
    fallback_collection: python_docs
  
  # Cache settings
  cache:
    embedding_cache_ttl: 3600  # 1 hour
    query_cache_ttl: 300  # 5 minutes
    metadata_cache_ttl: 600  # 10 minutes
```

**File: `collections/jj_docs.yml` (Individual Collection)**

```yaml
# JJ Documentation Collection Configuration
collection:
  id: jj_docs
  name: "JJ Documentation"
  description: "Jujutsu VCS documentation - a Git-compatible version control system"
  domain: "version-control"
  tags: 
    - vcs
    - jj
    - jujutsu
    - git-alternative
    - version-control
    - cli-tool
    - revision-control

# Source configuration
sources:
  base_urls:
    - https://jj-vcs.github.io/jj/latest/
    - https://jj-vcs.github.io/jj/v0.32.0/  # Specific version
  
  allow_patterns:
    - ^https://jj-vcs\.github\.io/jj/latest/.*
    - ^https://jj-vcs\.github\.io/jj/v0\.32\.0/.*
  
  deny_patterns:
    - \.pdf$
    - \.zip$
    - \.(png|jpg|jpeg|gif|svg)$
    - /assets/
    - /search/

# Ingestion configuration
ingestion:
  chunk_chars: 1500
  chunk_overlap: 300
  max_pages: 300
  concurrency: 8
  respect_robots_txt: true
  user_agent: "RAG-Crawler/1.0"
  request_timeout: 30
  retry_attempts: 3

# Embedding configuration
embeddings:
  provider: sentence-transformers
  model: all-MiniLM-L6-v2
  batch_size: 100

# Storage configuration
storage:
  chroma_collection_name: jj_docs
  persist_dir: data/chroma/jj_docs
  metadata_fields:
    - url
    - title
    - section
    - version

# Collection metadata
metadata:
  language: en
  version: "0.32.0"
  last_updated: "2024-01-15"
  priority: 1
  maintainer: "jj-vcs team"
  documentation_url: "https://jj-vcs.github.io"
  
  # Keywords for better matching
  keywords:
    primary:
      - jujutsu
      - jj
      - vcs
    secondary:
      - rebase
      - conflict
      - branch
      - commit
      - merge
      - revision

# Update configuration
updates:
  schedule: weekly  # daily, weekly, monthly, or cron expression
  incremental: true
  notify_on_update: true
```

## 2. Migration Configuration

**File: `migration.yml` (For migrating from single to multi-collection)**

```yaml
# Migration configuration from single-collection to multi-collection
migration:
  source:
    type: single-collection
    config_path: ./ingest/web_rag.yml
    chroma_persist_dir: data/chroma
    collection_name: web_rag
  
  target:
    type: multi-collection
    config_path: ./collections.yml
    strategy: split  # split, wrap, or duplicate
  
  # How to handle the migration
  options:
    # Split strategy: Analyze existing data and split into collections
    split:
      analyze_urls: true
      create_collections_from_domains: true
      min_documents_per_collection: 50
    
    # Wrap strategy: Keep as single collection in new format
    wrap:
      collection_id: legacy
      collection_name: "Legacy Documentation"
      preserve_metadata: true
    
    # Duplicate strategy: Keep old and create new
    duplicate:
      keep_original: true
      new_prefix: "v2_"
```

## 3. Environment Configuration

**File: `.env` (Environment variables)**

```bash
# Embedding Configuration
EMBEDDING_PROVIDER=sentence-transformers
EMBEDDING_MODEL=all-MiniLM-L6-v2
OPENAI_API_KEY=sk-...

# Storage Configuration
CHROMA_PERSIST_DIR=data/chroma
COLLECTIONS_CONFIG_PATH=./collections.yml

# Default Collection (for backwards compatibility)
DEFAULT_COLLECTION=python_docs

# Cache Configuration
REDIS_URL=redis://localhost:6379
CACHE_ENABLED=true

# Logging
LOG_LEVEL=INFO
LOG_FILE=logs/rag_mcp.log

# Performance
MAX_CONCURRENT_COLLECTIONS=10
LAZY_LOAD_COLLECTIONS=true
```

## 4. Docker Compose Configuration

**File: `docker-compose.yml`**

```yaml
version: '3.8'

services:
  rag-mcp:
    build: .
    environment:
      - COLLECTIONS_CONFIG_PATH=/app/config/collections.yml
      - CHROMA_PERSIST_DIR=/app/data/chroma
      - EMBEDDING_PROVIDER=${EMBEDDING_PROVIDER}
      - EMBEDDING_MODEL=${EMBEDDING_MODEL}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./logs:/app/logs
    ports:
      - "8000:8000"
    depends_on:
      - redis
      - chroma
  
  chroma:
    image: chromadb/chroma:latest
    volumes:
      - chroma_data:/chroma/data
    ports:
      - "8001:8000"
  
  redis:
    image: redis:alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

volumes:
  chroma_data:
  redis_data:
```

## 5. Collection Template

**File: `templates/collection_template.yml`**

```yaml
# Collection Configuration Template
# Copy this file and customize for your documentation source

collection:
  id: your_collection_id  # Unique identifier (alphanumeric + underscore)
  name: "Your Collection Name"  # Human-readable name
  description: "Detailed description of what this collection contains"
  domain: "your-domain"  # e.g., programming-language, framework, tool
  tags:  # List of searchable tags
    - tag1
    - tag2
    - tag3

# Where to crawl documentation from
sources:
  base_urls:
    - https://your-docs-site.com/
  
  allow_patterns:  # Regex patterns for URLs to include
    - ^https://your-docs-site\.com/docs/.*
  
  deny_patterns:  # Regex patterns for URLs to exclude
    - \.pdf$
    - /api/v1/  # Old API version

# How to process the content
ingestion:
  chunk_chars: 1200  # Characters per chunk
  chunk_overlap: 200  # Overlap between chunks
  max_pages: 500  # Maximum pages to crawl
  concurrency: 8  # Parallel crawling threads

# Embedding configuration
embeddings:
  provider: sentence-transformers  # or openai
  model: all-MiniLM-L6-v2  # Model name

# Storage settings
storage:
  chroma_collection_name: your_collection_id
  persist_dir: data/chroma/your_collection_id

# Metadata for collection selection and management
metadata:
  language: en
  version: "1.0.0"
  last_updated: "2024-01-20"
  priority: 1  # Higher priority for disambiguation
  maintainer: "Your Team"
  
  # Keywords for better matching
  keywords:
    primary:  # Most important keywords
      - keyword1
      - keyword2
    secondary:  # Supporting keywords
      - keyword3
      - keyword4
```

## 6. CLI Usage Examples

```bash
# Initialize multi-collection system
python -m rag_mcp.cli init --config collections.yml

# Ingest a specific collection
python -m rag_mcp.cli ingest --collection jj_docs

# Ingest all collections
python -m rag_mcp.cli ingest --all

# Update a collection
python -m rag_mcp.cli update --collection python_docs

# List all collections
python -m rag_mcp.cli list

# Test collection selection
python -m rag_mcp.cli test-selection "How do I rebase in jj?"

# Migrate from single to multi-collection
python -m rag_mcp.cli migrate --config migration.yml

# Start the MCP server
python -m rag_mcp.server --config collections.yml
```

## 7. MCP Client Configuration

**File: `.mcp.json`**

```json
{
  "mcpServers": {
    "multi-rag": {
      "command": "sh",
      "args": ["-c", "cd /path/to/rag && python -m rag_mcp.server"],
      "env": {
        "COLLECTIONS_CONFIG_PATH": "./collections.yml",
        "OPENAI_API_KEY": "${OPENAI_API_KEY}",
        "LOG_LEVEL": "INFO"
      }
    }
  }
}
```

## 8. Testing Configuration

**File: `test_collections.yml`**

```yaml
# Minimal configuration for testing
version: "2.0"

defaults:
  chunk_chars: 500
  chunk_overlap: 50
  embedding_provider: sentence-transformers
  embedding_model: all-MiniLM-L6-v2

collections:
  test_collection:
    name: "Test Collection"
    description: "Collection for unit tests"
    domain: "testing"
    tags: ["test", "demo"]
    
    sources:
      base_urls:
        - https://example.com/docs/
      allow_patterns:
        - ^https://example\.com/docs/.*
    
    metadata:
      priority: 1

registry:
  auto_discover: false
  default_collection: test_collection
```

These configuration examples demonstrate the flexibility and extensibility of the multi-collection system, supporting various deployment scenarios from simple single-file setups to complex distributed configurations with multiple collection sources.
