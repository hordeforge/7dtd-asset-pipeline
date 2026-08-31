"""Configuration loading and path resolution."""

from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigNotFoundError, PipelineError

CONFIG_NAME = ".shamway.toml"
VALID_BUNDLE = re.compile(r"^[a-z0-9][a-z0-9._-]*\.unity3d$")


def _toml_string(value: str) -> str:
    """A value as a quoted TOML basic string, safe for any input.

    `mod_name` arrives from ModInfo.xml and the rest from command lines, so a
    name carrying a quote, a backslash, or a control character must terminate
    nothing: rendered raw it would write a configuration that fails to parse,
    or silently truncate at the first quote. JSON string escaping is valid TOML
    basic-string escaping (`\\"`, `\\\\`, `\\n`, `\\uXXXX`), and `tomllib`
    decodes it to exactly the original value.
    """
    return json.dumps(value)


# Where the mod's bundle comes from. This is the one key that decides whether a
# Unity editor has to exist on this machine at all, so every Unity-touching
# surface (doctor, build, status, validate) reads it rather than guessing from
# whether UNITY_EDITOR happens to be set. Declaration order is the order these
# are offered in: "synthesized" is the default, and "unity" is the one a mod
# opts into.
BUNDLE_SOURCES = {
    "synthesized": "this tool writes it directly, with no editor: shamway build",
    "none": "the mod ships no bundle; XML, loose atlas icons and DLLs only",
    "external": "an editor elsewhere builds it; this host gates and stages it: shamway stage",
    "unity": "a local editor builds it: shamway build",
}
DEFAULT_BUNDLE_SOURCE = "synthesized"
# What `source_root` means differs per bundle source, so each one owns its
# default here rather than in the caller. `"unity"` names a path inside the
# project the editor collects from; every other source has no project, so the
# same key is read against the mod root and must point somewhere in it.
UNITY_SOURCE_ROOT = "Assets/ModAssets/Bundle"
SYNTHESIZED_SOURCE_ROOT = "assets-src/bundle"


def default_source_root(bundle_source: str) -> str:
    """The membership folder a bundle source expects when none was given."""
    return UNITY_SOURCE_ROOT if bundle_source == "unity" else SYNTHESIZED_SOURCE_ROOT


def resolve_bundle_source(bundle_source: str | None, adopting: bool) -> str:
    """What an unstated `bundle_source` means.

    Unity is opt-in, so nothing chooses it for a caller who did not ask —
    except adopting a Unity project, which is the ask. `init --adopt PROJECT`
    that then had to repeat `--bundle-source unity` would be a second gesture
    for the decision the first one already made, and forgetting it would
    scaffold a synthesized mod beside a project nothing reads.
    """
    if bundle_source is not None:
        return bundle_source
    return "unity" if adopting else DEFAULT_BUNDLE_SOURCE


# The sources that build here. They differ in what starts the build, not in
# what gates it afterwards.
LOCAL_BUNDLE_SOURCES = ("synthesized", "unity")
# What SHAMWAY_BUNDLE_SOURCE may set: every declared source except "none",
# because whether a mod has a bundle is the mod's decision recorded in the
# file, and the environment only says where this host gets it from. Derived
# from BUNDLE_SOURCES so the two cannot drift when a source is added.
MACHINE_BUNDLE_SOURCES = tuple(name for name in BUNDLE_SOURCES if name != "none")
BUNDLE_SOURCE_ENV = "SHAMWAY_BUNDLE_SOURCE"

# The motion a generated acceptance case may capture. Declared per asset stem
# under `[acceptance] motion_kinds`; see docs/authoring/video.md for what each
# generates. "fixed" opts out of a motion clip entirely (a world-fixed thing
# has no motion worth capturing), which is why the fixture pins it to today's
# unchanged generation. "walk-entity" spawns the stem as a real entity class
# and drives it walking along the ground — the only kind that grounds the
# entity with the game's own spawner rather than staging a prefab.
MOTION_KINDS = ("turntable", "walk-cycle", "walk-entity", "fixed")


