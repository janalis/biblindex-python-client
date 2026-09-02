# ──────────────────────────────────────────────
# Biblindex Client — Makefile
# ──────────────────────────────────────────────

PYTHON_VERSION := $(shell cat .python-version)

# Detect OS
ifeq ($(OS),Windows_NT)
	DETECTED_OS := Windows
	CP_CMD := powershell -Command Copy-Item
	CHECK_CMD := where
	NULL := nul
else
	DETECTED_OS := $(shell uname -s)
	CP_CMD := cp
	CHECK_CMD := command -v
	NULL := /dev/null
endif

.PHONY: help install-pyenv install-python install-uv install-deps install-env run setup test lint lint-fix bump-patch bump-minor bump-major release

# ──────────────────────────────────────────────
# Help
# ──────────────────────────────────────────────

help: ## Show this help message
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make <target>\n\nTargets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  %-20s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ──────────────────────────────────────────────
# Development
# ──────────────────────────────────────────────

run: ## Run the example script
	@if $(CHECK_CMD) pyenv >$(NULL) 2>&1; then \
		pyenv local $(PYTHON_VERSION); \
	fi
	@uv sync
	@uv run python src/example.py

test: ## Run tests with coverage
	@if $(CHECK_CMD) pyenv >$(NULL) 2>&1; then \
		pyenv local $(PYTHON_VERSION); \
	fi
	@uv sync --group test
	@uv run pytest --cov=biblindex_client --cov-report=term-missing

lint: ## Lint and type-check the codebase
	@if $(CHECK_CMD) pyenv >$(NULL) 2>&1; then \
		pyenv local $(PYTHON_VERSION); \
	fi
	@uv sync --group lint --group typecheck
	@uv run ruff check .
	@uv run ruff format --check .
	@uv run mypy

lint-fix: ## Auto-fix lint issues and format code
	@if $(CHECK_CMD) pyenv >$(NULL) 2>&1; then \
		pyenv local $(PYTHON_VERSION); \
	fi
	@uv sync --group lint
	@uv run ruff check --fix .
	@uv run ruff format .

setup: install-pyenv install-python install-uv install-deps install-env ## Full project setup (all install steps)

install-pyenv: ## Install pyenv (Python version manager)
	@if $(CHECK_CMD) pyenv >$(NULL) 2>&1; then \
		echo "pyenv is already installed"; \
	else \
		echo "Installing pyenv..."; \
		curl -fsSL https://pyenv.run | bash; \
	fi

install-python: ## Install the required Python version via pyenv
	@if [ ! -f .python-version ]; then \
		echo ".python-version file not found"; \
		exit 1; \
	fi
	@if command -v python >/dev/null 2>&1 && python --version 2>&1 | grep -q "$(PYTHON_VERSION)"; then \
		echo "Python $(PYTHON_VERSION) already available"; \
	else \
		echo "Installing Python $(PYTHON_VERSION) via pyenv (if available)..."; \
		pyenv install $(PYTHON_VERSION) || true; \
	fi
	@echo "Setting local Python version..."
	@pyenv local $(PYTHON_VERSION) || echo "pyenv not available"

install-uv: ## Install uv (Python package manager)
	@if $(CHECK_CMD) uv >$(NULL) 2>&1; then \
		echo "uv is already installed"; \
	else \
		echo "Installing uv..."; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
	fi

install-deps: ## Install Python dependencies from pyproject.toml
	@if [ ! -f pyproject.toml ]; then \
		echo "pyproject.toml not found"; \
		exit 1; \
	fi
	@command -v uv >/dev/null 2>&1 || { echo "uv is required but not installed"; exit 1; }
	@echo "Installing Python dependencies from pyproject.toml..."
	@uv sync

install-env: ## Create .env.local from .env.example template
	@if [ ! -f .env.example ]; then \
		echo ".env.example not found, skipping"; \
	elif [ -f .env.local ]; then \
		echo ".env.local already exists"; \
	else \
		echo "Creating .env.local from .env.example"; \
		python -c "from shutil import copyfile; copyfile('.env.example', '.env.local')"; \
	fi

bump-patch: ## Bump version (patch)
	@uv sync --group release
	@uv run bump-my-version bump patch

bump-minor: ## Bump version (minor)
	@uv sync --group release
	@uv run bump-my-version bump minor

bump-major: ## Bump version (major)
	@uv sync --group release
	@uv run bump-my-version bump major

# Usage: make release part=patch|minor|major
release: bump-$(part) ## Cut a new release (pass part=patch|minor|major)
	@echo "Release v$$(uv run bump-my-version show --format json | uv run python -c "import sys,json; d=json.load(sys.stdin); print(d['current_version'])") ready"
	@git push origin HEAD
	@git push origin "v$$(uv run bump-my-version show --format json | uv run python -c "import sys,json; d=json.load(sys.stdin); print(d['current_version'])")"
	@echo "Tag & commit pushed. The GitHub Release workflow will build and publish."
