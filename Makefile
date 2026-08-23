.PHONY: check lint typecheck test coverage all

# uv runs the suite when it is available so contributors share one toolchain;
# the plain interpreter still works, because the core has no dependencies.
PYTHON := $(shell command -v uv >/dev/null 2>&1 && echo "uv run --no-project python3" || echo python3)

all: check test

SHELL_SCRIPTS := scripts/bootstrap scripts/install-tools.sh scripts/install-unity-editor.sh scripts/compile-editor-scripts.sh

check: lint
	$(PYTHON) -m compileall -q src tests
	bash -n $(SHELL_SCRIPTS)
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck -S warning $(SHELL_SCRIPTS); \
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
	elif [ -n "$${CI:-}" ]; then \
		echo "ERROR: CI requires ruff; e.g. uv tool install ruff" >&2; \
		exit 1; \
	else \
		echo "note: ruff not installed; skipped python linting"; \
	fi

# Not part of `check` yet: the tree still carries ~80 findings under these
# settings (first-assignment narrowing in cli.run(), object-typed JSON flows in
# tests). Fix them, then add `typecheck` to the check prerequisites and the CI
# install step makes it blocking.
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
