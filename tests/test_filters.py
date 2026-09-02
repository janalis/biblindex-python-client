"""Refusal of query parameters an endpoint would accept and then ignore."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import responses

from biblindex_client import (
    BiblIndexClient,
    FilterVocabularyUnavailableError,
    PageSizeError,
    UndeclaredParameterError,
)

from .conftest import BASE_URL, make_hydra_collection, make_iri_template, make_openapi_document

DOCS_URL = f"{BASE_URL}/api/docs.jsonopenapi"


@pytest.fixture
def authed(client: BiblIndexClient) -> BiblIndexClient:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    return client


def register_docs(paths: dict[str, list[str]]) -> None:
    responses.get(DOCS_URL, json=make_openapi_document(paths))


@responses.activate
def test_undeclared_param_raises_before_any_request(
    authed: BiblIndexClient, openapi_paths: dict[str, list[str]]
) -> None:
    """The 709,440-row hazard: /api/quotations has no author filter."""
    register_docs(openapi_paths)

    with pytest.raises(UndeclaredParameterError) as error:
        authed.request("/api/quotations", {"author": 42})

    message = str(error.value)
    assert "'author'" in message
    assert "work" in message
    assert "would look filtered but would not be" in message
    # Only the docs fetch happened; the resource was never requested.
    assert len(responses.calls) == 1
    assert responses.calls[0].request.url.startswith(DOCS_URL)


@responses.activate
def test_declared_param_is_sent(
    authed: BiblIndexClient, openapi_paths: dict[str, list[str]]
) -> None:
    register_docs(openapi_paths)
    responses.get(f"{BASE_URL}/api/works", json=make_hydra_collection([], total_items=8))

    authed.request("/api/works", {"author": 42})

    assert "author=42" in responses.calls[-1].request.url


@responses.activate
def test_pagination_only_params_skip_discovery(authed: BiblIndexClient) -> None:
    """The common browse path must not pay for schema discovery."""
    responses.get(f"{BASE_URL}/api/works", json=make_hydra_collection([], total_items=0))

    authed.request("/api/works", {"page": 1, "itemsPerPage": 30})

    assert len(responses.calls) == 1
    assert "docs.jsonopenapi" not in responses.calls[0].request.url


@responses.activate
def test_locale_is_refused_with_an_explanation(
    authed: BiblIndexClient, openapi_paths: dict[str, list[str]]
) -> None:
    """`?locale=fr` returns 200 and English; the caller must be told."""
    register_docs(openapi_paths)

    with pytest.raises(UndeclaredParameterError) as error:
        authed.request("/api/authors", {"locale": "fr"})

    assert "locale" in str(error.value)
    assert "no effect" in str(error.value)


@responses.activate
def test_validation_can_be_disabled_per_call(
    authed: BiblIndexClient, openapi_paths: dict[str, list[str]]
) -> None:
    register_docs(openapi_paths)
    responses.get(f"{BASE_URL}/api/quotations", json=make_hydra_collection([]))

    authed.request("/api/quotations", {"author": 42}, validateParams=False)

    assert "author=42" in responses.calls[-1].request.url


@responses.activate
def test_unknown_vocabulary_raises_rather_than_guessing(authed: BiblIndexClient) -> None:
    responses.get(DOCS_URL, status=404)

    with pytest.raises(UndeclaredParameterError) as error:
        authed.request("/api/quotations", {"author": 42})

    assert "declared filters are unknown" in str(error.value)
    assert "validateParams=False" in str(error.value)


@responses.activate
def test_docs_are_fetched_once_even_after_failure(authed: BiblIndexClient) -> None:
    responses.get(DOCS_URL, status=500)

    for _ in range(3):
        with pytest.raises(UndeclaredParameterError):
            authed.request("/api/quotations", {"author": 42})

    assert len(responses.calls) == 1


@responses.activate
def test_search_block_teaches_the_vocabulary(authed: BiblIndexClient) -> None:
    """The `search` block is free, and covers a server whose docs are unreachable."""
    responses.get(DOCS_URL, status=404)
    responses.get(
        f"{BASE_URL}/api/works",
        json=make_hydra_collection(
            [], total_items=0, search=make_iri_template("clavisNumbers", "author")
        ),
    )

    authed.request("/api/works", {"page": 1})

    assert authed.filtersFor("/api/works") == frozenset({"clavisNumbers", "author"})

    with pytest.raises(UndeclaredParameterError):
        authed.request("/api/works", {"nonsense": 1})


@responses.activate
def test_array_and_scalar_spellings_are_interchangeable(
    authed: BiblIndexClient, openapi_paths: dict[str, list[str]]
) -> None:
    register_docs(openapi_paths)
    responses.get(f"{BASE_URL}/api/verses", json=make_hydra_collection([]))

    authed.request("/api/verses", {"book": 49})
    authed.request("/api/verses", {"book[]": 49})


@responses.activate
def test_filters_for_reports_declared_filters(
    authed: BiblIndexClient, openapi_paths: dict[str, list[str]]
) -> None:
    register_docs(openapi_paths)

    assert authed.filtersFor("/api/quotations") == frozenset({"work"})
    # An endpoint that genuinely declares none, distinct from one we cannot read.
    assert authed.filtersFor("/api/books") == frozenset()


@responses.activate
def test_filters_for_raises_when_it_cannot_know(authed: BiblIndexClient) -> None:
    """Never report "no filters" for an endpoint the client simply cannot read."""
    responses.get(DOCS_URL, status=404)

    with pytest.raises(FilterVocabularyUnavailableError):
        authed.filtersFor("/api/quotations")


@responses.activate
def test_page_size_above_the_server_cap_raises(authed: BiblIndexClient) -> None:
    """itemsPerPage=500 silently serves 100; clamping would repeat the bug."""
    with pytest.raises(PageSizeError) as error:
        authed.request("/api/books", {"itemsPerPage": 500})

    assert "100" in str(error.value)
    assert len(responses.calls) == 0
