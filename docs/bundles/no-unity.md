# Running without Unity

## Where Unity actually enters

Of everything this pipeline does, only three operations *can* start a Unity
editor, and none of them has to:

- `build`, and only when the mod has asked for it with `bundle_source =
  "unity"`. The default is `"synthesized"`, which starts nothing;
- `render-icon`, which photographs a bundle prefab. `shamway generate
  mesh-icon` does the same job from the mesh file in headless Blender;
- `verify-bundle`, which is a *checker*, not a builder — nothing needs it to
  build, gate, stage or ship, and it is the one offline check here that this
  project did not also author.

Every other command — `status`, `doctor`, `refs`, `validate`, `inspect`
(including `--deep`), `pack`, `check-mesh`, `check-sound`, `check-icons`,
`generate`, `prompt`, `docs`, `stage`, `acceptance-provider`, and the whole
`client` family — is Python reading files, and always ran on a machine with no
editor and no game.

**That is measured, not asserted.** CI's `scaffold` job runs on a hosted Linux
runner with no editor and no game install: it scaffolds a modlet with no flags,
fails if a Unity project appears, authors a mesh and a texture, and runs `build`
and `validate`. It then gates the shader lane in *both* states — with the
distribution's own vkd3d 1.2 it must degrade to a bare `Mesh` and print the
caveat, and with a vkd3d 1.19 built from source it must produce `AssetBundle`,
`GameObject`, `Transform`, `MeshFilter`, `MeshRenderer`, `Mesh`, `Material`,
`Shader` and `Texture2D`. A change that puts an editor back on the default
path, or that turns a degraded lane silent, stops CI rather than reaching this
page.

So the real question is never "can I use shamway without Unity". It is **where
the `.unity3d` comes from**, or whether the mod needs one at all. That has four
answers, and the configuration states which one applies:

| `bundle_source` | Where the bundle comes from | Needs an editor here |
|---|---|---|
| `synthesized` **(default)** | this tool writes it directly: `shamway build`, seconds, no editor | no |
| `none` | nowhere: the mod ships no bundle | no |
| `external` | an editor elsewhere builds it; this host gates and stages it: `shamway stage` | no |
| `unity` **(opt in)** | a local editor builds it: `shamway build` | yes |

Three of the four need no editor, and the default is one of them: an `init`
that says nothing about a bundle source gets `synthesized`. The single
exception is `init --adopt PROJECT`, where pointing at a Unity project the mod
already has *is* the opt-in, so that scaffolds `unity` without repeating it.

Three questions decide which case a mod is in:

1. Does any XML ask the engine to load an asset out of a bundle — a
   `Meshfile`, a block `Model`, a `sounds.xml` `ClipName`, an XUi mesh? If not,
   the mod needs no bundle: `none`.
2. Does everything in that bundle draw unlit and opaque? Then `synthesized`
   writes it here, with no editor and no project — textures, sounds, text
   files, and a mesh source file becoming a prefab with its mesh, material and
   shader.
3. Only if the bundle needs shading this writer does not author — lit,
   shadowed, transparent, normal-mapped, or multi-pass — does an editor have to
   compile it: `unity` if one lives on this machine, `external` if it lives on
   another.

The rest of this page takes them in that order.

## A mod with no bundle

A 7 Days to Die modlet does not have to contain a bundle. These ship as loose
files and the engine reads them directly:

- `Config/**/*.xml` — every XPath patch;
- `UIAtlases/<AtlasName>/<name>.png` — item icons, packed into a runtime atlas
  by folder name (see [game-integration.md](../game-integration.md));
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
  generates its icons instead, and a mod with a mesh file can photograph that
  with `shamway generate mesh-icon`, which is headless Blender rather than
  Unity.

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

## Moving a mod off the editor lane

A mod scaffolded before `"synthesized"` was the default, or one that opted into
an editor and no longer needs it, moves in two steps. Whether it *can* move is
the first question: the writer emits one unlit opaque pass, so a mod whose
props are lit, transparent, normal-mapped or multi-pass, or that ships
particles or rigging, stays on `"unity"`. Check what is actually in the bundle
first:

```bash
shamway inspect --deep Resources/mymod.unity3d
```

**Just this machine, reversibly.** The committed configuration is the mod's
decision; where *this* host gets a bundle from is not. Nothing is edited:

```bash
export SHAMWAY_BUNDLE_SOURCE=synthesized
shamway build
```

