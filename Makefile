.PHONY: check lint typecheck test coverage all

# scripts/bootstrap installs the pinned analyzers into .venv/bin without
# putting them on PATH; prefer them so a bootstrapped checkout always runs
# exactly what CI runs instead of silently skipping gates CI enforces.
export PATH := $(CURDIR)/.venv/bin:$(PATH)

# uv runs the suite when it is available so contributors share one toolchain;
# the plain interpreter still works, because the core has no dependencies.
PYTHON := $(shell command -v uv >/dev/null 2>&1 && echo "uv run --no-project python3" || echo python3)

all: check test

SHELL_SCRIPTS := scripts/bootstrap scripts/install-tools.sh scripts/install-unity-editor.sh \
	scripts/compile-editor-scripts.sh scripts/playtest-acceptance.sh

check: lint typecheck
	$(PYTHON) -m compileall -q src tests scripts/github_asset_url.py
	bash -n $(SHELL_SCRIPTS)
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck -S style $(SHELL_SCRIPTS); \
	elif [ -n "$${CI:-}" ]; then \
		echo "ERROR: CI requires shellcheck; install it with scripts/install-tools.sh" >&2; \
		exit 1; \
	else \
		echo "note: shellcheck not installed; skipped shell linting"; \
	fi
	scripts/compile-editor-scripts.sh --quiet-missing

# Python analysis, mirroring the shellcheck contract: run when the tool is on
# PATH, hard-fail in CI, and say so plainly when skipped on a dev host.
lint:
	@if command -v ruff >/dev/null 2>&1; then \
		ruff check .; \
		ruff format --check .; \
	elif [ -n "$${CI:-}" ]; then \
		echo "ERROR: CI requires ruff; e.g. uv tool install ruff" >&2; \
		exit 1; \
	else \
		echo "note: ruff not installed; skipped python linting"; \
	fi

# Strict whole-tree typing. Same contract as lint: run when the tool is on
# PATH, hard-fail in CI, and say so plainly when skipped on a dev host.
# setuptools is checked alongside mypy because setup.py subclasses build_py.
typecheck:
	@if command -v mypy >/dev/null 2>&1; then \
		mypy .; \
	elif [ -n "$${CI:-}" ]; then \
		echo "ERROR: CI requires mypy; e.g. uv tool install mypy" >&2; \
		exit 1; \
	else \
		echo "note: mypy not installed; skipped type checking"; \
	fi

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

# Line coverage of src/ under the unit suite. Writes .coverage in the repo
# root; CI renders it into the README badge with scripts/coverage_badge.py.
COV := $(shell command -v uv >/dev/null 2>&1 && echo "uv run --no-project --with coverage python" || echo python3)

coverage:
	PYTHONPATH=src $(COV) -m coverage run --source=src -m unittest discover -s tests
	$(COV) -m coverage report -m
