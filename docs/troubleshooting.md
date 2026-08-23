# Troubleshooting

## “not compatible with this newer version of the Unity runtime”

Run:

```bash
7dtd-assets inspect Resources/mybundle.unity3d
7dtd-assets check-log .asset-pipeline/build/bundle/unity-build.log
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
case, or two assets share a stem. Run `7dtd-assets validate`, inspect the
tracked manifest, and rename the root prefab/object and source file together.

## Bundle loads but prefab/component is empty or missing

The class-142 gate proves the container, not every component. Search the Unity
log for all disabled-module warnings and inspect the object table with
UnityPy/AssetsTools.NET. Ensure the relevant engine module—particles, physics,
audio, animation—is declared. Then verify the exact prefab live.

## Normal or metallic map is assigned but has no effect

Check both sides:

- importer: normal-map type for normals; linear (`sRGBTexture = false`) for
  numeric masks;
- material: `_NORMALMAP` or `_METALLICGLOSSMAP` keyword enabled.

Inspector-looking fields alone are insufficient for script-generated
materials.

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
`7dtd-assets check-sound`, which rejects silence, near-silence, clipping, and
DC offset.

## A rendered icon is a uniform transparent square

The render ran without a graphics device. `7dtd-assets render-icon` never
passes `-nographics` for this reason — with that flag Unity executes the editor
method happily, `Camera.Render()` draws nothing, and the output looks like a
framing bug rather than a missing device. On a headless host, run the command
under `xvfb-run -a`.

The command fails when coverage is below 2%, so this state is reported rather
than shipped. If coverage is low but non-zero, the prefab may genuinely have no
renderers, or the camera yaw may be photographing an empty side of it.

## An icon has a coloured halo, or its whole cell is opaque

The background was removed with a hard threshold, or not at all. Use
`7dtd-assets generate cutout key`, which keeps partial alpha through the
transition band and de-spills the residual key tint, and inspect the result
against **both** a light and a dark background — a fringe is invisible against
one of them. `7dtd-assets check-icons` fails a cell whose alpha is entirely
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

## `doctor` cannot find game or editor

Use absolute machine-local environment variables:

```bash
export SEVEN_DAYS_TO_DIE_DIR="/path/containing/Data/Config/items.xml"
export UNITY_EDITOR="/path/ending/Editor/Unity"
7dtd-assets doctor
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
