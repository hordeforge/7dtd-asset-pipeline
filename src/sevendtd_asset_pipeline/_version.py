"""The package version, defined here so lower-level modules can read it.

`__init__.py` re-exports it for consumers; `operations.manifest()` imports it
directly, because the registry sits below the package root and must not
import upward into it.
"""

__version__ = "0.4.0"
