# ragger

Minimal Web RAG MCP server:
- Crawl docs from the web, extract, chunk, embed
- Save to Chroma persistent collection
- Expose MCP `search` tool and chunk resources

Quick start
- Create config: copy `ingest/web_rag.example.yml` → `ingest/web_rag.yml`
- Ingest: `python -m rag_mcp.cli ingest --config ingest/web_rag.yml`
- Run server: `python -m rag_mcp.server`

MCP config snippet
```
{
  "mcpServers": {
    "web-rag": {
      "command": "sh",
      "args": ["-c", "python -m rag_mcp.server"],
      "env": {
        "OPENAI_API_KEY": "${OPENAI_API_KEY}",
        "WEB_RAG_INDEX_DIR": "data/web_rag"
      }
    }
  }
}
```

Config envs:
- CHROMA_PERSIST_DIR: path to Chroma directory (default data/chroma)
- CHROMA_COLLECTION: collection name (default web_rag)
- EMBEDDING_PROVIDER: openai or sentence-transformers (server-side)
- EMBEDDING_MODEL: embedding model id
