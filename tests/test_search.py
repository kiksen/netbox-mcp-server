"""Tests for global search functionality (netbox_search_objects tool)."""

import pytest
from pydantic import TypeAdapter, ValidationError

from netbox_mcp_server.netbox_types import NETBOX_OBJECT_TYPES
from netbox_mcp_server.server import netbox_search_objects

_EMPTY_RESPONSE = {"count": 0, "next": None, "previous": None, "results": []}

# ============================================================================
# Parameter Validation Tests
# ============================================================================


def test_limit_validation_rejects_invalid_values():
    """Limit must be between 1 and 100."""
    limit_annotation = netbox_search_objects.__annotations__["limit"]
    ta = TypeAdapter(limit_annotation)

    with pytest.raises(ValidationError):
        ta.validate_python(0)

    with pytest.raises(ValidationError):
        ta.validate_python(101)

    ta.validate_python(1)
    ta.validate_python(100)


def test_invalid_object_type_raises_error(mock_ctx):
    """Invalid object type should raise ValueError with helpful message."""
    with pytest.raises(ValueError, match="Invalid object_type"):
        netbox_search_objects(query="test", object_types=["invalid_type_xyz"], ctx=mock_ctx)


# ============================================================================
# Default Behavior Tests
# ============================================================================


def test_searches_default_types_when_none_specified(mock_client, mock_ctx):
    """When object_types=None, should search 8 default common types."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    result = netbox_search_objects(query="test", ctx=mock_ctx)

    assert mock_client.get.call_count == 8
    assert isinstance(result, dict)
    assert len(result) == 8


def test_custom_object_types_limits_search_scope(mock_client, mock_ctx):
    """When object_types specified, should only search those types."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    result = netbox_search_objects(
        query="test", object_types=["dcim.device", "dcim.site"], ctx=mock_ctx
    )

    assert mock_client.get.call_count == 2
    assert set(result.keys()) == {"dcim.device", "dcim.site"}


# ============================================================================
# Field Projection Tests
# ============================================================================


def test_field_projection_applied_to_queries(mock_client, mock_ctx):
    """When fields specified, should apply to all queries as comma-separated string."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    netbox_search_objects(
        query="test", object_types=["dcim.device", "dcim.site"], fields=["id", "name"], ctx=mock_ctx
    )

    for call_args in mock_client.get.call_args_list:
        assert call_args[1]["params"]["fields"] == "id,name"


# ============================================================================
# Result Structure Tests
# ============================================================================


def test_result_structure_with_empty_and_populated_results(mock_client, mock_ctx):
    """Should return dict with all types as keys, empty lists for no matches."""

    def mock_get_side_effect(endpoint, params, fallback_endpoint=None):
        if "devices" in endpoint:
            return {
                "count": 1,
                "next": None,
                "previous": None,
                "results": [{"id": 1, "name": "device01"}],
            }
        return _EMPTY_RESPONSE

    mock_client.get.side_effect = mock_get_side_effect

    result = netbox_search_objects(
        query="test", object_types=["dcim.device", "dcim.site", "dcim.rack"], ctx=mock_ctx
    )

    assert set(result.keys()) == {"dcim.device", "dcim.site", "dcim.rack"}
    assert result["dcim.device"] == [{"id": 1, "name": "device01"}]
    assert result["dcim.site"] == []
    assert result["dcim.rack"] == []


# ============================================================================
# Error Resilience Tests
# ============================================================================


def test_continues_searching_when_one_type_fails(mock_client, mock_ctx):
    """If one object type fails, should continue searching others."""

    def mock_get_side_effect(endpoint, params, fallback_endpoint=None):
        if "devices" in endpoint:
            raise Exception("API error")
        elif "sites" in endpoint:
            return {
                "count": 1,
                "next": None,
                "previous": None,
                "results": [{"id": 1, "name": "site01"}],
            }
        return _EMPTY_RESPONSE

    mock_client.get.side_effect = mock_get_side_effect

    result = netbox_search_objects(
        query="test", object_types=["dcim.device", "dcim.site"], ctx=mock_ctx
    )

    assert result["dcim.site"] == [{"id": 1, "name": "site01"}]
    assert result["dcim.device"] == []


# ============================================================================
# NetBox API Integration Tests
# ============================================================================


def test_api_parameters_passed_correctly(mock_client, mock_ctx):
    """Should pass query, limit, and fields to NetBox API correctly."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    netbox_search_objects(
        query="switch01", object_types=["dcim.device"], fields=["id"], limit=25, ctx=mock_ctx
    )

    params = mock_client.get.call_args[1]["params"]
    assert params["q"] == "switch01"
    assert params["limit"] == 25
    assert params["fields"] == "id"


def test_uses_correct_api_endpoints(mock_client, mock_ctx):
    """Should use correct API endpoints from NETBOX_OBJECT_TYPES mapping."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    netbox_search_objects(
        query="test", object_types=["dcim.device", "ipam.ipaddress"], ctx=mock_ctx
    )

    called_endpoints = [call[0][0] for call in mock_client.get.call_args_list]
    assert NETBOX_OBJECT_TYPES["dcim.device"]["endpoint"] in called_endpoints
    assert NETBOX_OBJECT_TYPES["ipam.ipaddress"]["endpoint"] in called_endpoints


# ============================================================================
# Paginated Response Handling Tests
# ============================================================================


def test_extracts_results_from_paginated_response(mock_client, mock_ctx):
    """Should extract 'results' array from NetBox paginated response structure."""
    mock_client.get.return_value = {
        "count": 2,
        "next": None,
        "previous": None,
        "results": [{"id": 1, "name": "device01"}, {"id": 2, "name": "device02"}],
    }

    result = netbox_search_objects(query="test", object_types=["dcim.device"], ctx=mock_ctx)

    assert "dcim.device" in result
    assert isinstance(result["dcim.device"], list)
    assert result["dcim.device"] == [{"id": 1, "name": "device01"}, {"id": 2, "name": "device02"}]
