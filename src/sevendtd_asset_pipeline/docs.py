"""Serve this project's documentation from the installed package.

An agent working in a mod repository has the `shamway` command and nothing
else — no checkout of this repository, and often no network. The rules it needs
(the art-direction contract, the sound lane's engine facts, the ownership split
between the two repositories) would otherwise have to be copied into every mod,
which is exactly the duplication this pipeline exists to avoid.

So the docs ship inside the package and are readable from anywhere:

    shamway docs                  # what is available
    shamway docs art-direction    # print one, to read or to pipe

The mod keeps its own mod-specific documentation. This serves only what is
general.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from .errors import PipelineError

# Topic -> filename, with a one-line summary for the listing. Ordered the way a
# reader meets them rather than alphabetically. Filenames are relative to the
# docs root and carry their subdirectory; the categories themselves are
# described in docs/README.md.
TOPICS: dict[str, tuple[str, str]] = {
    "index": ("README.md", "what each documentation category holds, and where to start"),
    "mod-repo-layout": ("mod-repo-layout.md", "what lives in the mod repo and what lives here"),
    "sibling-repos": (
        "sibling-repos.md",
        "the other HordeForge repositories, and the client lock this one shares",
    ),
    "quickstart": ("getting-started/quickstart.md", "bare machine to a validated bundle"),
    "setup": (
        "getting-started/setup.md",
        "Python, game path, Unity, licensing, Windows module",
    ),
    "no-unity": (
        "bundles/no-unity.md",
        "the four answers to where the bundle comes from, three of them editorless",
    ),
    "offline-bundle-builder": (
        "adrs/0001-synthesize-bundles-without-an-editor.md",
        "the editorless writer: format research, what shipped, and remaining shader variants",
    ),
    "mesh-icon": (
        "adrs/0006-render-icons-from-the-mesh-with-blender.md",
        "the editorless icon lane, and why it renders clay rather than the in-game look",
    ),
    "consumer-api": ("consumer-api.md", "schema, call, serve, and the Python facade"),
    "game-integration": ("game-integration.md", "XML URIs, icons, audio, inheritance, packaging"),
    "art-direction": (
        "authoring/art-direction.md",
        "the house style, prompt patterns, and the two icon lanes",
    ),
    "audio": (
        "authoring/audio.md",
        "sound synthesis, sounds.xml, and why a loaded clip can be silent",
    ),
    "model-audio-review": (
        "prds/0001-contextual-model-audio-review.md",
        "the contextual model-audition and advisory-review contract, and what shipped with it",
    ),
    "model-video-review": (
        "prds/0002-video-based-asset-review.md",
        "the video-based asset review: motion clips, the deadeye gateway, and what shipped with it",
    ),
    "video": (
        "authoring/video.md",
        "staged motion clips, the motion-kind declaration, and the deadeye review lane",
    ),
    "vfx": (
        "authoring/vfx.md",
        "`.vfx` ParticleSystem graphs, budgets, LOD tiers, and two silent material failures",
    ),
    "skinned-gear": (
        "authoring/skinned-gear.md",
        "worn armor: SkinnedMeshRenderer from a glTF skin; SDCS extras still want an editor",
    ),
    "entities": (
        "authoring/entities.md",
        "custom entities: the rigs, generate rig/entity, the entityclasses.xml wiring,"
        " the Physics-node grounding capsule, movement, the per-part UV atlas +"
        " role-aware hide, and the per-rig live sign-off",
    ),
    "environment-effects": (
        "authoring/environment-effects.md",
        "weather, fog and light: the effect the bundle cannot carry",
    ),
    "agent-workflows": (
        "authoring/agent-workflows.md",
        "the lane each asset type follows, and the evidence packet",
    ),
    "authoring-tools": (
        "authoring/authoring-tools.md",
        "the researched OSS tools and which gate each belongs to",
    ),
    "bundle-generation": ("bundles/bundle-generation.md", "the complete build path"),
    "validation": ("validation.md", "each gate and its proof boundary"),
    "improvements": (
        "status/improvements.md",
        "known gaps, what closes them, and the OSS tools that belong to each",
    ),
    "troubleshooting": ("runbooks/troubleshooting.md", "failure messages and their root causes"),
    "configuration": ("configuration.md", "every .shamway.toml key"),
    "architecture": ("architecture.md", "design, boundaries, and the trust model"),
    "blockers": ("status/blockers.md", "what still needs a human, a licence, or a client"),
    "research-provenance": (
        "research/research-provenance.md",
        "where each 7DTD-specific rule came from",
    ),
    "release-checklist": ("runbooks/release-checklist.md", "artifact and live acceptance"),
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
        "the packaged documentation is missing; reinstall the pipeline (uv sync from a checkout)"
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
        raise PipelineError(
            f"unknown documentation topic {topic!r}; expected one of: {known}"
        ) from None
    path = _root() / filename
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PipelineError(f"cannot read {path}: {exc}") from exc
