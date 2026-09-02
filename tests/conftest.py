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


def make_hydra_collection(
    members: list[Any],
    *,
    total_items: int | None = None,
    next_page: str | None = None,
    search: dict[str, Any] | None = None,
    prefixed: bool = False,
    context: str = "/api/contexts/Thing",
) -> dict[str, Any]:
    """Build a Hydra collection envelope in either key spelling.

    Bare keys mirror a live API Platform 4 response, recorded from
    ``GET /api/books?itemsPerPage=2&page=1`` on 02/09/2026::

        {"@context": "/api/contexts/Book", "@id": "/api/books",
         "@type": "Collection", "totalItems": 107, "member": [...],
         "view": {"@id": "...", "@type": "PartialCollectionView",
                  "first": "...", "last": "...", "next": "..."}}

    ``prefixed=True`` produces the API Platform 3 spelling the client also
    still supports.
    """
    prefix = "hydra:" if prefixed else ""

    envelope: dict[str, Any] = {
        "@context": context,
        "@id": "/api/things",
        "@type": "hydra:Collection" if prefixed else "Collection",
        f"{prefix}member": members,
    }

    if total_items is not None:
        envelope[f"{prefix}totalItems"] = total_items

    view: dict[str, Any] = {
        "@id": "/api/things?page=1",
        "@type": "hydra:PartialCollectionView" if prefixed else "PartialCollectionView",
    }
    if next_page is not None:
        view[f"{prefix}next" if prefixed else "next"] = next_page
    envelope[f"{prefix}view"] = view

    if search is not None:
        envelope[f"{prefix}search"] = search

    return envelope


def make_iri_template(*variables: str, template: str = "/api/things") -> dict[str, Any]:
    """Build a Hydra IriTemplate, as API Platform advertises declared filters.

    Recorded from ``GET /api/works`` on 02/09/2026.
    """
    return {
        "@type": "IriTemplate",
        "template": f"{template}{{?{','.join(variables)}}}",
        "variableRepresentation": "BasicRepresentation",
        "mapping": [
            {
                "@type": "IriTemplateMapping",
                "variable": variable,
                "property": variable,
                "required": False,
            }
            for variable in variables
        ],
    }


def make_openapi_document(paths: dict[str, list[str]]) -> dict[str, Any]:
    """Build an OpenAPI document declaring GET query parameters per path."""
    return {
        "openapi": "3.1.0",
        "paths": {
            path: {
                "get": {
                    "parameters": [
                        {"name": name, "in": "query", "schema": {"type": "string"}}
                        for name in names
                    ]
                }
            }
            for path, names in paths.items()
        },
    }


@pytest.fixture
def openapi_paths() -> dict[str, list[str]]:
    """Declared parameters recorded from the live API on 02/09/2026."""
    return {
        "/api/quotations": ["page", "itemsPerPage", "work"],
        "/api/works": ["page", "itemsPerPage", "clavisNumbers", "author"],
        "/api/verses": ["page", "itemsPerPage", "bible", "bible[]", "book", "book[]"],
        "/api/books": ["page", "itemsPerPage"],
        "/api/authors": ["page", "itemsPerPage"],
    }
