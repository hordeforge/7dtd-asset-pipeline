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
| R1 | Four host tools are downloaded and installed as executables with no checksum, from a moving `releases/latest` URL | install script → host | `scripts/install-tools.sh:773`, `:801`, `:870`, `:886` | High |
| R2 | A modlet is copied into the shared client `Mods/` directory, and the destination base is a caller-supplied path with no containment check | build tree → live game client | `src/sevendtd_asset_pipeline/client.py:1553`, `:676`, `:722` | High |
| R3 | Asset bytes leave the host to a third-party model endpoint, the gateway result is stored without redaction, and the API key is carried onto whatever host a redirect names | host → third-party API | `src/sevendtd_asset_pipeline/providers/gemini.py:120`, `:125`, `video_review.py:611`, `evidence.py:85` | High |
| R4 | Mod-controlled and downloaded binary files are parsed in-process with length checks but no size ceilings | file → parser | `src/sevendtd_asset_pipeline/gltf_scene.py:153`, `generators/bind.py:705`, `shader_blob.py:662` | Medium |
| R5 | Mod XML is parsed with the stdlib parser, with no hardened configuration | mod tree → parser | `src/sevendtd_asset_pipeline/references.py:62` | Medium |
| R6 | `serve` has no caller identity: any process that can write the pipe may invoke operations, and only `writes` gates them | process → IPC | `src/sevendtd_asset_pipeline/serve.py:72` | Medium |
| R7 | `shamway script` runs bash with the operator's argv and no timeout | operator → host process | `src/sevendtd_asset_pipeline/scripts.py:106` | Low |
| R8 | The Unity editor download is verified only against an MD5 digest | build → host process | `scripts/install-unity-editor.sh:152` | Low |

R1 and R2 are the two worth a security owner's time. R3 is a deliberate,
consented data flow whose evidence trail is weaker than the flow.

R2 is not only an operator mistyping `--mods-dir`: the base is a parameter of
the published `client_deploy` operation (`operations.py:576`), so a caller on
the `serve` pipe (R6) with writes permitted can aim the deploy anywhere the
operator can write. The *name* is validated (`client.py:591`); the base it is
joined to is not.

## Attack surface

### Entry points

| Entry point | Input | Control | Location |
|---|---|---|---|
| CLI arguments | operator strings | argparse; per-command validation | `src/sevendtd_asset_pipeline/cli.py` |
| `shamway serve` | newline-delimited JSON on stdin | operation registry, `writes` gate | `serve.py:45` |
| `shamway call` / `Pipeline.call` | JSON or kwargs | schema validation only | `api.py:501` |
| Mod source tree | TOML, XML, CSV, images, meshes, clips | per-gate validation | `config.py:288`, `references.py:62` |
| Bundle files | UnityFS container bytes | delegated to `unityz` | `unityfs.py:58` |
| glTF/GLB/OBJ | interchange file bytes and URIs | length checks, URI containment | `gltf_scene.py:153`, `generators/bind.py:705` |
| PNG atlas | IHDR and cell pixels | signature and length checks | `icon_check.py:122` |
| DXBC/SPIR-V blobs | shader compiler output | magic and length checks | `shader_blob.py:662` |
| `review-audio` / `review-video` | clip bytes, intent JSON | `--allow-network` gate | `audio_review.py:492`, `video_review.py:450` |
| `client deploy`, `client hold` | mod tree, arbitrary argv | name validation, `flock` | `client.py:649`, `client.py:505` |
| `scripts/install-*.sh` | remote URLs, versions | checksum on the editor, `unityz`, uv, vkd3d, and Blender downloads; none on four others (R1) | `scripts/install-tools.sh:573`, `:654` |
| Environment | `GEMINI_API_KEY`, `SEVEN_DAYS_TO_DIE_*_DIR`, `PLAYTEST_LOCK_FILE`, `SHAMWAY_SCRIPT_ROOT`, `ZMOLV_*` | read, not validated | `providers/gemini.py:30`, `client.py:138`, `client.py:182` |

There is no network listener. `serve` is stdio by decision
(`docs/adrs/0004-one-operation-registry-and-no-network-server.md`), so the
IPC boundary is a pipe, not a port.

### Surface the code holds that the model must not lose

- The `flock` sidecar every `7dtd-playtest` session reads
  (`client.py:380`), the same lock `scripts/playtest-*.sh` take.
