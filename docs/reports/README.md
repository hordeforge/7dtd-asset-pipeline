# Operational reports

This directory preserves the evidence, diagnosis, resolution, and verification
of bugs and investigations that would otherwise be lost in a run log or a pull
request discussion. It complements the reference pages: reference describes
intended behaviour; a report explains an observed failure and the work that
resolved it.

When a resolution becomes a repeatable recovery procedure, write the concise
current procedure in [runbooks/](../runbooks/) and link it from here — the
report keeps its history, the runbook stays current.

## Conventions

- Name reports `YYYY-MM-DD-<short-topic>.md`.
- Every report starts with `## TL;DR`, then gives the detail needed to repeat
  the reasoning without reconstructing it from logs: what was observed, what
  was ruled out and how, the resolution, and the verification.
- Keep the original evidence when resolving; add the fix commit, tests, and
  remaining risk instead of rewriting the incident away.
- Where a claim rests on engine behaviour, name the artifact or decompiler
  tool that produced it — the same rule
  [research/research-provenance.md](../research/research-provenance.md)
  enforces.

## Inventory

<!-- inventory:report:start -->
(none written yet)
<!-- inventory:report:end -->
