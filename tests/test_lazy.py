"""Tests for lazy resource and collection wrappers."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import responses

from biblindex_client import BiblIndexClient, LazyCollection, LazyResource

from .conftest import BASE_URL

EXTRACT_URL = f"{BASE_URL}/api/extracts/42"


@responses.activate
def test_lazy_resource_behaves_like_mutable_mapping(client: BiblIndexClient) -> None:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(
        EXTRACT_URL,
        json={"@id": "/api/extracts/42", "title": "Extract 42", "place": "/api/places/1"},
    )

    resource = LazyResource(client, "/api/extracts/42", {})

    assert resource.resource == "/api/extracts/42"
    assert repr(resource) == "LazyResource('/api/extracts/42')"
    assert len(resource) == 3
    assert set(resource) == {"@id", "title", "place"}

    resource["title"] = "Updated"
    assert resource["title"] == "Updated"
    assert isinstance(resource["place"], LazyResource)
    del resource["place"]
    assert "place" not in resource
    assert repr(resource) == "{'@id': '/api/extracts/42', 'title': 'Updated'}"


def test_lazy_resource_returns_seed_while_already_loading(client: BiblIndexClient) -> None:
    resource = LazyResource(client, "/api/extracts/42", {}, {"id": 42})
    resource._loading = True

    assert resource._load() == {"id": 42}


@responses.activate
def test_lazy_collection_behaves_like_mutable_sequence(client: BiblIndexClient) -> None:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(
        f"{BASE_URL}/api/things?page=2",
        json=[{"id": 3}],
    )
    responses.get(
        f"{BASE_URL}/api/things?page=3",
        json=[],
    )
    collection = LazyCollection(
        client,
        [1, 2],
        currentResource="/api/things?page=1",
        nextResource="/api/things?page=2",
        totalItems=None,
        cache={},
    )

    assert collection[0] == 1
    assert collection[:1] == [1]
    assert collection[:0] == []
    assert isinstance(collection[2], LazyResource)
    assert collection[2]["id"] == 3
    assert collection.loadedItems == 3
    assert [item["id"] if isinstance(item, LazyResource) else item for item in collection] == [
        1,
        2,
        3,
    ]
    assert collection[-1]["id"] == 3
    assert repr(collection) == "LazyCollection(loadedItems=3, totalItems=None)"

    collection[0] = 10
    collection.insert(1, 11)
    del collection[2]
    assert collection[:2] == [10, 11]


@responses.activate
def test_lazy_collection_fetches_pages_for_iteration_and_open_slice(
    client: BiblIndexClient,
) -> None:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(f"{BASE_URL}/api/things?page=2", json=[{"id": 2}])
    responses.get(f"{BASE_URL}/api/things?page=3", json=[])
    responses.get(f"{BASE_URL}/api/more-things?page=2", json=[{"id": 20}])
    responses.get(f"{BASE_URL}/api/more-things?page=3", json=[])
    collection = LazyCollection(
        client,
        [1],
        currentResource="/api/things?page=1",
        nextResource="/api/things?page=2",
        totalItems=None,
        cache={},
    )

    assert [item["id"] if isinstance(item, LazyResource) else item for item in collection] == [
        1,
        2,
    ]
    assert collection[:] == [1, collection[1]]

    otherCollection = LazyCollection(
        client,
        [10],
        currentResource="/api/more-things?page=1",
        nextResource="/api/more-things?page=2",
        totalItems=None,
        cache={},
    )

    assert [
        item["id"] if isinstance(item, LazyResource) else item for item in otherCollection[:]
    ] == [
        10,
        20,
    ]


@responses.activate
def test_lazy_collection_stops_on_non_collection_next_page(
    client: BiblIndexClient,
) -> None:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(f"{BASE_URL}/api/things?page=2", json={"items": []})
    collection = LazyCollection(
        client,
        [1],
        currentResource="/api/things?page=1",
        nextResource="/api/things?page=2",
        totalItems=None,
        cache={},
    )

    with pytest.raises(IndexError):
        collection[1]


@responses.activate
def test_lazy_collection_handles_hydra_page_without_members(
    client: BiblIndexClient,
) -> None:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(
        f"{BASE_URL}/api/things?page=2",
        json={"hydra:member": None, "hydra:view": {"hydra:next": "/api/things?page=3"}},
    )
    responses.get(
        f"{BASE_URL}/api/things?page=3",
        json={"hydra:member": [{"@id": "/api/things/2"}]},
    )
    collection = LazyCollection(
        client,
        [1],
        currentResource="/api/things?page=1",
        nextResource="/api/things?page=2",
        totalItems=None,
        cache={},
    )

    assert collection[1]["@id"] == "/api/things/2"


@responses.activate
def test_lazy_collection_stops_on_scalar_next_page(client: BiblIndexClient) -> None:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    responses.get(f"{BASE_URL}/api/things?page=2", json="not a collection")
    collection = LazyCollection(
        client,
        [1],
        currentResource="/api/things?page=1",
        nextResource="/api/things?page=2",
        totalItems=None,
        cache={},
    )

    assert list(collection) == [1]


def test_lazy_resource_blocks_hydra_keys(client: BiblIndexClient) -> None:
    resource = LazyResource(client, "/api/extracts/42", {})
    resource._data = {
        "@id": "/api/extracts/42",
        "@type": "Extract",
        "@context": "/api/contexts/Extract",
        "title": "Extract 42",
        "hydra:view": {"@id": "/api/extracts/42"},
        "hydra:totalItems": 1,
    }

    with pytest.raises(KeyError):
        resource["hydra:view"]
    with pytest.raises(KeyError):
        resource["hydra:totalItems"] = 2
    with pytest.raises(KeyError):
        del resource["hydra:view"]

    keys = list(resource)
    assert "hydra:view" not in keys
    assert "hydra:totalItems" not in keys
    assert "@id" in keys
    assert "@type" in keys
    assert "@context" in keys
    assert "title" in keys

    assert len(resource) == 4
