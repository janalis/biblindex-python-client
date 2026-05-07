import os
from collections.abc import Mapping

from dotenv_flow import dotenv_flow

from biblindex_client import BiblIndexClient, LazyCollection, LazyResource

dotenv_flow("local")

if __name__ == "__main__":
    client = BiblIndexClient(
        os.getenv("BIBLINDEX_API_URL"),
        os.getenv("BIBLINDEX_API_USER"),
        os.getenv("BIBLINDEX_API_PASSWORD"),
        os.getenv("BIBLINDEX_API_KEY"),
        os.getenv("BIBLINDEX_API_SECRET"),
    )
    quotations = client.request(
        "/api/quotations",
        {
            "page": 1,
        },
    )

    members = quotations.get("hydra:member", []) if isinstance(quotations, Mapping) else quotations
    if isinstance(members, LazyCollection):
        print(
            f"Fetched quotation collection with {members.loadedItems} loaded "
            f"member link(s) out of {len(members)} total."
        )
    else:
        print(f"Fetched quotation collection with {len(members)} member link(s).")

    if not members:
        raise SystemExit

    quotation = members[0]
    print(f"First member is lazy: {isinstance(quotation, LazyResource)}")

    if isinstance(quotation, Mapping):
        print("Reading a field on the quotation now triggers the item fetch.")
        quotationId = quotation.get("@id", quotation.get("id", "unknown"))
        print(f"First quotation id: {quotationId}")

        for linkedProperty in ("extract", "work", "works"):
            if linkedProperty not in quotation:
                continue

            linkedValue = quotation[linkedProperty]
            print(f"{linkedProperty} is lazy: {isinstance(linkedValue, LazyResource)}")

            if isinstance(linkedValue, list) and linkedValue:
                firstLinkedValue = linkedValue[0]
                print(
                    f"First {linkedProperty} item is lazy: "
                    f"{isinstance(firstLinkedValue, LazyResource)}"
                )
                if isinstance(firstLinkedValue, Mapping):
                    print(f"Reading a field on {linkedProperty}[0] now triggers its fetch.")
                    firstLinkedValueId = firstLinkedValue.get(
                        "@id",
                        firstLinkedValue.get("id"),
                    )
                    print(f"First {linkedProperty} item id: {firstLinkedValueId}")
                break

            if isinstance(linkedValue, Mapping):
                print(f"Reading a field on {linkedProperty} now triggers its fetch.")
                linkedValueId = linkedValue.get("@id", linkedValue.get("id"))
                print(f"{linkedProperty} id: {linkedValueId}")
                break
