"""`Pipeline`: the single entry point for programmatic consumers.

The package exports ~30 functions, which is a fine library surface and a poor
API: a caller has to know which to call, in what order, and how to thread the
configuration through each one. `Pipeline` is that knowledge, expressed once.

    from sevendtd_asset_pipeline import Pipeline

    pipeline = Pipeline.discover()          # finds .shamway.toml upward
    if not pipeline.status().valid:
        pipeline.build()
        pipeline.validate()

Every method returns a dataclass that serializes to JSON, and every failure
raises `PipelineError` with one user-actionable message. `call()` dispatches
the same operations by name against the registry in `operations.py`, which is
what `shamway call` and `shamway serve` use, so the Python API and the
out-of-process API cannot drift apart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .build import reject_disabled_modules, run_build
from .capabilities import Capability, capabilities, require_capability
from .config import PipelineConfig, load_config
from .deep_inspect import DeepReport, deep_inspect
from .doctor import Check, run_doctor
from .errors import PipelineError
from .game import game_unity_version
from .icon_check import IconReport, check_icons
from .icon_render import RenderResult, render_icon
from .mesh_check import MeshReport, check_mesh
from .operations import get as get_operation
from .references import AssetReference, discover_references
from .scaffold import initialize
from .sound_check import SoundReport, check_sound
from .status import Status, collect_status
from .unity_release import Release, fetch_release
from .unityfs import BundleInfo, inspect_bundle
from .validation import ValidationReport, validate_bundle, validate_mod


class Pipeline:
    """A mod's asset pipeline, bound to one `.shamway.toml`."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config

    @classmethod
    def discover(cls, start: Path | str | None = None) -> Pipeline:
        """Resolve the nearest configuration at or above `start` (default: cwd)."""
        return cls(load_config(Path(start) if start is not None else None))

    @classmethod
    def scaffold(
        cls,
        mod_root: Path | str,
        *,
        unity_version: str | None = None,
        game_dir: Path | str | None = None,
        mod_name: str | None = None,
        bundle_name: str | None = None,
        changeset: str | None = None,
    ) -> tuple[Pipeline, list[Path]]:
        """Create the pipeline inside an existing modlet and return it, ready to use.

        Supply either `game_dir`, which reads the authoritative revision from a
        shipped game bundle, or an explicitly verified `unity_version`.
        """
        if game_dir is not None:
            unity_version = game_unity_version(Path(game_dir).resolve())[0]
        if not unity_version:
            raise PipelineError("scaffolding needs game_dir or unity_version")
        root = Path(mod_root)
        created = initialize(root, mod_name, bundle_name, unity_version, changeset)
        return cls.discover(root), created

    def __repr__(self) -> str:
        return f"Pipeline(mod_name={self.config.mod_name!r}, bundle={self.config.bundle_name!r})"

    # -- read-only ---------------------------------------------------------

    def status(self) -> Status:
        """Whole-mod state. Never raises for a mod-state problem."""
        return collect_status(self.config)

    def doctor(self) -> list[Check]:
        """Host readiness. Each check carries its own OK/WARN/INFO/FAIL verdict."""
        return run_doctor(self.config)

    def capabilities(self, probe_versions: bool = False) -> list[Capability]:
        """Optional capabilities, what they unlock, and how to install them."""
        return capabilities(probe_versions)

    def refs(self) -> list[AssetReference]:
        """Every bundle URI in the mod's `Config/**/*.xml`."""
        return discover_references(self.config.config_dir)

    def inspect(self, bundle: Path | str | None = None) -> BundleInfo:
        """UnityFS metadata for the staged bundle, or another one."""
        return inspect_bundle(Path(bundle) if bundle else self.config.bundle_output)

    def inspect_deep(self, bundle: Path | str | None = None) -> DeepReport:
        """Every serialized object and per-prefab components. Needs UnityPy."""
        return deep_inspect(Path(bundle) if bundle else self.config.bundle_output)

    def validate(self, bundle: Path | str | None = None) -> ValidationReport:
        """Validate the staged bundle and all XML references, or one bundle."""
        if bundle is not None:
            expected = self.expected_unity_version()
            info = validate_bundle(Path(bundle), expected)
            return ValidationReport((f"OK {info.path}: Unity {info.unity_version}",), 0)
        return validate_mod(self.config)

    def expected_unity_version(self) -> str | None:
        """The revision the installed game requires, when a game dir is configured."""
        if not self.config.game_dir:
            return None
        return game_unity_version(self.config.game_dir)[0]

    def check_log(self, log: Path | str) -> None:
        """Raise if a Unity log reports success while stripping engine modules."""
        reject_disabled_modules(Path(log))

    def check_mesh(
        self, mesh: Path | str, max_extent: float = 16.0, strict: bool = False
    ) -> MeshReport:
        """Check an authored mesh before Unity import. Needs trimesh."""
        return check_mesh(Path(mesh), max_extent, strict)

    def check_sound(
        self, clip: Path | str, max_seconds: float = 30.0, require_mono: bool = True
    ) -> SoundReport:
        """Measure a WAV clip and reject unshippable formats. No dependencies."""
        return check_sound(Path(clip), max_seconds, require_mono)

    def check_icons(self, atlas_root: str = "UIAtlases", cell: int = 160) -> IconReport:
        """Check the mod's atlas PNGs and its CustomIcon keys. Icons are not bundle members."""
        return check_icons(self.config.mod_root, self.config.config_dir, atlas_root, cell)

    def unity_release(self, version: str | None = None, platform: str = "LINUX") -> Release:
        """Resolve the official editor download for a revision. Uses the network."""
        from .game import project_unity_version

        return fetch_release(version or project_unity_version(self.config.unity_project), platform)

    # -- writes ------------------------------------------------------------

    def render_icon(
        self,
        prefab: str,
        output: Path | str | None = None,
        size: int = 160,
        atlas: str = "ItemIconAtlas",
        yaw: float = 208.0,
        pitch: float = 8.0,
        padding: float = 1.22,
    ) -> RenderResult:
        """Render a bundle prefab into an atlas icon. Starts a real editor."""
        return render_icon(self.config, prefab, output, size, atlas, yaw, pitch, padding)

    def build(self, probe: bool = False) -> Path:
        """Build, gate, and stage. The only method that writes into the modlet.

        With `probe=True` it builds a throwaway cube bundle that proves the
        environment and stages nothing.
        """
        return run_build(self.config, probe)

    # -- dispatch ----------------------------------------------------------

    def call(self, name: str, params: dict[str, Any] | None = None) -> Any:
        """Run a registered operation by name with a JSON-shaped params dict.

        This is what `shamway call` and `shamway serve` dispatch through,
        so an out-of-process consumer reaches exactly the methods above.
        """
        operation = get_operation(name)
        arguments = _validated(operation, params)
        return _DISPATCH[name](self, arguments)


