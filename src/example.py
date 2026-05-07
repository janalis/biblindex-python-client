import os

from dotenv_flow import dotenv_flow

from biblindex_client import BiblIndexClient, LazyResource

dotenv_flow("local")

if __name__ == "__main__":
    client = BiblIndexClient(
        os.getenv("BIBLINDEX_API_URL"),
        os.getenv("BIBLINDEX_API_USER"),
        os.getenv("BIBLINDEX_API_PASSWORD"),
        os.getenv("BIBLINDEX_API_KEY"),
        os.getenv("BIBLINDEX_API_SECRET"),
    )
    collection = client.request(
        "/api/quotations",
        {
            "page": 1,
        },
    )

    print(
        f"Fetched quotation collection with {collection.loadedItems} loaded "
        f"member link(s) out of {len(collection)} total."
    )

    if not collection:
        raise SystemExit

    item = collection[0]
    print(f"First member is lazy: {isinstance(item, LazyResource)}")

    print("Reading a field on the quotation now triggers the item fetch.")
    quotationId = item.get("@id", item.get("id", "unknown"))
    print(f"First quotation id: {quotationId}")

    for linkedProperty in ("extract", "work", "works"):
        if linkedProperty not in item:
            continue

        linkedValue = item[linkedProperty]
        print(f"{linkedProperty} is lazy: {isinstance(linkedValue, LazyResource)}")

        if isinstance(linkedValue, list) and linkedValue:
            firstLinkedValue = linkedValue[0]
            print(
                f"First {linkedProperty} item is lazy: {isinstance(firstLinkedValue, LazyResource)}"
            )
            print(f"Reading a field on {linkedProperty}[0] now triggers its fetch.")
            firstLinkedValueId = firstLinkedValue.get(
                "@id",
                firstLinkedValue.get("id"),
            )
            print(f"First {linkedProperty} item id: {firstLinkedValueId}")
            break

        if isinstance(linkedValue, LazyResource):
            print(f"Reading a field on {linkedProperty} now triggers its fetch.")
            linkedValueId = linkedValue.get("@id", linkedValue.get("id"))
            print(f"{linkedProperty} id: {linkedValueId}")
            break
