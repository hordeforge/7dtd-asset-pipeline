# Authoring — the asset lanes

How an asset is produced before a bundle exists: the reproducible
asset-as-code lanes, the style contract they render against, and the two asset
classes whose runtime behaviour makes a correct build silent or invisible.

- [agent-workflows.md](agent-workflows.md) — the lane each asset type follows
  (mesh, texture, icon, audio, VFX) and the evidence packet a release
  candidate carries.
- [art-direction.md](art-direction.md) — the house style for generated and
  drawn 2D assets, and the prompt patterns `shamway prompt` renders. Read it
  before writing any generation prompt.
- [audio.md](audio.md) — the sound lane, `sounds.xml`, and why a loaded clip
  can be inaudible.
- [video.md](video.md) — staged motion clips: the motion-kind declaration,
  `client capture --clip`, and the deadeye model-review lane.
- [vfx.md](vfx.md) — particle budgets, LOD tiers, and the two silent material
  failures.
- [skinned-gear.md](skinned-gear.md) — worn armor: why it is the one asset
  class that leaves the editorless lane, the bone names it binds to by name
  with no error on a miss, and what the prefab has to carry.
- [environment-effects.md](environment-effects.md) — weather, fog, and light:
  why a zone effect that ships only particles reads as a glitch, and the
  engine controls that make it weather.
- [authoring-tools.md](authoring-tools.md) — the optional open-source tools and
  which gate each one belongs to.

Every page here is served from an installed package (`shamway docs
agent-workflows`, and so on), because a mod repository has the command and no
checkout of this one.
