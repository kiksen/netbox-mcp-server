# NetBox MCP Server

> **⚠️ This is my modified version of the NetBox MCP Server**: The project structure has changed.
> - Added create VLAN and prefix tools
> - Upgraded to fastmcp 3.1.1
> - Removed all command line parameters and added `.env` support to run it in an Azure Web App
> - Docker users: rebuild images with updated CMD
> - Update Claude Desktop/Code configs to use `netbox-mcp-server` instead of `server.py`
> - Use `uv run netbox-mcp-server`

This is a [Model Context Protocol](https://modelcontextprotocol.io/) server for NetBox.  It enables you to interact with your NetBox data directly via LLMs that support MCP — including querying infrastructure objects, searching across types, and creating VLANs and prefixes.

## Tools

### Read / Query Tools

| Tool | Description |
|------|-------------|
| `netbox_get_objects` | Retrieves NetBox objects based on type and filters, with pagination and field projection |
| `netbox_get_object_by_id` | Gets detailed information about a specific NetBox object by its ID |
| `netbox_get_changelogs` | Retrieves change history records (audit trail) based on filters |
| `netbox_search_objects` | Performs a global full-text search across multiple NetBox object types |
| `netbox_get_site_summary_prefixes` | Returns all prefixes with IPAM role `site-summary` for a given site |
| `netbox_get_next_available_prefix` | Finds the next free prefix of a given size within a container prefix |
| `netbox_get_vlan_groups_for_site` | Lists all VLAN groups scoped to a specific site |
| `netbox_get_vlans_for_site` | Returns all VLANs for a site, resolved via its VLAN group |
| `netbox_check_vlan_id_in_vlan_group` | Checks whether a VLAN ID already exists in a given VLAN group |

### Write / Create Tools

| Tool | Description |
|------|-------------|
| `netbox_review_vlan_prefix_plan` | Presents a plan of VLANs and prefixes for user confirmation before creation |
| `netbox_create_vlan_prefix_batch` | Creates VLANs and associated prefixes in NetBox after explicit user confirmation |

> Note: the set of supported object types is explicitly defined and limited to the core NetBox objects, and won't work with object types from plugins.

## Usage

1. Create a read-write API token in NetBox with sufficient permissions for the tools to access the data you want to make available via MCP.

2. Install dependencies:

    ```bash
    # Using UV (recommended)
    uv sync

    # Or using pip
    pip install -e .
    ```

3. Configure environment variables:

   The server supports multiple configuration sources with the following precedence (highest to lowest):

   1. **Environment variables** (highest priority)
   2. **`.env` file** in the project root
   3. **Default values** (lowest priority)

   | Variable | Type | Default | Required | Description |
   |----------|------|---------|----------|-------------|
   | `NETBOX_URL` | URL | — | Yes | Base URL of your NetBox instance (e.g., `https://netbox.example.com/`) |
   | `NETBOX_TOKEN` | String | — | Yes | API token for authentication |
   | `TRANSPORT` | `stdio` \| `http` | `stdio` | No | MCP transport protocol |
   | `HOST` | String | `127.0.0.1` | If HTTP | Host address for HTTP server |
   | `PORT` | Integer | `8000` | If HTTP | Port for HTTP server |
   | `VERIFY_SSL` | Boolean | `false` | No | Whether to verify SSL certificates |
   | `MCP_TOKEN` | String | — | No | Bearer token to protect the HTTP endpoint (recommended when exposed beyond localhost) |
   | `LOG_LEVEL` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL` | `INFO` | No | Logging verbosity |

   **Example `.env` file** — create this in the project root:

   ```env
   # Core NetBox Configuration
   NETBOX_URL=https://netbox.example.com/
   NETBOX_TOKEN=your_api_token_here

   # Transport Configuration (optional, defaults to stdio)
   TRANSPORT=stdio

   # HTTP Transport Settings (only used if TRANSPORT=http)
   # HOST=127.0.0.1
   # PORT=8000

   # MCP Endpoint Authentication (recommended when TRANSPORT=http and exposed beyond localhost)
   # MCP_TOKEN=your_mcp_bearer_token_here

   # Security (optional, defaults to false)
   VERIFY_SSL=false

   # Logging (optional, defaults to INFO)
   LOG_LEVEL=INFO
   ```

   > The server does not accept CLI arguments. All configuration is done via environment variables or the `.env` file.

4. Verify the server can run:

   ```bash
   uv run netbox-mcp-server
   ```

   > **Note:** Without `NETBOX_URL` and `NETBOX_TOKEN` set, the server will exit with an error — this is expected. Set these values in your `.env` file or environment before connecting a client.

### Claude Code

#### Stdio Transport (Default)

Add the server using the `claude mcp add` command:

```bash
claude mcp add --transport stdio netbox \
  -- uv --directory /path/to/netbox-mcp-server run netbox-mcp-server
```

**Important notes:**

- Replace `/path/to/netbox-mcp-server` with the absolute path to your local clone
- The `--` separator distinguishes Claude Code flags from the server command
- Use `--scope project` to share the configuration via `.mcp.json` in version control
- Use `--scope user` to make it available across all your projects (default is `local`)

After adding, verify with `/mcp` in Claude Code or `claude mcp list` in your terminal.

#### HTTP Transport

For HTTP transport, first start the server manually:

```bash
NETBOX_URL=https://netbox.example.com/ \
NETBOX_TOKEN=<your-api-token> \
TRANSPORT=http \
uv run netbox-mcp-server
```

Then add the running server to Claude Code:

```bash
# Without MCP_TOKEN
claude mcp add --transport http netbox http://127.0.0.1:8000/mcp

# With MCP_TOKEN (when the server is protected by a bearer token)
claude mcp add --transport http netbox \
  --header "Authorization: Bearer <your-mcp-bearer-token>" \
  http://127.0.0.1:8000/mcp
```

Or use a `.mcp.json` file to share the config in version control:

```json
{
  "mcpServers": {
    "netbox": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "Authorization": "Bearer <your-mcp-bearer-token>"
      }
    }
  }
}
```

**Important notes:**

- The URL **must** include the protocol prefix (`http://` or `https://`)
- The default endpoint is `/mcp` when using HTTP transport
- The server must be running before Claude Code can connect
- Verify the connection with `claude mcp list` — you should see a ✓ next to the server name

