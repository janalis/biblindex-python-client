"""BiblIndex API client package.

Public entrypoint:

    from biblindex_client import BiblIndexClient
"""

from biblindex_client.biblindex import BiblIndexClient
from biblindex_client.lazy import LazyCollection, LazyResource

__all__ = ["BiblIndexClient", "LazyCollection", "LazyResource"]
