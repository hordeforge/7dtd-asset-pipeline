"""The client half of acceptance: a scenario provider the real game runs.

Every offline gate here ends with the same sentence — acceptance is a fresh
client that loads the changed asset. `client.py` is the plumbing for launching
that client; this module is what the client then *does*.

`verify-bundle` already loads a bundle in a Unity runtime of the game's own
revision, which proves the container and object graph deserialize. It cannot
prove the **game** reads them, because the game does not call
`AssetBundle.LoadFromFile` directly. It calls `DataLoader.LoadAsset<T>` on a
`#@modfolder(Name):Resources/<bundle>.unity3d?<stem>` URI, which runs three
pieces of engine code no runtime test touches:

* `ModManager.PatchModPathString`, rewriting `@modfolder(Name):` to the loaded
  mod's real path — and logging `[MODS] Mod reference for a mod that is not
  loaded` when the name is wrong;
* `AssetBundleManager.LoadAssetBundle`, opening the archive and caching it for
  the life of the process;
* `AssetBundleManager._get`, reducing the request to its file-name stem, which
  is the only thing that reads the `m_Container` table in the class-142 object.

So this module renders a `7dtd-playtest` scenario provider — a small C# mod
that runs inside the live client — with one case per bundle member, asserting
that the game loads it and that its properties survived the trip. It is
generated rather than vendored because the cases *are* the mod's manifest: a
bundle member with no case is a member nobody proved.

What it still cannot do is judge the asset. A texture that loads upside down
and a clip that loads at the wrong pitch both pass here. That is the human
look and listen, recorded with `shamway client capture`.

Running the provider is `7dtd-playtest`'s job, not this repository's: see
docs/sibling-repos.md for the boundary and the exclusivity lock both respect.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from contextlib import nullcontext
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from . import transcode
from .bundle_writer import synthesized_members
from .client import hold_for_write, user_mods_dir
from .config import PipelineConfig, load_config
from .errors import PipelineError
from .references import manifest_assets, read_mod_name

# The `LoadAsset<T>` expression that proves each loaded class actually loaded.
KIND_ASSERTIONS: dict[str, str] = {
    "Texture2D": "loaded.width > 0 && loaded.height > 0",
    "AudioClip": "loaded.channels > 0 && loaded.frequency > 0 && loaded.samples > 0",
    "TextAsset": "loaded.text != null",
    "GameObject": "loaded.transform != null",
    "Material": "loaded.shader != null",
    "Mesh": "loaded.vertexCount > 0 && loaded.triangles.Length > 0",
}

# Which class each manifest extension loads as — keyed by extension because
# `plan()`'s editor-built route sees file names, not classes. A synthesized mod
# asks the writer itself instead (`synthesized_members`), so this table only
# ever answers for a bundle an editor built.
ASSET_CASES: dict[str, str] = {
    ".png": "Texture2D",
    ".tga": "Texture2D",
    ".jpg": "Texture2D",
    ".jpeg": "Texture2D",
    ".bmp": "Texture2D",
    ".wav": "AudioClip",
    ".ogg": "AudioClip",
    ".mp3": "AudioClip",
    ".txt": "TextAsset",
    ".json": "TextAsset",
    ".csv": "TextAsset",
    ".prefab": "GameObject",
    ".fbx": "GameObject",
    ".mat": "Material",
    ".vfx": "GameObject",
    ".glb": "Mesh",
    ".gltf": "Mesh",
    ".obj": "Mesh",
    ".stl": "Mesh",
    ".ply": "Mesh",
}
# The converted lanes: whatever FFmpeg and ImageMagick let into a bundle has
# to be loadable from one too, so their containers join the same table rather
# than drifting into a second list.
for _suffix in transcode.AUDIO_SUFFIXES:
    ASSET_CASES[_suffix] = "AudioClip"
for _suffix in transcode.IMAGE_SUFFIXES:
    ASSET_CASES[_suffix] = "Texture2D"

# What each kind prints into the client log, so a pass is citable rather than
# merely green. `Report.Info` lines land under the harness's stable prefix.
ASSET_DETAILS: dict[str, str] = {
    "Texture2D": '" " + loaded.width + "x" + loaded.height + " " + loaded.format',
    "AudioClip": '" channels=" + loaded.channels + " frequency=" + loaded.frequency '
    '+ " samples=" + loaded.samples + " length=" + loaded.length',
    "TextAsset": '" bytes=" + loaded.bytes.Length',
    "GameObject": '" children=" + loaded.transform.childCount + " renderers=" '
    "+ loaded.GetComponentsInChildren<Renderer>(true).Length",
    "Material": '" shader=" + loaded.shader.name',
    "Mesh": '" vertices=" + loaded.vertexCount + " submeshes=" + loaded.subMeshCount '
    '+ " bounds=" + loaded.bounds.size',
}
TEMPLATE_DIR = "PlaytestProvider"
PROVIDER_DIRECTORY = "tools/shamway/acceptance"
# A stem no bundle contains, asserted to come back null. Without it a loader
# that answered every request would read as a pass on every case above.
ABSENT_STEM = "shamwayAbsentStemProbe"
_IDENTIFIER = re.compile(r"[^A-Za-z0-9_]")
_SUITE_SPLIT = re.compile(r"[,;\s]+")


def mixed_visual_suites(suite_list: str) -> bool:
    """True when a PLAYTEST_SUITE list asks for both prefab-look and block-place.

    Those are different pictures. Instantiating a prefab in front of the camera
    (`*_look`) and `SetBlockRpc` onto a voxel (`*_block_*`) must never share a
    client session: the self-test rendered a texture mid-air AND a placed
    block in the same run, repeatedly, whenever they were comma-listed.

    The name is the picture. This function only sees suite ids. Putting a
    camera-staged instantiate on a suite that is not named `*_look` so it can
    ride with `*_block_*` is the same mix, and this cannot catch it. Not a
    mix: a particle system that is already a child of the staged prefab;
    consecutive cases of one feature in one suite.
    """
    tokens = [token for token in _SUITE_SPLIT.split(suite_list.strip()) if token]
    look = any(token.endswith("_look") for token in tokens)
    block = any("_block_" in token for token in tokens)
    return look and block


def reject_mixed_visual_suites(suite_list: str) -> None:
    """Refuse a suite list that would paint two different pictures in one run."""
    if mixed_visual_suites(suite_list):
        raise PipelineError(
            f"refusing mixed visual suites {suite_list!r}: a prefab-look suite "
            "(*_look) and a block-placement suite (*_block_*) are different "
            "pictures. Run them as separate playtest invocations, never in one "
            "PLAYTEST_SUITE list."
        )


def _cs_body(text: str) -> str:
    """Escape a value for embedding inside an existing C# string literal.

    Stems and mod names arrive from a manifest or ModInfo.xml that can be built
    on another machine (`shamway stage` gates exactly such a pair), so they are
    untrusted here: unescaped, a `"` or a newline in a stem terminates the
    literal and the rest of the name compiles as C# inside a provider the live
    client executes. Control characters outside the named escapes (`\\u0000`,
    `\\x1b`) have no literal form a compiler accepts raw, so they become
    `\\\\uXXXX` too.
    """
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return re.sub(r"[\x00-\x1f\x7f]", lambda match: f"\\u{ord(match.group()):04x}", escaped)


def _comment_text(text: str) -> str:
    """Collapse a value to one line without an XML-comment terminator."""
    return " ".join(text.split()).replace("--", "—")


def _xml_attr(text: str) -> str:
    """Escape a value for a double-quoted XML attribute."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


