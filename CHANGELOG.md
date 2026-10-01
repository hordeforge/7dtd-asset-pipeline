# Changelog

All notable changes to `7dtd-asset-pipeline` are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are
the tags (`vX.Y.Z`) that drive the release workflow.

Releases are tag-driven: bump `__version__` in
[src/sevendtd_asset_pipeline/_version.py](src/sevendtd_asset_pipeline/_version.py),
move this file's `[Unreleased]` entries under the new version heading, land
both on `main`, then push the matching tag. The release workflow fails if a
tag has no changelog section.

## [Unreleased]

## [0.8.0] - 2026-10-01

### Added

- `tests/test_analysis_posture.py`, which fails when the analysis itself stops:
  a defect category dropped from ruff's `select`, a mypy strictness flag
  switched off, an analyzer unpinned in the dev group, a `make check` recipe
  that no longer runs an analyzer or no longer fails CI when one is missing, or
  an inline `# noqa`, `# type: ignore` or `# shellcheck disable` that names no
  rule or says nothing about why. The assertions are floors, so adding a
  category or a strictness flag stays allowed.
- `shamway --version`, which printed a usage error instead.
- `--config` on every subcommand, not only before the command name.
  `shamway status --config mod/.shamway.toml` was an unrecognized-argument
  error next to a working `shamway --config mod/.shamway.toml status`, and
  every subcommand's `--help` now shows the flag.
- `make smoke`, the two lines the `test`, `macos` and `capabilities` CI jobs
  each run before the suite (`shamway --help` and `shamway schema`). A
  dispatcher that raised on `--help` failed only after a push, because no
  local command reproduced them. `make all` now runs it alongside `check` and
  `test`.
- `tests/test_fuzz.py`, Hypothesis harnesses over the untrusted-input
  parsers: the `unityz info --json` report mapping in `unityfs.bundle_info`,
  the mod-supplied bundle URI, manifest and `ModInfo.xml` parsing in
  `references`, the DXBC container, token, RDEF and ISGN readers in
  `shader_blob`, and the BC1/BC3 block stream `block_compress.decode` reads.
  Each asserts the parser is total and its accepted result well-formed, over
  structure-aware seeds built from real report and container shapes.
