# Digest — <project, paper, or repository>

Named for the subject: `<project-or-paper>.md`.

## What was studied

The thing itself, with the version, commit, or artifact actually read, and why
it was worth a look. A digest that cannot be re-verified against a named
version is a wiki page.

## How they do it

Their approach, in their terms before ours. Enough mechanism that a reader can
tell whether it would survive this project's constraints — offline operation,
no writes into a game install, Unity opt-in (`bundle_source = "synthesized"`
is the default and starts no editor), an adopting mod that checks out
nothing.

## What applies here

The technique worth borrowing, and where it would land: a gate, a generator, a
parser bound, a command. The decision to adopt it is an [ADR](../adrs/), not
this page; an engine fact measured from their artifacts goes in
[research/research-provenance.md](../research/research-provenance.md) with the
tool that produced it.

## What deliberately does not

What was rejected and why — a different engine version, a licence that cannot
ship here, an assumption about a checkout or a network this pipeline does not
make. This section is what stops the next session re-reading the same project
and re-proposing the same idea.

## References

The repository, release, or paper, each with what it actually shows.
