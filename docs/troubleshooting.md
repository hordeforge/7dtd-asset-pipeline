# Troubleshooting

## “not compatible with this newer version of the Unity runtime”

Run:

```bash
shamway inspect Resources/mybundle.unity3d
shamway check-log .shamway/build/bundle/unity-build.log
```

If class 142 is absent, ensure `Packages/manifest.json` contains
`com.unity.modules.assetbundle`. Do not spend time changing compression,
graphics APIs, main asset, or legacy/modern exporter shape while the container
object is missing.

If class 142 exists, confirm the revision against the installed game's own
bundle, that the client is fresh, and that the deployed bytes match the built
bytes. Offline success still does not prove runtime acceptance.

## Unity logs “module ... is disabled in the build” but exits zero

Add the named `com.unity.modules.*` dependency. `stripEngineCode = false`
cannot include a package the project never declared. The pipeline refuses to
stage any artifact from such a log.

## Fixing Packages/manifest.json seems to change nothing

Unity's incremental cache may reuse prior bundle bytes. This template always
passes `ForceRebuildAssetBundle`. If a custom builder omits it, add it. Compare
output mtime and SHA-256 before drawing conclusions.

## “Model has a wrong name” or a silent fallback mesh

The requested file-name stem and loaded object name differ by spelling or
case, or two assets share a stem. Run `shamway validate`, inspect the
tracked manifest, and rename the root prefab/object and source file together.

## “Scripts have compiler errors” and nothing else

That one line is all the shell sees; the real `error CS…` line with a file
and line number is in the Unity log (`.shamway/build/*/unity-build.log`).
Read it there. Two causes recur: a `MinMaxCurve` assigned where the particle
Lights module wants a float (`lights.intensityMultiplier` is a float; the
curve goes on `lights.intensity`), and a hard-obsolete editor API — on
2022.3.62f2 `AudioImporter.preloadAudioData` is `[Obsolete(…, true)]`, so the
setting goes on `AudioImporterSampleSettings` instead. Catch both before
starting an editor with `scripts/compile-editor-scripts.sh`, which compiles
the editor scripts against the real editor's assemblies.

## `doctor` says the editor revision differs from the project

`UNITY_EDITOR` points at a different editor than the one `ProjectVersion.txt`
pins — a host routinely has several. This is not a warning to wave through:
batch mode opens the project with whatever editor it is given, **silently
upgrades it** to that editor's version, and builds a bundle the game rejects.
The project-vs-game check cannot see this, because it reads
`ProjectVersion.txt` before Unity rewrites it. Point `UNITY_EDITOR` at the
game-matched editor (`~/Unity/Hub/Editor/<revision>/Editor/Unity`).

## Bundle loads but prefab/component is empty or missing

The class-142 gate proves the container, not every component. Search the Unity
log for all disabled-module warnings and inspect the object table with
UnityPy/AssetsTools.NET. Ensure the relevant engine module—particles, physics,
audio, animation—is declared. Then verify the exact prefab live.

## Normal or metallic map is assigned but has no effect, or renders flat green

Check both sides:

- importer: normal-map type for normals; linear (`sRGBTexture = false`) for
  numeric masks;
- material: `_NORMALMAP` or `_METALLICGLOSSMAP` keyword enabled; `_EMISSION`
  for an emissive lamp; and the packed mask assigned to **both**
  `_MetallicGlossMap` and `_OcclusionMap`, since Standard reads occlusion
  from the second slot only.

A material whose keyword was never enabled is not merely "unchanged": in the
client it renders flat and green-tinged, which is the signature to look for.
Inspector-looking fields alone are insufficient for script-generated
materials; `GeneratedAsset.StandardMaterial` and `EmissiveMaterial` set the
keywords, and the `.mat` grep in [vfx.md](vfx.md) is how to read them back.

## Transparent particles appear as opaque cards

Set full shader state, not only `_Mode`: source/destination blend, `_ZWrite`,
keywords, and transparent render queue. Unity's material inspector normally
does this; batch scripts do not invoke the inspector GUI.

