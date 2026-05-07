from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping, MutableSequence
from typing import Any, Protocol


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


class LazyResource(MutableMapping[str, Any]):
    """Mapping proxy that fetches an API resource when its data is read."""

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

    def __getitem__(self, key: str) -> Any:
        if self._data is None and key in {"@id", "@type", "id"} and key in self._seed:
            return self._seed[key]

        return self._load()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._load()[key] = value

    def __delitem__(self, key: str) -> None:
        del self._load()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._load())

    def __len__(self) -> int:
        return len(self._load())

    def __repr__(self) -> str:
        if self._data is None:
            return f"LazyResource({self._resource!r})"

        return repr(self._data)


class LazyCollection(MutableSequence[Any]):
    """List-like collection that fetches following Hydra pages on demand."""

    def __init__(
        self,
        client: ResourceClient,
        items: list[Any],
        *,
        currentResource: str,
        nextResource: str | None,
        totalItems: int | None,
        cache: dict[str, Any],
    ) -> None:
        self._client = client
        self._items = items
        self._currentResource = currentResource
        self._nextResource = nextResource
        self._totalItems = totalItems
        self._cache = cache

    @property
    def loadedItems(self) -> int:
        """Number of items already loaded locally."""
        return len(self._items)

    def _fetchNextPage(self) -> bool:
        if self._nextResource is None:
            return False

        nextResource = self._nextResource
        page = self._client._requestJson(nextResource, {})
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

        members = page.get("hydra:member", [])
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

    def _fetchUntilIndex(self, index: int) -> None:
        while index >= len(self._items) and self._fetchNextPage():
            pass

    def __getitem__(self, index: int | slice) -> Any:
        if isinstance(index, slice):
            stop = index.stop
            if stop is None:
                self._fetchAllPages()
            elif stop > 0:
                self._fetchUntilIndex(stop - 1)
            return self._items[index]

        if index < 0:
            self._fetchAllPages()
        else:
            self._fetchUntilIndex(index)

        return self._items[index]

    def __setitem__(self, index: int | slice, value: Any) -> None:
        self._items[index] = value

    def __delitem__(self, index: int | slice) -> None:
        del self._items[index]

    def __len__(self) -> int:
        return self._totalItems if self._totalItems is not None else len(self._items)

    def insert(self, index: int, value: Any) -> None:
        self._items.insert(index, value)

    def __iter__(self) -> Iterator[Any]:
        index = 0
        while True:
            if index < len(self._items):
                yield self._items[index]
                index += 1
                continue

            if not self._fetchNextPage():
                break

    def __repr__(self) -> str:
        return f"LazyCollection(loadedItems={len(self._items)}, totalItems={self._totalItems!r})"

    def _fetchAllPages(self) -> None:
        while self._fetchNextPage():
            pass
