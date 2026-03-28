"""Tests for brief parameter validation and behavior."""

from netbox_mcp_server.server import netbox_get_object_by_id, netbox_get_objects


def test_brief_false_omits_parameter_get_objects(mock_client, mock_ctx):
    """When brief=False (default), should not include brief in API params for netbox_get_objects."""
    mock_client.get.return_value = {"count": 0, "results": [], "next": None, "previous": None}

    netbox_get_objects(object_type="dcim.site", filters={}, brief=False, ctx=mock_ctx)

    params = mock_client.get.call_args[1]["params"]
    assert "brief" not in params


def test_brief_default_omits_parameter_get_objects(mock_client, mock_ctx):
    """When brief not specified (uses default False), should not include brief in API params."""
    mock_client.get.return_value = {"count": 0, "results": [], "next": None, "previous": None}

    netbox_get_objects(object_type="dcim.site", filters={}, ctx=mock_ctx)

    params = mock_client.get.call_args[1]["params"]
    assert "brief" not in params


def test_brief_true_includes_parameter_get_objects(mock_client, mock_ctx):
    """When brief=True, should pass 'brief': '1' to API params for netbox_get_objects."""
    mock_client.get.return_value = {"count": 0, "results": [], "next": None, "previous": None}

    netbox_get_objects(object_type="dcim.site", filters={}, brief=True, ctx=mock_ctx)

    params = mock_client.get.call_args[1]["params"]
    assert params["brief"] == "1"


def test_brief_false_omits_parameter_get_by_id(mock_client, mock_ctx):
    """When brief=False (default), should not include brief in API params for netbox_get_object_by_id."""
    mock_client.get.return_value = {"id": 1, "name": "Test Site"}

    netbox_get_object_by_id(object_type="dcim.site", object_id=1, brief=False, ctx=mock_ctx)

    params = mock_client.get.call_args[1]["params"]
    assert "brief" not in params


def test_brief_default_omits_parameter_get_by_id(mock_client, mock_ctx):
    """When brief not specified (uses default False), should not include brief in API params."""
    mock_client.get.return_value = {"id": 1, "name": "Test Site"}

    netbox_get_object_by_id(object_type="dcim.site", object_id=1, ctx=mock_ctx)

    params = mock_client.get.call_args[1]["params"]
    assert "brief" not in params


def test_brief_true_includes_parameter_get_by_id(mock_client, mock_ctx):
    """When brief=True, should pass 'brief': '1' to API params for netbox_get_object_by_id."""
    mock_client.get.return_value = {"id": 1, "url": "http://example.com/api/dcim/sites/1/"}

    netbox_get_object_by_id(object_type="dcim.site", object_id=1, brief=True, ctx=mock_ctx)

    params = mock_client.get.call_args[1]["params"]
    assert params["brief"] == "1"
