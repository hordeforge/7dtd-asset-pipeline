# ADR 0004 — One operation registry behind every surface, and no network server

## Status

Accepted

## Context

Programmatic consumers differ — Python callers, other languages, CI, agents —
but a build tool with several interfaces that describe themselves differently
is worse than one with a single interface. Separately: this tool reads a game
install and writes files on the same machine — and can drive a Unity editor
there, for a mod that opted into one — so a listening port
would be a liability.

## Decision

`operations.py` holds the contract; the `Pipeline` facade, `call`, `serve`,
and the published `schema` all dispatch through it. A test asserts the
registry and the dispatch table name the same operations. No server is built
in: `serve` speaks line-delimited JSON over stdio, and `schema` publishes
enough for a consumer to generate whatever protocol wrapper they actually
need.

## Consequences

The published schema cannot describe behaviour that does not exist — drift is
a failing test instead of a support ticket. The cost is that adding an
operation means registering it in `operations.py`, `_DISPATCH`, and its docs
page in one change, with tests holding all three honest.
