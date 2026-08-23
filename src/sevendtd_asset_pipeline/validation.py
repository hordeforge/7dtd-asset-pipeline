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


def validate_bundle(path: Path, expected_version: str | None = None) -> BundleInfo:
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


def _check_reference(
    config: PipelineConfig,
    reference: AssetReference,
    assets: list[str],
    expected_version: str | None,
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
    bundle = resolve_case_insensitive(config.mod_root, reference.bundle_path)
    if bundle is None:
        raise PipelineError(f"{relative_source}: bundle does not exist: {reference.bundle_path}")
    if bundle.resolve() != config.bundle_output.resolve():
        raise PipelineError(
            f"{relative_source}: URI resolves to {bundle}, but this pipeline owns {config.bundle_output}"
        )
    validate_bundle(bundle, expected_version)
    stems = [Path(asset).stem for asset in assets]
    matches = [stem for stem in stems if stem.casefold() == reference.asset_stem.casefold()]
    if not matches:
        raise PipelineError(
            f"{relative_source}: asset stem {reference.asset_stem!r} is absent from {config.tracked_manifest}"
        )
    if len(matches) != 1:
        raise PipelineError(f"{relative_source}: asset stem {reference.asset_stem!r} is ambiguous")
    if matches[0] != reference.asset_stem:
        raise PipelineError(
            f"{relative_source}: asset case is {reference.asset_stem!r}, manifest has {matches[0]!r}"
        )
    return f"OK {relative_source}: {reference.asset_stem}"


def _check_code_reference(config: PipelineConfig, stem: str, assets: list[str]) -> str:
    """A stem the mod's code loads, held to the same rules as an XML reference."""
    stems = [Path(asset).stem for asset in assets]
    matches = [candidate for candidate in stems if candidate.casefold() == stem.casefold()]
    where = f"{config.config_file.name} code_references"
    if not matches:
        raise PipelineError(f"{where}: asset stem {stem!r} is absent from {config.tracked_manifest}")
    if len(matches) != 1:
        raise PipelineError(f"{where}: asset stem {stem!r} is ambiguous")
    if matches[0] != stem:
        raise PipelineError(f"{where}: asset case is {stem!r}, manifest has {matches[0]!r}")
    return f"OK {where}: {stem}"


def validate_mod(config: PipelineConfig) -> ValidationReport:
    actual_mod_name = read_mod_name(config.mod_root / "ModInfo.xml")
    if actual_mod_name != config.mod_name:
        raise PipelineError(
            f"ModInfo.xml Name is {actual_mod_name!r}, configuration says {config.mod_name!r}"
        )
    expected_version = game_unity_version(config.game_dir)[0] if config.game_dir else None
    validate_bundle(config.bundle_output, expected_version)
    assets = manifest_assets(config.tracked_manifest)
    reject_ambiguous_stems(assets)
    references = discover_references(config.config_dir)
    messages = [_check_reference(config, ref, assets, expected_version) for ref in references]
    messages += [_check_code_reference(config, stem, assets) for stem in config.code_references]
    return ValidationReport(tuple(messages), len(references) + len(config.code_references))