### Claude Desktop

Add the server configuration to your Claude Desktop config file. On Mac, edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
    "mcpServers": {
        "netbox": {
            "command": "uv",
            "args": [
                "--directory",
                "/path/to/netbox-mcp-server",
                "run",
                "netbox-mcp-server"
            ],
            "env": {
                "NETBOX_URL": "https://netbox.example.com/",
                "NETBOX_TOKEN": "<your-api-token>"
            }
        }
    }
}
```

> On Windows, use full, escaped path to your instance, such as `C:\\Users\\myuser\\.local\\bin\\uv` and `C:\\Users\\myuser\\netbox-mcp-server`.
> For detailed troubleshooting, consult the [MCP quickstart](https://modelcontextprotocol.io/quickstart/user).

### Examples

Use the tools in your LLM client. For example:

```text
> Get all devices in the 'Equinix DC14' site
...
> Tell me about my IPAM utilization
...
> What Cisco devices are in my network?
...
> Who made changes to the NYC site in the last week?
...
> Show me all configuration changes to the core router in the last month
```

#### Creating VLANs and Prefixes

The server supports creating VLANs and their associated prefixes via a two-step review-and-confirm workflow:

```text
Hello,
please create two new vlans for Bonn:
/28 PLC3
/28 PLC4

Thank you
```

The LLM will:
1. Look up the site summary prefixes for Bonn to find the correct parent prefix
2. Find the next two available `/28` subnets
3. Determine the correct VLAN IDs and role
4. Call `netbox_review_vlan_prefix_plan` to show you a summary table for review
5. Only after your explicit confirmation call `netbox_create_vlan_prefix_batch` to create the VLANs and prefixes

> **Rules enforced automatically:**
> - Each prefix must have a role: `access` or `production`
> - Production prefixes use VLAN IDs in the range 400–499
> - VLAN names are derived from the description (max 15 characters)
> - If the site has a tenant, it is automatically applied to both VLAN and prefix
> - Duplicate VLAN IDs within the same VLAN group are detected and reported before creation

### Field Filtering (Token Optimization)

Both `netbox_get_objects()` and `netbox_get_object_by_id()` support an optional `fields` parameter to reduce token usage:

```python
# Without fields: ~5000 tokens for 50 devices
devices = netbox_get_objects('devices', {'site': 'datacenter-1'})

