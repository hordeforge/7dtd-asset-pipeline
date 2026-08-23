# Example consumer

This directory illustrates the files a mod owns after `7dtd-assets init`.
The full Unity template is omitted here because the CLI creates it.

```bash
7dtd-assets init /path/to/real/ExampleMod \
  --game-dir "/path/to/7 Days To Die"
cd /path/to/real/ExampleMod
7dtd-assets doctor
7dtd-assets build --probe
```

`init` also writes `tools/7dtd-assets/AGENTS.md` here — the contract an agent
working in this mod should follow. Point the mod's own `AGENTS.md`/`CLAUDE.md`
at it. Orient at any time with `7dtd-assets status --json`; see
[Consumer interfaces](../../docs/consumer-api.md).

`init` also creates `assets-src/`, where editable sources and their provenance
live. It is deliberately outside the Unity bundle folder, so nothing
unfinished ships by sitting in the wrong place.

After importing a prefab named `exampleModWorkbench` below the generated
Unity project's `Assets/ModAssets/Bundle/`, build the real bundle before
enabling the sample XML references in `Config/`.

## The asset classes shown here

| File | What it demonstrates |
|---|---|
| `Config/blocks.xml` | a block `Model` bundle URI |
| `Config/sounds.xml` | a `sounds.xml` `ClipName` bundle URI, which `validate` checks the same way |
| `UIAtlases/ItemIconAtlas/` | where icons go — **not** the bundle; `7dtd-assets check-icons` covers them |

```bash
make -f Makefile.assets assets-validate   # bundle references + atlas icons
```
