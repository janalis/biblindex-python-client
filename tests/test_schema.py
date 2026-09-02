"""Filter vocabulary parsing, including malformed input."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
import requests
import responses

from biblindex_client import MAX_ITEMS_PER_PAGE, BiblIndexClient, BiblIndexError
from biblindex_client.schema import FilterVocabulary, searchVariables

from .conftest import BASE_URL, make_hydra_collection, make_iri_template

DOCS_URL = f"{BASE_URL}/api/docs.jsonopenapi"


@pytest.fixture
def authed(client: BiblIndexClient) -> BiblIndexClient:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    return client


@pytest.mark.parametrize(
    "document",
    [
        None,
        "not a mapping",
        {},
        {"paths": "not a mapping"},
        {"paths": {"/api/things": "not a mapping"}},
        {"paths": {"/api/things": {"get": {"parameters": "not a list"}}}},
        {"paths": {"/api/things": {"get": {"parameters": [{"noName": 1}, "junk"]}}}},
        {"paths": {"/api/things": {}}},
    ],
)
def test_malformed_openapi_documents_are_tolerated(document: Any) -> None:
    """Discovery is best-effort; a bad document must not raise."""
    vocabulary = FilterVocabulary()
    vocabulary.recordOpenApi(document)

    assert vocabulary.openApiAttempted


@pytest.mark.parametrize(
    ("search", "expected"),
    [
        (make_iri_template("author"), {"author"}),
        (None, set()),
        ("not a mapping", set()),
        ({"mapping": "not a list"}, set()),
        ({"mapping": [{"noVariable": 1}, "junk"]}, set()),
        ({}, set()),
    ],
)
def test_search_variable_parsing(search: Any, expected: set[str]) -> None:
    assert searchVariables(search) == expected


def test_unknown_resource_reports_nothing_undeclared() -> None:
    """An unknown endpoint yields no verdict, rather than a wrong one."""
    vocabulary = FilterVocabulary()

    assert vocabulary.undeclared("/api/things", {"anything"}) == set()
    assert not vocabulary.knows("/api/things")


def test_search_is_unioned_with_openapi() -> None:
    """A server may support more than its document admits."""
    vocabulary = FilterVocabulary()
    vocabulary.recordOpenApi(
        {"paths": {"/api/works": {"get": {"parameters": [{"name": "author"}]}}}}
    )
    vocabulary.recordSearch("/api/works", make_iri_template("clavisNumbers"))

    assert vocabulary.declaredFor("/api/works") == frozenset({"author", "clavisNumbers"})


def test_empty_search_block_is_ignored() -> None:
    vocabulary = FilterVocabulary()
    vocabulary.recordSearch("/api/works", {"mapping": []})

    assert not vocabulary.knows("/api/works")


def test_pagination_params_are_never_recorded_as_filters() -> None:
    vocabulary = FilterVocabulary()
    vocabulary.recordOpenApi(
        {
            "paths": {
                "/api/books": {"get": {"parameters": [{"name": "page"}, {"name": "itemsPerPage"}]}}
            }
        }
    )

    assert vocabulary.declaredFor("/api/books") == frozenset()
    assert vocabulary.knows("/api/books")


@responses.activate
def test_non_numeric_page_size_is_left_alone(authed: BiblIndexClient) -> None:
    responses.get(f"{BASE_URL}/api/books", json=make_hydra_collection([]))

    authed.request("/api/books", {"itemsPerPage": "all"})

    assert MAX_ITEMS_PER_PAGE == 100


@responses.activate
def test_iter_pages_yields_page_by_page(authed: BiblIndexClient) -> None:
    responses.get(
        f"{BASE_URL}/api/things",
        json=make_hydra_collection(
            [{"@id": "/api/things/1"}], total_items=2, next_page="/api/things?page=2"
        ),
    )
    responses.get(
        f"{BASE_URL}/api/things?page=2",
        json=make_hydra_collection([{"@id": "/api/things/2"}], total_items=2),
    )

    collection = authed.request("/api/things", {})
    pages = list(collection.iterPages())

    assert [len(page) for page in pages] == [1, 1]


@responses.activate
def test_iter_collection_walks_every_page(authed: BiblIndexClient) -> None:
    responses.get(
        f"{BASE_URL}/api/things",
        json=make_hydra_collection(
            [{"@id": "/api/things/1"}], total_items=2, next_page="/api/things?page=2"
        ),
    )
    responses.get(
        f"{BASE_URL}/api/things?page=2",
        json=make_hydra_collection([{"@id": "/api/things/2"}], total_items=2),
    )

    assert len(list(authed.iterCollection("/api/things"))) == 2


@responses.activate
def test_fetch_all_on_a_single_resource_is_refused(authed: BiblIndexClient) -> None:
    responses.get(f"{BASE_URL}/api/things/1", json={"@id": "/api/things/1", "title": "x"})

    with pytest.raises(BiblIndexError) as error:
        authed.fetchAll("/api/things/1")

    assert "did not return a collection" in str(error.value)


@responses.activate
def test_docs_transport_failure_is_tolerated(authed: BiblIndexClient) -> None:
    responses.get(DOCS_URL, body=requests.ConnectionError("boom"))
    responses.get(f"{BASE_URL}/api/works", json=make_hydra_collection([]))

    # Discovery failed, so the filter cannot be verified and is refused.
    with pytest.raises(BiblIndexError):
        authed.request("/api/works", {"author": 1})


@responses.activate
def test_openapi_request_negotiates_the_right_media_type(authed: BiblIndexClient) -> None:
    """The live docs endpoint answers 406 to a plain application/json request."""
    responses.get(DOCS_URL, json={"paths": {}})
    responses.get(f"{BASE_URL}/api/works", json=make_hydra_collection([]))

    with pytest.raises(BiblIndexError):
        authed.request("/api/works", {"author": 1})

    accept = responses.calls[0].request.headers["Accept"]
    assert "application/vnd.openapi+json" in accept
