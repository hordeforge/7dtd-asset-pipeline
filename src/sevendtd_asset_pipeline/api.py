"""`Pipeline`: the single entry point for programmatic consumers.

The package exports ~30 functions, which is a fine library surface and a poor
API: a caller has to know which to call, in what order, and how to thread the
configuration through each one. `Pipeline` is that knowledge, expressed once.

    from sevendtd_asset_pipeline import Pipeline

    pipeline = Pipeline.discover()          # finds .shamway.toml upward
    if not pipeline.status().valid:
        pipeline.build()
        pipeline.validate()

Every method returns a JSON-serializable value — usually a dataclass with an
`as_dict`, sometimes a `Path`, list, or mapping; `_as_json` normalizes them all
— and every failure raises `PipelineError` with one user-actionable message.
`call()` dispatches
the same operations by name against the registry in `operations.py`, which is
what `shamway call` and `shamway serve` use, so the Python API and the
out-of-process API cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from . import client
from .acceptance import generate as generate_acceptance_provider
from .build import (
    SYNTHESIZED_CAVEATS,
    expected_unity_version,
    reject_disabled_modules,
    run_build,
    stage_bundle,
)
from .bundle_verify import VerifyReport, verify_with_editor
from .bundle_writer import pack_directory
from .capabilities import Capability, capabilities, require_capability
from .client import AcceptanceRun, LogReport
from .config import PipelineConfig, load_config
from .deep_inspect import DeepReport, deep_inspect
from .doctor import Check, run_doctor
from .errors import PipelineError
from .game import game_unity_version, project_unity_version
from .icon_check import IconReport, check_icons
from .icon_render import RenderResult, render_icon
from .mesh_check import MeshReport, check_mesh
from .operations import Operation
from .operations import get as get_operation
from .prompts import PromptResult
from .prompts import render as render_prompt
from .references import AssetReference, discover_references, manifest_assets
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
        adopt_project: Path | str | None = None,
        source_root: str | None = None,
        manifest_dir: str | None = None,
        bundle_source: str = "unity",
    ) -> tuple[Pipeline, list[Path]]:
        """Create the pipeline inside an existing modlet and return it, ready to use.

        Supply either `game_dir`, which reads the authoritative revision from a
        shipped game bundle, or an explicitly verified `unity_version`.

        `adopt_project` points at a Unity project the mod already has: the
        template is not copied, only the pipeline-owned editor scripts are
        installed, and the configuration is written to match. Nothing moves.
        """
        if game_dir is not None:
            unity_version = game_unity_version(Path(game_dir).resolve())[0]
        if not unity_version and bundle_source != "none":
            raise PipelineError(
                'scaffolding needs game_dir or unity_version, unless bundle_source is "none"'
            )
        root = Path(mod_root)
        created = initialize(
            root,
            mod_name,
            bundle_name,
            unity_version or "",
            changeset,
            adopt_project,
            source_root,
            manifest_dir,
            bundle_source,
        )
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

    def acceptance_provider(
        self,
        harness_dll: Path | str | None = None,
        install: bool = False,
        mods_dir: Path | str | None = None,
    ) -> dict[str, object]:
        """Render (and optionally build) the client-side acceptance provider.

        The cases are the mod's own manifest, so a bundle member that nothing
        asserts is a member nobody proved.
        """
        install_dir = None
        if install:
            install_dir = Path(mods_dir) if mods_dir else client.user_mods_dir(self.config.game_dir)
        # The install copy into the shared Mods folder happens under the held
        # client lock, like every other writer there: refuse-then-copy left an
        # acquirer a window to launch between the two steps.
        with (
            client.hold_for_write("install into the shared Mods folder")
            if install
            else nullcontext()
        ):
            return generate_acceptance_provider(
                self.config,
                self.config.game_dir,
                Path(harness_dll) if harness_dll else None,
                install_dir,
            )

    def verify_bundle(self, bundle: Path | str | None = None) -> VerifyReport:
        """Load a bundle in a real Unity runtime and report what came back.

        Needs an editor, and needs nothing else to have used one: this is how a
        synthesized bundle gets a check that this repository did not write.
        """
        return verify_with_editor(
            Path(bundle) if bundle else self.config.bundle_output,
            self.config.unity_editor,
            expected_unity_version(self.config),
            self.config.build_dir / "verify",
        )

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

    def client_where(self, game_dir: Path | str | None = None) -> dict[str, Any]:
        """The Proton client's per-user paths, derived from the game directory."""
        return client.where_info(Path(game_dir) if game_dir else self.config.game_dir)

    def client_log(
        self,
        path: Path | str | None = None,
        log_dir: Path | str | None = None,
        mod_name: str | None = None,
    ) -> LogReport:
        """Classify the newest client log (or a given one)."""
        return _client_log(path, log_dir, mod_name, self.config.game_dir)

    def unity_release(self, version: str | None = None, platform: str = "LINUX") -> Release:
        """Resolve the official editor download for a revision. Uses the network."""
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

    def client_deploy(
        self, mods_dir: Path | str | None = None, mod_name: str | None = None, replace: bool = True
    ) -> dict[str, Any]:
        """Copy the deployable modlet into the client's per-user Mods/ folder.

        The write happens under the shared client lock, so a deployment can
        never land between another session's acquire and launch.
        """
        name = mod_name or self.config.mod_name
        target = Path(mods_dir) if mods_dir else client.user_mods_dir(self.config.game_dir)
        with client.hold_for_write("deploy into the shared Mods folder"):
            copied = client.deploy_mod(self.config.mod_root, target, name, replace)
        return {"destination": str(target / name), "copied": copied}

    def client_launch(
        self,
        run_seconds: int | None = None,
        mute: bool = False,
        mod_name: str | None = None,
        steam_bin: str = "steam",
        log_dir: Path | str | None = None,
    ) -> AcceptanceRun:
        """Start a fresh client through Steam and classify the log it writes."""
        return client.fresh_client_run(
            self.config.game_dir,
            mod_name or self.config.mod_name,
            run_seconds=run_seconds,
            mute=mute,
            steam_bin=steam_bin,
            log_dir=Path(log_dir) if log_dir else None,
        )

    def stage(
        self,
        bundle: Path | str,
        manifest: Path | str | None = None,
        log: Path | str | None = None,
    ) -> tuple[Path, list[str]]:
        """Gate a bundle built elsewhere and stage it. Needs no Unity on this host.

        Returns the staged path and the gates that could not run, which a
        caller must report: an unrun gate reads exactly like a passed one.
        """
        return stage_bundle(
            self.config,
            Path(bundle),
            Path(manifest) if manifest else None,
            Path(log) if log else None,
        )

    def pack(
        self,
        source: Path | str,
        output: Path | str,
        unity_version: str | None = None,
        game_dir: Path | str | None = None,
        manifest: Path | str | None = None,
    ) -> dict[str, Any]:
        """Synthesize a bundle from a directory of assets, with no editor."""
        return _pack(
            {
                "source": str(source),
                "output": str(output),
                "unity_version": unity_version,
                "game_dir": str(game_dir) if game_dir else None,
                "manifest": str(manifest) if manifest else None,
            },
            self.config.game_dir,
        )

    def build(self, probe: bool = False) -> Path:
        """Build, gate, and stage. The only method that writes into the modlet.

        With `probe=True` it builds a throwaway cube bundle that proves the
        environment and stages nothing.
        """
        return run_build(self.config, probe)

    def prompt(
        self,
        kind: str,
        subject: str,
        role: str = "",
        palette: str = "",
        key: str = "",
        avoid: tuple[str, ...] = (),
        stem: str = "myModThing",
    ) -> PromptResult:
        """One house-style image-generation prompt, and the lane that follows it.

        Needs no config and no mod: an agent can render a prompt before the
        modlet exists. The style contract behind it is `docs/authoring/art-direction.md`.
        """
        return render_prompt(kind, subject, role, palette, key, tuple(avoid), stem)

    # -- dispatch ----------------------------------------------------------

    def call(self, name: str, params: dict[str, Any] | None = None) -> Any:
        """Run a registered operation by name with a JSON-shaped params dict.

        This is what `shamway call` and `shamway serve` dispatch through,
        so an out-of-process consumer reaches exactly the methods above.
        """
        operation = get_operation(name)
        arguments = _validated(operation, params)
        return _DISPATCH[name](self, arguments)


