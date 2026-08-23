"""Render a house-style image-generation prompt, and the lane that follows it.

`docs/art-direction.md` is the style contract, and it is written to be read.
This module is the same contract in executable form, for the case the contract
was written for: an agent in a mod repository that needs a prompt *now* and
would otherwise improvise one.

Improvising is the failure mode the art-direction page opens with. A prompt
missing the asset-type line gets an icon composed like a photograph; one
missing the lighting line gets a cinematic rim-lit product render; one that
asks for a transparent background gets a checkerboard that no cutout can key.
Each clause below is there because its absence produced a reject, so the
skeleton is assembled here rather than recalled:

    shamway prompt item-icon --subject "a rugged wired electrical trigger"
    shamway prompt opacity-mask --subject "a broad smoke-puff cluster"

The output is the prompt to hand to whatever image model the session has, plus
the exact commands that turn its result into a deployable asset. This ships no
image model and picks none — see `docs/art-direction.md`, "Producing the source
image".

What this deliberately does not do is choose the *subject*. A prompt is only as
good as its subject clause and its negative list, and both are the author's
judgement about this particular asset: name the components in order of
importance, and name the specific wrong answer the last candidate produced
(`--avoid "carry handle"`), because generic negatives do not remove a specific
recurring artefact.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from dataclasses import dataclass, field

from .errors import PipelineError

# The key colour is a colour the subject cannot contain, because the cutout
# works by colour distance: a magenta key behind a magenta warning light
# removes the light. `docs/art-direction.md`, "Choosing the key colour".
KEYS: dict[str, tuple[str, str]] = {
    "magenta": ("#ff00ff", "the default: olive, steel, charcoal, earth, yellow subjects"),
    "green": ("#00ff00", "the subject contains magenta, pink, or hot red"),
    "black": ("#000000", "only for a grayscale opacity mask"),
}

DEFAULT_PALETTE = "oxidised olive, charcoal, dirty steel, muted hazard yellow, one faded red accent"

# Negatives every subject attracts. Generative models default to cinematic
# product renders; this list is what pulls them back to a game asset.
COMMON_NEGATIVES = (
    "text",
    "numerals",
    "logos",
    "watermark",
    "UI frame",
    "border",
    "background gradient",
    "lens flare",
    "cinematic treatment",
    "glossy product-render finish",
)

STYLE = (
    "deliberately authored, slightly hand-painted survival-game prop; "
    "worn industrial materials; simplified forms"
)


@dataclass(frozen=True)
class Kind:
    """One prompt shape: what the model is being asked to make."""

    asset_type: str
    """The line that decides perspective. An icon and an albedo make opposite
    choices here, so it is stated first and never left implicit."""

    summary: str
    composition: str
    lighting: str
    readability: str
    default_key: str
    negatives: tuple[str, ...] = ()
    """Negatives specific to this asset type, added to COMMON_NEGATIVES."""

    style: str = STYLE
    """The treatment clause. A surface and a particle are not props, and calling
    them one pulls the model back toward rendering an object."""

    palette_default: str = DEFAULT_PALETTE
    forced_key: str | None = None
    """Set when the asset type only works against one key, as an opacity mask
    only works on pure black."""

    notes: tuple[str, ...] = ()
    lane: tuple[str, ...] = field(default_factory=tuple)
    """The commands that turn the model's output into a deployable asset."""