## Particle errors repeat every frame

Read the first error in the client log. Modules such as velocity-over-lifetime
can require X/Y/Z curves to use the same mode. A constant on one axis and a
curve on another can serialize cleanly and fail only at runtime.

## A sound loads and resolves, but nobody hears it

`validate` proves the clip is in the bundle under the right stem. Three engine
behaviours can still silence it, and all three pass every offline gate:

- `Audio.Manager.LoadAudio` plays **nothing** past the AudioSource prefab's
  `maxDistance`, so a long-range event on a vanilla short-range source is
  silent out there;
- a node's `DistantClip` is used only past `DistantFadeStart`, which defaults
  to `-1` — never;
- an unknown sound-group name does not error; it simply never plays.

See [audio.md](audio.md). Check the clip itself first with
`shamway check-sound`, which rejects silence, near-silence, clipping, and
DC offset.

## The icon did not change after I edited the generator

`render-icon` photographs whatever prefab is on disk. A generator gated on a
stamp (the `[ShamwayPreBuild]` pattern) regenerates only when its stamp
changes, so a geometry edit that forgot to bump the stamp re-renders the old
mesh — and the old mesh ships in the bundle too, with a green build. Bump the
stamp, or delete the generated prefab, and look at the prefab itself before
believing the icon.

## A rendered icon is a uniform transparent square

The render ran without a graphics device. `shamway render-icon` never
passes `-nographics` for this reason — with that flag Unity executes the editor
method happily, `Camera.Render()` draws nothing, and the output looks like a
framing bug rather than a missing device. On a headless host, run the command
under `xvfb-run -a`.

The command fails when coverage is below 2%, so this state is reported rather
than shipped. If coverage is low but non-zero, the prefab may genuinely have no
renderers, or the camera yaw may be photographing an empty side of it.

## An icon has a coloured halo, or its whole cell is opaque

The background was removed with a hard threshold, or not at all. Use
`shamway generate cutout key`, which keeps partial alpha through the
transition band and de-spills the residual key tint, and inspect the result
against **both** a light and a dark background — a fringe is invisible against
one of them. `shamway check-icons` fails a cell whose alpha is entirely
opaque, because that means the cutout never happened.

## A property you deleted is still applied

`ItemClassesFromXml` and `BlocksFromXml` copy every parent property that the
`Extends` `param1` exclusion list does not name. Removing a `TintColor`,
`Meshfile`, `Model`, or `CustomIcon` line from your own definition therefore
does **not** stop the parent's value being inherited — it has to be *excluded*:

```xml
<property name="Extends" value="thrownGrenadeContact" param1="Meshfile,TintColor" />
```

The symptom is silent: an authored palette multiplied by an inherited tint, or
a new variant wearing another variant's mesh. Nothing in a bundle gate can see
it, because the bundle is correct.

## Every display name shows as its raw id

`Localization.csv` is at the mod root. The engine reads it from **`Config/`**
only (`ModManager.LoadLocalizations` builds `mod.Path + "/Config"`), logs
nothing when it is elsewhere, and `Localization.Get` returns the key on a
miss. The client log has `[MODS] Loading localization from mod: <Name>` when
the file was found; its absence is the diagnosis. Move the file into
`Config/`.

## `[MODS] Mod reference for a mod that is not loaded`

The `Name` inside `@modfolder(Name)` does not match any loaded mod's
`ModInfo.xml` `Name` — a rename, a copy into another mod, or a case
difference. `shamway validate` checks the name against this mod's
`ModInfo.xml`; this line in the client log means the deployed copy differs
from the one validated, or the mod did not load at all (check for
`Loaded Mod: <Name>` first).

## The mod is installed but the client ignores it, or warns of a duplicate

