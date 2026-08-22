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