@dataclass(frozen=True)
class PipelineConfig:
    config_file: Path
    mod_root: Path
    mod_name: str
    bundle_name: str
    unity_project: Path
    source_root: str
    build_dir: Path
    manifest_dir: Path
    resources_dir: Path
    config_dir: Path
    target: str
    bundle_source: str
    unity_version: str | None
    """The revision from `[unity] version`.

    Only the editorless backend reads it, and only when no game is configured:
    with a Unity project the revision comes from `ProjectVersion.txt`, and with
    a game install it comes from a shipped bundle's own header. Both are better
    evidence than a string in a configuration file.
    """
    unity_editor: Path | None
    game_dir: Path | None
    compress_textures: bool = False
    """Whether the editorless writer block-compresses textures.

    Off by default because it is lossy, and this pipeline does not quietly
    change what an author signed off on. On, a fully opaque texture becomes
    `DXT1` (8x smaller) and one with alpha `DXT5` (4x), which is what Unity's
    own importer would have done; `build` prints the visible PSNR of each so
    the trade is a number rather than a shrug.
    """
    compress_audio: bool = False
    """Whether the editorless writer encodes clips to Vorbis.

    Off for the same reason `compress_textures` is: Vorbis is lossy, and the
    samples a listener signed off on are the PCM ones. On, a clip becomes an
    FSB5 Vorbis bank (mode 15) — what Unity's own importer would have written,
    and roughly 40x smaller. It needs FFmpeg to encode and the `fsb5`
    capability to gate the setup header FMOD rebuilds.
    """
    code_references: tuple[str, ...] = ()
    """Bundle stems the mod's own C# loads, which no XML names.

    `validate` can only discover what `Config/**/*.xml` references. A prefab
    loaded from a Harmony hook (`DataLoader.LoadAsset<GameObject>(uri)`), a
    light prefab a particle module instantiates, an AudioClip a script plays —
    none of those appear in any XML, so a typo in their stem is invisible
    offline unless the mod declares them here. Listed stems are checked against
    the tracked manifest exactly like an XML reference: present, unambiguous,
    exact case.
    """
    acceptance_motion_kinds: dict[str, str] = field(default_factory=dict)
    """Per-asset motion kind (`turntable` | `walk-cycle` | `fixed`).

    Declared under `[acceptance] motion_kinds = {"thing": "turntable"}` and
    read by `shamway acceptance-provider`: a declared kind turns that asset's
    generated look case into a `CaseDef.StagedClip` (a motion clip the
    playtest runner captures), except `fixed`, which keeps today's unchanged
    generation. Absent means today's behavior, byte for byte.
    """

    @property
    def has_bundle(self) -> bool:
        """Whether this mod ships a `.unity3d` at all.

        A mod of XML and loose `UIAtlases/` PNGs is a complete 7DTD modlet and
        never needs Unity. Saying so here is what keeps the bundle gates from
        reporting the absence of a file the mod was never meant to have.
        """
        return self.bundle_source != "none"

    @property
    def builds_locally(self) -> bool:
        """Whether `shamway build` produces the bundle on this machine."""
        return self.bundle_source in LOCAL_BUNDLE_SOURCES

    @property
    def bundle_source_dir(self) -> Path:
        """The folder whose contents become the bundle.

        With a Unity project `source_root` is a path inside it, because that is
        what the editor collects. Without one there is no project to be inside,
        so the same key is read against the mod root.
        """
        if self.bundle_source == "unity":
            return self.unity_project / self.source_root
        return self.mod_root / self.source_root

    def require_bundle(self) -> None:
        if not self.has_bundle:
            raise PipelineError(
                f'{self.config_file.name} sets bundle_source = "none", so this mod has no '
                'bundle. Set it to "synthesized" (written here, no editor), "external", or '
                '"unity", and give it a bundle_name, to add one.'
            )

    @property
    def bundle_output(self) -> Path:
        self.require_bundle()
        return self.resources_dir / self.bundle_name

    @property
    def tracked_manifest(self) -> Path:
        self.require_bundle()
        return self.manifest_dir / f"{self.bundle_name}.manifest"


