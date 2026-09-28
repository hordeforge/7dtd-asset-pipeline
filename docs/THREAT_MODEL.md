# Threat model

What can be attacked in this tool, what it costs, and what stands in the way.
It is derived from the code: every entry point, boundary, and control below
carries a `path:line` reference, and `tests/test_assets.py` fails when one of
those references stops pointing at a line that exists. A statement here that
no longer has code behind it is a defect, not history.

This page models the surface. It does not fix anything: a threat with a
location is handed to a point review. `docs/architecture.md` owns the
destructive-action policy this page measures against.

## Scope

In scope: the `shamway` CLI, the `shamway serve` stdio channel, the Python
`Pipeline` facade, the packaged host scripts, and the writers into the game
client's per-user data directory.

Out of scope: the 7 Days to Die client and its dedicated server, the
installed game (read-only evidence), Unity itself, and the sibling
repositories, which have their own surfaces.

The threat actor with reach here is a hostile or careless party upstream of
the operator: a mod author whose source is adopted, an asset file from a
third party, a GitHub release, or another session sharing the machine. The
operator is the one who runs the commands, so every boundary below is crossed
by data the operator did not write.

## Risk-ranked summary

| # | Risk | Boundary | Where | Severity |
|---|---|---|---|---|
| R1 | Four host tools are downloaded and installed as executables with no checksum, from a moving `releases/latest` URL | install script → host | `scripts/install-tools.sh:766`, `:809`, `:858`, `:886` | High |
| R2 | A modlet is copied into the shared client `Mods/` directory, and the destination base is operator-supplied with no containment check | build tree → live game client | `src/sevendtd_asset_pipeline/client.py:540`, `:1377`, `:568` | High |
| R3 | Asset bytes leave the host to a third-party model endpoint, and the gateway result is stored without redaction | host → third-party API | `src/sevendtd_asset_pipeline/providers/gemini.py:104`, `video_review.py:392`, `video_review.py:720` | High |
| R4 | Mod-controlled and downloaded binary files are parsed in-process with length checks but no size ceilings | file → parser | `src/sevendtd_asset_pipeline/gltf_scene.py:152`, `generators/bind.py:704`, `shader_blob.py:666` | Medium |
| R5 | Mod XML is parsed with the stdlib parser, with no hardened configuration | mod tree → parser | `src/sevendtd_asset_pipeline/references.py:51` | Medium |
| R6 | `serve` has no caller identity: any process that can write the pipe may invoke operations, and only `writes` gates them | process → IPC | `src/sevendtd_asset_pipeline/serve.py:67` | Medium |
| R7 | `shamway script` runs bash with the operator's argv and no timeout | operator → host process | `src/sevendtd_asset_pipeline/scripts.py:106` | Low |
| R8 | The Unity editor download is MD5-verified and a launch is unbounded | build → host process | `scripts/install-unity-editor.sh:129`, `client.py:1166` | Low |

R1 and R2 are the two worth a security owner's time. R3 is a deliberate,
consented data flow whose evidence trail is weaker than the flow.

## Attack surface

### Entry points

| Entry point | Input | Control | Location |
|---|---|---|---|
| CLI arguments | operator strings | argparse; per-command validation | `src/sevendtd_asset_pipeline/cli.py` |
| `shamway serve` | newline-delimited JSON on stdin | operation registry, `writes` gate | `serve.py:78` |
| `shamway call` / `Pipeline.call` | JSON or kwargs | schema validation only | `api.py:487` |
| Mod source tree | TOML, XML, CSV, images, meshes, clips | per-gate validation | `config.py:233`, `references.py:51` |
| Bundle files | UnityFS container bytes | delegated to `unityz` | `unityfs.py:58` |
| glTF/GLB/OBJ | interchange file bytes and URIs | length checks, URI containment | `gltf_scene.py:152`, `generators/bind.py:704` |
| PNG atlas | IHDR and cell pixels | signature and length checks | `icon_check.py:121` |
| DXBC/SPIR-V blobs | shader compiler output | magic and length checks | `shader_blob.py:666` |
| `review-audio` / `review-video` | clip bytes, intent JSON | `--allow-network` gate | `audio_review.py:542`, `video_review.py:509` |
| `client deploy`, `client hold` | mod tree, arbitrary argv | name validation, `flock` | `client.py:530`, `client.py:1413` |
| `scripts/install-*.sh` | remote URLs, versions | checksum on the editor, `unityz`, uv, vkd3d, and Blender downloads; none on four others (R1) | `scripts/install-tools.sh:536`, `:628` |
| Environment | `GEMINI_API_KEY`, `SEVEN_DAYS_TO_DIE_*_DIR`, `PLAYTEST_LOCK_FILE`, `SHAMWAY_SCRIPT_ROOT`, `ZMOLV_*` | read, not validated | `providers/gemini.py:30`, `client.py:138`, `client.py:182` |

