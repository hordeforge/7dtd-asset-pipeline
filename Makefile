.PHONY: check test all

# uv runs the suite when it is available so contributors share one toolchain;
# the plain interpreter still works, because the core has no dependencies.
PYTHON := $(shell command -v uv >/dev/null 2>&1 && echo "uv run --no-project python3" || echo python3)

all: check test

check:
	$(PYTHON) -m compileall -q src tests
	bash -n scripts/bootstrap scripts/install-tools.sh scripts/install-unity-editor.sh
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck -S warning scripts/bootstrap scripts/install-tools.sh scripts/install-unity-editor.sh; \
	else \
		echo "note: shellcheck not installed; skipped shell linting"; \
	fi

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v
