Web RAG MCP Server
===================

Overview
--------
- Crawl public documentation sites, extract text, chunk, and embed locally.
- Store a lightweight vector index on disk (NumPy + JSONL metadata).
- Serve semantic search via an MCP server (`web-rag`) exposing a `search` tool and `web-rag://chunk/<id>` resources.

Install (optional group)
------------------------
- With Poetry: `poetry install --with rag`
- Or with uv: `uv pip install -r <generated requirements>` (Poetry-managed projects work well with `poetry run`).

Config
------
- Copy `ingest/web_rag.example.yml` to `ingest/web_rag.yml` and edit:
  - `base_urls`: list of starting URLs to crawl.
  - `allow_patterns` / `deny_patterns`: regex filters on absolute URLs.
  - `max_pages`, `concurrency`: crawl bounds.
  - `chunk_chars`, `chunk_overlap`: chunking strategy.
  - `embedding_provider`: `openai` or `sentence-transformers`.
  - `embedding_model`: `text-embedding-3-small` or your local model name.

Ingestion
---------
- OpenAI embeddings:
  - Export `OPENAI_API_KEY`.
  - Run: `poetry run python -m rag_mcp.cli ingest --config ingest/web_rag.yml`
- Local embeddings:
  - Install `sentence-transformers` and pick a model (e.g., `all-MiniLM-L6-v2`).
  - Set `embedding_provider: sentence-transformers` and `embedding_model: all-MiniLM-L6-v2`.
  - Run the same ingest command.

Output
------
- Written to `data/web_rag/` by default:
  - `embeddings.npy`: L2-normalized float32 matrix (N, D)
  - `meta.jsonl`: one JSON per chunk with id,url,title,text,offset
  - `Chroma collection (no separate model.json; embeddings handled by collection)`: provider/name/dim used at build time

MCP Server
----------
- Start: `python -m rag_mcp.server`
- Env (optional):
  - `CHROMA_PERSIST_DIR`: path to the index dir (default `data/web_rag`).
  - `WEB_RAG_QUERY_PROVIDER`: override provider for query embeddings (`openai` or `sentence-transformers`). Defaults to index provider.
  - `WEB_RAG_QUERY_MODEL`: override model for query embeddings (defaults to index model).

MCP Client Config
-----------------
- Add an entry in `.mcp.json` or your client’s MCP config, for example:
```
{
  "mcpServers": {
    "web-rag": {
      "command": "sh",
      "args": ["-c", "poetry run python -m rag_mcp.server"],
      "env": {
        "OPENAI_API_KEY": "${OPENAI_API_KEY}",
        "CHROMA_PERSIST_DIR": "data/web_rag"
      }
    }
  }
}
```

Tools & Resources
-----------------
- Tool: `search(query: string, k?: number)` → returns top chunks with `resource` URIs.
- Resource: `web-rag://chunk/<id>` → full chunk text + metadata.
- Resource: `web-rag://index/manifest` → summary of the loaded index.

Notes
-----
- The server doesn’t crawl itself. Use the CLI to create/update the index, then `search` uses it immediately. Call `search` after re-ingesting; no restart required if the files are replaced (restart if clients cache results).
- The server embeds queries server-side. For OpenAI, ensure `OPENAI_API_KEY` is set. For local, install `sentence-transformers` and set provider/model envs if different from the index build.

