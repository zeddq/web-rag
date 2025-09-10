#!/usr/bin/env python3
"""
Universal MCP Client Script
===========================
A command-line tool to interact with any MCP server.

Features:
- Discover and list available MCP servers
- List tools and resources for each server
- Execute any tool with arguments
- Access any resource by URI
- Interactive and non-interactive modes
- Full support for web-rag multi-collection server

Usage:
    # List all available servers
    python scripts/mcp_client.py list-servers

    # List tools for a server
    python scripts/mcp_client.py list-tools web-rag

    # List resources for a server
    python scripts/mcp_client.py list-resources web-rag

    # Execute a tool - Search across collections
    python scripts/mcp_client.py exec web-rag search --query "jj rebase" --k 5

    # Search a specific collection
    python scripts/mcp_client.py exec web-rag search --query "docker compose" --collection_id "docker_collection"

    # List all collections
    python scripts/mcp_client.py exec web-rag list_collections

    # Select best collection for a query
    python scripts/mcp_client.py exec web-rag select_collection --query "how to use git"

    # Get collection info
    python scripts/mcp_client.py exec web-rag get_collection_info --collection_id "jj_vcs"

    # Access a resource
    python scripts/mcp_client.py get-resource web-rag "web-rag://chunk/123"

    # Interactive mode
    python scripts/mcp_client.py interactive
"""

import asyncio
import json
import sys
import os
import argparse
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
import re

