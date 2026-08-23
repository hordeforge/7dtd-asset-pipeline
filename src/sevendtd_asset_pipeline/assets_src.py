"""The editable-source tree a mod gets, and the provenance it must record.

The bundle is a build output. Everything that produced it — a prompt, a seed, a
Blender script, an ImageMagick command — is the actual source, and if it lives
only in someone's shell history the asset cannot be regenerated, corrected, or
defended. So `shamway init` creates a home for it with a README that says
what belongs in each lane and what a provenance row has to carry.

This directory is deliberately *outside* the Unity bundle-membership folder.
Concepts, rejected alternatives, masks, turntables and full-resolution sources
stay here; only selected outputs are copied into the Unity project, so nothing
unfinished can ship by being in the wrong folder.
"""

from __future__ import annotations

from pathlib import Path

LANES = {
    "icons": "atlas icons: generated or drawn sources, and the cut-out RGBA derivative",
    "textures": "albedo, normal, and packed mask sources for materials",
    "meshes": "Blender/OpenSCAD scripts and their exported .glb",
    "audio": "sound generators and their .wav output",
    "vfx": "particle card sources and opacity masks",
}

README = """# Editable asset sources for {mod_name}

Nothing in this directory ships. It holds the sources, generators, and
provenance behind the assets that do: the deployable artifacts are the bundle
at `Resources/{bundle_name}`, the PNGs under `UIAtlases/`, and nothing else.

Keep it this way round on purpose. Concepts, rejected alternatives, masks,
turntables and full-resolution sources live here; only a *selected* output is
copied into `tools/shamway/UnityProject/Assets/ModAssets/Bundle/`, so an
unfinished asset cannot ship merely by sitting in the wrong folder.

## Layout

| Directory | What belongs in it |
|---|---|
{lane_rows}

## Every asset owes a provenance row

Add one row per asset to the table below when you add the asset. An entry that
cannot be regenerated from what is written here is not finished.

| Asset | Source | How it was made | Deployed as | Reviewed |
|---|---|---|---|---|
| _example_ | `icons/nuke-v4.png` | image generation, prompt below; cut out with `shamway generate cutout key --size 160` | `UIAtlases/ItemIconAtlas/myModNuke.png` | not yet |

For generated art, record the model or tool, the **exact prompt**, the
references used, which candidate was selected and why, and the licence basis.
A prompt is provenance, not acceptance evidence — it says where the pixels came
from, never that they are good. `shamway prompt KIND --subject "..."` renders
the house pattern to start from; record what you actually sent, not the
template, because the subject and the negatives are what you changed.

For generated audio, meshes, and textures, the generator script *is* the
provenance: record the command and its `--seed`. Re-running it must reproduce
the file byte-for-byte, so a diff means someone changed the design.

## The commands

Nothing here is a copy of the pipeline. Author with its generators and read its
rules through the command itself — there is no checkout of it to point at:

- `shamway generate --list` — the generators, and what each needs
- `shamway prompt --list` — the house-style image prompts, rendered ready to use
- `shamway docs art-direction` — the style contract and prompt patterns
- `shamway docs audio` — the sound lane
- `shamway docs mod-repo-layout` — what belongs here vs in the pipeline

```bash
shamway generate --list
shamway prompt --list
shamway docs art-direction
shamway docs audio
shamway docs mod-repo-layout
```

```bash
shamway generate sound blast audio/thing.wav --seed 7 \
    --promote ../tools/shamway/UnityProject/Assets/ModAssets/Bundle/Sounds/myModThing.wav
shamway generate cutout key icons/src.png ../UIAtlases/ItemIconAtlas/thing.png \
    --size 160 --pad 0.9 --trim
shamway generate texture-maps textures/paint.png --out-dir textures/derived --stem myModPaint \
    --also ../tools/shamway/UnityProject/Assets/ModAssets/Bundle/Textures
shamway generate mesh meshes/thing.glb --shape box --size 1 0.6 0.8
```

Promote from the generator (`--promote`, `--also`), never by copying by hand:
the bundle copy is then the recorded design by construction.

Then gate each lane, build, and validate — from the mod root:

- `shamway capabilities --json` — what is installed, and what it unlocks
- `shamway check-icons` — every atlas PNG and CustomIcon key
- `shamway render-icon myModThing` — photograph a prefab into an icon

```bash
shamway capabilities --json
shamway check-mesh assets-src/meshes/thing.glb
shamway check-sound assets-src/audio/thing.wav
shamway check-icons
shamway render-icon myModThing
shamway build && shamway validate
```

Then a fresh client, and a human look or listen. Offline gates are necessary,
never sufficient:

```bash
shamway client deploy .
shamway client launch --mod-name {mod_name} --run-seconds 120 --mute
```

A listening run is never `--mute`. Record in the provenance row which of the
two a person did.
"""


def render_readme(mod_name: str, bundle_name: str) -> str:
    rows = "\n".join(f"| `{name}/` | {purpose} |" for name, purpose in LANES.items())
    return (
        README.replace("{mod_name}", mod_name)
        .replace("{bundle_name}", bundle_name)
        .replace("{lane_rows}", rows)
    )


def create(mod_root: Path, mod_name: str, bundle_name: str, directory: str = "assets-src") -> Path:
    """Create the source tree, leaving any existing content untouched."""
    root = mod_root / directory
    root.mkdir(parents=True, exist_ok=True)
    for lane, purpose in LANES.items():
        lane_dir = root / lane
        lane_dir.mkdir(exist_ok=True)
        keep = lane_dir / ".gitkeep"
        if not keep.exists():
            keep.write_text(f"# {purpose}\n", encoding="utf-8")
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(render_readme(mod_name, bundle_name), encoding="utf-8")
    return root