def _validated(operation, params: dict[str, Any] | None) -> dict[str, Any]:
    """Reject unknown or missing parameters, and demand any capability, up front.

    Failing here means an out-of-process caller gets the same message for the
    same mistake as a Python caller, before any work starts.
    """
    arguments = dict(params or {})
    properties = operation.parameters.get("properties", {})
    unknown = set(arguments) - set(properties)
    if unknown:
        allowed = ", ".join(sorted(properties)) or "none"
        raise PipelineError(
            f"operation {operation.name!r} got unknown parameter(s): "
            f"{', '.join(sorted(unknown))}; accepts: {allowed}"
        )
    for required in operation.parameters.get("required", []):
        if required not in arguments:
            raise PipelineError(
                f"operation {operation.name!r} requires parameter {required!r}"
            )
    for capability in operation.capabilities:
        require_capability(capability)
    return arguments


def _as_json(value: Any) -> Any:
    """Convert a pipeline result into something `json.dumps` accepts."""
    for attribute in ("as_dict", "describe"):
        method = getattr(value, attribute, None)
        if callable(method):
            return method()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_as_json(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(value)
    return value


def call_json(pipeline: Pipeline | None, name: str, params: dict[str, Any] | None = None) -> Any:
    """Dispatch an operation and return a JSON-serializable result.

    `pipeline` may be None for operations whose `needs_config` is False, which
    is what lets `capabilities`, `check_mesh`, `check_log`, `unity_release`, and
    `init` run outside a scaffolded mod.
    """
    operation = get_operation(name)
    if operation.needs_config and pipeline is None:
        raise PipelineError(
            f"operation {name!r} needs a mod configuration; run it inside a modlet "
            "containing .shamway.toml, or pass a config path"
        )
    if pipeline is None:
        return _as_json(_STATELESS[name](_validated(operation, params)))
    return _as_json(pipeline.call(name, params))


# Config-bound operations, resolved against a Pipeline instance.
_DISPATCH: dict[str, Any] = {
    "status": lambda self, p: self.status(),
    "capabilities": lambda self, p: self.capabilities(p.get("probe_versions", False)),
    "doctor": lambda self, p: self.doctor(),
    "validate": lambda self, p: self.validate(p.get("bundle")),
    "refs": lambda self, p: self.refs(),
    "inspect": lambda self, p: self.inspect(p.get("bundle")),
    "inspect_deep": lambda self, p: self.inspect_deep(p.get("bundle")),
    "check_mesh": lambda self, p: self.check_mesh(
        p["mesh"], p.get("max_extent", 16.0), p.get("strict", False)
    ),
    "check_log": lambda self, p: (self.check_log(p["log"]), {"ok": True})[1],
    "check_sound": lambda self, p: self.check_sound(
        p["clip"], p.get("max_seconds", 30.0), p.get("require_mono", True)
    ),
    "check_icons": lambda self, p: self.check_icons(
        p.get("atlas_root", "UIAtlases"), p.get("cell", 160)
    ),
    "render_icon": lambda self, p: self.render_icon(
        p["prefab"], p.get("output"), p.get("size", 160), p.get("atlas", "ItemIconAtlas"),
        p.get("yaw", 208.0), p.get("pitch", 8.0), p.get("padding", 1.22),
    ),
    "unity_release": lambda self, p: self.unity_release(p.get("version"), p.get("platform", "LINUX")),
    "build": lambda self, p: {"bundle": str(self.build(p.get("probe", False)))},
    "init": lambda self, p: _init(p),
}


def _needs_version() -> str:
    raise PipelineError(
        "unity_release needs a 'version' parameter when it runs outside a scaffolded "
        "mod; inside one it defaults to the Unity project's revision"
    )


def _init(params: dict[str, Any]) -> dict[str, Any]:
    _, created = Pipeline.scaffold(
        params["mod_root"],
        unity_version=params.get("unity_version"),
        game_dir=params.get("game_dir"),
        mod_name=params.get("mod_name"),
        bundle_name=params.get("bundle_name"),
        changeset=params.get("changeset"),
    )
    return {"created": [str(path) for path in created]}


# Operations that work without a mod configuration.
_STATELESS: dict[str, Any] = {
    "capabilities": lambda p: capabilities(p.get("probe_versions", False)),
    "check_mesh": lambda p: check_mesh(
        Path(p["mesh"]), p.get("max_extent", 16.0), p.get("strict", False)
    ),
    "check_log": lambda p: (reject_disabled_modules(Path(p["log"])), {"ok": True})[1],
    "check_sound": lambda p: check_sound(
        Path(p["clip"]), p.get("max_seconds", 30.0), p.get("require_mono", True)
    ),
    "unity_release": lambda p: fetch_release(
        p["version"] if p.get("version") else _needs_version(), p.get("platform", "LINUX")
    ),
    "init": _init,
}
