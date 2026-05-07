# BiblIndex Python client

[![Python](https://img.shields.io/badge/Python-3.12+-blue?logo=python)](https://www.python.org/)
[![uv](https://img.shields.io/badge/uv-package%20manager-111111?logo=python)](https://docs.astral.sh/uv/)
[![Make](https://img.shields.io/badge/Make-automation-orange?logo=gnu)](https://www.gnu.org/software/make/)
![Cross Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20WSL-lightgrey)
[![CI](https://github.com/janalis/biblindex-python-client/actions/workflows/ci.yml/badge.svg)](https://github.com/janalis/biblindex-client/actions/workflows/ci.yml)

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
cp .env .env.local
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

The package is published directly from this Git repository — no PyPI account
needed. Consumers install it by adding the Git URL to their own project.

### With `uv`

```bash
uv add "biblindex-client @ git+https://github.com/janalis/biblindex-client.git"
```

To pin a specific tag, branch or commit:

```bash
uv add "biblindex-client @ git+https://github.com/janalis/biblindex-client.git@v0.1.0"
```

### With `pip`

```bash
pip install "biblindex-client @ git+https://github.com/janalis/biblindex-client.git"
```

### Or in `pyproject.toml`

```toml
[project]
dependencies = [
    "biblindex-client @ git+https://github.com/janalis/biblindex-client.git@v0.1.0",
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

### Lazy fetching

API responses are automatically wrapped in lazy proxies that defer network requests until data is actually read:

- **`LazyResource`** (`MutableMapping`): resource links (e.g. `/api/extracts/42`, `{"@id": "/api/works/1"}`) embedded in responses are wrapped as lazy mappings — the linked resource is fetched only when a field is accessed.
- **`LazyCollection`** (`MutableSequence`): paginated Hydra collections and plain JSON arrays are wrapped as lazy sequences — subsequent pages are fetched on demand when iterating or indexing beyond the current page.

Hydra metadata properties (`hydra:member`, `hydra:view`, `hydra:search`, `hydra:totalItems`) are not exposed through the lazy wrappers — collections are returned directly as `LazyCollection` instances.

Caching ensures the same API resource is never fetched twice within a single response tree.

```python
from biblindex_client import BiblIndexClient, LazyResource

client = BiblIndexClient(...)
collection = client.request("/api/quotations", {"page": 1})

# members is a LazyCollection — pages fetched lazily
item = collection[0]           # no network call yet
print(item["@id"])       # triggers fetch of /api/quotations/1229419
```

#### Using `application/json` (plain JSON)

> **Warning:** Prefer `application/ld+json` (the default) whenever the API supports it. The Hydra JSON-LD format provides metadata (`hydra:totalItems`, `hydra:view`) that enables accurate `len()` and proper next-page resolution via `hydra:next` links. With plain `application/json`, total item count is unavailable and pagination falls back to incrementing `?page=N`, which may yield empty pages at the end.

When the API returns plain JSON arrays instead of Hydra collections, configure the `accept` media type:

```python
from biblindex_client import BiblIndexClient, LazyCollection, LazyResource

client = BiblIndexClient(
    baseUrl="https://www.biblindex.org",
    username="...",
    password="...",
    clientId="...",
    clientSecret="...",
    accept="application/json",
)

collection = client.request("/api/quotations", {"page": 1})

# The array is wrapped in a LazyCollection — pages are fetched lazily
print(type(collection))           # <class 'LazyCollection'>
print(collection.loadedItems)     # items loaded so far (page 1)

# Accessing beyond the current page triggers ?page=N
item = collection[2]              # fetches /api/quotations?page=2
print(item["id"])                 # reads from the fetched item
```

Pagination uses the `?page=N` query parameter automatically — each fetch increments the page number. If the API returns an empty array the collection stops fetching further pages.

## Publishing a new version

```bash
make bump-patch   # or bump-minor / bump-major
```

This bumps the version in `pyproject.toml`, commits, tags (`vX.Y.Z`), and pushes to GitHub. The [Release workflow](.github/workflows/release.yml) then builds the distribution and creates a GitHub Release with auto-generated release notes.

Consumers pin the new tag in their `git+` URL.

If you ever want to publish to a real index (PyPI, private registry):

```bash
uv build         # produces dist/*.whl and dist/*.tar.gz
uv publish       # upload (configure credentials via UV_PUBLISH_TOKEN or ~/.pypirc)
```

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
