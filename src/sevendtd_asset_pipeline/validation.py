"""Offline gates for built bundles and mod XML references."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .config import PipelineConfig
from .errors import PipelineError
from .game import game_unity_version
from .references import (
    AssetReference,
    discover_references,
    manifest_assets,
    read_mod_name,
    resolve_case_insensitive,
)
from .unityfs import BundleInfo, inspect_bundle


@dataclass(frozen=True)
class ValidationReport:
    messages: tuple[str, ...]
    reference_count: int


def validate_bundle(
    path: Path, expected_version: str | None = None, info: BundleInfo | None = None
) -> BundleInfo:
    """Gate one bundle, reusing `info` when the caller has already parsed `path`."""
    if info is None:
        info = inspect_bundle(path)
    if expected_version and info.unity_version != expected_version:
        raise PipelineError(
            f"{path.name} uses Unity {info.unity_version}; installed game uses {expected_version}"
        )
    if not info.has_assetbundle_object:
        raise PipelineError(
            f"{path.name} contains no class-142 AssetBundle object; 7DTD will reject it as "
            "not compatible. Ensure Packages/manifest.json includes "
            "com.unity.modules.assetbundle and inspect the build log for disabled modules."
        )
    return info


def reject_ambiguous_stems(assets: list[str]) -> None:
    by_stem: dict[str, list[str]] = defaultdict(list)
    for asset in assets:
        by_stem[Path(asset).stem.casefold()].append(asset)
    collisions = [paths for paths in by_stem.values() if len(paths) > 1]
    if collisions:
        detail = "; ".join(", ".join(paths) for paths in collisions)
        raise PipelineError(f"bundle contains ambiguous file-name stems: {detail}")


def _stem_index(assets: list[str]) -> dict[str, list[str]]:
    """Fold each asset's stem once, so per-reference lookups stop rescanning."""
    index: dict[str, list[str]] = defaultdict(list)
    for asset in assets:
        index[Path(asset).stem.casefold()].append(Path(asset).stem)
    return index


def _check_stem(
    where: str, stem: str, index: dict[str, list[str]], manifest: Path
) -> None:
    matches = index.get(stem.casefold(), [])
    if not matches:
        raise PipelineError(f"{where}: asset stem {stem!r} is absent from {manifest}")
    if len(matches) != 1:
        raise PipelineError(f"{where}: asset stem {stem!r} is ambiguous")
    if matches[0] != stem:
        raise PipelineError(
            f"{where}: asset case is {stem!r}, manifest has {matches[0]!r}"
        )


def _check_reference(
    config: PipelineConfig,
    reference: AssetReference,
    stems: dict[str, list[str]],
    resolved: dict[str, Path | None],
    owned: Path,
) -> str:
    relative_source = reference.source.relative_to(config.mod_root)
    if not reference.is_modfolder:
        raise PipelineError(
            f"{relative_source}: {reference.uri} uses neither '@modfolder:' nor "
            "'@modfolder(Name):'; it targets game bundles, which this pipeline does not own"
        )
    # A bare '@modfolder:' resolves to the mod owning the patch file, which is
    # this mod, so only an explicit name can disagree with the configuration.
    if reference.mod_name is not None and reference.mod_name != config.mod_name:
        raise PipelineError(
            f"{relative_source}: URI names mod {reference.mod_name!r}, expected {config.mod_name!r}"
        )
    # Patch sets routinely hold dozens of URIs aimed at the one staged bundle,
    # so resolution results are shared across the loop instead of re-listing
    # directories per reference.
    if reference.bundle_path not in resolved:
        resolved[reference.bundle_path] = resolve_case_insensitive(
            config.mod_root, reference.bundle_path
        )
    bundle = resolved[reference.bundle_path]
    if bundle is None:
        raise PipelineError(f"{relative_source}: bundle does not exist: {reference.bundle_path}")
    if bundle != owned:
        raise PipelineError(
            f"{relative_source}: URI resolves to {bundle}, but this pipeline owns {config.bundle_output}"
        )
    # The staged bundle was already gated at the top of validate_mod, and the
    # ownership check above proved every reference aims at that same file, so
    # there is nothing left to parse here.
    _check_stem(
        str(relative_source), reference.asset_stem, stems, config.tracked_manifest
    )
    return f"OK {relative_source}: {reference.asset_stem}"


def _check_code_reference(config: PipelineConfig, stem: str, stems: dict[str, list[str]]) -> str:
    """A stem the mod's code loads, held to the same rules as an XML reference."""
    where = f"{config.config_file.name} code_references"
    _check_stem(where, stem, stems, config.tracked_manifest)
    return f"OK {where}: {stem}"


def _validate_bundle_free(config: PipelineConfig) -> ValidationReport:
    """Gate a mod that declares no bundle.

    There is no artifact to parse, so the whole gate is the one mistake this
    configuration makes possible: XML that asks the engine to load an asset out
    of a bundle the mod does not ship. In the client that is a silent load
    failure, not an error the player can act on.
    """
    references = discover_references(config.config_dir)
    if references:
        detail = "; ".join(
            f"{reference.source.relative_to(config.mod_root)}: {reference.uri}"
            for reference in references[:5]
        )
        raise PipelineError(
            f"{config.config_file.name} sets bundle_source = \"none\", but "
            f"{len(references)} XML reference(s) load assets from a bundle: {detail}. "
            "Either remove the references or give the mod a bundle."
        )
    return ValidationReport(
        (f"OK {config.mod_name}: no bundle declared, and no XML asks for one",), 0
    )


def validate_mod(
    config: PipelineConfig,
    *,
    game_version: tuple[str, Path] | None = None,
    bundle_info: BundleInfo | None = None,
    assets: list[str] | None = None,
    references: list[AssetReference] | None = None,
) -> ValidationReport:
    """Gate the whole mod.

    `game_version` and `bundle_info` accept results a caller (such as
    `collect_status`) has already computed for this configuration; both are
    expensive reads that must not run twice in one pass. They must describe
    `config.game_dir`'s answer and a parse of `config.bundle_output`.
    `assets` and `references` are the same kind of hand-off for the tracked
    manifest and the Config/ XML scan, which a status pass has usually already
    read; None means "compute it here", including when a caller's earlier read
    failed and the gate should fail on the same read.
    """
    actual_mod_name = read_mod_name(config.mod_root / "ModInfo.xml")
    if actual_mod_name != config.mod_name:
        raise PipelineError(
            f"ModInfo.xml Name is {actual_mod_name!r}, configuration says {config.mod_name!r}"
        )
    if not config.has_bundle:
        return _validate_bundle_free(config)
    if game_version is not None:
        expected_version: str | None = game_version[0]
    elif config.game_dir:
        expected_version = game_unity_version(config.game_dir)[0]
    else:
        expected_version = None
    validate_bundle(config.bundle_output, expected_version, bundle_info)
    if assets is None:
        assets = manifest_assets(config.tracked_manifest)
    reject_ambiguous_stems(assets)
    stems = _stem_index(assets)
    if references is None:
        references = discover_references(config.config_dir)
    owned = config.bundle_output.resolve()
    resolved: dict[str, Path | None] = {}
    messages = [
        _check_reference(config, ref, stems, resolved, owned) for ref in references
    ]
    messages += [_check_code_reference(config, stem, stems) for stem in config.code_references]
    return ValidationReport(tuple(messages), len(references) + len(config.code_references))
