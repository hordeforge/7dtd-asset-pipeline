"""Build hook: ship the documentation inside the package.

The metadata lives in pyproject.toml; this file exists for one job. `docs/`
stays at the repository root, because that is where a human and GitHub expect
it and where every relative link between the pages resolves. But an agent
working in a *mod* repository has only the installed `shamway` command —
no checkout — and `shamway docs <topic>` has to work there, so the same
files are copied into the package at build time.

Copied, not symlinked: a symlink survives an editable install and nothing else.
An editable install needs no copy at all, because `docs.py` falls back to the
source tree it can still see.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py

ROOT = Path(__file__).parent
SOURCE_DOCS = ROOT / "docs"
SOURCE_SCRIPTS = ROOT / "scripts"
PACKAGE = "sevendtd_asset_pipeline"


# setuptools publishes no type information (no py.typed): the base class is
# Any, and strict mode needs this named exception right on the subclass line.
class build_py(_build_py):  # type: ignore[misc]  # noqa: N801 - setuptools requires this name
    def run(self) -> None:
        staged = ROOT / "src" / PACKAGE / "docs"
        if SOURCE_DOCS.is_dir():
            shutil.rmtree(staged, ignore_errors=True)
            staged.mkdir(parents=True, exist_ok=True)
            for page in sorted(SOURCE_DOCS.rglob("*.md")):
                target = staged / page.relative_to(SOURCE_DOCS)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(page, target)
        # The host scripts ship the same way, so `shamway script NAME` works
        # in a mod that has no checkout of this repository.
        staged_scripts = ROOT / "src" / PACKAGE / "scripts"
        if SOURCE_SCRIPTS.is_dir():
            shutil.rmtree(staged_scripts, ignore_errors=True)
            staged_scripts.mkdir(parents=True, exist_ok=True)
            for script in sorted(SOURCE_SCRIPTS.glob("*.sh")):
                shutil.copy2(script, staged_scripts / script.name)
        super().run()


setup(cmdclass={"build_py": build_py})
