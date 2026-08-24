# Agent instructions

This repository is the reusable asset pipeline for 7 Days to Die modlets. It
is designed to be driven by coding agents, so these rules are the contract.
Read them before inspecting, planning, editing, or testing anything here.

## What this repository is

`shamway` turns editable Unity assets into a validated
`Resources/<name>.unity3d` inside a standalone modlet, and fails loudly on the
silent-corruption modes a plain successful Unity build does not catch. It owns
tooling only. It owns no art, no mod, and no game install.

Read [README.md](README.md) and the relevant page under [docs/](docs/) before
changing behavior. [docs/architecture.md](docs/architecture.md) explains the
trust boundaries; [docs/research/research-provenance.md](docs/research/research-provenance.md)
records where each 7DTD-specific rule came from.

## Working on this repository

This repository lives in the **hordeforge** organization
(`github.com/hordeforge/7dtd-asset-pipeline`), alongside the other `7dtd-*`
projects. Work here goes on a branch and lands through a pull request; nothing
is pushed straight to the default branch.

[docs/sibling-repos.md](docs/sibling-repos.md) indexes the other twelve
repositories and what each owns. Read it before running anything under
`shamway client`: `7dtd-playtest` owns the live-client exclusivity lock those
commands take, and a deploy made while another session holds it lands in that
session's next launch.

### Fix it upstream, do not work around it here

This repository is the generalized extraction of an asset pipeline that grew
inside a mod repository. Its whole reason to exist is that the general thing
lives in one place instead of being re-solved locally. That rule does not stop
at this repository's edge.

**When work here runs into a bug, a missing check, or a confusing default in a
sibling `hordeforge/7dtd-*` repository, fix it there.** Not with a workaround
here, not with a note in a doc, not by telling the user. In that sibling:
branch, fix, add the test that would have caught it, **update that
repository's own documentation**, push, open a pull request, and merge it —
autonomously, the same lifecycle this repository uses. Then come back. A
local workaround for someone else's bug is a second copy of the problem, and
the next project to hit it starts from zero.

This has a track record. `shamway client deploy` was blind to the shared
client lock and deployed into another session's run; `playtest_run.py`
preflighted the dedicated server but not the client, so a caller who exported
the wrong variable waited out a fifteen-minute timeout instead of reading one
error line. Both were fixed where they belonged.

### Never declare an impossibility you did not test

**Do not write "impossible", "cannot", "the wall", "not a temporary gap", or
"nothing offline produces that" unless you ran a check that returned it.** If
no check was run, the only honest phrasing is "I have not checked whether X is
possible". This binds a passing remark in a report exactly as hard as a
conclusion in an ADR, and hardest of all when the sentence is about to be
written into a page the next session will read as settled.

