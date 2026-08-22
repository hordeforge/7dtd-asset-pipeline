"""Line-delimited JSON request/response over stdio.

`7dtd-assets call` costs a process start per operation, which is fine
occasionally and wasteful in a loop. `serve` pays it once: a consumer writes
one JSON object per line and reads one JSON object per line back, in order.

No protocol library and no network socket. A local build tool that reads a game
install and drives a Unity editor has no business opening a port, and any
protocol wrapper a consumer wants can be generated from `schema --json`.

Request:   {"id": 1, "op": "status", "params": {}}
Response:  {"id": 1, "ok": true, "result": {...}}
           {"id": 1, "ok": false, "error": {"type": "PipelineError",
                                            "message": "..."}}

`id` is echoed back untouched, and may be omitted. A malformed line gets an
error response rather than closing the stream, so one bad request cannot
desynchronize a long-running session.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, TextIO

from .api import Pipeline, call_json
from .errors import PipelineError
from .operations import get as get_operation
from .operations import manifest

PROTOCOL = 1


def _error(identifier: Any, exc: BaseException) -> dict[str, Any]:
    return {
        "id": identifier,
        "ok": False,
        "error": {"type": type(exc).__name__, "message": str(exc)},
    }


def handle(request: Any, resolve: Callable[[], Pipeline | None], allow_writes: bool) -> dict:
    """Turn one decoded request into one response. Never raises."""
    if not isinstance(request, dict):
        return _error(None, PipelineError("each request must be a JSON object"))
    identifier = request.get("id")
    operation_name = request.get("op")
    if not isinstance(operation_name, str):
        return _error(identifier, PipelineError("request needs an 'op' string"))

    # Built-ins, so a consumer can discover the surface over the same channel
    # it will use to call it.
    if operation_name == "schema":
        return {"id": identifier, "ok": True, "result": manifest()}
    if operation_name == "ping":
        return {"id": identifier, "ok": True, "result": {"protocol": PROTOCOL}}

    params = request.get("params") or {}
    if not isinstance(params, dict):
        return _error(identifier, PipelineError("'params' must be a JSON object"))
    try:
        operation = get_operation(operation_name)
        if operation.writes and not allow_writes:
            raise PipelineError(
                f"operation {operation_name!r} writes files and this server is read-only; "
                "restart it with --allow-writes to permit it"
            )
        pipeline = resolve() if operation.needs_config else None
        return {"id": identifier, "ok": True, "result": call_json(pipeline, operation_name, params)}
    except PipelineError as exc:
        return _error(identifier, exc)
    except Exception as exc:  # noqa: BLE001 - a handler bug must not kill the session
        return _error(identifier, exc)


def serve(
    resolve: Callable[[], Pipeline | None],
    allow_writes: bool = False,
    stream_in: TextIO | None = None,
    stream_out: TextIO | None = None,
) -> int:
    """Read requests until end of input, writing one response line per request."""
    stream_in = stream_in or sys.stdin
    stream_out = stream_out or sys.stdout
    for line in stream_in:
        line = line.strip()
        if not line:
            continue
        try:
            request: Any = json.loads(line)
        except json.JSONDecodeError as exc:
            response = _error(None, PipelineError(f"invalid JSON request: {exc}"))
        else:
            response = handle(request, resolve, allow_writes)
        stream_out.write(json.dumps(response, sort_keys=True) + "\n")
        # Flush per response: a consumer is usually blocked reading this line.
        stream_out.flush()
    return 0
