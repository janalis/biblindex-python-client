import requests

from datetime import datetime, timedelta

"""
HTTP client for interacting with the BiblIndex API.

This client handles:
- Authentication via OAuth2 password grant
- Automatic token refresh
- Authenticated GET requests to API resources

Attributes:
    baseUrl (str): Base URL of the API.
    username (str): API username.
    password (str): API password.
    clientId (str): OAuth client ID.
    clientSecret (str): OAuth client secret.
    accessToken (str | None): Current access token.
    refreshToken (str | None): Refresh token used to renew access tokens.
    expiresIn (datetime | None): Expiration time of the current access token.
    session (requests.Session): Reusable HTTP session.
"""
class BiblIndexClient:
    """
    Initialize the API client with credentials and configuration.

    Args:
        baseUrl (str): Base API URL.
        username (str): Username for authentication.
        password (str): Password for authentication.
        clientId (str): OAuth client ID.
        clientSecret (str): OAuth client secret.
    """
    def __init__(self, baseUrl, username, password, clientId, clientSecret):
        self.baseUrl = baseUrl
        self.username = username
        self.password = password
        self.clientId = clientId
        self.clientSecret = clientSecret

        self.accessToken = None
        self.expiresIn = None
        self.refreshToken = None

        self.session = requests.Session()

    """
    Perform an authenticated GET request to the API.

    Automatically:
    - Fetches tokens if not available
    - Refreshes token if expired

    Args:
        resource (str): API resource path (e.g. "books", "users").
        params (dict): Query parameters for the request.

    Returns:
        dict: Parsed JSON response from the API.

    Raises:
        requests.HTTPError: If the HTTP request fails.
    """
    def request(self, resource, params):
        if not self.accessToken:
            self.fetchTokens()

        if self.expiresIn < datetime.now():
            self.refreshToken()

        response = self.session.request(
            "GET",
            f"{self.baseUrl}/{resource}",
            params=params,
            headers={
                "Authorization": f"Bearer {self.accessToken}",
                "Accept": "application/json",
            },
        )

        response.raise_for_status()
        return response.json()

    """
    Fetch initial OAuth access and refresh tokens using password grant.

    Updates:
        accessToken (str)
        refreshToken (str)
        expiresIn (datetime)
    """
    def fetchTokens(self):
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

    """
    Refresh the OAuth access token using the refresh token.

    Updates:
        accessToken (str)
        refreshToken (str)
        expiresIn (datetime)
    """
    def refreshToken(self):
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
