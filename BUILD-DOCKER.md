# Docker Build & Run Guide

## Build the Image

```bash
docker build -t netbox-mcp-server:latest .
```

## Run the Container

> **Note:** Docker containers must use `TRANSPORT=http` — stdio transport does not work in containers.

### Standard (port mapping)

```bash
docker run --rm \
  -e NETBOX_URL=https://netbox.example.com/ \
  -e NETBOX_TOKEN=<your-api-token> \
  -e TRANSPORT=http \
  -e HOST=0.0.0.0 \
  -e PORT=8000 \
  -p 8000:8000 \
  netbox-mcp-server:latest
```

The MCP endpoint is available at `http://localhost:8000/mcp`.

### Host Network (Linux only)

Use this when NetBox runs on the same host machine:

```bash
docker run --rm \
  --network host \
  -e NETBOX_URL=http://localhost:18000/ \
  -e NETBOX_TOKEN=<your-api-token> \
  -e TRANSPORT=http \
  -e HOST=0.0.0.0 \
  -e PORT=8000 \
  netbox-mcp-server:latest
```

### NetBox on Host (macOS/Windows)

Use `host.docker.internal` to reach the host machine from a container:

```bash
docker run --rm \
  -e NETBOX_URL=http://host.docker.internal:18000/ \
  -e NETBOX_TOKEN=<your-api-token> \
  -e TRANSPORT=http \
  -e HOST=0.0.0.0 \
  -e PORT=8000 \
  -p 8000:8000 \
  netbox-mcp-server:latest
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NETBOX_URL` | Yes | - | Base URL of your NetBox instance |
| `NETBOX_TOKEN` | Yes | - | Read-only API token |
| `TRANSPORT` | Yes (Docker) | `stdio` | Must be `http` for containers |
| `HOST` | Yes (Docker) | `127.0.0.1` | Use `0.0.0.0` to accept external connections |
| `PORT` | No | `8000` | HTTP server port |
| `VERIFY_SSL` | No | `true` | Set `false` to skip SSL verification |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |

## Connect with Claude Code

Once the container is running, register the server:

```bash
claude mcp add --transport http netbox http://127.0.0.1:8000/mcp
```

Verify the connection:

```bash
claude mcp list
```

You should see a `✓` next to `netbox`.
