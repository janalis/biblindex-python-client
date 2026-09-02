from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import datetime, timedelta
from types import TracebackType
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from biblindex_client.errors import (
    AccessDeniedError,
    AuthenticationError,
    BiblIndexError,
    BiblIndexHTTPError,
    FilterVocabularyUnavailableError,
    PageSizeError,
    UndeclaredParameterError,
    accessDeniedMessage,
    describeErrorBody,
    pageSizeMessage,
    undeclaredParameterMessage,
    vocabularyUnavailableMessage,
)
from biblindex_client.lazy import (
    LazyCollection,
    LazyResource,
    collectionValue,
    envelopeValue,
    hydraEnvelopeKeys,
)
from biblindex_client.schema import (
    ALWAYS_ALLOWED,
    OPENAPI_ACCEPT,
    OPENAPI_RESOURCE,
    FilterVocabulary,
)

JSON_LD_MIME_TYPE = "application/ld+json"

DEFAULT_TIMEOUT: float = 30.0

# Refresh tokens slightly before their actual expiry so a token that would
# expire mid-request is renewed up front.
TOKEN_EXPIRY_LEEWAY_SECONDS: int = 30

# BiblIndex serves at most this many items per page whatever is asked for.
MAX_ITEMS_PER_PAGE: int = 100

# Pages a single implicit iteration or index may fetch before it must say so.
DEFAULT_MAX_AUTO_PAGES: int = 50


