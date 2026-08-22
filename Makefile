.PHONY: check test all

all: check test

check:
	python3 -m compileall -q src tests
	bash -n scripts/bootstrap scripts/install-tools.sh scripts/install-unity-editor.sh
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck -S warning scripts/bootstrap scripts/install-tools.sh scripts/install-unity-editor.sh; \
	else \
		echo "note: shellcheck not installed; skipped shell linting"; \
	fi

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v
