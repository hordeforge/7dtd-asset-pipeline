# Running without Unity

## Where Unity actually enters

Of everything this pipeline does, only two operations *can* start a Unity
editor: `build` — and only when the mod asks for it — and `render-icon`. Every other command — `status`, `doctor`, `refs`,
`validate`, `inspect` (including `--deep`), `check-mesh`, `check-sound`,
`check-icons`, `generate`, `prompt`, `docs`, `stage`, and the whole `client`
family — is Python reading files, and always ran on a machine with no editor
and no game.

So the real question is never "can I use shamway without Unity". It is **where
the `.unity3d` comes from**, or whether the mod needs one at all. That has four
answers, and the configuration states which one applies:

| `bundle_source` | Where the bundle comes from | Needs an editor here |
|---|---|---|
| `unity` (default) | a local editor builds it: `shamway build` | yes |
| `synthesized` | this tool writes it directly: `shamway build`, seconds, no editor | no |
| `external` | an editor elsewhere builds it; this host gates and stages it: `shamway stage` | no |
| `none` | nowhere: the mod ships no bundle | no |

Three questions decide it:

1. Does any XML ask the engine to load an asset out of a bundle — a
   `Meshfile`, a block `Model`, a `sounds.xml` `ClipName`, an XUi mesh? If not,
   the mod needs no bundle: `none`.
2. Is everything in that bundle a texture, a sound or a text file? Then
   `synthesized` writes it here, with no editor and no project.
3. Otherwise the bundle contains a mesh, a prefab, a material or a shader, and
   an editor has to serialize it: `unity` if one lives on this machine,
   `external` if it lives on another.

The rest of this page takes them in that order.

## A mod with no bundle

A 7 Days to Die modlet does not have to contain a bundle. These ship as loose
files and the engine reads them directly:

- `Config/**/*.xml` — every XPath patch;
- `UIAtlases/<AtlasName>/<name>.png` — item icons, packed into a runtime atlas
  by folder name (see [game-integration.md](game-integration.md));
- `Config/Localization.csv`;
- a Harmony DLL at the mod root.

Only a `#@modfolder(...):Resources/<name>.unity3d?<stem>` URI needs a bundle,
and that is what `DataLoader.LoadAsset<T>` resolves for meshes, prefabs,
materials and clips. An item that reuses a vanilla mesh, retunes vanilla
values, and ships its own icon involves no Unity anywhere.

Scaffold that mod with no game install, no editor and no network:

```bash
shamway init /path/to/MyMod --bundle-source none
```

No Unity project is created, no editor script is vendored, no revision is
pinned, and `Makefile.assets` has no build targets — a target that can only
fail teaches whoever runs it to stop trusting the file. The
`tools/shamway/AGENTS.md` written into the mod says the same in its first
paragraph, so an agent arriving cold does not go looking for a bundle.

What the gates do in this mode:

- `doctor` reports the bundle source and stops. There is no Unity row to fail
  and no standing warning about an editor the mod does not use.
- `validate` checks the one mistake this configuration makes possible: XML that
  loads an asset from a bundle the mod does not ship. In the client that is a
  silent load failure, not an error a player can act on, so it is a hard
  rejection here.
- `status` reports `bundle_source`, and `bundle_path`, `bundle_name` and
  `manifest_path` as `null` rather than as missing files.
- `check-icons`, `generate icon`, `generate cutout` and the whole art-direction
  lane work unchanged. `render-icon` is the one icon command that needs an
  editor, because it photographs a bundle prefab; a bundle-free mod draws or
  generates its icons instead.

### Adding a bundle later

There is no in-place upgrade command. `init` refuses to overwrite what it
generates, which is what makes it safe to run, so move the generated files
aside and scaffold again with the flags you want:

```bash
cd /path/to/MyMod
mv .shamway.toml .shamway.toml.bak
mv Makefile.assets Makefile.assets.bak
mv tools/shamway/AGENTS.md tools/shamway/AGENTS.md.bak
shamway init . --game-dir "$SEVEN_DAYS_TO_DIE_DIR"
```

Then re-apply whatever you had edited into the old files — `code_references`,
mod-specific agent rules — and delete the backups. `assets-src/` and
`UIAtlases/` are left alone by a second `init`; nothing you authored is lost.

## A bundle this tool writes itself

`bundle_source = "synthesized"` removes Unity from the build entirely. There is
no project, no editor, no batch-mode run: `shamway build` reads a folder of
source files and writes the `.unity3d` in milliseconds.

```bash
shamway init /path/to/MyMod --bundle-source synthesized --game-dir "$SEVEN_DAYS_TO_DIE_DIR"
```

