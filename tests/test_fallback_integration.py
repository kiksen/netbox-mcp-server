"""Tests for fallback endpoint integration in MCP tools.

These tests verify that the server tools correctly pass fallback endpoints
to the NetBox client for types that have version-dependent endpoints.
"""

from netbox_mcp_server.server import (
    netbox_get_object_by_id,
    netbox_get_objects,
    netbox_search_objects,
)

_EMPTY_RESPONSE = {"count": 0, "results": [], "next": None, "previous": None}

# ============================================================================
# netbox_get_objects Fallback Tests
# ============================================================================


def test_get_objects_passes_fallback_for_objecttype(mock_client, mock_ctx):
    """netbox_get_objects should pass fallback_endpoint for core.objecttype."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    netbox_get_objects(object_type="core.objecttype", filters={}, ctx=mock_ctx)

    mock_client.get.assert_called_once()
    assert mock_client.get.call_args[1]["fallback_endpoint"] == "extras/object-types"


def test_get_objects_no_fallback_for_regular_types(mock_client, mock_ctx):
    """netbox_get_objects should pass None fallback for types without fallback."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    netbox_get_objects(object_type="dcim.device", filters={}, ctx=mock_ctx)

    mock_client.get.assert_called_once()
    assert mock_client.get.call_args[1]["fallback_endpoint"] is None


def test_get_objects_uses_primary_endpoint_for_objecttype(mock_client, mock_ctx):
    """netbox_get_objects should use core/object-types as primary endpoint."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    netbox_get_objects(object_type="core.objecttype", filters={}, ctx=mock_ctx)

    assert mock_client.get.call_args[0][0] == "core/object-types"


# ============================================================================
# netbox_get_object_by_id Fallback Tests
# ============================================================================


def test_get_object_by_id_passes_fallback_for_objecttype(mock_client, mock_ctx):
    """netbox_get_object_by_id should pass fallback_endpoint for core.objecttype."""
    mock_client.get.return_value = {"id": 1, "name": "dcim.device"}

    netbox_get_object_by_id(object_type="core.objecttype", object_id=1, ctx=mock_ctx)

    mock_client.get.assert_called_once()
    assert mock_client.get.call_args[1]["fallback_endpoint"] == "extras/object-types/1"


def test_get_object_by_id_no_fallback_for_regular_types(mock_client, mock_ctx):
    """netbox_get_object_by_id should pass None fallback for types without fallback."""
    mock_client.get.return_value = {"id": 1, "name": "Test Device"}

    netbox_get_object_by_id(object_type="dcim.device", object_id=1, ctx=mock_ctx)

    mock_client.get.assert_called_once()
    assert mock_client.get.call_args[1]["fallback_endpoint"] is None


def test_get_object_by_id_uses_primary_endpoint_with_id(mock_client, mock_ctx):
    """netbox_get_object_by_id should use correct primary endpoint with ID."""
    mock_client.get.return_value = {"id": 42, "name": "dcim.site"}

    netbox_get_object_by_id(object_type="core.objecttype", object_id=42, ctx=mock_ctx)

    assert mock_client.get.call_args[0][0] == "core/object-types/42"


# ============================================================================
# netbox_search_objects Fallback Tests
# ============================================================================


def test_search_objects_passes_fallback_for_objecttype(mock_client, mock_ctx):
    """netbox_search_objects should pass fallback_endpoint when searching objecttype."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    netbox_search_objects(query="device", object_types=["core.objecttype"], ctx=mock_ctx)

    mock_client.get.assert_called_once()
    assert mock_client.get.call_args[1]["fallback_endpoint"] == "extras/object-types"


def test_search_objects_no_fallback_for_regular_types(mock_client, mock_ctx):
    """netbox_search_objects should pass None fallback for types without fallback."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    netbox_search_objects(query="switch", object_types=["dcim.device"], ctx=mock_ctx)

    mock_client.get.assert_called_once()
    assert mock_client.get.call_args[1]["fallback_endpoint"] is None


def test_search_objects_mixed_types_with_and_without_fallback(mock_client, mock_ctx):
    """When searching mixed types, each should get correct fallback."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    netbox_search_objects(
        query="test", object_types=["dcim.device", "core.objecttype"], ctx=mock_ctx
    )

    assert mock_client.get.call_count == 2
    for call in mock_client.get.call_args_list:
        endpoint = call[0][0]
        fallback = call[1]["fallback_endpoint"]
        if "devices" in endpoint:
            assert fallback is None
        elif "object-types" in endpoint:
            assert fallback == "extras/object-types"


# ============================================================================
# New Object Types Tests (NetBox 4.4/4.5 additions)
# ============================================================================


def test_config_context_profile_no_fallback(mock_client, mock_ctx):
    """extras.configcontextprofile (new in 4.4) should have no fallback."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    netbox_get_objects(object_type="extras.configcontextprofile", filters={}, ctx=mock_ctx)

    assert mock_client.get.call_args[1]["fallback_endpoint"] is None


def test_owner_no_fallback(mock_client, mock_ctx):
    """users.owner (new in 4.5) should have no fallback."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    netbox_get_objects(object_type="users.owner", filters={}, ctx=mock_ctx)

    assert mock_client.get.call_args[1]["fallback_endpoint"] is None


def test_owner_group_no_fallback(mock_client, mock_ctx):
    """users.ownergroup (new in 4.5) should have no fallback."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    netbox_get_objects(object_type="users.ownergroup", filters={}, ctx=mock_ctx)

    assert mock_client.get.call_args[1]["fallback_endpoint"] is None
