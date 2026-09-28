# Contributing

Contributions should preserve the pipeline's proof boundaries and standalone
mod portability.

```bash
scripts/bootstrap
make check test
```

`make help` lists every target. `make stage` re-runs the copy half of the
package build, which is what the packaged-docs and packaged-scripts tests ask
for after a change to `docs/` or to a shipped script.

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

## Where new code goes

`src/sevendtd_asset_pipeline/` is one flat layer of leaf modules, two feature
subpackages, and a thin surface stack. [docs/architecture.md](docs/architecture.md)
states the dependency rules and why each exists; this is where a change lands.

| A change to | Goes in |
|---|---|
| A gate that reads a finished artifact and fails the build | a new `<subject>_check.py`, beside the ones it shares a subject with |
| The bundle the tool writes itself | `bundle_writer.py`, and its shader lane in `shader_blob.py` |
| A reproducible asset | `generators/<name>.py`, then `generators.GENERATORS` |
| An advisory model review, or the evidence either lane records | `providers/`, or the lane module, with the shared half in `evidence.py` |
| A `shamway` subcommand | `cli.py`, unless the command tree is large enough to own its parser (`client.py`, `prompts.py` do) |
| A published operation contract | `operations.OPERATIONS` **and** `api._DISPATCH`; a test fails if the two disagree |
| An optional tool the pipeline probes for | `capabilities.REGISTRY`, with what it unlocks and its install command |
| A page shipped in the package, or a host script | `docs.TOPICS` / `scripts.SCRIPTS`, after the file exists under `docs/` or `scripts/` |
| Editor C# a consuming mod vendors | `templates/UnityProject/`, then `scaffold.PIPELINE_EDITOR_SCRIPTS` |

A new root module is a last resort: the flat layer stays navigable because
there are few of them, and `tests/test_module_graph.py` fails on a cycle, on a
root module reaching into a subpackage, and on a base module
(`errors`, `atomic`, `capabilities`, `workdir`) reaching outside the base layer.

Tests are `tests/test_<module>.py`, one file per module, and they drive the
public entry point rather than a helper — the shipped stdout, a written file, a
raised `PipelineError` — because a test that re-does the logic in the test body
proves nothing about the code that ships.

## Fuzzing the untrusted-input parsers

`tests/test_fuzz.py` holds the property-based harnesses (Hypothesis, a
`dependency-groups` dev entry) for the two parsers that cross a trust
boundary:

| Harness | Input it generates |
|---|---|
| `UnityzReportMappingTests` | `unityz info --json` reports, a separately versioned reader's stdout feeding the class-142 gate |
| `ModReferenceParsingTests` | bundle URIs, tracked manifests, and `ModInfo.xml`, all read out of a modlet this repository did not write |

Each harness asserts the parser is **total**: any input ends as a
`PipelineError` naming what was wrong or a result whose invariants hold, and
anything else is a failure. A fuzzer only proves a bug exists; these assertions
are what turn a lost invariant into a failing test.

The report strategy is structure-aware. Random JSON almost never builds a node
list the reader accepts, which fuzzes the rejection path and never the one the
gate runs on, so `unityz_reports` builds real report shapes and breaks one
field at a time, and the seeds are reports a real bundle produces. Keep it that
way: a strategy biased toward malformed input is a harness that cannot see a
regression in the accepting path.

Every crash artifact becomes a pinned `@example` in the same change, and a
parser that gains a new rejection rule gets the assertion that states it.

```bash
make test TESTS=tests.test_fuzz
```

`make test` is the whole suite, and `TESTS=` narrows it to any dotted unittest
name: a module, a class, or a single case. Empty `TESTS` is the same discovery
run CI makes, so the narrowed form cannot drift from the full one. `make help`
lists every target.

## Building a distribution

`make dist` is the only command that builds the sdist and wheel, and the
release workflow runs it rather than calling `uv build` itself. It is
reproducible: the epoch defaults to the last commit's own date, `TZ` and
`LC_ALL` are pinned so neither a sorted file list nor a formatted name varies
with the host, and `scripts/normalize_dist.py` replaces the sdist's tar
metadata, which is otherwise the build machine's clock and user. `make clean-dist`
removes what the build leaves behind (`build/`, `dist/`, and the staged copies
of `docs/` and `scripts/`).

`make reproducible` builds twice and compares the artifacts byte for byte, and
the second build runs from a copy of the tree at a different absolute path, so
a build that records the directory it was built in fails instead of passing
because both builds shared one. CI runs it on every pull request and the
release workflow runs it before publishing, so a timestamp or a uid reaching a
shipped artifact fails a build rather than being discovered later. Pass
`SOURCE_DATE_EPOCH` to build from something other than a commit (an unpacked
sdist, a shallow copy with no git history); without it and without a commit,
`make dist` fails rather than guessing.

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

`__all__` is snapshotted in `tests/test_release_contract.py`
(`PublicApiTests.PUBLIC_API`), so a name added or dropped there is a deliberate
act. Dropping one is a break: declare it in `[Unreleased]` under `Removed`, in
backticks, then update the snapshot. The suite fails both ways, because an
accidental export or an undeclared removal is what the snapshot exists to catch.
The published operation surface (`shamway schema`) is guarded separately: adding
an operation means adding it to `operations.OPERATIONS` and `api._DISPATCH`, and
the suite fails if the two disagree.

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