KINDS: dict[str, Kind] = {
    "item-icon": Kind(
        asset_type="7 Days to Die inventory item icon",
        summary="an inventory icon source, for an atlas cell",
        composition=(
            "high-angle three-quarter view, single centred object, generous padding, "
            "fully contained"
        ),
        lighting="dramatic neutral studio lighting; dangerous industrial mood",
        readability="must read clearly at 160 x 160 pixels",
        default_key="magenta",
        negatives=(
            "scenery",
            "ground plane",
            "horizon",
            "shadow",
            "reflection",
            "loose wires",
            "carry handle or yoke",
            "suitcase shape",
            "extra objects",
        ),
        notes=(
            "Generate three to five narrow candidates, review them at 160 px rather "
            "than at full resolution, keep one, and delete the rest.",
            "Pass the mod's already-approved icons as image references when this is "
            "a sibling of them, so the family stays recognisable as one family.",
        ),
        lane=(
            "shamway generate cutout key assets-src/icons/{stem}-src.png \\\n"
            "    UIAtlases/ItemIconAtlas/{stem}.png --size 160 --pad 0.9 --trim",
            "shamway check-icons",
        ),
    ),
    "block-concept": Kind(
        asset_type="7 Days to Die placed-block concept sheet",
        summary="a concept for a world prop, to model or to derive an icon from",
        composition=(
            "high-angle three-quarter view, single centred object resting level, "
            "generous padding, fully contained"
        ),
        lighting="dramatic neutral studio lighting; dangerous industrial mood",
        readability=(
            "must read clearly as a knee-high ground-placed prop at normal in-world "
            "distance"
        ),
        default_key="magenta",
        negatives=(
            "scenery",
            "ground plane",
            "horizon",
            "shadow",
            "reflection",
            "player character",
            "extra objects",
        ),
        notes=(
            "A concept is reference for the mesh, not the mesh. Decide the two mesh "
            "lanes on what the shape needs: an authored mesh for organic or sculpted "
            "geometry, composed primitives via GeneratedAsset.Primitive for "
            "hard-surface props. See `shamway docs agent-workflows`.",
        ),
        lane=(
            "shamway generate cutout key assets-src/concepts/{stem}-src.png \\\n"
            "    assets-src/concepts/{stem}.png --trim",
        ),
    ),
    "material-albedo": Kind(
        asset_type="7 Days to Die tileable PBR albedo",
        summary="a flat, tileable material sheet, not a picture of an object",
        composition=(
            "perfectly flat orthographic 2D material sheet, square, seamlessly "
            "tileable"
        ),
        lighting=(
            "perfectly even flat lighting, baked into no direction; the surface's own "
            "wear supplies all contrast"
        ),
        readability=(
            "must stay readable on a compact ground-placed prop at normal game distance"
        ),
        default_key="",
        style=(
            "deliberately authored, slightly hand-painted survival-game surface; "
            "worn industrial materials; restrained irregular wear"
        ),
        negatives=(
            "object silhouette",
            "floor",
            "horizon",
            "baked directional lighting",
            "shadows",
            "highlights",
            "reflections",
            "perspective",
            "rendered object",
        ),
        notes=(
            "An albedo source is not a picture of an object. Say so in the prompt, or "
            "the model renders the object.",
            "Derive the normal and packed mask from the albedo rather than generating "
            "them: derived maps stay in register with the albedo for free, and a "
            "hand-authored normal has to be redrawn every time the albedo changes.",
        ),
        lane=(
            "shamway generate texture-maps assets-src/textures/{stem}.png \\\n"
            "    --out-dir assets-src/textures/derived --stem {stem} \\\n"
            "    --metallic 0.58 --smoothness 0.16 \\\n"
            "    --also tools/shamway/UnityProject/Assets/ModAssets/Bundle/Textures",
        ),
    ),
    "particle-card": Kind(
        asset_type="7 Days to Die camera-facing particle card",
        summary="an additive VFX sprite: a flash, a fireball, or a shock ring",
        composition=(
            "exactly one isolated, compact, camera-facing sprite, centred, fully "
            "contained, with empty background around it"
        ),
        lighting="the sprite emits its own light; no external light source",
        style="chunky, camera-facing, slightly hand-painted game-particle forms",
        readability=(
            "must read as one restrained game particle, not as a rendered scene"
        ),
        default_key="magenta",
        negatives=(
            "ground plane",
            "shadow",
            "reflection",
            "smoke column",
            "dust ring",
            "terrain",
            "debris",
            "portal",
            "magic spell",
            "sci-fi HUD",
            "target marker",
        ),
        notes=(
            "Chunky, slightly hand-painted game-particle forms — the negative list "
            "here is doing most of the work, because this subject attracts portals "
            "and HUD rings.",
            "An additive material ignores the card's own alpha for brightness, so the "
            "key must still be cut: a leftover key fringe reads as a coloured halo.",
        ),
        lane=(
            "shamway generate cutout key assets-src/vfx/{stem}-src.png \\\n"
            "    assets-src/vfx/{stem}.png --size 512 --trim",
        ),
    ),
    "opacity-mask": Kind(
        asset_type="7 Days to Die particle opacity mask",
        summary="a grayscale smoke mask on pure black, keyed by brightness not colour",
        composition=(
            "exactly one isolated, irregular cluster, centred, fully contained; a "
            "dense soft centre, varied rounded puffs, a naturally broken lower edge, "
            "a few sparse wisps"
        ),
        lighting=(
            "no lighting; brightness is opacity, ranging from soft mid-grey to white"
        ),
        style="deliberately chunky, slightly hand-painted survival-game texture",
        readability="this is an opacity mask, not a scene",
        default_key="black",
        forced_key="black",
        palette_default="grayscale only; black is reserved for empty background",
        negatives=(
            "colour",
            "landscape",
            "sky",
            "ground plane",
            "fire",
            "embers",
            "debris",
            "shadow",
            "reflection",
            "frame",
            "gradient",
        ),
        notes=(
            "Smoke is the exception to chroma keying: a colour key cannot survive soft "
            "smoke edges, so it is generated as brightness on pure black and converted "
            "to alpha instead.",
            "The black point is what removes a generator's faint background haze "
            "without hardening the puff edges. A card that keeps that haze shows up in "
            "game as a grey rectangle around every particle.",
        ),
        lane=(
            "shamway generate cutout luma assets-src/vfx/{stem}-mask.png \\\n"
            "    assets-src/vfx/{stem}-card.png --black-point 15",
        ),
    ),
}


def kinds() -> list[dict[str, str]]:
    """The prompt kinds, for `--list` and for the published schema."""
    return [
        {"kind": name, "summary": kind.summary, "asset_type": kind.asset_type}
        for name, kind in KINDS.items()
    ]


