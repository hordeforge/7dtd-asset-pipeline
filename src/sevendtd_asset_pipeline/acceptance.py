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

# Which `LoadAsset<T>` a bundle member is fetched with, and what about it is
# worth asserting once loaded. Keyed by source extension, the same mapping
# `bundle_writer.ASSET_KINDS` uses, so the two cannot disagree about what a
# `.png` becomes.
KIND_SOURCE_ASSERTIONS = {
    "Texture2D": "loaded.width > 0 && loaded.height > 0",
    "AudioClip": "loaded.channels > 0 && loaded.frequency > 0 && loaded.samples > 0",
}

ASSET_CASES: dict[str, tuple[str, str]] = {
    ".png": ("Texture2D", "loaded.width > 0 && loaded.height > 0"),
    ".tga": ("Texture2D", "loaded.width > 0 && loaded.height > 0"),
    ".jpg": ("Texture2D", "loaded.width > 0 && loaded.height > 0"),
    ".wav": ("AudioClip", "loaded.channels > 0 && loaded.frequency > 0 && loaded.samples > 0"),
    ".ogg": ("AudioClip", "loaded.channels > 0 && loaded.frequency > 0 && loaded.samples > 0"),
    ".mp3": ("AudioClip", "loaded.channels > 0 && loaded.frequency > 0 && loaded.samples > 0"),
    ".txt": ("TextAsset", "loaded.text != null"),
    ".json": ("TextAsset", "loaded.text != null"),
    ".csv": ("TextAsset", "loaded.text != null"),
    ".prefab": ("GameObject", "loaded.transform != null"),
    ".fbx": ("GameObject", "loaded.transform != null"),
    ".mat": ("Material", "loaded.shader != null"),
    ".glb": ("Mesh", "loaded.vertexCount > 0 && loaded.triangles.Length > 0"),
    ".gltf": ("Mesh", "loaded.vertexCount > 0 && loaded.triangles.Length > 0"),
    ".obj": ("Mesh", "loaded.vertexCount > 0 && loaded.triangles.Length > 0"),
    ".stl": ("Mesh", "loaded.vertexCount > 0 && loaded.triangles.Length > 0"),
    ".ply": ("Mesh", "loaded.vertexCount > 0 && loaded.triangles.Length > 0"),
    ".jpeg": ("Texture2D", "loaded.width > 0 && loaded.height > 0"),
    ".bmp": ("Texture2D", "loaded.width > 0 && loaded.height > 0"),
}
# The converted lanes: whatever FFmpeg and ImageMagick let into a bundle has
# to be loadable from one too, and this generated the cases rather than a
# hand-written list so the two cannot drift as those tuples grow.
for _kind, _suffixes in (
    ("AudioClip", transcode.AUDIO_SUFFIXES),
    ("Texture2D", transcode.IMAGE_SUFFIXES),
):
    for _suffix in _suffixes:
        ASSET_CASES[_suffix] = (_kind, KIND_SOURCE_ASSERTIONS[_kind])

# Every extension mapped to a kind must assert the same property of it, so the
# case body can look the assertion up by kind instead of re-deriving it per
# bundle member. A disagreement inside ASSET_CASES is an authoring error here,
# not something a provider should resolve by picking one.
KIND_ASSERTIONS: dict[str, str] = {}
for _entry in ASSET_CASES.values():
    agreed = KIND_ASSERTIONS.setdefault(_entry[0], _entry[1])
    if agreed != _entry[1]:
        raise PipelineError(
            f"ASSET_CASES gives {_entry[0]} two different assertions: {agreed!r} and {_entry[1]!r}"
        )

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


