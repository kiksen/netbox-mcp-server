"""Tests for ordering parameter validation and behavior."""

import pytest
from pydantic import TypeAdapter, ValidationError

from netbox_mcp_server.server import netbox_get_objects

_EMPTY_RESPONSE = {"count": 0, "results": [], "next": None, "previous": None}


def test_ordering_rejects_invalid_types():
    """Ordering parameter should reject non-string/non-list types."""
    ordering_annotation = netbox_get_objects.__annotations__["ordering"]
    adapter = TypeAdapter(ordering_annotation)

    with pytest.raises(ValidationError):
        adapter.validate_python(123)

    with pytest.raises(ValidationError):
        adapter.validate_python({"field": "name"})

    with pytest.raises(ValidationError):
        adapter.validate_python(["name", 123])


def test_ordering_none_omits_parameter(mock_client, mock_ctx):
    """When ordering=None, should not include ordering in API params."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    netbox_get_objects(object_type="dcim.site", filters={}, ordering=None, ctx=mock_ctx)

    params = mock_client.get.call_args[1]["params"]
    assert "ordering" not in params


def test_ordering_empty_string_omits_parameter(mock_client, mock_ctx):
    """When ordering='', should not include ordering in API params."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    netbox_get_objects(object_type="dcim.site", filters={}, ordering="", ctx=mock_ctx)

    params = mock_client.get.call_args[1]["params"]
    assert "ordering" not in params


def test_ordering_single_field_ascending(mock_client, mock_ctx):
    """When ordering='name', should pass 'name' to API params."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    netbox_get_objects(object_type="dcim.site", filters={}, ordering="name", ctx=mock_ctx)

    params = mock_client.get.call_args[1]["params"]
    assert params["ordering"] == "name"


def test_ordering_single_field_descending(mock_client, mock_ctx):
    """When ordering='-id', should pass '-id' to API params."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    netbox_get_objects(object_type="dcim.site", filters={}, ordering="-id", ctx=mock_ctx)

    params = mock_client.get.call_args[1]["params"]
    assert params["ordering"] == "-id"


def test_ordering_multiple_fields_as_list(mock_client, mock_ctx):
    """When ordering=['facility', '-name'], should pass comma-separated string."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    netbox_get_objects(
        object_type="dcim.site", filters={}, ordering=["facility", "-name"], ctx=mock_ctx
    )

    params = mock_client.get.call_args[1]["params"]
    assert params["ordering"] == "facility,-name"


def test_ordering_empty_list_omits_parameter(mock_client, mock_ctx):
    """When ordering=[], should not include ordering in API params."""
    mock_client.get.return_value = _EMPTY_RESPONSE

    netbox_get_objects(object_type="dcim.site", filters={}, ordering=[], ctx=mock_ctx)

    params = mock_client.get.call_args[1]["params"]
    assert "ordering" not in params
