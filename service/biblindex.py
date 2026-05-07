import requests

from datetime import datetime, timedelta
class BiblIndexClient:
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
    def request(self, resource, params):
        if not self.accessToken:
            self.fetchTokens()
        if self.expiresIn < datetime.now():
            self.refreshToken()
        response = self.session.request("GET", f"{self.baseUrl}/{resource}", params=params, headers={
            "Authorization": f"Bearer {self.accessToken}",
            "Accept": "application/json"
        })
        return response.json()
    def fetchTokens(self):
        response = self.session.post(f"{self.baseUrl}/api/token", data={
            "grant_type": "password",
            "username": self.username,
            "password": self.password,
            "client_id": self.clientId,
            "client_secret": self.clientSecret
        })
        data = response.json()
        self.accessToken = data["access_token"]
        self.refreshToken = data["refresh_token"]
        self.expiresIn = datetime.now() + timedelta(seconds=data["expires_in"])
    def refreshToken(self):
        response = self.session.post(f"{self.baseUrl}/api/token", data={
            "grant_type": "refresh_token",
            "refresh_token": self.refreshToken,
            "client_id": self.clientId,
            "client_secret": self.clientSecret
        })
        data = response.json()
        self.accessToken = data["access_token"]
        self.refreshToken = data["refresh_token"]
        self.expiresIn = datetime.now() + timedelta(seconds=data["expires_in"])