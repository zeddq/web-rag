Multi-Collection RAG MCP Server
================================

Overview
--------
- Crawl multiple documentation sites, organized into specialized collections.
- Each collection targets a specific domain (e.g., programming language, framework, tool).
- Intelligent query routing automatically selects the most relevant collection.
- Serve semantic search via an MCP server (`web-rag`) with automatic collection selection.

Install
-------
- With Poetry: `poetry install --with rag`
- Or with uv: `uv pip install -r <generated requirements>` (Poetry-managed projects work well with `poetry run`).

Configuration
-------------
- Copy `ingest/multi-collection.example.yml` to `ingest/multi-collection.yml` and customize:
  - Define multiple collections with unique domains and sources
  - Set global defaults for chunking and embedding settings
  - Configure collection-specific overrides as needed

### Multi-Collection Configuration Format

```yaml
version: "2.0"

# Global defaults
defaults:
  chunk_chars: 1200
  chunk_overlap: 200
  embedding_provider: sentence-transformers
  embedding_model: all-MiniLM-L6-v2
  chroma_persist_dir: data/chroma

# Collection definitions
collections:
  jj_docs:
    name: "JJ Documentation"
    description: "Jujutsu VCS documentation and guides"
    domain: "version-control"
    tags: ["vcs", "jj", "jujutsu", "git-alternative"]
    sources:
      base_urls:
        - https://jj-vcs.github.io/jj/latest/
      allow_patterns:
        - ^https://jj-vcs\.github\.io/jj/latest/.*
      deny_patterns:
        - \.pdf$
        - \.(png|jpg|jpeg|gif|svg)$
```

Ingestion
---------
### Ingest All Collections
```bash
# Using OpenAI embeddings
export OPENAI_API_KEY=sk-your-key-here
python -m rag_mcp.cli ingest --config ingest/multi-collection.yml --all

# Using local embeddings
python -m rag_mcp.cli ingest --config ingest/multi-collection.yml --all
```

### Ingest Specific Collection
```bash
python -m rag_mcp.cli ingest --config ingest/multi-collection.yml --collection jj_docs
```

### Collection Management
```bash
# List all collections
python -m rag_mcp.cli list --config ingest/multi-collection.yml

# Update a specific collection
python -m rag_mcp.cli update --collection jj_docs
```

Storage
-------
- Each collection is stored separately in Chroma:
  - `data/chroma/jj_docs/` - JJ documentation collection
  - `data/chroma/python_docs/` - Python documentation collection
  - Each collection maintains its own embeddings and metadata

MCP Server
----------
- Start: `python -m rag_mcp.server`
- Environment variables:
  - `MULTI_COLLECTION_CONFIG_PATH`: path to multi-collection config (default: `ingest/multi-collection.yml`)
  - `CHROMA_PERSIST_DIR`: base directory for collections (default: `data/chroma`)
  - `OPENAI_API_KEY`: required for OpenAI embedding providers

MCP Client Config
-----------------
```json
{
  "mcpServers": {
    "web-rag": {
      "command": "sh",
      "args": ["-c", "cd /Users/cezary/ragger && /Users/cezary/ragger/.venv/bin/python -m rag_mcp.server"],
      "env": {
        "MULTI_COLLECTION_CONFIG_PATH": "ingest/multi-collection.yml",
        "OPENAI_API_KEY": "${OPENAI_API_KEY}",
        "CHROMA_PERSIST_DIR": "data/chroma"
      }
    }
  }
}
```

Tools & Resources
-----------------
### MCP Tools
- `search(query: string, k?: number, collection_id?: string)` → automatically selects best collection and returns results
- `select_collection(query: string)` → returns the best matching collection for a query
- `list_collections()` → lists all available collections with metadata
- `get_collection_info(collection_id: string)` → detailed collection information

### MCP Resources
- `web-rag://chunk/<id>` → full chunk text + metadata from any collection
- `web-rag://collection/<id>/info` → detailed collection information
- `web-rag://index/manifest` → summary of all collections

Query Examples
--------------
```bash
# Automatic collection selection
"How do I rebase in jj?" → routes to jj_docs collection

# Explicit collection selection
"@python_docs How do I use async functions?" → searches python_docs specifically

# Collection discovery
"What collections are available?" → uses list_collections tool
```

Collection Selection
--------------------
The system uses intelligent routing to select the most appropriate collection:

1. **Explicit Selection**: Use `@collection_name` in queries to specify a collection
2. **Keyword Matching**: Matches query terms against collection tags and descriptions
3. **Semantic Matching**: Uses embedding similarity between query and collection metadata
4. **Hybrid Approach**: Combines keyword and semantic matching for best results

Performance Features
--------------------
- **Lazy Loading**: Collections are loaded only when accessed
- **Intelligent Caching**: Query results and embeddings are cached for performance
- **Scalable Architecture**: Supports 100+ collections efficiently
- **Automatic Resource Management**: Collections are unloaded when inactive

Notes
-----
- Each collection is independent with its own embedding model and configuration
- The server automatically routes queries to the most relevant collection
- Collections can be updated independently without affecting others
- No server restart required after re-ingesting collections

