from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

import requests


class BiblIndexClient:
    """HTTP client for interacting with the BiblIndex API.

    Handles:
    - Authentication via OAuth2 password grant
    - Automatic token refresh
    - Authenticated GET requests to API resources

    Attributes:
        baseUrl: Base URL of the API.
        username: API username.
        password: API password.
        clientId: OAuth client ID.
        clientSecret: OAuth client secret.
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
    ) -> None:
        """Initialize the API client with credentials and configuration."""
        self.baseUrl: str = baseUrl
        self.username: str = username
        self.password: str = password
        self.clientId: str = clientId
        self.clientSecret: str = clientSecret

        self.accessToken: str | None = None
        self.refreshToken: str | None = None
        self.expiresIn: datetime | None = None

        self.session: requests.Session = requests.Session()

    def request(self, resource: str, params: Mapping[str, Any]) -> Any:
        """Perform an authenticated GET request to the API.

        Automatically fetches tokens if missing, and refreshes them if
        expired before issuing the call.

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
        if not self.accessToken:
            self.fetchTokens()

        if self.expiresIn is not None and self.expiresIn < datetime.now():
            self.refreshTokens()

        if not resource.startswith("/"):
            resource = "/" + resource

        if not resource.startswith("/api"):
            resource = "/api" + resource

        response = self.session.request(
            "GET",
            f"{self.baseUrl}{resource}",
            params=dict(params),
            headers={
                "Authorization": f"Bearer {self.accessToken}",
                "Accept": "application/json",
            },
        )

        response.raise_for_status()
        return response.json()

    def fetchTokens(self) -> None:
        """Fetch initial OAuth access and refresh tokens using password grant.

        Updates :attr:`accessToken`, :attr:`refreshToken`, :attr:`expiresIn`.
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
        )

        data = response.json()

        self.accessToken = data["access_token"]
        self.refreshToken = data["refresh_token"]
        self.expiresIn = datetime.now() + timedelta(seconds=data["expires_in"])

    def refreshTokens(self) -> None:
        """Refresh the OAuth access token using the stored refresh token.

        Updates :attr:`accessToken`, :attr:`refreshToken`, :attr:`expiresIn`.

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
        )

        data = response.json()

        self.accessToken = data["access_token"]
        self.refreshToken = data["refresh_token"]
        self.expiresIn = datetime.now() + timedelta(seconds=data["expires_in"])
