# RFC NNNN — <the question, phrased as a question>

## Status

Open / Decided (ADR NNNN) / Withdrawn — opened <date>.

An RFC presents options and a recommendation so a decision can be made; it is
not itself the decision. When it is decided, write the [ADR](../adrs/) and name
it here.

## Question

One sentence, phrased so an option can answer it. "Which bundle source do
adopters get by default", not "we should default to synthesized".

**Why now.** What forces the choice: a blocked change, a cost, a failure, a
dependency going away.

**Drivers.** The constraints any acceptable option must satisfy — offline
operation, no writes into a game install, the gate table in AGENTS.md, the
uv-only rule, what an adopting mod may depend on. Keep them concrete enough to
disqualify something.

**Out of scope.** What this deliberately does not decide.

## Current state

How it works today, including the workaround standing in for a decision. Name
the files, commands, and config keys that would change.

## Options

One subsection per option, and the status quo is one of them. Include at least
one option that adds nothing new — an existing command used differently, the
standard library, or doing nothing.

### Option A — <name>

- **What it is:**
- **How it would fit:** files, commands, gates, and docs that change.
- **Pros / Cons:**
- **Cost to adopt / cost to back out:**
- **Evidence:** each link with what it actually shows; mark anything
  unverified as `unverified`.

### Option B — status quo

- **What it is:** keep the current behaviour.
- **Cons:** what it costs over the next year.

## Recommendation

The option, the confidence, and what would change it. Argue the trade-off
accepted, not the pros again. Say how reversible it is and where the point of
no return sits — a written manifest format, a published operation, a staged
artifact.

## Open questions

Each with the spike, measurement, or person that settles it.

## References

Related ADRs, PRDs, reports, and research pages.