There is no network listener. `serve` is stdio by decision
(`docs/adrs/0004-one-operation-registry-and-no-network-server.md`), so the
IPC boundary is a pipe, not a port.

### Surface the code holds that the model must not lose

- The `flock` sidecar every `7dtd-playtest` session reads
  (`client.py:329`), the same lock `scripts/playtest-*.sh` take.
- The per-user `Mods/` directory, which is shared with other sessions on the
  machine (`client.py:117`).
- Provider credentials in the environment, and the evidence documents that
  record what was sent to the provider (`evidence.py:24`).

## Trust boundaries and data flow

| Boundary | Crossing | Validation point |
|---|---|---|
| Mod author → pipeline | TOML, XML, CSV, images, meshes | per-gate; no single chokepoint |
| Mod XML → filesystem | bundle URI | traversal refused: `references.py:153` |
| glTF → filesystem | external buffer URI | `..`, absolute, `%`, NUL refused: `gltf_scene.py:180` |
| Mod tree → live client | deployable files | name validation `client.py:458`, symlink refusal `client.py:484` |
| Pipeline → host process | argv arrays, no `shell=True` | registry allowlist `scripts.py:81` |
| Host → third-party API | clip bytes, intent | `--allow-network` gate, host constants |
| Host → release servers | tool archives | digest comparison on five downloads (`install-tools.sh:552`) |
| Consumer → `serve` | JSON lines | `writes` gate only |
| Game install → pipeline | bytes, config, revision | read-only; no code from it is parsed or executed |

Privilege transitions: `client deploy` writes outside the modlet into a
directory the game loads (`client.py:1377`), and
`client hold -- CMD` runs an arbitrary command under the shared lock
(`client.py:1413`). Both are transitions the operator triggers deliberately
and neither is recorded as an identity-bearing event.

Secrets: `GEMINI_API_KEY` or `GOOGLE_API_KEY` enter from the environment
(`providers/gemini.py:60`), travel as an `x-goog-api-key` header rather than
a query string (`providers/gemini.py:107`), and are never placed in argv. The
video gateway inherits the parent environment
(`video_review.py:392`), so every key in the operator's environment reaches
that child. There is no rotation path in this repository: keys live in the
operator's environment and are revoked there.

## Assets and impact

- **Source assets and modlets.** Corruption or replacement changes what ships
  into a client. Blast radius is the deployed mod, not the repository.
- **The shared client `Mods/` directory and the lock.** Damage here reaches
  other sessions: a bad deploy is read by a live run (`client.py:1378`).
- **Provider credentials.** Theft costs the operator's Gemini quota and
  account.
- **Asset bytes leaving the host.** A review upload publishes unreleased art
  and audio to a third party.
- **The development host.** R1 and R2 are both code execution on it.
- **Reputation of a release.** A bundle that loads but is wrong is a mod
  author's complaint, not a security event, and no offline gate catches it.

## Threats per boundary

### Mod author → pipeline (STRIDE)

- **Tampering.** A crafted `ModInfo.xml` or manifest steers bundle resolution;
  the traversal guard covers the URI path (`references.py:153`) and nothing
  else.
- **Information disclosure.** A bundle URI that resolves outside the mod root
  is refused, so a mod cannot read the operator's tree; the case-insensitive
  walk also refuses a case collision (`references.py:159`).
- **Denial of service.** No bundle size, member count, or vertex count ceiling
  exists in the writer, so a large source exhausts memory in the build
  process rather than failing fast.
