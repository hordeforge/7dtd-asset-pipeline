# Report — <what failed, in the words it was observed in>

Dated `YYYY-MM-DD-<short-topic>.md`.

## TL;DR

- **Observed:** the symptom, as it appeared — the error line, the silent
  clip, the missing icon.
- **Cause:** the one sentence a reader needs.
- **Resolved by:** the change, with its commit.
- **Still open:** the residual risk, or `none`.

## Evidence

What was actually seen, kept verbatim: the failing command, the stderr line,
the classified client log, the `inspect --json` output. Keep this when the
report is resolved; a rewritten incident cannot be re-reasoned.

## What was ruled out

Each hypothesis and the check that killed it. A promising wrong lead is worth
as much as the right one to the next session that starts from the same
symptom.

## Cause

The mechanism, not the symptom — where all the callers route through. Where
the cause is engine behaviour, name the artifact or tool that proved it
(`Data/Config/*.xml`, `ilspycmd` on `Assembly-CSharp.dll`, a bundle from the
game's own `Data/`); "it seemed to work in game" is not a source. If the bug
belonged to a sibling `hordeforge/7dtd-*` repository, say so and link the pull
request that fixed it there.

## Resolution

The change, the test that would have caught it, and the documentation updated
in the same commit.

## Verification

What proves it fixed: the command and its output, the gate that now fails on
the old input, and — where the failure was visible or audible — the fresh
client and the human look or listen. Offline output alone is never the last
line here.

## Follow-up

If the recovery is repeatable, write the procedure in
[runbooks/](../runbooks/) and link it here: this page keeps the history, the
runbook stays current.