@dataclass(frozen=True)
class ProviderPlan:
    """What will be written, and the cases it will carry."""

    directory: Path
    assembly: str
    suite_id: str
    mod_name: str
    bundle_uri_path: str
    stems: tuple[tuple[str, str], ...]
    motions: tuple[tuple[str, str], ...] = ()
    """(stem, motion kind) pairs declared under `[acceptance] motion_kinds`."""

    def as_dict(self) -> dict[str, object]:
        return {
            "directory": str(self.directory),
            "assembly": self.assembly,
            "suite": self.suite_id,
            "mod_name": self.mod_name,
            "bundle_uri_path": self.bundle_uri_path,
            "cases": [{"stem": stem, "kind": kind} for stem, kind in self.stems],
            "motions": [{"stem": stem, "kind": kind} for stem, kind in self.motions],
        }


def _identifier(text: str) -> str:
    cleaned = _IDENTIFIER.sub("", text)
    return cleaned or "Mod"


def _template(name: str) -> str:
    path = files("sevendtd_asset_pipeline").joinpath(f"templates/{TEMPLATE_DIR}/{name}")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PipelineError(f"cannot read packaged provider template {path}: {exc}") from exc


def plan(config: PipelineConfig) -> ProviderPlan:
    """Derive the provider from the mod's own configuration and manifest."""
    mod_root = Path(config.mod_root)
    manifest = Path(config.tracked_manifest)
    if not manifest.is_file():
        raise PipelineError(
            f"no tracked manifest at {manifest}; run `shamway build` (or `stage`) first. "
            "The provider's cases are the manifest: without it there is nothing to assert."
        )
    stems: list[tuple[str, str]] = []
    unsupported: list[str] = []
    if config.bundle_source == "synthesized":
        # Ask the writer what it names things instead of mapping an extension
        # to a class. Those two answers stopped agreeing the day a mesh source
        # started producing a prefab: the manifest still lists `prop.glb`, and
        # the object under `prop` is a GameObject, so a provider built from the
        # extension asked for LoadAsset<Mesh>("prop") and a live client
        # correctly returned null.
        stems = list(synthesized_members(Path(config.bundle_source_dir)))
        unsupported = [name for name, kind in stems if kind not in KIND_ASSERTIONS]
        if unsupported:
            raise PipelineError(
                "no load case is defined for the synthesized member(s) "
                + ", ".join(sorted(unsupported)[:5])
                + "; add the class to acceptance.KIND_ASSERTIONS with what proves it loaded."
            )
        return _rendered_plan(config, mod_root, stems)
    for asset in manifest_assets(manifest):
        suffix = Path(asset).suffix.lower()
        kind = ASSET_CASES.get(suffix)
        if kind is None:
            unsupported.append(asset)
            continue
        stems.append((Path(asset).stem, kind))
    if unsupported:
        kinds = ", ".join(sorted(ASSET_CASES))
        raise PipelineError(
            "no load case is defined for " + ", ".join(sorted(unsupported)[:5]) + f"; known "
            f"extensions are {kinds}. Add the extension to acceptance.ASSET_CASES (and, for "
            "a class the table does not yet name, its assertion to KIND_ASSERTIONS), rather "
            "than leaving a bundle member nobody proves."
        )
    if not stems:
        raise PipelineError(f"{manifest} lists no assets a provider case could load")
    return _rendered_plan(config, mod_root, stems)


