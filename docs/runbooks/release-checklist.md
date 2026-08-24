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
- [ ] Every bundle stem only C# loads is listed in `.shamway.toml` `code_references`.
- [ ] `Localization.csv` is inside `Config/`, and every item/block has a key there.
- [ ] Materials carry a `Material` suffix; no stamp-gated generator was edited without its stamp.

## Build and offline gates

- [ ] `shamway doctor` has no relevant warnings.
- [ ] `shamway build --probe` passes on the authoring host.
- [ ] `shamway build` passes and stages bundle plus manifest.
- [ ] `shamway validate` passes every recursive XML reference.
- [ ] `shamway check-icons` passes, and every external `CustomIcon` key is deliberate.
- [ ] `shamway check-sound` passes for every shipped clip.
- [ ] `shamway check-mesh` passes for every authored mesh.
- [ ] `shamway script compile-editor-scripts --scripts <vendored Editor/> --with <mod Editor/>` passes for the game-matched revision.
- [ ] `shamway inspect --json` records correct revision and class 142.
- [ ] Unity log contains no disabled-module, shader, particle, compiler, or serialization error.
- [ ] A second unchanged build is byte-identical, or nondeterminism is explained.
- [ ] Package contains `Resources/<bundle>.unity3d` and excludes authoring files.

## Fresh-client acceptance

- [ ] Deploy to the folder the client actually reads (`shamway client where`), with no second copy in the install's `Mods/`.
- [ ] Start a genuinely fresh supported client with the candidate installed
      (`shamway client launch --mod-name …` refuses a running one).
- [ ] The log shows `Loaded Mod:`, `UIAtlas ItemIconAtlas: Pack took`, and `Loading localization from mod:`.
- [ ] Load every changed prefab/clip/VFX stem by the real consuming path, in process,
      comparing the loaded name to the stem and asking the atlas by name.
- [ ] No incompatibility, bundle failure, wrong-name, fallback, shader, or exception log.
- [ ] A listening run was **unmuted**, and the report says so.
- [ ] Check scale, axes, pivot, bounds, collider, attachment points, and state variants.
- [ ] Check material maps under varied light and transparent material edges.
- [ ] Check icons at native UI size and in every intended UI context.
- [ ] Listen at near/fade/far distances and under concurrency where relevant.
- [ ] Check VFX LOD, repeated effects, caps, cleanup, frame time, and accessibility.
- [ ] Test presentation failure fallback when gameplay must remain functional.
- [ ] Preserve bundle hash, logs/reports, and screenshots/listening notes.
      `shamway client capture LABEL --observable "..."` records each frame with
      what it was checked against; `shamway client capture --list` prints the set.
- [ ] Name explicitly which acceptance items a human actually looked at or listened to,
      and which remain open. A green offline run closes none of them.

## Human sign-off

A canonical list, separate from task checkboxes: a visual debt recorded as a
sub-bullet of a task that was then ticked off became invisible to every later
session. One line per item a person must look at or listen to, with the
person and date when it happened, and the third state — *mod-owned but
failed review* — kept distinct from "stand-in" and "accepted".

- [ ] Held form: scale beside a vanilla item, lamp or indicator legible, wire/attachment point where the prop says it is.
- [ ] Placed form: bounds, orientation, wire endpoints, and the smaller tier reading smaller beside the larger.
- [ ] Materials: relief and uneven gloss on paint, seams where the albedo shows them, bare steel brushed not mirrored, rubber matte, nothing like wet plastic.
- [ ] Effects: from the ground, from far, from above; a close-range billboard judged for what it necessarily fills.
- [ ] Sound: near, across the fade, at maximum range, under concurrency, and on loop.
- [ ] Every line above that a person actually checked has a captured frame and a
      written verdict in `.local/acceptance/manifest.json`. A capture with a
      `null` verdict is an open question, not a sign-off.

## After a game update

- [ ] Verify game files in Steam, then `shamway doctor`: does the shipped bundle's revision still match?
- [ ] `shamway build --probe` with the (possibly new) game-matched editor.
- [ ] Re-decompile every engine fact in [research-provenance.md](../research/research-provenance.md) and record the pass.
- [ ] `shamway validate`, `check-icons`, `check-sound`; then a fresh client.
- [ ] Re-verify the asset inventory against `Config/` and the installed game, not against prose — the source project found its stand-in table stale on two rows.

## Cross-platform/server scope

- [ ] Test every promised client platform; do not infer Metal shader support from Windows.
- [ ] Test dedicated-server paths that resolve bundle assets.
- [ ] Confirm every joining client has the asset-bearing mod installed.