- `make dist` and `make reproducible`, and the release workflow builds through
  the first. Two builds of one tree used to differ in the sdist's tar metadata
  (the build machine's clock, uid, and user name), which made a shipped
  artifact impossible to rebuild and compare; `SOURCE_DATE_EPOCH`, `TZ`, and
  `LC_ALL` are pinned and `scripts/normalize_dist.py` replaces what the epoch
  cannot reach. `make reproducible` builds twice and compares, and both the
  pull-request workflow and the release job run it.
- `.python-version`, pinning the interpreter `scripts/bootstrap` and `make`
  build against. A range resolved on a host with a newer Python installed gave
  a `.venv` outside the matrix CI tests and outside the version a release is
  built with.
- The result types a `Pipeline` method returns are now re-exported from the
  package root: `AcceptanceRun`, `LocalizationReport`, `LogReport`,
  `PatchReport`, `PromptResult`, `TextureReport`, `VerifyReport`, alongside
  `check_texture`, `check_localization` and `check_patches`. A consumer
  annotating the documented `TextureReport` of `check_texture` had to import
  `sevendtd_asset_pipeline.colour` for it, past the line the package draws
  around what is supported. The suite fails when a `Pipeline` method hands
  back a type the root package does not export.
- `docs/consumer-api.md` lists every `Pipeline` method, and the suite fails
  when one exists without an entry: `check_localization`, `check_patches`,
  `review_video` and `expected_unity_version` were callable and unlisted,
  which is the same defect as a method that does not exist.
- A public-API snapshot gate in `tests/test_release_contract.py`.
  `sevendtd_asset_pipeline.__all__` is the supported surface, and a name
  dropping out of it broke a consumer with an `ImportError` and nothing in
  the release notes. A name that leaves the surface now fails the suite until
  the `[Unreleased]` section declares it under `Removed` and the snapshot is
  updated; a name added fails until it is snapshotted, so the next removal
  cannot read as an addition nobody reviewed. This project is 0.x, so the
  minor bump carries the break; the changelog is where the consumer learns
  of it.
- `.shamway.toml` loading refuses a key it does not read, naming the nearest
  real one: a misspelled `compress_texture` was a setting nobody applied, and
  the build behaved as if it had never been asked for.
- Boolean keys must be TOML's unquoted `true`/`false`, and `target`,
  `source_root` and `[unity] version` must be strings. A quoted `"false"`
  became `True`, which switched a lossy encoder on silently.

### Changed

- The pinned unityz install and its `GITHUB_PATH` line were six copies of two
  steps across `ci.yml` and `release.yml`; they are one composite action,
  `.github/actions/setup-unityz`, called by every job that reads a bundle.
  `release.yml`'s test job also runs `shamway --help` and `shamway schema`
  before the suite, the entry-point check `ci.yml` runs and the release job
  was the last publish path without.
- `make check` prints `not run: workflow linting` instead of a skipping note
  when it runs under `CI`. No GitHub runner image carries `actionlint`, so on a
  pull request that gate does not run, and a green `note:` line read exactly
  like a gate that passed.
- The `all` extra is one self-reference,
  `7dtd-asset-pipeline[writer,authoring,mesh,audio,patch]`, instead of a
  hand-copied list of the six requirement strings the five capability extras
  declare. A capability extra that gained a dependency used to keep resolving
  while `pip install .[all]` under-installed the lane the caller was told it
  covers, silently, and the two prose lists of what `[all]` brings were already
  short of it. `tests/test_release_contract.py` now fails when `all` and the
  capability extras disagree, when a package is declared by two extras, when a
  requirement is not a lower bound, and when an extra names a package no
  module under `src/` imports.
- `texture2ddecoder` is pinned to `1.0.6` in the dev group, beside ruff, mypy,
  setuptools, coverage and hypothesis. It is the suite's independent
  block-compression decoder, so a new major that changes its BCn output moves
  the cross-check's verdict, and a `>=1` range let each checkout resolve
  whichever release was newest. The lock already recorded 1.0.6; the
  requirement now says so.
- `review-audio` and `review-video` bound what a submission may carry before
  it costs anything: an intent document over 64 KB or an assembled prompt over
  32,000 characters is refused locally, and `--timeout` must be a positive
  finite number of seconds no greater than 900. The prompt was billable input
  with no limit on it, and a non-positive timeout reached `socket.settimeout`
  and failed there as a traceback rather than as the single `ERROR:` line the
  command surface promises.
- The hosted Gemini adapter resubmits a request the provider says it did not
  take (HTTP 429, 500, 502, 503, 504) up to three attempts, waiting for
  `Retry-After` within an 8-second cap and falling back to exponential backoff.
  A refused credential or any other 4xx is not retried: that is the caller's
  problem, and repeating it only multiplies the cost.
- Both review lanes record `duration_seconds` in the evidence document and the
  report's `usage` block. Token counts arrived from the provider and the model
  version from both sides; the elapsed time was on record nowhere.
- Both review lanes refuse an attachment whose filename carries a control
  character. The name is author-supplied data interpolated into a prompt text
  part, and a line break in it opened a line that read as the pipeline's own
  instruction, which is the channel `fold_author_text` already closes for
  every other author string.
- The three lanes that shell out to a headless Blender (`generate mesh`,
  `generate mesh-icon`, `generate bind`) share one `generators/blender.py`,
  which owns the PATH probe, the `--background --factory-startup` invocation,
  and the 300s bound. Each lane had its own copy, so a fourth lane restating
  them would drift, and a wedge would then hang that lane alone. Behaviour,
  messages, and exit codes are unchanged.
- `docs/architecture.md` states the `providers` credential read that
  `capabilities.py` makes, which the rule it sat under did not admit and
  `tests/test_module_graph.py` has always allowed.
- `CONTRIBUTING.md` gained "Where new code goes", the placement table for a
  change and the registries each one has to be added to.

- `coverage` pinned to `7.10.7` in the `dev` dependency group. It produces
  the number the README coverage badge publishes, and the run that computed
  it resolved it per invocation with `uv run --with coverage`, outside
  `uv.lock` and unpinned, so a release could move the published percentage
  with nothing recorded in the repository. `make coverage` and the
  `coverage-badge` CI job now take it from the same locked dev group as
  `ruff` and `mypy`.
- The published wheel's license metadata moved to the SPDX form.
  `project.license` is the string `MIT` and `license-files` names the
  `LICENSE` the wheel already installed, replacing the `{ text = "MIT" }`
  table and the `License :: OSI Approved :: MIT License` classifier. Both
  were deprecated by setuptools with a 2027-02-18 removal, and a build that
  still succeeds today stops building on a setuptools upgrade. The wheel's
  core metadata carries `License-Expression: MIT` in place of `License: MIT`,
  and `tests/test_release_contract.py` fails if either deprecated form returns.
- The wheel declares a `Homepage` and a `Documentation` project URL, and
  `Programming Language :: Python :: 3.11/3.12/3.13` classifiers matching the
  matrix `ci.yml` tests. A gate in `tests/test_release_contract.py` reads that
  matrix, so the published metadata cannot claim an interpreter the suite does
  not run, or omit one it does.
- `texture2ddecoder` moved from the `writer`, `inspect` and `all` extras to
  the `dev` dependency group. Only the block-compression cross-check in
  `tests/test_block_compress.py` imports it, so a consumer installing
  `7dtd-asset-pipeline[writer]` no longer pays to install a decoder the
  shipped code never calls. The suite still gets it: `uv sync` installs the
  dev group, which is where the cross-check runs.
- `setuptools` pinned to `84.0.0` in the `dev` group, beside the `ruff` and
  `mypy` pins. `setup.py` subclasses `build_py` and mypy type-checks it, so a
  silent setuptools major is as much a gate change as an analyzer release.
- `build-system.requires` floors setuptools at 77 rather than 65. The SPDX
  `license` string and `license-files` above are PEP 639 metadata setuptools
  implemented in 77.0.0, so an isolated build resolving an older backend
  rejected this sdist's own `pyproject.toml`. A consumer installing from the
  sdist with build isolation is who meets that backend; the dev-group pin keeps
  CI green and does not reach their environment.

### Removed

- The `inspect` extra, which listed the same `lz4>=1` the `writer` extra
  already does and unlocked nothing: deep inspection reads type trees that
  ship inside the `unityz` command, so no extra could ever provide it. The
  package is installed from its git URL and is not registered on PyPI, so
  there is no published release whose `[inspect]` request would now fail.
  `pip install '7dtd-asset-pipeline[inspect]'` resolves to an unknown extra
  and installs nothing rather than silently pulling a package it never used.
- `audio_review` and `video_review` re-exported the shared `evidence` helpers
  (`redact`, `sha256_bytes`, `sha256_file`, `SENSITIVE_KEY_PARTS`,
  `USAGE_SENSITIVE_KEY_PARTS`) and an `__all__` that named them, for callers
  that import from the lane module. Both lanes already call them as
  `evidence.<name>`, so the imports existed only to satisfy a test. Import
  them from `sevendtd_asset_pipeline.evidence`, which is where they are
  defined.
- `shader_blob.vulkan_shader_hash`, a two-argument function that ignored both
  arguments and returned 32 zero bytes. The field it filled is not validated
  (a live client renders a stock blob with every byte of it corrupted), so the
  bytes are now the named constant `VULKAN_UNVALIDATED_HASH` the record
  builder splices in directly.
- `capabilities._availability`, a third way to ask the question
  `capabilities()` and `has_capability()` already answer, with no caller
  outside its own test.

### Fixed

- Apt installation continues when its repositories have no optional Zig package and reports the Vulkan codec prerequisite. ASCII suite folding works with Bash 3.2, home redaction covers symlink aliases, and portable tests compare file identity and render epochs using the host date syntax.

- The `macos` job ran the suite through `uv run --no-project`, which resolves
  an ambient interpreter and ignores the `.venv` the same job just synced from
  `uv.lock`. macOS evidence therefore covered no locked dependency at all, so a
  platform break that exists only against a pinned version went unseen. It runs
  `make test` now, on the tree the job installed.
- The vkd3d cache key named the version and the runner but not the recipe, so
  a change to `scripts/install-tools.sh --with-vkd3d-source` kept restoring the
  binary the previous recipe built. `hashFiles` of the installer is part of the
  key now.
- A `Config/**/*.xml` saved as UTF-16 or UTF-32 was refused whole. Its
  encoding is stated with a byte-order mark and no readable declaration, which
  is what a Windows editor's "Unicode" save, Visual Studio and every .NET
  `Encoding.Unicode` writer emit. `validate`, `refs` and `check-localization`
  all stopped with `cannot read`, so a mod whose every key is Cyrillic, CJK or
  Arabic reported no reference and no missing row: a green localization check
  that never read the file it was run against. `text.bom_encoding` is the
  named answer and `references.decode_config_xml` reads the mark before the
  declaration. `read_mod_info` already read one, through `ET.parse`, so the
  package was answering this one question two ways.
- `check-localization` failed a Japanese, Korean, Chinese, Thai or Vietnamese
  `Description` as a missing localization key. The bare-token test that
  separates a key from a sentence is written in English, and English is one of
  the few languages that separates its words with spaces, so a description in
  one of those scripts is a bare token and the gate asked its author for a
  table row for their own sentence. A value carrying no ASCII is reconciled
  only when a row answers for it, so a Russian mod that keys on Cyrillic is
  unaffected, and otherwise it is reported in `notes` as undecided rather than
  failed.
- `tests/test_bundle_verify.py` indexed a `dict[str, object]` directly, so
  `make typecheck` failed on a correct checkout with `Value of type "object" is
  not indexable`. The assertion now compares the whole asset list, which also
  pins its length.
- `tests/test_release_contract.py` read the PEP 639 setuptools floor with a
  `setuptools>=N` pattern, so the exact `build-system.requires` pin
  (`setuptools==84.0.0`) read as no constraint at all and the test failed on
  a correct checkout with `None != 77`. It now reads both forms and treats an
  exact pin as the floor it is, and still fails a pin below 77 or an
  unconstrained requirement.
- Every child process this package runs is decoded as UTF-8 with undecodable
  bytes replaced, through the named pair in the new `text` module. Sixteen
  call sites passed `text=True` and nothing else, so the encoding was
  `locale.getpreferredencoding(False)`: the same `unityz`, `dotnet`, Blender,
  pactl or glTF-validator invocation read differently on a German and a
  C-locale host, and one byte a Windows tool emitted in its own code page
  raised `UnicodeDecodeError` out of `communicate()`, which no call site
  caught, ending the run in a traceback rather than the single `ERROR:` line
  the CLI promises. `tests/test_text.py` fails if a text-mode call site stops
  naming its encoding.
- Bundle stems, atlas PNG stems and `CustomIcon` keys are compared on one
  folded spelling (NFC, then case-folded) instead of `str.casefold()` alone,
  and so is case-insensitive resolution of a `@modfolder` bundle path. A mod
  authored on macOS stores `café` decomposed while `Config/` spells it
  composed: the lookup missed a bundle that was there, and two cells of that
  pair in one atlas passed as two keys where the engine loads one. A name that
  is not byte-identical to the one that answered it is still reported, now
  naming whether it differs in case, in Unicode normalization form, or both.
  `localization_check` now takes its composed spelling from the same module.
- A mod name with no ASCII in it (`日本`, `中文`) produced the same acceptance
  provider assembly name and the same playtest suite id for every such mod, so
  a live-client run could report one mod's suite under another's. The
  identifier now carries a short digest of the name the author typed, as the
  bundle stem already did.
- The pull-request Python matrix cancels its sibling legs on the first red
  (`fail-fast` defaults to true), so one version-specific break reported as
  three unknowns. The legs now run to completion.
- `.github/workflows/release.yml` had no concurrency group, so two runs of
  the same tag could race two non-idempotent `gh release create` calls. Runs
  for a tag are now queued rather than run at once.
- The DXBC readers in `shader_blob` bound-check every field they address
  before using it as an offset or a length: the chunk count, the chunk table,
  a chunk offset, a chunk size, the SHDR dword count, and the RDEF and ISGN
  string offsets. A truncated or mis-declared container raised a
  `struct.error` from the middle of the module, and a count field could send
  `struct.unpack_from` looking 16 GB past a 40-byte buffer. The same
  `PipelineError`-shaped rejection is what an input-semantic name in
  non-ASCII bytes used to break, and it now decodes with replacement as the
  rest of the module does.
- `block_compress.decode` refuses a texture format that is neither BC1 nor
  BC3, dimensions that are not a positive multiple of four, a stream whose
  length is not a whole number of blocks, and a block count that disagrees
  with the dimensions. All four reached NumPy as a bare `ValueError` from a
  `reshape` rather than as an actionable gate failure.
- `validate` and `status` publish the `game-revision` `not run:` line whenever
  no game directory is configured, not only when the mod records no revision
  of its own. Checking the bundle's revision against the mod's own
  configuration is not holding it against the installed game, which is what
  the gate is for, and a mod with a configured `unity.version` reported a
  gate that had not run as one that had.
- `hypothesis` is declared to mypy as an untyped third-party module, and
  `tests/test_fuzz.py` as a module whose test methods are decorated by that
  generator. Both were unhandled, so `make check` failed on every decorated
  harness: the module could not be resolved, and a decorated method counted
  as untyped by construction.
- `generators/hide.py` imports `tileable_noise` from the module that defines
  it, and no longer imports `texture_maps` at all. The re-export it called it
  through was neither used nor exported under `--strict`, so ruff and mypy
  both refused the tree.
- `Config/**/*.xml` is decoded as the encoding its own XML declaration names.
  The read was hardcoded to UTF-8, so a mod authored on a non-English Windows
  locale and saved as `encoding="windows-1251"` failed every gate that walks
  `Config/` with "cannot read" on the whole file, and `check-localization`
  reported no key at all for a mod whose names are all non-ASCII.
- The playtest host scripts no longer read the host's locale where a wrong
  answer follows. `playtest-capture.sh` ranks client logs with `LC_ALL=C sort
  -rn` (a numeric sort parses the timestamp's decimal point through
  `LC_NUMERIC`, so a comma-decimal locale ranked every log as `0` and the loop
  photographed whichever session wrote last) and compares uptime as bash
  integers instead of through `awk`.
- `shamway script playtest-synthesized --look STEM` folds the suite id with an
  ASCII lower rather than bash's `${var,,}`, which follows `LC_CTYPE`: a
  Turkish host turned the `I` in a stem into a dotless `ı` and named a suite
  the orchestrator never runs.
- `json_field.py` and `github_asset_url.py` pin stdio and argv to UTF-8. Under
  a non-UTF-8 locale a mod path or an asset name arrives as lone surrogates,
  and a producer that is not writing UTF-8 is now named instead of producing a
  path the shell cannot open.
- Two mod names written in a script with no ASCII in them derive distinct
  bundle stems. They all folded to the same `mod-assets.unity3d`, and a
  file-stem collision is what makes a mod's assets unreachable.
- `docs/getting-started/setup.md` and `docs/authoring/authoring-tools.md` named
  the pinned `unityz` 0.1.3 and, on the setup page, a commit three pins old,
  while `scripts/install-unityz.sh` has pinned 0.1.10
  (`4f2126382b08370c9b2b016f73dc80bf48df30be`) since 0.6.0. A host followed
  the page and installed a reader older than the writer's. A test in
  `tests/test_scripts.py` now fails when a page names a pinned release or
  commit the installer no longer pins; the historical citations in the
  research pages are left alone, because they are measurements, not
  instructions.
- `hypothesis` is a declared `dev` dependency again. The manifest prune
  dropped it as unused, but `tests/test_fuzz.py` imports it, and a checkout
  without it reports that module as `unittest.loader._FailedTest`, so
  `make check test` failed on a clean clone while reading as a broken suite
  rather than a missing dev dependency. It is pinned at `6.168.2` beside the
  other dev tools.
- `make check test` runs the bootstrapped checkout's own `.venv` when there is
  one. It preferred `uv run --no-project`, which ignores that `.venv` by
  design, so the suite ran without the `dev` group and the Hypothesis
  harnesses in `tests/test_fuzz.py` could not be collected.
- `PLAYTEST_LOCK_STALE_SEC` is refused when it is shorter than two heartbeat
  beats. A hold rewrites its heartbeat every 30 s, so a window of 20 s (or 30)
  expired a live holder's own claim between its beats: `lock_holder` read the
  session free while it was still writing to the lock, and the next caller
  acquired over a run in progress, which is the overwrite the lock exists to
  prevent. A non-numeric or non-positive value was already refused; a
  plausible-looking small one now is too.
- `read_manifest` returns captures in `captured_at` order, as its docstring
  said, instead of the order the file happens to hold. Adoption stamps the
  instant a frame was taken, so a clip captured yesterday and adopted today
  sorted behind one captured an hour ago, and `client capture --list` printed
  a timeline that contradicted the stamp beside each entry. A record whose
  stamp cannot be read keeps its position rather than being sorted on a guess.
- `review-video` puts the evidence document it wrote in its result instead of
  the redaction module. The report's `evidence` key carried a module object,
  so `--json` died on serialization and the text form raised a
  `TypeError` subscripting it: a paid submission completed and then the
  command crashed printing the receipt.
- `review-video --clip` accepts an absolute path. The clip was compared to the
  capture root lexically, and the root defaults to a relative
  `.local/acceptance`, so an absolute path was refused as "never adopted"
  even when this tool had adopted that clip.
- The generator `--help` output names `shamway generate NAME` again. The
  program name was taken by swapping `sys.argv[0]`, which Python 3.14 stops
  reading when the host itself was started with `-m`; each generator now
  states its own `prog` through the shared `generators.command_parser`, and
  `generators.run` clears `__main__.__spec__` for the call alongside the swap,
  so a host started with `-m` (the test suite, a mod's own script) no longer
  advertises `python -m unittest` in the usage line.
- The text form of a model review names the frame an issue sits at, not only
  its timestamp, and both review commands print through one shared function
  (`review-audio` and `review-video` had two copies that had drifted: the
  video one never reported unavailable usage).
- `scripts/coverage_badge.py` writes its SVG with `newline="\n"`, like every
  other text writer in the project. A Windows host no longer gets CRLF line
  ends, which had also tripped the packaged copy through the line-ending gate.
- A hold that borrowed a lock the same session already held no longer clears
  it on the way out. An orchestrator exports `PLAYTEST_SESSION_ID` for the
  whole run, so every command it ran inherited the id, took a borrow, and
  released it: `running=no` went out over a claim the run was still
  heartbeating, and a second session could acquire the client and write into
  `Mods/` under a run in progress. A borrow keeps the run's `acquired` stamp
  and leaves the record held; an aged-out record of the same id is not live
  and is still reclaimed and released normally.
- `client deploy` moves an existing deployment aside for the rename instead of
  deleting it first, and restores it if the swap fails. The delete-then-rename
  left a window in which the folder the client loads from did not exist, and a
  failure or a kill inside it destroyed the previous deployment outright.
- `Pipeline.unity_release()` and `shamway unity-release` resolve the
  revision from the mod's Unity project alone, so on the default
  `bundle_source = "synthesized"` — which creates no project — they failed
  with a missing-file error for a mod that had recorded its revision at
  scaffold time. They now fall back to the installed game, then to
  `[unity] version`, which is what `build` already used.
- A `.gltf` external buffer `uri` is confined to the document's own directory.
  `../../.ssh/id_rsa` or a bare `/etc/passwd` was joined onto the source
  directory and read as vertex data, so an untrusted glTF read any file the
  build process could read.
- A `TextAsset` source file reached the bundle through text mode, so a UTF-8
  BOM became a leading U+FEFF in `m_Script` and every CRLF line end was shipped
  as LF. The source is now decoded from its bytes, which keeps the file's own
  text and drops the BOM.
- `client disable-discord` rewrote the Proton `user.reg` hive from text it had
  decoded with `errors="replace"`, turning any byte that is not valid UTF-8
  into U+FFFD and its CRLF line ends into LF. The edit is now a byte
  substitution that leaves the rest of the hive untouched, and it matches the
  pref on the CRLF file Wine actually writes (the text form only matched it
  because reading the file normalized the line ends away first).
- The generated provider's `ModInfo.xml` wrote a line break in a mod name
  literally, which an XML parser folds to a space, so the file named a
  different mod than the one it was generated from. Tab, newline and carriage
  return are now written as character references.
- `check-localization` names a referenced key whose `Localization.csv` row is
  the same word in a different Unicode normalization form, instead of counting
  it resolved or missing with nothing said about the two spellings.
- An unstated `source_root` now follows `bundle_source` instead of defaulting
  to the Unity project path, which resolved against a mod with no project and
  was then refused as a misconfiguration.
- `PLAYTEST_LOCK_STALE_SEC` is validated: a non-numeric value used to fall back
  to the default silently, and a zero or negative one made every claim read as
  free, which is the path that takes over another session's live client lock.
- The Gemini provider closes the `HTTPError` it reports on, so a failed request
  no longer leaks its socket into a `ResourceWarning` from wherever the
  collector happens to run.
- The BC1/BC3 encoder chose its palette index from a squared colour distance
  computed in int16. A channel difference of 182 already exceeds 32767, so the
  wrapped negative won the comparison and a block whose two colours are far
  apart came back as the wrong one: a black outline on a light panel decoded as
  the panel colour. The distance is int32 now.
- `generate hide --atlas` resized a cell's periodic field to the cell rect
  instead of tiling it. The rects are the least-remainder split of the texture
  across the grid, so a cell a pixel wider than the field had its field raveled
  and refilled from the top-left, wrapping a row of it back inside the cell.
- A generated cylinder's closing quad wrapped onto its first vertex, sampling
  the whole atlas cell in reverse on that one face. The ring now closes at
  `u = 1.0` with a duplicated seam column.
- Generated clips faded to `1/count` rather than to zero at the end, and up to
  `(count - 1)/count` at the start, leaving the step the fade exists to remove.
  `fade_head` is the matching ramp and both reach their end.
- `shamway generate icon --size 0` wrote an empty PNG and then divided by its
  area; the size is refused up front.
- A WAV declaring zero channels reached `len(frames) // (2 * channels)` before
  the mono/stereo refusal, raising a ZeroDivisionError.
- `_ogg_packets` accepted a segment table running past the end of the stream and
  wrote the truncated packets into the FSB5 bank under correct length prefixes.

## [0.7.0] - 2026-09-21

### Removed

- `shader_blob.compile_spirv`, the vkd3d DXBC-to-SPIR-V translation path.
  Production compiles Vulkan sub-programs with `compile_spirv_glslang`
  (glslangValidator), the route Unity itself uses; a live client refused the
  translated module.
- `acceptance.mixed_visual_suites` and `acceptance.reject_mixed_visual_suites`.
  The gate lives in `scripts/playtest-acceptance.sh`, the generated provider,
  and the playtest orchestrator; the Python pair had no production caller.
- `anim.animation_component`, a legacy Animation component dict builder with
  zero production callers.
- `unityz.run_json_lines`, a module-level wrapper only one test used.

### Changed

- `generate cutout` requires numpy (like texture-maps and hide); the
  numpy-free per-pixel fallbacks are gone.
- `Pipeline` call dispatch coerces parameters from each operation's published
  schema instead of six hand-written per-operation converters.
- The type-tree default walker lives in `typetrees.typetree_default`, shared
  by `anim` and `particles` instead of duplicated.
- The audio and video review lanes share one `evidence` module for intent
  decoding, string validation, redaction, and SHA-256; `capture` digests
  through it too.
- `check-sound` reads WAV through `generators/audio.read_wav` instead of its
  own near-identical reader.

## [0.6.0] - 2026-09-20

### Changed

- `gltfpack`'s capability install hint is `shamway script install-tools --with-extras`, matching Compressonator and AssetRipper.

- `scripts/install-unityz.sh` pins unityz 0.1.6 (commit 154332a): the
  release whose default `info` reads the UnityFS block table and
  decompresses only the blocks covering serialized metadata. Binary and
  source checksums were verified against the GitHub release assets.
- `scripts/install-unityz.sh` pins unityz 0.1.7 (commit e819955): ships
  2021.3.45f2 built-in type trees alongside 2022.3.62f2. Binary and
  source checksums were verified against the GitHub release assets.
- `scripts/install-unityz.sh` pins unityz 0.1.8 (commit c99e631): ships
  the extra LTS dumps (2019.4.41f2, 2020.3.49f1, 2021.3.58f1,
  2022.3.76f1, 2023.2.18f1). Binary and source checksums were verified
  against the GitHub release assets.
- `scripts/install-unityz.sh` pins unityz 0.1.9 (commit d97fd0f): format
  2-8 metadata-only `info` (header plus trailing metadata, not the
  object-data hole). Binary and source checksums were verified against
  the GitHub release assets.
- `scripts/install-unityz.sh` pins unityz 0.1.10 (commit 4f21263):
  `trees --builtin` lists shipped dumps; UnityFS `info --json` includes
  `metadata_only`. Binary and source checksums were verified against
  the GitHub release assets.
- `scripts/install-unityz.sh` replaces an existing unityz older than the
  pin. `--check` still reports the >= 0.1.2 contract floor; a host that
  already had 0.1.2–0.1.5 now gets 0.1.6 on the next install instead of
  being skipped.

### Added

- `shamway capabilities --json` probes `compressonatorcli` and
  `assetripper` (install: `shamway script install-tools --with-extras`).
  Neither is required by a pack or inspect command.
- A skipped-without-game `unityz info --json` budget on the 621 MB
  `trees` fallback: 0.2 s wall / 64 MB RSS. Measured 0.006 s / 13.5 MB
  with the 1.15 GB `.resS` sidecar left compressed; stock 7DTD UnityFS
  files in this install have no LZMA or LZHAM blocks.

## [0.5.0] - 2026-09-11

### Changed

- `AGENTS.md` states what this repository owns and does not own, so the
  pipeline / playtest / sandbox boundaries are readable from the repo itself.
  No behaviour change.

## [0.4.0] - 2026-09-05

### Added

- `shamway script cross-read BUNDLE` reads a synthesized bundle with
  AssetsTools.NET (C#, pinned 3.0.5, needs the .NET SDK), a reader that shares
  no code with the writer or with unityz, and prints the revision, platform,
  object table and container entries as JSON. `tests/test_cross_read.py`
  compares it with `unityz info --json --objects` on the self-test bundle
  wherever `dotnet` is present; the two agree on all 604 objects and 50
  container entries. This closes the cross-read the UnityPy removal left owed.

## [0.3.1] - 2026-09-05

### Changed

- `client deploy` and clip adoption refuse symlinks, so a copied tree cannot
  follow a link out of the modlet or capture directory.
- GitHub release-asset URLs, Unity editor download URLs, and Gemini model
  identifiers are restricted to their expected hosts and path-segment shape
  before anything is fetched.
- Host installers follow HTTPS-only redirects, including after a 3xx.

## [0.3.0] - 2026-09-05

### Changed

- The synthesized writer serializes through `unityz create`: `bundle_writer.py`
  still decides path ids, the class-142 container and the resource layout, and
  hands a spec (release trees from `unityz trees --builtin`, object values,
  sidecar) to the pinned unityz, which embeds the trees, writes the
  SerializedFile and UnityFS archive and verifies its own output before it
  lands. The self-test bundle rebuilt this way differs from the previous
  writer's bytes only in the array flag of the two `TypelessData` tree nodes,
  which Unity's own trees carry; the committed fixture was regenerated.
  Packing is about twice as fast (1.1 s vs 2.4 s for the self-test source).
- `shamway inspect --deep` reads a stripped SerializedFile of a release unityz
  packs (2022.3.62f2) through `--builtin` instead of refusing it; a stripped
  file of any other release is refused by name.
- `anim.py` and `particles.py` take their version-correct defaults from the
  same `unityz trees --builtin` export.

### Removed

- UnityPy. It is no longer a dependency, an extra, or a capability; the
  `writer`/`inspect`/`all` extras keep lz4 and texture2ddecoder only. The
  `doctor` writer row and the `pack`/`inspect_deep` operations now declare
  `unityz`. Historical measurements keep their UnityPy attribution.

- `scripts/install-unityz.sh` pins unityz 0.1.4 (commit 9218681): the
  release that carries the built-in 2022.3.62f2 type-tree database
  (`trees --builtin`) and from-empty bundle creation (`create`). Binary and
  source checksums were verified against the GitHub release assets.

### Added

- **`shamway generate bind`** — skin an authored glTF/OBJ onto a shipped
  rig (`--rig`, `--height`, `--stretch-x`, `--solidify` for open shells,
  `--head-lift` for a head-local OBJ, `--neck [M]` to fill the torso hole
  with a cylinder, `--voxel M` to fuse overlapping extras, `--anim` for Idle1+Walk).
  After AUTO it pins the pelvis to Hips and paints thigh/shin/foot shafts
  to those bones so Idle1 walk cannot crumple the butt or freeze the shins.
  `--head-lift` places the
  head by its lowest vertex, not its origin (origin-lift parks a
  head-local mesh in the neck hole). Same arguments produce the same bytes.
  Lifts `Root` to the glTF scene root so clip paths resolve. SelfTestMod's
  humanoid, dinosaur and arachnid fixtures are bind output, not one-off
  remeshes.
- **Remeshed humanoid, dinosaur and arachnid fixtures** — SelfTestMod's
  `shamwaySelfTestHumanoid` is `generate bind --head-lift --neck --anim`
  with Idle1 A-pose (Z drop composed with Y arm swing);
  `shamwaySelfTestDino` and `shamwaySelfTestArachnid` are bind output on
  the shipped shamway rigs so Idle1 walk+spin still plays. `generate entity`
  still emits primitives; arachnid no longer meshes Middle/Lower (that was
  the 16-leg look).
- **Improved remaining-rig silhouettes** — bird body is a Z-keel (not a
  stack of Y-cylinders) with a neck that reaches the head and legs that
  reach the feet; dinosaur is a horizontal theropod with a large forward
  skull and a heavy tail; crocodile is a low wide hull with a laterally
  compressed paddle tail, short side-legs, a toothed snout and two rows of
  osteoderms; arachnid abdomen is a flat box and legs splay outboard;
  humanoid arms are X-boxes along the shoulder chain. Remaining-rig Idle1
  marches in place, yaws the root through a full turn (the creature turns
  with its legs), and sways the tail. Humanoid Idle1/Walk use a 0.55 rad
  stride on the thighs and drop the T-pose arms about Z while swinging
  them about Y. Parts accept a local `offset`.
  `docs/authoring/entities.md` now opens with the `generate creature` on-ramp.
- **Shipped-rig reference creatures at the quadruped construction bar** —
  bird, arachnid, dinosaur, crocodile and humanoid now generate as a skinned
  mesh, a per-part UV atlas, spawnable `entityclasses.xml` (`Prefab` + `Mesh` +
  `UserSpawnType`), and Idle1/Walk clips. SelfTestMod ships those five as
  bundle members with role-aware hides (slate / charcoal / olive / rust / tan).
  `--anim walk` is body-plan-aware: biped thighs on humanoid/dinosaur, four
  legs on crocodile (and quadruped), eight legs on arachnid, perched legs on
  bird — wings are never Walk legs; idle on a bird also flaps. `shamway
  generate creature` is the one-shot on-ramp (calls `generate entity` then
  `generate hide`); `--scale` and `--coat NAME` (moss, brown, cream, slate,
  olive, rust, charcoal, tan) are the size and coat morphs.
- **`compress_audio`: the editorless writer encodes Vorbis** — a clip becomes an
  FSB5 Vorbis bank (mode 15) instead of PCM16, measured 44x smaller on a
  one-second tone (57x stereo). `compress_audio = true` in `.shamway.toml` or
  `shamway pack --compress-audio`; **off by default** because it is lossy and
  because no live client has played one yet. Needs FFmpeg (`transcode.as_vorbis`)
  to encode and the `fsb5` capability for the setup-header catalogue.
  An FSB5 Vorbis bank carries no setup header — the decoder rebuilds it from a
  CRC-32 — so the writer verifies per clip that the header libvorbis produced is
  one FMOD can rebuild, and that its blocksizes match the ones the decoder would
  derive, and **refuses** otherwise rather than writing a bank that decodes to
  noise. 96000 Hz has no catalogued header and is refused; PCM still takes it.
  The container layout, the CRC-32 mechanism and the measurements (164/164
  catalogued headers reproduce as `zlib.crc32` of libvorbis' setup packet; 198
  of 198 rate × channel × quality combinations usable; round trip through
  `python-fsb5` at 40.1 dB SNR) are in `docs/research/research-provenance.md`,
  "FSB5 Vorbis". Closes improvements §4's audio half.
- **Environment-lane runtime helper: documented-and-per-mod** — `docs/authoring/environment-effects.md`
  gains a copy-paste reference implementation of the capture/clamp/restore
  discipline, and the §6 RFC call is decided (option a) in
  `docs/adrs/0007`; the pipeline does not ship game-runtime C# (it is tooling,
  not mod content, and `make check` cannot compile a runtime assembly).
- **`validate` runs the patch gate** — `check_patches` is folded into
  `validate_mod`, so a Config/ patch XPath selecting zero nodes fails the
  default gate (it was already `shamway check-patches` standalone).
- **`check-patches` evaluates selectors with lxml (full XPath 1.0)** when the
  optional `patch` extra is installed — matching the engine's `XPathEvaluate` —
  and falls back to the standard-library subset otherwise. `lxml` is a new
  optional capability (in `capabilities.REGISTRY`, extra `patch`); a selector
  the available evaluator cannot run is still reported as not checked, never
  guessed.
- **`shamway check-patches`** replays every structural operation XPath in
  `Config/*.xml` against the installed game's read-only `Data/Config/<stem>.xml`
  and fails the ones selecting zero nodes. The engine silently no-ops a
  zero-match XPath (`XmlFile.GetXpathResultsInList` returns false, the operation
  returns 0), so a typo'd/renamed selector ships unapplied with no error; the
  decompiled rules are in research-provenance. An XPath the standard-library
  subset cannot evaluate is reported as not checked rather than guessed.
- **`ModInfo.xml` schema is gated** — `validate` now checks `<Version>` is
  present and a dotted-numeric version and `<Description>` is non-empty
  (`references.check_mod_info_schema`). A missing/malformed version ships a
  stale mod version and a missing description a blank mod-list row, neither of
  which errors in game.
- **Property-based tests for the UnityFS reader** (`tests/test_property.py`,
  Hypothesis, dev-group dep). `inspect_bundle` must succeed or raise the
  reader's own `PipelineError` on arbitrary bytes, hostile class IDs, hostile
  node sizes / archive flags / truncation, and hostile LZ4 payloads — never a
  leaked `struct.error`/raw exception that a caller turns into a traceback.
- **`shamway check-localization`** reconciles every localization key Config/
  references (item/block/entity_class names plus bare-token
  `display_name`/`Description`/`desc_key`/`tooltip` values) with the mod's
  `Config/Localization.csv` and the game's vanilla table, failing a referenced
  key provided by neither when the mod ships a CSV (a dropped row is a bug —
  `Localization.Get` returns the key itself on a miss, so it shows as a raw
  name). A mod with no CSV is reported as untranslated rather than failed;
  `--no-vanilla-keys` fails vanilla keys too.
- Generated entity bones **carry colliders**: the writer adds a small
  `BoxCollider` to every skinned bone GameObject, so the game's physics body
  builds real colliders instead of `NullCollider`s
  (`PhysicsBodyInstance.bindCollider` looks for a Box/Capsule/Sphere collider
  on each referenced bone and, finding none, created a null collider — the
  real root cause of a generated creature floating). A generated creature is
  now physically solid and grounds when the engine simulates it (e.g.
  server-side). **Grounded walking is still not demable in the client-side
  look harness:** the client does not gravity-simulate a client-spawned
  entity — measured, the creature holds its +3 m spawn offset (y=64.08) with
  the colliders present. A server-side spawn (or a harness that simulates the
  spawned entity's gravity) is the outstanding, non-asset step; recorded in
  research-provenance.
- **`shamway generate hide`** draws a seeded fur/hide albedo for a
  generated entity — mottled patches, anisotropic fur clumps, hair grain
  (periodic by construction, so a primitive's default UVs never show a
  seam) — with no image model and no host packages beyond Pillow and
  NumPy. Same seed, same bytes. `--patch` adds a second, darker tone
  (spots), which is what keeps a creature readable against whatever the
  biome is — a single flat hue disappears into the forest or the dirt.
  The self-test creature's skin is the two-tone coat (`--base 192,180,152
  --patch 70,55,40`), so the leg-boundary is judgeable in a look run.
- Generated quadruped **paws are now chunky and visible**: the default
  quadruped parts had 0.045 m-tall paw boxes that read as nothing at the
  distance a look run photographs from — the creature looked legless and
  "clipped into the floor". The front paws are now 0.10×0.15×0.09 m and
  the rear 0.11×0.17×0.10 m, so the feet read at a glance.
- Generated entities **attack, die and jump**: `--anim` grows `attack`,
  `death` and `jump` — `Attack1` jabs the head forward and back (a
  half-sine, never past rest — that overshoot is the nervous-bob look —
  with a quarter body pitch), `Death` rolls the body over once and stays
  down (`loop: false` → `m_WrapMode` 1), and `Jump` hops the body.
  `parse_anim` accepts them plus `loop` and `body_bone`; `clip_fields`
  picks the wrap mode from the entries. The self-test creature carries
  all six kinds, and the attack and death clips were signed off in a live
  client on 2026-08-30.
- Staged look prefabs **sit on the ground**: the generated look case
  grounds its prefab at `World.GetHeight` + 1 — the chunk's actual
  top-block height map, the exact query the game's own spawner uses for
  ground entities (`chunk.GetHeight(...) + 1`, reverse-engineered from
  `World.FindRandomSpawnPointNearPosition`), rebased to absolute
  coordinates with `Origin.position`. An animated entity now moves against
  the terrain instead of hovering in front of the camera. (Three wrong
  ground queries are recorded in research-provenance: `GetHeightAt` is the
  uncarved generator heightmap, `GetTerrainHeight` is the generator's
  cached height that ignores voxel edits — it sat the entity ~2 blocks
  under the visible surface — and a raw rebased query hit the map-origin
  column. The staging rotation also no longer pitches the prefab by the
  camera's look angle.)
- Generated entities **walk and look around**: `--anim idle,head,walk`
  writes legacy clips — `Idle1` (a body bob merged with a slow head yaw)
  and `Walk` (a trot: upper legs swing, knees bend the opposite way, the
  body dips between steps, diagonal pairs move together) — with the bone
  paths picked rig-aware from the rig's own names. The `.anim.json`
  declaration is the extension point (any clip name the engine's
  controller plays; entries merging by name). The self-test creature's
  turntable clip was signed off for motion, the gait as a recorded
  milestone.
- Generated entities **move**: `generate entity --anim` writes a
  `{stem}.anim.json` (a looping `Idle1` bob on the rig's first bone) and
  sets `AvatarController=GameObjectAnimalAnimation` on the entity class;
  the writer attaches a legacy `Animation` component with the declared
  clips to the prefab root. Legacy clips serialize their curves directly
  (`m_MuscleClipSize = 0`, measured from the game's animals.bundle), so
  they are synthesized through the type tree with no editor. The self-test
  creature is animated and its turntable look suite captures a motion clip;
  the rig looks and the motion were signed off in a live client on
  2026-08-30.
- The generated entity is now spawnable and visibly textured:
  `generate entity --xml` emits `UserSpawnType="Menu"` (the console
  `spawnentity` command lists only non-`None` classes — verified from IL),
  and the self-test creature ships a 256×256 albedo. The creature's look
  is its own suite (`shamwayselftest_shamwaySelfTestCreature_look`), not
  stacked with every other prefab. The default `playtest-synthesized` run
  asserts the creature's texture loads at its authored size.
- `examples/SelfTestMod` ships a hierarchy (`timedNuke` / `armedLamp`), a
  skinned `gear` prefab, and a looping `burst` VFX graph whose cards come
  from `shamway generate particle-card` (haze flash/smoke, streak sparks).
  `playtest-synthesized` runs `shamwayselftest_editorless` and asserts the
  live client found the named child, bound both skinned bones, and
  instantiated the particle prefab. Visual sign-off of the looping VFX is
  `playtest-synthesized.sh --look` (`shamwayselftest_burst_look` only —
  never comma-listed with `*_block_*`, never stacked with other prefabs).
- The entity lane: `shamway generate rig` emits a bone-structure template as
  a glTF armature (a shipped 20-bone `humanoid` rig, any custom spec, rigid
  validation), and `shamway generate entity` skins procedural primitives to a
  rig and writes the `entityclasses.xml` patch (mandatory `Prefab` + `Mesh`
  bundle URI). Both feed the writer's skinned lane, and the generated
  prefab is proven by UnityPy read-back.
- Seven more shipped rigs, each with its own default part set:
  `quadruped` and its `quadruped-small`/`quadruped-large` size variants
  (one-line `"base"` + `"scale"` specs), `bird`, `dinosaur`, `arachnid` and
  `crocodile`. A rig spec can now carry `"scale"` and extend another rig by
  `"base"`, and both generators take `--scale` on top — bones and parts
  scale together.
- The self-test fixture (`examples/SelfTestMod`) now carries a generated
  skinned entity beside the prop: `playtest-synthesized` asserts in a live
  client that the entity prefab comes back with its `SkinnedMeshRenderer`
  and that its weighted mesh loads with its vertex stream, and `validate`
  cross-checks the entity's `entityclasses.xml` URIs against the manifest.
- Editorless `bundle_source = "synthesized"` now writes named glTF prefab
  hierarchies (including an `armedLamp` child), `SkinnedMeshRenderer` from a
  glTF skin (bind poses, weights, bone-name hashes; never flattened to
  MeshRenderer), and ParticleSystem / ParticleSystemRenderer graphs from a
  versioned `.vfx` declaration, with transparent and additive particle
  shaders that do not reuse the opaque `Shamway/Unlit` pass.

### Changed

- Bundle-writer round-trip tests now inspect Python-authored fields, resource
  sidecars, meshes, and prefab references through the pinned unityz CLI instead
  of UnityPy.
- Prefab, hierarchy, skinned-mesh, particle, and generated-entity tests now use
  unityz object trees and path IDs for their independent bundle readback.
- Animation serialization tests now use unityz for legacy clips, curves,
  components, and figure hierarchy path IDs.
- Shader and material round trips now use unityz object trees and enriched
  shader-record decoding instead of UnityPy object wrappers and its LZ4 helper.
  All test-reader domains are migrated; the two creation-side capabilities in
  `TODO.md` remain before the runtime UnityPy dependency can be removed.
- `scripts/install-unityz.sh` installs the pinned unityz 0.1.3 release
  binary (Linux x86_64, macOS arm64, checksum-verified) instead of building
  from source; other platforms and `UNITYZ_FROM_SOURCE=1` still build the
  pinned commit with Zig. CI no longer installs Zig for it.
- `shamway generate audio from-bank` delegates FSB5 parsing and WAV/OGG
  extraction to the pinned unityz CLI. An incomplete decode is now a non-zero
  command failure instead of a partial reference set; python-fsb5 remains the
  independent writer check and Vorbis setup-header catalogue. The remaining
  UnityPy type-tree parity gap and separate fresh-writer contract are tracked
  in `TODO.md` and `docs/status/improvements.md`.
- Usage docs for this session's surfaces: `docs/authoring/vfx.md` field
  reference and `--look` recipe; `no-unity.md` `.vfx` membership;
  `validation.md` `PLAYTEST_CONCERN_SUITES`; `consumer-api.md` /
  `quickstart.md` synthesized vs `--look`; troubleshooting for mixed
  suites and the unsigned-off burst haze.
- The self-test `burst` look stages flash, smoke and sparks as one prefab
  (that is allowed). They used to share one origin, so the additive gold
  flash hid the other layers. Each system now has a distinct
  `shape.position` (smoke left, flash centre, sparks right).
  `docs/authoring/vfx.md` documents that as the reusable `.vfx` surface
  (`shape.position` / `shape.rotation`, `shamway generate particle-card`);
  any synthesized mod uses the same commands. Grey haze is still not
  readable at `--look` — parked as improvements.md §8.
- AGENTS.md and CONTRIBUTING.md state the uv rule as a run contract: bootstrap
  **this** checkout, then `uv run --project . shamway` / `.venv/bin/shamway`.
  A sibling clone's venv or the system interpreter is a different environment.
- One concern per playtest run: `playtest-synthesized` declares its
  default trio as `PLAYTEST_CONCERN_SUITES` so the harness can refuse an
  undeclared comma-list of unrelated features. `--look` is a separate
  invocation. A child that is part of a built prefab is not a second
  suite.
- `make check` enables the ruff rule groups the tree already passed
  (debugger leftovers, builtin shadowing, naive datetimes, blanket
  ignores, and the pie/return/raise/logging/version-compare sets) and
  extra mypy codes (bare `# type: ignore`, truthy-bool, possibly-undefined,
  exhaustive-match, and related) plus `strict_bytes` and
  `strict_equality_for_none`.

### Fixed

- The entity lane's "the generated creature is invisible because `Shamway/Unlit`
  does not skin" conclusion was **refuted** (research-provenance, improvements,
  entities, no-unity). A re-run of `verify-bundle --draw` (editor 2022.3.62f2)
  shows the four generated entities draw 6–26% with `Shamway/Unlit` as-is; only
  the flat two-bone `gear` fixture rasterizes nothing, and its own material
  draws on a built-in cube. `Game/SDCS/Skin` (the shader the earlier live swap
  called "the player's skinning shader") binds **no** blend channels in any of
  its 198 d3d11 vertex sub-programs — it draws the mesh in bind pose and does
  not skin — so that swap proved the mesh is renderable, not that a shader must
  skin. Authoring GPU skinning into `Shamway/Unlit` is therefore not the fix;
  the live-client creature invisibility is a separate, un-diagnosed problem.
- `docs/authoring/environment-effects.md` no longer tells a mod to set
  `bundle_source = "unity"` for the particle character layer. That layer is a
  `.vfx` declaration on the synthesized path; weather itself still needs no
  bundle.
- Bone-name hashes are CRC-32 of the slash-separated Transform path starting
  at `Origin` (`Origin/Hips` is 1722913273, matching nomad.bundle
  `bodyCloth`), not of the leaf GameObject name.
- `pack_directory` no longer swallows a glTF parse error and flatten a
  broken skin to MeshRenderer. A skin whose joints are out of range fails
  the pack.
- `playtest-synthesized.sh` asserts the self-test mesh at its authored
  1 × 1 × 1 m bounds, and runs `shamwayselftest_block_model` so the prop is
  `SetBlockRpc`'d onto a grounded voxel and looked at there (AtomicDoomsday's
  placed bomb/detonator pattern). The previous look case instantiated the
  prefab 1.2 m in front of the camera, and the block-model suite then yanked
  the ModelEntity into the same spot.
