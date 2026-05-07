"""Tests for the BiblIndexClient HTTP wrapper."""

from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import parse_qs

import pytest
import requests
import responses

from biblindex_client import BiblIndexClient, LazyCollection, LazyResource

from .conftest import BASE_URL, TOKEN_URL, make_token_payload

RESOURCE_PATH = "/api/quotations"
RESOURCE_URL = f"{BASE_URL}{RESOURCE_PATH}"
QUOTATION_URL = f"{BASE_URL}{RESOURCE_PATH}/1229419"
EXTRACT_URL = f"{BASE_URL}/api/extracts/42"
WORK_1_URL = f"{BASE_URL}/api/works/1"
WORK_2_URL = f"{BASE_URL}/api/works/2"


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
    assert client.accept == "application/ld+json"
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
    assert api_call.request.headers["Accept"] == "application/ld+json"


@responses.activate
def test_request_can_use_application_json_accept_header() -> None:
    client = BiblIndexClient(
        baseUrl=BASE_URL,
        username="user",
        password="pass",
        clientId="id",
        clientSecret="secret",
        accept="application/json",
    )
    responses.post(TOKEN_URL, json=make_token_payload("A1", "R1"))
    responses.get(RESOURCE_URL, json=[])

    client.request(RESOURCE_PATH, {"page": 1})

    assert responses.calls[1].request.headers["Accept"] == "application/json"


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


@responses.activate
def test_request_lazy_fetches_collection_members_from_response_links(
    client: BiblIndexClient,
) -> None:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(
        RESOURCE_URL,
        json={
            "@context": "/api/contexts/Quotation",
            "@id": "/api/quotations",
            "@type": "hydra:Collection",
            "hydra:member": [
                "/api/quotations/1229419",
                {"@id": "/api/quotations/1229420", "@type": "Quotation"},
            ],
            "hydra:view": {"@id": "/api/quotations?page=1"},
        },
    )
    responses.get(
        QUOTATION_URL,
        json={"@id": "/api/quotations/1229419", "@type": "Quotation", "number": 1229419},
    )
    responses.get(
        f"{BASE_URL}/api/quotations/1229420",
        json={"@id": "/api/quotations/1229420", "@type": "Quotation", "number": 1229420},
    )

    result = client.request(RESOURCE_PATH, {})

    assert isinstance(result, LazyCollection)
    firstMember = result[0]
    secondMember = result[1]
    assert isinstance(firstMember, LazyResource)
    assert isinstance(secondMember, LazyResource)
    assert len(responses.calls) == 1

    assert firstMember["number"] == 1229419
    assert secondMember["@id"] == "/api/quotations/1229420"
    assert len(responses.calls) == 2

    assert secondMember["number"] == 1229420
    assert len(responses.calls) == 3
    assert responses.calls[1].request.url == QUOTATION_URL
    assert responses.calls[2].request.url == f"{BASE_URL}/api/quotations/1229420"


@responses.activate
def test_request_lazy_fetches_collection_pages_when_accessing_later_items(
    client: BiblIndexClient,
) -> None:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(
        RESOURCE_URL,
        json={
            "@id": "/api/quotations",
            "@type": "hydra:Collection",
            "hydra:member": [{"@id": "/api/quotations/1229419", "@type": "Quotation"}],
            "hydra:totalItems": 2,
            "hydra:view": {
                "@id": "/api/quotations?page=1",
                "@type": "hydra:PartialCollectionView",
                "hydra:next": "/api/quotations?page=2",
            },
        },
    )
    responses.get(
        f"{RESOURCE_URL}?page=2",
        json={
            "@id": "/api/quotations",
            "@type": "hydra:Collection",
            "hydra:member": [{"@id": "/api/quotations/1229420", "@type": "Quotation"}],
            "hydra:totalItems": 2,
            "hydra:view": {
                "@id": "/api/quotations?page=2",
                "@type": "hydra:PartialCollectionView",
            },
        },
    )

    result = client.request(RESOURCE_PATH, {})

    assert isinstance(result, LazyCollection)
    assert len(result) == 2
    assert result.loadedItems == 1
    assert len(responses.calls) == 1

    assert result[1]["@id"] == "/api/quotations/1229420"
    assert result.loadedItems == 2
    assert len(responses.calls) == 2
    assert responses.calls[1].request.url == f"{RESOURCE_URL}?page=2"