That scaffolds `assets-src/bundle/`, and every file you put there becomes one
asset, named by its file stem — the name 7DTD's URIs ask for:

| Source file | Becomes | Loaded as |
|---|---|---|
| `myModPanel.png` | `Texture2D`, RGBA32, uncompressed | `LoadAsset<Texture2D>` |
| `myModBlast.wav` | `AudioClip`, 16-bit PCM in an FSB5 bank | `sounds.xml`, `LoadAsset<AudioClip>` |
| `myModData.json`, `.txt`, `.csv` | `TextAsset` | `LoadAsset<TextAsset>` |

```bash
shamway build
shamway validate
```

A file the writer cannot make is **named and refused**, never skipped: a source
file nobody built is exactly the silence this pipeline exists to remove.

### What it writes, and how that was established

The writer emits the structure a real Unity build emits, and each piece of it
was read out of a real artifact rather than guessed:

- the UnityFS container — format 8, the game's own revision string, block
  table, `CAB-<hash>` directory node — read from the bundles the installed game
  ships;
- a SerializedFile version 22 with **type trees written**, because the game's
  own bundles carry them;
- each object serialized by walking that class's own type tree for the exact
  revision, taken from UnityPy's per-version database. A type tree *is* the
  engine's field layout; nothing here guesses one, and a class without one is
  refused;
- the class-142 `AssetBundle` object, with the `m_Container` table that makes
  each asset reachable by name and the `m_RuntimeCompatibility` and
  `m_PathFlags` values Unity's own container carries;
- for audio, an FSB5 bank in a `.resource` stream beside the serialized file,
  because an `AudioClip` holds no samples — it holds an offset into a bank FMOD
  reads. The bank's layout was read out of the `.resource` stream of a bundle
  this repository's editor built from the same WAV.

Provenance for each of those is in
[research-provenance.md](research-provenance.md); the design record, the prior
art surveyed, and what is not attempted are in
[offline-bundle-builder.md](offline-bundle-builder.md).

### What it cannot write, and why that is not a temporary gap

Meshes, prefabs, materials and shaders still need an editor. The blocker is
specifically the **shader**: a material references one, and a shader in a
bundle is compiled platform bytecode produced by Unity's shader compiler. No
offline writer can produce that, so a prefab whose renderer has no valid shader
renders magenta in the client — a failure no offline gate can see. A mod with a
mesh or a prefab therefore uses `unity` or `external`; both are unchanged and
neither is second-class.

The `Mesh` object itself is writable in principle, and
[offline-bundle-builder.md](offline-bundle-builder.md) records the
clone-and-patch idea that could reach materials one day. Neither is built,
because a half-built prefab lane is worse than none.

### The gates say what they are worth

Every offline gate still runs, and one of them changes meaning. When the
artifact and its checker have the same author they cannot cross-examine each
other, so `build` prints exactly that, every time:

```text
note: the class-142 container gate ran against this tool's own output, so here it
      is structural, not independent evidence that the engine accepts the container
note: the stem-collision gate read the membership record this build wrote, for the
      same reason
note: the build-log gate cannot run: there is no editor to report stripping an
      engine module while claiming success
note: a fresh client is therefore the acceptance for a synthesized bundle rather
      than a confirmation of it
```

The revision gate is unaffected: it compares the bundle's revision with the
installed game's, and rejects a writer aimed at the wrong engine.

The reports never say a synthesized bundle was *built*. They say
**synthesized**, because "built" carries a claim about who serialized it.

### The check that is not self-graded

When an editor *does* exist — on a build host, on a developer's machine, in a
container — it can be used as a **verifier** instead of a builder. That is the
inversion this backend allows:

```bash
shamway verify-bundle
```

It creates a throwaway project under `.shamway/build/verify/`, calls
`AssetBundle.LoadFromFile` — the same call the game makes — and loads every
asset with the engine's own class definitions, reporting type, name, texture
format, and a clip's decoded channel count, frequency and sample count. It also
checks that each asset answers to its own name and not only to the lowercased
container key, because that is how 7DTD asks for it.

It needs no Unity project of its own and nothing needs it to build or ship. It
proves the container and the object graph survive a runtime of that revision.
It says nothing about whether the asset is right.

### What is still owed

A fresh client. For a synthesized bundle that is not a confirmation step, it is
*the* acceptance, and [blockers.md](blockers.md) records how far it has got.