On a Proton host the client loads mods from its per-user data
(`…/compatdata/251570/pfx/drive_c/users/steamuser/AppData/Roaming/7DaysToDie/Mods/`),
not from the install's `Mods/`. A mod present in both places loads from the
per-user copy and the install copy is ignored with a duplicate warning — so a
rebuilt bundle deployed to the wrong one never runs. `shamway client where`
prints the folder the client actually reads; `shamway client deploy` puts the
modlet there and replaces what was there before.

## The client sits on a menu backdrop with no menu

Steam was not running when the client started. Exec'ing Proton directly
bypasses the Steam *launcher*, not the Steam *API*: the log says
`[Steamworks.NET] SteamAPI_Init() failed … probably Steam not running`, the
first thing to touch Steamworks throws, and the symptom looks like a display
or Proton fault. Start Steam (`steam -silent` is enough) first, and grep the
log for `SteamAPI_Init` before suspecting anything else.

## The client hangs at world load, but only sometimes

Proton async-load starvation. The shipped build sets
`Application.runInBackground` only inside `if (Application.isEditor)` and
never assigns `Application.backgroundLoadingPriority` (both confirmed with
`ilspycmd` on V 3.1.0 b14), so when the window loses focus Unity throttles the
process and the async `Resources.LoadAsync`/`LoadManager.LoadAsset` waits in
world load can starve — the log ends after `AstarManager Init` and nothing
follows. It is a race against focus, which is why it is non-deterministic.
`Awake IsFocused: False` early in the log is the tell. Keep the client
window focused during an acceptance run.

## A placed block vanishes, and the client shows air

On the **dedicated server** log: `WRN Entity FallingBlock_N
(EntityFallingBlock) fell off the world, pos=…`. A `Shape=ModelEntity` block
placed without support under every voxel it occupies becomes a falling
entity in the stability pass; the client just reports air. Ground each
column of the placement, never fall back to a local-only `SetBlockLocal`,
and read the server log before hypothesising about bundles or replication.

## `client capture` says there is no screenshot tool, or writes a black frame

The session type decides which tools work, not what is installed. Under
Wayland, an X11 grabber (`maim`, `scrot`, ImageMagick's `import`) reaches no
compositor and returns a black or garbage image **while exiting zero** — which
is why `capture` selects by session rather than trying each in turn, and why a
black frame is more likely to mean "wrong tool" than "wrong moment".

Check what the session is and what was found:

```bash
shamway capabilities --json
```

Install one that fits:

```bash
shamway script install-tools --with-desktop-capture
```

If the tool exits zero but writes nothing, `capture` fails rather than filing
an empty file — some desktop portals refuse a screenshot without an interactive
permission grant and report success anyway. Take the shot with the desktop's
own hotkey and enter it into the same manifest:

```bash
shamway client capture held-nuke --file ~/Pictures/screenshot.png \
    --observable "held upright, not sunk into the hand"
```

## `client capture` refuses because no client is running

Deliberate. A frame of a main menu, a desktop, or the terminal that ran the
command files into the manifest looking exactly like evidence, and the next
reader has no way to tell. Launch a client first, or pass `--allow-no-client`
when you genuinely mean to capture whatever is on screen.

## `doctor` cannot find game or editor

Use absolute machine-local environment variables:

```bash
export SEVEN_DAYS_TO_DIE_DIR="/path/containing/Data/Config/items.xml"
export UNITY_EDITOR="/path/ending/Editor/Unity"
shamway doctor
```

Do not commit these paths.

## Probe fails before a useful Unity log exists

Run `"$UNITY_EDITOR" -version`, check execute permissions, and on Linux inspect
dynamic dependencies with `ldd`. Install missing host compatibility packages
from the operating system's trusted package manager.

## Editor reports a license failure

Open Unity Hub or Unity's supported licensing flow and activate the license as
the current user. Do not copy a license from another person/machine or ask an
agent to handle account credentials.

## macOS player shows missing/pink shaders

A Windows bundle includes D3D11/OpenGL/Vulkan variants, not Metal. Treat native
macOS shaders as a separate platform-asset problem. Prove a macOS-target
bundle and a runtime selection strategy; do not rename two platform files to
the same URI and hope the loader chooses.