- Generated prefab look cases are **one suite per prefab**
  (`<mod>_<stem>_look`), 3.5 m off the camera, and call
  `CaseDef.RegisterStaged` so instances cannot overlay. Putting every mesh
  in one `*_look` suite stacked a particle system, a skinned mesh and a cube
  on the same point. `<mod>_bundle` is loads only. An undeclared comma-list
  of suites is refused; `*_look` with `*_block_*` is refused even when
  declared. A ModelEntity block is judged by placing it.

- Shared-client lock heartbeats are parsed the way `7dtd-playtest` writes
  them (Z, numeric epoch, offset, naive-as-UTC). A `running=yes` record whose
  stamp cannot be read stays held, so a live claim is not overwritten.
- `latest_client_log` accepts a log whose mtime falls in the launch's whole
  second, so a 1-second-resolution filesystem no longer reports "the client
  did not start" for a client that did.
- Capture `captured_at` is the file mtime in UTC regardless of the host
  timezone, including during EDT in `America/New_York`.
- `playtest-capture.sh` times its wait against `/proc/uptime`, so an NTP
  step cannot fire or stall the 900s timeout.
- `doctor` and `build` locate Windows Build Support from the editor binary's
  real assembly root (`Editor/Data` on Linux and Windows, `Unity.app/Contents`
  on macOS) instead of always looking next to the executable.
