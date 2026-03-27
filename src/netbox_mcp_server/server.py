import argparse
import logging
import sys
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from netbox_mcp_server.config import Settings, configure_logging
from netbox_mcp_server.netbox_client import NetBoxRestClient
from netbox_mcp_server.netbox_types import NETBOX_OBJECT_TYPES


def parse_cli_args() -> dict[str, Any]:
    """
    Parse command-line arguments for configuration overrides.

    Returns:
        dict of configuration overrides (only includes explicitly set values)
    """
    parser = argparse.ArgumentParser(
        description="NetBox MCP Server - Model Context Protocol server for NetBox",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Core NetBox settings
    parser.add_argument(
        "--netbox-url",
        type=str,
        help="Base URL of the NetBox instance (e.g., https://netbox.example.com/)",
    )
    parser.add_argument(
        "--netbox-token",
        type=str,
        help="API token for NetBox authentication",
    )

    # Transport settings
    parser.add_argument(
        "--transport",
        type=str,
        choices=["stdio", "http"],
        help="MCP transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        type=str,
        help="Host address for HTTP server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Port for HTTP server (default: 8000)",
    )

    # Security settings
    ssl_group = parser.add_mutually_exclusive_group()
    ssl_group.add_argument(
        "--verify-ssl",
        action="store_true",
        dest="verify_ssl",
        default=None,
        help="Verify SSL certificates (default)",
    )
    ssl_group.add_argument(
        "--no-verify-ssl",
        action="store_false",
        dest="verify_ssl",
        help="Disable SSL certificate verification (not recommended)",
    )

    # Observability settings
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity level (default: INFO)",
    )

    args: argparse.Namespace = parser.parse_args()

    overlay: dict[str, Any] = {}
    if args.netbox_url is not None:
        overlay["netbox_url"] = args.netbox_url
    if args.netbox_token is not None:
        overlay["netbox_token"] = args.netbox_token
    if args.transport is not None:
        overlay["transport"] = args.transport
    if args.host is not None:
        overlay["host"] = args.host
    if args.port is not None:
        overlay["port"] = args.port
    if args.verify_ssl is not None:
        overlay["verify_ssl"] = args.verify_ssl
    if args.log_level is not None:
        overlay["log_level"] = args.log_level

    return overlay


# valid ipam roles
VALID_IPAM_ROLES = {"access", "production"}

# production vlan_range
PRODUCTION_VLAN_RANGE = (400, 499)


# Default object types for global search
DEFAULT_SEARCH_TYPES = [
    "dcim.device",  # Most common search target
    "dcim.site",  # Site names frequently searched
    "ipam.ipaddress",  # IP searches very common
    "dcim.interface",  # Interface names/descriptions
    "dcim.rack",  # Rack identifiers
    "ipam.vlan",  # VLAN names/IDs
    "circuits.circuit",  # Circuit identifiers
    "virtualization.virtualmachine",  # VM names
]

INSTRUCTIONS = """
This mcp server is used for netbox. 

Some general netbox rules for vlan and prefix creation:
- A prefix can be called prefix, network or subnet
- each prefix needs to have a role: access or production
- production prefixes have vlans in the vlan range between 400 to 499
- this mcp server creates need to be part of a vlan_group to ensure there are no duplicate groups
- ech prefix has the scope site.
- if the site you are creating a prefix has a tenant, set also the tenant of the site equal to the prefix
- always ask the user to verify all settings before creating a prefix with vlan id, site and role
- vlan names are derived from the desctipion and need to be not longer than 15 characters

To create a new prefix the user will ask to create a new network with the following subnet mask e.g. /24 for a specific site.
As a next step get the the correct site-summary.
If you know the site-summary get the next free prefix with the specific subnet size
"""

mcp = FastMCP("NetBox", instructions=INSTRUCTIONS)
netbox = None


