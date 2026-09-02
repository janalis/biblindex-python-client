"""Defensive branches: malformed bodies, odd IRIs, and the explicit walk limits."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import responses

from biblindex_client import AuthenticationError, BiblIndexClient, LazyResource
from biblindex_client.errors import accessDeniedMessage, describeErrorBody
from biblindex_client.schema import FilterVocabulary

from .conftest import BASE_URL, TOKEN_URL, make_hydra_collection, make_iri_template


@pytest.fixture
def authed(client: BiblIndexClient) -> BiblIndexClient:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    return client


# --- error body extraction ---------------------------------------------------


def test_describe_error_body_without_a_response() -> None:
    assert describeErrorBody(None) is None
    assert "403 Access Denied on /api/works." in accessDeniedMessage("/api/works", None)


@responses.activate
def test_describe_error_body_ignores_a_non_mapping_body(authed: BiblIndexClient) -> None:
    """An error body that is a JSON array carries no description to read."""
    responses.get(f"{BASE_URL}/api/works", status=403, json=["nope"])

    with pytest.raises(Exception) as error:
        authed.request("/api/works", {})

    assert "Server said" not in str(error.value)


@responses.activate
def test_token_rejection_without_a_readable_body(client: BiblIndexClient) -> None:
    responses.post(TOKEN_URL, status=503, body="upstream down", content_type="text/plain")

    with pytest.raises(AuthenticationError) as error:
        client.fetchTokens()

    assert str(error.value) == "The token endpoint rejected the password grant (503)."


# --- id backfill edges -------------------------------------------------------


def test_backfill_ignores_an_iri_without_an_identifier(client: BiblIndexClient) -> None:
    """A collection IRI names no item, so there is no id to derive."""
    assert client._withBackfilledId({"@id": "/api/authors"}) == {"@id": "/api/authors"}
    assert client._withBackfilledId({"@id": "/elsewhere/42"}) == {"@id": "/elsewhere/42"}
    assert client._withBackfilledId({"name": "x"}) == {"name": "x"}


# --- lazy resource internals -------------------------------------------------


def test_bare_envelope_keys_are_hidden_on_a_collection_payload(
    client: BiblIndexClient,
) -> None:
    """The mirror of the prefixed case: bare keys hidden, but only in an envelope."""
    resource = LazyResource(client, "/api/things", {})
    resource._data = {
        "@id": "/api/things",
        "@type": "Collection",
        "totalItems": 2,
        "member": [{"@id": "/api/things/1"}],
        "view": {"@id": "/api/things?page=1"},
        "title": "visible",
    }

    with pytest.raises(KeyError):
        resource["member"]
    with pytest.raises(KeyError):
        resource["totalItems"]

    assert set(resource) == {"@id", "@type", "title"}
    assert resource["title"] == "visible"


@responses.activate
def test_loaded_resource_reprs_its_data(authed: BiblIndexClient) -> None:
    responses.get(f"{BASE_URL}/api/things/1", json={"@id": "/api/things/1", "title": "x"})

    resource = LazyResource(authed, "/api/things/1", {})

    assert repr(resource) == "LazyResource('/api/things/1')"
    resource["title"]
    assert repr(resource) == "{'@id': '/api/things/1', 'title': 'x', 'id': 1}"


# --- collection extras -------------------------------------------------------


@responses.activate
def test_collection_exposes_its_search_template(authed: BiblIndexClient) -> None:
    """The IriTemplate the endpoint advertises is kept, not discarded."""
    responses.get(
        f"{BASE_URL}/api/works",
        json=make_hydra_collection([], total_items=0, search=make_iri_template("author")),
    )

    collection = authed.request("/api/works", {})

    assert collection.search is not None
    assert collection.search["@type"] == "IriTemplate"


@responses.activate
def test_iter_all_stops_at_max_items(authed: BiblIndexClient) -> None:
    """maxItems must stop the walk without fetching the remaining pages."""
    responses.get(
        f"{BASE_URL}/api/things",
        json=make_hydra_collection(
            [{"@id": "/api/things/1"}, {"@id": "/api/things/2"}],
            total_items=99,
            next_page="/api/things?page=2",
        ),
    )

    collection = authed.request("/api/things", {})

    assert len(list(collection.iterAll(maxItems=2))) == 2
    # Page 2 was never requested.
    assert len(responses.calls) == 1


# --- filter matching ---------------------------------------------------------


def test_scalar_name_matches_an_array_only_declaration() -> None:
    """API Platform declares `book[]`; a caller sending `book` means the same."""
    vocabulary = FilterVocabulary()
    vocabulary.recordOpenApi(
        {"paths": {"/api/verses": {"get": {"parameters": [{"name": "book[]"}]}}}}
    )

    assert vocabulary.undeclared("/api/verses", {"book"}) == set()
    assert vocabulary.undeclared("/api/verses", {"book[0]"}) == set()
    assert vocabulary.undeclared("/api/verses", {"chapter"}) == {"chapter"}
