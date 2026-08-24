"""The engine class names a mod's XML is allowed to name.

`<property name="Class" value="X" />` on a block does not describe the mod; it
names a **C# type in the game's own assembly**, and the engine resolves it as
`Block` + `X`. A value that names no such type aborts the whole file:

    ERR XML loader: Loading and parsing 'blocks.xml' failed
    EXC Class 'Decoration' not found on block shamwayPropProofBlock!

Everything after that is a cascade — items.xml fails next, the block set no
longer matches any save, `TileEntityComposite.read` floods the log, and world
load ends in a NullReferenceException. The mod looks catastrophically broken
and the cause is one invented word.

None of this is visible to a bundle gate. The URI resolves, the manifest is
complete, the prefab loads. That is why this check exists as its own gate
rather than as a note telling authors to be careful: it was written after an
invented `Class="Decoration"` passed `shamway validate` and was only caught by
reading a live client's log.

The name set comes from the installed game, never from a list maintained here.
A hardcoded set is wrong the first time the engine adds a class, and it would
fail a mod for using something real.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .errors import PipelineError

# `monodis --typedef` lists every type in the assembly, one per line, in a
# format that carries the name among other columns; the names are matched
# rather than parsed positionally so a format change degrades to "found
# nothing" instead of to a wrong answer.
TYPE_NAME = re.compile(r"\b(Block[A-Za-z0-9_]+)\b")
ASSEMBLY = Path("7DaysToDie_Data/Managed/Assembly-CSharp.dll")


def _from_assembly(game_dir: Path) -> set[str] | None:
    """Every `Class` value the engine can resolve, from its own type table.

    Authoritative: the engine looks the type up by name, so the set of types
    named `Block<X>` *is* the set of legal values. Verified against the
    installed game on 2026-08-24 — every one of the `Class` values vanilla's
    own `blocks.xml` uses resolves to a `Block<X>` type, with no exceptions.
    """
    if shutil.which("monodis") is None:
        return None
    assembly = Path(game_dir) / ASSEMBLY
    if not assembly.is_file():
        return None
    try:
        listed = subprocess.run(
            # above, and the same PATH lookup the capability registry gates on.
            ["monodis", "--typedef", str(assembly)],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if listed.returncode != 0:
        return None
    names = set(TYPE_NAME.findall(listed.stdout))
    # A run that returned nothing recognisable is not an empty game; treating
    # it as one would fail every mod that names any class at all.
    if not names:
        return None
    return {name.removeprefix("Block") for name in names if name != "Block"}


def _from_vanilla_config(game_dir: Path) -> set[str] | None:
    """The `Class` values the shipped `blocks.xml` itself uses.

    Weaker than the assembly, and deliberately so: it is what vanilla happens
    to use, not what the engine can resolve, so a real class no vanilla block
    needs is absent from it. Used only when `monodis` is not installed, and the
    caller is told which source answered so a refusal can be read for what it
    is worth.
    """
    config = Path(game_dir) / "Data" / "Config" / "blocks.xml"
    if not config.is_file():
        return None
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    found = set(re.findall(r'name="Class"\s+value="([^"]+)"', text))
    return found or None


def block_classes(game_dir: Path | None) -> tuple[set[str], str]:
    """Legal `Class` values, and the name of the source that produced them.

    Raises when nothing can answer, because a gate that silently accepts
    everything is worse than one that says it could not run.
    """
    if game_dir is None:
        raise PipelineError(
            "no game directory is configured, so block Class values cannot be checked "
            "against the engine's own type table. Set SEVEN_DAYS_TO_DIE_DIR."
        )
    from_assembly = _from_assembly(game_dir)
    if from_assembly is not None:
        return from_assembly, "Assembly-CSharp.dll type table (monodis)"
    from_config = _from_vanilla_config(game_dir)
    if from_config is not None:
        return from_config, "the shipped blocks.xml (monodis absent: vanilla usage only)"
    raise PipelineError(
        f"cannot read block classes from {game_dir}: neither "
        f"{ASSEMBLY} (needs monodis: shamway script install-tools --with-research) "
        "nor Data/Config/blocks.xml could be read"
    )


# `<block name="x">` … `<property name="Class" value="y" />` … `</block>`, so a
# Class inside an item or a recipe is not mistaken for a block's. Non-greedy to
# the next `</block>` keeps one block's properties from bleeding into the next.
BLOCK_BODY = re.compile(r"<block\b[^>]*\bname=\"([^\"]+)\"[^>]*>(.*?)</block>", re.DOTALL)
CLASS_PROPERTY = re.compile(r'name="Class"\s+value="([^"]+)"')


def declared_block_classes(config_dir: Path) -> list[tuple[str, str, Path]]:
    """Every `(block, class, file)` a mod's `Config/**/*.xml` declares."""
    declared: list[tuple[str, str, Path]] = []
    for path in sorted(Path(config_dir).rglob("*.xml")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise PipelineError(f"cannot read {path}: {exc}") from exc
        for block, body in BLOCK_BODY.findall(text):
            for value in CLASS_PROPERTY.findall(body):
                declared.append((block, value, path))
    return declared
