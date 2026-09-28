"""7DTD XML asset URI discovery and tracked-manifest parsing."""

from __future__ import annotations

import codecs
import functools
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .errors import PipelineError
from .text import folded

BUNDLE_URI = re.compile(r"#[^\s\"'<>]+\?[^\s\"'<>]+")
# 7DTD accepts both tokens; ReadPatchXmlWithFixedModFolders rewrites either.
# Source: hordeforge/7dtd-engine-research docs/mod-loading.md, confirmed
# against the installed Assembly-CSharp.dll string table ('@modfolder(' and
# '@modfolder:').
MODFOLDER = re.compile(r"@modfolder(?:\(([^)]*)\))?:", re.IGNORECASE)

# The tracked manifest's own version marker, and the only one this reader
# implements. Both backends emit it (see `bundle_writer.render_manifest`) and
# `stage` copies an editor-produced one over the tracked file, so a manifest
# written by any of them is read here. A file declaring any other version is
# refused: the `Assets:` block is the only section parsed below, so a
# differently shaped file would otherwise be read as a complete membership
# list out of whatever precedes the first unindented line, and every
# downstream stem, case and reference gate would treat that as authoritative.
MANIFEST_FILE_VERSION = "0"


@dataclass(frozen=True)
class AssetReference:
    source: Path
    uri: str
    is_modfolder: bool
    mod_name: str | None
    bundle_path: str
    asset_name: str

    @functools.cached_property
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


def check_mod_info_schema(mod_info: Path, info: ModInfo | None = None) -> list[str]:
    """`ModInfo.xml` schema problems: Version and Description must be present.

    `validate` already compares `<Name>` with the configuration; this is the
    rest of the schema. A missing or malformed `Version` ships a stale mod
    version that the client logs and the mod manager shows; a missing
    `Description` shows a blank row in the server list. Neither errors anywhere.

    `info` is that same parsed `ModInfo.xml`, for a caller that read it already.
    """
    if info is None:
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


def config_xml_texts(config_dir: Path) -> list[tuple[Path, str]]:
    """Every `Config/**/*.xml` with its text, in a stable order.

    The several gates that read a mod's XML all need the same walk, and every
    file is decoded as its own XML declaration says, because a mod authored on
    a non-English Windows locale can carry a legacy code page rather than
    UTF-8. An absent directory is empty rather than an error: a mod that ships
    no Config has nothing to check.
    """
    if not config_dir.is_dir():
        return []
    texts: list[tuple[Path, str]] = []
    for xml_file in sorted(config_dir.rglob("*.xml")):
        texts.append((xml_file, _read_config_xml(xml_file)))
    return texts


# The XML declaration is what says how a file's bytes are encoded, and it may
# only appear at the very start of the document. Read as bytes, not as text:
# decoding first is the problem.
_XML_DECLARATION = re.compile(rb"""\A\s*<\?xml\s[^>]*?encoding\s*=\s*["']([\w.-]+)["']""")
# `UTF-8` and `utf8` name the same codec, and a BOM in front of either is
# stripped rather than decoded into a leading U+FEFF the regexes would carry.
_UTF8_ALIASES = frozenset({"utf-8", "utf8"})


def _read_config_xml(path: Path) -> str:
    """One Config XML file, decoded as the encoding its own declaration names.

    A hardcoded UTF-8 read fails on a mod whose editor wrote
    `<?xml ... encoding="windows-1252"?>`, which is what an author on a
    non-English Windows locale gets, and it fails on the whole file rather
    than on the one name in it: `validate`, `refs` and `check-localization`
    all stop with "cannot read" instead of reporting that mod's keys. The
    declaration is read from the raw bytes because choosing the decoder is
    what the declaration is for.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read {path}: {exc}") from exc
    declaration = _XML_DECLARATION.match(raw.removeprefix(codecs.BOM_UTF8))
    # No declaration leaves None, and the XML spec's default for that is
    # UTF-8 with a BOM allowed; one that names a UTF-8 alias is the same codec.
    declared = None if declaration is None else declaration.group(1).decode("ascii").lower()
    encoding = "utf-8-sig" if declared is None or declared in _UTF8_ALIASES else declared
    try:
        return raw.decode(encoding)
    except LookupError as exc:
        raise PipelineError(
            f"cannot read {path}: it declares encoding={declared!r}, "
            "which this Python has no codec for"
        ) from exc
    except UnicodeDecodeError as exc:
        raise PipelineError(f"cannot read {path}: {exc}") from exc


def discover_references(
    config_dir: Path, texts: list[tuple[Path, str]] | None = None
) -> list[AssetReference]:
    """Every bundle URI `Config/**/*.xml` asks for.

    `texts` is the hand-off several gates share: a caller that already read
    `Config/` passes it in rather than walking and decoding the tree again.
    """
    references: list[AssetReference] = []
    for xml_file, text in config_xml_texts(config_dir) if texts is None else texts:
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
    version = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("ManifestFileVersion:"):
            version = stripped.partition(":")[2].strip()
        elif stripped == "Assets:":
            in_assets = True
            continue
        elif in_assets and stripped.startswith("- "):
            assets.append(stripped[2:].strip())
        elif in_assets and stripped and not line[:1].isspace():
            break
    if version != MANIFEST_FILE_VERSION:
        raise PipelineError(
            f"{manifest} declares ManifestFileVersion {version or 'none'}; this reader "
            f"implements version {MANIFEST_FILE_VERSION} only, and would read a file of "
            "another shape as a complete membership list"
        )
    if not assets:
        raise PipelineError(f"{manifest} lists no Assets")
    return assets


def resolve_case_insensitive(root: Path, relative: str) -> Path | None:
    """Resolve under root as 7DTD does, refusing traversal outside it.

    Each component is matched folded, so a reference spelled in composed NFC
    finds a file macOS stored decomposed (NFD) and vice versa: two spellings
    of one directory name are one name to every filesystem 7DTD runs on, and
    a byte comparison would report the bundle as absent.
    """
    current = root.resolve()
    parts = [part for part in relative.replace("\\", "/").split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise PipelineError(f"bundle path escapes the mod root: {relative}")
    for part in parts:
        if not current.is_dir():
            return None
        matches = [child for child in current.iterdir() if folded(child.name) == folded(part)]
        if len(matches) > 1:
            raise PipelineError(f"case-insensitive path collision below {current}: {part}")
        if not matches:
            return None
        current = matches[0]
    return current if current.is_file() else None
