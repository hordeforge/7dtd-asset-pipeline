class PipelineError(RuntimeError):
    """A user-actionable pipeline failure."""


class ConfigNotFoundError(PipelineError):
    """No `.shamway.toml` exists at or above the starting directory.

    A subclass, not a message convention: a caller that can proceed without a
    configuration (the stateless operations) must be able to catch exactly
    this case and refuse every other one. Swallowing all of `PipelineError`
    turned a malformed file into "needs a mod configuration", which sent the
    reader looking for a missing file that was there all along.
    """
