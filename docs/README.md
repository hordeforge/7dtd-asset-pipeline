# Reference documentation

Every page here is also served from an installed package with `shamway docs`
(`shamway docs` lists them; `shamway docs TOPIC` prints one, and `shamway docs
index` prints this page), so a mod repository can read these rules with no
checkout of this repository.

Every subdirectory carries its own `README.md` index, and every genre carries
a `TEMPLATE.md` to start a new page from.

## Reference

Start pages live in [getting-started/](getting-started/README.md) — the
complete bare-machine path in [quickstart.md](getting-started/quickstart.md)
and each choice explained in [setup.md](getting-started/setup.md).

The asset lanes own [authoring/](authoring/README.md): the lane each asset type
follows ([agent-workflows.md](authoring/agent-workflows.md)), the house style
([art-direction.md](authoring/art-direction.md)), the sound and VFX lanes
([audio.md](authoring/audio.md), [vfx.md](authoring/vfx.md)), and the optional
OSS toolchain ([authoring-tools.md](authoring/authoring-tools.md)).

How a bundle is produced lives in [bundles/](bundles/README.md): the editor
build path ([bundle-generation.md](bundles/bundle-generation.md)) and where a
`.unity3d` may come from when there is no editor
([no-unity.md](bundles/no-unity.md)).

The rest of the reference sits at the top level: the design and trust
boundaries ([architecture.md](architecture.md)), every configuration key
([configuration.md](configuration.md)), the machine-facing interfaces
([consumer-api.md](consumer-api.md)), each gate and its proof boundary
([validation.md](validation.md)), the engine-side integration rules
([game-integration.md](game-integration.md)), the ownership split between mod
and pipeline ([mod-repo-layout.md](mod-repo-layout.md)), and the sibling
HordeForge repositories ([sibling-repos.md](sibling-repos.md)).

## Procedures and state

Procedures for recurring situations live in [runbooks/](runbooks/README.md):
failure messages and their root causes
([troubleshooting.md](runbooks/troubleshooting.md)) and the release path
([release-checklist.md](runbooks/release-checklist.md)).

The working state of the project lives in [status/](status/README.md): what
still needs a human, a licence, or a client ([blockers.md](status/blockers.md)),
and known capability gaps ([improvements.md](status/improvements.md)).

## Decisions and process records

- [adrs/](adrs/README.md) — decisions that have been made: the constraint, the
  choice, the honest cost. ADR 0001 owns the editorless bundle writer's design
  record.
- [rfcs/](rfcs/README.md) — decisions still open, each arguing alternatives and
  a recommendation.
- [prds/](prds/README.md) — specifications of intended behaviour for
  capabilities not built yet.
- [research/](research/README.md) — engine facts and the tool or artifact that
  measured each one ([research-provenance.md](research/research-provenance.md)).
- [reports/](reports/README.md) — operational bugs and evidence-led
  investigations, preserved instead of lost to run logs.
- [reviews/](reviews/README.md) — working notes that have not hardened into any
  of the above.
- [digests/](digests/README.md) — what other projects' work can teach this one.

An open question is an RFC; the decision it produces is an ADR; the evidence
either one rests on is a research page. Neither store requires the other.
