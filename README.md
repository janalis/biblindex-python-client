# BiblIndex Python client

[![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python)](https://www.python.org/)
[![uv](https://img.shields.io/badge/uv-package%20manager-111111?logo=python)](https://docs.astral.sh/uv/)
[![Make](https://img.shields.io/badge/Make-automation-orange?logo=gnu)](https://www.gnu.org/software/make/)
![Cross Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20WSL-lightgrey)
[![CI](https://github.com/janalis/biblindex-python-client/actions/workflows/ci.yml/badge.svg)](https://github.com/janalis/biblindex-python-client/actions/workflows/ci.yml)

## Maintainers

| Name              | Email              |
| ----------------- | ------------------ |
| Pierre Hennequart | pierre@janalis.com |

## Documentation

https://www.biblindex.org/api

## Quick Start

```bash
make setup
make run
```

## Installation

### Clone the repository

```bash
git clone <repo-url>
cd <repo-name>
```

### Install Python environment

This project uses a version-managed Python setup.

```bash
pyenv install $(cat .python-version)
pyenv local $(cat .python-version)
```

### Install dependencies

This project uses a modern Python packaging tool:

```bash
uv sync
```

### Environment variables

```bash
cp .env.example .env.local
```

Edit .env.local with your configuration.

## Run the project

### Using Make (recommended)

```bash
make help      # List all available commands
make run
```

### Or manually

```bash
uv run python src/example.py
```

## Available commands

Run `make help` to see all available commands with descriptions:

```bash
make help
```

## Platform Support

| OS      | Support | Notes               |
|---------|---------|---------------------|
| macOS   | ✅       | Native supported    |
| Linux   | ✅       | Native supported    |
| Windows | ⚠️      | Use WSL or Git Bash | 

## Notes

* Uses pyenv for Python version management
* Uses uv for fast dependency resolution
* Makefile orchestrates setup + run steps

## Recommended Setup

For the smoothest experience:

* macOS / Linux → native terminal
* Windows → WSL2 (recommended)

## Use as a library in another project

Released versions are published to [PyPI](https://pypi.org/project/biblindex-client/).

### With `uv`

```bash
uv add biblindex-client
```

### With `pip`

```bash
pip install biblindex-client
```

### Installing an unreleased commit

To use a version that hasn't been released to PyPI yet, install directly from the
Git repository (optionally pinned to a tag, branch or commit):

```bash
uv add "biblindex-client @ git+https://github.com/janalis/biblindex-python-client.git@v0.1.0"
```

### Or in `pyproject.toml`

```toml
[project]
dependencies = [
    "biblindex-client @ git+https://github.com/janalis/biblindex-python-client.git@v0.1.0",
]
```

### Usage

```python
from biblindex_client import BiblIndexClient

client = BiblIndexClient(
    baseUrl="https://www.biblindex.org",
    username="...",
    password="...",
    clientId="...",
    clientSecret="...",
)

quotations = client.request("/api/quotations", {"page": 1})
```

### Reliability

Every HTTP call uses a 30-second timeout by default; pass `timeout=` to change it (a float, a `(connect, read)` tuple, or `None` to disable). Retries are off by default — pass `retries=N` to enable transport-level retries with backoff for GET requests on transient errors (429 and 5xx responses, connection failures). Token requests are never blindly retried; instead, a 401 API response triggers an automatic token renewal (refresh grant, falling back to the password grant) and a single replay of the request.

The client can be used as a context manager to release the underlying HTTP session:

```python
with BiblIndexClient(
    baseUrl="https://www.biblindex.org",
    username="...",
    password="...",
    clientId="...",
    clientSecret="...",
    timeout=10.0,
    retries=3,
) as client:
    quotations = client.request("/api/quotations", {"page": 1})
```

### Lazy fetching

API responses are automatically wrapped in lazy proxies that defer network requests until data is actually read:

- **`LazyResource`** (`Mapping`, read-only): resource links (e.g. `/api/extracts/42`, `{"@id": "/api/works/1"}`) embedded in responses are wrapped as lazy mappings — the linked resource is fetched only when a field is accessed.
- **`LazyCollection`** (`Sequence`, read-only): paginated Hydra collections and plain JSON arrays are wrapped as lazy sequences — subsequent pages are fetched on demand when iterating or indexing beyond the current page.

Hydra envelope properties are not exposed through the lazy wrappers. Both
spellings are understood: API Platform 4 serves them bare (`member`, `view`,
`search`, `totalItems`), API Platform 3 prefixes them (`hydra:member`, ...).
Bare names are only treated as envelope metadata inside a real collection
envelope, so a resource with a genuine field called `member` keeps it.

Caching ensures the same API resource is never fetched twice within a single
response tree.

```python
from biblindex_client import BiblIndexClient, LazyResource

client = BiblIndexClient(...)
collection = client.request("/api/quotations", {"page": 1})

# members is a LazyCollection — pages fetched lazily
item = collection[0]           # no network call yet
print(item["@id"])       # triggers fetch of /api/quotations/1229419
```

#### Using `application/json` (plain JSON)

The API also serves plain JSON arrays, selected with `accept="application/json"`:

```python
client = BiblIndexClient(..., accept="application/json")
collection = client.request("/api/quotations", {"page": 1})
```

Prefer the default `application/ld+json`: the JSON-LD envelope carries
`totalItems` (so `len()` is the real total) and an explicit `next` link. With
plain JSON there is no total, and pagination falls back to incrementing
`?page=N` until a page comes back empty. Note the two media types differ in
what they carry per item — plain JSON has `id` but no `@id`, JSON-LD the
reverse on some resources, which is why `backfillIds` exists.

#### Pagination

The server serves at most **100 items per page** whatever `itemsPerPage` asks
for, so a single large request is never enough. Asking for more raises
`PageSizeError` rather than silently returning a short page.

Implicit paging is capped by `maxAutoPages` (default 50). Without a cap a single
`list(collection)` on `/api/quotations` would issue several thousand requests.
Walk a whole collection explicitly instead:

```python
from biblindex_client import PaginationLimitError

books = client.fetchAll("/api/books")             # every page, explicitly
for verse in client.iterCollection("/api/verses"):  # streamed, page by page
    ...

collection = client.request("/api/books", {"page": 1})
collection.fetchAll(maxItems=500)
collection.iterPages()
collection.totalItems, collection.loadedItems, collection.isComplete
```

`len(collection)` reports the server's `totalItems` — the answer to "how many
match" — which may exceed `loadedItems`. That gap is deliberate; `isComplete`
tells you whether everything has been loaded.

#### Filter validation

API Platform answers **200 and silently ignores** query parameters an endpoint
does not declare, so an unfiltered result is indistinguishable from a filtered
one. The client refuses them instead, before the request goes out:

```python
from biblindex_client import UndeclaredParameterError

client.filtersFor("/api/quotations")   # frozenset({'work'})
client.filtersFor("/api/verses")       # bible, book, chapter, number (+ [] forms)

client.request("/api/quotations", {"author": 42})
# UndeclaredParameterError: /api/quotations does not declare 'author'. API
# Platform ignores undeclared query parameters and still answers 200, so the
# result would look filtered but would not be. Declared filters: work.
```

The vocabulary comes from `/api/docs.jsonopenapi`, fetched once per client and
only when a call actually carries a filter — the plain `{"page": N}` browse path
costs nothing extra. The `search` block of each collection response reinforces
it for free. Pass `validateParams=False` (per client or per call) to opt out.

`filtersFor()` raises `FilterVocabularyUnavailableError` rather than reporting
"no filters" for an endpoint it could not read — an empty answer would be
indistinguishable from a fact about the API.

#### Errors

| exception | when |
|---|---|
| `AccessDeniedError` | 403 — names `ROLE_API_CLIENT` when the corpus is the target |
| `AuthenticationError` | 401, or the token endpoint rejecting the grant |
| `BiblIndexHTTPError` | any other failing status |
| `UndeclaredParameterError` | a filter the endpoint would ignore |
| `PageSizeError` | `itemsPerPage` above the server's cap |
| `PaginationLimitError` | implicit paging past `maxAutoPages` |
| `FilterVocabularyUnavailableError` | declared filters could not be determined |

All of them derive from `BiblIndexError`, and the HTTP ones also derive from
`requests.HTTPError`, so existing `except requests.HTTPError` handlers keep
working. Error bodies are read, so the server's own explanation is preserved.

#### Read-only

`LazyResource` and `LazyCollection` are `Mapping` and `Sequence`. The API is not
writable through this client, so an assignment that could never reach the server
is refused rather than kept in memory looking like a saved change. Use
`dict(resource)` or `list(collection)` for a mutable copy.

#### Known API limitations

Verified against the live API on 02/09/2026:

| behaviour | consequence |
|---|---|
| `itemsPerPage` capped at 100 | always page; `fetchAll()` does it for you |
| `?locale=` accepted and ignored | `name`/`description` are English regardless; refused by the client |
| `id` absent in ld+json on `authors`, `work_editions`, `editions` | backfilled from the `@id` IRI (`backfillIds=False` to opt out) |
| `/api/quotations` declares only `work` | no filter by biblical segment or author |
| corpus endpoints need `ROLE_API_CLIENT` | 403 until the account is granted it |

## Publishing a new version

```bash
make bump-patch   # or bump-minor / bump-major
```

This bumps the version in `pyproject.toml`, commits, tags (`vX.Y.Z`), and pushes to GitHub. The [Release workflow](.github/workflows/release.yml) then builds the distribution, publishes it to **TestPyPI** and then **PyPI**, and creates a GitHub Release with auto-generated release notes.

Publishing uses [PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/) (OIDC) via `uv publish` — no API tokens or credentials are stored or needed locally. The TestPyPI upload acts as a smoke test that gates the real PyPI release.

## Contributing

This project is open to contributions.

We welcome pull requests following the standard GitHub flow:

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Open a pull request

Please ensure your changes are well tested and follow the existing code style.

## API Modifications

If you need changes, extensions, or adjustments to the API, please contact the maintainers.
