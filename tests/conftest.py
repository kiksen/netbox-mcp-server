"""Shared pytest fixtures."""

from unittest.mock import MagicMock

import pytest

from netbox_mcp_server.adapter.netbox_adapter import NetboxAdapter


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def adapter(mock_client):
    return NetboxAdapter(netbox=mock_client)


@pytest.fixture
def mock_ctx(mock_client):
    ctx = MagicMock()
    ctx.fastmcp._lifespan_result = {"netbox": mock_client}
    return ctx