**Permanently.** Two keys change together, and they have to: `source_root`
means a path *inside the Unity project* for `"unity"` and a path *in the mod*
for `"synthesized"`, so changing one without the other points the writer at a
folder that does not exist. `load_config` refuses that combination by name
rather than letting a build print "create this folder", which would be the
wrong fix.

Edit `.shamway.toml`:

```toml
bundle_source = "synthesized"
source_root = "assets-src/bundle"
```

Then move the **source files** — images, clips, meshes, text — out of
`tools/shamway/UnityProject/Assets/ModAssets/Bundle/` and into
`assets-src/bundle/`, without their `.meta` files, which mean nothing off the
editor lane:

```bash
cd /path/to/MyMod
mkdir -p assets-src/bundle
find tools/shamway/UnityProject/Assets/ModAssets/Bundle -type f ! -name '*.meta' -exec cp {} assets-src/bundle/ \;
shamway build
shamway validate
```

What does **not** move is anything the editor authored rather than imported: a
`.prefab`, a `.mat`, a `.shader`, a particle system. `collect_sources` refuses
those by name instead of skipping them, and the writer builds the prefab,
material and shader itself from each mesh file — so a prop whose prefab was
composed from primitives in the editor has to be re-authored as a mesh
(`shamway generate mesh`, Blender, OpenSCAD) before it can make the trip.

Keep the Unity project until a fresh client has accepted the synthesized
bundle. Deleting it is the one step that cannot be undone from git alone if
any `.meta` went with it.

## A bundle this tool writes itself

`bundle_source = "synthesized"` removes Unity from the build entirely. There is
no project, no editor, no batch-mode run: `shamway build` reads a folder of
source files and writes the `.unity3d` in milliseconds.

```bash
shamway init /path/to/MyMod --game-dir "$SEVEN_DAYS_TO_DIE_DIR"
```

No flag selects it — it is what `init` does when nothing says otherwise.
`--bundle-source synthesized` is accepted and means the same thing, and stating
it is worth doing in a script that must not change meaning if the default ever
does.

That scaffolds `assets-src/bundle/`, and every file you put there becomes one
asset, named by its file stem — the name 7DTD's URIs ask for:

| Source file | Becomes | Loaded as |
|---|---|---|
| `myModPanel.png`, `.jpg`, `.tga`, `.bmp` | `Texture2D`, RGBA32 (or DXT1/DXT5) | `LoadAsset<Texture2D>` |
| `myModBlast.wav` | `AudioClip`, 16-bit PCM in an FSB5 bank | `sounds.xml`, `LoadAsset<AudioClip>` |
| `myModData.json`, `.txt`, `.csv` | `TextAsset` | `LoadAsset<TextAsset>` |
| `myModThing.glb`, `.gltf`, `.obj`, `.stl`, `.ply` | a **prefab** with its `Mesh`, `Material` and `Shader` | `Meshfile`, block `Model`, `LoadAsset<GameObject>` |
| `myModBeep.ogg`, `.mp3`, `.flac`, `.aiff`, `.m4a`, `.opus`, `.wma` | `AudioClip`, decoded by **FFmpeg** first | `sounds.xml`, `LoadAsset<AudioClip>` |
| `myModGlyph.svg`, `.psd`, `.exr`, `.webp`, `.avif` | `Texture2D`, rasterized by **ImageMagick** first | `LoadAsset<Texture2D>` |

The last two rows are why the source folder takes what an author actually has
on disk rather than only what the standard library reads. Both converters are
optional: a `.wav` and a `.png` need nothing installed, and a source whose
converter is missing is **refused by name with the install line**, never
skipped and never silently downgraded. Conversion always goes to a temporary
file, so the lossy original a person signed off on is never overwritten.

An SVG rasterizes at its own pixel size × `density / 96` — 4x at the default
384 — because SVG's user unit is 1/96 inch. Author the size you want, or
scale it in the icon lane afterwards.

### The mesh lane, and what it is not

