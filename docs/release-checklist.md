# Release checklist

## Source and project

- [ ] Every selected source asset and `.meta` is committed.
- [ ] Generation scripts, seeds, prompts, references, and licenses are recorded.
- [ ] No concept/source-only file accidentally sits below bundle source root.
- [ ] Unity project revision equals the installed game's shipped bundle revision.
- [ ] Required `com.unity.modules.*` dependencies cover every component type.
- [ ] Bundle asset stems are mod-prefixed and globally unique.
- [ ] Every variant owns its own icon, held mesh, and placed model; no player-facing
      variant inherits another's art, and `Extends` `param1` excludes what it must.
- [ ] `assets-src/README.md` has a provenance row for every shipped asset.

## Build and offline gates

- [ ] `shamway doctor` has no relevant warnings.
- [ ] `shamway build --probe` passes on the authoring host.
- [ ] `shamway build` passes and stages bundle plus manifest.
- [ ] `shamway validate` passes every recursive XML reference.
- [ ] `shamway check-icons` passes, and every external `CustomIcon` key is deliberate.
- [ ] `shamway check-sound` passes for every shipped clip.
- [ ] `shamway check-mesh` passes for every authored mesh.
- [ ] `shamway inspect --json` records correct revision and class 142.
- [ ] Unity log contains no disabled-module, shader, particle, compiler, or serialization error.
- [ ] A second unchanged build is byte-identical, or nondeterminism is explained.
- [ ] Package contains `Resources/<bundle>.unity3d` and excludes authoring files.

## Fresh-client acceptance

- [ ] Start a genuinely fresh supported client with the candidate installed.
- [ ] Load every changed prefab/clip/VFX stem by the real consuming path.
- [ ] No incompatibility, bundle failure, wrong-name, fallback, shader, or exception log.
- [ ] Check scale, axes, pivot, bounds, collider, attachment points, and state variants.
- [ ] Check material maps under varied light and transparent material edges.
- [ ] Check icons at native UI size and in every intended UI context.
- [ ] Listen at near/fade/far distances and under concurrency where relevant.
- [ ] Check VFX LOD, repeated effects, caps, cleanup, frame time, and accessibility.
- [ ] Test presentation failure fallback when gameplay must remain functional.
- [ ] Preserve bundle hash, logs/reports, and screenshots/listening notes.
- [ ] Name explicitly which acceptance items a human actually looked at or listened to,
      and which remain open. A green offline run closes none of them.

## Cross-platform/server scope

- [ ] Test every promised client platform; do not infer Metal shader support from Windows.
- [ ] Test dedicated-server paths that resolve bundle assets.
- [ ] Confirm every joining client has the asset-bearing mod installed.
