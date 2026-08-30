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

- Editorless `bundle_source = "synthesized"` now writes named glTF prefab
  hierarchies (including an `armedLamp` child), `SkinnedMeshRenderer` from a
  glTF skin (bind poses, weights, bone-name hashes; never flattened to
  MeshRenderer), and ParticleSystem / ParticleSystemRenderer graphs from a
  versioned `.vfx` declaration, with transparent and additive particle
  shaders that do not reuse the opaque `Shamway/Unlit` pass.

### Changed

- `make check` enables the ruff rule groups the tree already passed
  (debugger leftovers, builtin shadowing, naive datetimes, blanket
  ignores, and the pie/return/raise/logging/version-compare sets) and
  extra mypy codes (bare `# type: ignore`, truthy-bool, possibly-undefined,
  exhaustive-match, and related) plus `strict_bytes` and
  `strict_equality_for_none`.

### Fixed

- Shared-client lock heartbeats are parsed the way `7dtd-playtest` writes
  them (Z, numeric epoch, offset, naive-as-UTC). A `running=yes` record whose
  stamp cannot be read stays held, so a live claim is not overwritten.
- `latest_client_log` accepts a log whose mtime falls in the launch's whole
  second, so a 1-second-resolution filesystem no longer reports "the client
  did not start" for a client that did.
- Capture `captured_at` is the file mtime in UTC regardless of the host
  timezone, including during EDT in `America/New_York`.
- `playtest-capture.sh` times its wait against `/proc/uptime`, so an NTP
  step cannot fire or stall the 900s timeout.
- `doctor` and `build` locate Windows Build Support from the editor binary's
  real assembly root (`Editor/Data` on Linux and Windows, `Unity.app/Contents`
  on macOS) instead of always looking next to the executable.
- Scratch directories honour the host cache directory (`~/Library/Caches` on
  macOS, `%LOCALAPPDATA%` on Windows) when `XDG_CACHE_HOME` is unset.
- The zmol-v search and `install-tools.sh` copy the shared library Zig actually
  emits (`.so` / `.dylib` / `.dll`), not only `libzmolv.so`.
- `render-icon` passes `-force-glcore` only on Linux, where Xvfb needs it;
  macOS and Windows editors keep Metal and D3D11.

## [0.2.0] - 2026-08-26

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
- `make locked`, run by `make check`: fails when `uv.lock` has drifted from
  `pyproject.toml`, which is what every CI job dies on.

### Fixed

- Every CI job had failed at install since the version became dynamic:
  `uv.lock` still recorded a literal `0.1.0` and `uv sync --locked` refused it.
- `make check test` never returned. `test_the_wait_expires_and_names_the_stale_log`
  mocked `time.monotonic` to a constant and `time.sleep` to a no-op, so
  `latest_client_log`'s poll loop spun forever. That file now runs in 0.004s.
- A built wheel shipped stale documentation and host scripts. The sdist
  carried no top-level `docs/` or `scripts/`, so `setup.py`'s staging step
  found nothing and silently kept whatever was already staged in the build
  tree. `MANIFEST.in` grafts the sources and prunes the staged copies, and
  the release workflow now compares the built wheel against the tagged tree.
- The coverage-badge step ran `git remote add origin` outside the `else`
  branch its comment places it in, so it also ran on the clone path, where
  the remote already exists, and failed the step under `set -e`.
- CI ran under the implicit `bash -e`, which has no `pipefail`, so
  `shamway build | tee log` reported `tee`'s exit code and passed on a
  failed build.

### Changed

- Scratch work is staged under `$XDG_CACHE_HOME/shamway` (`~/.cache/shamway`)
  instead of `/tmp`, which is tmpfs on most Linux hosts. This covers the
  decoded WAV, the rasterized sheet, the Blender render, the three shader
  compiles, and the multi-gigabyte editor archive `install-unity-editor.sh`
  downloads. An exported `TMPDIR` is respected.
- The shell scripts and the CI workflow call sibling `.py` helpers instead of
  embedding Python in heredocs and `python -c`, so each file stays one
  language and the CI assertions are linted and type-checked like the rest of
  the tree.

## [0.1.0] - 2026-08-24

Initial tagged release: synthesized UnityFS bundle writing with no editor,
offline gates (revision match, class-142 object, stem collisions, mesh UVs,
clip format, icon atlas), the `shamway` CLI and its JSON operation surface,
and the scaffolded standalone modlet layout.
