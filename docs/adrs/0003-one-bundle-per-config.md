# ADR 0003 — One bundle per config

## Status

Accepted

## Context

A config could own several bundles, which would let one modlet share build
orchestration across artifacts — at the price of making every naming,
reference, and version check conditional on which bundle it is looking at.

## Decision

Schema 1 intentionally owns one bundle. Multiple bundles use multiple configs
today.

## Consequences

Naming/reference/version validation stays exhaustive and simple. The cost is
that there is no shared build orchestration across a modlet's bundles. A
future schema may model an array only when real consumers need it — not
before.
