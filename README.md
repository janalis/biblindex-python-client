# BiblIndex Python client

## Tech Stack

![Python](https://img.shields.io/badge/Python-3.12+-blue?logo=python)
![uv](https://img.shields.io/badge/uv-package%20manager-111111?logo=python)
![Make](https://img.shields.io/badge/Make-automation-orange?logo=gnu)
![Cross Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20WSL-lightgrey)

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
uv run python main.py
```

## Available commands

| Command    | Description         |
|------------|---------------------|
| make setup | Install everything  |
| make run   | Run the application |

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