# With fields: ~500 tokens (90% reduction)
devices = netbox_get_objects(
    'devices',
    {'site': 'datacenter-1'},
    fields=['id', 'name', 'status', 'site']
)
```

**Common field patterns:**

- **Devices:** `['id', 'name', 'status', 'device_type', 'site', 'primary_ip4']`
- **IP Addresses:** `['id', 'address', 'status', 'dns_name', 'description']`
- **Interfaces:** `['id', 'name', 'type', 'enabled', 'device']`
- **Sites:** `['id', 'name', 'status', 'region', 'description']`

The `fields` parameter uses NetBox's native field filtering. See the [NetBox API documentation](https://docs.netbox.dev/en/stable/integrations/rest-api/) for details.

### Startup Log

At startup the server logs all configuration values so you can verify the correct settings are active — useful when deploying to Azure Web App or other cloud environments. Tokens are partially masked (first 3 characters visible):

```
2025-01-01 12:00:00 - netbox_mcp_server.server - INFO - Starting NetBox MCP Server
2025-01-01 12:00:00 - netbox_mcp_server.server - INFO - Configuration:
2025-01-01 12:00:00 - netbox_mcp_server.server - INFO -   NETBOX_URL      = https://netbox.example.com/
2025-01-01 12:00:00 - netbox_mcp_server.server - INFO -   NETBOX_TOKEN    = c00****
2025-01-01 12:00:00 - netbox_mcp_server.server - INFO -   TRANSPORT       = http
2025-01-01 12:00:00 - netbox_mcp_server.server - INFO -   HOST            = 0.0.0.0
2025-01-01 12:00:00 - netbox_mcp_server.server - INFO -   PORT            = 8000
2025-01-01 12:00:00 - netbox_mcp_server.server - INFO -   VERIFY_SSL      = False
2025-01-01 12:00:00 - netbox_mcp_server.server - INFO -   MCP_TOKEN       = abc****
2025-01-01 12:00:00 - netbox_mcp_server.server - INFO -   LOG_LEVEL       = INFO
```

## Docker Usage

### Standard Docker Image

Build and run the NetBox MCP server in a container:

```bash
# Build the image
docker build -t netbox-mcp-server:latest .

# Run with HTTP transport (required for Docker containers)
docker run --rm \
  -e NETBOX_URL=https://netbox.example.com/ \
  -e NETBOX_TOKEN=<your-api-token> \
  -e MCP_TOKEN=<your-api-token> \
  -e TRANSPORT=http \
  -e HOST=0.0.0.0 \
  -e PORT=8000 \
  -p 8000:8000 \
  netbox-mcp-server:latest
```

> **Note:** Docker containers require `TRANSPORT=http` since stdio transport doesn't work in containerized environments.

**Connecting to NetBox on your host machine:**

If your NetBox instance is running on your host machine (not in a container), you need to use `host.docker.internal` instead of `localhost` on macOS and Windows:

```bash
# For NetBox running on host (macOS/Windows)
docker run --rm \
  -e NETBOX_URL=http://host.docker.internal:18000/ \
  -e NETBOX_TOKEN=<your-api-token> \
  -e MCP_TOKEN=<your-api-token> \
  -e TRANSPORT=http \
  -e HOST=0.0.0.0 \
  -e PORT=8000 \
  -p 8000:8000 \
  netbox-mcp-server:latest
```

> **Note:** On Linux, you can use `--network host` instead, or use the host's IP address directly.

**With additional configuration options:**

```bash
docker run --rm \
  -e NETBOX_URL=https://netbox.example.com/ \
  -e NETBOX_TOKEN=<your-api-token> \
  -e TRANSPORT=http \
  -e HOST=0.0.0.0 \
  -e LOG_LEVEL=DEBUG \
  -e VERIFY_SSL=false \
  -p 8000:8000 \
  netbox-mcp-server:latest
```

The server will be accessible at `http://localhost:8000/mcp` for MCP clients.

## Development

After cloning the repository, install dependencies and activate the pre-commit hooks:

```bash
uv sync
uv run pre-commit install
```

The pre-commit hooks run automatically on every `git commit`:

| Hook | What it does |
|------|-------------|
| `ruff-check --fix` | Lints the code and auto-fixes where possible |
| `ruff-format` | Formats the code (Black-compatible style) |
| `pytest` | Runs the full test suite |

If a hook fails, the commit is aborted. Fix the reported issues and commit again.

To run the hooks manually without committing:

```bash
uv run pre-commit run --all-files
```

## License

This project is licensed under the Apache 2.0 license.  See the LICENSE file for details.