- The per-user `Mods/` directory, which is shared with other sessions on the
  machine (`client.py:150`).
- Provider credentials in the environment, and the evidence documents that
  record what was sent to the provider (`evidence.py:85`).

## Trust boundaries and data flow

| Boundary | Crossing | Validation point |
|---|---|---|
| Mod author → pipeline | TOML, XML, CSV, images, meshes | per-gate; no single chokepoint |
| Mod XML → filesystem | bundle URI | traversal refused: `references.py:225` |
| glTF → filesystem | external buffer URI | `..`, absolute, `%`, NUL refused: `gltf_scene.py:191` |
| Mod tree → live client | deployable files | name validation `client.py:591`, symlink refusal `client.py:617` |
| Pipeline → host process | argv arrays, no `shell=True` | registry allowlist `scripts.py:81` |
| Host → third-party API | clip bytes, intent | `--allow-network` gate, host constants |
| Host → release servers | tool archives | digest comparison on five downloads (`install-tools.sh:573`) |
| Consumer → `serve` | JSON lines | `writes` gate only |
| Game install → pipeline | bytes, config, revision | read-only; no code from it is parsed or executed |

Privilege transitions: `client deploy` writes outside the modlet into a
directory the game loads (`client.py:1560`), and
`client hold -- CMD` runs an arbitrary command under the shared lock
(`client.py:544`). Both are transitions the operator triggers deliberately
and neither is recorded as an identity-bearing event. The first becomes a
caller's transition, not the operator's, whenever `mods_dir` arrives as an
operation parameter over the pipe (R2, R6).

Secrets: `GEMINI_API_KEY` or `GOOGLE_API_KEY` enter from the environment
(`providers/gemini.py:69`), travel as an `x-goog-api-key` header rather than
a query string (`providers/gemini.py:120`), and are never placed in argv. The
video gateway inherits the parent environment
(`video_review.py:333`), so every key in the operator's environment reaches
that child. There is no rotation path in this repository: keys live in the
operator's environment and are revoked there.

## Assets and impact

- **Source assets and modlets.** Corruption or replacement changes what ships
  into a client. Blast radius is the deployed mod, not the repository.
- **The shared client `Mods/` directory and the lock.** Damage here reaches
  other sessions: a bad deploy is read by a live run (`client.py:1562`).
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
  the traversal guard covers the URI path (`references.py:225`) and nothing
  else.
- **Information disclosure.** A bundle URI that resolves outside the mod root
  is refused, so a mod cannot read the operator's tree; the case-insensitive
  walk also refuses a case collision (`references.py:231`).
- **Denial of service.** No bundle size, member count, or vertex count ceiling
  exists in the writer, so a large source exhausts memory in the build
  process rather than failing fast.
- **Elevation of privilege.** A mod that adopts
  `templates/UnityProject/Assets/SevenDaysToDieAssetPipeline/Editor/GeneratedAsset.cs`
  runs C# in the editor when the mod opts into `bundle_source = "unity"`;
  that is a documented opt-in, not a defect.

### Mod author → live client

- **Tampering.** `deploy` copies the allowlisted candidates the mod tree
  holds (`client.py:649`), including root DLLs, and replaces whatever
  deployment shares the name.
- **Spoofing.** The deployed name comes from `ModInfo.xml` (`client.py:1552`);
  `_deploy_name` refuses separators, NUL, control characters, and bidi
  overrides (`client.py:591`), so a name cannot point outside `Mods/`.
- **Repudiation.** A deploy writes no attributable log line; the shared
  directory shows files, not who put them there.

### Host → third-party API

- **Information disclosure.** Clip bytes and the intent document are uploaded
  deliberately, behind `--allow-network` (`audio_review.py:514`). The gate
  precedes credential read and socket open.
- **Information disclosure, second path.** The gateway's whole envelope is
  copied into the evidence document unredacted (`video_review.py:611`), and
  `evidence.redact` drops credential-bearing mapping keys and abbreviates
  home paths but leaves other strings alone (`evidence.py:85`), so a
  credential in free text survives.
- **Information disclosure, third path.** The request is issued through
  `urllib.request.urlopen` (`providers/gemini.py:125`), whose default redirect
  handler follows a 301, 302, or 303 after a POST and copies every request
  header except `content-length` and `content-type` onto the new URL, with no
  scheme or host check. The `x-goog-api-key` header
  (`providers/gemini.py:120`) therefore reaches whatever host a redirect names.
  Read from the running interpreter's own
  `urllib.request.HTTPRedirectHandler.redirect_request` source; no request was
  made. The host scripts pin `https` through their redirects
  (`install-tools.sh:15`) and this Python path does not.

