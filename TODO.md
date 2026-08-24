# TODO

Two lists already own the *content* of what is left, and stay authoritative:

- [docs/status/blockers.md](docs/status/blockers.md) — things that are built
  but **unproven**, because proving them needs a human, a licence, or a machine
  a coding session cannot reach. Each entry carries the exact command and the
  line that confirms it.
- [docs/status/improvements.md](docs/status/improvements.md) — capability gaps:
  things nobody has built, with the tool that would close each.

This file owns what neither of those does: **the order to do them in, and who
can actually do each one.** Nothing here restates a command that already lives
in `blockers.md`; go there for the how.

## Clear the blockers

Six entries are open. None of them blocks writing code — every one blocks
*claiming* that code works, which is the distinction this repository is built
around. Until an entry is closed, nothing may describe its subject as working,
verified, or accepted.

| # | What stays unproven until it runs | What it needs that a coding session cannot supply |
|---|---|---|
| 1 | `install-unity-editor.sh`'s download-verify-unpack branch | a host without 2022.3.62f2 already installed |
| 2 | Hub sign-in, license activation, Flatpak-to-native copy | a person at a graphical desktop, and their credentials |
| 3 | An **editor-built** bundle surviving a fresh client | a real mod, an editor, and a person who looks at the asset |
| 4 | `render-icon` and six `GeneratedAsset` helpers *executing* | an editor plus a display (or `xvfb-run -a`) |
| 5 | The `external` round trip: build there, stage here | a second machine |
| 6 | A synthesized mesh and its clay icon in front of a player | a live client, and a person's eyes |

### Order to work them

Do them in this order, for reasons that are about cost rather than importance:

1. **6, then 4.** Both need one client session on this host, and 6 needs no
   editor at all — it is the cheapest evidence still outstanding and it closes
   the newest gap, which is the one most likely to be quietly assumed shut.
   Run 4 in the same sitting: the display is already there.
2. **3.** Same session again if an editor-built mod is to hand. It is the
   largest single claim still open — the backend most mods use — so it is
   worth its own deliberate run rather than being folded into 6's.
3. **5.** Needs a second machine, so it waits for one to exist rather than
   for anyone to find time.
4. **2, then 1.** Both are about installing Unity, and 2 is a prerequisite for
   any host that would exercise 1. Neither blocks a single line of pipeline
   work; they block the claim that a bare machine can get to a built bundle.

Entries 1 and 2 are the two this repository will probably carry longest, and
that is correct: 2 is deliberately never automated, and 1 only becomes cheap
the next time someone sets up a fresh host. Do not let their age argue for
weakening them.

### How to close one

Closing a blocker is a commit, not a note in a chat:

1. Run the entry's **You run** block verbatim, on the machine it names.
2. Check the entry's **Confirms it worked** line — the literal output, not
   something that resembles it.
3. In one commit: delete the entry from **Open**, add it to **Verified, for
   contrast** with the *measured output pasted in*, and update whatever page
   made the weaker claim. An entry moved without its evidence is worth less
   than one left open.
4. Where the proof was a person looking or listening, record the frame with
   `shamway client capture LABEL --observable "..."` and say in the entry what
   they were asked to check. "Looked fine" is not a finding; "centred and
   circular, not stretched" is.

If a run **fails**, that is the blocker doing its job. Fix the cause, then
close the entry — never edit the entry to match what happened.

## Everything else

Capability work is [improvements.md](docs/status/improvements.md), which
already carries its own ordering and names the OSS tool for each gap. The two
worth knowing about without reading it: XML patches are scanned but never
applied, so an XPath that matches nothing is silent; and the synthesized
texture and audio lanes are uncompressed, which is a size cost, not a
correctness one.
