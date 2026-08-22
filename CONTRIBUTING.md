# Contributing

Contributions should preserve the pipeline's proof boundaries and standalone
mod portability.

```bash
scripts/bootstrap
make check test
```

When changing UnityFS parsing, add a generated fixture for both acceptance and
rejection. When changing bundle generation, document which real failure or
engine requirement motivates the change and run a game-matched probe plus a
fresh-client acceptance test before release.

Do not commit Unity `Library/`, credentials, licenses, machine paths,
copyrighted game assets, or third-party assets without their required license
and attribution. Commit Unity source assets with their `.meta` files.

Commit and pull-request messages must not contain `Co-Authored-By` trailers or
tool-generated attribution/badges.