Two failures are the same failure: over-generalizing a positive observation
("it worked here, so it works"), and over-generalizing a negative one ("I
could not find a way, so there is none"). The second is worse, because it
forecloses work rather than merely overstating it, and nobody re-opens a
question the documentation calls closed.

This rule has a scar. On 2026-08-24 this repository's documentation said, in
six places and in an ADR, that a Unity shader "cannot be produced offline,
ever — only Unity's shader compiler produces that". It was false, and the
disproof was already installed on the machine that wrote it:

```bash
which vkd3d-compiler glslangValidator
```

`vkd3d-compiler` (WineHQ, OSS) compiles HLSL to SM4/SM5 **DXBC** — the exact
bytecode Unity's d3d11 sub-programs carry — and `glslangValidator` emits the
SPIR-V the Vulkan sub-programs carry. Two *borrowing* routes had genuinely been
measured closed (the shipped player carries only internal shaders; the game's
own bundles embed theirs same-file), and the report leapt from "cannot borrow
one" to "cannot author one". That does not follow, and it deleted the exact
capability the work had been asked for.

So, concretely, before any such sentence — **both** of these, not either:

1. **Check locally.** Run `which`, a package search, or one probe script, and
   **cite what it returned** in the same paragraph.
2. **Search online, thoroughly.** The local host is not the state of the art;
   an absent tool proves nothing about whether the tool exists. Look for the
   format specification, the open-source implementation, the reverse-
   engineering write-up, the issue thread where someone already did it. Search
   the *format* and the *artifact* by name, not only your framing of the
   problem: "Unity shader sub-program blob format" finds what "can I make a
   shader without Unity" does not. Prior art for reading a format is prior art
   for writing it — every parser is a specification someone already paid for.
   Name the sources you found, and say what you searched if you found nothing.

A local `which` that comes back empty and no search is **not** a check; that
combination is how the shader claim below got written. Off-the-shelf pieces
for this repository's own problems have turned up in Wine, in Khronos, in
HearthSim's game-modding tools and in a decade of Unity reverse-engineering
projects — none of which were installed here, and all of which were one search
away.

Then, when writing it down:

- name the *specific* route measured closed, never the whole problem — "the
  player has no shader a mod may reference" is a finding, "shaders are
  impossible" is not;
- prefer **"unbuilt, and here is the route"** to "impossible". If the route is
  long, that is a cost, and a cost belongs in
  [docs/status/improvements.md](docs/status/improvements.md), not in a page
  that tells the next session to stop;
- if you genuinely could not settle it, write "**not checked**" and say what
  would settle it. That is an honest state; "impossible" is a claim.

An impossibility claim is a gate on future work. It needs the same evidence
this file demands of every other gate.

### Documentation is written while the work happens, never afterwards

Documentation is **not** a step at the end and **not** a follow-up commit. It
is written *during* the change, in the same working session, as each piece
lands — the way a test is. An agent that finishes the code and then goes
looking for the pages to update has already got it wrong, even if it updates
them: by then the reasons are reconstructed rather than recorded, and the
things that were surprising on the way have been forgotten.

In practice that means: when a behaviour changes, stop and write the page
before moving to the next piece of code; when a measurement is taken, write it
into [docs/research/research-provenance.md](docs/research/research-provenance.md)
with the tool that produced it before acting on it; when a route is tried and
rejected, record *why* before trying the next one.

Every behaviour change updates the documentation in the same commit that makes
it — in **whichever** repository the change lands, this one or a sibling. A new
command goes in this file's command table and in the page that owns its
subject; a new operation goes in `operations.OPERATIONS`; a new doc page goes
in `docs.TOPICS` and in its directory's `README.md`; a new host script goes in
`scripts.SCRIPTS`; a new engine fact goes in
[docs/research/research-provenance.md](docs/research/research-provenance.md)
with the tool that produced it. An undocumented capability is one the next session
will rebuild from scratch, and an undocumented gate is one it will delete.

- `scripts/bootstrap` — uv sync from the committed lockfile, with extras
- `make check test` — compile, shellcheck, and the unit suite

```bash
scripts/bootstrap
make check test
```

Use **uv** for every Python step — environments, installs, and runs. Do not
add `pip`, `pipx`, `venv`, or `python -m pip` invocations to scripts, docs, or
CI; `scripts/install-tools.sh` installs uv itself, from the distribution
package or the official checksum-verified release.

`make check test` must pass before you hand work back. It needs no network,
no Unity, and no game install.

- Changes to `unityfs.py` require generated fixtures for **both** acceptance
  and rejection. Never loosen a parser bound to make a real file work without
  first proving what that file actually contains.
- Changes to bundle generation (`build.py`, `BundleBuilder.cs`) require
  `make check test` plus a game-matched `shamway build --probe` when Unity
  is available on the host.
- Changes to the editor-side C# (`GeneratedAsset.cs`, `IconRenderer.cs`,
  `ShamwayPreBuild.cs`, `BundleBuilder.cs`, `BundleVerifier.cs`) are not covered by the Python suite.
  `make check` compiles them against the installed editor's assemblies when
  `mcs` and an editor are present (`scripts/compile-editor-scripts.sh`); run
  that, then state plainly which grade the change reached — compiled, probed,
  or executed by an editor — and never describe a compiled-only change as
  verified.
- Those files (`BundleBuilder.cs`, `BundleVerifier.cs`, `GeneratedAsset.cs`,
  `IconRenderer.cs`, `ShamwayPreBuild.cs`) are what a consuming mod vendors.
  Adding another means adding it to `scaffold.PIPELINE_EDITOR_SCRIPTS`, or an
  adopted project silently will not get it.
- New engine facts need a named source: `Data/Config/*.xml` (and `XML.txt`)
  in the installed game, `ilspycmd`/`monodis` on `Assembly-CSharp.dll`
  (`scripts/install-tools.sh --with-research` installs them), or
  `hordeforge/7dtd-engine-research`. Record which tool produced the fact. "It
  seemed to work in game" is not a source and the next session cannot
  re-verify it; a `strings` hit proves a name exists, not a behaviour.
  Decompiled evidence beats a wiki or a monorepo doc: `Localization.csv` was
  documented in the mod root for a year and the engine reads it from
  `Config/`.
