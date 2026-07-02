from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from types import TracebackType
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from biblindex_client.lazy import LazyCollection, LazyResource

JSON_LD_MIME_TYPE = "application/ld+json"

DEFAULT_TIMEOUT: float = 30.0

# Refresh tokens slightly before their actual expiry so a token that would
# expire mid-request is renewed up front.
TOKEN_EXPIRY_LEEWAY_SECONDS: int = 30


class BiblIndexClient:
    """HTTP client for interacting with the BiblIndex API.

    Handles:
    - Authentication via OAuth2 password grant
    - Automatic token refresh, including re-authentication on a 401 response
    - Authenticated GET requests to API resources

    Attributes:
        baseUrl: Base URL of the API.
        username: API username.
        password: API password.
        clientId: OAuth client ID.
        clientSecret: OAuth client secret.
        accept: Media type used in the ``Accept`` header for API GET requests.
        timeout: Timeout in seconds applied to every HTTP call, either a
            single value or a ``(connect, read)`` tuple; ``None`` disables it.
        retries: Number of transport-level retries for GET requests
            (``0`` disables retries).
        accessToken: Current access token, or None before first auth.
        refreshToken: Refresh token used to renew access tokens.
        expiresIn: Expiration time of the current access token.
        session: Reusable HTTP session.
    """

    def __init__(
        self,
        baseUrl: str,
        username: str,
        password: str,
        clientId: str,
        clientSecret: str,
        accept: str = JSON_LD_MIME_TYPE,
        timeout: float | tuple[float, float] | None = DEFAULT_TIMEOUT,
        retries: int = 0,
    ) -> None:
        """Initialize the API client with credentials and configuration."""
        self.baseUrl: str = baseUrl
        self.username: str = username
        self.password: str = password
        self.clientId: str = clientId
        self.clientSecret: str = clientSecret
        self.accept: str = accept
        self.timeout: float | tuple[float, float] | None = timeout
        self.retries: int = retries

        self.accessToken: str | None = None
        self.refreshToken: str | None = None
        self.expiresIn: datetime | None = None

        self.session: requests.Session = requests.Session()

        if retries > 0:
            # GET-only: token POSTs must never be blindly retried, as a retry
            # after an ambiguous failure could rotate the refresh token
            # server-side and desynchronize auth state.
            retry = Retry(
                total=retries,
                backoff_factor=0.5,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET"}),
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry)
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()

    def __enter__(self) -> BiblIndexClient:
        return self

    def __exit__(
        self,
        excType: type[BaseException] | None,
        excValue: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def request(self, resource: str, params: Mapping[str, Any]) -> Any:
        """Perform an authenticated GET request to the API.

        Automatically fetches tokens if missing, and refreshes them if
        expired before issuing the call. If the API still answers 401, the
        tokens are renewed and the call is replayed once. API resource links
        found in the response body are wrapped in lazy resources that are
        fetched on access.

        Args:
            resource: API resource path. Must start with a leading slash
                (e.g. ``/api/quotations``); a missing leading slash is
                normalized for convenience.
            params: Query parameters for the request.

        Returns:
            Parsed JSON response from the API.

        Raises:
            requests.HTTPError: If the HTTP request fails.
        """
        resource = self._normalizeResource(resource)
        currentResource = self._resourceWithParams(resource, params)
        data = self._requestJson(resource, params)
        cache = {resource: data, currentResource: data}

        wrapped = self._wrapLinkedResources(
            data,
            currentResource=currentResource,
            cache=cache,
        )
        if isinstance(data, list) and isinstance(wrapped, list):
            return LazyCollection(
                self,
                wrapped,
                currentResource=currentResource,
                nextResource=self._nextPlainJsonPageResource(currentResource),
                totalItems=None,
                cache=cache,
            )

        return wrapped

    def _requestJson(self, resource: str, params: Mapping[str, Any]) -> Any:
        """Perform an authenticated GET request and return the raw JSON body.

        A 401 response triggers a token renewal and a single replay of the
        request; a second 401 is raised as :class:`requests.HTTPError`.
        """
        if not self.accessToken:
            self.fetchTokens()

        if self.expiresIn is not None and self.expiresIn < datetime.now() + timedelta(
            seconds=TOKEN_EXPIRY_LEEWAY_SECONDS
        ):
            self.refreshTokens()

        response = self._authorizedGet(resource, params)
        if response.status_code == 401:
            self._reauthenticate()
            response = self._authorizedGet(resource, params)

        response.raise_for_status()
        return response.json()

    def _authorizedGet(self, resource: str, params: Mapping[str, Any]) -> requests.Response:
        """Issue a GET request carrying the current bearer token."""
        return self.session.request(
            "GET",
            f"{self.baseUrl}{resource}",
            params=dict(params),
            headers={
                "Authorization": f"Bearer {self.accessToken}",
                "Accept": self.accept,
            },
            timeout=self.timeout,
        )

    def _reauthenticate(self) -> None:
        """Renew tokens after a 401: refresh grant if possible, else password grant."""
        if self.refreshToken is None:
            self.fetchTokens()
            return

        try:
            self.refreshTokens()
        except requests.HTTPError:
            self.fetchTokens()

    def _wrapLinkedResources(
        self,
        data: Any,
        *,
        currentResource: str,
        cache: dict[str, Any],
    ) -> Any:
        """Wrap API links embedded in a response body with lazy resources."""
        if isinstance(data, list):
            wrappedItems: list[Any] = []
            for item in data:
                resource = (
                    self._linkedResource(item.get("@id"))
                    or self._resourceFromCollectionItem(item, currentResource)
                    if isinstance(item, dict)
                    else self._linkedResource(item)
                )
                if resource is not None and resource != currentResource:
                    seed = item if isinstance(item, Mapping) else None
                    wrappedItems.append(self._lazyResource(resource, cache, seed))
                    continue

                wrappedItems.append(
                    self._wrapLinkedResources(
                        item,
                        currentResource=currentResource,
                        cache=cache,
                    )
                )

            return wrappedItems

        if isinstance(data, dict):
            hydraMember = data.get("hydra:member")
            if isinstance(hydraMember, list):
                wrappedMembers = self._wrapLinkedResources(
                    hydraMember,
                    currentResource=currentResource,
                    cache=cache,
                )
                return LazyCollection(
                    self,
                    wrappedMembers,
                    currentResource=currentResource,
                    nextResource=self._nextPageResource(data),
                    totalItems=(
                        data["hydra:totalItems"]
                        if isinstance(data.get("hydra:totalItems"), int)
                        else None
                    ),
                    cache=cache,
                )

            return self._wrapLinkedResourceProperties(
                data,
                currentResource=currentResource,
                cache=cache,
            )

        resource = self._linkedResource(data)
        if resource is None:
            return data

        if resource == currentResource:
            return data

        return self._lazyResource(resource, cache)

    def _wrapLinkedResourceProperties(
        self,
        data: dict[str, Any],
        *,
        currentResource: str,
        cache: dict[str, Any],
    ) -> dict[str, Any]:
        """Wrap resource links in a mapping without replacing its metadata."""
        wrapped: dict[str, Any] = {}
        for key, value in data.items():
            if key in {"@id", "@type"}:
                wrapped[key] = value
                continue

            if key in {"hydra:member", "hydra:view", "hydra:search", "hydra:totalItems"}:
                continue

            resource = self._linkedResource(value)
            if resource is not None:
                if resource == currentResource:
                    wrapped[key] = value
                    continue

                wrapped[key] = self._lazyResource(resource, cache)
                continue

            if isinstance(value, dict):
                valueResource = self._linkedResource(value.get("@id"))
                if valueResource is not None and valueResource != currentResource:
                    wrapped[key] = self._lazyResource(valueResource, cache, value)
                    continue

            wrapped[key] = self._wrapLinkedResources(
                value,
                currentResource=currentResource,
                cache=cache,
            )

        return wrapped

    def _lazyResource(
        self,
        resource: str,
        cache: dict[str, Any],
        seed: Mapping[str, Any] | None = None,
    ) -> Any:
        if resource in cache:
            return cache[resource]

        lazyResource = LazyResource(self, resource, cache, seed)
        cache[resource] = lazyResource
        return lazyResource

    def _nextPageResource(self, data: Mapping[str, Any]) -> str | None:
        view = data.get("hydra:view")
        if not isinstance(view, Mapping):
            return None

        return self._linkedResource(view.get("hydra:next"))

    def _nextPlainJsonPageResource(self, resource: str) -> str | None:
        parsedResource = urlparse(resource)
        query = dict(parse_qsl(parsedResource.query, keep_blank_values=True))
        rawPage = query.get("page")
        if rawPage is None:
            return None

        try:
            query["page"] = str(int(rawPage) + 1)
        except ValueError:
            return None

        nextResource = parsedResource.path
        nextQuery = urlencode(query)
        if nextQuery:  # pragma: no branch
            nextResource = f"{nextResource}?{nextQuery}"

        return nextResource

    def _resourceFromCollectionItem(
        self,
        item: Mapping[str, Any],
        currentResource: str,
    ) -> str | None:
        """Infer an item resource from a collection item carrying only an id."""
        itemId = item.get("id")
        if itemId is None:
            return None

        collectionResource = currentResource.split("?", maxsplit=1)[0].rstrip("/")
        if not collectionResource.startswith("/api/"):
            return None

        if collectionResource.rsplit("/", maxsplit=1)[-1] == str(itemId):
            return None

        return f"{collectionResource}/{itemId}"

    def _linkedResource(self, value: Any) -> str | None:
        """Return a normalized API resource path when ``value`` is a link."""
        if not isinstance(value, str):
            return None

        if value.startswith("http://") or value.startswith("https://"):
            parsedBaseUrl = urlparse(self.baseUrl)
            parsedValue = urlparse(value)
            if (
                parsedValue.scheme != parsedBaseUrl.scheme
                or parsedValue.netloc != parsedBaseUrl.netloc
            ):
                return None

            value = parsedValue.path
            if parsedValue.query:
                value = f"{value}?{parsedValue.query}"

        if not value.startswith(("/", "api/")):
            return None

        resource = self._normalizeResource(value)
        if resource == "/api/token" or not resource.startswith("/api/"):
            return None

        return resource

    def _normalizeResource(self, resource: str) -> str:
        """Normalize a resource path so it can be appended to ``baseUrl``."""
        if resource.startswith(self.baseUrl):
            resource = resource[len(self.baseUrl) :]

        if not resource.startswith("/"):
            resource = "/" + resource

        if not resource.startswith("/api"):
            resource = "/api" + resource

        return resource

    def _resourceWithParams(self, resource: str, params: Mapping[str, Any]) -> str:
        if not params:
            return resource

        query = urlencode(dict(params), doseq=True)
        separator = "&" if "?" in resource else "?"

        return f"{resource}{separator}{query}"

    def fetchTokens(self) -> None:
        """Fetch initial OAuth access and refresh tokens using password grant.

        Updates :attr:`accessToken`, :attr:`refreshToken`, :attr:`expiresIn`.

        Raises:
            requests.HTTPError: If the token endpoint rejects the credentials.
                Token state is left untouched on failure.
        """
        response = self.session.post(
            f"{self.baseUrl}/api/token",
            data={
                "grant_type": "password",
                "username": self.username,
                "password": self.password,
                "client_id": self.clientId,
                "client_secret": self.clientSecret,
            },
            timeout=self.timeout,
        )

        response.raise_for_status()
        data = response.json()

        self.accessToken = data["access_token"]
        self.refreshToken = data["refresh_token"]
        self.expiresIn = datetime.now() + timedelta(seconds=data["expires_in"])

    def refreshTokens(self) -> None:
        """Refresh the OAuth access token using the stored refresh token.

        Updates :attr:`accessToken`, :attr:`refreshToken`, :attr:`expiresIn`.

        Raises:
            requests.HTTPError: If the token endpoint rejects the refresh
                token. Token state is left untouched on failure.

        Note:
            Renamed from ``refreshToken`` to ``refreshTokens`` so it no
            longer collides with the ``refreshToken`` attribute set after
            authentication.
        """
        response = self.session.post(
            f"{self.baseUrl}/api/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refreshToken,
                "client_id": self.clientId,
                "client_secret": self.clientSecret,
            },
            timeout=self.timeout,
        )

        response.raise_for_status()
        data = response.json()

        self.accessToken = data["access_token"]
        self.refreshToken = data["refresh_token"]
        self.expiresIn = datetime.now() + timedelta(seconds=data["expires_in"])
