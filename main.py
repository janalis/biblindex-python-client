import os

from dotenv import load_dotenv
from service.biblindex import BiblIndexClient

# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    load_dotenv()
    client = BiblIndexClient(
        os.environ["BIBLINDEX_API_URL"],
        os.environ["BIBLINDEX_API_USER"],
        os.environ["BIBLINDEX_API_PASSWORD"],
        os.environ["BIBLINDEX_API_KEY"],
        os.environ["BIBLINDEX_API_SECRET"]
    )
    print(client.request("/api/quotations", {
        "page": 1,
    }))
