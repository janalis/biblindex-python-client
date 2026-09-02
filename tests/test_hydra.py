"""Hydra envelope handling: bare keys, the collection discriminator, id backfill."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
import responses

from biblindex_client import BiblIndexClient, LazyCollection
from biblindex_client.lazy import (
    collectionValue,
    envelopeValue,
    hydraEnvelopeKeys,
    isHydraCollection,
)

from .conftest import BASE_URL, make_hydra_collection


@pytest.fixture
def authed(client: BiblIndexClient) -> BiblIndexClient:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    return client


# --- the discriminator -------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"@type": "Collection", "member": []}, True),
        ({"@type": "hydra:Collection"}, True),
        ({"hydra:member": [{"@id": "/api/things/1"}]}, True),
        ({"member": [], "totalItems": 7}, True),
        ({"member": [], "view": {"@id": "/api/things"}}, True),
        ({"member": [], "@context": "/api/contexts/Thing"}, True),
        # A domain field that merely shares a bare envelope name.
        ({"member": "Association of Studies", "name": "x"}, False),
        ({"member": [{"name": "a"}], "name": "x"}, False),
        ({"@id": "/api/works/1", "title": "x"}, False),
    ],
)
def test_is_hydra_collection_discriminates(payload: dict[str, Any], expected: bool) -> None:
    assert isHydraCollection(payload) is expected


def test_bare_envelope_names_survive_on_a_plain_resource() -> None:
    """A resource field named `member` or `view` must not be hidden."""
    work = {"@id": "/api/works/1", "member": "Association of Studies", "view": "public"}

    assert hydraEnvelopeKeys(work) == frozenset()
    assert collectionValue(work, "member") is None


def test_prefixed_keys_are_hidden_even_outside_a_collection() -> None:
    """`hydra:` is never a legal domain field name, so it needs no discriminator."""
    payload = {"@id": "/api/things/1", "hydra:view": {}, "title": "x"}

    assert hydraEnvelopeKeys(payload) == frozenset({"hydra:view"})


def test_envelope_value_reads_either_spelling() -> None:
    assert envelopeValue({"next": "/p2"}, "next") == "/p2"
    assert envelopeValue({"hydra:next": "/p2"}, "next") == "/p2"
    assert envelopeValue({}, "next") is None


# --- end-to-end, both spellings ---------------------------------------------


@pytest.mark.parametrize("prefixed", [False, True], ids=["bare", "prefixed"])
@responses.activate
def test_request_wraps_collection_in_either_spelling(
    authed: BiblIndexClient, prefixed: bool
) -> None:
    """The regression net for the 0.2.3 bug: bare keys must yield a collection."""
    responses.get(
        f"{BASE_URL}/api/things",
        json=make_hydra_collection(
            [{"@id": "/api/things/1", "@type": "Thing"}],
            total_items=107,
            prefixed=prefixed,
        ),
    )

    result = authed.request("/api/things", {})

    assert isinstance(result, LazyCollection)
    assert len(result) == 107
    assert result.loadedItems == 1
    assert result.totalItems == 107


@responses.activate
def test_bare_collection_is_not_a_seven_key_dict(authed: BiblIndexClient) -> None:
    """0.2.3 returned a dict of envelope keys here, and len() was the key count."""
    responses.get(
        f"{BASE_URL}/api/things",
        json=make_hydra_collection([{"@id": "/api/things/1"}], total_items=107),
    )

    result = authed.request("/api/things", {})

    assert not isinstance(result, dict)
    assert len(result) != 7


@pytest.mark.parametrize("prefixed", [False, True], ids=["bare", "prefixed"])
@responses.activate
def test_next_page_resolves_in_either_spelling(authed: BiblIndexClient, prefixed: bool) -> None:
    responses.get(
        f"{BASE_URL}/api/things",
        json=make_hydra_collection(
            [{"@id": "/api/things/1"}],
            total_items=2,
            next_page="/api/things?page=2",
            prefixed=prefixed,
        ),
    )
    responses.get(
        f"{BASE_URL}/api/things?page=2",
        json=make_hydra_collection([{"@id": "/api/things/2"}], total_items=2, prefixed=prefixed),
    )

    result = authed.request("/api/things", {})
    items = list(result)

    assert len(items) == 2
    assert result.isComplete


# --- id backfill -------------------------------------------------------------


@responses.activate
def test_id_is_backfilled_from_the_iri(authed: BiblIndexClient) -> None:
    """Live ld+json omits `id` on authors; a join keyed on it matched nothing."""
    responses.get(
        f"{BASE_URL}/api/authors",
        json=make_hydra_collection(
            [{"@id": "/api/authors/2", "@type": "Author", "name": "Aelredus"}],
            total_items=1,
        ),
    )

    responses.get(
        f"{BASE_URL}/api/authors/2",
        json={"@id": "/api/authors/2", "@type": "Author", "name": "Aelredus"},
    )

    collection = authed.request("/api/authors", {})
    author = collection[0]

    # Served straight from the collection seed, without fetching the item.
    assert author["id"] == 2
    assert len(responses.calls) == 1

    # And present once the item itself is loaded.
    assert "id" in set(author)


@responses.activate
def test_backfill_never_clobbers_a_real_id(authed: BiblIndexClient) -> None:
    responses.get(
        f"{BASE_URL}/api/things/1",
        json={"@id": "/api/things/1", "id": 99, "title": "x"},
    )

    result = authed.request("/api/things/1", {})

    assert result["id"] == 99


@responses.activate
@responses.activate
def test_backfill_can_be_disabled() -> None:
    client = BiblIndexClient(
        baseUrl=BASE_URL,
        username="u",
        password="p",
        clientId="i",
        clientSecret="s",
        backfillIds=False,
    )
    client.accessToken = "A"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(f"{BASE_URL}/api/authors/2", json={"@id": "/api/authors/2", "name": "x"})

    result = client.request("/api/authors/2", {})

    assert "id" not in result


def test_identifier_extraction(client: BiblIndexClient) -> None:
    assert client._identifierFromResource("/api/authors/42") == 42
    assert client._identifierFromResource("/api/authors/42?x=1") == 42
    assert client._identifierFromResource("/api/works/1/editions/2") == 2
    assert client._identifierFromResource("/api/authors/9a3f-uuid") == "9a3f-uuid"
    # A collection path carries no identifier.
    assert client._identifierFromResource("/api/authors") is None
    assert client._identifierFromResource("/other/42") is None
