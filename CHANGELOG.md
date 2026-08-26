# Changelog

All notable changes to `7dtd-asset-pipeline` are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are
the tags (`vX.Y.Z`) that drive the release workflow.

Releases are tag-driven: bump `__version__` in
[src/sevendtd_asset_pipeline/_version.py](src/sevendtd_asset_pipeline/_version.py),
move this file's `[Unreleased]` entries under the new version heading, land
both on `main`, then push the matching tag. The release workflow fails if a
tag has no changelog section.

## [Unreleased]

### Added

- `acceptance-provider` operation and `shamway acceptance-provider` command:
  generates the 7dtd-playtest scenario provider that loads every bundle member
  through the game's own `DataLoader` in a live client.
- `check-texture` operation (`shamway check-texture`): checks a generated
  texture against what generation actually gets wrong — its mean colour against
  the `material.color` it replaces, compared in sRGB.
- `review-audio` / `review-video` operations (`shamway review-audio`,
  `shamway review-video`): advisory model-assisted semantic review of a clip or
  recording; refuse without explicit network consent and never replace the
  human listen or look.
- `ConfigNotFoundError` in the package's public exports, so scripts can catch
  a missing `.shamway.toml` without catching every pipeline error.

Nothing in this window has been released yet; the newest published version is
0.1.0 below.

## [0.1.0] - 2026-08-24

Initial tagged release: synthesized UnityFS bundle writing with no editor,
offline gates (revision match, class-142 object, stem collisions, mesh UVs,
clip format, icon atlas), the `shamway` CLI and its JSON operation surface,
and the scaffolded standalone modlet layout.
