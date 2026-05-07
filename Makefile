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

.PHONY: install-pyenv install-python install-uv install-deps install-env run setup test lint lint-fix

run:
	@if $(CHECK_CMD) pyenv >$(NULL) 2>&1; then \
		pyenv local $(PYTHON_VERSION); \
	fi
	@uv sync
	@uv run python src/example.py

test:
	@if $(CHECK_CMD) pyenv >$(NULL) 2>&1; then \
		pyenv local $(PYTHON_VERSION); \
	fi
	@uv sync --group test
	@uv run pytest --cov=biblindex_client --cov-report=term-missing

lint:
	@if $(CHECK_CMD) pyenv >$(NULL) 2>&1; then \
		pyenv local $(PYTHON_VERSION); \
	fi
	@uv sync --group lint --group typecheck
	@uv run ruff check .
	@uv run ruff format --check .
	@uv run mypy

lint-fix:
	@if $(CHECK_CMD) pyenv >$(NULL) 2>&1; then \
		pyenv local $(PYTHON_VERSION); \
	fi
	@uv sync --group lint
	@uv run ruff check --fix .
	@uv run ruff format .

setup: install-pyenv install-python install-uv install-deps install-env

install-pyenv:
	@if $(CHECK_CMD) pyenv >$(NULL) 2>&1; then \
		echo "pyenv is already installed"; \
	else \
		echo "Installing pyenv..."; \
		curl -fsSL https://pyenv.run | bash; \
	fi

install-python:
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

install-uv:
	@if $(CHECK_CMD) uv >$(NULL) 2>&1; then \
		echo "uv is already installed"; \
	else \
		echo "Installing uv..."; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
	fi

install-deps:
	@if [ ! -f pyproject.toml ]; then \
		echo "pyproject.toml not found"; \
		exit 1; \
	fi
	@command -v uv >/dev/null 2>&1 || { echo "uv is required but not installed"; exit 1; }
	@echo "Installing Python dependencies from pyproject.toml..."
	@uv sync

install-env:
	@if [ ! -f .env ]; then \
		echo ".env not found, skipping"; \
	elif [ -f .env.local ]; then \
		echo ".env.local already exists"; \
	else \
		echo "Creating .env.local from .env"; \
		python -c "from shutil import copyfile; copyfile('.env', '.env.local')"; \
	fi
