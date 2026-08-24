# Validation and proof boundaries

## Commands

```bash
shamway status --json
shamway doctor --json
shamway inspect Resources/examplemod.unity3d
shamway refs
shamway validate
shamway check-icons
shamway check-sound assets-src/audio/clip.wav
shamway check-mesh assets-src/meshes/thing.glb
```

One more applies only to a mod whose bundle an editor built, because the log it
reads is one an editor wrote:

```bash
shamway check-log .shamway/build/bundle/unity-build.log
```

`inspect --json` and `doctor --json` are suitable for CI and agent workflows.
`doctor` gives every check its own `OK`/`WARN`/`FAIL` verdict and exits
non-zero when any is `FAIL`, so a single broken check never hides the rest of
the report. Every other command exits non-zero with one `ERROR: ...` line on
stderr. Prefer exit codes over parsing prose.

## Offline gates

Five of these read an editor's *build* and so apply only to
`bundle_source = "unity"` or a staged `"external"` bundle; they are marked. The
rest read the artifact and the mod's own XML, and run on every path.

| Gate | Failure caught | Evidence used |
|---|---|---|
| Editor exit/output *(editor only)* | compiler, license, target, or serialization failure | process exit and expected files |
| Disabled-module log gate *(editor only)* | Unity “succeeds” while stripping classes | exact warning family in full Unity log |
| UnityFS signature/revision | wrong file or engine revision | built bundle header and installed game bundle header |
| Class-142 gate | container cannot become a runtime `AssetBundle` | first serialized file's class/type table |
| Manifest stem uniqueness | assets unreachable because 7DTD discards path/extension | complete tracked manifest |
| URI mod identity | wrong `@modfolder` name, or a URI targeting game bundles | `ModInfo.xml` and recursive XML scan |
| Bundle path | missing, wrong, or escaped file | case-insensitive resolution below mod root |
| Asset case/membership | typo, case mismatch, or absent stem | URI and tracked manifest |
| Code-referenced stems | a prefab or clip only C# loads, absent from or misnamed in the bundle | `code_references` in `.shamway.toml` against the tracked manifest |
| Particle curve-mode log gate *(editor only)* | a system that logs on every frame in the client | `curves must all be in the same mode` in the Unity build log |
| Editor revision *(editor only)* | `UNITY_EDITOR` pointing at a different editor, which silently upgrades the project | `Unity -version` against `ProjectVersion.txt` |
| Engine modules *(editor only)* | a component class Unity will strip while reporting success | `Packages/manifest.json` |
| Atlas cell shape | an icon that is not square, not the cell size, has no alpha, or was never cut out of its background | PNG IHDR chunk, plus alpha coverage when Pillow is present |
| Icon key case | a `CustomIcon` whose case differs from the filename stem it ships | recursive XML scan against `UIAtlases/` |
| Clip format | stereo, unexpected sample rate, silence, near-silence, clipping, DC offset | WAV frames |
| Mesh extents/conformance | a mesh authored in the wrong unit, or invalid glTF | trimesh and the Khronos validator |

Icons are **not** bundle members — `ModManager.LoadUiAtlases` packs
`UIAtlases/<Atlas>/*.png` at runtime — so `validate` cannot see them and
`check-icons` exists to cover them. It reconciles three kinds of key:
`CustomIcon`, `display_entry icon=` in `progression.xml`, and the **name** of
every item or block that sets no `CustomIcon`, because that is the engine's
default sprite lookup. A key this mod does not provide is reported, never
failed: referencing a vanilla key is normal.

### The absence of an editor is itself gated

Every claim on this page about what runs without Unity is checked on each push.
CI's `scaffold` job runs on a hosted Linux runner with no editor and no game
install: it scaffolds a modlet with no flags, refuses a Unity project appearing,
authors a mesh and a texture, builds, validates, and asserts the resulting
bundle carries `AssetBundle`, `GameObject`, `Transform`, `MeshFilter`,
`MeshRenderer`, `Mesh`, `Material`, `Shader` and `Texture2D`. Removing
`vkd3d-compiler` fails it, which is what makes it a gate rather than a
demonstration. See [CONTRIBUTING.md](../CONTRIBUTING.md).

