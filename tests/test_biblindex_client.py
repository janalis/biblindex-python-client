"""Tests for the BiblIndexClient HTTP wrapper."""

from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import parse_qs

import pytest
import requests
import responses

from biblindex_client import BiblIndexClient

from .conftest import BASE_URL, TOKEN_URL, make_token_payload

RESOURCE_PATH = "/api/quotations"
RESOURCE_URL = f"{BASE_URL}{RESOURCE_PATH}"


def _last_form(call: responses.Call) -> dict[str, list[str]]:
    """Decode an x-www-form-urlencoded POST body into a dict."""
    body = call.request.body
    if isinstance(body, bytes):
        body = body.decode()
    return parse_qs(body or "")


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


def test_constructor_stores_credentials_and_starts_unauthenticated(
    client: BiblIndexClient,
) -> None:
    assert client.baseUrl == BASE_URL
    assert client.username == "user"
    assert client.password == "pass"
    assert client.clientId == "id"
    assert client.clientSecret == "secret"
    assert client.accessToken is None
    assert client.refreshToken is None
    assert client.expiresIn is None
    assert isinstance(client.session, requests.Session)


# ---------------------------------------------------------------------------
# fetchTokens()
# ---------------------------------------------------------------------------


@responses.activate
def test_fetch_tokens_populates_state(client: BiblIndexClient) -> None:
    responses.post(TOKEN_URL, json=make_token_payload("A1", "R1", expires_in=1800))

    before = datetime.now()
    client.fetchTokens()

    assert client.accessToken == "A1"
    assert client.refreshToken == "R1"
    assert client.expiresIn is not None
    # expiresIn should be ~1800s in the future (allow small clock drift).
    assert client.expiresIn >= before + timedelta(seconds=1799)
    assert client.expiresIn <= datetime.now() + timedelta(seconds=1801)


@responses.activate
def test_fetch_tokens_uses_password_grant(client: BiblIndexClient) -> None:
    responses.post(TOKEN_URL, json=make_token_payload())

    client.fetchTokens()

    form = _last_form(responses.calls[0])
    assert form["grant_type"] == ["password"]
    assert form["username"] == ["user"]
    assert form["password"] == ["pass"]
    assert form["client_id"] == ["id"]
    assert form["client_secret"] == ["secret"]


# ---------------------------------------------------------------------------
# refreshTokens()
# ---------------------------------------------------------------------------


@responses.activate
def test_refresh_tokens_uses_refresh_grant_and_updates_state(
    client: BiblIndexClient,
) -> None:
    client.refreshToken = "old-refresh"
    responses.post(TOKEN_URL, json=make_token_payload("A2", "R2", expires_in=600))

    client.refreshTokens()

    form = _last_form(responses.calls[0])
    assert form["grant_type"] == ["refresh_token"]
    assert form["refresh_token"] == ["old-refresh"]
    assert form["client_id"] == ["id"]
    assert form["client_secret"] == ["secret"]

    assert client.accessToken == "A2"
    assert client.refreshToken == "R2"
    assert client.expiresIn is not None


# ---------------------------------------------------------------------------
# request()
# ---------------------------------------------------------------------------


@responses.activate
def test_request_first_call_authenticates_then_GETs(client: BiblIndexClient) -> None:
    responses.post(TOKEN_URL, json=make_token_payload("A1", "R1"))
    responses.get(RESOURCE_URL, json={"items": []})

    result = client.request(RESOURCE_PATH, {"page": 1})

    assert result == {"items": []}
    assert len(responses.calls) == 2
    # Second call is the resource GET, with the bearer token.
    api_call = responses.calls[1]
    assert api_call.request.url.startswith(RESOURCE_URL)
    assert api_call.request.headers["Authorization"] == "Bearer A1"
    assert api_call.request.headers["Accept"] == "application/json"


@responses.activate
def test_request_with_valid_token_skips_token_endpoint(
    client: BiblIndexClient,
) -> None:
    client.accessToken = "preset-A"
    client.refreshToken = "preset-R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(RESOURCE_URL, json={"ok": True})

    result = client.request(RESOURCE_PATH, {})

    assert result == {"ok": True}
    assert len(responses.calls) == 1
    assert responses.calls[0].request.headers["Authorization"] == "Bearer preset-A"


@responses.activate
def test_request_refreshes_when_token_expired(client: BiblIndexClient) -> None:
    client.accessToken = "stale-A"
    client.refreshToken = "good-R"
    client.expiresIn = datetime.now() - timedelta(seconds=1)
    responses.post(TOKEN_URL, json=make_token_payload("fresh-A", "fresh-R"))
    responses.get(RESOURCE_URL, json={"refreshed": True})

    result = client.request(RESOURCE_PATH, {})

    assert result == {"refreshed": True}
    assert len(responses.calls) == 2
    # First call: refresh-grant POST.
    refresh_form = _last_form(responses.calls[0])
    assert refresh_form["grant_type"] == ["refresh_token"]
    assert refresh_form["refresh_token"] == ["good-R"]
    # Second call: GET with the new bearer token.
    assert responses.calls[1].request.headers["Authorization"] == "Bearer fresh-A"


@responses.activate
def test_request_passes_query_params(client: BiblIndexClient) -> None:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(RESOURCE_URL, json={})

    client.request(RESOURCE_PATH, {"page": 2, "limit": 10})

    sent = responses.calls[0].request.url
    assert "page=2" in sent
    assert "limit=10" in sent


@responses.activate
def test_request_raises_on_http_error(client: BiblIndexClient) -> None:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(RESOURCE_URL, status=500, json={"error": "boom"})

    with pytest.raises(requests.HTTPError):
        client.request(RESOURCE_PATH, {})


@responses.activate
def test_request_builds_url_with_leading_slash(client: BiblIndexClient) -> None:
    """A resource starting with '/' joins the baseUrl without a doubled slash."""
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(RESOURCE_URL, json={})

    client.request("/api/quotations", {})

    # responses' URL matcher already enforces this, but assert explicitly to
    # make the intent visible: no '//' between host and path.
    sent = responses.calls[0].request.url.split("?")[0]
    assert sent == RESOURCE_URL
    assert "//api/quotations" not in sent


@responses.activate
def test_request_normalizes_missing_leading_slash(client: BiblIndexClient) -> None:
    """A resource passed without a leading slash is normalized, not concatenated raw."""
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(RESOURCE_URL, json={})

    client.request("api/quotations", {})

    sent = responses.calls[0].request.url.split("?")[0]
    assert sent == RESOURCE_URL


@responses.activate
def test_request_normalizes_missing_leading_api_prefix(client: BiblIndexClient) -> None:
    """A resource passed without a leading /api prefix is normalized, not concatenated raw."""
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(RESOURCE_URL, json={})

    client.request("quotations", {})

    sent = responses.calls[0].request.url.split("?")[0]
    assert sent == RESOURCE_URL
