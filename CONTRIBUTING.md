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

`make check` compiles the package, syntax-checks every shell script, and runs
`shellcheck` when it is installed. `make check test` needs no network, no
Unity, and no game install.

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