- Keep the consumer scaffold standalone. A modlet built with this pipeline
  must never need a relative checkout of this repository, another mod, or a
  sibling project at build time. That is why the generators and the
  documentation are packaged and reachable as `shamway generate` and
  `shamway docs`: a mod calls them, never copies them. Anything general
  belongs here; anything mod-specific belongs in the mod. See
  [docs/mod-repo-layout.md](docs/mod-repo-layout.md).
- Adding a generator means adding it to `generators.GENERATORS`; adding a doc
  page means adding it to `docs.TOPICS` and to the `README.md` index of the
  directory it lands in. The tests fail when any of those drifts, and the
  first two are published in `shamway schema`.
- `docs/` is categorized: every subdirectory is a genre with its own
  `README.md`, and every genre carries a `TEMPLATE.md` to start a page from — an ADR for a decision made, an RFC for one still open, a
  PRD for behaviour not built yet, a runbook for a recurring procedure, a
  research page for an engine fact, a report for an investigation.
  [docs/README.md](docs/README.md) is the index, served as `shamway docs index`.

## Gates you must not weaken

These exist because each one caught a real failure. Removing one needs
stronger evidence than the evidence that introduced it, recorded in
`docs/research/research-provenance.md`.

| Gate | What it catches |
|---|---|
| class-142 `AssetBundle` object | a container the runtime rejects as incompatible |
| disabled-module log rejection | Unity reporting success while stripping engine classes |
| game-matched Unity revision | an editor that silently produces an unloadable bundle |
| file-stem collision rejection | assets made unreachable by 7DTD's stem-only lookup |
| atlas-cell and `CustomIcon` checks | icons the bundle gates cannot see at all |
| clip format checks | a clip that is stereo, silent, clipping, or DC-offset |
| fresh-client acceptance | everything an offline parse cannot prove |

The offline gates are necessary, not sufficient. Never describe a bundle as
working, verified, or accepted on offline output alone: acceptance always ends
with a fresh client and a human look or listen at the changed asset.

A passing in-client suite does not change that. `shamway acceptance-provider`
generates cases that load every bundle member through the game's own
`DataLoader.LoadAsset<T>` — the strongest mechanical evidence available, and
since 2026-08-24 the proof that the engine reads a synthesized bundle — but
every one of those cases passes on a texture that loads upside down and a clip
at the wrong pitch. **A load is not a look.** Report a green suite as "the game
read it", never as "it works", and say plainly when nobody has yet looked.

The first synthesized bundle to go all the way through makes the point: the
suite reported `pass=3 fail=0`, and what the reviewer added on top was that the
ring was *centred and circular* and the beeps were *clean*. Stretched art and a
crackling clip pass every gate in this repository.

Unity is optional; the gates are not. A mod may declare `bundle_source =
"none"` and ship no bundle, `"external"` and have its bundle built by an editor
on another machine, or `"synthesized"` and have this tool write the bundle with
no editor at all. The gates travel with the artifact in every case: `stage`
prints a `not run:` line for each gate whose evidence (the build log, an
installed game) did not arrive, and a synthesize prints what its gates are
worth when the artifact and the checker share an author. Never drop one of
those lines from a report — an unrun or by-construction gate reads exactly like
a passed one — and **never call a synthesized bundle "built"**: that word
carries a claim about who serialized it.
[docs/bundles/no-unity.md](docs/bundles/no-unity.md) owns those paths and
[docs/adrs/0001-synthesize-bundles-without-an-editor.md](docs/adrs/0001-synthesize-bundles-without-an-editor.md) the writer's
design and its shader wall.

- Changes to `bundle_writer.py` need the same evidence `unityfs.py` does —
  fixtures for acceptance *and* rejection — plus a read-back through UnityPy,
  which parses Unity's format with none of this repository's code. Adding an
  asset class means adding it to `ASSET_KINDS`, giving it a constructor whose
  field values came from a real artifact rather than from a wiki, and saying in
  `docs/research/research-provenance.md` which artifact. Never invent a field layout: a
  class without a type tree for the target revision is refused, deliberately.
- `shamway verify-bundle` is the strongest offline evidence available for a
  synthesized bundle, because it is the engine's own loader. When an editor is
  present, run it and say so; when it is not, say that too. It still proves
  construction, never acceptance.

