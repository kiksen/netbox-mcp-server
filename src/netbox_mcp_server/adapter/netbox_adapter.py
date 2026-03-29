import ipaddress
from dataclasses import dataclass
from typing import Annotated, Any, cast

from pydantic import Field

from netbox_mcp_server import constants as CONST
from netbox_mcp_server.client.netbox_client import NetBoxRestClient
from netbox_mcp_server.netbox_types import NETBOX_OBJECT_TYPES
from netbox_mcp_server.port.netbox_port import NetboxPort


@dataclass
class NetboxAdapter(NetboxPort):
    netbox: NetBoxRestClient

    def validate_filters(self, filters: dict[str, Any]) -> None:
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
            raise ValueError(
                f"Invalid filter '{filter_name}': Multi-hop relationship "
                f"traversal or invalid lookup suffix not supported. Use direct field filters like "
                f"'site_id' or two-step queries."
            )

    def get_objects(
        self,
        object_type: str,
        filters: dict[str, Any],
        fields: list[str] | None = None,
        brief: bool = False,
        limit: Annotated[int, Field(default=5, ge=1, le=100)] = 5,
        offset: Annotated[int, Field(default=0, ge=0)] = 0,
        ordering: str | list[str] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """
        Get objects from NetBox based on their type and filters
        """
        # Validate object_type exists in mapping
        if object_type not in NETBOX_OBJECT_TYPES:
            valid_types = "\n".join(f"- {t}" for t in sorted(NETBOX_OBJECT_TYPES.keys()))
            raise ValueError(f"Invalid object_type. Must be one of:\n{valid_types}")

        # Validate filter patterns
        self.validate_filters(filters)

        # Get API endpoint and fallback from mapping
        endpoint, fallback = self._get_endpoint_info(object_type)

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
        return self.netbox.get(endpoint, params=params, fallback_endpoint=fallback)

    def get_object_by_id(
        self,
        object_type: str,
        object_id: int,
        fields: list[str] | None = None,
        brief: bool = False,
    ) -> dict[str, Any] | list[dict[str, Any]]:
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
        endpoint, fallback = self._get_endpoint_info(object_type)
        full_endpoint = f"{endpoint}/{object_id}"
        full_fallback = f"{fallback}/{object_id}" if fallback else None

        params: dict[str, Any] = {}
        if fields:
            params["fields"] = ",".join(fields)

        if brief:
            params["brief"] = "1"

        return self.netbox.get(full_endpoint, params=params, fallback_endpoint=full_fallback)

    def get_changelogs(self, filters: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
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

        # Apply default limit if not set by caller
        params = filters.copy()
        params.setdefault("limit", 50)

        return self.netbox.get(endpoint, params=params)

    def search_objects(
        self,
        query: str,
        object_types: list[str] | None = None,
        fields: list[str] | None = None,
        limit: Annotated[int, Field(default=5, ge=1, le=100)] = 5,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Perform global search across NetBox infrastructure.
        """
        search_types = object_types if object_types is not None else CONST.DEFAULT_SEARCH_TYPES

        # Validate all object types exist in mapping
        for obj_type in search_types:
            if obj_type not in NETBOX_OBJECT_TYPES:
                valid_types = "\n".join(f"- {t}" for t in sorted(NETBOX_OBJECT_TYPES.keys()))
                raise ValueError(
                    f"Invalid object_type '{obj_type}'. Must be one of:\n{valid_types}"
                )

        results: dict[str, list[dict[str, Any]]] = {obj_type: [] for obj_type in search_types}

        # Build results dictionary (error-resilient)
        for obj_type in search_types:
            try:
                endpoint, fallback = self._get_endpoint_info(obj_type)
                params: dict[str, Any] = {"q": query, "limit": limit}
                if fields:
                    params["fields"] = ",".join(fields)
                response = cast(
                    dict[str, Any],
                    self.netbox.get(
                        endpoint,
                        params=params,
                        fallback_endpoint=fallback,
                    ),
                )
                # Extract results array from paginated response
                results[obj_type] = response.get("results", [])
            except Exception:  # noqa: S112 - intentional error-resilient search
                # Continue searching other types if one fails
                # results[obj_type] already has empty list
                continue

        return results

    def get_next_available_prefix(
        self,
        parent_prefix: Annotated[
            str, Field(description="CIDR of the container prefix, e.g. '10.0.0.0/16'")
        ],
        site: Annotated[str, Field(description="Site name or slug, e.g. 'Bonn' or 'bonn'")],
        prefix_length: Annotated[
            int, Field(description="Desired prefix length (1-128), e.g. 26 for /26")
        ],
    ) -> dict[str, Any]:
        if not (1 <= prefix_length <= 128):
            raise ValueError(f"prefix_length must be between 1 and 128, got {prefix_length}")

        # Step 1: Find the container prefix
        response = cast(
            dict[str, Any],
            self.netbox.get(
                "ipam/prefixes",
                params={
                    "prefix": parent_prefix,
                    "site": site,
                    "status": "container",
                    "limit": 1,
                },
            ),
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
        available = cast(
            list[dict[str, Any]],
            self.netbox.get(f"ipam/prefixes/{container_id}/available-prefixes"),
        )
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

    def get_site_summary_prefixes(
        self,
        site: Annotated[str, Field(description="Site name or slug, e.g. 'Berlin' or 'berlin'")],
        fields: list[str] | None = None,
        limit: Annotated[int, Field(default=100, ge=1, le=1000)] = 100,
        offset: Annotated[int, Field(default=0, ge=0)] = 0,
    ) -> dict[str, Any] | list[dict[str, Any]]:
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

        return self.netbox.get("ipam/prefixes", params=params)

    def get_vlan_groups_for_site(
        self,
        site_slug: Annotated[str, Field(description="Site slug, e.g. 'bonn'")],
        fields: list[str] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """
        Get all VLAN groups scoped to a specific site.
        """
        # Step 1: resolve site slug -> site id
        site_response = cast(
            dict[str, Any],
            self.netbox.get("dcim/sites", params={"slug": site_slug, "limit": 1}),
        )
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

        return self.netbox.get("ipam/vlan-groups", params=params)

    def get_vlans_for_site(
        self,
        site_slug: Annotated[str, Field(description="Site slug, e.g. 'bonn'")],
    ) -> dict[str, Any]:
        """
        Get all VLANs for a specific site by resolving the site's VLAN group.
        """
        # Step 1: resolve site slug -> site id
        site_response = cast(
            dict[str, Any],
            self.netbox.get("dcim/sites", params={"slug": site_slug, "limit": 1}),
        )
        site_results = site_response.get("results", [])
        if not site_results:
            raise ValueError(f"No site found with slug '{site_slug}'")
        site_id = site_results[0]["id"]

        # Step 2: fetch VLAN group scoped to this site
        group_response = cast(
            dict[str, Any],
            self.netbox.get(
                "ipam/vlan-groups",
                params={"scope_type": "dcim.site", "scope_id": site_id, "limit": 1},
            ),
        )
        group_results = group_response.get("results", [])
        if not group_results:
            raise ValueError(f"No VLAN group found for site '{site_slug}'")
        vlan_group = group_results[0]

        # Step 3: fetch all VLANs in this group, only id/vid/name
        vlan_response = cast(
            dict[str, Any],
            self.netbox.get(
                "ipam/vlans",
                params={
                    "group_id": vlan_group["id"],
                    "fields": "id,vid,name",
                    "limit": 1000,
                    "ordering": "vid",
                },
            ),
        )

        total = vlan_response.get("count", 0)
        results = vlan_response.get("results", [])
        truncated = total > len(results)

        return {
            "count": total,
            "vlan_group": {"id": vlan_group["id"], "name": vlan_group["name"]},
            "results": results,
            **(
                {
                    "warning": f"Results truncated: {len(results)} of {total} VLANs returned. Use netbox_get_objects with offset for full pagination."
                }
                if truncated
                else {}
            ),
        }

    def check_vlan_id_in_vlan_group(
        self,
        vlan_group_id: Annotated[int, Field(description="Numeric ID of the VLAN group")],
        vid: Annotated[int, Field(description="VLAN ID to check (1-4094)", ge=1, le=4094)],
    ) -> dict[str, Any]:
        """
        Check whether a VLAN ID already exists within a specific VLAN group.
        """
        response = cast(
            dict[str, Any],
            self.netbox.get(
                "ipam/vlans",
                params={"group_id": vlan_group_id, "vid": vid, "limit": 1},
            ),
        )
        results = response.get("results", [])
        return {
            "exists": len(results) > 0,
            "vlan": results[0] if results else None,
        }

    def review_vlan_prefix_plan(
        self,
        site_slug: Annotated[str, Field(description="Site slug, e.g. 'bonn'")],
        entries: Annotated[
            list[dict[str, Any]],
            Field(
                description="List of dicts with keys: vlan_id (int), prefix (str), role (str), description (str)"
            ),
        ],
    ) -> dict[str, Any]:
        """
        Present a plan of VLANs and prefixes for user confirmation before creation.
        """
        # Step 1: Resolve site
        site_response = cast(
            dict[str, Any],
            self.netbox.get("dcim/sites", params={"slug": site_slug, "limit": 1}),
        )
        site_results = site_response.get("results", [])
        if not site_results:
            raise ValueError(f"No site found with slug '{site_slug}'")

        site = site_results[0]
        site_id = site["id"]
        site_info: dict[str, Any] = {
            "id": site_id,
            "name": site["name"],
            "slug": site["slug"],
            "tenant": (site.get("tenant", {}).get("name") if site.get("tenant") else None),
        }

        # Step 2: Resolve VLAN group for site
        vlan_group_response = cast(
            dict[str, Any],
            self.netbox.get(
                "ipam/vlan-groups",
                params={"scope_type": "dcim.site", "scope_id": site_id, "limit": 1},
            ),
        )
        vlan_group_results = vlan_group_response.get("results", [])
        vlan_group_id = vlan_group_results[0]["id"] if vlan_group_results else None
        vlan_group_name = vlan_group_results[0]["name"] if vlan_group_results else None
        site_info["vlan_group"] = vlan_group_name

        # Step 3: Validate each entry and detect conflicts
        validation_errors: list[str] = []
        conflicts: list[dict[str, Any]] = []
        plan: list[dict[str, Any]] = []

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
                validation_errors.append(f"Entry {i + 1} (VLAN {vlan_id}): missing 'description'")

            # Validate role
            if role and role not in CONST.VALID_IPAM_ROLES:
                validation_errors.append(
                    f"Entry {i + 1} (VLAN {vlan_id}): invalid role '{role}'. "
                    f"Must be one of: {', '.join(sorted(CONST.VALID_IPAM_ROLES))}"
                )

            # Validate production VLAN range
            if role == "production" and vlan_id is not None:
                lo, hi = CONST.PRODUCTION_VLAN_RANGE
                if not (lo <= vlan_id <= hi):
                    validation_errors.append(
                        f"Entry {i + 1} (VLAN {vlan_id}): production prefixes require "
                        f"VLAN ID between {lo} and {hi}, got {vlan_id}"
                    )

            # Check for existing VLAN conflict
            existing_vlan: dict[str, Any] | None = None
            if vlan_id is not None and vlan_group_id is not None:
                existing_resp = cast(
                    dict[str, Any],
                    self.netbox.get(
                        "ipam/vlans",
                        params={"group_id": vlan_group_id, "vid": vlan_id, "limit": 1},
                    ),
                )
                existing_results = existing_resp.get("results", [])
                if existing_results:
                    ev = existing_results[0]
                    # Fetch existing prefixes linked to this VLAN
                    existing_prefixes_resp = cast(
                        dict[str, Any],
                        self.netbox.get(
                            "ipam/prefixes",
                            params={"vlan_id": ev["id"], "limit": 10},
                        ),
                    )
                    existing_prefix_list = [
                        p["prefix"] for p in existing_prefixes_resp.get("results", [])
                    ]
                    existing_vlan: dict[str, Any] = {
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

            # Check for duplicate description within the same VLAN group
            description_conflict = None
            if description and vlan_group_id is not None:
                desc_resp = cast(
                    dict[str, Any],
                    self.netbox.get(
                        "ipam/vlans",
                        params={
                            "group_id": vlan_group_id,
                            "description": description,
                            "limit": 10,
                        },
                    ),
                )
                desc_results = desc_resp.get("results", [])
                # Exclude the current VLAN ID (to avoid false positive when overwriting)
                desc_results = [v for v in desc_results if v.get("vid") != vlan_id]
                if desc_results:
                    dv = desc_results[0]
                    description_conflict = {
                        "id": dv["id"],
                        "vid": dv["vid"],
                        "name": dv.get("name", ""),
                        "description": dv.get("description", ""),
                    }
                    warnings.append(
                        f"Description '{description}' already used by VLAN {dv['vid']} "
                        f"(name='{dv.get('name')}')"
                    )

            plan.append(
                {
                    "vlan_id": vlan_id,
                    "prefix": prefix,
                    "role": role,
                    "description": description,
                    "warnings": warnings,
                    "existing_vlan": existing_vlan,
                    "description_conflict": description_conflict,
                }
            )

        # Step 4: Build summary table
        table_rows: list[str] = []
        for entry in plan:
            conflict_marker = " ⚠" if entry["existing_vlan"] else ""
            table_rows.append(
                f"| {entry['vlan_id']}{conflict_marker} | {entry['prefix']} | {entry['role']} | {entry['description']} |"
            )

        summary = (
            f"Site: {site_info['name']} ({site_info['slug']})"
            + (f"  |  Tenant: {site_info['tenant']}" if site_info["tenant"] else "")
            + (f"  |  VLAN Group: {site_info['vlan_group']}" if site_info["vlan_group"] else "")
            + "\n\n"
            + "| VLAN ID | Prefix | IPAM Role | Description |\n"
            + "|---------|--------|-----------|-------------|\n"
            + "\n".join(table_rows)
        )

        if conflicts:
            summary += "\n\n**⚠ Conflicts - these VLANs already exist:**\n"
            for c in conflicts:
                summary += (
                    f"- VLAN {c['vid']}: name=`{c['name']}`, "
                    f"description=`{c['description']}`, "
                    f"prefixes={c['existing_prefixes'] or 'none'}\n"
                )
            summary += (
                "\nTo overwrite existing VLANs, set `overwrite_existing_vlans=true` "
                "in `netbox_create_vlan_prefix_batch`."
            )

        if any(e.get("description_conflict") for e in plan):
            summary += "\n\n**⚠ Description already in use:**\n"
            for e in plan:
                dc = e.get("description_conflict")
                if dc:
                    summary += (
                        f"- Description '{e['description']}' already used by "
                        f"VLAN {dc['vid']} (name=`{dc['name']}`)\n"
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
            "description_conflicts": [
                e["description_conflict"] for e in plan if e.get("description_conflict")
            ],
            "validation_errors": validation_errors,
            "summary": summary,
        }

    def create_vlan_prefix_batch(
        self,
        site_slug: Annotated[str, Field(description="Site slug, e.g. 'bonn'")],
        entries: Annotated[
            list[dict[str, Any]],
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
    ) -> dict[str, Any]:
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
        site_response = cast(
            dict[str, Any],
            self.netbox.get("dcim/sites", params={"slug": site_slug, "limit": 1}),
        )
        site_results = site_response.get("results", [])
        if not site_results:
            raise ValueError(f"No site found with slug '{site_slug}'")
        site = site_results[0]
        site_id = site["id"]
        tenant_id = site.get("tenant", {}).get("id") if site.get("tenant") else None

        # Step 2: Resolve VLAN group for site
        vlan_group_response = cast(
            dict[str, Any],
            self.netbox.get(
                "ipam/vlan-groups",
                params={"scope_type": "dcim.site", "scope_id": site_id, "limit": 1},
            ),
        )
        vlan_group_results = vlan_group_response.get("results", [])
        if not vlan_group_results:
            raise ValueError(f"No VLAN group found scoped to site '{site_slug}'")
        vlan_group_id = vlan_group_results[0]["id"]

        # Step 3: Pre-resolve all unique role slugs to IDs
        role_slugs = {entry["role"] for entry in entries if entry.get("role")}
        role_id_map: dict[str, int] = {}
        for slug in role_slugs:
            role_response = cast(
                dict[str, Any],
                self.netbox.get("ipam/roles", params={"slug": slug, "limit": 1}),
            )
            role_results = role_response.get("results", [])
            if not role_results:
                raise ValueError(
                    f"IPAM role '{slug}' not found in NetBox. Please create the role first."
                )
            role_id_map[slug] = role_results[0]["id"]

        created = []
        errors = []

        for entry in entries:
            try:
                vlan_id = entry["vlan_id"]
                prefix_cidr = entry["prefix"]
                role = entry["role"]
                description = entry.get("description", "")
                vlan_name = entry.get("vlan_name") or f"VLAN-{vlan_id}"

                # Validate role
                if role not in CONST.VALID_IPAM_ROLES:
                    errors.append(
                        {
                            "vlan_id": vlan_id,
                            "prefix": prefix_cidr,
                            "error": f"Invalid role '{role}'. Must be one of: {', '.join(sorted(CONST.VALID_IPAM_ROLES))}",
                        }
                    )
                    continue

                # Validate production VLAN range
                if role == "production":
                    lo, hi = CONST.PRODUCTION_VLAN_RANGE
                    if not (lo <= vlan_id <= hi):
                        errors.append(
                            {
                                "vlan_id": vlan_id,
                                "prefix": prefix_cidr,
                                "error": f"Production VLANs require VLAN ID between {lo} and {hi}, got {vlan_id}",
                            }
                        )
                        continue

                # Step 4: Check if VLAN already exists
                existing_resp = cast(
                    dict[str, Any],
                    self.netbox.get(
                        "ipam/vlans",
                        params={"group_id": vlan_group_id, "vid": vlan_id, "limit": 1},
                    ),
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
                    # Overwrite: update name and description on existing VLAN
                    existing_vlan_id = existing_vlans[0]["id"]
                    updated_vlan = self.netbox.update(
                        "ipam/vlans",
                        existing_vlan_id,
                        {"name": vlan_name, "description": description},
                    )
                    created_vlan = updated_vlan
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
                    created_vlan = self.netbox.create("ipam/vlans", vlan_payload)

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

                created_prefix = self.netbox.create("ipam/prefixes", prefix_payload)

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
                        "vlan_id": entry.get("vlan_id"),
                        "prefix": entry.get("prefix"),
                        "error": str(e),
                    }
                )

        return {
            "created": created,
            "errors": errors,
        }

    def _get_endpoint_info(self, object_type: str) -> tuple[str, str | None]:
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