### When this tool wrote the bundle itself — the default

Every gate in the table above that is not marked *(editor only)* still runs
against a synthesized bundle, and the
revision gate still means exactly what it meant: it rejects a bundle written
for an engine the installed game does not use. Two others change character,
because an artifact and a checker with the same author cannot cross-examine
each other, and one cannot run at all:

| Gate | On a synthesized bundle |
|---|---|
| class-142 container | true by construction — structural, not independent evidence |
| stem uniqueness | reads the membership record this build wrote, same caveat |
| disabled-module log gate | cannot run: no editor, so no log, and nothing was stripped |
| engine revision | unchanged and independent |
| every XML reference gate | unchanged: they read the mod's XML, not the artifact's author |

One more note appears only when a lane degraded: with no `vkd3d-compiler` on
the host, a mesh source is packed as a bare `Mesh` rather than as the prefab
the game resolves, and `build` says which it wrote. A quieter bundle must never
read like a whole one.

`build` prints those as `note:` lines on every synthesize, and calls the
result **synthesized**, never *built*. What restores independent evidence is
`shamway verify-bundle`, which loads the artifact in a real Unity runtime with
the engine's own loader and class definitions — the only offline check here
that this repository did not also author. It needs an editor, which is exactly
what the backend exists to avoid, so it is optional and its absence is
reported rather than assumed away. Nothing needs it to build, gate, stage or
ship; it is a checker, and the only reason an editor is worth having on a
machine that does not build with one.

Acceptance is unchanged and matters more: a fresh client and a person.

### When the bundle was built somewhere else

`shamway stage` runs this same table minus the two gates that read the *build*
rather than the artifact. The class-142, revision, stem-uniqueness and
atomic-staging gates are identical, because they parse the file that will
ship. The disabled-module and particle-curve log gates run only when the Unity
log travels with the bundle (`--log`), and the revision gate only when
`SEVEN_DAYS_TO_DIE_DIR` names an installed game. Whatever could not run is
printed as a `not run:` line and returned in `skipped[]`, because an unrun gate
that goes unmentioned reads exactly like a passed one.

A mod that declares no bundle (`bundle_source = "none"`) has one gate in
total: no XML may load an asset out of a bundle the mod does not ship.
[no-unity.md](bundles/no-unity.md) covers all four cases.

### What `validate` discovers, and what it cannot

`validate` scans the *text* of `Config/**/*.xml`. Two consequences:

- **An asset only C# loads is invisible.** A prefab a Harmony hook fetches
  with `DataLoader.LoadAsset<GameObject>(uri)`, a Light prefab a particle
  Lights module instantiates, an AudioClip a script plays — no XML names them.
  Declare their stems in `.shamway.toml` `code_references` and they are held
  to the same membership, uniqueness, and case rules.