## Safety rules

- **Never write to a 7 Days to Die install.** It is read-only evidence for the
  Unity revision and engine behavior. The client's per-user data directory
  (`compatdata/251570/pfx/…/AppData/Roaming/7DaysToDie/`) is *not* the
  install: that is where `shamway client deploy` writes, and where a Proton
  client loads mods from.
- **Never launch a client over someone else's.** `shamway client launch`
  refuses while `7DaysToDie.exe` runs; do not work around that. One machine
  has one client, and a reused process proves nothing about a rebuild.
- **Never automate, request, print, log, or commit Unity credentials or
  license data.** Sign-in and activation are user-owned actions.
  `scripts/install-unity-editor.sh` deliberately stops and waits for a human.
- Never commit Unity `Library/`, machine-local paths, copyrighted game assets,
  or third-party assets lacking their license and attribution.
- Commit Unity source assets together with their `.meta` files.
- Do not add `Co-Authored-By` trailers or generated-with tool fluff to commit
  messages or pull-request descriptions.

## Using the pipeline in a mod

Full walkthrough: [docs/getting-started/quickstart.md](docs/getting-started/quickstart.md). The short form:

- `scripts/install-tools.sh --with-unity-prereqs` — host packages
- `scripts/bootstrap` — the CLI

```bash
scripts/install-tools.sh --with-unity-prereqs
scripts/bootstrap
shamway init /path/to/MyMod --game-dir "$SEVEN_DAYS_TO_DIE_DIR"
scripts/install-unity-editor.sh --project /path/to/MyMod/tools/shamway/UnityProject
shamway doctor && shamway build --probe
```

Then, per asset change:

- `shamway build` — build, gate, stage bundle + tracked manifest
- `shamway validate` — bundle and every recursive Config/**/*.xml reference

```bash
shamway build
shamway validate
```

Machine-readable output for agents and CI:

| Command | Contract |
|---|---|
| `shamway doctor --json` | array of `{status, name, detail}`; exit 1 if any `FAIL` |
| `shamway inspect --json BUNDLE` | revision, archive format, class IDs, class-142 flag |
| `shamway unity-release --json` | official editor URL, changeset, and MD5 for a revision |
| `shamway refs` | one `source: uri` line per discovered XML reference |
| `shamway status --json` | whole-mod state; never raises for a mod-state problem |
| `shamway stage BUNDLE` | gate and stage a bundle an editor elsewhere built; lists the gates its evidence could not support |
| `shamway pack SRC OUT` | synthesize a bundle from textures, clips, text files and meshes, with no editor |
| `shamway verify-bundle` | load a bundle in a real Unity runtime; needs an editor, proves construction only |
| `shamway acceptance-provider` | generate the 7dtd-playtest scenario provider that loads every bundle member through the game's own `DataLoader`, in a live client |
| `shamway capabilities --json` | optional capabilities, what they unlock, install commands |
| `shamway inspect --deep --json` | every serialized object and per-prefab components |
| `shamway check-mesh --json` | authored-mesh extents and glTF conformance |
| `shamway check-sound --json` | clip format, level, clipping, DC offset |
| `shamway check-icons --json` | atlas cells and every `CustomIcon` key |
| `shamway render-icon STEM` | render a bundle prefab into its atlas cell, materials and all (needs an editor and a display) |
| `shamway generate mesh-icon MESH PNG` | the same cell from a mesh file through headless Blender: no editor, no display, and a clay render rather than the in-game look |
| `shamway generate --list` | the packaged asset generators, callable from any mod |
| `shamway prompt --list` | the house-style image prompts, rendered with the lane that consumes them |
| `shamway docs [TOPIC]` | this repository's documentation, served from the package |
| `shamway script NAME` | the host scripts (install-tools, install-unity-editor, compile-editor-scripts, playtest-acceptance), served from the package |
| `shamway client where --json` | the client's per-user `Mods/` and `logs/` paths |
| `shamway client deploy MOD` | copy the deployable modlet there (writes outside the install only) |
| `shamway client launch --mod-name NAME` | a genuinely fresh client, then its log classified; refuses a running one |
| `shamway client log --json` | classify the newest client log: positive load lines and silent-failure signatures |
| `shamway client capture LABEL` | record the frame a visual sign-off was made on, and its observable |

