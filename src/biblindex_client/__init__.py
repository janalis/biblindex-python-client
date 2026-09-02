"""BiblIndex API client package.

Public entrypoint:

    from biblindex_client import BiblIndexClient
"""

from biblindex_client.biblindex import (
    DEFAULT_MAX_AUTO_PAGES,
    MAX_ITEMS_PER_PAGE,
    BiblIndexClient,
)
from biblindex_client.errors import (
    AccessDeniedError,
    AuthenticationError,
    BiblIndexError,
    BiblIndexHTTPError,
    FilterVocabularyUnavailableError,
    PageSizeError,
    PaginationLimitError,
    UndeclaredParameterError,
)
from biblindex_client.lazy import LazyCollection, LazyResource

__all__ = [
    "DEFAULT_MAX_AUTO_PAGES",
    "MAX_ITEMS_PER_PAGE",
    "AccessDeniedError",
    "AuthenticationError",
    "BiblIndexClient",
    "BiblIndexError",
    "BiblIndexHTTPError",
    "FilterVocabularyUnavailableError",
    "LazyCollection",
    "LazyResource",
    "PageSizeError",
    "PaginationLimitError",
    "UndeclaredParameterError",
]
