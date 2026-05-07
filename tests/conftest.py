"""Shared pytest fixtures for biblindex_client tests."""

from __future__ import annotations

from typing import Any

import pytest

from biblindex_client import BiblIndexClient

BASE_URL = "https://api.example.com"
TOKEN_URL = f"{BASE_URL}/api/token"


@pytest.fixture
def client() -> BiblIndexClient:
    """A fresh, unauthenticated client pointed at the fake test API."""
    return BiblIndexClient(
        baseUrl=BASE_URL,
        username="user",
        password="pass",
        clientId="id",
        clientSecret="secret",
    )


def make_token_payload(
    access: str = "access-1",
    refresh: str = "refresh-1",
    expires_in: int = 3600,
) -> dict[str, Any]:
    """Build a fake OAuth token endpoint response body."""
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": expires_in,
    }
