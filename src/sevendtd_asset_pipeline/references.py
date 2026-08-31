"""7DTD XML asset URI discovery and tracked-manifest parsing."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .errors import PipelineError

BUNDLE_URI = re.compile(r"#[^\s\"'<>]+\?[^\s\"'<>]+")
# 7DTD accepts both tokens; ReadPatchXmlWithFixedModFolders rewrites either.
# Source: hordeforge/7dtd-engine-research docs/mod-loading.md, confirmed
# against the installed Assembly-CSharp.dll string table ('@modfolder(' and
# '@modfolder:').
MODFOLDER = re.compile(r"@modfolder(?:\(([^)]*)\))?:", re.IGNORECASE)


@dataclass(frozen=True)
class AssetReference:
    source: Path
    uri: str
    is_modfolder: bool
    mod_name: str | None
    bundle_path: str
    asset_name: str

    @property
    def asset_stem(self) -> str:
        return Path(self.asset_name.replace("\\", "/")).stem


# A dotted-numeric version, the shape the client and mod managers expect.
VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+){1,2}$")


@dataclass(frozen=True)
class ModInfo:
    name: str
    display_name: str | None = None
    version: str | None = None
    description: str | None = None


def read_mod_info(mod_info: Path) -> ModInfo:
    try:
        # Parses XML from inside the mod being validated, never from the network
        # or a game install; defusedxml would add the first runtime dependency
        # to a zero-dependency core.
        root = ET.parse(mod_info).getroot()  # noqa: S314
    except (OSError, ET.ParseError) as exc:
        raise PipelineError(f"cannot parse {mod_info}: {exc}") from exc
    values: dict[str, str] = {}
    for element in root.iter():
        tag = element.tag.lower()
        if tag in ("name", "displayname", "version", "description") and element.get("value"):
            values[tag] = element.get("value", "").strip()
    if "name" not in values:
        raise PipelineError(f'{mod_info} has no <Name value="..."> element')
    return ModInfo(
        name=values["name"],
        display_name=values.get("displayname"),
        version=values.get("version"),
        description=values.get("description"),
    )


def check_mod_info_schema(mod_info: Path) -> list[str]:
    """`ModInfo.xml` schema problems: Version and Description must be present.

    `validate` already compares `<Name>` with the configuration; this is the
    rest of the schema. A missing or malformed `Version` ships a stale mod
    version that the client logs and the mod manager shows; a missing
    `Description` shows a blank row in the server list. Neither errors anywhere.
    """
    info = read_mod_info(mod_info)
    problems: list[str] = []
    if not info.version:
        problems.append(
            'ModInfo.xml has no <Version value="...">; the client reads it for the mod '
            "version, so a missing one ships a stale/empty version"
        )
    elif not VERSION_RE.match(info.version):
        problems.append(
            f"ModInfo.xml Version {info.version!r} is not a dotted numeric version (e.g. 1.0.0)"
        )
    if not info.description:
        problems.append(
            'ModInfo.xml has no <Description value="...">; the in-game mod list shows a '
            "blank row for it"
        )
    return problems


def read_mod_name(mod_info: Path) -> str:
    return read_mod_info(mod_info).name


def parse_reference(source: Path, uri: str) -> AssetReference:
    body, separator, asset = uri[1:].partition("?")
    if not separator or not asset:
        raise PipelineError(f"{source}: malformed bundle URI {uri!r}")
    match = MODFOLDER.search(body)
    # '@modfolder(Name):' names a mod explicitly; bare '@modfolder:' means the
    # mod that owns the patch file, so an absent group is a self-reference, not
    # an absent modfolder token.
    mod_name = match.group(1) or None if match else None
    bundle_path = MODFOLDER.sub("", body).lstrip("/\\") if match else body
    return AssetReference(source, uri, match is not None, mod_name, bundle_path, asset)


def discover_references(config_dir: Path) -> list[AssetReference]:
    if not config_dir.is_dir():
        return []
    references: list[AssetReference] = []
    for xml_file in sorted(config_dir.rglob("*.xml")):
        try:
            text = xml_file.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            raise PipelineError(f"cannot read {xml_file}: {exc}") from exc
        references.extend(
            parse_reference(xml_file, match.group(0)) for match in BUNDLE_URI.finditer(text)
        )
    return references


def manifest_assets(manifest: Path) -> list[str]:
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
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