- **Elevation of privilege.** A mod that adopts `GeneratedAsset.cs` runs C# in
  the editor when the mod opts into `bundle_source = "unity"`; that is a
  documented opt-in, not a defect.

### Mod author → live client

- **Tampering.** `deploy` copies whatever the mod tree holds, including files
  outside bundle membership.
- **Spoofing.** The deployed name comes from `ModInfo.xml` (`client.py:1376`);
  `_deploy_name` refuses separators, NUL, control characters, and bidi
  overrides (`client.py:458`), so a name cannot point outside `Mods/`.
- **Repudiation.** A deploy writes no attributable log line; the shared
  directory shows files, not who put them there.

### Host → third-party API

- **Information disclosure.** Clip bytes and the intent document are uploaded
  deliberately, behind `--allow-network` (`audio_review.py:542`). The gate
  precedes credential read and socket open.
- **Information disclosure, second path.** The gateway's whole `error`
  envelope is written into the evidence document unredacted
  (`video_review.py:720`), and `evidence.redact` drops mapping keys only
  (`evidence.py:46`), so a credential in free text survives.

### Host → release servers (R1)

- **Tampering and elevation of privilege.** `gltf_validator`
  (`install-tools.sh:766`), `gltfpack` and `compressonatorcli`
  (`install-tools.sh:793`), and AssetRipper (`install-tools.sh:858`) are
  fetched from `releases/latest`, extracted, and installed as executables
  with no digest compared. A compromised release, a hijacked maintainer, or a
  MITM against a mutable URL runs code as the operator. The four downloads
  that do compare a digest are uv (`:536`), vkd3d (`:628`), Blender (`:699`),
  and the Unity editor (`install-unity-editor.sh:129`).
- **Spoofing.** `unity_release.py:60` constrains a returned download URL to
  `https` and the `download.unity3d.com` host, and refuses CR/LF/NUL.

### File → parser (R4)

- **Denial of service, and memory corruption by malformed input.** GLB chunk
  walks are bounded by declared length (`gltf_scene.py:158`), the Blender
  export path unpacks an offset with no length check
  (`generators/bind.py:704`), and the shader blob readers check magic and
  minimum length only (`shader_blob.py:666`). The container itself is parsed
  by the pinned `unityz` process (`unityfs.py:58`), not in this interpreter,
  which keeps the worst case out of the tool's own address space.

### Mod XML → parser (R5)

- **Information disclosure.** `references.py:51` parses mod XML with the
  stdlib `ElementTree` and no hardened configuration; the comment there
  states the reason (a zero-dependency core). `patch_check.py:194` uses
  `resolve_entities=False, no_network=True` when the optional `lxml` is
  installed and falls back to the stdlib parser otherwise
  (`patch_check.py:196`), so the hardened parse is conditional on an optional
  package being present.

### Process → `serve` (R6)

- **Elevation of privilege.** `serve` refuses an operation marked `writes`
  unless the server was started with `--allow-writes` (`serve.py:67`), and
  that flag is the only gate. There is no caller identity and no allowlist
  (`api.py:487`): any process holding the pipe has the operator's authority.
  The pipe is the boundary, and it is not authenticated.

### Operator → host process (R7, R8)

- **Denial of service.** `scripts.py:106` runs bash with no timeout, and
  `client.py:1166` launches Steam with no timeout and no process group.
  `unity_process.py:141` is the one place a timeout kills the whole group.

## Mitigations

### Controls that exist

| Control | Covers | Location |
|---|---|---|
| `--allow-network` gate, default off | unwanted upload | `audio_review.py:542`, `video_review.py:509`, `api.py:269` |
| API key in a header, never in argv | credential leak via the process table | `providers/gemini.py:107` |
| Fixed API hosts, https-only redirects | endpoint substitution | `providers/gemini.py:29`, `install-tools.sh:15` |
| Download digest comparison, refusal when none is published | supply chain on the editor, `unityz`, uv, vkd3d, and Blender downloads | `install-tools.sh:552`, `scripts/install-unityz.sh:165` |
| URI traversal refusal for bundle and glTF paths | filesystem escape | `references.py:153`, `gltf_scene.py:180` |
| Deploy name validation, symlink refusal, mod-root refusal | writes outside the intended directory | `client.py:458`, `:484`, `:544` |
| `flock` held across the deploy write | a second session clobbering a live run | `client.py:1384` |
| `shell=True` absent; argv arrays everywhere | command injection | repo-wide; `scripts.py:106` |
| Script registry allowlist | running an arbitrary file | `scripts.py:81` |
| Staged then atomically replaced writes | partial artifact on failure | `atomic.py:25`, `client.py:569` |
| Evidence redaction of sensitive keys | secrets in stored evidence | `evidence.py:46` |
| Unknown config keys refused | silent misconfiguration | `config.py:91` |
| `serve` write gate | accidental mutation over a pipe | `serve.py:67` |

