"""Discovery of the query parameters each API endpoint actually declares.

API Platform answers 200 and silently drops query parameters an endpoint does
not declare, so a filtered and an unfiltered result are indistinguishable to the
caller. This module collects the endpoint's declared vocabulary so the client
can refuse such a parameter instead of returning a plausible wrong answer.

Two sources feed the same cache:

``/api/docs.jsonopenapi``
    The full OpenAPI document. Public, so it needs no token, and it is the only
    source that can validate the *first* call to an endpoint.

The ``search`` block of a collection response
    API Platform ships a Hydra ``IriTemplate`` on every collection that declares
    filters. It costs nothing — the envelope is already in hand — and keeps the
    cache honest if the OpenAPI document is stale or unreachable.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# Pagination controls, handled by API Platform itself. They never appear in an
# endpoint's declared filters, so they are always legitimate.
ALWAYS_ALLOWED = frozenset({"page", "itemsPerPage", "pagination"})

OPENAPI_RESOURCE = "/api/docs.jsonopenapi"

# The docs endpoint serves application/vnd.openapi+json and answers 406 to a
# plain application/json request, so the negotiation has to be explicit.
OPENAPI_ACCEPT = "application/vnd.openapi+json, application/json;q=0.9, */*;q=0.5"


def _parameterNames(operation: Any) -> set[str]:
    """Collect declared parameter names from one OpenAPI GET operation."""
    if not isinstance(operation, Mapping):
        return set()

    parameters = operation.get("parameters")
    if not isinstance(parameters, list):
        return set()

    names: set[str] = set()
    for parameter in parameters:
        if isinstance(parameter, Mapping):
            name = parameter.get("name")
            if isinstance(name, str):
                names.add(name)

    return names


def searchVariables(search: Any) -> set[str]:
    """Collect filter variables from a Hydra ``IriTemplate`` search block."""
    if not isinstance(search, Mapping):
        return set()

    mapping = search.get("mapping")
    if not isinstance(mapping, list):
        return set()

    variables: set[str] = set()
    for entry in mapping:
        if isinstance(entry, Mapping):
            variable = entry.get("variable")
            if isinstance(variable, str):
                variables.add(variable)

    return variables


class FilterVocabulary:
    """Per-endpoint cache of declared query parameters."""

    def __init__(self) -> None:
        self._byResource: dict[str, set[str]] = {}
        self._openApiAttempted = False

    @property
    def openApiAttempted(self) -> bool:
        """Whether an OpenAPI load has already been tried this session."""
        return self._openApiAttempted

    def markOpenApiAttempted(self) -> None:
        """Record that the OpenAPI document was fetched, or failed to fetch."""
        self._openApiAttempted = True

    def knows(self, resource: str) -> bool:
        """Whether anything is known about ``resource``."""
        return resource in self._byResource

    def declaredFor(self, resource: str) -> frozenset[str]:
        """Declared filters for ``resource``, empty when none are declared."""
        return frozenset(self._byResource.get(resource, set()))

    def recordOpenApi(self, document: Any) -> None:
        """Absorb an OpenAPI document, one entry per path with a GET operation."""
        self.markOpenApiAttempted()

        if not isinstance(document, Mapping):
            return

        paths = document.get("paths")
        if not isinstance(paths, Mapping):
            return

        for path, operations in paths.items():
            if not isinstance(path, str) or not isinstance(operations, Mapping):
                continue

            names = _parameterNames(operations.get("get"))
            self._byResource.setdefault(path, set()).update(names - ALWAYS_ALLOWED)

    def recordSearch(self, resource: str, search: Any) -> None:
        """Absorb the ``search`` block of a collection response.

        Unioned rather than replacing: a server may support more than its
        OpenAPI document admits, and a false rejection is worse than a miss.
        """
        variables = searchVariables(search)
        if not variables:
            return

        self._byResource.setdefault(resource, set()).update(variables - ALWAYS_ALLOWED)

    def undeclared(self, resource: str, params: Iterable[str]) -> set[str]:
        """Return the parameters ``resource`` does not declare."""
        declared = self._byResource.get(resource)
        if declared is None:
            return set()

        return {name for name in params if not _isAllowed(name, declared)}


def _isAllowed(name: str, declared: set[str]) -> bool:
    """Whether a parameter name matches a declared filter.

    Accepts the array spellings API Platform declares alongside the scalar one
    (``book`` and ``book[]``), and the bracketed form a caller may send
    (``book[0]``).
    """
    if name in ALWAYS_ALLOWED or name in declared:
        return True

    if f"{name}[]" in declared:
        return True

    base = name.split("[", maxsplit=1)[0]

    return base in declared or f"{base}[]" in declared
