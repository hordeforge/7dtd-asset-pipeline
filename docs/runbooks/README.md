# Runbooks — procedures for recurring situations

A runbook is the concise, current procedure for a situation that comes back:
a failure with a known cause, or a checklist a release has to pass. It answers
"what do I check and do now?". A [report](../reports/) keeps the evidence and
the failed hypotheses that explain why the procedure is safe; the runbook stays
short and correct.

## What belongs here

- A recovery procedure for a failure seen more than once.
- A checklist that gates an artifact or a release.

What does not belong: a one-off investigation ([reports/](../reports/)), a
capability gap ([status/improvements.md](../status/improvements.md)), or the
reference description of a gate ([validation.md](../validation.md)).

## Conventions

- Start from [TEMPLATE.md](TEMPLATE.md), and keep `## TL;DR` right after the
  title for a symptom runbook.
- Name a symptom runbook for the symptom, not for the incident that found it:
  `<subsystem>-<symptom>.md`.
- Commands must run as written; substitutions and explanations go in the prose
  around the block.
- Never a step that writes into a 7 Days to Die install, and never one that
  launches a client over a running one.
- Supersede rather than delete a procedure when the recovery model changes.

## Inventory

<!-- inventory:runbook:start -->
- [troubleshooting.md](troubleshooting.md) — failure messages and their root
  causes, from build refusals to a silent clip in a live client
- [release-checklist.md](release-checklist.md) — the artifact, offline-gate,
  and live-acceptance boxes a release has to tick
<!-- inventory:runbook:end -->