- Scratch directories honour the host cache directory (`~/Library/Caches` on
  macOS, `%LOCALAPPDATA%` on Windows) when `XDG_CACHE_HOME` is unset.
- The zmol-v search and `install-tools.sh` copy the shared library Zig actually
  emits (`.so` / `.dylib` / `.dll`), not only `libzmolv.so`.
- `render-icon` passes `-force-glcore` only on Linux, where Xvfb needs it;
  macOS and Windows editors keep Metal and D3D11.

## [0.2.0] - 2026-08-26

### Added

- `acceptance-provider` operation and `shamway acceptance-provider` command:
  generates the 7dtd-playtest scenario provider that loads every bundle member
  through the game's own `DataLoader` in a live client.
- `check-texture` operation (`shamway check-texture`): checks a generated
  texture against what generation actually gets wrong — its mean colour against
  the `material.color` it replaces, compared in sRGB.
- `review-audio` / `review-video` operations (`shamway review-audio`,
  `shamway review-video`): advisory model-assisted semantic review of a clip or
  recording; refuse without explicit network consent and never replace the
  human listen or look.
- `ConfigNotFoundError` in the package's public exports, so scripts can catch
  a missing `.shamway.toml` without catching every pipeline error.
- `make locked`, run by `make check`: fails when `uv.lock` has drifted from
  `pyproject.toml`, which is what every CI job dies on.

