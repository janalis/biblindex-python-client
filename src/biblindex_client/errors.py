"""Exception hierarchy for the BiblIndex client.

The API answers several failure modes with a bare status code and a body a
caller rarely reads, so a plain :class:`requests.HTTPError` loses the one piece
of information that explains what to do next. These types carry the diagnosis
in the message instead.

``BiblIndexHTTPError`` inherits :class:`requests.HTTPError`, so code written
against earlier releases that catches ``requests.HTTPError`` keeps working.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import requests

# Resources gated behind ``ROLE_API_CLIENT``. A 403 on any of these has a known
# cause worth stating outright rather than making the caller infer it.
CORPUS_RESOURCES = frozenset(
    {
        "/api/quotations",
        "/api/verses",
        "/api/extracts",
        "/api/sequences",
        "/api/patristic_mentions",
    }
)

# Keys API Platform uses for the human-readable part of an error body, in the
# bare and prefixed spellings both major versions emit.
_DESCRIPTION_KEYS = (
    "description",
    "hydra:description",
    "detail",
    # OAuth2 token-endpoint failures, where the reason is the whole point.
    "error_description",
    "title",
    "hydra:title",
    "message",
    "error",
)


class BiblIndexError(Exception):
    """Base class for every error raised by this package."""


class BiblIndexHTTPError(BiblIndexError, requests.HTTPError):
    """An API call failed.

    Also a :class:`requests.HTTPError`, so existing ``except`` clauses that
    predate this hierarchy continue to catch it.
    """


class AuthenticationError(BiblIndexHTTPError):
    """The token endpoint rejected the credentials."""


class AccessDeniedError(BiblIndexHTTPError):
    """The token is valid but the account is not authorized for the resource."""


class UndeclaredParameterError(BiblIndexError, ValueError):
    """A query parameter the endpoint does not declare, and would silently drop.

    Raised before the request is sent. API Platform answers 200 and ignores
    parameters it does not know, so an unfiltered result is indistinguishable
    from a filtered one; refusing up front is the only way a caller finds out.
    """


class PaginationLimitError(BiblIndexError):
    """A collection walk exceeded its page budget."""


def describeErrorBody(response: requests.Response | None) -> str | None:
    """Extract the server's human-readable explanation from an error body."""
    if response is None:
        return None

    try:
        body: Any = response.json()
    except ValueError:
        return None

    if not isinstance(body, Mapping):
        return None

    for key in _DESCRIPTION_KEYS:
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None


def accessDeniedMessage(
    resource: str,
    response: requests.Response | None,
    *,
    anonymous: bool = False,
) -> str:
    """Build the message for a 403, naming the missing role when it is known."""
    parts = [f"403 Access Denied on {resource}."]

    description = describeErrorBody(response)
    if description:
        parts.append(f"Server said: {description}")

    if anonymous:
        # No token was sent, so nothing can be concluded about an account.
        parts.append(
            "This client was built without credentials, so no token was sent. "
            "This resource is not public: construct the client with username, "
            "password, clientId and clientSecret."
        )
        if resource.split("?", maxsplit=1)[0] in CORPUS_RESOURCES:
            parts.append(
                "Note that credentials alone may not be enough here — this "
                "resource also requires the ROLE_API_CLIENT role on the account."
            )

        return " ".join(parts)

    if resource.split("?", maxsplit=1)[0] in CORPUS_RESOURCES:
        parts.append(
            "The token itself is valid — /api/works and /api/authors accept the "
            "same one — so this is a missing authorization rather than an "
            "authentication failure. The account needs ROLE_API_CLIENT; ask the "
            "BiblIndex maintainers to grant it."
        )
    else:
        parts.append(
            "The token was accepted but the account is not authorized for this "
            "resource. Check the roles granted to the API account."
        )

    return " ".join(parts)


def undeclaredParameterMessage(
    resource: str,
    offenders: Iterable[str],
    declared: Iterable[str],
) -> str:
    """Build the message for parameters the endpoint would silently ignore."""
    offenderList = sorted(offenders)
    declaredList = sorted(declared)

    parts = [
        f"{resource} does not declare {', '.join(repr(o) for o in offenderList)}.",
        (
            "API Platform ignores undeclared query parameters and still answers "
            "200, so the result would look filtered but would not be."
        ),
    ]

    if declaredList:
        parts.append(f"Declared filters: {', '.join(declaredList)}.")
    else:
        parts.append("This endpoint declares no filters at all.")

    if "locale" in offenderList:
        parts.append(
            "Note: 'locale' is accepted by some BiblIndex endpoints but has no "
            "effect — name and description are served in English regardless."
        )

    parts.append("Pass validateParams=False to send it anyway.")

    return " ".join(parts)


class PageSizeError(BiblIndexError, ValueError):
    """A requested page size the server would silently reduce."""


class FilterVocabularyUnavailableError(BiblIndexError):
    """The declared filters for a resource could not be determined.

    Raised rather than reporting "no filters", which a caller would read as a
    fact about the endpoint instead of a gap in the client's knowledge.
    """


def pageSizeMessage(requested: int, maximum: int) -> str:
    """Build the message for a page size above the server's cap."""
    return (
        f"itemsPerPage={requested} exceeds the server cap of {maximum}. "
        f"BiblIndex silently serves {maximum} items instead, so the extra would "
        f"look like a short page rather than a capped one. Ask for "
        f"{maximum} or fewer and page through the rest — client.fetchAll() and "
        f"client.iterCollection() do that for you."
    )


def vocabularyUnavailableMessage(resource: str, params: Iterable[str]) -> str:
    """Build the message for filters that cannot be checked against a schema."""
    return (
        f"Cannot verify {', '.join(repr(p) for p in sorted(params))} against "
        f"{resource}: the declared filters are unknown, because "
        f"/api/docs.jsonopenapi could not be read and no response from this "
        f"endpoint has advertised a search template yet. Sending them anyway "
        f"risks a silently unfiltered result. Pass validateParams=False to "
        f"proceed regardless."
    )
