from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Protocol

from biblindex_client.errors import PaginationLimitError

# Hydra envelope properties. API Platform 4 serves them bare; 3 prefixes them.
# Both are read, so the client works against either generation of the server.
_BARE_ENVELOPE_KEYS = frozenset({"member", "view", "search", "totalItems"})
_PREFIXED_ENVELOPE_KEYS = frozenset(
    {"hydra:member", "hydra:view", "hydra:search", "hydra:totalItems"}
)

_COLLECTION_TYPES = frozenset({"Collection", "hydra:Collection"})


class ResourceClient(Protocol):
    """Client behavior required by lazy resources and collections."""

    def _requestJson(self, resource: str, params: Mapping[str, Any]) -> Any: ...

    def _wrapLinkedResources(
        self,
        data: Any,
        *,
        currentResource: str,
        cache: dict[str, Any],
    ) -> Any: ...

    def _nextPlainJsonPageResource(self, resource: str) -> str | None: ...

    def _nextPageResource(self, data: Mapping[str, Any]) -> str | None: ...

    def _recordVocabulary(self, resource: str, data: Any) -> None: ...


def envelopeValue(data: Mapping[str, Any], name: str) -> Any:
    """Read a Hydra property in either spelling, from a known envelope.

    Used where the mapping is already known to be metadata — the ``view``
    object, for instance — so a bare name carries no ambiguity.
    """
    if name in data:
        return data[name]

    return data.get(f"hydra:{name}")


def isHydraCollection(data: Mapping[str, Any]) -> bool:
    """Whether a mapping is a Hydra collection envelope rather than a resource.

    Needed because the bare spellings (``member``, ``view``, ``totalItems``,
    ``search``) are also plausible domain field names. Hiding them
    unconditionally would mask real data — the very failure this client exists
    to prevent — so they are only treated as metadata inside a real envelope.
    """
    if data.get("@type") in _COLLECTION_TYPES:
        return True

    if any(key in data for key in _PREFIXED_ENVELOPE_KEYS):
        return True

    if not isinstance(data.get("member"), list):
        return False

    # A bare ``member`` list alone is not enough: corroborate it with another
    # envelope marker before treating the payload as a collection.
    return (
        isinstance(data.get("totalItems"), int)
        or isinstance(data.get("view"), Mapping)
        or "@context" in data
    )


def collectionValue(data: Mapping[str, Any], name: str) -> Any:
    """Read a Hydra envelope property from a payload that may be a resource."""
    prefixed = data.get(f"hydra:{name}")
    if prefixed is not None:
        return prefixed

    if isHydraCollection(data):
        return data.get(name)

    return None


def hydraEnvelopeKeys(data: Mapping[str, Any]) -> frozenset[str]:
    """Envelope keys to hide from a mapping's public view.

    Prefixed keys are always metadata — ``hydra:`` is not a legal domain field
    name. Bare keys are only metadata inside a collection envelope.
    """
    hidden = {key for key in data if key in _PREFIXED_ENVELOPE_KEYS}

    if isHydraCollection(data):
        hidden |= {key for key in data if key in _BARE_ENVELOPE_KEYS}

    return frozenset(hidden)


class LazyResource(Mapping[str, Any]):
    """Read-only mapping proxy that fetches an API resource when data is read.

    Read-only on purpose: the BiblIndex API is not writable through this client,
    so an assignment that appeared to succeed would never reach the server.
    """

    def __init__(
        self,
        client: ResourceClient,
        resource: str,
        cache: dict[str, Any],
        seed: Mapping[str, Any] | None = None,
    ) -> None:
        self._client = client
        self._resource = resource
        self._cache = cache
        self._seed = dict(seed or {})
        self._data: dict[str, Any] | None = None
        self._loading = False

    @property
    def resource(self) -> str:
        """Normalized API path represented by this lazy resource."""
        return self._resource

    def _load(self) -> dict[str, Any]:
        if self._data is not None:
            return self._data

        if self._loading:
            return self._seed

        self._loading = True
        try:
            raw = self._client._requestJson(self._resource, {})
            self._data = self._client._wrapLinkedResources(
                raw,
                currentResource=self._resource,
                cache=self._cache,
            )
        finally:
            self._loading = False

        return self._data

    def _hiddenKeys(self, data: Mapping[str, Any]) -> frozenset[str]:
        return hydraEnvelopeKeys(data)

    def __getitem__(self, key: str) -> Any:
        if key in _PREFIXED_ENVELOPE_KEYS:
            raise KeyError(key)

        if self._data is None and key in {"@id", "@type", "id"} and key in self._seed:
            return self._seed[key]

        data = self._load()
        if key in self._hiddenKeys(data):
            raise KeyError(key)

        return data[key]

    def __iter__(self) -> Iterator[str]:
        data = self._load()
        hidden = self._hiddenKeys(data)
        for key in data:
            if key not in hidden:
                yield key

    def __len__(self) -> int:
        data = self._load()

        return len(data) - len(self._hiddenKeys(data))

    def __repr__(self) -> str:
        if self._data is None:
            return f"LazyResource({self._resource!r})"

        return repr(self._data)


