"""Serve this project's documentation from the installed package.

An agent working in a mod repository has the `7dtd-assets` command and nothing
else — no checkout of this repository, and often no network. The rules it needs
(the art-direction contract, the sound lane's engine facts, the ownership split
between the two repositories) would otherwise have to be copied into every mod,
which is exactly the duplication this pipeline exists to avoid.

So the docs ship inside the package and are readable from anywhere:

    7dtd-assets docs                  # what is available
    7dtd-assets docs art-direction    # print one, to read or to pipe

The mod keeps its own mod-specific documentation. This serves only what is
general.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from .errors import PipelineError

# Topic -> filename, with a one-line summary for the listing. Ordered the way a
# reader meets them rather than alphabetically.
TOPICS: dict[str, tuple[str, str]] = {
    "mod-repo-layout": ("mod-repo-layout.md", "what lives in the mod repo and what lives here"),
    "quickstart": ("quickstart.md", "bare machine to a validated bundle"),
    "setup": ("setup.md", "Python, game path, Unity, licensing, Windows module"),
    "consumer-api": ("consumer-api.md", "schema, call, serve, and the Python facade"),
    "game-integration": ("game-integration.md", "XML URIs, icons, audio, inheritance, packaging"),
    "art-direction": ("art-direction.md", "the house style, prompt patterns, and the two icon lanes"),
    "audio": ("audio.md", "sound synthesis, sounds.xml, and why a loaded clip can be silent"),
    "vfx": ("vfx.md", "particle budgets, LOD tiers, and two silent material failures"),
    "agent-workflows": ("agent-workflows.md", "the lane each asset type follows, and the evidence packet"),
    "authoring-tools": ("authoring-tools.md", "the researched OSS tools and which gate each belongs to"),
    "bundle-generation": ("bundle-generation.md", "the complete build path"),
    "validation": ("validation.md", "each gate and its proof boundary"),
    "troubleshooting": ("troubleshooting.md", "failure messages and their root causes"),
    "configuration": ("configuration.md", "every .7dtd-assets.toml key"),
    "architecture": ("architecture.md", "design, boundaries, and the trust model"),
    "research-provenance": ("research-provenance.md", "where each 7DTD-specific rule came from"),
    "release-checklist": ("release-checklist.md", "artifact and live acceptance"),
}


def _root() -> Path:
    """Where the documentation is, whether installed or run from a checkout."""
    packaged = files("sevendtd_asset_pipeline").joinpath("docs")
    if packaged.is_dir():
        return Path(str(packaged))
    # Running from a source tree: the real docs/ directory is two levels up.
    source = Path(__file__).resolve().parents[2] / "docs"
    if source.is_dir():
        return source
    raise PipelineError(
        "the packaged documentation is missing; reinstall the pipeline "
        "(uv pip install --editable . from a checkout)"
    )


def topics() -> list[dict[str, str]]:
    """Every readable topic, with its summary and whether it is present."""
    root = _root()
    return [
        {
            "topic": topic,
            "summary": summary,
            "available": str((root / filename).is_file()).lower(),
        }
        for topic, (filename, summary) in TOPICS.items()
    ]


def read(topic: str) -> str:
    """The full text of one documentation topic."""
    try:
        filename = TOPICS[topic][0]
    except KeyError:
        known = ", ".join(TOPICS)
        raise PipelineError(f"unknown documentation topic {topic!r}; expected one of: {known}") from None
    path = _root() / filename
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PipelineError(f"cannot read {path}: {exc}") from exc