def validate_filters(filters: dict) -> None:
    """
    Validate that filters don't use multi-hop relationship traversal.

    NetBox API does not support nested relationship queries like:
    - device__site_id (filtering by related object's field)
    - interface__device__site (multiple relationship hops)

    Valid patterns:
    - Direct field filters: site_id, name, status
    - Lookup expressions: name__ic, status__in, id__gt

    Args:
        filters: Dictionary of filter parameters

    Raises:
        ValueError: If filter uses invalid multi-hop relationship traversal
    """
    valid_suffixes = {
        "n",
        "ic",
        "nic",
        "isw",
        "nisw",
        "iew",
        "niew",
        "ie",
        "nie",
        "empty",
        "regex",
        "iregex",
        "lt",
        "lte",
        "gt",
        "gte",
        "in",
    }

    for filter_name in filters:
        # Skip special parameters
        if filter_name in ("limit", "offset", "fields", "q"):
            continue

        if "__" not in filter_name:
            continue

        parts = filter_name.split("__")

        # Allow field__suffix pattern (e.g., name__ic, id__gt)
        if len(parts) == 2 and parts[-1] in valid_suffixes:
            continue
        # Block multi-hop patterns and invalid suffixes
        if len(parts) >= 2:
            raise ValueError(
                f"Invalid filter '{filter_name}': Multi-hop relationship "
                f"traversal or invalid lookup suffix not supported. Use direct field filters like "
                f"'site_id' or two-step queries."
            )


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

    Valid object_type values:

    """
    + "\n".join(f"- {t}" for t in sorted(NETBOX_OBJECT_TYPES.keys()))
    + """

    See NetBox API documentation for filtering options for each object type.
    """
)
def netbox_get_objects(
    object_type: str,
    filters: dict,
    fields: list[str] | None = None,
    brief: bool = False,
    limit: Annotated[int, Field(default=5, ge=1, le=100)] = 5,
    offset: Annotated[int, Field(default=0, ge=0)] = 0,
    ordering: str | list[str] | None = None,
):
    """
    Get objects from NetBox based on their type and filters
    """
    # Validate object_type exists in mapping
    if object_type not in NETBOX_OBJECT_TYPES:
        valid_types = "\n".join(f"- {t}" for t in sorted(NETBOX_OBJECT_TYPES.keys()))
        raise ValueError(f"Invalid object_type. Must be one of:\n{valid_types}")

    # Validate filter patterns
    validate_filters(filters)

    # Get API endpoint and fallback from mapping
    endpoint, fallback = _get_endpoint_info(object_type)

    # Build params with pagination (parameters override filters dict)
    params = filters.copy()
    params["limit"] = limit
    params["offset"] = offset

    if fields:
        params["fields"] = ",".join(fields)

    if brief:
        params["brief"] = "1"

    if ordering:
        if isinstance(ordering, list):
            ordering = ",".join(ordering)
        if ordering.strip() != "":
            params["ordering"] = ordering

    # Make API call
    return netbox.get(endpoint, params=params, fallback_endpoint=fallback)


@mcp.tool
def netbox_get_object_by_id(
    object_type: str,
    object_id: int,
    fields: list[str] | None = None,
    brief: bool = False,
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
    # Validate object_type exists in mapping
    if object_type not in NETBOX_OBJECT_TYPES:
        valid_types = "\n".join(f"- {t}" for t in sorted(NETBOX_OBJECT_TYPES.keys()))
        raise ValueError(f"Invalid object_type. Must be one of:\n{valid_types}")

    # Get API endpoint and fallback from mapping
    endpoint, fallback = _get_endpoint_info(object_type)
    full_endpoint = f"{endpoint}/{object_id}"
    full_fallback = f"{fallback}/{object_id}" if fallback else None

    params = {}
    if fields:
        params["fields"] = ",".join(fields)

    if brief:
        params["brief"] = "1"

    return netbox.get(full_endpoint, params=params, fallback_endpoint=full_fallback)


@mcp.tool
def netbox_get_changelogs(filters: dict):
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
    endpoint = "core/object-changes"

    # Make API call
    return netbox.get(endpoint, params=filters)


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
    + "', '".join(DEFAULT_SEARCH_TYPES)
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
    """
)
def netbox_search_objects(
    query: str,
    object_types: list[str] | None = None,
    fields: list[str] | None = None,
    limit: Annotated[int, Field(default=5, ge=1, le=100)] = 5,
) -> dict[str, list[dict]]:
    """
    Perform global search across NetBox infrastructure.
    """
    search_types = object_types if object_types is not None else DEFAULT_SEARCH_TYPES

    # Validate all object types exist in mapping
    for obj_type in search_types:
        if obj_type not in NETBOX_OBJECT_TYPES:
            valid_types = "\n".join(
                f"- {t}" for t in sorted(NETBOX_OBJECT_TYPES.keys())
            )
            raise ValueError(
                f"Invalid object_type '{obj_type}'. Must be one of:\n{valid_types}"
            )

    results = {obj_type: [] for obj_type in search_types}

    # Build results dictionary (error-resilient)
    for obj_type in search_types:
        try:
            endpoint, fallback = _get_endpoint_info(obj_type)
            response = netbox.get(
                endpoint,
                params={
                    "q": query,
                    "limit": limit,
                    "fields": ",".join(fields) if fields else None,
                },
                fallback_endpoint=fallback,
            )
            # Extract results array from paginated response
            results[obj_type] = response.get("results", [])
        except Exception:  # noqa: S112 - intentional error-resilient search
            # Continue searching other types if one fails
            # results[obj_type] already has empty list
            continue

    return results


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
) -> dict:
    import ipaddress

    if not (1 <= prefix_length <= 128):
        raise ValueError(
            f"prefix_length must be between 1 and 128, got {prefix_length}"
        )

    # Step 1: Find the container prefix
    response = netbox.get(
        "ipam/prefixes",
        params={
            "prefix": parent_prefix,
            "site": site,
            "status": "container",
            "limit": 1,
        },
    )
    results = response.get("results", [])
    if not results:
        raise ValueError(
            f"No container prefix found for prefix='{parent_prefix}', site='{site}'"
        )
    container = results[0]
    container_id = container["id"]
    container_network = ipaddress.ip_network(container["prefix"], strict=False)

    # Step 2: Validate requested prefix length
    if prefix_length <= container_network.prefixlen:
        raise ValueError(
            f"prefix_length {prefix_length} must be greater than the container's "
            f"prefix length {container_network.prefixlen}"
        )

    # Step 3: Fetch available blocks from NetBox
    available = netbox.get(f"ipam/prefixes/{container_id}/available-prefixes")
    if not available:
        raise ValueError(
            f"No available prefixes in container '{parent_prefix}' at site '{site}'"
        )

    # Step 4: Find the first block large enough
    for block in available:
        block_network = ipaddress.ip_network(block["prefix"], strict=False)
        if block_network.prefixlen <= prefix_length:
            subnet = next(block_network.subnets(new_prefix=prefix_length))
            return {
                "next_available_prefix": str(subnet),
                "container": {
                    "id": container_id,
                    "prefix": container["prefix"],
                    "site": site,
                    "status": container.get("status", {}).get("value", "container"),
                },
                "available_block": block["prefix"],
            }

    raise ValueError(
        f"No available block large enough for /{prefix_length} in container "
        f"'{parent_prefix}' at site '{site}'"
    )


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
    """,
)
def netbox_get_site_summary_prefixes(
    site: Annotated[
        str, Field(description="Site name or slug, e.g. 'Berlin' or 'berlin'")
    ],
    fields: list[str] | None = None,
    limit: Annotated[int, Field(default=100, ge=1, le=1000)] = 100,
    offset: Annotated[int, Field(default=0, ge=0)] = 0,
) -> dict:
    """
    Get all prefixes with IPAM role 'site-summary' for a specific site.
    """
    params: dict[str, Any] = {
        "site": site,
        "role": "site-summary",
        "limit": limit,
        "offset": offset,
    }

    if fields:
        params["fields"] = ",".join(fields)

    return netbox.get("ipam/prefixes", params=params)


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
    """,
)
def netbox_get_vlan_groups_for_site(
    site_slug: Annotated[str, Field(description="Site slug, e.g. 'bonn'")],
    fields: list[str] | None = None,
) -> dict:
    """
    Get all VLAN groups scoped to a specific site.
    """
    # Step 1: resolve site slug -> site id
    site_response = netbox.get("dcim/sites", params={"slug": site_slug, "limit": 1})
    site_results = site_response.get("results", [])
    if not site_results:
        raise ValueError(f"No site found with slug '{site_slug}'")
    site_id = site_results[0]["id"]

    # Step 2: fetch VLAN groups scoped to this site
    params: dict[str, Any] = {
        "scope_type": "dcim.site",
        "scope_id": site_id,
    }
    if fields:
        params["fields"] = ",".join(fields)

    return netbox.get("ipam/vlan-groups", params=params)


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
) -> dict:
    """
    Get all VLANs for a specific site by resolving the site's VLAN group.
    """
    # Step 1: resolve site slug -> site id
    site_response = netbox.get("dcim/sites", params={"slug": site_slug, "limit": 1})
    site_results = site_response.get("results", [])
    if not site_results:
        raise ValueError(f"No site found with slug '{site_slug}'")
    site_id = site_results[0]["id"]

    # Step 2: fetch VLAN group scoped to this site
    group_response = netbox.get(
        "ipam/vlan-groups",
        params={"scope_type": "dcim.site", "scope_id": site_id, "limit": 1},
    )
    group_results = group_response.get("results", [])
    if not group_results:
        raise ValueError(f"No VLAN group found for site '{site_slug}'")
    vlan_group = group_results[0]

    # Step 3: fetch all VLANs in this group, only id/vid/name
    vlan_response = netbox.get(
        "ipam/vlans",
        params={
            "group_id": vlan_group["id"],
            "fields": "id,vid,name",
            "limit": 1000,
            "ordering": "vid",
        },
    )

    return {
        "count": vlan_response.get("count", 0),
        "vlan_group": {"id": vlan_group["id"], "name": vlan_group["name"]},
        "results": vlan_response.get("results", []),
    }


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
def netbox_check_vlan_id_in_group(
    vlan_group_id: Annotated[int, Field(description="Numeric ID of the VLAN group")],
    vid: Annotated[int, Field(description="VLAN ID to check (1-4094)", ge=1, le=4094)],
) -> dict:
    """
    Check whether a VLAN ID already exists within a specific VLAN group.
    """
    response = netbox.get(
        "ipam/vlans",
        params={"group_id": vlan_group_id, "vid": vid, "limit": 1},
    )
    results = response.get("results", [])
    return {
        "exists": len(results) > 0,
        "vlan": results[0] if results else None,
    }


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
        list[dict],
        Field(
            description="List of dicts with keys: vlan_id (int), prefix (str), role (str), description (str)"
        ),
    ],
) -> dict:
    """
    Present a plan of VLANs and prefixes for user confirmation before creation.
    """
    # Step 1: Resolve site
    site_response = netbox.get("dcim/sites", params={"slug": site_slug, "limit": 1})
    site_results = site_response.get("results", [])
    if not site_results:
        raise ValueError(f"No site found with slug '{site_slug}'")

    site = site_results[0]
    site_id = site["id"]
    site_info = {
        "id": site_id,
        "name": site["name"],
        "slug": site["slug"],
        "tenant": site.get("tenant", {}).get("name") if site.get("tenant") else None,
    }

    # Step 2: Resolve VLAN group for site
    vlan_group_response = netbox.get(
        "ipam/vlan-groups",
        params={"scope_type": "dcim.site", "scope_id": site_id, "limit": 1},
    )
    vlan_group_results = vlan_group_response.get("results", [])
    vlan_group_id = vlan_group_results[0]["id"] if vlan_group_results else None

    # Step 3: Validate each entry and detect conflicts
    validation_errors: list[str] = []
    conflicts: list[dict] = []
    plan: list[dict] = []

    for i, entry in enumerate(entries):
        vlan_id = entry.get("vlan_id")
        prefix = entry.get("prefix")
        role = entry.get("role")
        description = entry.get("description", "")
        warnings: list[str] = []

        # Validate required fields
        if vlan_id is None:
            validation_errors.append(f"Entry {i + 1}: missing 'vlan_id'")
        if not prefix:
            validation_errors.append(f"Entry {i + 1}: missing 'prefix'")
        if not role:
            validation_errors.append(f"Entry {i + 1}: missing 'role'")
            role = None
        if not description:
            validation_errors.append(
                f"Entry {i + 1} (VLAN {vlan_id}): missing 'description'"
            )

        # Validate role
        if role and role not in VALID_IPAM_ROLES:
            validation_errors.append(
                f"Entry {i + 1} (VLAN {vlan_id}): invalid role '{role}'. "
                f"Must be one of: {', '.join(sorted(VALID_IPAM_ROLES))}"
            )

        # Validate production VLAN range
        if role == "production" and vlan_id is not None:
            lo, hi = PRODUCTION_VLAN_RANGE
            if not (lo <= vlan_id <= hi):
                validation_errors.append(
                    f"Entry {i + 1} (VLAN {vlan_id}): production prefixes require "
                    f"VLAN ID between {lo} and {hi}, got {vlan_id}"
                )

        # Check for existing VLAN conflict
        existing_vlan = None
        if vlan_id is not None and vlan_group_id is not None:
            existing_resp = netbox.get(
                "ipam/vlans",
                params={"group_id": vlan_group_id, "vid": vlan_id, "limit": 1},
            )
            existing_results = existing_resp.get("results", [])
            if existing_results:
                ev = existing_results[0]
                # Fetch existing prefixes linked to this VLAN
                existing_prefixes_resp = netbox.get(
                    "ipam/prefixes",
                    params={"vlan_id": ev["id"], "limit": 10},
                )
                existing_prefix_list = [
                    p["prefix"] for p in existing_prefixes_resp.get("results", [])
                ]
                existing_vlan = {
                    "id": ev["id"],
                    "vid": ev["vid"],
                    "name": ev.get("name", ""),
                    "description": ev.get("description", ""),
                    "existing_prefixes": existing_prefix_list,
                }
                conflicts.append(existing_vlan)
                warnings.append(
                    f"VLAN {vlan_id} already exists: name='{ev.get('name')}', "
                    f"description='{ev.get('description')}', "
                    f"prefixes={existing_prefix_list or 'none'}"
                )

        plan.append(
            {
                "vlan_id": vlan_id,
                "prefix": prefix,
                "role": role,
                "description": description,
                "warnings": warnings,
                "existing_vlan": existing_vlan,
            }
        )

    # Step 4: Build summary table
    table_rows = []
    for entry in plan:
        conflict_marker = " ⚠" if entry["existing_vlan"] else ""
        table_rows.append(
            f"| {entry['vlan_id']}{conflict_marker} | {entry['prefix']} | {entry['role']} | {entry['description']} |"
        )

    summary = (
        f"Site: {site_info['name']} ({site_info['slug']})"
        + (f"  |  Tenant: {site_info['tenant']}" if site_info["tenant"] else "")
        + "\n\n"
        + "| VLAN ID | Prefix | IPAM Role | Description |\n"
        + "|---------|--------|-----------|-------------|\n"
        + "\n".join(table_rows)
    )

    if conflicts:
        summary += "\n\n**⚠ Conflicts – diese VLANs existieren bereits:**\n"
        for c in conflicts:
            summary += (
                f"- VLAN {c['vid']}: name=`{c['name']}`, "
                f"description=`{c['description']}`, "
                f"prefixes={c['existing_prefixes'] or 'none'}\n"
            )
        summary += (
            "\nUm vorhandene VLANs zu überschreiben, `overwrite_existing_vlans=true` "
            "in `netbox_create_vlan_prefix_batch` setzen."
        )

    if validation_errors:
        summary += "\n\n**Validation errors:**\n" + "\n".join(
            f"- {e}" for e in validation_errors
        )

    return {
        "confirmed": False,
        "site": site_info,
        "plan": plan,
        "conflicts": conflicts,
        "validation_errors": validation_errors,
        "summary": summary,
    }


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
        list[dict],
        Field(
            description="List of dicts with keys: vlan_id (int), prefix (str), role (str), description (str), vlan_name (str, optional)"
        ),
    ],
    confirmed: Annotated[
        bool,
        Field(
            description="Must be True - only set after user has explicitly approved the plan"
        ),
    ],
    overwrite_existing_vlans: Annotated[
        bool,
        Field(
            description="If True, existing VLANs are reused and updated. Only set after user confirmed overwrite."
        ),
    ] = False,
) -> dict:
    """
    Create VLANs and prefixes in NetBox after user confirmation.
    """
    if not confirmed:
        raise ValueError(
            "Creation refused: 'confirmed' is False. "
            "Call netbox_review_vlan_prefix_plan first, present the summary table to the user, "
            "and only set confirmed=True after the user has explicitly approved the plan."
        )

    # Step 1: Resolve site
    site_response = netbox.get("dcim/sites", params={"slug": site_slug, "limit": 1})
    site_results = site_response.get("results", [])
    if not site_results:
        raise ValueError(f"No site found with slug '{site_slug}'")
    site = site_results[0]
    site_id = site["id"]
    tenant_id = site.get("tenant", {}).get("id") if site.get("tenant") else None

    # Step 2: Resolve VLAN group for site
    vlan_group_response = netbox.get(
        "ipam/vlan-groups",
        params={"scope_type": "dcim.site", "scope_id": site_id, "limit": 1},
    )
    vlan_group_results = vlan_group_response.get("results", [])
    if not vlan_group_results:
        raise ValueError(f"No VLAN group found scoped to site '{site_slug}'")
    vlan_group_id = vlan_group_results[0]["id"]

    # Step 3: Pre-resolve all unique role slugs to IDs
    role_slugs = {entry["role"] for entry in entries if entry.get("role")}
    role_id_map: dict[str, int] = {}
    for slug in role_slugs:
        role_response = netbox.get("ipam/roles", params={"slug": slug, "limit": 1})
        role_results = role_response.get("results", [])
        if not role_results:
            raise ValueError(
                f"IPAM role '{slug}' not found in NetBox. "
                f"Please create the role first."
            )
        role_id_map[slug] = role_results[0]["id"]

    created = []
    errors = []

    for entry in entries:
        vlan_id = entry["vlan_id"]
        prefix_cidr = entry["prefix"]
        role = entry["role"]
        description = entry.get("description", "")
        vlan_name = entry.get("vlan_name") or f"VLAN-{vlan_id}"

        try:
            # Step 4: Check if VLAN already exists
            existing_resp = netbox.get(
                "ipam/vlans",
                params={"group_id": vlan_group_id, "vid": vlan_id, "limit": 1},
            )
            existing_vlans = existing_resp.get("results", [])

            if existing_vlans:
                if not overwrite_existing_vlans:
                    existing = existing_vlans[0]
                    errors.append(
                        {
                            "vlan_id": vlan_id,
                            "prefix": prefix_cidr,
                            "error": (
                                f"VLAN {vlan_id} already exists "
                                f"(name='{existing.get('name')}', description='{existing.get('description')}'). "
                                f"Set overwrite_existing_vlans=True to reuse it."
                            ),
                        }
                    )
                    continue
                # Overwrite: update description on existing VLAN
                existing_vlan_id = existing_vlans[0]["id"]
                netbox.update(
                    "ipam/vlans", existing_vlan_id, {"description": description}
                )
                created_vlan = existing_vlans[0]
                created_vlan["id"] = existing_vlan_id
            else:
                # Create new VLAN
                vlan_payload: dict[str, Any] = {
                    "vid": vlan_id,
                    "name": vlan_name,
                    "group": vlan_group_id,
                    "status": "active",
                    "description": description,
                }
                if tenant_id:
                    vlan_payload["tenant"] = tenant_id
                created_vlan = netbox.create("ipam/vlans", vlan_payload)

            # Step 5: Create Prefix linked to VLAN (role must be numeric ID)
            prefix_payload: dict[str, Any] = {
                "prefix": prefix_cidr,
                "scope_type": "dcim.site",
                "scope_id": site_id,
                "vlan": created_vlan["id"],
                "role": role_id_map[role],
                "status": "active",
                "description": description,
            }
            if tenant_id:
                prefix_payload["tenant"] = tenant_id

            created_prefix = netbox.create("ipam/prefixes", prefix_payload)

            created.append(
                {
                    "vlan": {
                        "id": created_vlan["id"],
                        "vid": vlan_id,
                        "name": created_vlan.get("name", vlan_name),
                    },
                    "prefix": {
                        "id": created_prefix["id"],
                        "prefix": created_prefix["prefix"],
                        "role": role,
                    },
                }
            )

        except Exception as e:
            errors.append(
                {
                    "vlan_id": vlan_id,
                    "prefix": prefix_cidr,
                    "error": str(e),
                }
            )

    return {
        "created": created,
        "errors": errors,
    }