### Gaps, ranked by exploitability then impact

1. **R1**: unverified executable downloads. Highest impact on this host, and
   the only gap with a direct path to arbitrary code execution.
2. **R2**: `--mods-dir` is joined without a containment check
   (`client.py:540`), and `shutil.rmtree(destination)` (`client.py:568`)
   deletes it on a replace. The name is validated; the base is not.
3. **R3**: the unredacted gateway envelope (`video_review.py:720`) and the
   free-text hole in `redact` (`evidence.py:46`).
4. **R4/R5**: no size ceilings in the parsers, and the hardened XML parser
   is conditional on an optional dependency.
5. **R6**: no authentication on the `serve` pipe beyond the `writes` flag.

### Claims the code does not fully back

`docs/architecture.md` lists its destructive-action policy under "Security and
destructive-action policy". Each line was checked against the code; the ones
that hold are `no Unity credentials in config`, `no game-install writes`,
`no shell evaluation of TOML values` (`config.py:9` uses `tomllib`),
`subprocess arguments are passed as an array`, `bundle URI traversal outside
the mod root is rejected`, and `init` refusing to overwrite.

The checksum bullet reads as a general download policy and is not one. The
Unity editor archives and modules are MD5-verified against Unity's own
published digests with an unpublished digest a hard failure
(`scripts/install-unity-editor.sh:129`), and the pinned `unityz` release is
SHA-256-verified (`scripts/install-unityz.sh:165`). Four other tools are not
verified at all (R1). The bullet was narrowed to name the editor, and R1
records the rest rather than leaving a reader to infer coverage.

## Abuse cases

These are scenarios an authenticated, untrusted-role party can reach, each
with the enabling code path named. None was attempted; all are read from the
code.

- **A mod that deploys into another session's client.** A mod tree whose
  `ModInfo.xml` carries a name that passes `_deploy_name` but whose directory
  holds harness files replaces them under `deploy_mod`
  (`client.py:530`), and a `rmtree` at `client.py:568` removes whatever was
  there. The lock stops a concurrent writer, not a hostile payload.
- **A redirect in a glTF that reads the operator's home directory.** Refused
  by `gltf_scene.py:180`; recorded so the guard is not deleted as dead code.
- **An asset that exfiltrates itself.** A bundle member that is a `TextAsset`
  is uploaded when a review is requested with `--allow-network`; the operator
  consented to the upload, but the consent is per-command, not per-asset, and
  the evidence document is the only record of what left.
- **Release supply chain.** A hijacked `gltfpack` release executes as the
  operator at `install-tools.sh:793`.
- **A hostile consumer of `serve`.** A process that can write the pipe calls
  any non-writing operation with the operator's authority, including
  `client_where`, which prints machine paths (`serve.py:67`).

## Response readiness

Recorded as observed, not prescribed: this repository names no security
contact, no supported-versions policy, and no `SECURITY.md`, so there is no
disclosure path to correct or to point at. Events with no audit trail to
investigate from:

- A deploy records no actor and no lock holder beyond the transient
  `flock` record (`client.py:374`), which is removed on release.
- `shamway client capture` is the only citable record of a visual sign-off
  (`capture.py:184`); every other event in the offline gates leaves a console
  line and no file.
- Model reviews write an evidence document with a content hash
  (`audio_review.py:812`), which is the strongest trail in the tool.

## Keeping this current

A change adds to this page when it adds an entry point, crosses a boundary,
adds or removes a mitigation, or changes what the code downloads. The
`path:line` references are the drift check: `tests/test_assets.py` verifies
that every reference in this file names an existing line, so a moved function
fails the suite rather than quietly making a claim false.