class BiblIndexClient:
    """HTTP client for interacting with the BiblIndex API.

    Handles:
    - Authentication via OAuth2 password grant
    - Automatic token refresh, including re-authentication on a 401 response
    - Authenticated GET requests to API resources
    - Refusal of query parameters the endpoint would silently ignore

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
        validateParams: Refuse query parameters an endpoint does not declare.
        backfillIds: Derive a missing ``id`` from the resource IRI.
        maxAutoPages: Pages a single implicit paging operation may fetch.
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
        validateParams: bool = True,
        backfillIds: bool = True,
        maxAutoPages: int | None = DEFAULT_MAX_AUTO_PAGES,
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
        self.validateParams: bool = validateParams
        self.backfillIds: bool = backfillIds
        self.maxAutoPages: int | None = maxAutoPages

        self.accessToken: str | None = None
        self.refreshToken: str | None = None
        self.expiresIn: datetime | None = None

        self.session: requests.Session = requests.Session()

        self._vocabulary = FilterVocabulary()

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

    def request(
        self,
        resource: str,
        params: Mapping[str, Any] | None = None,
        *,
        validateParams: bool | None = None,
    ) -> Any:
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
            validateParams: Override the client-wide parameter validation for
                this call only.

        Returns:
            Parsed JSON response from the API.

        Raises:
            UndeclaredParameterError: If a parameter is not declared by the
                endpoint, and would therefore be ignored without notice.
            AccessDeniedError: If the account is not authorized (403).
            BiblIndexHTTPError: If the request fails for another reason.
        """
        resource = self._normalizeResource(resource)
        sent = dict(params or {})

        self._validateRequestParams(resource, sent, validateParams)

        currentResource = self._resourceWithParams(resource, sent)
        data = self._requestJson(resource, sent)
        self._recordVocabulary(resource, data)

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
                maxAutoPages=self.maxAutoPages,
            )

        return wrapped

    def fetchAll(
        self,
        resource: str,
        params: Mapping[str, Any] | None = None,
        *,
        itemsPerPage: int = MAX_ITEMS_PER_PAGE,
        maxItems: int | None = None,
    ) -> list[Any]:
        """Fetch every item of a collection, paging explicitly.

        The server caps a page at :data:`MAX_ITEMS_PER_PAGE` however many are
        asked for, so a single large request is never enough.
        """
        collection = self._collectionFor(resource, params, itemsPerPage)

        return collection.fetchAll(maxItems=maxItems)

    def iterCollection(
        self,
        resource: str,
        params: Mapping[str, Any] | None = None,
        *,
        itemsPerPage: int = MAX_ITEMS_PER_PAGE,
        maxItems: int | None = None,
    ) -> Iterator[Any]:
        """Iterate every item of a collection, one page at a time."""
        collection = self._collectionFor(resource, params, itemsPerPage)

        return collection.iterAll(maxItems=maxItems)

    def _collectionFor(
        self,
        resource: str,
        params: Mapping[str, Any] | None,
        itemsPerPage: int,
    ) -> LazyCollection:
        sent = dict(params or {})
        sent.setdefault("itemsPerPage", itemsPerPage)
        sent.setdefault("page", 1)

        result = self.request(resource, sent)
        if not isinstance(result, LazyCollection):
            raise BiblIndexError(
                f"{resource} did not return a collection; "
                f"got {type(result).__name__}. Use request() for a single resource."
            )

        return result

    def filtersFor(self, resource: str) -> frozenset[str]:
        """Return the query filters an endpoint declares.

        Note what this answers for the corpus: ``/api/quotations`` declares only
        ``work`` (plus the ``page``/``itemsPerPage`` pagination controls). There
        is no filter by biblical segment and none by author, so "citations of a
        given passage" cannot be expressed as a server-side query on that
        endpoint. ``/api/verses`` does declare ``bible``, ``book``, ``chapter``
        and ``number``.

        Raises:
            FilterVocabularyUnavailableError: If the declared filters cannot be
                determined. Never reports "no filters" for an endpoint it simply
                does not know about.
        """
        normalized = self._collectionResourceOf(self._normalizeResource(resource))
        self._ensureVocabulary()

        if not self._vocabulary.knows(normalized):
            raise FilterVocabularyUnavailableError(
                f"The declared filters for {normalized} are unknown: "
                f"{OPENAPI_RESOURCE} could not be read and no response from this "
                f"endpoint has advertised a search template yet."
            )

        return self._vocabulary.declaredFor(normalized)

    def _validateRequestParams(
        self,
        resource: str,
        params: Mapping[str, Any],
        override: bool | None,
    ) -> None:
        """Refuse parameters the endpoint would accept and then ignore."""
        enabled = self.validateParams if override is None else override
        if not enabled:
            return

        self._checkPageSize(params)

        filterable = {name for name in params if name not in ALWAYS_ALLOWED}
        if not filterable:
            # Nothing to check, so nothing to look up: the common browse path
            # never pays for schema discovery.
            return

        normalized = self._collectionResourceOf(resource)
        self._ensureVocabulary()

        if not self._vocabulary.knows(normalized):
            raise UndeclaredParameterError(vocabularyUnavailableMessage(normalized, filterable))

        undeclared = self._vocabulary.undeclared(normalized, filterable)
        if undeclared:
            raise UndeclaredParameterError(
                undeclaredParameterMessage(
                    normalized,
                    undeclared,
                    self._vocabulary.declaredFor(normalized),
                )
            )

    def _checkPageSize(self, params: Mapping[str, Any]) -> None:
        requested = params.get("itemsPerPage")
        if requested is None:
            return

        try:
            size = int(requested)
        except (TypeError, ValueError):
            return

        if size > MAX_ITEMS_PER_PAGE:
            raise PageSizeError(pageSizeMessage(size, MAX_ITEMS_PER_PAGE))

    def _ensureVocabulary(self) -> None:
        """Load the OpenAPI document once per client, tolerating failure."""
        if self._vocabulary.openApiAttempted:
            return

        self._vocabulary.markOpenApiAttempted()

        try:
            response = self.session.get(
                f"{self.baseUrl}{OPENAPI_RESOURCE}",
                headers={"Accept": OPENAPI_ACCEPT},
                timeout=self.timeout,
            )
            if response.status_code != 200:
                return

            self._vocabulary.recordOpenApi(response.json())
        except (requests.RequestException, ValueError):
            # Discovery is best-effort; an unreachable document leaves the
            # vocabulary unknown, which _validateRequestParams reports plainly.
            return

    def _recordVocabulary(self, resource: str, data: Any) -> None:
        """Absorb the ``search`` block a collection response carries for free."""
        if not isinstance(data, Mapping):
            return

        search = collectionValue(data, "search")
        if search is not None:
            self._vocabulary.recordSearch(self._collectionResourceOf(resource), search)

    def _collectionResourceOf(self, resource: str) -> str:
        """Strip the query string from a resource path."""
        return resource.split("?", maxsplit=1)[0]

    def _requestJson(self, resource: str, params: Mapping[str, Any]) -> Any:
        """Perform an authenticated GET request and return the raw JSON body.

        A 401 response triggers a token renewal and a single replay of the
        request; a second 401 is raised as :class:`AuthenticationError`.
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

        self._raiseForStatus(response, resource=resource)

        return self._decodeJson(response, resource=resource)

    def _raiseForStatus(self, response: requests.Response, *, resource: str) -> None:
        """Turn an error response into an exception that explains itself."""
        if response.status_code < 400:
            return

        if response.status_code == 403:
            raise AccessDeniedError(
                accessDeniedMessage(resource, response),
                response=response,
                request=response.request,
            )

        if response.status_code == 401:
            detail = describeErrorBody(response)
            message = f"401 Unauthorized on {resource}."
            if detail:
                message = f"{message} Server said: {detail}"
            raise AuthenticationError(
                f"{message} The credentials were refused, or the token was "
                f"rejected twice in a row.",
                response=response,
                request=response.request,
            )

        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            detail = describeErrorBody(response)
            message = str(error)
            if detail:
                message = f"{message} Server said: {detail}"
            raise BiblIndexHTTPError(
                message,
                response=response,
                request=response.request,
            ) from error

    def _decodeJson(self, response: requests.Response, *, resource: str) -> Any:
        """Parse a response body, reporting non-JSON payloads clearly."""
        try:
            return response.json()
        except ValueError as error:
            contentType = response.headers.get("Content-Type", "unknown")
            raise BiblIndexError(
                f"{resource} returned {response.status_code} with a non-JSON body "
                f"(Content-Type: {contentType}). First bytes: {response.text[:200]!r}"
            ) from error

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
            hydraMember = collectionValue(data, "member")
            if isinstance(hydraMember, list):
                wrappedMembers = self._wrapLinkedResources(
                    hydraMember,
                    currentResource=currentResource,
                    cache=cache,
                )
                totalItems = collectionValue(data, "totalItems")
                search = collectionValue(data, "search")

                return LazyCollection(
                    self,
                    wrappedMembers,
                    currentResource=currentResource,
                    nextResource=self._nextPageResource(data),
                    totalItems=totalItems if isinstance(totalItems, int) else None,
                    cache=cache,
                    maxAutoPages=self.maxAutoPages,
                    search=search if isinstance(search, Mapping) else None,
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
        hidden = hydraEnvelopeKeys(data)
        wrapped: dict[str, Any] = {}

        for key, value in data.items():
            if key in {"@id", "@type"}:
                wrapped[key] = value
                continue

            if key in hidden:
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

        return self._withBackfilledId(wrapped)

    def _withBackfilledId(
        self, data: dict[str, Any], resource: str | None = None
    ) -> dict[str, Any]:
        """Fill a missing ``id`` from the resource IRI.

        In JSON-LD the API omits ``id`` on authors, work_editions and editions
        while serving it in plain JSON. A join keyed on the missing field
        matches nothing and raises nothing, so the value is restored from the
        ``@id`` IRI, which carries the same identifier.
        """
        if not self.backfillIds or data.get("id") is not None:
            return data

        iri = data.get("@id")
        source = iri if isinstance(iri, str) else resource
        if source is None:
            return data

        identifier = self._identifierFromResource(source)
        if identifier is None:
            return data

        data["id"] = identifier

        return data

    def _identifierFromResource(self, resource: str) -> int | str | None:
        """Extract the identifier from an item IRI, or None for a collection."""
        path = self._collectionResourceOf(resource).rstrip("/")
        if not path.startswith("/api/"):
            return None

        segments = [segment for segment in path.split("/") if segment]
        if len(segments) < 3:
            return None

        tail = segments[-1]

        return int(tail) if tail.isdigit() else tail

    def _lazyResource(
        self,
        resource: str,
        cache: dict[str, Any],
        seed: Mapping[str, Any] | None = None,
    ) -> Any:
        if resource in cache:
            return cache[resource]

        if seed is not None:
            seed = self._withBackfilledId(dict(seed), resource)

        lazyResource = LazyResource(self, resource, cache, seed)
        cache[resource] = lazyResource

        return lazyResource

    def _nextPageResource(self, data: Mapping[str, Any]) -> str | None:
        view = collectionValue(data, "view")
        if not isinstance(view, Mapping):
            return None

        return self._linkedResource(envelopeValue(view, "next"))

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

        # ``query`` always holds at least the page just incremented, so the
        # encoded query string is never empty here.
        return f"{parsedResource.path}?{urlencode(query)}"

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
            AuthenticationError: If the token endpoint rejects the credentials.
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

        self._storeTokens(response, grant="password")

    def refreshTokens(self) -> None:
        """Refresh the OAuth access token using the stored refresh token.

        Updates :attr:`accessToken`, :attr:`refreshToken`, :attr:`expiresIn`.

        Raises:
            AuthenticationError: If the token endpoint rejects the refresh
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

        self._storeTokens(response, grant="refresh_token")

    def _storeTokens(self, response: requests.Response, *, grant: str) -> None:
        """Validate a token response and store the tokens it carries."""
        if response.status_code >= 400:
            detail = describeErrorBody(response)
            message = f"The token endpoint rejected the {grant} grant ({response.status_code})."
            if detail:
                message = f"{message} Server said: {detail}"

            raise AuthenticationError(
                message,
                response=response,
                request=response.request,
            )

        data = self._decodeJson(response, resource="/api/token")

        self.accessToken = data["access_token"]
        self.refreshToken = data["refresh_token"]
        self.expiresIn = datetime.now() + timedelta(seconds=data["expires_in"])