- **A patch that never lands still passes.** A wrong XPath — a missing
  container element, a case difference, a leading `/` left off — matches
  nothing, and the patcher logs nothing. The `Model` or `ClipName` inside it
  is syntactically perfect and resolves offline, and the game never sees it.
  `validate` proves a URI is *correct*, not that it is *applied*; only a
  client (or the engine's `ConfigsDump`) proves that.

The UnityFS parser is dependency-free and bounded: it reads archive metadata,
decompresses uncompressed/LZ4 blocks, and reads serialized class IDs. It does
not execute Unity, deserialize every object, or modify files.

## Why class 142 is mandatory

A UnityFS header with the correct editor version is not sufficient. A project
whose package manifest disables the AssetBundle engine module can emit a file
with a matching header but no serialized class-142 `AssetBundle` object. The
runtime has no container object to return and rejects it as incompatible.

The build log usually names the stripped type:

```text
'AssetBundle' is not supported because the module AssetBundle is disabled in the build.
```

That warning and the class-table check are independent gates. Keep both: one
explains the source setting, the other inspects the actual artifact.

## What offline validation does not prove

It does not prove that:

- a particular component survived serialization merely because its type is
  present somewhere in the bundle;
- a prefab's scale, axes, bounds, collider, material, animation, or attachment
  point is correct;
- shader keywords/blending/import color space render correctly;
- an AudioClip is audible at the desired range or mix — `maxDistance` on the
  AudioSource prefab and a sound group's fade ranges decide that, and both are
  runtime behaviour;
- a sound-group name a block or item references actually exists;
- an icon is readable at its deployed size, or that the art matches the mesh;
- custom shaders contain the right platform variants;
- client and dedicated-server runtime paths both accept the asset;
- gameplay gracefully falls back when presentation assets are missing.

## Runtime acceptance

For every rebuilt bundle:

1. deploy it to a clean mod installation on a client with EAC settings
   appropriate to the mod;
2. start a fresh client process so no old bundle remains cached;
3. force every changed asset to load by exact URI;
4. search the client log for the lines that prove the mod loaded, and for
   bundle-load failures, incompatibility, wrong-name errors, missing shaders,
   particle errors, and exceptions;
5. inspect models, materials, VFX, icons, and audio with human eyes/ears;
6. test relevant distances, lighting, held/world states, LODs, and repeated
   spawning;
7. preserve durable evidence (log/report/screenshots and bundle hash).

Do not accept a bundle from a launcher that reused an already-running client.

### Step 3 has a mechanical definition too

"Force every changed asset to load by exact URI" reads like a human sitting in
the world equipping things. It is not: a
[hordeforge/7dtd-playtest](https://github.com/hordeforge/7dtd-playtest)
scenario provider runs inside the live client and can ask the engine directly.
`shamway acceptance-provider` generates that provider from the mod's tracked
manifest — one case per bundle member, each calling `DataLoader.LoadAsset<T>`
on the member's real URI, plus a stem the bundle does not contain that must
return null so a loader answering everything cannot read as a pass.

```bash
shamway acceptance-provider --harness-dll /path/to/7dtd-playtest.dll --install
```

`scripts/playtest-acceptance.sh` runs the whole sequence — generate, build,
deploy the modlet and the harness mods, hand off to the orchestrator, print
the case results:

```bash
shamway script playtest-acceptance
```

The provider is generated rather than hand-written because the cases *are* the
manifest: a bundle member with no case is a member nobody proved. Adding an
extension the writer can emit means adding it to `acceptance.ASSET_CASES` with
the `LoadAsset<T>` the engine really uses; an unmapped member is refused, not
skipped.

Stems and mod names reach the generated C# and XML as untrusted text — a
staged manifest or a vendored ModInfo.xml can come from another machine — so
the generator escapes them into its string literals, XML attributes, and
comments; a stem that is not a legal C# identifier still gets a valid local
variable name.

Two boundaries this does not cross. It proves the engine read the bytes, never
that they are the right bytes — step 5 is still a person. And it runs against a
client the harness drives, which means it takes the shared client lock; see
[sibling-repos.md](sibling-repos.md).

### The mechanics, on a Linux host

Steps 1, 2, 4 and 7 have a mechanical definition, and `shamway client`
encodes it so "fresh" is not a matter of opinion:

- `shamway client where` — the client's per-user Mods/ and logs/
- `shamway client deploy .` — copy the deployable modlet there
- `shamway client log --mod-name MyMod` — classify the newest log again

```bash
shamway client where
shamway client deploy .
shamway client launch --mod-name MyMod --run-seconds 120 --mute
shamway client log --mod-name MyMod
```

What each of those knows:

- **Where the client loads mods from.** A Proton client's user data is the
  wine user's `%APPDATA%`:
  `<library>/steamapps/compatdata/251570/pfx/drive_c/users/steamuser/AppData/Roaming/7DaysToDie/`.
  Its `Mods/` is where mods are deployed for acceptance; it survives a Steam
  file verification and needs no write into the install. The install's own
  `Mods/` holds only `0_TFP_Harmony`, so looking there and concluding the mod
  is absent is a false alarm. A mod present in **both** loads from the
  per-user copy and the install copy is ignored with a duplicate warning —
  the stale-bundle trap. When reading the install for reference, look only
  at its real `Mods/`; backup or overhaul folders such as `Mods.DF/` are not
  loaded and are not evidence. `deploy` copies only `ModInfo.xml`, `Config/`,
  `Resources/`, `UIAtlases/`, `Prefabs/`, `UI/` and root DLLs, replacing the
  previous deployment, so nothing stale survives beside the new bundle.
- **What "fresh" means.** A bundle is cached for the life of the process
  under its path, so a reused client proves nothing about a rebuild. `launch`
  refuses while a `7DaysToDie.exe` or `7DaysToDie_EAC.exe` is running
  (matching the executable, not the bare name, which also matches the
  dedicated server and `7DaysToDie_Data` paths), records the launch time, and
  then requires the newest `logs/output_log_client__*.txt` to post-date it.
- **Where the log is, and that it is rewritten.** The client writes a new
  `output_log_client__<date>__<time>.txt` under the user data's `logs/` on
  every start. Quote the report or copy the file; a line number from the live
  log is meaningful only for the run that produced it.
- **The positive lines.** A loaded mod logs `[MODS] Loaded Mod: <Name>`; a
  packed atlas logs `UIAtlas ItemIconAtlas: Pack took N us`; a found
  `Config/Localization.csv` logs `[MODS] Loading localization from mod:
  <Name>`. The **absence** of a positive line is the diagnosis: no
  localization line means the file is in the wrong place, and nothing else
  will say so.
- **The negative lines**, each named after the silent failure it reveals:
  `[MODS] Mod reference for a mod that is not loaded` (the `@modfolder(Name)`
  does not match `ModInfo.xml`), `Loading AssetBundle … failed` and
  `not compatible with this newer version of the Unity runtime` (the bundle
  did not open), `Model has a wrong name` / `ERR Model '…'` (stem or case),
  `SteamAPI_Init() failed` (Steam was not running), `curves must all be in the
  same mode` (particle modes), `Awake IsFocused: False` (see
  troubleshooting: Proton async-load starvation), and
  `EntityFallingBlock … fell off the world` on the **server** log (a placed
  model block with no support). A bare exception is reported but not
  failed, because vanilla throws some; read the first one.
- **Launching through Steam.** `steam -applaunch 251570 -skipintro
  -skipnewsscreen=true` is what `launch` runs. Steam hands the request to the
  already-running Steam client, so the game inherits **Steam's**
  environment, not the shell's: a variable a test hook reads must go into the
  game's Steam launch options as `VAR=value %command%`, and `tr '\0' '\n' <
  /proc/<pid>/environ | grep VAR` confirms it arrived. Steam must be running
  even when Proton is exec'd directly by another launcher — without it the
  client logs `SteamAPI_Init() failed` and sits on a menu backdrop that looks
  like a display fault. `disable-discord` flips the persisted
  `DiscordDisabled` pref in the Proton `user.reg` so an unattended run does
  not negotiate rich presence.
- **Audio.** `--mute` mutes the client's PipeWire/Pulse sink input at the OS
  layer (never a game setting) and unmutes it again before returning. A
  listening run is never muted; see [audio.md](authoring/audio.md), which also covers
  the saved WirePlumber state that keeps a muted game silent afterwards.

`launch` and `log` exit 0 only when every positive line was found and no
negative line appeared. That is **loadability** evidence: the mod loaded, the
atlas packed, the bundle opened, nothing errored. It is not a look or a
listen, and the report says so in its last line.

### Step 3, precisely: asking the game rather than reading pixels

"Force every changed asset to load" is best done **in process**, with a mod's
own test hook or console command, because each resolution path has a fallback
that hides a miss from the eye:

- Load each bundle asset with `DataLoader.LoadAsset<Transform>(uri)` directly
  and compare the returned object's **name** to the URI stem. Going through
  `BlockShapeModelEntity.getPrefab` would hand back `block_missingPrefab` and
  items would draw `leather.fbx`; the direct load returns `null` on a failed
  open, which is the honest answer.
- Ask the atlas for each sprite **by name**.
  `MultiSourceAtlasManager.GetAtlasForSprite` returns `atlases[0]` for an
  unknown sprite, so a missing icon draws some other atlas's art rather than
  nothing.
- Look each sound group up in `Audio.Manager.audioData`, and remember that
  `Block.SoundPickup` defaults to `craft_take_item`: a dropped sound property
  is a *wrong* sound, not a missing one.
- Cover the assets no XML names — code-loaded VFX prefabs, Light prefabs,
  scripted clips — and the properties whose absence is silent:
  `ActivationTransformToHide` children, `DropScale`, an inherited `TintColor`
  (this check is what caught a vanilla tint multiplying authored paint that
  nothing else reported).

Report it as one line of the form `resolved=N/N icons= models= vfx= sounds=
misses=none`. Print that line into the client log, because the log is the one
channel this pipeline can read back: the client records only *that* a console
command executed, never its **output**, so a command that ran and reported a
problem is indistinguishable there from one that worked. Reading the output
instead needs the client's web API or a dedicated server's telnet console —
both of which live in the mod, since the command whose answer you want is the
mod's own. This pipeline deliberately ships neither transport: without a
mod-side command to call, they can only ask a vanilla console questions that
say nothing about a mod's assets. To get a new item into the bag for a look, `giveself <item>
[qty] [quality] [putInInventory]` — the fourth argument defaults to **false**
and drops the item into the world, which looks exactly like a bad item name.

A run like this proves that everything resolves. It signs off nothing: the
held lamp being legible, the smaller tier reading smaller beside the larger,
the cloud reading from the ground and from two kilometres — those are a
person's, and the evidence packet records who looked.

### Steps 5 and 7: recording what a person saw

The judgement stays a person's. What is mechanical is the artefact it leaves,
and without one "looks right" is a sentence in a chat log that no later session
can reopen, compare against, or disagree with.

`shamway client capture` files the frame next to the observable it was checked
against. Frame the shot in the client and let the countdown fire — a capture
taken by alt-tabbing to a terminal photographs the terminal:

```bash
shamway client capture held-nuke --wait 5 \
    --observable "held upright like a grenade, not sunk into the hand, at 0.42 m hand scale"
shamway client capture --list
```

It writes `.local/acceptance/<label>.png` and appends to
`.local/acceptance/manifest.json`: the label, the observable, the backend that
took it, the image's own size, SHA-256 and mtime — and a `verdict` field that
is always `null`. Nothing here writes a pass. A reviewer fills that field in,
or the frame stands as an open question.

What it refuses to do matters as much as what it does:

- **It will not capture without a running client.** A screenshot of a main
  menu, or of the terminal that ran the command, files into the manifest
  looking exactly like evidence. `--allow-no-client` is there for the case
  where you mean it.
- **It picks the backend by session type, not by what is installed.** An X11
  grabber under Wayland returns a black or garbage frame *and exits zero*, so
  a preference list alone would file a black rectangle as a sign-off.
  `shamway capabilities` reports which tool was found;
  `shamway script install-tools --with-desktop-capture` installs one.
- **It captures the full screen only.** Naming a specific window needs a
  compositor-specific lookup, and one that picked the wrong window would
  record the wrong thing under the right label.

A screenshot taken with the desktop's own hotkey is exactly as good; enter it
into the same manifest so it is cited rather than lost:

```bash
shamway client capture held-nuke --file ~/Pictures/screenshot.png \
    --observable "held upright like a grenade, not sunk into the hand"
```

Audio has no equivalent artefact, and pretending otherwise would be worse than
the gap: a waveform is not a listen. Record the clip's `check-sound` numbers,
the sound group, and the fact that a person listened on a fresh client — see
[audio.md](authoring/audio.md), "Acceptance".
