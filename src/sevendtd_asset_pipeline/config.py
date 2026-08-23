"""Configuration loading and path resolution."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import PipelineError

CONFIG_NAME = ".shamway.toml"
VALID_BUNDLE = re.compile(r"^[a-z0-9][a-z0-9._-]*\.unity3d$")


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
    unity_editor: Path | None
    game_dir: Path | None
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

    @property
    def bundle_output(self) -> Path:
        return self.resources_dir / self.bundle_name

    @property
    def tracked_manifest(self) -> Path:
        return self.manifest_dir / f"{self.bundle_name}.manifest"


def _path(base: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise PipelineError(f"{field} must be a non-empty path string")
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def _optional_path(base: Path, value: object, env_name: str) -> Path | None:
    raw = os.environ.get(env_name) or (value if isinstance(value, str) else "")
    return _path(base, raw, env_name) if raw else None


def find_config(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        return current
    for directory in (current, *current.parents):
        candidate = directory / CONFIG_NAME
        if candidate.is_file():
            return candidate
    raise PipelineError(
        f"could not find {CONFIG_NAME} from {current}; run 'shamway init MOD_ROOT'"
    )


def load_config(path: Path | None = None) -> PipelineConfig:
    config_file = find_config(path)
    try:
        data = tomllib.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PipelineError(f"cannot read {config_file}: {exc}") from exc

    if data.get("schema_version") != 1:
        raise PipelineError(f"{config_file}: schema_version must be 1")
    base = config_file.parent
    mod_root = _path(base, data.get("mod_root", "."), "mod_root")
    mod_name = data.get("mod_name")
    bundle_name = data.get("bundle_name")
    if not isinstance(mod_name, str) or not mod_name.strip():
        raise PipelineError("mod_name must be a non-empty string")
    if not isinstance(bundle_name, str) or not VALID_BUNDLE.fullmatch(bundle_name):
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

    config = PipelineConfig(
        config_file=config_file,
        mod_root=mod_root,
        mod_name=mod_name,
        bundle_name=bundle_name,
        unity_project=_path(base, data.get("unity_project", "tools/shamway/UnityProject"), "unity_project"),
        source_root=str(data.get("source_root", "Assets/ModAssets/Bundle")),
        build_dir=_path(base, data.get("build_dir", ".shamway/build"), "build_dir"),
        manifest_dir=_path(base, data.get("manifest_dir", "tools/shamway/manifests"), "manifest_dir"),
        resources_dir=_path(mod_root, data.get("resources_dir", "Resources"), "resources_dir"),
        config_dir=_path(mod_root, data.get("config_dir", "Config"), "config_dir"),
        target=str(data.get("target", "StandaloneWindows64")),
        unity_editor=_optional_path(base, unity.get("editor"), "UNITY_EDITOR"),
        game_dir=_optional_path(base, game.get("directory"), "SEVEN_DAYS_TO_DIE_DIR"),
        code_references=tuple(item.strip() for item in code_references),
    )
    for field, owned_path in (
        ("resources_dir", config.resources_dir),
        ("config_dir", config.config_dir),
    ):
        if not owned_path.is_relative_to(config.mod_root):
            raise PipelineError(f"{field} must stay below mod_root: {owned_path}")
    return config


def render_config(
    mod_name: str,
    bundle_name: str,
    unity_version: str,
    unity_project: str = "tools/shamway/UnityProject",
    source_root: str = "Assets/ModAssets/Bundle",
    manifest_dir: str = "tools/shamway/manifests",
) -> str:
    """Render `.shamway.toml`.

    The three path arguments exist because a mod that already had a Unity
    project keeps it where it is: adoption is a configuration change, not a
    file move. Moving a Unity project means moving every `.meta` with it, and
    a mistake there re-imports every asset under a new GUID.
    """
    return f'''# Paths are relative to this file unless absolute.
schema_version = 1
mod_root = "."
mod_name = "{mod_name}"
bundle_name = "{bundle_name}"
unity_project = "{unity_project}"
source_root = "{source_root}"
build_dir = ".shamway/build"
manifest_dir = "{manifest_dir}"
resources_dir = "Resources"
config_dir = "Config"
target = "StandaloneWindows64"

# Bundle stems the mod's C# loads directly (DataLoader.LoadAsset, a particle
# Lights prefab, a scripted AudioClip). No XML names them, so `validate` only
# sees them if they are listed here. Stem only, exact case, no extension.
code_references = []

[unity]
# Prefer the UNITY_EDITOR environment variable for machine-local paths.
editor = ""
version = "{unity_version}"

[game]
# Prefer SEVEN_DAYS_TO_DIE_DIR. The installed game is read-only reference.
directory = ""
'''
