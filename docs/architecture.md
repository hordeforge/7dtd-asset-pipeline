# Architecture

## Design goals

- Work from any standalone 7DTD modlet without repository-relative
  dependencies.
- Keep editable source — and, where a mod opted into an editor, its Unity
  project state — owned by that mod.
- Make the dangerous silent failures deterministic build-time failures.
- Require no optional Python dependency merely to inspect or validate a
  bundle; the base host toolset includes the pinned `unityz` reader.
- Require no Unity editor at all, ever, by default: the writer here produces
  every asset class a modlet references, and a Unity editor is a source a mod
  opts into (`bundle_source = "unity"`) rather than a dependency of the tool.
- Treat the installed game, emitted artifact, and fresh client as separate
  authorities for version, construction, and acceptance.
- Be easy for both humans and coding agents to run and audit: every command is
  machine-readable, and the rules travel into the consuming mod.

## Components

| Component | Responsibility |
|---|---|
| Python CLI | config, scaffold, doctor, status, build orchestration, staging, XML/manifest validation |
| `operations.py` | the operation registry: one machine-readable contract for every surface |
| `api.py` | the `Pipeline` facade, and the dispatch `call`/`serve` share |
| `serve.py` | line-delimited JSON request/response over stdio |
| `capabilities.py` | which optional tools are usable, what they unlock, how to install them |
| Unity project template | *(opt-in)* editor revision, package modules, source membership boundary |
| `BundleBuilder.cs` | *(opt-in)* editor-side serialization, graphics APIs, options, collision rejection, probe |
| `build.stage_bundle` | the same gates and staging for a bundle a *different* editor built, so no editor is needed here |
| `bundle_writer.py` | **the default build path**: UnityFS container, SerializedFile v22, type trees, and the Texture2D/AudioClip/TextAsset/Mesh/Material/Shader/prefab objects, with no editor |
| `shader_blob.py` | the shader sub-program container: HLSL through `vkd3d-compiler` to `DXBC`, wrapped as Unity's compressed blob |
| `bundle_verify.py` + `BundleVerifier.cs` | loads a bundle in a real runtime with the engine's own loader — the one offline check this project does not also author |
| `GeneratedAsset.cs` | asset-as-code prefab/material/import/particle/audio helpers that encode the batch-mode traps |
| `IconRenderer.cs` | renders a bundle prefab into an atlas cell, so an icon cannot drift from its mesh |
| `icon_check.py` | the atlas gate: cell geometry, alpha, and every `CustomIcon` key |
| `sound_check.py` | the clip gate: channels, rate, level, clipping, DC offset |
| `assets_src.py` | the editable-source tree and the provenance contract written into the mod |
| `client.py` | fresh-client acceptance: the client's per-user paths, allow-listed deployment, Steam launch, OS-layer mute, and log classification |
| `scripts/compile-editor-scripts.sh` | compiles the vendored editor C# against a real editor's assemblies, without starting one |
| `scripts/install-tools.sh` | host packages, including `vkd3d-compiler` for the writer's shader lane |
| `scripts/install-unity-editor.sh` | *(opt-in)* the checksum-verified game-matched editor |
| `generators/` (in the package) | reproducible sound, audio, cutout, particle-card, icon, texture-maps, mesh, mesh-optimize, mesh-icon and bind generation, as `shamway generate` |
| consumer `AGENTS.md` | the agent contract, written into the mod by `init` |
| `unityz.py` + pinned `unityz` | bounded process/JSON boundary, UnityFS decompression, revision and serialized class table |
| tracked `.manifest` | complete build membership for offline exact-stem validation |
| installed game | authoritative expected bundle revision, read-only |
| fresh client | final runtime/render/audio acceptance |

## Trust boundaries

The CLI trusts neither an editor zero exit nor a matching bundle header by
itself. Staging occurs only after log and artifact gates. It never parses or
executes scripts from the game install and never writes there.

Where this tool wrote the artifact itself — the default — one side of that
sentence has no independent half: a checker and an artifact with the same
author cannot cross-examine each other. `build.synthesized_caveats()` says so
in the words every caller prints, rather than letting a self-graded gate read
like an independent one, and it adds a line when a lane degraded for want of a
host tool. What restores an independent reading is `verify-bundle` (a real
runtime) and, always, a fresh client.

`client.py` is the one component that touches a running game, and its
boundary is deliberate: it launches through Steam (`steam -applaunch`) rather
than executing anything from the install, reads the install only to derive
the Steam library, and writes only below the client's per-user data directory
(`compatdata/<app>/pfx/.../AppData/Roaming/7DaysToDie/`), which is outside
the install and is where a Proton client loads mods from anyway. Its mute is
an OS audio-layer operation on the process's sink input, never a game
setting. It proves loadability and hands over to a person; it makes no
claim about what an asset looks or sounds like.

### Where scratch work lands

The lanes that shell out stage real payloads: a WAV decoded by FFmpeg, a sheet
rasterized by ImageMagick, a Blender render, a shader compiled by
vkd3d-compiler or glslangValidator, and, in `install-unity-editor.sh`, a
multi-gigabyte editor archive. All of it goes under `$XDG_CACHE_HOME/shamway`
when that is set, otherwise the host's usual user-cache directory
(`~/.cache/shamway` on Linux, `~/Library/Caches/shamway` on macOS,
`%LOCALAPPDATA%\shamway` on Windows), through `workdir.scratch_dir` in Python
and a `TMPDIR` default in the shell scripts. A `TMPDIR` the caller already
exported is respected.

Not `/tmp`: it is tmpfs on most Linux hosts, so that default charges every one
of those payloads against RAM. Each scratch directory is removed on exit.