The mechanical half is automated. `shamway acceptance-provider` generates a
scenario provider for
[hordeforge/7dtd-playtest](https://github.com/hordeforge/7dtd-playtest) with
one case per manifest entry, each loading its asset through the game's own
`DataLoader.LoadAsset<T>` inside a live client — the resolution chain a Unity
runtime cannot run: `@modfolder(Name)` rewriting, `AssetBundleManager`
opening the archive, and the stem reduction that reads the class-142
`m_Container` table. `scripts/playtest-acceptance.sh` wires the whole run
together: generate, build, deploy, hand off to the harness.

```bash
shamway script playtest-acceptance
```

```bash
shamway acceptance-provider --harness-dll /path/to/7dtd-playtest.dll --install
```

A bare launch, without the harness, is still available and still valid — it
proves the mod loads, not that anything read the bundle:

```bash
shamway client deploy .
shamway client launch --mod-name MyMod
```

The half that stays owed forever is the person. A texture that loads upside
down and a clip that loads at the wrong pitch pass every case above. Record
what was judged, and against what, with:

```bash
shamway client capture bundle-assets --observable "the panel reads upright; the cue is one clean beep"
```

## A bundle built somewhere else

`build` is not one thing. It is: start an editor, gate its log, gate the
artifact it wrote, gate the membership it recorded, then stage the artifact
atomically. Only the first step needs Unity.

`stage` is every step but the first:

```bash
shamway stage build/mymod.unity3d --manifest build/mymod.unity3d.manifest --log build/unity-build.log
```

The manifest defaults to `<bundle>.manifest` beside the bundle, which is where
Unity writes it, so the usual call is one argument:

```bash
shamway stage build/mymod.unity3d
```

Three files must travel back from the build host, and each one exists for a
gate that cannot be reconstructed from the others:

| File | What it is for |
|---|---|
| `<name>.unity3d` | the artifact: revision and class-142 gates, and the bytes that ship |
| `<name>.unity3d.manifest` | Unity's own record of bundle membership — the only offline source for the stem-collision gate and for `validate`'s exact-stem checks |
| the Unity build log | the disabled-module gate: Unity reporting *success* while stripping engine classes, which no artifact shows |

What `stage` runs, and what it cannot:

| Gate | Runs |
|---|---|
| class-142 `AssetBundle` object | always |
| bundle-wide file-stem collisions | always |
| atomic manifest-then-bundle staging | always |
| Unity revision against the installed game | only with `SEVEN_DAYS_TO_DIE_DIR` set |
| disabled modules and particle curve modes | only with `--log` |

A gate that did not run is printed as a `not run:` line and returned as
`skipped[]` from `shamway call stage`. That is deliberate: an unrun gate that
goes unmentioned reads exactly like a passed one. Bring the log.

`stage` refuses nothing that `build` accepts; a mod configured as `unity` can
stage a bundle a colleague built, and a rejected candidate never replaces the
bundle already in `Resources/` — the same failure-safe staging `build` uses.

### The build host

The build host is an ordinary checkout of the same mod on a machine that has
the game-matched editor, installed the same way:

```bash
shamway script install-unity-editor --project tools/shamway/UnityProject
shamway build
```

But the mod's committed configuration says `external`, and on that host it is
not. Whether a mod *has* a bundle belongs in the file; whether *this machine*
builds it does not, exactly like `UNITY_EDITOR`. So the build host says so in
its environment:

```bash
export SHAMWAY_BUNDLE_SOURCE=unity
shamway build
```

The override chooses between `unity` and `external` only. It cannot turn a
bundle-free mod into one with a bundle, because that is the mod's decision and
not the machine's, and it is refused with that reason.

Then copy `Resources/<name>.unity3d`, the tracked manifest, and
`.shamway/build/bundle/unity-build.log` back to the machine that owns the
repository, and stage them there.

Unity licensing stays user-owned, on the build host as everywhere else. This
project never automates, requests, prints, logs or commits Unity credentials or
license data; `install-unity-editor.sh` stops and waits for a human on purpose.
If your build host is a CI runner, its licensing is yours to arrange there, and
it belongs in neither this mod's configuration nor its logs.

## What works with no editor at all

Everything except `render-icon`, and — unless the mod asks for a Unity build —
`build` as well:

```bash
shamway status --json
shamway doctor
shamway validate
shamway refs
shamway inspect Resources/mymod.unity3d
shamway check-icons
shamway check-sound assets-src/audio/blast.wav
shamway check-mesh assets-src/meshes/thing.glb
shamway generate --list
shamway prompt item-icon --subject "a squat charcoal welded-steel control box"
shamway client deploy .
shamway client launch --mod-name MyMod
```

The last two matter most: **acceptance never needed the editor**. A bundle
built anywhere, staged here, still ends where every asset in this pipeline
ends — a genuinely fresh client and a human look or listen at the changed
asset. Offline gates are necessary, not sufficient, on every path through this
page.
