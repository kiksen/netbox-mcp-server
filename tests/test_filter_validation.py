"""Tests for filter validation."""

from unittest.mock import MagicMock

import pytest

from netbox_mcp_server.adapter.netbox_adapter import NetboxAdapter


@pytest.fixture
def adapter():
    return NetboxAdapter(netbox=MagicMock())


def test_direct_field_filters_pass(adapter):
    """Direct field filters should pass validation."""
    adapter.validate_filters({"site_id": 1, "name": "router", "status": "active"})


def test_lookup_suffixes_pass(adapter):
    """Lookup suffixes should pass validation."""
    adapter.validate_filters({"name__ic": "switch", "id__in": [1, 2, 3], "vid__gte": 100})


def test_special_parameters_ignored(adapter):
    """Special parameters like limit, offset should be ignored."""
    adapter.validate_filters({"limit": 10, "offset": 5, "fields": "id,name", "q": "search"})


def test_multi_hop_filters_rejected(adapter):
    """Multi-hop relationship traversal should be rejected."""
    with pytest.raises(ValueError, match="Multi-hop relationship traversal"):
        adapter.validate_filters({"device__site_id": 1})


def test_nested_relationships_rejected(adapter):
    """Deeply nested relationships should be rejected."""
    with pytest.raises(ValueError, match="Multi-hop relationship traversal"):
        adapter.validate_filters({"interface__device__site": "dc1"})


def test_error_message_helpful(adapter):
    """Error message should mention the invalid filter and suggest alternatives."""
    with pytest.raises(ValueError, match="Multi-hop relationship traversal"):
        adapter.validate_filters({"device__site_id": 1})