def _validated(operation: Operation, params: dict[str, Any] | None) -> dict[str, Any]:
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
            raise PipelineError(f"operation {operation.name!r} requires parameter {required!r}")
    for name, value in arguments.items():
        allowed = properties[name].get("enum")
        if allowed and value not in allowed:
            options = ", ".join(repr(option) for option in allowed)
            raise PipelineError(
                f"operation {operation.name!r} got {name}={value!r}; expected one of: {options}"
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
_DISPATCH: dict[str, Callable[[Pipeline, dict[str, Any]], Any]] = {
    "status": lambda self, p: self.status(),
    "capabilities": lambda self, p: self.capabilities(p.get("probe_versions", False)),
    "doctor": lambda self, p: self.doctor(),
    "validate": lambda self, p: self.validate(p.get("bundle")),
    "refs": lambda self, p: self.refs(),
    "inspect": lambda self, p: self.inspect(p.get("bundle")),
    "inspect_deep": lambda self, p: self.inspect_deep(p.get("bundle")),
    "check_mesh": lambda self, p: self.check_mesh(**_mesh_params(p)),
    "check_log": lambda self, p: _check_log_result(Path(p["log"])),
    "check_sound": lambda self, p: self.check_sound(**_sound_params(p)),
    "check_icons": lambda self, p: self.check_icons(
        p.get("atlas_root", "UIAtlases"), p.get("cell", 160)
    ),
    "render_icon": lambda self, p: self.render_icon(
        p["prefab"],
        p.get("output"),
        p.get("size", 160),
        p.get("atlas", "ItemIconAtlas"),
        p.get("yaw", 208.0),
        p.get("pitch", 8.0),
        p.get("padding", 1.22),
    ),
    "unity_release": lambda self, p: self.unity_release(
        p.get("version"), p.get("platform", "LINUX")
    ),
    "build": lambda self, p: {"bundle": str(self.build(p.get("probe", False)))},
    "pack": lambda self, p: _pack(p, self.config.game_dir),
    "verify_bundle": lambda self, p: self.verify_bundle(p.get("bundle")),
    "acceptance_provider": lambda self, p: self.acceptance_provider(
        p.get("harness_dll"), bool(p.get("install", False)), p.get("mods_dir")
    ),
    "stage": lambda self, p: _stage_result(
        self.stage(p["bundle"], p.get("manifest"), p.get("log"))
    ),
    "init": lambda self, p: _init(p),
    "client_where": lambda self, p: self.client_where(p.get("game_dir")),
    "client_deploy": lambda self, p: self.client_deploy(
        p.get("mods_dir"), p.get("mod_name"), p.get("replace", True)
    ),
    "client_launch": lambda self, p: self.client_launch(
        p.get("run_seconds"),
        p.get("mute", False),
        p.get("mod_name"),
        p.get("steam_bin", "steam"),
        p.get("log_dir"),
    ),
    "client_log": lambda self, p: self.client_log(
        p.get("path"), p.get("log_dir"), p.get("mod_name")
    ),
    "prompt": lambda self, p: self.prompt(**_prompt_params(p)),
}


def _client_log(
    path: Path | str | None, log_dir: Path | str | None, mod_name: str | None, game_dir: Path | None
) -> LogReport:
    if path:
        return client.scan_log(Path(path), mod_name)
    directory = Path(log_dir) if log_dir else client.client_log_dir(game_dir)
    return client.scan_log(client.latest_client_log(directory), mod_name)


# Shared parameter plumbing for the operations that run identically with and
# without a configuration. One mapping per operation keeps the JSON-schema
# defaults in `_STATELESS` from drifting away from the bound methods in
# `_DISPATCH`.
def _prompt_params(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": params["kind"],
        "subject": params["subject"],
        "role": params.get("role", ""),
        "palette": params.get("palette", ""),
        "key": params.get("key", ""),
        "avoid": tuple(params.get("avoid", ())),
        "stem": params.get("stem", "myModThing"),
    }


def _mesh_params(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "mesh": Path(params["mesh"]),
        "max_extent": params.get("max_extent", 16.0),
        "strict": params.get("strict", False),
    }


def _sound_params(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "clip": Path(params["clip"]),
        "max_seconds": params.get("max_seconds", 30.0),
        "require_mono": params.get("require_mono", True),
    }


def _pack(params: dict[str, Any], game_dir: Path | None) -> dict[str, Any]:
    """Synthesize a bundle outside any mod configuration.

    The revision is not defaulted to something current: the caller names it, or
    an installed game answers. A bundle carries the revision it claims to be
    for, and a wrong one loads as "not compatible with this newer version".
    """
    source = Path(params["source"])
    output = Path(params["output"])
    version = params.get("unity_version")
    directory = Path(params["game_dir"]) if params.get("game_dir") else game_dir
    if not version and directory:
        version = game_unity_version(directory)[0]
    if not version:
        raise PipelineError(
            "pack needs 'unity_version' or 'game_dir': a bundle carries the revision it "
            "claims to be for, and the installed game is what has to load it"
        )
    bundle, manifest_text = pack_directory(source, output.name, version)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(bundle)
    manifest = Path(params["manifest"]) if params.get("manifest") else Path(f"{output}.manifest")
    manifest.write_text(manifest_text, encoding="utf-8")
    return {
        "bundle": str(output),
        "manifest": str(manifest),
        "bytes": len(bundle),
        "assets": manifest_assets(manifest),
        "caveats": list(SYNTHESIZED_CAVEATS),
    }


def _stage_result(staged: tuple[Path, list[str]]) -> dict[str, Any]:
    bundle, skipped = staged
    return {"bundle": str(bundle), "skipped": skipped}


def _check_log_result(log: Path) -> dict[str, bool]:
    reject_disabled_modules(log)
    return {"ok": True}


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
        adopt_project=params.get("adopt_project"),
        source_root=params.get("source_root"),
        manifest_dir=params.get("manifest_dir"),
        bundle_source=params.get("bundle_source", "unity"),
    )
    return {"created": [str(path) for path in created]}