Any geometry file [trimesh](../authoring/authoring-tools.md#trimesh--python-mesh-generation-and-checks)
reads becomes a `Mesh`: positions, normals, and UV0 when the file has them,
interleaved in one vertex stream. Blender, OpenSCAD (through STL), `shamway
generate mesh`, and anything else that exports an interchange format all reach
the bundle the same way, with no editor between them and it.

```bash
shamway check-mesh assets-src/bundle/myModThing.glb
shamway build
```

Two conversions happen inside the writer, because both are the kind of wrong
that loads perfectly and looks broken:

- **handedness**: glTF, OBJ, STL and PLY are right-handed and Unity is not, so
  X is negated and triangle winding reversed. A mesh converted without this is
  mirrored, and every gate passes;
- **up axis**: the file must be Y-up. A Z-up export arrives lying on its face.
  That is an exporter setting and no amount of geometry inspection reveals it —
  set it in Blender's export dialog or `--python` call.

What the mesh lane does not write: tangents, vertex colours, blend shapes,
skinning, and more than one submesh. One mesh file is one material's worth of
geometry, and a normal-mapped material would find no tangents. Both are
consequences of the paragraph below rather than of effort.

A `Mesh` is a mesh, not a model. 7DTD's `Meshfile` and block `Model` resolve
through `DataLoader.LoadAsset<GameObject>` — a **prefab**, which needs a
renderer, which needs a material, which needs a shader. This writer now builds
that whole chain, so a mesh source file produces a loadable model rather than
its geometry half.

### What a mesh source file becomes

One mesh file `prop.glb` produces four objects, and the **prefab takes the
stem** because that is the name the game resolves:

| Object | Name | Why |
|---|---|---|
| `GameObject` prefab | `prop` | what `Meshfile` and `Model` ask for |
| `Mesh` | `prop_mesh` | the prefab owns the stem, so the mesh cannot |
| `Material` | `prop_mat` | the renderer's one material slot |
| `Shader` | `Shamway/Unlit` | one per bundle, shared by every material |

A texture named `prop_albedo` in the same source tree is bound to that
material's `_MainTex`; without one the material draws Unity's built-in white.

**This lane needs `vkd3d-compiler`.** Without it the writer packs the bare
`Mesh` it always did rather than refusing the build — a mesh-only bundle is
still reachable through `LoadAsset<Mesh>`, and a mod that packed yesterday
keeps packing. The difference is visible in `shamway capabilities` and
`shamway doctor`, never silent in the artifact's behaviour: a bundle either
has a prefab or it does not.
The suffix is a convention, not a guess — the prefab has to own `prop`, so the
texture cannot also be called `prop`, and the stem-collision gate would reject
it if it were.

### The shader it writes, and the ones it does not

One pass: an unlit textured pass, d3d11 and OpenGLCore, no keyword variants,
no hardware tiers. The HLSL is compiled by
[`vkd3d-compiler`](https://gitlab.winehq.org/wine/vkd3d) to the same shader
model 4 `DXBC` the game's own sub-programs carry, and wrapped in the container
documented in `hordeforge/7dtd-engine-research`,
[`docs/shader-subprogram-blob.md`](https://github.com/hordeforge/7dtd-engine-research/blob/main/docs/shader-subprogram-blob.md).
No Unity is involved in producing it.

What it deliberately is not: lit, shadowed, transparent, cut-out,
normal-mapped, instanced, or multi-pass. Those need keyword variants and
constant buffers this writer does not declare, and a prop that needs one of
them still wants `unity` or `external`. **An unlit prop is unaffected by
scene lighting** — it draws at full brightness at midnight, which is a look
decision, not a defect.

**The shader does not run yet, and this page said otherwise.** The lines below
were measured under `-nographics`, where there is no device to compile a
sub-program against, so `isSupported` is not a verdict:

```text
VERIFY-SHADER: 'Shamway/Unlit' isSupported=True passes=1     # -nographics: meaningless
VERIFY-SHADER: 'Shamway/Unlit' isSupported=False passes=3    # real device: the answer
VERIFY-MATERIAL: ... shaderSupported=False _MainTex=<unbound>
```

A block whose `Model` is a synthesized prefab therefore **places in 7DTD and
renders nothing** — no error, no magenta, an invisible block. Everything around
the shader is sound: the container, the prefab, the mesh, the material and the
`PPtr` chain are all read back correctly by a runtime and by the game itself.

Get the real answer with a graphics device:

```bash
xvfb-run -a shamway verify-bundle --draw
```

That is the engine's own loader and its own verdict, and it is still **a load,
not a look**: nobody has yet watched this shader draw. See
[research-provenance.md](../research/research-provenance.md).

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
[research-provenance.md](../research/research-provenance.md); the design record, the prior
art surveyed, and what is not attempted are in
[offline-bundle-builder.md](../adrs/0001-synthesize-bundles-without-an-editor.md).

### What it does not write yet, and why none of it is a law

Every asset class a 7DTD modlet references from XML — `Texture2D`,
`AudioClip`, `TextAsset`, `Mesh`, `Material`, `Shader`, and the prefab group —
is written here. What is left is **inside** the shader lane, not outside it:

| Unbuilt | What it would take |
|---|---|
| lit, shadowed, or fog-affected shading | the lighting constant buffers and the keyword variants a real surface pass declares |
| transparency and cut-out | a second blend state and a render-queue tag, both already representable in `_shader_state` |
| normal mapping | tangents in the mesh lane, plus a second texture property |
| instancing and multi-pass | more than one `m_Passes` entry, and the instancing variant flag |
| Vulkan and Metal sub-programs | `glslangValidator` for SPIR-V; the container is the same |

A prop that needs one of those still uses `unity` or `external`, and neither is
second-class. Everything else does not.

**Nothing on that list is a property of the engine.** This page said the
opposite until 2026-08-24 — that materials and shaders "cannot be produced
offline, ever" — which was false, and the tool that disproved it
(`vkd3d-compiler`) was already installed on the machine that wrote it. The
correction is recorded in
[research-provenance.md](../research/research-provenance.md).

What *is* measured, and remains true, is that a mod bundle must carry its own
shader, because **borrowing** one is closed both ways:

- **the player's shaders.** The shipped game's `unity default resources`
  carries six shaders and all six are internal — no Standard, no Unlit,
  nothing a prop could use.
- **the game's own.** The `trees` bundle embeds its ten shaders, and every
  material in it points at one in the *same file*. Copying those into a mod
  would ship the game's assets.

Carrying its own is exactly what this writer does, so that finding is a
constraint the lane satisfies rather than a wall it stops at. The remaining
gaps are tracked in [status/improvements.md](../status/improvements.md).

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

A person's eyes and ears — and, as of 2026-08-24, only that.

The load is proven. 7 Days to Die V 3.1.0 b14 opened a bundle this tool
serialized with no editor in its path and returned both objects through
`DataLoader.LoadAsset<T>`, requested by stem, with FMOD decoding the
hand-written FSB5 bank to `channels=1 frequency=44100 samples=20727`. The log
lines and what each one covers are in [blockers.md](../status/blockers.md) entry 6.

The look is done too, once: on the same day a reviewer aimed and fired in the
client and reported the texture rendering as a centred, circular ring and the
clip as three clean beeps. Both findings — *not stretched*, *not crackling* —
are exactly the kind no offline gate and no in-client case reports, which is
why that step is not a formality. For a synthesized bundle the human look is
the only step with an opinion about the content, and it is owed again every
time the content changes.

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

It regenerates the save every run — a reused world is state from the last one,
and this run is meant to prove what *this* build does. `--reuse-save` opts out
for a quick loop, and a report that used it has to say so.

To prove the **writer** rather than a particular mod, there is a self test that
brings its own modlet — generated in a temporary directory, built with no
editor, run through a live client, and asserted by value:

```bash
shamway script playtest-synthesized
```

[validation.md](../validation.md) lists what each of its assertions catches.

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
shamway check-mesh assets-src/bundle/myModThing.glb
shamway generate --list
shamway generate mesh-icon assets-src/bundle/myModThing.glb UIAtlases/ItemIconAtlas/myModThing.png
shamway prompt item-icon --subject "a squat charcoal welded-steel control box"
shamway client deploy .
shamway client launch --mod-name MyMod
```

`build` is in that list too, and is the point of the page: with the default
`bundle_source` it writes the bundle here.

```bash
shamway build
shamway pack assets-src/bundle out.unity3d --game-dir "$SEVEN_DAYS_TO_DIE_DIR"
```

`render-icon` is the only command with no editorless form, and only because it
photographs a bundle prefab with its materials. `generate mesh-icon` covers
the same intent from the mesh file, in headless Blender, and says in its own
output that what it produced is a clay render.

The default path has exactly one host dependency of its own, and only for the
prefab lane: `vkd3d-compiler` **1.3 or newer**, which compiles the shader.
Version matters — Debian and Ubuntu package 1.2, which is on PATH and cannot
read HLSL — so the registry probes what the binary supports rather than whether
it exists, and reports a too-old one with the reason:

```bash
shamway capabilities --missing
```

Neither an absent nor a too-old compiler fails the build. The mesh is packed as
a bare `Mesh` and `build` prints a note saying which it wrote, rather than
letting a quieter bundle pass for a whole one. `scripts/install-tools.sh` installs
a usable one where the distribution has one, and
`scripts/install-tools.sh --with-vkd3d-source` builds one where it does not —
a no-op on a host that is already fine, so it is safe to run anywhere.

The last two matter most: **acceptance never needed the editor**. A bundle
built anywhere, staged here, still ends where every asset in this pipeline
ends — a genuinely fresh client and a human look or listen at the changed
asset. Offline gates are necessary, not sufficient, on every path through this
page.
