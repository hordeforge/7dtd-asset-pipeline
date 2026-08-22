"""7DTD XML asset URI discovery and tracked-manifest parsing."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .errors import PipelineError

BUNDLE_URI = re.compile(r"#[^\s\"'<>]+\?[^\s\"'<>]+")
MODFOLDER = re.compile(r"@modfolder\(([^)]*)\):", re.IGNORECASE)


@dataclass(frozen=True)
class AssetReference:
    source: Path
    uri: str
    mod_name: str | None
    bundle_path: str
    asset_name: str

    @property
    def asset_stem(self) -> str:
        return Path(self.asset_name.replace("\\", "/")).stem


def read_mod_name(mod_info: Path) -> str:
    try:
        root = ET.parse(mod_info).getroot()
    except (OSError, ET.ParseError) as exc:
        raise PipelineError(f"cannot parse {mod_info}: {exc}") from exc
    for element in root.iter():
        if element.tag.lower() == "name" and element.get("value"):
            return element.get("value", "")
    raise PipelineError(f"{mod_info} has no <Name value=\"...\"> element")


def parse_reference(source: Path, uri: str) -> AssetReference:
    body, separator, asset = uri[1:].partition("?")
    if not separator or not asset:
        raise PipelineError(f"{source}: malformed bundle URI {uri!r}")
    match = MODFOLDER.search(body)
    mod_name = match.group(1) if match else None
    bundle_path = MODFOLDER.sub("", body).lstrip("/\\") if match else body
    return AssetReference(source, uri, mod_name, bundle_path, asset)


def discover_references(config_dir: Path) -> list[AssetReference]:
    if not config_dir.is_dir():
        return []
    references: list[AssetReference] = []
    for xml_file in sorted(config_dir.rglob("*.xml")):
        try:
            text = xml_file.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise PipelineError(f"cannot read {xml_file}: {exc}") from exc
        references.extend(parse_reference(xml_file, match.group(0)) for match in BUNDLE_URI.finditer(text))
    return references


def manifest_assets(manifest: Path) -> list[str]:
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise PipelineError(f"cannot read manifest {manifest}: {exc}") from exc
    assets: list[str] = []
    in_assets = False
    for line in lines:
        stripped = line.strip()
        if stripped == "Assets:":
            in_assets = True
            continue
        if in_assets and stripped.startswith("- "):
            assets.append(stripped[2:].strip())
        elif in_assets and stripped and not line[:1].isspace():
            break
    if not assets:
        raise PipelineError(f"{manifest} lists no Assets")
    return assets


def resolve_case_insensitive(root: Path, relative: str) -> Path | None:
    """Resolve under root as 7DTD does, refusing traversal outside it."""
    current = root.resolve()
    parts = [part for part in relative.replace("\\", "/").split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise PipelineError(f"bundle path escapes the mod root: {relative}")
    for part in parts:
        if not current.is_dir():
            return None
        matches = [child for child in current.iterdir() if child.name.casefold() == part.casefold()]
        if len(matches) > 1:
            raise PipelineError(f"case-insensitive path collision below {current}: {part}")
        if not matches:
            return None
        current = matches[0]
    return current if current.is_file() else None
