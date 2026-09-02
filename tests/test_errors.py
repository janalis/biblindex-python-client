"""Errors that explain themselves rather than handing back a bare status code."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import requests
import responses

from biblindex_client import (
    AccessDeniedError,
    AuthenticationError,
    BiblIndexClient,
    BiblIndexError,
    BiblIndexHTTPError,
)

from .conftest import BASE_URL, TOKEN_URL, make_token_payload

RESOURCE_URL = f"{BASE_URL}/api/quotations"


@pytest.fixture
def authed(client: BiblIndexClient) -> BiblIndexClient:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    return client


@responses.activate
def test_403_on_the_corpus_names_the_missing_role(authed: BiblIndexClient) -> None:
    """The audit's §1: a valid token, and no ROLE_API_CLIENT on the account."""
    responses.get(
        RESOURCE_URL,
        status=403,
        json={"@type": "hydra:Error", "hydra:description": "Access Denied."},
    )

    with pytest.raises(AccessDeniedError) as error:
        authed.request("/api/quotations", {})

    message = str(error.value)
    assert "ROLE_API_CLIENT" in message
    assert "Access Denied." in message
    assert "missing authorization" in message
    assert error.value.response is not None
    assert error.value.response.status_code == 403


@responses.activate
def test_403_elsewhere_does_not_claim_the_role_is_missing(authed: BiblIndexClient) -> None:
    responses.get(f"{BASE_URL}/api/works", status=403, json={})

    with pytest.raises(AccessDeniedError) as error:
        authed.request("/api/works", {})

    assert "ROLE_API_CLIENT" not in str(error.value)


@responses.activate
def test_bare_description_key_is_read_too(authed: BiblIndexClient) -> None:
    """API Platform 4 serves the error body's keys bare, like everything else."""
    responses.get(RESOURCE_URL, status=403, json={"description": "Access Denied."})

    with pytest.raises(AccessDeniedError) as error:
        authed.request("/api/quotations", {})

    assert "Access Denied." in str(error.value)


@pytest.mark.parametrize("status", [400, 404, 409, 500, 503])
@responses.activate
def test_http_errors_stay_catchable_as_requests_http_error(
    authed: BiblIndexClient, status: int
) -> None:
    """The compatibility guarantee for code written against 0.2.x."""
    responses.get(RESOURCE_URL, status=status, json={})

    with pytest.raises(requests.HTTPError) as error:
        authed.request("/api/quotations", {})

    assert isinstance(error.value, BiblIndexHTTPError)
    assert isinstance(error.value, BiblIndexError)


@responses.activate
def test_403_is_also_a_requests_http_error(authed: BiblIndexClient) -> None:
    responses.get(RESOURCE_URL, status=403, json={})

    with pytest.raises(requests.HTTPError):
        authed.request("/api/quotations", {})


@responses.activate
def test_token_rejection_surfaces_the_oauth_reason(client: BiblIndexClient) -> None:
    responses.post(
        TOKEN_URL,
        status=400,
        json={"error": "invalid_grant", "error_description": "Invalid credentials."},
    )

    with pytest.raises(AuthenticationError) as error:
        client.fetchTokens()

    assert "Invalid credentials." in str(error.value)
    assert "password grant" in str(error.value)
    # Token state is left untouched on failure.
    assert client.accessToken is None


@responses.activate
def test_persistent_401_raises_authentication_error(client: BiblIndexClient) -> None:
    responses.post(TOKEN_URL, json=make_token_payload())
    responses.get(RESOURCE_URL, status=401, json={"description": "Expired token."})

    with pytest.raises(AuthenticationError) as error:
        client.request("/api/quotations", {})

    assert "Expired token." in str(error.value)


@responses.activate
def test_non_json_body_is_reported_clearly(authed: BiblIndexClient) -> None:
    """A proxy's HTML 200 used to surface as a raw JSONDecodeError."""
    responses.get(
        RESOURCE_URL,
        status=200,
        body="<html>502 Bad Gateway</html>",
        content_type="text/html",
    )

    with pytest.raises(BiblIndexError) as error:
        authed.request("/api/quotations", {})

    assert "non-JSON body" in str(error.value)
    assert "text/html" in str(error.value)
