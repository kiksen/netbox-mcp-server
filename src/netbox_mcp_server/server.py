import logging
import sys
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from fastmcp.dependencies import CurrentContext
from fastmcp.server.auth.auth import AccessToken, TokenVerifier
from fastmcp.server.lifespan import lifespan
from pydantic import Field

from netbox_mcp_server import constants as CONST
from netbox_mcp_server.client.netbox_client import NetBoxRestClient
from netbox_mcp_server.config import Settings, configure_logging
from netbox_mcp_server.depends import get_adapter
from netbox_mcp_server.netbox_types import NETBOX_OBJECT_TYPES

logger = logging.getLogger(__name__)


settings: Settings | None = None


class StaticBearerTokenVerifier(TokenVerifier):
    """Verifies Bearer tokens against a single static token from configuration."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        if token == self._token:
            return AccessToken(token=token, client_id="mcp-client", scopes=[])
        return None


# ck @asynccontextmanager
@lifespan
async def server_lifespan(server):
    if settings is None:
        raise RuntimeError("settings must be initialized before server start")
    try:
        client = NetBoxRestClient(
            url=str(settings.netbox_url),
            token=settings.netbox_token.get_secret_value(),
            verify_ssl=settings.verify_ssl,
        )
        logger.debug("NetBox client initialized successfully")
        yield {"netbox": client}
    except Exception as e:
        logger.error(f"Failed to initialize NetBox client: {e}")
        raise


mcp = FastMCP("NetBox", instructions=CONST.INSTRUCTIONS, lifespan=server_lifespan)


@mcp.tool(
    description="""
    Get objects from NetBox based on their type and filters

    Args:
        object_type: String representing the NetBox object type (e.g. "dcim.device", "ipam.ipaddress")
        filters: dict of filters to apply to the API call based on the NetBox API filtering options

                FILTER RULES:
                Valid: Direct fields like {'site_id': 1, 'name': 'router', 'status': 'active'}
                Valid: Lookups like {'name__ic': 'switch', 'id__in': [1,2,3], 'vid__gte': 100}
                Invalid: Multi-hop like {'device__site_id': 1} - NOT supported

                Lookup suffixes: n, ic, nic, isw, nisw, iew, niew, ie, nie,
                                 empty, regex, iregex, lt, lte, gt, gte, in

                Two-step pattern for cross-relationship queries:
                  sites = netbox_get_objects('dcim.site', {'name': 'NYC'})
                  netbox_get_objects('dcim.device', {'site_id': sites[0]['id']})

        fields: Optional list of specific fields to return
                **IMPORTANT: ALWAYS USE THIS PARAMETER TO MINIMIZE TOKEN USAGE**
                Field filtering significantly reduces response payload and is critical for performance.

                - None or [] = returns all fields (NOT RECOMMENDED - use only when you need complete objects)
                - ['id', 'name'] = returns only specified fields (RECOMMENDED)

                Examples:
                - For counting: ['id'] (minimal payload)
                - For listings: ['id', 'name', 'status']
                - For IP addresses: ['address', 'dns_name', 'description']

                Uses NetBox's native field filtering via ?fields= parameter.
                **Always specify only the fields you actually need.**

        brief: returns only a minimal representation of each object in the response.
               This is useful when you need only a list of available objects without any related data.

        limit: Maximum results to return (default 5, max 100)
               Start with default, increase only if needed

        offset: Skip this many results for pagination (default 0)
                Example: offset=0 (page 1), offset=5 (page 2), offset=10 (page 3)

        ordering: Fields used to determine sort order of results.
                  Field names may be prefixed with '-' to invert the sort order.
                  Multiple fields may be specified with a list of strings.

                  Examples:
                  - 'name' (alphabetical by name)
                  - '-id' (ordered by ID descending)
                  - ['facility', '-name'] (by facility, then by name descending)
                  - None, '' or [] (default NetBox ordering)


    Returns:
        Paginated response dict with the following structure:
            - count: Total number of objects matching the query
                     ALWAYS REFER TO THIS FIELD FOR THE TOTAL NUMBER OF OBJECTS MATCHING THE QUERY
            - next: URL to next page (or null if no more pages)
                    ALWAYS REFER TO THIS FIELD FOR THE NEXT PAGE OF RESULTS
            - previous: URL to previous page (or null if on first page)
                        ALWAYS REFER TO THIS FIELD FOR THE PREVIOUS PAGE OF RESULTS
            - results: Array of objects for this page
                       ALWAYS REFER TO THIS FIELD FOR THE OBJECTS ON THIS PAGE

    ENSURE YOU ARE AWARE THE RESULTS ARE PAGINATED BEFORE PROVIDING RESPONSE TO THE USER.

    IMPORTANT: If the result contains multiple objects and the user needs to select one
    to proceed (e.g. choosing a site, device, or prefix), present the options using the
    AskUserQuestion tool before continuing.

    Valid object_type values:

    """
    + "\n".join(f"- {t}" for t in sorted(NETBOX_OBJECT_TYPES.keys()))
    + """

    See NetBox API documentation for filtering options for each object type.
    """
)
def netbox_get_objects(
    object_type: str,
    filters: dict[str, Any],
    fields: list[str] | None = None,
    brief: bool = False,
    limit: Annotated[int, Field(default=5, ge=1, le=100)] = 5,
    offset: Annotated[int, Field(default=0, ge=0)] = 0,
    ordering: str | list[str] | None = None,
    ctx: Context = CurrentContext(),
):
    """
    Get objects from NetBox based on their type and filters
    """
    nb = get_adapter(ctx)
    return nb.get_objects(object_type, filters, fields, brief, limit, offset, ordering)


@mcp.tool
def netbox_get_object_by_id(
    object_type: str,
    object_id: int,
    fields: list[str] | None = None,
    brief: bool = False,
    ctx: Context = CurrentContext(),
):
    """
    Get detailed information about a specific NetBox object by its ID.

    Args:
        object_type: String representing the NetBox object type (e.g. "dcim.device", "ipam.ipaddress")
        object_id: The numeric ID of the object
        fields: Optional list of specific fields to return
                **IMPORTANT: ALWAYS USE THIS PARAMETER TO MINIMIZE TOKEN USAGE**
                Field filtering reduces response payload by 80-90% and is critical for performance.

                - None or [] = returns all fields (NOT RECOMMENDED - use only when you need complete objects)
                - ['id', 'name'] = returns only specified fields (RECOMMENDED)

                Examples:
                - For basic info: ['id', 'name', 'status']
                - For devices: ['id', 'name', 'status', 'site']
                - For IP addresses: ['address', 'dns_name', 'vrf', 'status']

                Uses NetBox's native field filtering via ?fields= parameter.
                **Always specify only the fields you actually need.**
        brief: returns only a minimal representation of the object in the response.
               This is useful when you need only a summary of the object without any related data.

    Returns:
        Object dict (complete or with only requested fields based on fields parameter)
    """
    nb = get_adapter(ctx)
    return nb.get_object_by_id(object_type, object_id, fields, brief)


@mcp.tool
def netbox_get_changelogs(filters: dict[str, Any], ctx: Context = CurrentContext()):
    """
    Get object change records (changelogs) from NetBox based on filters.

    Args:
        filters: dict of filters to apply to the API call based on the NetBox API filtering options

    Returns:
        Paginated response dict with the following structure:
            - count: Total number of changelog entries matching the query
                     ALWAYS REFER TO THIS FIELD FOR THE TOTAL NUMBER OF CHANGELOG ENTRIES MATCHING THE QUERY
            - next: URL to next page (or null if no more pages)
                    ALWAYS REFER TO THIS FIELD FOR THE NEXT PAGE OF RESULTS
            - previous: URL to previous page (or null if on first page)
                        ALWAYS REFER TO THIS FIELD FOR THE PREVIOUS PAGE OF RESULTS
            - results: Array of changelog entries for this page
                       ALWAYS REFER TO THIS FIELD FOR THE CHANGELOG ENTRIES ON THIS PAGE

    Filtering options include:
    - user_id: Filter by user ID who made the change
    - user: Filter by username who made the change
    - changed_object_type_id: Filter by numeric ContentType ID (e.g., 21 for dcim.device)
                              Note: This expects a numeric ID, not an object type string
    - changed_object_id: Filter by ID of the changed object
    - object_repr: Filter by object representation (usually contains object name)
    - action: Filter by action type (created, updated, deleted)
    - time_before: Filter for changes made before a given time (ISO 8601 format)
    - time_after: Filter for changes made after a given time (ISO 8601 format)
    - q: Search term to filter by object representation

    Examples:
    To find all changes made to a specific object by ID:
    {"changed_object_id": 123}

    To find changes by object name pattern:
    {"object_repr": "router-01"}

    To find all deletions in the last 24 hours:
    {"action": "delete", "time_after": "2023-01-01T00:00:00Z"}

    Each changelog entry contains:
    - id: The unique identifier of the changelog entry
    - user: The user who made the change
    - user_name: The username of the user who made the change
    - request_id: The unique identifier of the request that made the change
    - action: The type of action performed (created, updated, deleted)
    - changed_object_type: The type of object that was changed
    - changed_object_id: The ID of the object that was changed
    - object_repr: String representation of the changed object
    - object_data: The object's data after the change (null for deletions)
    - object_data_v2: Enhanced data representation
    - prechange_data: The object's data before the change (null for creations)
    - postchange_data: The object's data after the change (null for deletions)
    - time: The timestamp when the change was made
    """
    nb = get_adapter(ctx)
    return nb.get_changelogs(filters)


@mcp.tool(
    description="""
    Perform global search across NetBox infrastructure.

    Searches names, descriptions, IP addresses, serial numbers, asset tags,
    and other key fields across multiple object types.

    Args:
        query: Search term (device names, IPs, serial numbers, hostnames, site names)
               Examples: 'switch01', '192.168.1.1', 'NYC-DC1', 'SN123456'
        object_types: Limit search to specific types (optional)
                     Default: ["""
    + "', '".join(CONST.DEFAULT_SEARCH_TYPES)
    + """]
                     Examples: ['dcim.device', 'ipam.ipaddress', 'dcim.site']
        fields: Optional list of specific fields to return (reduces response size) IT IS STRONGLY RECOMMENDED TO USE THIS PARAMETER TO MINIMIZE TOKEN USAGE.
                - None or [] = returns all fields (no filtering)
                - ['id', 'name'] = returns only specified fields
                Examples: ['id', 'name', 'status'], ['address', 'dns_name']
                Uses NetBox's native field filtering via ?fields= parameter
        limit: Max results per object type (default 5, max 100)

    Returns:
        Dictionary with object_type keys and list of matching objects.
        All searched types present in result (empty list if no matches).

    Example:
        # Search for anything matching "switch"
        results = netbox_search_objects('switch')
        # Returns: {
        #   'dcim.device': [{'id': 1, 'name': 'switch-01', ...}],
        #   'dcim.site': [],
        #   ...
        # }

        # Search for IP address
        results = netbox_search_objects('192.168.1.100')
        # Returns: {
        #   'ipam.ipaddress': [{'id': 42, 'address': '192.168.1.100/24', ...}],
        #   ...
        # }

        # Limit search to specific types with field projection
        results = netbox_search_objects(
            'NYC',
            object_types=['dcim.site', 'dcim.location'],
            fields=['id', 'name', 'status']
        )

    IMPORTANT: If the search returns multiple results and the user needs to select one
    to proceed, present the matching objects as selectable options using the
    AskUserQuestion tool before continuing.
    """
)
def netbox_search_objects(
    query: str,
    object_types: list[str] | None = None,
    fields: list[str] | None = None,
    limit: Annotated[int, Field(default=5, ge=1, le=100)] = 5,
    ctx: Context = CurrentContext(),
) -> dict[str, list[dict[str, Any]]]:
    """
    Perform global search across NetBox infrastructure.
    """
    nb = get_adapter(ctx)
    search_types = object_types if object_types is not None else CONST.DEFAULT_SEARCH_TYPES
    return nb.search_objects(query, search_types, fields, limit)


@mcp.tool(
    description="""
    Get the next available prefix of a given size within a NetBox container prefix.

    Args:
        parent_prefix: CIDR notation of the container prefix (e.g. "10.0.0.0/16")
        site: Site name or slug to narrow the search (e.g. "Bonn" or "bonn")
        prefix_length: Desired prefix length (e.g. 26 for a /26)

    Returns:
        Dict with:
          - next_available_prefix: CIDR of the first available subnet (e.g. "10.0.1.128/26")
          - container: Info about the container prefix (id, prefix, site, status)
          - available_block: The free block from which the subnet was carved
    """,
)
def netbox_get_next_available_prefix(
    parent_prefix: Annotated[
        str, Field(description="CIDR of the container prefix, e.g. '10.0.0.0/16'")
    ],
    site: Annotated[str, Field(description="Site name or slug, e.g. 'Bonn' or 'bonn'")],
    prefix_length: Annotated[
        int, Field(description="Desired prefix length (1-128), e.g. 26 for /26")
    ],
    ctx: Context = CurrentContext(),
) -> dict[str, Any]:
    nb = get_adapter(ctx)
    return nb.get_next_available_prefix(parent_prefix, site, prefix_length)


@mcp.tool(
    description="""
    Get all prefixes with IPAM role 'site-summary' for a specific site.

    This tool retrieves all summary prefixes assigned to a site, which are used
    to document the overall IP address space allocated to that site.

    Args:
        site: Site name or slug (e.g. "Berlin" or "berlin")
        fields: Optional list of specific fields to return to minimize token usage.
                - None or [] = returns all fields
                - ['prefix', 'description', 'status'] = returns only specified fields
        limit: Maximum results to return (default 100, max 1000)
        offset: Skip this many results for pagination (default 0)

    Returns:
        Paginated response dict with:
            - count: Total number of matching prefixes
            - next: URL to next page (or null)
            - previous: URL to previous page (or null)
            - results: List of prefix objects

    IMPORTANT: If the result contains more than one prefix, present all of them
    as selectable options using the AskUserQuestion tool before proceeding.
    """,
)
def netbox_get_site_summary_prefixes(
    site: Annotated[str, Field(description="Site name or slug, e.g. 'Berlin' or 'berlin'")],
    fields: list[str] | None = None,
    limit: Annotated[int, Field(default=100, ge=1, le=1000)] = 100,
    offset: Annotated[int, Field(default=0, ge=0)] = 0,
    ctx: Context = CurrentContext(),
) -> dict[str, Any] | list[dict[str, Any]]:
    """
    Get all prefixes with IPAM role 'site-summary' for a specific site.
    """
    nb = get_adapter(ctx)
    return nb.get_site_summary_prefixes(site, fields, limit, offset)


@mcp.tool(
    description="""
    Get all VLAN groups scoped to a specific site.

    Args:
        site_slug: The slug of the site (e.g. "bonn")
        fields: Optional list of specific fields to return to minimize token usage.
                - None or [] = returns all fields
                - ['id', 'name', 'slug'] = returns only specified fields

    Returns:
        Paginated response dict with:
            - count: Total number of matching VLAN groups
            - next: URL to next page (or null)
            - previous: URL to previous page (or null)
            - results: List of VLAN group objects

    IMPORTANT: If the result contains more than one VLAN group, present all of them
    as selectable options using the AskUserQuestion tool before proceeding.
    """,
)
def netbox_get_vlan_groups_for_site(
    site_slug: Annotated[str, Field(description="Site slug, e.g. 'bonn'")],
    fields: list[str] | None = None,
    ctx: Context = CurrentContext(),
) -> dict[str, Any] | list[dict[str, Any]]:
    """
    Get all VLAN groups scoped to a specific site.
    """
    nb = get_adapter(ctx)
    return nb.get_vlan_groups_for_site(site_slug, fields)


@mcp.tool(
    description="""
    Get all VLANs for a specific site by resolving the site's VLAN group.

    Args:
        site_slug: The slug of the site (e.g. "bonn")

    Returns:
        Dict with:
          - count: Total number of VLANs
          - vlan_group: The resolved VLAN group (id, name)
          - results: List of VLANs with only id, vid, name
    """,
)
def netbox_get_vlans_for_site(
    site_slug: Annotated[str, Field(description="Site slug, e.g. 'bonn'")],
    ctx: Context = CurrentContext(),
) -> dict[str, Any]:
    """
    Get all VLANs for a specific site by resolving the site's VLAN group.
    """
    nb = get_adapter(ctx)
    return nb.get_vlans_for_site(site_slug)


@mcp.tool(
    description="""
    Check whether a VLAN ID already exists within a specific VLAN group.

    Args:
        vlan_group_id: The numeric ID of the VLAN group to check
        vid: The VLAN ID to look for (1-4094)

    Returns:
        Dict with:
            - exists: True if the VLAN ID is already used in this group, False otherwise
            - vlan: The matching VLAN object if found, null otherwise
    """,
)
def netbox_check_vlan_id_in_vlan_group(
    vlan_group_id: Annotated[int, Field(description="Numeric ID of the VLAN group")],
    vid: Annotated[int, Field(description="VLAN ID to check (1-4094)", ge=1, le=4094)],
    ctx: Context = CurrentContext(),
) -> dict[str, Any]:
    """
    Check whether a VLAN ID already exists within a specific VLAN group.
    """
    nb = get_adapter(ctx)
    return nb.check_vlan_id_in_vlan_group(vlan_group_id, vid)


@mcp.tool(
    description="""
    Present a plan of VLANs and prefixes for user confirmation BEFORE creating them.

    This tool MUST be called before netbox_create_vlan_prefix_batch to let the user
    review and confirm all planned entries. It shows the site details and a structured
    table of the planned VLANs/prefixes.

    Rules that are validated:
    - role must be 'access' or 'production'
    - production prefixes must have a VLAN ID between 400 and 499

    Conflict detection:
    - If a VLAN ID already exists in the site's VLAN group, its current name,
      description and associated prefixes are shown so the user can decide whether
      to overwrite.
    - If a vlan description or a vlan name is already used, ask the user to decide whether to overwrite.

    Args:
        site_slug: Slug of the target site (e.g. "bonn")
        entries: List of planned entries, each with:
                 - vlan_id: The VLAN ID (1-4094)
                 - prefix: The prefix in CIDR notation (e.g. "10.200.1.0/24")
                 - role: IPAM role, either 'access' or 'production'
                 - description: Description for VLAN and prefix

    Returns:
        Dict with:
            - confirmed: Always False - user must explicitly confirm via separate call
            - site: Site details (name, slug, tenant)
            - plan: List of validated entries with warnings
            - conflicts: List of VLAN IDs that already exist, with current details
            - validation_errors: List of rule violations found
            - summary: Human-readable summary table for display
    """,
)
def netbox_review_vlan_prefix_plan(
    site_slug: Annotated[str, Field(description="Site slug, e.g. 'bonn'")],
    entries: Annotated[
        list[dict[str, Any]],
        Field(
            description="List of dicts with keys: vlan_id (int), prefix (str), role (str), description (str)"
        ),
    ],
    ctx: Context = CurrentContext(),
) -> dict[str, Any]:
    """
    Present a plan of VLANs and prefixes for user confirmation before creation.
    """
    nb = get_adapter(ctx)
    return nb.review_vlan_prefix_plan(site_slug, entries)


@mcp.tool(
    description="""
    Create VLANs and their associated prefixes in NetBox for a specific site.

    IMPORTANT: This tool MUST only be called after netbox_review_vlan_prefix_plan has been
    presented to the user and the user has explicitly confirmed the plan. The 'confirmed'
    parameter must be set to True to proceed - set it to True ONLY after the user has
    reviewed the summary table and given explicit approval.

    For each entry the tool will:
      1. Create a VLAN with the given vlan_id in the site's VLAN group
      2. Create a prefix linked to the VLAN, with the correct role and site

    If a VLAN already exists and overwrite_existing_vlans is False (default), the entry
    is skipped with an error. Set overwrite_existing_vlans=True only after the user has
    explicitly confirmed overwriting the conflicting VLANs shown by netbox_review_vlan_prefix_plan.

    If the site has a tenant, the tenant is automatically applied to both VLAN and prefix.

    Args:
        site_slug: Slug of the target site (e.g. "bonn")
        entries: List of entries to create, each with:
                 - vlan_id: The VLAN ID (1-4094)
                 - prefix: The prefix in CIDR notation (e.g. "10.200.0.0/28")
                 - role: IPAM role slug, either 'access' or 'production'
                 - description: Description applied to both VLAN and prefix
                 - vlan_name: Optional VLAN name (defaults to "VLAN-<vlan_id>")
        confirmed: Must be True - only set after user has explicitly approved the plan
                   shown by netbox_review_vlan_prefix_plan
        overwrite_existing_vlans: If True, existing VLANs are reused and their description
                                  is updated. Only set after user confirmed overwrite.

    Returns:
        Dict with:
            - created: List of created objects, each with 'vlan' and 'prefix' sub-dicts
            - errors: List of errors that occurred during creation
    """,
)
def netbox_create_vlan_prefix_batch(
    site_slug: Annotated[str, Field(description="Site slug, e.g. 'bonn'")],
    entries: Annotated[
        list[dict[str, Any]],
        Field(
            description="List of dicts with keys: vlan_id (int), prefix (str), role (str), description (str), vlan_name (str, optional)"
        ),
    ],
    confirmed: Annotated[
        bool,
        Field(description="Must be True - only set after user has explicitly approved the plan"),
    ],
    overwrite_existing_vlans: Annotated[
        bool,
        Field(
            description="If True, existing VLANs are reused and updated. Only set after user confirmed overwrite."
        ),
    ] = False,
    ctx: Context = CurrentContext(),
) -> dict[str, Any]:
    """
    Create VLANs and prefixes in NetBox after user confirmation.
    """
    nb = get_adapter(ctx)
    return nb.create_vlan_prefix_batch(site_slug, entries, confirmed, overwrite_existing_vlans)


def main() -> None:
    """Main entry point for the MCP server."""
    global settings

    try:
        settings = Settings()
    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    configure_logging(settings.log_level)

    if settings.mcp_token:
        mcp.auth = StaticBearerTokenVerifier(settings.mcp_token.get_secret_value())
        logger.info("MCP Bearer token authentication enabled")
    else:
        logger.warning("MCP_TOKEN is not set — the HTTP endpoint is publicly accessible")

    logger.info("Starting NetBox MCP Server")
    logger.info("Configuration:")
    for key, value in settings.get_effective_config_summary().items():
        logger.info(f"  {key:<15} = {value}")

    if not settings.verify_ssl:
        logger.warning(
            "SSL certificate verification is DISABLED. "
            "This is insecure and should only be used for testing."
        )

    if settings.transport == "http" and settings.host in [
        "0.0.0.0",
        "::",
        "[::]",
    ]:
        logger.warning(
            f"HTTP transport is bound to {settings.host}:{settings.port}, which exposes the "
            "service to all network interfaces (IPv4/IPv6). This is insecure and should only be "
            "used for testing. Ensure this is secured with TLS/reverse proxy if exposed to network."
        )
    elif settings.transport == "http" and settings.host not in [
        "127.0.0.1",
        "localhost",
    ]:
        logger.info(
            f"HTTP transport is bound to {settings.host}:{settings.port}. "
            "Ensure this is secured with TLS/reverse proxy if exposed to network."
        )

    try:
        if settings.transport == "stdio":
            logger.info("Starting stdio transport")
            mcp.run(transport="stdio")
        elif settings.transport == "http":
            logger.info(f"Starting HTTP transport on {settings.host}:{settings.port}")
            mcp.run(transport="http", host=settings.host, port=settings.port)
    except Exception as e:
        logger.error(f"Failed to start MCP server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