@responses.activate
def test_request_lazy_fetches_collection_members_from_item_ids(
    client: BiblIndexClient,
) -> None:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(
        RESOURCE_URL,
        json=[
            {"id": 1229419, "extract": "/api/extracts/42"},
            {"id": 1229420},
        ],
    )
    responses.get(
        QUOTATION_URL,
        json={"id": 1229419, "extract": "/api/extracts/42", "number": 1229419},
    )
    responses.get(
        f"{BASE_URL}/api/quotations/1229420",
        json={"id": 1229420, "number": 1229420},
    )

    result = client.request(RESOURCE_PATH, {})

    assert isinstance(result, LazyCollection)
    firstMember = result[0]
    secondMember = result[1]
    assert isinstance(firstMember, LazyResource)
    assert isinstance(secondMember, LazyResource)
    assert len(responses.calls) == 1

    assert firstMember["id"] == 1229419
    assert len(responses.calls) == 1

    assert firstMember["number"] == 1229419
    assert isinstance(firstMember["extract"], LazyResource)
    assert secondMember["number"] == 1229420
    assert len(responses.calls) == 3
    assert responses.calls[1].request.url == QUOTATION_URL
    assert responses.calls[2].request.url == f"{BASE_URL}/api/quotations/1229420"


@responses.activate
def test_request_lazy_fetches_application_json_collection_pages(
    client: BiblIndexClient,
) -> None:
    client.accept = "application/json"
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(
        RESOURCE_URL,
        json=[
            {"id": 1229419},
            {"id": 1229420},
        ],
    )
    responses.get(
        f"{RESOURCE_URL}?page=2",
        json=[
            {"id": 1229421},
        ],
    )

    result = client.request(RESOURCE_PATH, {"page": 1})

    assert isinstance(result, LazyCollection)
    assert result.loadedItems == 2
    assert len(result) == 2
    assert len(responses.calls) == 1

    thirdMember = result[2]

    assert isinstance(thirdMember, LazyResource)
    assert thirdMember["id"] == 1229421
    assert result.loadedItems == 3
    assert len(responses.calls) == 2
    assert responses.calls[1].request.url == f"{RESOURCE_URL}?page=2"
    assert responses.calls[1].request.headers["Accept"] == "application/json"


@responses.activate
def test_request_lazy_fetches_linked_item_properties(client: BiblIndexClient) -> None:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(
        QUOTATION_URL,
        json={
            "@id": "/api/quotations/1229419",
            "@type": "Quotation",
            "extract": "/api/extracts/42",
            "works": [
                "/api/works/1",
                {"@id": "/api/works/2", "@type": "Work"},
            ],
        },
    )
    responses.get(
        EXTRACT_URL,
        json={"@id": "/api/extracts/42", "@type": "Extract", "title": "Extract 42"},
    )
    responses.get(
        WORK_1_URL,
        json={"@id": "/api/works/1", "@type": "Work", "title": "Work 1"},
    )
    responses.get(
        WORK_2_URL,
        json={"@id": "/api/works/2", "@type": "Work", "title": "Work 2"},
    )

    result = client.request("/api/quotations/1229419", {})

    assert result["@id"] == "/api/quotations/1229419"
    assert isinstance(result["extract"], LazyResource)
    assert isinstance(result["works"][0], LazyResource)
    assert isinstance(result["works"][1], LazyResource)
    assert len(responses.calls) == 1

    assert result["extract"]["title"] == "Extract 42"
    assert len(responses.calls) == 2

    assert result["works"][0]["title"] == "Work 1"
    assert result["works"][1]["@id"] == "/api/works/2"
    assert len(responses.calls) == 3

    assert result["works"][1]["title"] == "Work 2"
    assert len(responses.calls) == 4