def _cs_body(text: str) -> str:
    """Escape a value for embedding inside an existing C# string literal.

    Stems and mod names arrive from a manifest or ModInfo.xml that can be built
    on another machine (`shamway stage` gates exactly such a pair), so they are
    untrusted here: unescaped, a `"` or a newline in a stem terminates the
    literal and the rest of the name compiles as C# inside a provider the live
    client executes.
    """
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


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

    def as_dict(self) -> dict[str, object]:
        return {
            "directory": str(self.directory),
            "assembly": self.assembly,
            "suite": self.suite_id,
            "mod_name": self.mod_name,
            "bundle_uri_path": self.bundle_uri_path,
            "cases": [{"stem": stem, "kind": kind} for stem, kind in self.stems],
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
        entry = ASSET_CASES.get(suffix)
        if entry is None:
            unsupported.append(asset)
            continue
        stems.append((Path(asset).stem, entry[0]))
    if unsupported:
        kinds = ", ".join(sorted(ASSET_CASES))
        raise PipelineError(
            "no load case is defined for " + ", ".join(sorted(unsupported)[:5]) + f"; known "
            f"extensions are {kinds}. Add the extension to acceptance.ASSET_CASES with the "
            "LoadAsset<T> the engine actually uses for it, rather than leaving a bundle "
            "member nobody proves."
        )
    if not stems:
        raise PipelineError(f"{manifest} lists no assets a provider case could load")
    return _rendered_plan(config, mod_root, stems)


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


def _staged_case(prefab_stem: str) -> str:
    """A case that puts the prefab in front of the camera and holds it.

    Every other case here answers *did it load*, and a bundle whose prop is
    invisible passes all of them - which is how a shader that renders nothing
    survived every gate this repository has. `CaseDef.Staged` holds the scene
    and announces itself, so a screenshot loop can photograph the frame and a
    person, or another graphics API, can be compared against it.

    The prefab is instantiated directly rather than placed as a block: the
    question is whether *this bundle's* renderer draws, and a block adds the
    game's own placement, rotation and collision on top of the thing under
    test.
    """
    name = _cs_body(prefab_stem)
    variable = _identifier(prefab_stem)
    return f"""
        GameObject {variable}Staged = null;
        queue.Add(CaseDef.Staged(label, "look_{name}", new[] {{ "capture", "bundle" }},
            stage: ctx =>
            {{
                var prefab = DataLoader.LoadAsset<GameObject>(Bundle + "?{name}");
                if (prefab == null)
                {{
                    Report.Info("{name}: LoadAsset<GameObject> returned null; nothing to stage");
                    return false;
                }}
                var player = ctx == null ? null : ctx.Player;
                if (player == null)
                {{
                    Report.Info("{name}: no local player, so there is no camera to stage in front of");
                    return false;
                }}
                // An arm's length ahead and at eye height, so the frame is the
                // prop rather than the ground it would otherwise sit on.
                var eye = player.position + Vector3.up * 1.6f;
                var ahead = player.transform.forward;
                {variable}Staged = UnityEngine.Object.Instantiate(prefab);
                {variable}Staged.transform.position = eye + ahead * 1.2f;
                {variable}Staged.transform.rotation =
                    Quaternion.LookRotation(-ahead, Vector3.up);
                var renderers = {variable}Staged.GetComponentsInChildren<Renderer>(true);
                Report.Info("{name}: staged at " + {variable}Staged.transform.position
                    + " with " + renderers.Length + " renderer(s)");
                // A prefab with no renderer cannot be photographed into evidence.
                return renderers.Length > 0;
            }},
            holdSeconds: 12f,
            fail: "could not stage {name} in front of the camera"));
"""


def render(plan_: ProviderPlan) -> dict[str, str]:
    """The provider's files, as `filename -> text`."""
    cases = "".join(_case(stem, kind) for stem, kind in plan_.stems)
    # One staged frame per prefab: the only case here that can fail on a bundle
    # whose every member loads and whose prop is invisible.
    cases += "".join(_staged_case(stem) for stem, kind in plan_.stems if kind == "GameObject")
    mod_name = _cs_body(plan_.mod_name)
    source = _template("AcceptanceProvider.cs.in").format(
        MOD_NAME=mod_name,
        CLASS_NAME=f"{plan_.assembly}Provider",
        SUITE_ID=plan_.suite_id,
        BUNDLE_URI_PATH=_cs_body(plan_.bundle_uri_path),
        CASES=cases,
        ABSENT_STEM=ABSENT_STEM,
    )
    project = _template("AcceptanceProvider.csproj.in").format(
        MOD_NAME=_comment_text(plan_.mod_name), ASSEMBLY_NAME=plan_.assembly
    )
    mod_info = (
        '<?xml version="1.0" encoding="UTF-8" ?>\n<xml>\n'
        f'\t<Name value="{_xml_attr(plan_.assembly)}" />\n'
        f'\t<DisplayName value="{_xml_attr(plan_.mod_name + " bundle acceptance")}" />\n'
        '\t<Description value="Generated 7dtd-playtest scenario provider: loads every '
        "bundle member through the game's own DataLoader.\" />\n"
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
