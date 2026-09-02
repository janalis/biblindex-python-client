"""Demonstrate the client against the live API.

Reads credentials from .env.local. Run with ``make run``.
"""

import os

from dotenv_flow import dotenv_flow

from biblindex_client import (
    AccessDeniedError,
    BiblIndexClient,
    LazyCollection,
    PageSizeError,
    UndeclaredParameterError,
)

dotenv_flow("local")


def main() -> None:
    client = BiblIndexClient(
        os.getenv("BIBLINDEX_API_URL", ""),
        os.getenv("BIBLINDEX_API_USER", ""),
        os.getenv("BIBLINDEX_API_PASSWORD", ""),
        os.getenv("BIBLINDEX_API_KEY", ""),
        os.getenv("BIBLINDEX_API_SECRET", ""),
    )

    print("== Collections ==")
    books = client.request("/api/books", {"itemsPerPage": 100, "page": 1})
    print(f"/api/books -> {type(books).__name__}")
    print(f"  totalItems={len(books)} loaded={books.loadedItems} complete={books.isComplete}")

    print("\n== Paging past the server's 100-item cap ==")
    print(f"fetchAll -> {len(client.fetchAll('/api/books'))} items")
    try:
        client.request("/api/books", {"itemsPerPage": 500})
    except PageSizeError as error:
        print(f"itemsPerPage=500 refused: {str(error)[:70]}...")

    print("\n== Declared filters ==")
    for resource in ("/api/quotations", "/api/verses", "/api/works", "/api/books"):
        print(f"  {resource:20s} {sorted(client.filtersFor(resource))}")

    print("\n== A filter the endpoint would silently ignore ==")
    try:
        client.request("/api/quotations", {"author": 42})
    except UndeclaredParameterError as error:
        print(f"  refused: {str(error)[:100]}...")

    print("\n== A filter it does declare ==")
    works = client.request("/api/works", {"author": 42, "itemsPerPage": 1, "page": 1})
    print(f"  /api/works?author=42 -> {len(works)} works")

    print("\n== id backfilled from the @id IRI (absent in ld+json) ==")
    authors = client.request("/api/authors", {"itemsPerPage": 1, "page": 1})
    if isinstance(authors, LazyCollection) and authors.loadedItems:
        author = authors[0]
        print(f"  @id={author['@id']!r} -> id={author['id']!r}")

    print("\n== The corpus, which needs ROLE_API_CLIENT ==")
    try:
        quotations = client.request("/api/quotations", {"page": 1})
        print(f"  reachable: {len(quotations)} quotations")
    except AccessDeniedError as error:
        print(f"  {str(error)[:160]}...")

    client.close()


if __name__ == "__main__":
    main()