@responses.activate
def test_request_lazy_fetch_uses_cache_when_same_resource_is_linked_multiple_times(
    client: BiblIndexClient,
) -> None:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(
        QUOTATION_URL,
        json={
            "@id": "/api/quotations/1229419",
            "extract": "/api/extracts/42",
            "relatedExtract": "/api/extracts/42",
        },
    )
    responses.get(
        EXTRACT_URL,
        json={"@id": "/api/extracts/42", "@type": "Extract", "title": "Extract 42"},
    )

    result = client.request("/api/quotations/1229419", {})

    assert result["extract"] is result["relatedExtract"]
    assert len(responses.calls) == 1

    assert result["extract"]["title"] == "Extract 42"
    assert len(responses.calls) == 2
    assert result["relatedExtract"]["title"] == "Extract 42"
    assert len(responses.calls) == 2


def test_client_helpers_cover_non_resource_branches(client: BiblIndexClient) -> None:
    assert client._linkedResource(42) is None
    assert client._linkedResource("https://other.example.com/api/things/1") is None
    assert client._linkedResource("not-a-resource") is None
    assert client._linkedResource("/api/token") is None
    assert client._linkedResource(f"{BASE_URL}/api/things/1") == "/api/things/1"
    assert client._linkedResource(f"{BASE_URL}/api/things/1?foo=bar") == ("/api/things/1?foo=bar")
    assert client._linkedResource("api/things/1") == "/api/things/1"

    assert client._nextPageResource({}) is None
    assert client._nextPlainJsonPageResource("/api/things") is None
    assert client._nextPlainJsonPageResource("/api/things?page=abc") is None
    assert client._nextPlainJsonPageResource("/api/things?page=1&limit=10") == (
        "/api/things?page=2&limit=10"
    )

    assert client._resourceFromCollectionItem({}, "/api/things") is None
    assert client._resourceFromCollectionItem({"id": 1}, "/not-api/things") is None
    assert client._resourceFromCollectionItem({"id": 1}, "/api/things/1") is None
    assert client._normalizeResource(f"{BASE_URL}/api/things/1") == "/api/things/1"
    assert client._resourceWithParams("/api/things?existing=1", {"page": 2}) == (
        "/api/things?existing=1&page=2"
    )


def test_client_wrapping_helpers_cover_reference_branches(client: BiblIndexClient) -> None:
    cache: dict[str, object] = {}

    assert client._wrapLinkedResources(
        [{"name": "not a resource"}],
        currentResource="/api/things",
        cache=cache,
    ) == [{"name": "not a resource"}]
    assert (
        client._wrapLinkedResources(
            "/api/things/1",
            currentResource="/api/things/1",
            cache=cache,
        )
        == "/api/things/1"
    )
    assert isinstance(
        client._wrapLinkedResources(
            "/api/things/2",
            currentResource="/api/things/1",
            cache=cache,
        ),
        LazyResource,
    )

    wrappedSelfReference = client._wrapLinkedResourceProperties(
        {"self": "/api/things/1"},
        currentResource="/api/things/1",
        cache=cache,
    )
    assert wrappedSelfReference == {"self": "/api/things/1"}

    wrappedLinkedMapping = client._wrapLinkedResourceProperties(
        {"place": {"@id": "/api/places/1", "name": "Paris"}},
        currentResource="/api/things/1",
        cache=cache,
    )
    assert isinstance(wrappedLinkedMapping["place"], LazyResource)
    assert wrappedLinkedMapping["place"]["@id"] == "/api/places/1"

    wrappedNestedSelfReference = client._wrapLinkedResourceProperties(
        {"place": {"@id": "/api/things/1", "name": "Current"}},
        currentResource="/api/things/1",
        cache=cache,
    )
    assert wrappedNestedSelfReference == {"place": {"@id": "/api/things/1", "name": "Current"}}


def test_wrap_linked_resource_properties_skips_hydra_keys(client: BiblIndexClient) -> None:
    wrapped = client._wrapLinkedResourceProperties(
        {"hydra:view": {"@id": "/api/things?page=1"}, "title": "foo"},
        currentResource="/api/things",
        cache={},
    )
    assert "hydra:view" not in wrapped
    assert wrapped["title"] == "foo"