# Add parent directory to path for local imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
except ImportError:
    print("Error: MCP library not installed. Please install it with: pip install mcp")
    sys.exit(1)


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server."""

    name: str
    command: str
    args: List[str]
    env: Dict[str, str] = None
    cwd: str = None

    def to_stdio_params(self) -> StdioServerParameters:
        """Convert to StdioServerParameters for MCP client."""
        # Expand command and args
        full_command = [self.command] + self.args

        # Process environment variables
        env = os.environ.copy()
        if self.env:
            for key, value in self.env.items():
                # Expand environment variable references like ${VAR}
                expanded = os.path.expandvars(value)
                env[key] = expanded

        return StdioServerParameters(
            command=full_command[0],
            args=full_command[1:] if len(full_command) > 1 else [],
            env=env,
            cwd=self.cwd,
        )


class MCPClient:
    """Universal MCP client for interacting with any MCP server."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize the MCP client with optional config path."""
        self.config_path = config_path or self._find_config_file()
        self.servers = self._load_servers()

    def _find_config_file(self) -> Optional[str]:
        """Find MCP configuration file in standard locations."""
        possible_paths = [
            Path(
                "/Users/cezary/Library/Application Support/Cursor/User/globalStorage/rooveterinaryinc.roo-cline/settings/mcp_settings.json"
            ),
            Path.home() / ".mcp.json",
            Path.cwd() / ".mcp.json",
            Path.cwd() / "mcp.json",
            Path.cwd() / ".roo" / "mcp.json",
            Path.home() / ".config" / "mcp" / "config.json",
        ]

        # Check standard file paths first
        for path in possible_paths:
            if path.exists():
                return str(path)

        # Try to extract MCP servers from Claude's config
        try:
            cmd = 'tmpfile=$(mktemp) && cat ~/.claude.json | jq \'{mcpServers: .?.mcpServers}\' > "$tmpfile" && echo "$tmpfile"'
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                claude_config_path = result.stdout.strip()
                if Path(claude_config_path).exists():
                    # Verify the file has MCP servers content
                    with open(claude_config_path, "r") as f:
                        config = json.load(f)
                    if config.get("mcpServers"):
                        return claude_config_path
        except (
            subprocess.SubprocessError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
            FileNotFoundError,
        ):
            # If jq or claude config extraction fails, continue without it
            pass

        return None

    def _load_servers(self) -> Dict[str, MCPServerConfig]:
        """Load server configurations from config file."""
        servers = {}

        if not self.config_path or not Path(self.config_path).exists():
            # If no config file, try to detect the local web-rag server
            print("No MCP config file found. Attempting to detect local servers...")

            # Check if we're in the ragger project with web-rag server
            if Path("rag_mcp/server.py").exists():
                # Detect the project root and virtual environment
                project_root = Path.cwd()
                venv_python = None

                # Check for poetry environment
                if Path("pyproject.toml").exists():
                    # Try to get poetry python path
                    try:
                        result = subprocess.run(
                            ["poetry", "env", "info", "--path"],
                            capture_output=True,
                            text=True,
                            timeout=5,
                        )
                        if result.returncode == 0:
                            venv_path = Path(result.stdout.strip())
                            venv_python = venv_path / "bin" / "python"
                    except:
                        pass

                # Fallback to .venv if poetry command fails
                if not venv_python or not venv_python.exists():
                    venv_python = project_root / ".venv" / "bin" / "python"

                # Use system python as last resort
                if not venv_python.exists():
                    venv_python = Path(sys.executable)

                servers["web-rag"] = MCPServerConfig(
                    name="web-rag",
                    command="sh",
                    args=[
                        "-c",
                        f"cd {project_root} && {venv_python} -m rag_mcp.server",
                    ],
                    env={
                        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
                        "MULTI_COLLECTION_CONFIG_PATH": os.getenv(
                            "MULTI_COLLECTION_CONFIG_PATH",
                            "ingest/multi-collection.yml",
                        ),
                    },
                    cwd=str(project_root),
                )
                print(f"✅ Detected local web-rag server at {project_root}")
                print(f"   Using Python: {venv_python}")

            return servers

        # Load from config file
        try:
            with open(self.config_path, "r") as f:
                config = json.load(f)

            mcp_servers = config.get("mcpServers", {})
            for name, server_config in mcp_servers.items():
                servers[name] = MCPServerConfig(
                    name=name,
                    command=server_config.get("command", ""),
                    args=server_config.get("args", []),
                    env=server_config.get("env", {}),
                    cwd=server_config.get("cwd"),
                )

            print(f"Loaded {len(servers)} servers from {self.config_path}")

        except Exception as e:
            print(f"Error loading config from {self.config_path}: {e}")

        return servers

    def list_servers(self) -> List[str]:
        """List all available MCP servers."""
        return list(self.servers.keys())

    async def connect_to_server(self, server_name: str) -> Optional[ClientSession]:
        """Connect to a specific MCP server."""
        if server_name not in self.servers:
            print(f"Error: Server '{server_name}' not found in configuration")
            return None

        server_config = self.servers[server_name]
        stdio_params = server_config.to_stdio_params()

        try:
            # Create client session
            async with stdio_client(stdio_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    # Initialize the session
                    await session.initialize()
                    return session
        except Exception as e:
            print(f"Error connecting to server '{server_name}': {e}")
            return None

    async def list_tools(self, server_name: str) -> List[Dict[str, Any]]:
        """List all tools available on a server."""
        server_config = self.servers.get(server_name)
        if not server_config:
            print(f"Error: Server '{server_name}' not found")
            return []

        stdio_params = server_config.to_stdio_params()

        try:
            async with stdio_client(stdio_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    # Get available tools
                    tools_response = await session.list_tools()
                    tools = []

                    for tool in tools_response.tools:
                        tool_info = {
                            "name": tool.name,
                            "description": tool.description,
                            "input_schema": (
                                tool.inputSchema if hasattr(tool, "inputSchema") else {}
                            ),
                        }
                        tools.append(tool_info)

                    return tools

        except Exception as e:
            print(f"Error listing tools for '{server_name}': {e}")
            return []

    async def list_resources(self, server_name: str) -> List[Dict[str, Any]]:
        """List all resources available on a server."""
        server_config = self.servers.get(server_name)
        if not server_config:
            print(f"Error: Server '{server_name}' not found")
            return []

        stdio_params = server_config.to_stdio_params()

        try:
            async with stdio_client(stdio_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    # Get available resources
                    resources_response = await session.list_resources()
                    resources = []

                    for resource in resources_response.resources:
                        resource_info = {
                            "uri": resource.uri,
                            "name": resource.name,
                            "description": (
                                resource.description
                                if hasattr(resource, "description")
                                else ""
                            ),
                            "mimeType": (
                                resource.mimeType
                                if hasattr(resource, "mimeType")
                                else ""
                            ),
                        }
                        resources.append(resource_info)

                    return resources

        except Exception as e:
            print(f"Error listing resources for '{server_name}': {e}")
            return []

    async def execute_tool(
        self, server_name: str, tool_name: str, arguments: Dict[str, Any]
    ) -> Any:
        """Execute a tool on a server with given arguments."""
        server_config = self.servers.get(server_name)
        if not server_config:
            print(f"Error: Server '{server_name}' not found")
            return None

        stdio_params = server_config.to_stdio_params()

        try:
            async with stdio_client(stdio_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    # Execute the tool
                    result = await session.call_tool(tool_name, arguments)
                    return result

        except Exception as e:
            print(f"Error executing tool '{tool_name}' on '{server_name}': {e}")
            return None

    async def get_resource(self, server_name: str, uri: str) -> Any:
        """Get a resource from a server by URI."""
        server_config = self.servers.get(server_name)
        if not server_config:
            print(f"Error: Server '{server_name}' not found")
            return None

        stdio_params = server_config.to_stdio_params()

        try:
            async with stdio_client(stdio_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    # Get the resource
                    result = await session.read_resource(uri)
                    return result

        except Exception as e:
            print(f"Error getting resource '{uri}' from '{server_name}': {e}")
            return None


def parse_tool_arguments(args: List[str]) -> Dict[str, Any]:
    """Parse tool arguments from command line format."""
    arguments = {}
    i = 0

    while i < len(args):
        if args[i].startswith("--"):
            key = args[i][2:]  # Remove --

            # Check if there's a value
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                value = args[i + 1]

                # Try to parse as JSON first
                try:
                    value = json.loads(value)
                except:
                    # Try to parse as number
                    try:
                        if "." in value:
                            value = float(value)
                        else:
                            value = int(value)
                    except:
                        # Keep as string
                        pass

                arguments[key] = value
                i += 2
            else:
                # Boolean flag
                arguments[key] = True
                i += 1
        else:
            i += 1

    return arguments


async def interactive_mode(client: MCPClient):
    """Run the client in interactive mode."""
    print("\n🚀 MCP Client Interactive Mode")
    print("=" * 50)
    print("Commands:")
    print("  servers          - List all available servers")
    print("  tools <server>   - List tools for a server")
    print("  resources <server> - List resources for a server")
    print("  exec <server> <tool> [args] - Execute a tool")
    print("  get <server> <uri> - Get a resource")
    print("  help             - Show this help")
    print("  quit/exit        - Exit interactive mode")
    print("=" * 50)

    # Print web-rag specific examples if available
    if "web-rag" in client.list_servers():
        print("\n📚 Web-RAG Multi-Collection Examples:")
        print("  exec web-rag list_collections")
        print('  exec web-rag search --query "your query" --k 5')
        print('  exec web-rag search --query "@docker compose up" --k 3')
        print('  exec web-rag select_collection --query "how to use git"')
        print('  exec web-rag get_collection_info --collection_id "jj_vcs"')
        print("=" * 50)

    while True:
        try:
            command = input("\nmcp> ").strip()

            if not command:
                continue

            parts = command.split()
            cmd = parts[0].lower()

            if cmd in ["quit", "exit"]:
                print("Goodbye!")
                break

            elif cmd == "help":
                print("\nCommands:")
                print("  servers          - List all available servers")
                print("  tools <server>   - List tools for a server")
                print("  resources <server> - List resources for a server")
                print("  exec <server> <tool> [args] - Execute a tool")
                print("  get <server> <uri> - Get a resource")
                print("  quit/exit        - Exit interactive mode")

                if "web-rag" in client.list_servers():
                    print("\n📚 Web-RAG Examples:")
                    print("  exec web-rag list_collections")
                    print('  exec web-rag search --query "docker" --k 5')

            elif cmd == "servers":
                servers = client.list_servers()
                if servers:
                    print("\n📦 Available servers:")
                    for server in servers:
                        print(f"  • {server}")
                else:
                    print("No servers configured")

            elif cmd == "tools" and len(parts) >= 2:
                server_name = parts[1]
                tools = await client.list_tools(server_name)
                if tools:
                    print(f"\n🔧 Tools for '{server_name}':")
                    for tool in tools:
                        print(f"\n  • {tool['name']}")
                        if tool["description"]:
                            print(f"    {tool['description']}")
                        if tool.get("input_schema", {}).get("properties"):
                            print(f"    Parameters:")
                            props = tool["input_schema"]["properties"]
                            for param, details in props.items():
                                required = param in tool["input_schema"].get(
                                    "required", []
                                )
                                req_text = " (required)" if required else " (optional)"
                                desc = details.get("description", "")
                                print(f"      --{param}{req_text}: {desc}")
                else:
                    print(f"No tools found for '{server_name}'")

            elif cmd == "resources" and len(parts) >= 2:
                server_name = parts[1]
                resources = await client.list_resources(server_name)
                if resources:
                    print(f"\n📚 Resources for '{server_name}':")
                    for resource in resources:
                        print(f"\n  • {resource['uri']}")
                        if resource["name"]:
                            print(f"    Name: {resource['name']}")
                        if resource["description"]:
                            print(f"    {resource['description']}")
                else:
                    print(f"No resources found for '{server_name}'")

            elif cmd == "exec" and len(parts) >= 3:
                server_name = parts[1]
                tool_name = parts[2]
                tool_args = parse_tool_arguments(parts[3:])

                print(
                    f"\nExecuting {tool_name} on {server_name} with args: {tool_args}"
                )
                result = await client.execute_tool(server_name, tool_name, tool_args)

                if result:
                    print("\n✅ Result:")
                    if hasattr(result, "content"):
                        # Handle different content types
                        for content_item in result.content:
                            if hasattr(content_item, "text"):
                                # Try to parse as JSON for pretty printing
                                try:
                                    data = json.loads(content_item.text)
                                    print(json.dumps(data, indent=2))
                                except:
                                    print(content_item.text)
                            else:
                                print(json.dumps(content_item, default=str, indent=2))
                    else:
                        print(json.dumps(result, default=str, indent=2))

            elif cmd == "get" and len(parts) >= 3:
                server_name = parts[1]
                uri = parts[2]

                print(f"\nGetting resource {uri} from {server_name}")
                result = await client.get_resource(server_name, uri)

                if result:
                    print("\n✅ Resource content:")
                    if hasattr(result, "contents"):
                        for content in result.contents:
                            if hasattr(content, "text"):
                                print(content.text)
                            elif hasattr(content, "uri"):
                                print(f"URI: {content.uri}")
                                if hasattr(content, "mimeType"):
                                    print(f"Type: {content.mimeType}")
                            else:
                                print(content)
                    else:
                        print(result)

            else:
                print(f"Unknown command or invalid syntax: {command}")
                print("Type 'help' for available commands")

        except KeyboardInterrupt:
            print("\nUse 'quit' or 'exit' to leave interactive mode")
        except Exception as e:
            print(f"Error: {e}")


async def main():
    """Main entry point for the MCP client."""
    parser = argparse.ArgumentParser(
        description="Universal MCP Client - Interact with any MCP server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list-servers
  %(prog)s list-tools web-rag
  %(prog)s list-resources web-rag
  
  # Search across all collections (auto-select best)
  %(prog)s exec web-rag search --query "jj rebase" --k 5
  
  # Search with @ prefix for collection hint
  %(prog)s exec web-rag search --query "@docker compose up" --k 3
  
  # Search specific collection by ID
  %(prog)s exec web-rag search --query "git commands" --collection_id "jj_vcs"
  
  # List all available collections
  %(prog)s exec web-rag list_collections
  
  # Analyze which collection best matches a query  
  %(prog)s exec web-rag select_collection --query "how to use kubernetes"
  
  # Get detailed information about a collection
  %(prog)s exec web-rag get_collection_info --collection_id "docker_collection"
  
  # Access a specific chunk resource
  %(prog)s get-resource web-rag "web-rag://chunk/123"
  
  # Interactive mode
  %(prog)s interactive
        """,
    )

    parser.add_argument("--config", help="Path to MCP configuration file")

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # List servers command
    subparsers.add_parser("list-servers", help="List all configured MCP servers")

    # List tools command
    list_tools_parser = subparsers.add_parser(
        "list-tools", help="List tools for a server"
    )
    list_tools_parser.add_argument("server", help="Server name")

    # List resources command
    list_resources_parser = subparsers.add_parser(
        "list-resources", help="List resources for a server"
    )
    list_resources_parser.add_argument("server", help="Server name")

    # Execute tool command
    exec_parser = subparsers.add_parser("exec", help="Execute a tool")
    exec_parser.add_argument("server", help="Server name")
    exec_parser.add_argument("tool", help="Tool name")
    exec_parser.add_argument(
        "args", nargs=argparse.REMAINDER, help="Tool arguments (--key value format)"
    )

    # Get resource command
    get_parser = subparsers.add_parser("get-resource", help="Get a resource")
    get_parser.add_argument("server", help="Server name")
    get_parser.add_argument("uri", help="Resource URI")

    # Interactive mode
    subparsers.add_parser("interactive", help="Run in interactive mode")

    args = parser.parse_args()

    # Initialize client
    client = MCPClient(config_path=args.config)

    if not args.command:
        parser.print_help()
        return

    # Execute command
    if args.command == "list-servers":
        servers = client.list_servers()
        if servers:
            print("📦 Available MCP servers:")
            for server in servers:
                print(f"  • {server}")
        else:
            print("No servers configured")

    elif args.command == "list-tools":
        tools = await client.list_tools(args.server)
        if tools:
            print(f"🔧 Tools for '{args.server}':")
            for tool in tools:
                print(f"\n• {tool['name']}")
                if tool["description"]:
                    # Wrap description text
                    desc_lines = tool["description"].split("\n")
                    for line in desc_lines:
                        print(f"  {line}")
                if tool.get("input_schema", {}).get("properties"):
                    print(f"  Parameters:")
                    props = tool["input_schema"]["properties"]
                    required = tool["input_schema"].get("required", [])
                    for param, details in props.items():
                        req_text = " (required)" if param in required else " (optional)"
                        desc = details.get("description", "")
                        param_type = details.get("type", "string")
                        print(f"    --{param}{req_text}: {desc} [{param_type}]")
        else:
            print(f"No tools found for '{args.server}'")

    elif args.command == "list-resources":
        resources = await client.list_resources(args.server)
        if resources:
            print(f"📚 Resources for '{args.server}':")
            for resource in resources:
                print(f"\n• {resource['uri']}")
                if resource["name"]:
                    print(f"  Name: {resource['name']}")
                if resource["description"]:
                    print(f"  Description: {resource['description']}")
                if resource["mimeType"]:
                    print(f"  Type: {resource['mimeType']}")
        else:
            print(f"No resources found for '{args.server}'")

    elif args.command == "exec":
        tool_args = parse_tool_arguments(args.args)
        print(f"Executing '{args.tool}' on '{args.server}' with arguments: {tool_args}")

        result = await client.execute_tool(args.server, args.tool, tool_args)
        if result:
            print("\n✅ Result:")
            if hasattr(result, "content"):
                for content_item in result.content:
                    if hasattr(content_item, "text"):
                        # Try to parse as JSON for pretty printing
                        try:
                            data = json.loads(content_item.text)
                            print(json.dumps(data, indent=2))
                        except:
                            print(content_item.text)
                    else:
                        print(json.dumps(content_item, default=str, indent=2))
            else:
                print(json.dumps(result, default=str, indent=2))

    elif args.command == "get-resource":
        print(f"Getting resource '{args.uri}' from '{args.server}'")

        result = await client.get_resource(args.server, args.uri)
        if result:
            print("\n✅ Resource content:")
            if hasattr(result, "contents"):
                for content in result.contents:
                    if hasattr(content, "text"):
                        print(content.text)
                    elif hasattr(content, "uri"):
                        print(f"URI: {content.uri}")
                        if hasattr(content, "mimeType"):
                            print(f"Type: {content.mimeType}")
                    else:
                        print(content)
            else:
                print(result)

    elif args.command == "interactive":
        await interactive_mode(client)


if __name__ == "__main__":
    asyncio.run(main())
