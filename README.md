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
make run
```

### Or manually

```bash
uv run python src/example.py
```

## Available commands

| Command       | Description                                  |
|---------------|----------------------------------------------|
| make setup    | Install everything                           |
| make run      | Run the application                          |
| make test     | Run the test suite with coverage report      |
| make lint     | Run ruff check, format check, and mypy       |
| make lint-fix | Auto-fix lint issues and reformat the code   |

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

## Publishing a new version

1. Bump `version` in `pyproject.toml`.
2. Tag the release: `git tag v0.1.1 && git push --tags`.
3. Consumers pin the new tag in their `git+` URL.

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
