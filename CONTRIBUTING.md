# Contributing

Contributions should preserve the pipeline's proof boundaries and standalone
mod portability.

```bash
scripts/bootstrap
make check test
```

Every Python step goes through uv, **in this checkout**. `scripts/bootstrap`
creates `.venv` from `uv.lock`; then `uv run --project . shamway` or
`.venv/bin/shamway`. A worktree bootstraps itself — do not borrow another
clone's `.venv`, and do not run `python3 -m sevendtd_asset_pipeline` from the
system interpreter. `make` uses `uv run` when uv is on PATH and falls back to
the plain interpreter otherwise, because the core has no dependencies and the
suite must pass without the optional capabilities — CI runs it both ways.

`make check` compiles the package, syntax-checks every shell script, runs
`shellcheck` when it is installed, and — when Mono's `mcs` and a Unity 2022.3
editor are on the host — compiles the five vendored editor scripts against
that editor's assemblies (`scripts/compile-editor-scripts.sh`). `make check
test` needs no network, no Unity *running*, and no game install; the editor
compile is opportunistic and skips with a note when it cannot run.

The editor scripts are the opt-in half of this repository — a mod that takes
the default `bundle_source = "synthesized"` never loads one — but they are
still owned here and still gated. An editor-script change comes in three
grades, and the report must say which: compiled (`make check` on a host with
the editor), probed
(`shamway build --probe` ran it), or executed for real (`render-icon`, a
generator, a fresh client). Never describe the first as the third.

## The editorless path is a CI gate, not a claim

"Unity is opt-in" is the kind of statement that rots quietly, because the
machine that would notice usually has an editor on it. So the `scaffold` job in
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) proves it on a hosted
runner that has never had one: it scaffolds a modlet with **no flags**, asserts
no Unity project appeared and that the configuration says `synthesized`,
authors a mesh and a texture into `assets-src/bundle/`, runs `shamway build`
and `shamway validate`, and then fails unless the bundle contains every class
the game resolves —

```text
AssetBundle GameObject Transform MeshFilter MeshRenderer Mesh Material Shader Texture2D
```

That last assertion is the one that matters, and it is not decorative: with no
usable `vkd3d-compiler` it fails with `editorless bundle is missing
['GameObject', 'Material', 'MeshFilter', 'MeshRenderer', 'Shader',
'Transform']`.

The job gates the *other* state too, and gets it for free: Ubuntu packages
vkd3d 1.2, which predates the HLSL support this writer needs, so the runner's
own package exercises the degraded lane. That half asserts the capability
registry reports it unusable **with a reason**, the build still succeeds, the
caveat is printed, and the bundle contains a bare `Mesh` and no prefab. Then a
vkd3d 1.19 built from source (cached) proves the whole chain.

A change that quietly puts an editor back on the default path, that degrades
the prefab lane, or that lets a degraded lane go unmentioned, stops CI rather
than reaching a page nobody re-reads.

Do not weaken that job to make a change pass. It is the only place in this
repository where the absence of Unity is measured rather than asserted.

## Portability

The CLI claims to run on Linux, macOS, and Windows
([docs/getting-started/quickstart.md](docs/getting-started/quickstart.md)); CI exercises Linux and
macOS. The rest of that claim (Windows) rests on construction, not evidence:
no Unix-only module at import time (`PortabilityTests` in tests/test_client.py
simulates Windows' missing `fcntl`), explicit endianness in every binary
format, pathlib instead
of string paths, and [`.gitattributes`](.gitattributes) pinning LF so a
Windows checkout cannot ship CRLF shell scripts through `shamway script`. A
platform absent from CI is asserted, never proven; extend the matrix before
extending the claim.

## Releases

Releases are tag-driven, like the rest of hordeforge: bump `__version__` in
[src/sevendtd_asset_pipeline/_version.py](src/sevendtd_asset_pipeline/_version.py)
(the version's single source; [pyproject.toml](pyproject.toml) reads it
dynamically and holds no second copy), move
[CHANGELOG.md](CHANGELOG.md)'s `[Unreleased]` entries under a `## [X.Y.Z] -
date` heading, land both on `main`, then push a matching `vX.Y.Z` tag. The
release workflow re-runs the suite on the tagged tree, fails if the tag does
not equal `__version__`, and publishes a GitHub Release carrying the sdist,
wheel, and SBOM built from exactly that tree — with that changelog section as
the notes, so a tag without its changelog entry cannot ship.

This project is 0.x: per SemVer, minor bumps may break, and the changelog's
`Changed`/`Removed` entries are where such breaks are declared. The Python API
surface beyond `__all__` in `sevendtd_asset_pipeline/__init__.py` is internal
and may change without notice.

Agent-facing rules live in [AGENTS.md](AGENTS.md) and apply to human
contributors too.

When changing UnityFS parsing, add a generated fixture for both acceptance and
rejection. When changing bundle generation, document which real failure or
engine requirement motivates the change and run a game-matched probe plus a
fresh-client acceptance test before release.

Do not commit Unity `Library/`, credentials, licenses, machine paths,
copyrighted game assets, or third-party assets without their required license
and attribution. Commit Unity source assets with their `.meta` files.

Commit and pull-request messages must not contain `Co-Authored-By` trailers or
tool-generated attribution/badges.