### Fixed

- Every CI job had failed at install since the version became dynamic:
  `uv.lock` still recorded a literal `0.1.0` and `uv sync --locked` refused it.
- `make check test` never returned. `test_the_wait_expires_and_names_the_stale_log`
  mocked `time.monotonic` to a constant and `time.sleep` to a no-op, so
  `latest_client_log`'s poll loop spun forever. That file now runs in 0.004s.
- A built wheel shipped stale documentation and host scripts. The sdist
  carried no top-level `docs/` or `scripts/`, so `setup.py`'s staging step
  found nothing and silently kept whatever was already staged in the build
  tree. `MANIFEST.in` grafts the sources and prunes the staged copies, and
  the release workflow now compares the built wheel against the tagged tree.
- The coverage-badge step ran `git remote add origin` outside the `else`
  branch its comment places it in, so it also ran on the clone path, where
  the remote already exists, and failed the step under `set -e`.
- CI ran under the implicit `bash -e`, which has no `pipefail`, so
  `shamway build | tee log` reported `tee`'s exit code and passed on a
  failed build.

### Changed

- Scratch work is staged under `$XDG_CACHE_HOME/shamway` (`~/.cache/shamway`)
  instead of `/tmp`, which is tmpfs on most Linux hosts. This covers the
  decoded WAV, the rasterized sheet, the Blender render, the three shader
  compiles, and the multi-gigabyte editor archive `install-unity-editor.sh`
  downloads. An exported `TMPDIR` is respected.
- The shell scripts and the CI workflow call sibling `.py` helpers instead of
  embedding Python in heredocs and `python -c`, so each file stays one
  language and the CI assertions are linted and type-checked like the rest of
  the tree.

## [0.1.0] - 2026-08-24

Initial tagged release: synthesized UnityFS bundle writing with no editor,
offline gates (revision match, class-142 object, stem collisions, mesh UVs,
clip format, icon atlas), the `shamway` CLI and its JSON operation surface,
and the scaffolded standalone modlet layout.
