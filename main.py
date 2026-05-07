import os

from dotenv_flow import dotenv_flow
from service.biblindex import BiblIndexClient

dotenv_flow("local")

if __name__ == '__main__':
    client = BiblIndexClient(
        os.getenv("BIBLINDEX_API_URL"),
        os.getenv("BIBLINDEX_API_USER"),
        os.getenv("BIBLINDEX_API_PASSWORD"),
        os.getenv("BIBLINDEX_API_KEY"),
        os.getenv("BIBLINDEX_API_SECRET")
    )
    print(client.request("/api/quotations", {
        "page": 1,
    }))