# Operations that work without a mod configuration.
_STATELESS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "capabilities": lambda p: capabilities(p.get("probe_versions", False)),
    # A prompt is rendered before the modlet exists as often as after it.
    "prompt": lambda p: render_prompt(**_prompt_params(p)),
    "check_mesh": lambda p: check_mesh(**_mesh_params(p)),
    "check_log": lambda p: _check_log_result(Path(p["log"])),
    "check_sound": lambda p: check_sound(**_sound_params(p)),
    "unity_release": lambda p: fetch_release(
        p["version"] if p.get("version") else _needs_version(), p.get("platform", "LINUX")
    ),
    "init": _init,
    "pack": lambda p: _pack(p, None),
    "client_where": lambda p: client.where_info(
        Path(p["game_dir"]) if p.get("game_dir") else client.game_dir_from_env()
    ),
    "client_launch": lambda p: client.fresh_client_run(
        client.game_dir_from_env(),
        p.get("mod_name"),
        run_seconds=p.get("run_seconds"),
        mute=p.get("mute", False),
        steam_bin=p.get("steam_bin", "steam"),
        log_dir=Path(p["log_dir"]) if p.get("log_dir") else None,
    ),
    "client_log": lambda p: _client_log(
        p.get("path"), p.get("log_dir"), p.get("mod_name"), client.game_dir_from_env()
    ),
}
