# Architecture

## Design goals

- Work from any standalone 7DTD modlet without repository-relative
  dependencies.
- Keep editable source and Unity project state owned by that mod.
- Make the dangerous silent failures deterministic build-time failures.
- Require no Python dependency merely to inspect or validate a bundle.
- Treat the installed game, emitted artifact, and fresh client as separate
  authorities for version, construction, and acceptance.
- Be easy for both humans and coding agents to run and audit: every command is
  machine-readable, and the rules travel into the consuming mod.

## Components

| Component | Responsibility |
|---|---|
| Python CLI | config, scaffold, doctor, status, build orchestration, staging, XML/manifest validation |
| Unity project template | editor revision, package modules, source membership boundary |
| `BundleBuilder.cs` | actual serialization, graphics APIs, options, collision rejection, probe |
| `GeneratedAsset.cs` | asset-as-code prefab/material helpers that encode the batch-mode traps |
| `scripts/install-*.sh` | host packages and the checksum-verified game-matched editor |
| `scripts/generators/` | reproducible audio, icon, texture, and mesh generation |
| consumer `AGENTS.md` | the agent contract, written into the mod by `init` |
| UnityFS reader | signature, revision, block decompression, serialized type table |
| tracked `.manifest` | complete build membership for offline exact-stem validation |
| installed game | authoritative expected Unity revision |
| fresh client | final runtime/render/audio acceptance |

## Trust boundaries

The CLI trusts neither an editor zero exit nor a matching bundle header by
itself. Staging occurs only after log and artifact gates. It never parses or
executes scripts from the game install and never writes there.

The UnityFS reader is intentionally not a general Unity deserializer. A small
auditable parser has a narrower attack and maintenance surface for the two
facts the gate needs. UnityPy and AssetsTools.NET remain optional independent
diagnostics.

## Why a tracked manifest

The bundle object's container could be deserialized to obtain membership, but
that would make basic validation depend on a large changing parser. Unity
already emits a text manifest with exact source paths. Tracking it gives CI a
stable source of membership, catches forgotten rebuilds in review, and keeps
the deployable package clean because the manifest itself is not shipped.

The manifest and bundle are one logical artifact and must be committed
together.

## Failure-safe staging

Unity writes to ignored raw output. The CLI validates there and copies each
accepted artifact to a temporary sibling of its destination before atomic
rename. Failed candidates do not overwrite the last accepted bundle.

## One bundle per config

Schema 1 intentionally owns one bundle. This keeps naming/reference/version
validation exhaustive and simple. Multiple bundles can use multiple configs
today; a future schema may model an array only when real consumers need shared
build orchestration.

## Portability

Consumer paths are relative to the mod root, generated support files live
inside it, and machine paths come from environment variables. The standalone
pipeline repository is a development/install source only; generated modlets do
not require a relative checkout of it at build time once the CLI is installed.

## Why the editor install is resolved, not pinned

A changeset hardcoded in a script is correct until the game updates its engine
and then silently wrong. `unity_release.py` asks Unity's official release
service for the changeset, archive URL, and MD5 belonging to whatever revision
the project needs, and the installer refuses any download Unity published no
checksum for. The version itself still comes from the installed game, so the
chain is game bundle -> revision -> official download -> verified bytes.

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