def _motions(config: PipelineConfig, stems: list[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    """The declared motion kinds, validated against the member stems.

    A motion kind makes sense only on the mesh/prefab a player sees move; a
    kind declared on a member that never stages (a texture, a sound) is
    refused rather than silently ignored, so a typo in the stem cannot read as
    a working motion case.
    """
    known = dict(stems)
    declared: list[tuple[str, str]] = []
    for stem, motion in sorted(config.acceptance_motion_kinds.items()):
        member_kind = known.get(stem)
        if member_kind is None:
            raise PipelineError(
                f"acceptance.motion_kinds names {stem!r}, which is not a bundle member; "
                "a motion kind can only be declared on an asset the provider stages"
            )
        if member_kind != "GameObject":
            raise PipelineError(
                f"acceptance.motion_kinds names {stem!r}, which loads as {member_kind}, not "
                "a prefab; a motion clip stages a mesh/prefab, so the kind belongs on the "
                "GameObject member"
            )
        declared.append((stem, motion))
    return tuple(declared)


def _rendered_plan(
    config: PipelineConfig, mod_root: Path, stems: list[tuple[str, str]]
) -> ProviderPlan:
    """The plan itself, once the (name, class) pairs are known.

    Shared by both routes into `plan`, so a synthesized mod and an
    editor-built one cannot end up with differently shaped providers.
    """
    mod_name = read_mod_name(mod_root / "ModInfo.xml")
    bundle_name = Path(config.bundle_output).name
    resources = Path(config.resources_dir).name
    assembly = f"{_identifier(mod_name)}Acceptance"
    return ProviderPlan(
        directory=mod_root / PROVIDER_DIRECTORY,
        assembly=assembly,
        suite_id=f"{_identifier(mod_name).lower()}_bundle",
        mod_name=mod_name,
        bundle_uri_path=f"{resources}/{bundle_name}",
        stems=tuple(stems),
        motions=_motions(config, stems),
    )


def _case(stem: str, kind: str) -> str:
    detail = ASSET_DETAILS.get(kind, '""')
    assertion = KIND_ASSERTIONS[kind]
    name = _cs_body(stem)
    # The local variable must be a C# identifier even when the stem is not
    # ("blast-loop" would otherwise emit `blast-loopLoaded`): each case's
    # variable lives in its own lambda scope, so sanitized names cannot collide.
    variable = _identifier(stem)
    return f"""
        {kind} {variable}Loaded = null;
        queue.Add(CaseDef.Live(label, "load_{name}", new[] {{ "bundle" }},
            act: ctx =>
            {{
                {variable}Loaded = DataLoader.LoadAsset<{kind}>(Bundle + "?{name}");
                var loaded = {variable}Loaded;
                Report.Info(loaded == null
                    ? "{name}: LoadAsset<{kind}> returned null"
                    : "{name}: " + loaded.name + {detail});
            }},
            assert: ctx =>
            {{
                var loaded = {variable}Loaded;
                return loaded != null && loaded.name == "{name}" && {assertion};
            }},
            fail: "the game did not load {name} from the staged bundle"));
"""


def _stage_body(stem: str) -> str:
    """The `stage:` lambda shared by the staged-look and staged-clip cases.

    The prefab is instantiated directly rather than placed as a block: the
    question is whether *this bundle's* renderer draws, and a block adds the
    game's own placement, rotation and collision on top of the thing under
    test. A ModelEntity block's look is a separate provider that
    `SetBlockRpc`s into a grounded voxel and `Helpers.LookAt`s it (see
    SelfTestMod's `shamwayselftest_block_model`). Standoff is 3.5 m so a
    1 m cube is in frame rather than filling the lens.
    """
    name = _cs_body(stem)
    variable = _identifier(stem)
    return f"""
                var prefab = DataLoader.LoadAsset<GameObject>(Bundle + "?{name}");
                if (prefab == null)
                {{
                    Report.Info("{name}: LoadAsset<GameObject> returned null; nothing to stage");
                    return false;
                }}
                var player = ctx == null ? null : ctx.Player;
                if (player == null)
                {{
                    Report.Info(
                        "{name}: no local player, so there is no camera to stage in front of");
                    return false;
                }}
                // In front of the *camera*, not the player's feet. An
                // EntityPlayerLocal's `position` is its ground position and its
                // own transform faces its body, so a prop placed from those
                // lands under the camera and out of frame - which is exactly
                // what the first staged capture photographed: an empty scene
                // that still passed, because the case only asks whether a
                // renderer exists.
                var camera = player.playerCamera != null
                    ? player.playerCamera.transform
                    : player.transform;
                var ahead = camera.forward;
                {variable}Staged = UnityEngine.Object.Instantiate(prefab);
                CaseDef.RegisterStaged({variable}Staged);
                {variable}Staged.transform.position = camera.position + ahead * 3.5f;
                // Face the camera, and keep the prop's own up axis upright so
                // the orientation card is readable rather than lying on edge.
                {variable}Staged.transform.rotation =
                    Quaternion.LookRotation(-ahead, Vector3.up);
                var renderers = {variable}Staged.GetComponentsInChildren<Renderer>(true);
                Report.Info("{name}: staged at " + {variable}Staged.transform.position
                    + ", camera at " + camera.position
                    + ", with " + renderers.Length + " renderer(s)");
                // A prefab with no renderer cannot be photographed into evidence.
                return renderers.Length > 0;"""


def _staged_case(prefab_stem: str) -> str:
    """A case that puts the prefab in front of the camera and holds it.

    Every other case here answers *did it load*, and a bundle whose prop is
    invisible passes all of them - which is how a shader that renders nothing
    survived every gate this repository has. `CaseDef.Staged` holds the scene
    and announces itself, so a screenshot loop can photograph the frame and a
    person, or another graphics API, can be compared against it.
    """
    name = _cs_body(prefab_stem)
    variable = _identifier(prefab_stem)
    return f"""
        GameObject {variable}Staged = null;
        queue.Add(CaseDef.Staged(label, "look_{name}", new[] {{ "capture", "bundle" }},
            stage: ctx =>
            {{{_stage_body(prefab_stem)}
            }},
            holdSeconds: 12f,
            fail: "could not stage {name} in front of the camera"));
"""


def _staged_clip_case(prefab_stem: str) -> str:
    """A `CaseDef.StagedClip` case: the staged hold plus captured frames.

    The staged prefab rotates one full turn over the hold, so the captured
    frames prove the silhouette from every side — the turntable. The
    generated provider is the only place that already knows, per asset, its
    stem and kind, which is why the declaration lives here rather than in the
    playtest suite. A worn asset that must be seen *walking* is not staged
    here: it uses `_walk_clip_case`, which equips it on the player and records
    the player actually moving.
    """
    name = _cs_body(prefab_stem)
    variable = _identifier(prefab_stem)
    return f"""
        GameObject {variable}Staged = null;
        queue.Add(CaseDef.StagedClip(
            label, "motion_{name}", new[] {{ "capture", "bundle", "clip" }},
            stage: ctx =>
            {{{_stage_body(prefab_stem)}
            }},
            holdSeconds: 12f,
            onHold: (ctx, holdFraction) =>
            {{
                var staged = {variable}Staged;
                if (staged == null) return;
                // One full turn over the hold: 360 degrees across 12 seconds.
                staged.transform.Rotate(0f, 360f * Time.deltaTime / 12f, 0f);
            }},
            fail: "could not stage {name} for its motion clip"));
"""


def _walk_clip_case(prefab_stem: str) -> str:
    """A case that equips the item on the player, walks, and records.

    A walk cycle cannot be staged in front of a camera: the motion is the
    game's own animation of the player actually walking, driven with stock
    autorun (`Helpers.StartWalk`, not teleport). The case gives and equips
    the item by its stem name (`Helpers.TryEquipItem`), records an on-demand
    clip (`Helpers.BeginClip`/`EndClip`) while the player walks, and fails
    cleanly when the item does not exist or cannot be equipped — a
    `walk-cycle` declaration on a non-wearable asset reads as a failed case,
    not a silent hold.
    """
    name = _cs_body(prefab_stem)
    variable = _identifier(prefab_stem)
    return f"""
        int {variable}Equipped = -1;
        queue.Add(CaseDef.Live(label, "motion_{name}", new[] {{ "capture", "clip" }},
            act: ctx =>
            {{
                var player = ctx == null ? null : ctx.Player;
                if (player == null)
                {{
                    Report.Info("{name}: no local player to equip and walk");
                    return;
                }}
                ctx.FloatA = Time.unscaledTime;
                {variable}Equipped = Helpers.TryEquipItem(player, "{name}");
                if ({variable}Equipped < 0)
                {{
                    Report.Info("{name}: could not give/equip an item named \\"{name}\\"; "
                        + "a walk-cycle case is for a worn/equippable asset");
                    return;
                }}
                Helpers.BeginClip("motion_{name}", 2, 4);
                Helpers.StartWalk(1f);
            }},
            wait: ctx =>
            {{
                float elapsed = Time.unscaledTime - ctx.FloatA;
                return elapsed >= 12f;
            }},
            assert: ctx =>
            {{
                Helpers.StopWalk();
                Helpers.EndClip("motion_{name}");
                return {variable}Equipped >= 0;
            }},
            timeout: 40f,
            fail: "could not walk {name} and record its motion clip"));
"""


def render(plan_: ProviderPlan) -> dict[str, str]:
    """The provider's files, as `filename -> text`."""
    cases = "".join(_case(stem, kind) for stem, kind in plan_.stems)
    # One look suite per prefab. Putting every mesh in one `*_look` suite
    # instantiates them at the same camera offset, so a particle system, a
    # skinned mesh and a cube pile up in one spot — that is mixing unrelated
    # pictures, not a sign-off. Each GameObject gets `<mod>_<stem>_look`.
    # Instantiating in front of the camera is not placing a block;
    # `reject_mixed_visual_suites` refuses those two in one PLAYTEST_SUITE.
    motion_kinds = dict(plan_.motions)
    prefix = (
        plan_.suite_id[: -len("_bundle")] if plan_.suite_id.endswith("_bundle") else plan_.suite_id
    )
    look_yields_parts: list[str] = []
    look_branch_parts: list[str] = []
    for stem, kind in plan_.stems:
        if kind != "GameObject":
            continue
        motion = motion_kinds.get(stem)
        if motion == "turntable":
            body = _staged_clip_case(stem)
        elif motion == "walk-cycle":
            body = _walk_clip_case(stem)
        else:
            body = _staged_case(stem)
        look_id = f"{prefix}_{_cs_body(stem)}_look"
        look_yields_parts.append(f'yield return "{look_id}";')
        look_branch_parts.append(
            f'if (suite == "{look_id}")\n        {{\n{body}            return;\n        }}\n'
        )
    look_yields = "\n            ".join(look_yields_parts)
    look_branch = "".join(look_branch_parts)
    mod_name = _cs_body(plan_.mod_name)
    source = _template("AcceptanceProvider.cs.in").format(
        MOD_NAME=mod_name,
        CLASS_NAME=f"{plan_.assembly}Provider",
        SUITE_ID=plan_.suite_id,
        LOOK_YIELDS=look_yields,
        LOOK_BRANCH=look_branch,
        BUNDLE_URI_PATH=_cs_body(plan_.bundle_uri_path),
        CASES=cases,
        ABSENT_STEM=ABSENT_STEM,
    )
    project = _template("AcceptanceProvider.csproj.in").format(
        MOD_NAME=_comment_text(plan_.mod_name), ASSEMBLY_NAME=plan_.assembly
    )
    _description = (
        "Generated 7dtd-playtest scenario provider: loads every "
        "bundle member through the game's own DataLoader."
    )
    mod_info = (
        '<?xml version="1.0" encoding="UTF-8" ?>\n<xml>\n'
        f'\t<Name value="{_xml_attr(plan_.assembly)}" />\n'
        f'\t<DisplayName value="{_xml_attr(plan_.mod_name + " bundle acceptance")}" />\n'
        f'\t<Description value="{_xml_attr(_description)}" />\n'
        '\t<Author value="shamway" />\n\t<Version value="1.0.0" />\n</xml>\n'
    )
    return {
        f"{plan_.assembly}.cs": source,
        f"{plan_.assembly}.csproj": project,
        "ModInfo.xml": mod_info,
    }


def write(plan_: ProviderPlan) -> list[Path]:
    """Write the provider into the mod, overwriting a previous generation."""
    plan_.directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, text in render(plan_).items():
        target = plan_.directory / name
        target.write_text(text, encoding="utf-8")
        written.append(target)
    return written


def build(plan_: ProviderPlan, game_dir: Path, harness_dll: Path, output: Path) -> Path:
    """Compile the provider against the game's assemblies and the harness."""
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        raise PipelineError(
            "building the acceptance provider needs the .NET SDK on PATH ('dotnet'). "
            "It is optional: the rendered source is the deliverable, and any host with "
            "the SDK can build it."
        )
    managed = Path(game_dir) / "7DaysToDie_Data" / "Managed"
    if not (managed / "Assembly-CSharp.dll").is_file():
        raise PipelineError(f"no Assembly-CSharp.dll under {managed}; is that a game install?")
    if not Path(harness_dll).is_file():
        raise PipelineError(
            f"no 7dtd-playtest harness assembly at {harness_dll}. Build it in a checkout of "
            "hordeforge/7dtd-playtest ('make build'), then pass --harness-dll."
        )
    project = plan_.directory / f"{plan_.assembly}.csproj"
    try:
        result = subprocess.run(
            [
                dotnet,
                "build",
                str(project),
                "-c",
                "Release",
                "-o",
                str(output),
                "-v",
                "q",
                f"-p:GameManagedDir={managed}",
                f"-p:PlaytestHarnessPath={Path(harness_dll)}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
    except subprocess.TimeoutExpired as exc:
        raise PipelineError(
            "dotnet build did not finish within 600s and was killed; a cold "
            "NuGet restore on an offline host is the usual cause."
        ) from exc
    if result.returncode != 0:
        tail = (result.stdout + result.stderr).strip().splitlines()[-12:]
        raise PipelineError("dotnet build failed:\n" + "\n".join(tail))
    assembly = output / f"{plan_.assembly}.dll"
    if not assembly.is_file():
        raise PipelineError(f"dotnet build reported success but wrote no {assembly}")
    shutil.copyfile(plan_.directory / "ModInfo.xml", output / "ModInfo.xml")
    return assembly


def generate(
    config: PipelineConfig,
    game_dir: Path | None = None,
    harness_dll: Path | None = None,
    install_dir: Path | None = None,
) -> dict[str, object]:
    """Render the provider, and build and install it when asked."""
    plan_ = plan(config)
    written = write(plan_)
    result: dict[str, object] = {**plan_.as_dict(), "written": [str(p) for p in written]}
    if harness_dll is None:
        result["built"] = None
        return result
    if game_dir is None:
        raise PipelineError("building the provider needs the game directory for its assemblies")
    output = Path(config.build_dir) / "acceptance" / plan_.assembly
    output.mkdir(parents=True, exist_ok=True)
    assembly = build(plan_, game_dir, harness_dll, output)
    result["built"] = str(assembly)
    if install_dir is not None:
        target = Path(install_dir) / plan_.assembly
        target.mkdir(parents=True, exist_ok=True)
        for name in (assembly.name, "ModInfo.xml"):
            shutil.copyfile(output / name, target / name)
        result["installed"] = str(target)
    return result


# ---------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="shamway acceptance-provider",
        description="generate the 7dtd-playtest scenario provider that loads this mod's "
        "bundle through the game's own DataLoader",
    )
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--harness-dll",
        type=Path,
        default=None,
        help="7dtd-playtest.dll; building is skipped when omitted",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="also copy the built provider into the client's Mods folder",
    )
    parser.add_argument("--mods-dir", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    install_dir = None
    if args.install:
        install_dir = args.mods_dir or user_mods_dir(config.game_dir)
    # The install copy into the shared Mods folder happens under the held
    # client lock: refusing first and copying after left an acquirer a window
    # to launch between the two and load a half-installed provider.
    with hold_for_write("install into the shared Mods folder") if args.install else nullcontext():
        result = generate(config, config.game_dir, args.harness_dll, install_dir)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    written = result.get("written")
    if isinstance(written, list):
        for path in written:
            print(f"wrote {path}")
    if result.get("built"):
        print(f"built {result['built']}")
    if result.get("installed"):
        print(f"installed {result['installed']}")
    print(
        f"next: run it from a hordeforge/7dtd-playtest checkout, which owns the client "
        f"lock and the runner:\n  make playtest SUITE={result['suite']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
