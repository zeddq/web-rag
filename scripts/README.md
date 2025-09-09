# MCP Scripts

This directory contains utility scripts for working with MCP servers and jj version control.

## mcp_client.py

A universal command-line client for interacting with any MCP (Model Context Protocol) server.

### Features

- **Server Discovery**: Automatically discovers MCP servers from configuration files or detects local servers
- **Tool Listing**: List all available tools for any MCP server with their input schemas
- **Resource Listing**: List all available resources (documents, data) from servers
- **Tool Execution**: Execute any tool on any server with proper argument handling
- **Resource Access**: Retrieve any resource by URI from servers
- **Interactive Mode**: Interactive shell for exploring and using MCP servers

### Installation

The script requires the MCP Python library:

```bash
pip install mcp
```

### Usage

#### List Available Servers

```bash
python scripts/mcp_client.py list-servers
```

#### List Tools for a Server

```bash
python scripts/mcp_client.py list-tools web-rag
```

#### List Resources for a Server

```bash
python scripts/mcp_client.py list-resources web-rag
```

#### Execute a Tool

```bash
# Search for documents
python scripts/mcp_client.py exec web-rag search -- --query "jj rebase" --k 5

# Select the best collection for a query
python scripts/mcp_client.py exec web-rag select_collection -- --query "How to use jj?"

# List all collections
python scripts/mcp_client.py exec web-rag list_collections

# Get collection info
python scripts/mcp_client.py exec web-rag get_collection_info -- --collection_id web_rag
```

Note: Use `--` before tool arguments to separate them from the command arguments.

#### Access a Resource

```bash
python scripts/mcp_client.py get-resource web-rag "web-rag://chunk/123"
```

#### Interactive Mode

```bash
python scripts/mcp_client.py interactive
```

In interactive mode, you can use these commands:
- `servers` - List all available servers
- `tools <server>` - List tools for a server
- `resources <server>` - List resources for a server
- `exec <server> <tool> [args]` - Execute a tool
- `get <server> <uri>` - Get a resource
- `help` - Show help
- `quit` or `exit` - Exit interactive mode

### Configuration

The script looks for MCP configuration in these locations (in order):
1. `~/.mcp.json` - User home directory
2. `./.mcp.json` - Current directory
3. `./mcp.json` - Current directory
4. `./.roo/mcp.json` - Roo project config directory
5. `~/.config/mcp/config.json` - User config directory
6. Claude's config - Extracted from `~/.claude.json` (requires `jq`)

You can also specify a custom config file:

```bash
python scripts/mcp_client.py --config /path/to/config.json list-servers
```

#### Configuration Format

```json
{
  "mcpServers": {
    "server-name": {
      "command": "python",
      "args": ["-m", "module.server"],
      "env": {
        "API_KEY": "${API_KEY}",
        "CONFIG_PATH": "./config.yml"
      },
      "cwd": "/path/to/working/directory"
    }
  }
}
```

### Examples

#### Search for JuJutsu Documentation

```bash
# Search for jj rebase information
python scripts/mcp_client.py exec web-rag search -- --query "jj rebase branches" --k 5

# Get a specific document chunk
python scripts/mcp_client.py get-resource web-rag "web-rag://chunk/6087817875441442090_103000"
```

#### Interactive Session Example

```bash
$ python scripts/mcp_client.py interactive

🚀 MCP Client Interactive Mode
==================================================
Commands:
  servers          - List all available servers
  tools <server>   - List tools for a server
  resources <server> - List resources for a server
  exec <server> <tool> [args] - Execute a tool
  get <server> <uri> - Get a resource
  help             - Show this help
  quit/exit        - Exit interactive mode
==================================================

mcp> servers

📦 Available servers:
  • web-rag

mcp> tools web-rag

🔧 Tools for 'web-rag':

  • search
    Search for relevant documents across collections.
    Schema: {
      "properties": {
        "query": {"type": "string"},
        "k": {"type": "integer", "default": 5},
        "collection_id": {"type": "string", "default": null}
      },
      "required": ["query"]
    }

mcp> exec web-rag search --query "jj squash" --k 2

Executing search on web-rag with args: {'query': 'jj squash', 'k': 2}

✅ Result:
{
  "results": [...],
  "selection_info": {...}
}

mcp> quit
Goodbye!
```

---

## apply_gitignore_to_jj.sh

A shell script that applies `.gitignore` patterns to JuJutsu (jj) by untracking matching files.

### Features

- Reads `.gitignore` file and processes each pattern
- Handles different gitignore pattern types:
  - Glob patterns (`**/__pycache__/`)
  - Absolute paths (`/data`)
  - Wildcards (`*.log`)
- Translates gitignore syntax to jj-compatible formats
- Provides detailed feedback on what's being untracked

### Usage

From the repository root:

```bash
./scripts/apply_gitignore_to_jj.sh
```

Or from any directory:

```bash
/path/to/scripts/apply_gitignore_to_jj.sh
```

The script will:
1. Read the `.gitignore` file from the repository root
2. Process each pattern and find matching files
3. Run `jj file untrack` for each match
4. Report which files were successfully untracked

### Example Output

```
🔍 Reading .gitignore and untracking matching files in jj...

Method 1: Using direct pattern matching with jj
================================================
📋 Processing pattern: **/__pycache__/
  ↳ Attempting to untrack pattern: **/__pycache__/

Method 2: Finding and untracking specific files
================================================
📋 Processing pattern: **/__pycache__/
  ↳ Untracking: ./rag_mcp/__pycache__
  ↳ Untracking: ./.venv/lib/python3.13/site-packages/mcp/__pycache__
  ...

✅ Finished processing .gitignore patterns

💡 Tips:
   - Files must be in .gitignore before they can be untracked
   - Use 'jj status' to see which files are currently tracked
   - Use 'jj file list' to see all tracked files
```

### Notes

- Files must already be in `.gitignore` before they can be untracked
- The script will skip files that are already untracked
- Comments and empty lines in `.gitignore` are properly handled
- The script uses two methods to ensure maximum compatibility with different pattern types