def _path(base: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise PipelineError(f"{field} must be a non-empty path string")
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def _optional_path(base: Path, value: object, env_name: str) -> Path | None:
    raw = os.environ.get(env_name) or (value if isinstance(value, str) else "")
    return _path(base, raw, env_name) if raw else None


def _machine_bundle_source(configured: str) -> str:
    """Let the machine say where *this* host gets the bundle from.

    Whether a mod has a bundle is the mod's business and lives in the file.
    Whether an editor exists on this particular machine is not: the same
    committed configuration is checked out on a build host with an editor and
    on a laptop or agent box without one, exactly like `UNITY_EDITOR`. So
    `SHAMWAY_BUNDLE_SOURCE` chooses where *this* machine gets the bundle from
    ("unity", "synthesized", or "external") but may never invent or remove a
    bundle.
    """
    override = os.environ.get(BUNDLE_SOURCE_ENV, "").strip()
    if not override:
        return configured
    if override not in MACHINE_BUNDLE_SOURCES:
        allowed = ", ".join(repr(name) for name in MACHINE_BUNDLE_SOURCES)
        raise PipelineError(
            f"{BUNDLE_SOURCE_ENV} may only be {allowed} (it says "
            f"where this machine gets the bundle from), not {override!r}"
        )
    if configured == "none":
        raise PipelineError(
            f"{BUNDLE_SOURCE_ENV}={override} cannot apply: the configuration says this mod "
            "ships no bundle. Whether a mod has a bundle is the mod's decision, not the "
            "machine's; change bundle_source in the configuration to add one."
        )
    return override


def find_config(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        return current
    for directory in (current, *current.parents):
        candidate = directory / CONFIG_NAME
        if candidate.is_file():
            return candidate
    raise ConfigNotFoundError(
        f"could not find {CONFIG_NAME} from {current}; run 'shamway init MOD_ROOT'"
    )


def load_config(path: Path | None = None) -> PipelineConfig:
    config_file = find_config(path)
    try:
        data = tomllib.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise PipelineError(f"cannot read {config_file}: {exc}") from exc

    if data.get("schema_version") != 1:
        raise PipelineError(f"{config_file}: schema_version must be 1")
    base = config_file.parent
    mod_root = _path(base, data.get("mod_root", "."), "mod_root")
    mod_name = data.get("mod_name")
    bundle_name = data.get("bundle_name", "")
    # Absent means "synthesized": this tool writes the bundle itself. Unity is
    # opt-in, so the source that needs an editor is the one a configuration has
    # to ask for by name. Every configuration `init` renders states the key
    # explicitly, so this default only ever applies to a hand-written file.
    bundle_source = data.get("bundle_source", DEFAULT_BUNDLE_SOURCE)
    if not isinstance(mod_name, str) or not mod_name.strip():
        raise PipelineError("mod_name must be a non-empty string")
    if bundle_source not in BUNDLE_SOURCES:
        options = ", ".join(f"{name!r} ({why})" for name, why in BUNDLE_SOURCES.items())
        raise PipelineError(f"bundle_source must be one of: {options}")
    bundle_source = _machine_bundle_source(bundle_source)
    if bundle_source == "none":
        # A name for a file the mod does not ship would be a lie every other
        # surface then has to reason about, so it is rejected rather than ignored.
        if bundle_name:
            raise PipelineError(
                'bundle_source = "none" means the mod ships no bundle, so bundle_name '
                f"must be empty, not {bundle_name!r}"
            )
    elif not isinstance(bundle_name, str) or not VALID_BUNDLE.fullmatch(bundle_name):
        raise PipelineError(
            "bundle_name must be a lowercase filesystem-safe name ending in .unity3d"
        )
    unity = data.get("unity", {})
    game = data.get("game", {})
    if not isinstance(unity, dict) or not isinstance(game, dict):
        raise PipelineError("[unity] and [game] must be TOML tables")
    code_references = data.get("code_references", [])
    if not isinstance(code_references, list) or not all(
        isinstance(item, str) and item.strip() for item in code_references
    ):
        raise PipelineError("code_references must be a list of non-empty asset stems")
    if code_references and bundle_source == "none":
        raise PipelineError(
            'code_references name assets inside a bundle, but bundle_source = "none"'
        )
    acceptance = data.get("acceptance", {})
    if not isinstance(acceptance, dict):
        raise PipelineError("[acceptance] must be a TOML table")
    motion_kinds = acceptance.get("motion_kinds", {})
    if not isinstance(motion_kinds, dict) or any(
        not isinstance(stem, str)
        or not stem.strip()
        or not isinstance(kind, str)
        or kind not in MOTION_KINDS
        for stem, kind in motion_kinds.items()
    ):
        raise PipelineError(
            "acceptance.motion_kinds must map asset stems to a motion kind "
            f"({', '.join(MOTION_KINDS)})"
        )

    config = PipelineConfig(
        config_file=config_file,
        mod_root=mod_root,
        mod_name=mod_name,
        bundle_name=bundle_name,
        unity_project=_path(
            base, data.get("unity_project", "tools/shamway/UnityProject"), "unity_project"
        ),
        source_root=str(data.get("source_root", "Assets/ModAssets/Bundle")),
        build_dir=_path(base, data.get("build_dir", ".shamway/build"), "build_dir"),
        manifest_dir=_path(
            base, data.get("manifest_dir", "tools/shamway/manifests"), "manifest_dir"
        ),
        resources_dir=_path(mod_root, data.get("resources_dir", "Resources"), "resources_dir"),
        config_dir=_path(mod_root, data.get("config_dir", "Config"), "config_dir"),
        target=str(data.get("target", "StandaloneWindows64")),
        bundle_source=bundle_source,
        unity_version=str(unity.get("version") or "") or None,
        unity_editor=_optional_path(base, unity.get("editor"), "UNITY_EDITOR"),
        game_dir=_optional_path(base, game.get("directory"), "SEVEN_DAYS_TO_DIE_DIR"),
        compress_textures=bool(data.get("compress_textures", False)),
        compress_audio=bool(data.get("compress_audio", False)),
        code_references=tuple(item.strip() for item in code_references),
        acceptance_motion_kinds=dict(motion_kinds),
    )
    # `source_root` means two different things per bundle source: a path inside
    # the Unity project for "unity", and a path in the mod for "synthesized".
    # A configuration switched from the first to the second without moving it
    # therefore points at <mod>/Assets/ModAssets/Bundle, which does not exist —
    # and the "create that folder" error a build would print is the wrong
    # advice, since the fix is to change the key. Caught here, before any work
    # starts. Only "synthesized" reads the key at all: "external" gets a bundle
    # someone else built and "none" has none, so both keep the scaffolded
    # default harmlessly and must not be refused for it.
    if (
        bundle_source == "synthesized"
        and config.source_root.startswith("Assets/")
        and not config.bundle_source_dir.is_dir()
    ):
        raise PipelineError(
            f"source_root {config.source_root!r} is a path inside a Unity project, but "
            'bundle_source = "synthesized" has no project — so it is read against the mod '
            f"root and resolves to {config.bundle_source_dir}, which does not exist. Point "
            "source_root at a folder in the mod (the scaffolded default is "
            '"assets-src/bundle") and put the source files there. Moving a mod off the '
            "editor lane: 'shamway docs no-unity'."
        )
    for config_field, owned_path in (
        ("resources_dir", config.resources_dir),
        ("config_dir", config.config_dir),
    ):
        if not owned_path.is_relative_to(config.mod_root):
            raise PipelineError(f"{config_field} must stay below mod_root: {owned_path}")
    return config


def render_config(
    mod_name: str,
    bundle_name: str,
    unity_version: str,
    unity_project: str = "tools/shamway/UnityProject",
    source_root: str | None = None,
    manifest_dir: str = "tools/shamway/manifests",
    bundle_source: str = DEFAULT_BUNDLE_SOURCE,
) -> str:
    """Render `.shamway.toml`.

    The three path arguments exist because a mod that already had a Unity
    project keeps it where it is: adoption is a configuration change, not a
    file move. Moving a Unity project means moving every `.meta` with it, and
    a mistake there re-imports every asset under a new GUID.

    `bundle_source` decides whether the rendered configuration describes a mod
    that builds its own bundle, stages one built elsewhere, or has none — the
    only key that decides whether this machine needs a Unity editor.

    An unstated `source_root` follows the bundle source rather than a single
    literal: a path inside the Unity project for `"unity"`, and one in the mod
    for everything else. A shared default silently rendered a project-relative
    path into a configuration with no project, which resolves nowhere.

    Every interpolated value goes through `_toml_string`: these strings come
    from ModInfo.xml and command lines, which are untrusted here.
    """
    source_root = source_root or default_source_root(bundle_source)
    if bundle_source == "none":
        return f"""# Paths are relative to this file unless absolute.
schema_version = 1
mod_root = "."
mod_name = {_toml_string(mod_name)}

# This mod ships no Unity asset bundle: XML, loose UIAtlases/ PNGs, and DLLs
# only. No Unity editor is needed to build, validate or ship it. Adding a
# bundle later means setting bundle_source = "synthesized", giving it a
# bundle_name, and putting source files in the folder source_root names — still
# with no editor. See `shamway docs no-unity`.
bundle_source = "none"

resources_dir = "Resources"
config_dir = "Config"

[game]
# Prefer SEVEN_DAYS_TO_DIE_DIR. The installed game is read-only reference.
directory = ""
"""
    if bundle_source == "synthesized":
        return f"""# Paths are relative to this file unless absolute.
schema_version = 1
mod_root = "."
mod_name = {_toml_string(mod_name)}
bundle_name = {_toml_string(bundle_name)}

# This mod's bundle is written by shamway itself: no Unity editor, no Unity
# project. `source_root` is the folder whose contents become the bundle, and it
# is read against this file rather than against a project that does not exist.
# What can be synthesized and what still needs an editor: `shamway docs no-unity`.
bundle_source = "synthesized"
source_root = {_toml_string(source_root)}

build_dir = ".shamway/build"
manifest_dir = {_toml_string(manifest_dir)}
resources_dir = "Resources"
config_dir = "Config"
target = "StandaloneWindows64"

# Block-compress textures to DXT1 (opaque, 8x smaller) or DXT5 (alpha, 4x).
# Off because it is lossy: turn it on deliberately, then look at the result.
# Every texture's sides must then be a multiple of four.
compress_textures = false

# Encode clips to Vorbis in an FSB5 bank (roughly 40x smaller) instead of PCM.
# Off because it is lossy: turn it on deliberately, then listen to the result.
# Needs FFmpeg to encode and the 'fsb5' capability to gate the header.
compress_audio = false

# Bundle stems the mod's C# loads directly. No XML names them, so `validate`
# only sees them if they are listed here. Stem only, exact case, no extension.
code_references = []

[unity]
# No editor is used. The revision is still recorded, because a bundle carries
# the revision it claims to be for; SEVEN_DAYS_TO_DIE_DIR overrides it with the
# installed game's own answer, which is the better evidence.
version = {_toml_string(unity_version)}

[game]
# Prefer SEVEN_DAYS_TO_DIE_DIR. The installed game is read-only reference.
directory = ""
"""
    external = bundle_source == "external"
    editor_note = (
        "# Built by an editor elsewhere (CI, another machine) and staged here with\n"
        "# `shamway stage BUNDLE --manifest M --log L`. UNITY_EDITOR is not needed\n"
        "# on this host; the build host still needs the revision below."
        if external
        else "# Prefer the UNITY_EDITOR environment variable for machine-local paths."
    )
    return f'''# Paths are relative to this file unless absolute.
schema_version = 1
mod_root = "."
mod_name = {_toml_string(mod_name)}
bundle_name = {_toml_string(bundle_name)}

# Where the bundle comes from: "synthesized" (this tool writes it, no editor;
# the default), "unity" (a local editor builds it), "external" (an editor
# elsewhere builds it and `shamway stage` gates it here), or "none" (the mod
# ships no bundle). See `shamway docs no-unity`.
bundle_source = "{bundle_source}"

unity_project = {_toml_string(unity_project)}
source_root = {_toml_string(source_root)}
build_dir = ".shamway/build"
manifest_dir = {_toml_string(manifest_dir)}
resources_dir = "Resources"
config_dir = "Config"
target = "StandaloneWindows64"

# Bundle stems the mod's C# loads directly (DataLoader.LoadAsset, a particle
# Lights prefab, a scripted AudioClip). No XML names them, so `validate` only
# sees them if they are listed here. Stem only, exact case, no extension.
code_references = []

[unity]
{editor_note}
editor = ""
version = {_toml_string(unity_version)}

[game]
# Prefer SEVEN_DAYS_TO_DIE_DIR. The installed game is read-only reference.
directory = ""
'''
