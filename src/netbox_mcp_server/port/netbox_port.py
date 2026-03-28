from typing import Annotated, Any, Protocol

from pydantic import Field


class NetboxPort(Protocol):
    def validate_filters(self, filters: dict) -> None: ...

    def get_objects(
        self,
        object_type: str,
        filters: dict,
        fields: list[str] | None = None,
        brief: bool = False,
        limit: Annotated[int, Field(default=5, ge=1, le=100)] = 5,
        offset: Annotated[int, Field(default=0, ge=0)] = 0,
        ordering: str | list[str] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]: ...
    def get_object_by_id(
        self,
        object_type: str,
        object_id: int,
        fields: list[str] | None = None,
        brief: bool = False,
    ) -> dict[str, Any] | list[dict[str, Any]]: ...

    def get_changelogs(self, filters: dict): ...

    def search_objects(
        self,
        query: str,
        object_types: list[str] | None = None,
        fields: list[str] | None = None,
        limit: Annotated[int, Field(default=5, ge=1, le=100)] = 5,
    ) -> dict[str, list[dict]]: ...

    def get_next_available_prefix(
        self,
        parent_prefix: Annotated[
            str, Field(description="CIDR of the container prefix, e.g. '10.0.0.0/16'")
        ],
        site: Annotated[str, Field(description="Site name or slug, e.g. 'Bonn' or 'bonn'")],
        prefix_length: Annotated[
            int, Field(description="Desired prefix length (1-128), e.g. 26 for /26")
        ],
    ) -> dict: ...

    def get_site_summary_prefixes(
        self,
        site: Annotated[str, Field(description="Site name or slug, e.g. 'Berlin' or 'berlin'")],
        fields: list[str] | None = None,
        limit: Annotated[int, Field(default=100, ge=1, le=1000)] = 100,
        offset: Annotated[int, Field(default=0, ge=0)] = 0,
    ) -> dict: ...

    def get_vlan_groups_for_site(
        self,
        site_slug: Annotated[str, Field(description="Site slug, e.g. 'bonn'")],
        fields: list[str] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]: ...

    def get_vlans_for_site(
        self,
        site_slug: Annotated[str, Field(description="Site slug, e.g. 'bonn'")],
    ) -> dict: ...
    def check_vlan_id_in_vlan_group(
        self,
        vlan_group_id: Annotated[int, Field(description="Numeric ID of the VLAN group")],
        vid: Annotated[int, Field(description="VLAN ID to check (1-4094)", ge=1, le=4094)],
    ) -> dict: ...
    def review_vlan_prefix_plan(
        self,
        site_slug: Annotated[str, Field(description="Site slug, e.g. 'bonn'")],
        entries: Annotated[
            list[dict],
            Field(
                description="List of dicts with keys: vlan_id (int), prefix (str), role (str), description (str)"
            ),
        ],
    ) -> dict: ...
    def create_vlan_prefix_batch(
        self,
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
    ) -> dict: ...

    def _get_endpoint_info(self, object_type: str) -> tuple[str, str | None]: ...
