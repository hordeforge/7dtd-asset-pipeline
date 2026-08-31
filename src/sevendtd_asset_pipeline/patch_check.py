"""Offline gate for the silent half of XML patch application.

The engine applies a mod's `Config/<stem>.xml` to the matching
`Data/Config/<stem>.xml` through `ModManager.XmlPatcher`. A structural
operation (`append`/`prepend`/`set`/`setattribute`/`remove`/`removeattribute`/
`insertafter`/`insertbefore`) whose XPath selects **no node** is a **silent
no-op** — `XmlFile.GetXpathResultsInList` returns false on a zero-count list and
the operation returns 0 with no error and no log line (see
`docs/research/research-provenance.md`, "Config XML patch application"). So a
typo'd attribute name or a renamed parent ships with the patch simply not
applied, and nothing anywhere says so. This gate runs the same selectors
against the installed game's read-only `Data/Config` copy and fails the ones
that would apply to zero nodes.

It uses the standard library's XPath subset (`xml.etree.ElementTree.findall`),
which covers the descendant/attribute/predicate selectors mod patches actually
use. An XPath the subset cannot evaluate is reported as **not checked** rather
than guessed, so the gate never claims a verdict on a selector it could not run.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

from .errors import PipelineError

# Structural operations that silently no-op on a zero-match XPath. (Conditional
# and Include have no xpath of their own; Conditional nests real operations.)
STRUCTURAL_OPS = frozenset(
    {
        "append",
        "prepend",
        "set",
        "setattribute",
        "remove",
        "removeattribute",
        "insertafter",
        "insertbefore",
    }
)


@dataclass
class PatchReport:
    checked: tuple[str, ...]
    resolved: tuple[str, ...]  # xpaths that matched >= 1 node
    problems: list[str]
    notes: list[str]

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict[str, object]:
        return asdict(self) | {"ok": self.ok}


def _iter_patch_operations(root: ET.Element) -> Iterator[tuple[str, str]]:
    """Yield (operation_name, xpath, path) for every structural op with an xpath."""
    for element in root.iter():
        name = element.tag.lower()
        xpath = element.get("xpath")
        if name in STRUCTURAL_OPS and xpath:
            yield name, xpath


def _evaluate(target_root: ET.Element, xpath: str) -> int:
    """How many nodes `xpath` selects in the stock target, or -1 if unevaluable."""
    xpath = xpath.strip()
    try:
        if xpath.startswith("//"):
            # Pure descendant search. ElementTree rejects a leading '//' on an
            # element ('cannot use absolute path on element'); the relative
            # './/' form is the same descendant axis and supports predicates.
            return len(target_root.findall("." + xpath))
        if xpath.startswith("/"):
            # Absolute path, rooted at the document element. '/a' is the root
            # itself (1 node if a == root.tag); '/a/b[c]' walks a's children.
            segments = [seg for seg in xpath[1:].split("/") if seg]
            if len(segments) == 1:
                return 1 if target_root.tag == segments[0] else 0
            if target_root.tag != segments[0]:
                return 0
            nodes = [target_root]
            for segment in segments[1:]:
                nxt: list[ET.Element] = []
                for node in nodes:
                    nxt.extend(node.findall("./" + segment))
                nodes = nxt
                if not nodes:
                    return 0
            return len(nodes)
        # Relative path (rare for a mod patch): ElementTree resolves it from the
        # root's children.
        return len(target_root.findall(xpath))
    except (ET.ParseError, SyntaxError, ValueError):
        return -1


def check_patches(
    mod_root: Path,
    config_dir: Path | None = None,
    game_dir: Path | None = None,
) -> PatchReport:
    """Fail every mod patch XPath that would select zero nodes in the stock file."""
    config = Path(config_dir) if config_dir else Path(mod_root) / "Config"
    checked: list[str] = []
    resolved: list[str] = []
    problems: list[str] = []
    notes: list[str] = []

    if game_dir is None:
        notes.append("no game directory; patch XPaths were not checked against the stock configs")
        return PatchReport(tuple(checked), tuple(resolved), problems, notes)

    stock_dir = Path(game_dir) / "Data" / "Config"
    if not stock_dir.is_dir():
        notes.append(f"no stock Config directory at {stock_dir}; patches were not checked")
        return PatchReport(tuple(checked), tuple(resolved), problems, notes)

    if not config.is_dir():
        return PatchReport(tuple(checked), tuple(resolved), problems, notes)

    for patch_file in sorted(config.rglob("*.xml")):
        stem = patch_file.stem
        target = stock_dir / f"{stem}.xml"
        if not target.is_file():
            notes.append(f"{patch_file.name}: no stock {stem}.xml to patch it against; not checked")
            continue
        target_root = _parse_xml(target, patch_file)
        patch_root = _parse_xml(patch_file, patch_file)
        # The patch file's children ARE the operations. The root tag of a mod
        # patch is usually '<configs>'; the engine applies each child element.
        for operation, xpath in _iter_patch_operations(patch_root):
            checked.append(xpath)
            count = _evaluate(target_root, xpath)
            if count < 0:
                notes.append(
                    f"{patch_file.name}: cannot evaluate XPath {xpath!r} with the "
                    "standard-library subset; not checked"
                )
            elif count == 0:
                problems.append(
                    f"{patch_file.name}: {operation} XPath {xpath!r} selects 0 nodes in "
                    f"{target.name}. The engine silently no-ops a zero-match XPath "
                    "(GetXpathResultsInList returns false, the operation returns 0), so "
                    "this patch is not applied and nothing reports it. Check the selector "
                    "against the stock file."
                )
            else:
                resolved.append(xpath)
    return PatchReport(tuple(checked), tuple(resolved), problems, notes)


def _parse_xml(path: Path, source: Path) -> ET.Element:
    try:
        return ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise PipelineError(f"cannot parse {source}: {exc}") from exc
