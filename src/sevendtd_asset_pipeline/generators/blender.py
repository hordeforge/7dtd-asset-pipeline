"""Running one script inside a headless Blender, for the lanes that need one.

`mesh`, `mesh-icon` and `bind` each own a Blender script, and each has to
answer the same two questions before its own result means anything: is Blender
on PATH, and did the child finish inside its bound. The bound is the same in
all three and is named once here, because a wedged headless start produces no
output and no error of its own — a timeout is the only thing that tells it
apart from a slow render.

What each lane does with the result stays its own: it names the artifact it
expected, so the message when Blender exits without writing it is the lane's
to word, not this module's.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from ..text import CHILD_DECODE_ERRORS, CHILD_ENCODING

# A headless Blender that wedges (a broken userpref, a stuck GPU probe) must
# fail the generator, not hang it. Generating one primitive is seconds of work,
# and the same lane bounds gltfpack at 300s in mesh_optimize.py.
BLENDER_TIMEOUT = 300

ABSENT = "blender is not on PATH. Run scripts/install-tools.sh --with-authoring."


def find_blender() -> str | None:
    """Blender's resolved path, or `None` after saying why there is none."""
    found = shutil.which("blender")
    if found is None:
        print(f"ERROR: {ABSENT}", file=sys.stderr)
    return found


def run_script(blender: str, script: Path, arguments: Sequence[str]) -> tuple[int, str] | None:
    """Run `script` headless, returning its exit code and combined output.

    `None` means Blender was killed for exceeding `BLENDER_TIMEOUT`, and the
    reason is already on stderr. Every other failure is the caller's to judge,
    because only the caller knows what the script was supposed to write.
    """
    try:
        result = subprocess.run(
            [
                blender,
                "--background",
                "--factory-startup",
                "--python",
                str(script),
                "--",
                *arguments,
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding=CHILD_ENCODING,
            errors=CHILD_DECODE_ERRORS,
            timeout=BLENDER_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        print(
            f"ERROR: Blender did not finish within {BLENDER_TIMEOUT}s and was killed; "
            "a wedged headless start is the usual cause.",
            file=sys.stderr,
        )
        return None
    return result.returncode, result.stdout