### Host → release servers (R1)

- **Tampering and elevation of privilege.** `gltf_validator`
  (`install-tools.sh:773`), `gltfpack` and `compressonatorcli`
  (both through `install_binary_release`, `install-tools.sh:820`), and
  AssetRipper (`install-tools.sh:870`) are fetched from `releases/latest`
  (`install-tools.sh:886` is the URL resolution the last of them uses),
  extracted, and installed as executables with no digest compared
  (`install-tools.sh:801` is where the first of them is announced and
  installed). A compromised release, a hijacked maintainer, or a MITM against
  a mutable URL runs code as the operator. The four downloads that do compare
  a digest are uv (`install-tools.sh:573`), vkd3d (`:654`), Blender (`:757`),
  and the Unity editor (`install-unity-editor.sh:152`).
- **Spoofing.** `unity_release.py:60` constrains a returned download URL to
  `https` and the `download.unity3d.com` host, and refuses CR/LF/NUL.

### File → parser (R4)

- **Denial of service, and memory corruption by malformed input.** GLB chunk
  walks are bounded by declared length (`gltf_scene.py:160`), the Blender
  export path unpacks the JSON chunk length out of offset 12 with no check
  that the file is even that long (`generators/bind.py:705`), and the shader blob
  readers check magic and minimum length only (`shader_blob.py:662`). The
  container itself is parsed by the pinned `unityz` process (`unityfs.py:58`),
  not in this interpreter, which keeps the worst case out of the tool's own
  address space.

### Mod XML → parser (R5)

- **Information disclosure.** `references.py:62` parses mod XML with the
  stdlib `ElementTree` and no hardened configuration; the comment above it
  states the reason (a zero-dependency core). `patch_check.py:194` uses
  `resolve_entities=False, no_network=True` when the optional `lxml` is
  installed and falls back to the stdlib parser otherwise
  (`patch_check.py:196`), so the hardened parse is conditional on an optional
  package being present.

### Process → `serve` (R6)

- **Elevation of privilege.** `serve` refuses an operation marked `writes`
  unless the server was started with `--allow-writes` (`serve.py:72`), and
  that flag is the only gate. There is no caller identity and no allowlist
  (`api.py:501`): any process holding the pipe has the operator's authority.
  The pipe is the boundary, and it is not authenticated. With writes
  permitted, `client_deploy` carries a `mods_dir` parameter
  (`operations.py:576`), so the same caller can aim a deployment outside
  `Mods/`.

### Operator → host process (R7, R8)

- **Denial of service.** `scripts.py:106` runs bash with no timeout and with
  the operator's whole environment. Everything else that spawns a long-lived
  process bounds it: the Steam launch carries `STEAM_LAUNCH_TIMEOUT`
  (`client.py:1331`), the Unity editor is run in its own session so a timeout
  kills the whole group (`unity_process.py:141`), and the deadeye gateway is
  reaped the same way (`video_review.py:333`).

## Mitigations

### Controls that exist

| Control | Covers | Location |
|---|---|---|
| `--allow-network` gate, default off | unwanted upload | `audio_review.py:514`, `video_review.py:476`, `api.py:278` |
| API key in a header, never in argv | credential leak via the process table | `providers/gemini.py:120` |
| Fixed API host, URL built from a constant and a quoted model name | endpoint substitution on the request this module builds | `providers/gemini.py:29` |
| `https` pinned through every redirect for the host scripts' curl | a 3xx onto `http://` or `file://` | `install-tools.sh:15` |
| Download digest comparison, refusal when none is published | supply chain on the editor, `unityz`, uv, vkd3d, and Blender downloads | `install-tools.sh:573`, `scripts/install-unityz.sh:168` |
| URI traversal refusal for bundle and glTF paths | filesystem escape | `references.py:225`, `gltf_scene.py:200` |
| Deploy name validation, symlink refusal, mod-root refusal | writes outside the intended directory | `client.py:591`, `:617`, `:680` |
| Deploy stages, parks the old copy, and restores it on a failed swap | a crash mid-replace leaving the client with no mod folder at all | `client.py:706`, `:722` |
| `flock` held across the deploy write | a second session clobbering a live run | `client.py:505` |
| `shell=True` absent; argv arrays everywhere | command injection | repo-wide; `scripts.py:106` |
| Script registry allowlist | running an arbitrary file | `scripts.py:81` |
| Staged then atomically replaced writes | partial artifact on failure | `atomic.py:25` |
| Evidence redaction of sensitive keys | secrets in stored evidence | `evidence.py:85` |
| Unknown config keys refused | silent misconfiguration | `config.py:288` |
| `serve` write gate | accidental mutation over a pipe | `serve.py:72` |