def _wrap(label: str, value: str, width: int = 78) -> str:
    """One labelled clause, wrapped inside the column the label opens.

    `textwrap.fill` measures the first line from column zero, so the label has
    to be part of that first line rather than prepended to the result — or
    every clause's first line runs a label's width past the margin.
    """
    indent = " " * 14
    return textwrap.fill(
        value, width=width, initial_indent=f"{label + ':':<14}", subsequent_indent=indent
    )


def render(
    kind: str,
    subject: str,
    role: str = "",
    palette: str = "",
    key: str = "",
    avoid: tuple[str, ...] = (),
    stem: str = "myModThing",
) -> dict[str, object]:
    """Build one prompt and the commands that consume its output.

    `subject` and `avoid` are the author's judgement and are never invented
    here; everything else has a house default that is right more often than not.
    """
    try:
        shape = KINDS[kind]
    except KeyError:
        known = ", ".join(KINDS)
        raise PipelineError(f"unknown prompt kind {kind!r}; expected one of: {known}") from None

    if not subject.strip():
        raise PipelineError(
            "a prompt needs a --subject: the shapes, materials and components, in "
            "order of importance. Without one the model picks the subject, and it "
            "picks a cinematic product render."
        )

    chosen = shape.forced_key or key or shape.default_key
    if chosen and chosen not in KEYS:
        known = ", ".join(KEYS)
        raise PipelineError(f"unknown key colour {chosen!r}; expected one of: {known}")
    if shape.forced_key and key and key != shape.forced_key:
        raise PipelineError(
            f"{kind} only works against the {shape.forced_key} key: "
            f"{shape.notes[0] if shape.notes else 'brightness is the alpha channel'}"
        )

    negatives = list(COMMON_NEGATIVES) + list(shape.negatives) + [item for item in avoid if item]
    lines = [
        _wrap("Asset type", shape.asset_type),
        _wrap(
            "Create",
            f"exactly one {subject.strip().rstrip('.')}"
            + (f", {role.strip().rstrip('.')}" if role.strip() else "")
            + ".",
        ),
        _wrap("Style", shape.style),
        _wrap("Composition", shape.composition),
        _wrap("Lighting", shape.lighting),
        _wrap("Palette", (palette or shape.palette_default).strip()),
        _wrap("Readability", shape.readability),
    ]
    if chosen:
        hex_value, _why = KEYS[chosen]
        lines.append(_wrap("Background", f"exactly flat {hex_value}"))
    lines.append(_wrap("Constraints", "no " + ", ".join(negatives) + "."))

    lane = [command.format(stem=stem) for command in shape.lane]
    return {
        "kind": kind,
        "subject": subject.strip(),
        "key": chosen,
        "key_hex": hex_value if chosen else "",
        "prompt": "\n".join(lines),
        "next": lane,
        "notes": list(shape.notes),
    }


def _print(result: dict[str, object]) -> None:
    print(result["prompt"])
    notes = list(result["notes"])
    if notes:
        print()
        for note in notes:
            print(textwrap.fill(note, width=78, initial_indent="- ", subsequent_indent="  "))
    lane = list(result["next"])
    if lane:
        print()
        print("Then, on the image the model returns:")
        print()
        for command in lane:
            # A wrapped command's continuation lines carry their own alignment;
            # indent every line so the block stays one pasteable command.
            print(textwrap.indent(command, "    "))
    print()
    print("Record the model, the exact prompt, the references and the selection")
    print("reason in assets-src/README.md. A prompt is provenance, not acceptance.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="shamway prompt",
        description="Render a house-style image-generation prompt, and the lane that follows it.",
        epilog="The full style contract is `shamway docs art-direction`.",
    )
    parser.add_argument("kind", nargs="?", help="; ".join(KINDS))
    parser.add_argument("--list", action="store_true", help="list the prompt kinds and exit")
    parser.add_argument(
        "--subject",
        default="",
        help="the shapes, materials and components, in order of importance",
    )
    parser.add_argument("--role", default="", help="what it is for, in one clause")
    parser.add_argument("--palette", default="", help="three to five named colours")
    parser.add_argument("--key", default="", choices=["", *KEYS], help="key colour to cut out against")
    parser.add_argument(
        "--avoid",
        action="append",
        default=[],
        metavar="ARTEFACT",
        help="a specific wrong answer the last candidate produced; repeatable",
    )
    parser.add_argument("--stem", default="myModThing", help="asset stem, used in the follow-up commands")
    parser.add_argument("--json", action="store_true", help="machine-readable result")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    if args.list or not args.kind:
        if args.json:
            print(json.dumps(kinds(), indent=2, sort_keys=True))
            return 0
        for entry in kinds():
            print(f"{entry['kind']:18} {entry['summary']}")
        print()
        print('Render one with: shamway prompt KIND --subject "..."')
        return 0

    result = render(
        args.kind,
        subject=args.subject,
        role=args.role,
        palette=args.palette,
        key=args.key,
        avoid=tuple(args.avoid),
        stem=args.stem,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print(result)
    return 0