def _get_endpoint_info(object_type: str) -> tuple[str, str | None]:
    """
    Returns (endpoint, fallback_endpoint) for the given object type.

    The fallback_endpoint is used for NetBox version compatibility when
    an endpoint path has changed between versions.

    Args:
        object_type: The NetBox object type (e.g., "dcim.device")

    Returns:
        Tuple of (endpoint, fallback_endpoint). fallback_endpoint is None
        if no fallback is needed for this object type.
    """
    type_info = NETBOX_OBJECT_TYPES[object_type]
    return type_info["endpoint"], type_info.get("fallback_endpoint")


def main() -> None:
    """Main entry point for the MCP server."""
    global netbox

    cli_overlay: dict[str, Any] = parse_cli_args()

    try:
        settings = Settings(**cli_overlay)
    except Exception as e:
        print(
            f"Configuration error: {e}", file=sys.stderr
        )  # noqa: T201 - before logging configured
        sys.exit(1)

    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    logger.info("Starting NetBox MCP Server")
    logger.info(f"Effective configuration: {settings.get_effective_config_summary()}")

    if not settings.verify_ssl:
        logger.warning(
            "SSL certificate verification is DISABLED. "
            "This is insecure and should only be used for testing."
        )

    if settings.transport == "http" and settings.host in [
        "0.0.0.0",
        "::",
        "[::]",
    ]:  # noqa: S104 - checking, not binding
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
        netbox = NetBoxRestClient(
            url=str(settings.netbox_url),
            token=settings.netbox_token.get_secret_value(),
            verify_ssl=settings.verify_ssl,
        )
        logger.debug("NetBox client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize NetBox client: {e}")
        sys.exit(1)

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
