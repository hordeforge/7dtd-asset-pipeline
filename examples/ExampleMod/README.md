# Example consumer

This directory illustrates the files a mod owns after `shamway init`. No Unity
project appears, because `init` creates none: `bundle_source = "synthesized"`
is the default and this tool writes the `.unity3d` itself.

```bash
shamway init /path/to/real/ExampleMod \
  --game-dir "/path/to/7 Days To Die"
cd /path/to/real/ExampleMod
shamway doctor
shamway build --probe
```

`init` also writes `tools/shamway/AGENTS.md` here — the contract an agent
working in this mod should follow. Point the mod's own `AGENTS.md`/`CLAUDE.md`
at it. Orient at any time with `shamway status --json`; see
[Consumer interfaces](../../docs/consumer-api.md).

`init` also creates `assets-src/`, where editable sources and their provenance
live. Only `assets-src/bundle/` becomes bundle content; everything beside it —
concepts, masks, turntables, full-length audio — stays out, so nothing
unfinished ships by sitting in the wrong place.

Put a mesh named `exampleModWorkbench.glb` in `assets-src/bundle/` and
`shamway build` turns it into the prefab the sample `Config/blocks.xml` asks
for, together with its mesh, material and shader. Build the real bundle before
enabling the sample XML references in `Config/`.

A mod that needs lit or normal-mapped shading, SDCS extras, or particle
modules the `.vfx` schema does not encode opts into an editor with
`shamway init --bundle-source unity`, which
additionally creates `tools/shamway/UnityProject/`; the prefab is then imported
there. See [Running without Unity](../../docs/bundles/no-unity.md).

## The asset classes shown here

| File | What it demonstrates |
|---|---|
| `Config/blocks.xml` | a block `Model` bundle URI |
| `Config/sounds.xml` | a `sounds.xml` `ClipName` bundle URI, which `validate` checks the same way |
| `UIAtlases/ItemIconAtlas/` | where icons go — **not** the bundle; `shamway check-icons` covers them |

- `make -f Makefile.assets assets-validate` — bundle references + atlas icons

```bash
make -f Makefile.assets assets-validate
```
