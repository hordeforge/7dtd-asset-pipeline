.PHONY: check lint typecheck locked test coverage all dist reproducible clean-dist

# bash is the shell this repository's scripts and CI both run, and `-o pipefail`
# is the difference between a failing command on the left of a pipe and a green
# target. Every recipe inherits both, so a recipe cannot swallow a failure.
SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c

# scripts/bootstrap installs the pinned analyzers into .venv/bin without
# putting them on PATH; prefer them so a bootstrapped checkout always runs
# exactly what CI runs instead of silently skipping gates CI enforces.
export PATH := $(CURDIR)/.venv/bin:$(PATH)

# The interpreter every target here runs on, read from the one file that pins
# it. `uv run --no-project` would otherwise pick whatever the host or uv
# considers current, which is a different Python on every machine and moves
# under a checkout that never changed.
PYTHON_PIN := $(strip $(shell cat .python-version 2>/dev/null))
PYTHON := $(shell command -v uv >/dev/null 2>&1 && echo "uv run --no-project --python $(or $(PYTHON_PIN),3.11) python" || echo python3)

# Where `dist` writes. Overridden by `reproducible`, which builds twice.
DIST_DIR ?= dist

all: check test

# actionlint is the workflow half of the shellcheck contract, and it checks the
# thing nothing else can: a workflow is only exercised by pushing it. It caught
# `${{ runner.temp }}` in a job-level `env:`, where that context does not
# resolve, which GitHub reports only as "a workflow file issue" after a push.
# Not a CI hard-fail like ruff and mypy, because CI proves its own workflows by
# running them; this is here so a person does not learn it from a red push.
#
# Every shell script the repo tracks, not a hand-kept list: playtest-capture.sh
# and playtest-synthesized.sh shipped unlinted for three commits because this
# line named only their older siblings. The wildcard cannot forget one.
SHELL_SCRIPTS := scripts/bootstrap $(wildcard scripts/*.sh)

check: lint typecheck locked
	$(PYTHON) -m compileall -q src tests $(wildcard scripts/*.py)
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
	@if command -v actionlint >/dev/null 2>&1; then \
		actionlint .github/workflows/*.yml; \
	else \
		echo "note: actionlint not installed; skipped workflow linting"; \
	fi

# Python analysis, mirroring the shellcheck contract: run when the tool is on
# PATH, hard-fail in CI, and say so plainly when skipped on a dev host.
lint:
	@if command -v ruff >/dev/null 2>&1; then \
		ruff check . && \
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

# Every CI job installs with `uv sync --locked`, which fails outright when
# uv.lock has drifted from pyproject.toml. Catching that here costs
# milliseconds and turns a whole-matrix red build into one local line: the
# dynamic-version switch went in without a re-lock and every job died at
# install, before a single test ran.
locked:
	@if command -v uv >/dev/null 2>&1; then \
		uv lock --check; \
	else \
		echo "note: uv not installed; skipped the lockfile check"; \
	fi

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

# Line coverage of src/ under the unit suite. Writes .coverage in the repo
# root; CI renders it into the README badge with scripts/coverage_badge.py.
# coverage rides in the pinned dev group, so $(PYTHON) resolves it from
# uv.lock and a run cannot grade against whatever PyPI served that day.
coverage:
	@$(PYTHON) -c "import coverage" 2>/dev/null || \
		{ echo "ERROR: coverage is not installed; run scripts/bootstrap" >&2; exit 1; }
	PYTHONPATH=src $(PYTHON) -m coverage run --source=src -m unittest discover -s tests
	$(PYTHON) -m coverage report -m

# The published sdist and wheel, and the only command in the repository that
# builds them; the release workflow calls this rather than `uv build` so a tag
# is cut by the same recipe a contributor can run.
#
# Reproducible by construction: the epoch defaults to the commit's own date
# rather than the wall clock, and the locale and timezone are pinned so a
# sorted file list and a formatted name cannot vary with the host. uv honors
# SOURCE_DATE_EPOCH for the wheel's zip entries; the sdist's tar metadata is the
# build machine's clock and user, which normalize_dist.py replaces.
dist:
	@command -v uv >/dev/null 2>&1 || { \
		echo "ERROR: uv not found; install it with scripts/install-tools.sh" >&2; \
		exit 1; \
	}
	@epoch="$${SOURCE_DATE_EPOCH:-$$(git log -1 --format=%ct 2>/dev/null)}"; \
	if [ -z "$$epoch" ]; then \
		echo "ERROR: no SOURCE_DATE_EPOCH in the environment and no git commit date;" >&2; \
		echo "       build from a checkout, or set SOURCE_DATE_EPOCH yourself" >&2; \
		exit 1; \
	fi; \
	echo "building distributions into $(DIST_DIR) with SOURCE_DATE_EPOCH=$$epoch"; \
	TZ=UTC LC_ALL=C SOURCE_DATE_EPOCH="$$epoch" uv build --out-dir '$(DIST_DIR)'; \
	$(PYTHON) scripts/normalize_dist.py --epoch "$$epoch" $(DIST_DIR)/*.tar.gz

# Two builds of this tree, compared byte for byte. The reproducibility claim is
# otherwise untested, and the ways it breaks (a timestamp, a uid, an unsorted
# file list) are invisible until something diffs the two.
reproducible:
	@first="$$(mktemp -d)"; second="$$(mktemp -d)"; \
	trap 'rm -rf "$$first" "$$second"' EXIT; \
	$(MAKE) --no-print-directory dist DIST_DIR="$$first" >/dev/null; \
	$(MAKE) --no-print-directory dist DIST_DIR="$$second" >/dev/null; \
	compared=0; \
	for artifact in "$$first"/*; do \
		name="$$(basename "$$artifact")"; \
		cmp "$$artifact" "$$second/$$name" >/dev/null || { \
			echo "ERROR: two builds of this tree disagree on $$name" >&2; \
			exit 1; \
		}; \
		compared=$$((compared + 1)); \
	done; \
	test "$$compared" -gt 0 || { echo "ERROR: no distribution was built" >&2; exit 1; }; \
	echo "OK: $$compared artifacts are byte-identical across two builds"

# The build leaves `build/`, setuptools' `src/*.egg-info`, and the staged copies
# of docs/ and scripts/ that setup.py writes into the package. All four are
# regenerated on every build.
clean-dist:
	rm -rf build $(DIST_DIR) src/*.egg-info \
		src/sevendtd_asset_pipeline/docs src/sevendtd_asset_pipeline/scripts
