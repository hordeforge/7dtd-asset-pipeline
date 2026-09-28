"""Offline gates for built bundles and mod XML references."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .config import PipelineConfig
from .engine_classes import block_classes, declared_block_classes
from .errors import PipelineError
from .game import game_unity_version
from .patch_check import check_patches
from .references import (
    AssetReference,
    check_mod_info_schema,
    discover_references,
    manifest_assets,
    read_mod_name,
    resolve_case_insensitive,
)
from .unityfs import BundleInfo, inspect_bundle

# The shape every gate uses to say its evidence did not arrive, and the
# prefix `ValidationReport.skipped` recognises. A gate that cannot run must
# not report a pass, because every other surface here prints `valid: true`
# from the absence of a failure.
NOT_RUN_PREFIX = "not run: "


def expected_revision(config: PipelineConfig) -> str | None:
    """The Unity revision a bundle is gated against, or None if none is known.

    The installed game decides it. Without a game directory the revision
    recorded as `[unity] version` is the next best answer, and it is the same
    one `build` stamps the bundle with (`build.expected_unity_version`), so
    `validate` gates on what `build` produced. Answering None to both left
    every validate route accepting a bundle at a revision the build would
    never have written.
    """
    if config.game_dir:
        return game_unity_version(config.game_dir)[0]
    return config.unity_version or None


@dataclass(frozen=True)
class ValidationReport:
    messages: tuple[str, ...]
    reference_count: int
    skipped: tuple[str, ...] = ()
    """Gates whose evidence did not arrive, each a `not run:` line.

    Also at the head of `messages`, so a caller that prints the report cannot
    miss one; bound separately so a machine-readable surface can publish what
    did not run instead of reporting only what did.
    """


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


def _check_stem(where: str, stem: str, index: dict[str, list[str]], manifest: Path) -> None:
    matches = index.get(stem.casefold(), [])
    if not matches:
        raise PipelineError(f"{where}: asset stem {stem!r} is absent from {manifest}")
    if len(matches) != 1:
        raise PipelineError(f"{where}: asset stem {stem!r} is ambiguous")
    if matches[0] != stem:
        raise PipelineError(f"{where}: asset case is {stem!r}, manifest has {matches[0]!r}")


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
            f"{relative_source}: URI resolves to {bundle},"
            f" but this pipeline owns {config.bundle_output}"
        )
    # The staged bundle was already gated at the top of validate_mod, and the
    # ownership check above proved every reference aims at that same file, so
    # there is nothing left to parse here.
    _check_stem(str(relative_source), reference.asset_stem, stems, config.tracked_manifest)
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
            f'{config.config_file.name} sets bundle_source = "none", but '
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
    # Schema problems are reported, not raised on: a missing Description shows
    # a blank row in the mod list, which is not a reason to refuse a bundle.
    mod_schema = check_mod_info_schema(config.mod_root / "ModInfo.xml")
    class_messages = check_block_classes(config)
    # A Config/ patch XPath that selects zero nodes is a silent no-op in the
    # engine (see research-provenance); the patch gate is part of validate so
    # the default gate catches it, not only `shamway check-patches`. Needs the
    # game dir; without it (or without a stock file) check_patches reports the
    # gap as a note, and a note that never reaches the report reads exactly
    # like a gate that passed.
    patch_report = check_patches(config.mod_root, config.config_dir, config.game_dir)
    if patch_report.problems:
        raise PipelineError("; ".join(patch_report.problems))
    notes = [f"not run: {note}" for note in patch_report.notes]
    if not config.has_bundle:
        report = _validate_bundle_free(config)
        messages = [
            *report.messages,
            *mod_schema,
            *class_messages,
            *notes,
        ]
        # No bundle to gate, so the report keeps the order the gates produced:
        # the first line a caller prints is the one about the mod, and the
        # unrun lines stay bound in `skipped` rather than leading.
        skipped = tuple(line for line in messages if line.startswith(NOT_RUN_PREFIX))
        return ValidationReport(tuple(messages), report.reference_count, skipped)
    not_run: list[str] = []
    if game_version is not None:
        expected_version: str | None = game_version[0]
    elif config.game_dir:
        expected_version = game_unity_version(config.game_dir)[0]
    else:
        # The gate is off in this branch whatever else is true: with no game
        # directory there is no installed revision to hold the bundle's
        # against. Without one, the `[unity] version` the mod's own config
        # records is the next best answer, and it is the same revision `build`
        # stamps (see `expected_revision`), so a bundle built for something
        # else still fails here. That fallback gates the bundle against the
        # revision it was written at, which is not the same gate: nothing here
        # was checked against an installed game, and holding the bundle's
        # revision against the mod's own configuration is not holding it
        # against the installed game, which is what this gate is for and what
        # nothing else here does. It is not evidence the installed game
        # accepts it, and the repository's own rule is that an unrun gate must
        # never read like a passed one, so the line below is emitted whether
        # or not the config recorded a version.
        expected_version = expected_revision(config)
        not_run.append(
            NOT_RUN_PREFIX + "the game-revision gate: no game directory is configured, so the "
            "bundle's Unity revision was not held against the installed game's. Set "
            "SEVEN_DAYS_TO_DIE_DIR."
        )
    validate_bundle(config.bundle_output, expected_version, bundle_info)
    if assets is None:
        assets = manifest_assets(config.tracked_manifest)
    reject_ambiguous_stems(assets)
    stems = _stem_index(assets)
    if references is None:
        references = discover_references(config.config_dir)
    owned = config.bundle_output.resolve()
    resolved: dict[str, Path | None] = {}
    messages = [_check_reference(config, ref, stems, resolved, owned) for ref in references]
    messages += [_check_code_reference(config, stem, stems) for stem in config.code_references]
    messages += mod_schema
    messages += class_messages
    messages += notes
    return _report([*not_run, *messages], len(references) + len(config.code_references))


def _report(messages: list[str], reference_count: int) -> ValidationReport:
    """One rule for what did not run, applied to every message this module emits.

    A gate whose evidence did not arrive says so in the `not run:` shape the
    staging gates use; those lines move to the head of the report so a caller
    that prints `messages` cannot scroll past one, and are bound separately so
    a machine-readable surface publishes the gap rather than reporting only
    what passed.
    """
    skipped = [message for message in messages if message.startswith(NOT_RUN_PREFIX)]
    ran = [message for message in messages if not message.startswith(NOT_RUN_PREFIX)]
    return ValidationReport((*skipped, *ran), reference_count, tuple(skipped))


def check_block_classes(config: PipelineConfig) -> list[str]:
    """Refuse a block whose `Class` names no engine type.

    `Class` is not mod data: the engine resolves it to a C# type named
    `Block<value>`, and one it cannot find aborts the whole XML file. What the
    player then sees is not "one bad block" — it is `blocks.xml` failing to
    parse, `items.xml` failing after it, every save's block ids no longer
    matching, `TileEntityComposite.read` flooding the log, and world load
    ending in a NullReferenceException. Nothing in a bundle gate can see it:
    the URI resolves, the manifest is complete, the prefab loads.

    Returns one line per block checked. A mod that names no `Class` at all is
    the common case and costs nothing.
    """
    declared = declared_block_classes(config.config_dir)
    if not declared:
        return []
    try:
        legal, source = block_classes(config.game_dir)
    except PipelineError as exc:
        # The repository's own rule: an unrun gate must never read like a
        # passed one. This is the `not run:` shape the staging gates use.
        return [f"{NOT_RUN_PREFIX}block Class check ({exc})"]
    unknown = [(block, value, path) for block, value, path in declared if value not in legal]
    if unknown:
        block, value, path = unknown[0]
        near = sorted(name for name in legal if name.lower().startswith(value[:3].lower()))
        suggestion = f" Did you mean one of: {', '.join(near[:5])}?" if near else ""
        raise PipelineError(
            f"{path.name}: block {block!r} sets Class={value!r}, which names no engine class "
            f"(the engine resolves it as Block{value}). Checked against {source}. A block "
            f"with an unresolvable Class makes the engine abort the whole file, so every "
            f"other block in it is lost too.{suggestion} Most model blocks set no Class at all."
        )
    return [f"OK {path.name}: block {block} Class={value}" for block, value, path in declared]