Unity parsing has one owner: the pinned `unityz` binary handles container
bounds, decompression, and SerializedFile metadata, while `unityz.py` maps its
versioned JSON contract into the pipeline's small report types. The pipeline
does not keep a second UnityFS/LZ4 parser. UnityPy remains on the creation side
for its release-indexed type-tree database; AssetsTools.NET remains an
optional independent diagnostic.

The icon and clip gates follow the same rule: the PNG check reads the IHDR
chunk with the standard library and the clip check uses `wave`, so both run on
a bare host. Pillow only ever *adds* a measurement (alpha coverage), and its
absence degrades to a note rather than to a pass.

Unity is a *source of the artifact*, not a dependency of the tool, and for
every asset class a modlet references it is not even that: `bundle_writer.py`
writes the container and the objects directly, so `bundle_source =
"synthesized"` — the default — removes the editor from the build entirely. What that costs is evidence, not
correctness-by-hope — the class-142 and stem gates become structural on our own
output, and every synthesize says so. The trust model answers it by inverting
the relationship: where an editor *does* exist it becomes a verifier
(`verify-bundle`) rather than a builder, and where it does not, a fresh client
is the acceptance rather than the confirmation. See
  [ADR 0001](adrs/0001-synthesize-bundles-without-an-editor.md).

`build` and
`stage` are the same pipeline with one step removed: the gates live in Python
and read the bundle, its manifest and its log, so which machine ran the editor
changes nothing about what is proven — except the two gates that read the build
log, which `stage` reports as unrun when the log did not travel with the
bundle. `bundle_source` states which case a mod is in; `SHAMWAY_BUNDLE_SOURCE`
lets a build host say the same about itself, because whether an editor exists
is machine state and belongs with `UNITY_EDITOR`, not in a committed file.
A mod that declares no bundle has no Unity surface at all, and `doctor` stops
reporting one.

`build`, `stage` and `render-icon` are the only operations that write into the modlet
(`client_deploy` and `client_launch` write outside it, into the client's
per-user data), and the registry marks every writer `writes: true` so a caller — `serve` included — can
refuse them before anything starts.

The writer's boundary is where the work has reached, **not** where the format
ends — a distinction this page got wrong until 2026-08-24, when it said the
writer "stops at materials and shaders" and called that a property of the
engine. `bundle_writer.py` covers textures, clips, text files, meshes,
materials, shaders and the prefab component group: every asset class a 7DTD
modlet references from XML. What was measured, and remains true, is only that a
shader cannot be *borrowed* — the shipped player carries six shaders and all
are internal, and the game's own bundles embed theirs same-file. Whether one
could be *authored* offline was never checked before it was written down as
impossible. It can: `vkd3d-compiler` compiles the pass to `DXBC` and the blob
container was decoded from a shipped bundle, so the writer emits one.

What the writer has not reached is narrower than that sentence was: one unlit
opaque d3d11 pass, no keyword variants, no other graphics API.
[ADR 0001](adrs/0001-synthesize-bundles-without-an-editor.md) records the
research and what is not attempted; [no-unity.md](bundles/no-unity.md) states
what a synthesized bundle owes instead.

The shader lane is the only part of the writer with a host dependency:
`vkd3d-compiler`. It degrades rather than refusing — a mesh becomes a bare
`Mesh` instead of a prefab — because a mod that packed yesterday should not
stop packing today. That makes it the one place a missing capability is not a
refusal, so `build` prints a caveat naming what was packed instead.

The mesh lane is also where an optional capability becomes structural rather
than additive: `trimesh` reads the interchange file, so without it the writer
refuses a `.glb` by name instead of skipping it. That is the same rule the rest
of the registry follows — a missing capability is a refusal with an install
command, never a quieter build.

## Why a tracked manifest

The decision and its costs are [ADR 0002](adrs/0002-membership-is-a-tracked-manifest-committed-beside-the-bundle.md):
membership comes from Unity's own text manifest tracked beside the bundle,
never from a second deserializer, and the two are committed together.

## Failure-safe staging

Unity writes to ignored raw output. The CLI validates there and copies each
accepted artifact to a temporary sibling of its destination before atomic
rename. Failed candidates do not overwrite the last accepted bundle.

## One bundle per config

[ADR 0003](adrs/0003-one-bundle-per-config.md) records the decision: schema 1
intentionally owns one bundle; multiple bundles use multiple configs today. A
future schema may model an array only when real consumers need shared build
orchestration.

## Portability

Consumer paths are relative to the mod root, generated support files live
inside it, and machine paths come from environment variables. The standalone
pipeline repository is a development/install source only; generated modlets do
not require a relative checkout of it at build time once the CLI is installed.

## One registry, several surfaces

[ADR 0004](adrs/0004-one-operation-registry-and-no-network-server.md) records
the decision: `operations.py` holds the contract and every surface dispatches
through it, so the published schema cannot describe behaviour that does not
exist. No server is built in — `serve` is stdio JSON, and `schema` publishes
enough for a consumer to generate whatever wrapper they need.

## Why the editor install is resolved, not pinned

[ADR 0005](adrs/0005-editor-install-is-resolved-not-pinned.md) records the
decision: the changeset comes from Unity's official release service for
whatever revision the installed game ships, never from a hardcoded pin, and a
download without a published checksum is refused.

## Security and destructive-action policy

- no Unity credentials or licenses in config;
- no game-install writes;
- no shell evaluation of TOML values;
- subprocess arguments are passed as an array;
- bundle URI traversal outside the mod root is rejected;
- no overwrite-capable scaffold flag;
- generated artifacts replace destinations only after validation;
- downloaded editor archives and modules are MD5-verified against Unity's own
  published digests, and an unpublished digest is a hard failure;
- `init` refuses to overwrite any file it would generate.
