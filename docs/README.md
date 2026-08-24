# Reference documentation

Every page here is also served from an installed package with `shamway docs`
(`shamway docs` lists them; `shamway docs TOPIC` prints one), so a mod
repository can read these rules with no checkout of this repository.

Start pages live in [docs/getting-started/](getting-started/) — the complete
bare-machine path in [quickstart.md](getting-started/quickstart.md) and each
choice explained in [setup.md](getting-started/setup.md).

The asset lanes own [docs/authoring/](authoring/): the lane each asset type
follows ([agent-workflows.md](authoring/agent-workflows.md)), the house style
([art-direction.md](authoring/art-direction.md)), the sound and VFX lanes
([audio.md](authoring/audio.md),
[vfx.md](authoring/vfx.md)), and the optional OSS toolchain
([authoring-tools.md](authoring/authoring-tools.md)).

How a bundle is produced lives in [docs/bundles/](bundles/): the editor build
path ([bundle-generation.md](bundles/bundle-generation.md)), where a `.unity3d`
may come from when there is no editor
([no-unity.md](bundles/no-unity.md)), and the design record of the writer that
needs no editor at all
([offline-bundle-builder.md](bundles/offline-bundle-builder.md)).

Evidence for the 7DTD-specific rules lives in
[docs/research/](research/) ([research-provenance.md](research/research-provenance.md)).

Procedures for recurring situations live in [docs/runbooks/](runbooks/):
failure messages and their root causes
([troubleshooting.md](runbooks/troubleshooting.md)) and the release path
([release-checklist.md](runbooks/release-checklist.md)).

The working state of the project lives in [docs/status/](status/): what still
needs a human, a licence, or a client ([blockers.md](status/blockers.md)), and
known capability gaps ([improvements.md](status/improvements.md)).

Reference pages sit at the top level: the design and trust boundaries
([architecture.md](architecture.md)), every configuration key
([configuration.md](configuration.md)), the machine-facing interfaces
([consumer-api.md](consumer-api.md)), each gate and its proof boundary
([validation.md](validation.md)), the engine-side integration rules
([game-integration.md](game-integration.md)), the ownership split between mod
and pipeline ([mod-repo-layout.md](mod-repo-layout.md)), and the sibling
HordeForge repositories ([sibling-repos.md](sibling-repos.md)).
