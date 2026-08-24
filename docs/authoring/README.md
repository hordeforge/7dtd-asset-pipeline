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
- [vfx.md](vfx.md) — particle budgets, LOD tiers, and the two silent material
  failures.
- [authoring-tools.md](authoring-tools.md) — the optional open-source tools and
  which gate each one belongs to.

Every page here is served from an installed package (`shamway docs
agent-workflows`, and so on), because a mod repository has the command and no
checkout of this one.