### Gaps, ranked by exploitability then impact

1. **R1**: unverified executable downloads. Highest impact on this host, and
   the only gap with a direct path to arbitrary code execution.
2. **R2**: the destination base is taken as given. `mods_dir` comes from
   `--mods-dir` or from the `client_deploy` operation parameter
   (`operations.py:576`), `destination` is that path joined with the
   validated name (`client.py:676`), and the previous deployment parked
   beside it is removed with `shutil.rmtree` (`client.py:722`). The name is
   validated; the base is not, and nothing refuses a base outside the
   game's per-user `Mods/`.
3. **R3**: the unredacted gateway envelope (`video_review.py:611`), the
   free-text hole in `redact` (`evidence.py:85`), and the redirect handler
   that carries `x-goog-api-key` to any host a 301 names
   (`providers/gemini.py:125`).
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
(`scripts/install-unity-editor.sh:152`), and the pinned `unityz` release is
SHA-256-verified (`scripts/install-unityz.sh:168`). Four other tools are not
verified at all (R1). The bullet was narrowed to name the editor, and R1
records the rest rather than leaving a reader to infer coverage.

## Abuse cases

These are scenarios an authenticated, untrusted-role party can reach, each
with the enabling code path named. None was attempted; all are read from the
code.

- **A mod that deploys over another session's client.** A mod tree whose
  `ModInfo.xml` carries a name that passes `_deploy_name` but whose directory
  holds harness files replaces them under `deploy_mod` (`client.py:649`): the
  old folder is parked beside the destination and then removed
  (`client.py:722`). The lock stops a concurrent writer, not a hostile
  payload, and `replace` defaults to on.
- **A caller that aims the deploy elsewhere.** `client_deploy` takes
  `mods_dir` as a parameter (`operations.py:576`) and `deploy_mod` joins it
  with the validated name without asking whether it is the game's `Mods/`
  (`client.py:676`). Over the pipe with writes permitted, that is a caller's
  write, not the operator's.
- **A redirect in a glTF that reads the operator's home directory.** Refused
  by `gltf_scene.py:191`; recorded so the guard is not deleted as dead code.
- **An asset that exfiltrates itself.** A bundle member that is a `TextAsset`
  is uploaded when a review is requested with `--allow-network`; the operator
  consented to the upload, but the consent is per-command, not per-asset, and
  the evidence document is the only record of what left.
- **Release supply chain.** A hijacked `gltf_validator` release executes as
  the operator at `install-tools.sh:801`.
- **A hostile consumer of `serve`.** A process that can write the pipe calls
  any non-writing operation with the operator's authority, including
  `client_where`, which prints machine paths (`serve.py:72`).

## Response readiness

Recorded as observed, not prescribed: this repository names no security
contact, no supported-versions policy, and no `SECURITY.md`, so there is no
disclosure path to correct or to point at. Events with no audit trail to
investigate from:

- A deploy records no actor and no lock holder beyond the transient
  `flock` record (`client.py:380`), which is removed on release.
- `shamway client capture` is the only citable record of a visual sign-off
  (`capture.py:286`); every other event in the offline gates leaves a console
  line and no file.
- Model reviews write an evidence document with a content hash
  (`audio_review.py:684`), which is the strongest trail in the tool.

## Keeping this current

A change adds to this page when it adds an entry point, crosses a boundary,
adds or removes a mitigation, or changes what the code downloads. The
`path:line` references are the drift check: `tests/test_assets.py` verifies
that every reference in this file names a line inside an existing file, so a
deleted file or a shrunken one fails the suite.

That check is about existence, not meaning, and it is worth saying so: on the
pass that found the R8 and R2 claims stale, roughly half these references
pointed at a line that existed and said something else, and the suite was
green throughout. A reference that has moved needs a reader, not a test.
