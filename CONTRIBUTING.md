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
editor are on the host — compiles the four vendored editor scripts against
that editor's assemblies (`scripts/compile-editor-scripts.sh`). `make check
test` needs no network, no Unity *running*, and no game install; the editor
compile is opportunistic and skips with a note when it cannot run.

An editor-script change therefore comes in three grades, and the report must
say which: compiled (`make check` on a host with the editor), probed
(`shamway build --probe` ran it), or executed for real (`render-icon`, a
generator, a fresh client). Never describe the first as the third.

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