class LazyCollection(Sequence[Any]):
    """Read-only sequence that fetches following Hydra pages on demand.

    Implicit paging is capped by ``maxAutoPages``. Without a cap, a single
    ``list(collection)`` on ``/api/quotations`` would issue several thousand
    requests against a laboratory server; :meth:`fetchAll` makes that explicit.
    """

    def __init__(
        self,
        client: ResourceClient,
        items: list[Any],
        *,
        currentResource: str,
        nextResource: str | None,
        totalItems: int | None,
        cache: dict[str, Any],
        maxAutoPages: int | None = None,
        search: Mapping[str, Any] | None = None,
    ) -> None:
        self._client = client
        self._items = items
        self._currentResource = currentResource
        self._nextResource = nextResource
        self._totalItems = totalItems
        self._cache = cache
        self._maxAutoPages = maxAutoPages
        self._search = search
        self._pagesFetched = 0

    @property
    def loadedItems(self) -> int:
        """Number of items already loaded locally."""
        return len(self._items)

    @property
    def totalItems(self) -> int | None:
        """Total the server reports, or None when it reports none."""
        return self._totalItems

    @property
    def isComplete(self) -> bool:
        """Whether every page has been loaded."""
        return self._nextResource is None

    @property
    def hasMore(self) -> bool:
        """Whether at least one further page remains."""
        return self._nextResource is not None

    @property
    def search(self) -> Mapping[str, Any] | None:
        """The Hydra ``IriTemplate`` declaring this endpoint's filters."""
        return self._search

    def _fetchNextPage(self) -> bool:
        if self._nextResource is None:
            return False

        nextResource = self._nextResource
        page = self._client._requestJson(nextResource, {})
        self._pagesFetched += 1

        if isinstance(page, list):
            if not page:
                self._nextResource = None
                return False

            wrappedItems = self._client._wrapLinkedResources(
                page,
                currentResource=nextResource,
                cache=self._cache,
            )
            self._items.extend(wrappedItems)
            self._currentResource = nextResource
            self._nextResource = self._client._nextPlainJsonPageResource(nextResource)
            return True

        if not isinstance(page, dict):
            self._nextResource = None
            return False

        self._client._recordVocabulary(nextResource, page)

        members = collectionValue(page, "member")
        if isinstance(members, list):
            wrappedMembers = self._client._wrapLinkedResources(
                members,
                currentResource=nextResource,
                cache=self._cache,
            )
            self._items.extend(wrappedMembers)

        self._currentResource = nextResource
        self._nextResource = self._client._nextPageResource(page)
        return True

    def _paginationLimitMessage(self, budget: int) -> str:
        total = self._totalItems if self._totalItems is not None else "an unknown number of"

        return (
            f"Refusing to auto-fetch beyond {budget} page(s) of "
            f"{self._currentResource}: {self.loadedItems} item(s) loaded out of "
            f"{total}. Implicit paging is capped so a single indexing or "
            f"iteration cannot issue thousands of requests. If you meant to walk "
            f"the whole collection, call collection.fetchAll() or iterate "
            f"collection.iterAll(); to change the cap, construct the client with "
            f"maxAutoPages=N, or None to disable it."
        )

    def _fetchWithinBudget(self, budget: int | None) -> bool:
        """Fetch one more page, honouring a page budget."""
        if budget is not None and self._pagesFetched >= budget:
            raise PaginationLimitError(self._paginationLimitMessage(budget))

        return self._fetchNextPage()

    def _fetchUntilIndex(self, index: int) -> None:
        while index >= len(self._items) and self._fetchWithinBudget(self._maxAutoPages):
            pass

    def _fetchAllPages(self, budget: int | None) -> None:
        while self._fetchWithinBudget(budget):
            pass

    def fetchAll(self, *, maxItems: int | None = None, maxPages: int | None = None) -> list[Any]:
        """Walk every page and return the items.

        Explicit by design: this is the call that says "yes, fetch all of it".
        """
        while maxItems is None or len(self._items) < maxItems:
            if not self._fetchWithinBudget(maxPages):
                break

        return list(self._items) if maxItems is None else list(self._items[:maxItems])

    def iterAll(self, *, maxItems: int | None = None) -> Iterator[Any]:
        """Iterate every item, page by page, without an implicit page cap."""
        index = 0
        while maxItems is None or index < maxItems:
            if index < len(self._items):
                yield self._items[index]
                index += 1
                continue

            if not self._fetchNextPage():
                break

    def iterPages(self, *, maxPages: int | None = None) -> Iterator[list[Any]]:
        """Iterate the collection one page at a time."""
        start = 0
        while True:
            if start < len(self._items):
                yield list(self._items[start:])
                start = len(self._items)
                continue

            if not self._fetchWithinBudget(maxPages):
                break

    def __getitem__(self, index: int | slice) -> Any:
        if isinstance(index, slice):
            stop = index.stop
            if stop is None:
                self._fetchAllPages(self._maxAutoPages)
            elif stop > 0:
                self._fetchUntilIndex(stop - 1)
            return self._items[index]

        if index < 0:
            self._fetchAllPages(self._maxAutoPages)
        else:
            self._fetchUntilIndex(index)

        return self._items[index]

    def __len__(self) -> int:
        return self._totalItems if self._totalItems is not None else len(self._items)

    def __iter__(self) -> Iterator[Any]:
        index = 0
        while True:
            if index < len(self._items):
                yield self._items[index]
                index += 1
                continue

            if not self._fetchWithinBudget(self._maxAutoPages):
                break

    def __repr__(self) -> str:
        return f"LazyCollection(loadedItems={len(self._items)}, totalItems={self._totalItems!r})"
