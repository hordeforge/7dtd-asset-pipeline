# Validation and proof boundaries

## Commands

```bash
7dtd-assets status --json
7dtd-assets doctor --json
7dtd-assets inspect Resources/examplemod.unity3d
7dtd-assets check-log .asset-pipeline/build/bundle/unity-build.log
7dtd-assets refs
7dtd-assets validate
```

`inspect --json` and `doctor --json` are suitable for CI and agent workflows.
`doctor` gives every check its own `OK`/`WARN`/`FAIL` verdict and exits
non-zero when any is `FAIL`, so a single broken check never hides the rest of
the report. Every other command exits non-zero with one `ERROR: ...` line on
stderr. Prefer exit codes over parsing prose.

## Offline gates

| Gate | Failure caught | Evidence used |
|---|---|---|
| Editor exit/output | compiler, license, target, or serialization failure | process exit and expected files |
| Disabled-module log gate | Unity “succeeds” while stripping classes | exact warning family in full Unity log |
| UnityFS signature/revision | wrong file or editor revision | built bundle header and installed game bundle header |
| Class-142 gate | container cannot become a runtime `AssetBundle` | first serialized file's class/type table |
| Manifest stem uniqueness | assets unreachable because 7DTD discards path/extension | complete tracked manifest |
| URI mod identity | wrong `@modfolder` name, or a URI targeting game bundles | `ModInfo.xml` and recursive XML scan |
| Bundle path | missing, wrong, or escaped file | case-insensitive resolution below mod root |
| Asset case/membership | typo, case mismatch, or absent stem | URI and tracked manifest |

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
- an AudioClip is audible at the desired range or mix;
- an icon is readable at its deployed size;
- custom shaders contain the right platform variants;
- client and dedicated-server runtime paths both accept the asset;
- gameplay gracefully falls back when presentation assets are missing.

## Runtime acceptance

For every rebuilt bundle:

1. deploy it to a clean mod installation on a client with EAC settings
   appropriate to the mod;
2. start a fresh client process so no old bundle remains cached;
3. force every changed asset to load by exact URI;
4. search the client log for bundle-load failures, incompatibility, wrong-name
   errors, missing shaders, particle errors, and exceptions;
5. inspect models, materials, VFX, icons, and audio with human eyes/ears;
6. test relevant distances, lighting, held/world states, LODs, and repeated
   spawning;
7. preserve durable evidence (log/report/screenshots and bundle hash).

Do not accept a bundle from a launcher that reused an already-running client.
