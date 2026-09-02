"""Page budgets, explicit walks, and the server's 100-item cap."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
import responses

from biblindex_client import BiblIndexClient, PaginationLimitError

from .conftest import BASE_URL, make_hydra_collection


@pytest.fixture
def authed(client: BiblIndexClient) -> BiblIndexClient:
    client.accessToken = "A"
    client.refreshToken = "R"
    client.expiresIn = datetime.now() + timedelta(seconds=300)
    return client


def register_pages(count: int, *, total: int) -> None:
    """Register a chain of single-item Hydra pages."""
    for page in range(1, count + 1):
        nextPage = f"/api/things?page={page + 1}" if page < count else None
        url = f"{BASE_URL}/api/things" if page == 1 else f"{BASE_URL}/api/things?page={page}"
        responses.get(
            url,
            json=make_hydra_collection(
                [{"@id": f"/api/things/{page}"}], total_items=total, next_page=nextPage
            ),
        )


@responses.activate
def test_iteration_stops_at_the_page_budget(authed: BiblIndexClient) -> None:
    """`for q in collection` over quotations would be ~7,000 requests."""
    authed.maxAutoPages = 3
    register_pages(10, total=10)

    collection = authed.request("/api/things", {})

    with pytest.raises(PaginationLimitError) as error:
        list(collection)

    message = str(error.value)
    assert "fetchAll" in message
    assert "maxAutoPages" in message


@responses.activate
def test_negative_index_is_budgeted(authed: BiblIndexClient) -> None:
    """`collection[-1]` silently walked every page in 0.2.3."""
    authed.maxAutoPages = 2
    register_pages(10, total=10)

    collection = authed.request("/api/things", {})

    with pytest.raises(PaginationLimitError):
        collection[-1]


@responses.activate
def test_fetch_all_is_explicit_and_unbudgeted(authed: BiblIndexClient) -> None:
    authed.maxAutoPages = 2
    register_pages(5, total=5)

    collection = authed.request("/api/things", {})
    items = collection.fetchAll()

    assert len(items) == 5
    assert collection.isComplete


@responses.activate
def test_fetch_all_honours_max_items(authed: BiblIndexClient) -> None:
    register_pages(5, total=5)

    collection = authed.request("/api/things", {})

    assert len(collection.fetchAll(maxItems=3)) == 3


@responses.activate
def test_iter_all_is_unbudgeted(authed: BiblIndexClient) -> None:
    authed.maxAutoPages = 1
    register_pages(4, total=4)

    collection = authed.request("/api/things", {})

    assert len(list(collection.iterAll())) == 4


@responses.activate
def test_len_reports_the_total_while_loaded_is_smaller(authed: BiblIndexClient) -> None:
    """The gap is real and documented: len() answers "how many match"."""
    register_pages(4, total=4)

    collection = authed.request("/api/things", {})

    assert len(collection) == 4
    assert collection.loadedItems == 1
    assert collection.hasMore
    assert not collection.isComplete


@responses.activate
def test_client_fetch_all_pages_a_capped_collection(authed: BiblIndexClient) -> None:
    """/api/books reports 107 but serves at most 100 per page."""
    register_pages(3, total=107)

    items: list[Any] = authed.fetchAll("/api/things")

    assert len(items) == 3
