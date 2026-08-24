# Runbook — <recurring symptom>

## TL;DR

- **Use when:** the observable trigger and its preconditions.
- **Recover by:** the current procedure in one sentence.
- **Verify with:** the command or observation that proves recovery.

## Scope

When this applies and when it does not. Link the [report](../reports/) that
established the procedure, and name the access, install, or version required.

## Diagnose

The shortest safe checks, in decision order, with what each result means and
when to stop rather than apply a recovery meant for another symptom. Prefer the
read-only commands: `doctor`, `inspect`, `refs`, `validate`, `status --json`.

## Recover

The minimal reversible steps. Explain any action with material side effects
before its command, and never a step that writes into a game install or
launches a client over a running one.

## Verify

The command, test, or in-client observation that proves recovery, its expected
result, and what to do when it fails.

## Follow up

The condition that requires a fresh investigation, any cleanup, and the fix
that would make this runbook unnecessary.
