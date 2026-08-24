# Contributing

Contributions should preserve the pipeline's proof boundaries and standalone
mod portability.

```bash
scripts/bootstrap
make check test
```

Every Python step goes through uv. `make` uses `uv run` when uv is on PATH and
falls back to the plain interpreter otherwise, because the core has no
dependencies and the suite must pass without the optional capabilities — CI
runs it both ways.

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

That last assertion is the one that matters, and it is not decorative: with
`vkd3d-compiler` removed it fails with
`editorless bundle is missing ['GameObject', 'Material', 'MeshFilter',
'MeshRenderer', 'Shader', 'Transform']`. A change that quietly puts an editor
back on the default path, or that degrades the prefab lane, stops CI rather
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

Releases are tag-driven, like the rest of hordeforge: bump `version` in
[pyproject.toml](pyproject.toml), land that on `main`, then push a matching
`vX.Y.Z` tag. The release workflow re-runs the suite on the tagged tree and
publishes a GitHub Release carrying the sdist and wheel built from exactly
that tree. A tag that disagrees with `pyproject.toml` fails the release
instead of publishing a mismatched artifact.

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
