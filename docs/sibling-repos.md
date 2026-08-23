# The other HordeForge repositories

This repository is one of thirteen in the [hordeforge](https://github.com/hordeforge)
organization. Until this page existed it named only one of the other twelve
(`7dtd-engine-research`, cited three times in
[research-provenance.md](research-provenance.md)), so an agent working here had
no way to discover the rest — including the one that owns a runtime lock this
repository's own `client` commands have to respect.

Every description below is the repository's own, taken from its `README.md`.
Nothing on this page describes anyone's machine or how any of these are
deployed; that varies per contributor, and this repository cannot see it.

## The index

| Repository | Called | What its README says it owns |
|---|---|---|
| [`7dtd-asset-pipeline`](https://github.com/hordeforge/7dtd-asset-pipeline) | shamway | this repository: editable Unity assets to a staged `Resources/*.unity3d`, with the gates a successful Unity build does not provide |
| [`7dtd-playtest`](https://github.com/hordeforge/7dtd-playtest) | Vanguard | stock-client gameplay automation against the dedicated server, emitting structured scenario results; ships the live-client exclusivity lock |
| [`7dtd-engine-research`](https://github.com/hordeforge/7dtd-engine-research) | Schematics | reverse-engineering of the V 3.1.0 (b14) dedicated server from the shipped `Assembly-CSharp.dll`: how it behaves, and its wire/file formats |
| [`7dtd-fastconnect`](https://github.com/hordeforge/7dtd-fastconnect) | Hotwire | a client helper for joining local/dev servers without Steam `steam://connect`, plus hooks for automated join tests |
| [`7dtd-server-optimizer`](https://github.com/hordeforge/7dtd-server-optimizer) | Crucible | an adaptive overload governor and Harmony optimization mod for dedicated servers; deliberately no profiler and no load generator |
| [`7dtd-server-apm`](https://github.com/hordeforge/7dtd-server-apm) | Geiger | observability and performance analysis for Linux dedicated servers, with an optional managed method-timing bridge |
| [`7dtd-server-guard`](https://github.com/hordeforge/7dtd-server-guard) | Landclaim | server-side behavioral anti-cheat and exploit mitigation |
| [`7dtd-server-container`](https://github.com/hordeforge/7dtd-server-container) | — | a dedicated server in a rootless podman container, with Crucible and Geiger loaded |
| [`7dtd-fps-bots`](https://github.com/hordeforge/7dtd-fps-bots) | — | server-side FPS bots that pathfind, hunt and shoot; vanilla clients need no mod |
| [`7dtd-loadgen`](https://github.com/hordeforge/7dtd-loadgen) | Screamer | LiteNetLib synthetic clients for load-testing dedicated servers |
| [`7dtd-realearth`](https://github.com/hordeforge/7dtd-realearth) | Pangea | 1:1 scale real-world Earth world generation: elevation, landcover, tile streaming, longitude wrap |
| [`zdtd-server`](https://github.com/hordeforge/zdtd-server) | ZDTD | a clean-room Zig dedicated server targeting the stock client wire |
| [`.github`](https://github.com/hordeforge/.github) | — | the organization profile |

Most of those are server-side and this pipeline neither reads nor calls them.
Two matter to work done here:

- **`7dtd-engine-research`** is a citable source for engine facts, alongside the
  installed game's own `Data/Config/*.xml` and a decompiler. `AGENTS.md`
  already requires a named source for every new engine fact.
- **`7dtd-playtest`** owns the exclusivity lock described next, which
  `shamway client` reads.

## Sharing a live client with 7dtd-playtest

A 7 Days to Die install has one client, and `shamway client deploy` and
`shamway client launch` drive it: `deploy` writes into the client's per-user
`Mods/` folder, and `launch` starts the client itself. When something else on
the same host also drives that client — a `7dtd-playtest` run is the case this
pipeline knows about — the two have to take turns, and a process check alone is
not enough to arrange that. An orchestrator that runs suites back to back
releases the client between them, so a check that only looks for a running
`7DaysToDie.exe` sees "free" in the gap and deploys into the run that starts
seconds later.

`7dtd-playtest` ships the coordination for this in `scripts/playtest_lock.py`:
a `key=value` lock file, `flock`-serialized on a `<lock>.flock` sidecar, with a
heartbeat and a documented staleness window. This repository reads and holds
that same file rather than defining a second one:

```text
~/.cache/7dtd-playtest/playtest_running
```

| Field | Meaning |
|---|---|
| `running` | `yes` while held, `no` when free |
| `session` | the holder's id, `<agent>-<UTC YYYYMMDD-HHMMSS>-<hex>` |
| `acquired` | UTC ISO8601 when the hold started |
| `heartbeat` | UTC ISO8601, refreshed about every 30 s while the holder lives |

`PLAYTEST_LOCK_FILE` overrides the path and `PLAYTEST_SESSION_ID` names the
holder; `PLAYTEST_LOCK_STALE_SEC` (default 120) is how old a heartbeat may get
before the hold counts as abandoned. Override the path only if everything
sharing that client overrides it together. A second path is not a second lock,
it is a holder nobody else can see, which is the failure the lock exists to
prevent.

What `shamway` does with it:

- `client deploy` refuses while another session holds it fresh, because a mod
  dropped into the shared `Mods/` folder is loaded by the holder's next launch,
  not only their current one.
- `client launch` refuses the same way, then holds the lock and heartbeats it
  for the duration of its run, releasing it at the end.
- Both still refuse when a client process is up, whatever the file says. The
  lock covers the gap between runs; the process check covers a lock nobody
  wrote.

Set `PLAYTEST_SESSION_ID` to the holder's session when a `shamway` command is
deliberately part of a run someone else already holds; that is the only case in
which these commands proceed against a held lock.

## Working across repositories

Every `hordeforge/7dtd-*` repository is an independent project: finished work
goes on a branch, through a pull request, and is merged there. Work started
here that turns out to belong in a sibling gets its own branch and pull request
in that sibling, so nothing here waits on an unmerged change somewhere else.