Every command exits non-zero with a single `ERROR: ...` line on stderr when a
gate fails. Prefer the exit code over parsing prose.

Do not hardcode the command surface. It is published:

- `shamway schema` — every operation, as JSON
- `shamway call status` — run one, JSON in and out
- `shamway serve` — many, one process, ~17x faster

```bash
shamway schema
shamway call status
shamway serve
```

Each operation declares its `cost`, whether it `writes`, whether it
`needs_config`, and which `capabilities` it needs — so you can decide what is
safe to run before running it. `serve` refuses writing operations unless
started with `--allow-writes`.

In Python, use the `Pipeline` facade rather than assembling the individual
functions:

```python
from sevendtd_asset_pipeline import Pipeline

pipeline = Pipeline.discover()
```

The full contract and JSON shapes are in
[docs/consumer-api.md](docs/consumer-api.md). Adding an operation means adding
it to `operations.OPERATIONS` and `api._DISPATCH`; the tests fail if the two
disagree, which keeps the published schema honest.

## Cost and blast radius

Some steps here are expensive or irreversible. Do not start them speculatively
and never in a loop:

- `scripts/install-unity-editor.sh` downloads several gigabytes and needs an
  interactive desktop for license activation.
- `shamway build` starts a real Unity editor; a cold project import takes
  minutes.
- `shamway build` (without `--probe`), `stage`, and `render-icon` are the only
  commands that write into the modlet, and the first two only after every
  offline gate passes; `client deploy`/`launch` write outside it, and `schema`
  marks all six writers. Use `--probe` for any
  environment question — it never stages anything.

Prefer `doctor`, `inspect`, `refs`, and `validate` when diagnosing. They are
fast, read-only, and need neither Unity nor the network.

## Asset authoring

[docs/authoring/agent-workflows.md](docs/authoring/agent-workflows.md) defines the reproducible
asset-as-code patterns (mesh, texture, icon, audio, VFX lanes) and the evidence
packet a release candidate must carry.
[docs/authoring/authoring-tools.md](docs/authoring/authoring-tools.md) lists the researched
open-source tools and which gate each one belongs to.
[docs/authoring/art-direction.md](docs/authoring/art-direction.md) is the style contract for
generated and drawn 2D assets — read it before writing any generation prompt.
[docs/authoring/audio.md](docs/authoring/audio.md) and [docs/authoring/vfx.md](docs/authoring/vfx.md) own the sound and
particle lanes, including the runtime behaviours that make a correctly built
asset silent or invisible.
[docs/authoring/environment-effects.md](docs/authoring/environment-effects.md) owns weather, fog and
light — the effect no bundle can carry, where every offline gate proves
nothing and a particle-only "environment" is the standard failure.

`shamway generate` ships working generators for the
sound, audio-conversion, cutout, particle-card, icon, texture, mesh, and
mesh-icon lanes, and the
scaffolded Unity project ships `GeneratedAsset.cs` for asset-as-code prefabs,
materials, imports, particles, and audio, plus `IconRenderer.cs`. Extend those
rather than starting a new pattern.

`shamway prompt KIND --subject "..."` renders the art-direction contract as a
ready image-generation prompt — the asset-type line, the key colour, the
negative list, and the commands that consume the model's output. Use it rather
than improvising a prompt; improvising is the specific failure
[docs/authoring/art-direction.md](docs/authoring/art-direction.md) opens with. Adding a prompt kind
means adding it to `prompts.KINDS`, and it is published in `shamway schema`.

The offline gates end at a fresh client and a human look. `shamway client
capture LABEL --observable "..."` files that frame with what it was checked
against, so a sign-off is citable later. It records; it never writes a verdict.

There are **two mesh lanes and both are first-class**: an authored mesh from
Blender or OpenSCAD for organic, rigged, or sculpted geometry, and composed
built-in primitives via `GeneratedAsset.Primitive(...)` for hard-surface props.
Pick by what the shape needs, not by what is installed.

Never guess whether an optional tool is present, and never catch `ImportError`
to find out. Ask the registry:

```bash
shamway capabilities --json
```

```python
from sevendtd_asset_pipeline import has_capability, require_capability
```

Adding an optional dependency means adding it to `capabilities.REGISTRY` with
what it unlocks and its install command, so `doctor`, `status`, the CLI, and
the raised errors all stay in agreement.

Keep generator sources outside the Unity bundle-membership directory; copy only
selected outputs in, so concepts and unused alternatives never ship.
