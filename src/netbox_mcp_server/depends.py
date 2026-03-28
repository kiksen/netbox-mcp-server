from fastmcp import Context

from netbox_mcp_server.adapter.netbox_adapter import NetboxAdapter


def get_adapter(ctx: Context) -> NetboxAdapter:
    return NetboxAdapter(netbox=ctx.fastmcp._lifespan_result["netbox"])
