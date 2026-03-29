from typing import Any, cast

from fastmcp import Context

from netbox_mcp_server.adapter.netbox_adapter import NetboxAdapter


def get_adapter(ctx: Context) -> NetboxAdapter:
    lifespan_result = cast(dict[str, Any], ctx.fastmcp._lifespan_result)
    return NetboxAdapter(netbox=lifespan_result["netbox"])
