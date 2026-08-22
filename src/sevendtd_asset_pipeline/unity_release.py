"""Resolve official Unity editor downloads for an exact revision.

The installed game names the revision, but Unity's download URLs are keyed by
changeset, so a hardcoded table goes stale on every game update. Unity's public
release service maps version to changeset, per-platform archives, and the MD5
each download must match, which keeps the installer generic and verifiable.

Source: <https://services.api.unity.com/unity/editor/release/v1/releases>
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .errors import PipelineError

RELEASE_API = "https://services.api.unity.com/unity/editor/release/v1/releases"
CHANGESET = re.compile(r"/download_unity/([0-9a-f]+)/")
WINDOWS_MONO_MODULE = "windows-mono"


@dataclass(frozen=True)
class Download:
    url: str
    md5: str | None


@dataclass(frozen=True)
class Release:
    version: str
    changeset: str
    editor: Download
    windows_mono: Download | None

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "changeset": self.changeset,
            "editor_url": self.editor.url,
            "editor_md5": self.editor.md5,
            "windows_mono_url": self.windows_mono.url if self.windows_mono else None,
            "windows_mono_md5": self.windows_mono.md5 if self.windows_mono else None,
        }


def _md5(integrity: object) -> str | None:
    """Decode Unity's ``md5-<base64 of the hex digest>`` integrity field."""
    if not isinstance(integrity, str) or not integrity.startswith("md5-"):
        return None
    try:
        digest = base64.b64decode(integrity[4:], validate=True).decode("ascii")
    except (ValueError, UnicodeDecodeError):
        return None
    return digest if re.fullmatch(r"[0-9a-f]{32}", digest) else None


def parse_release(payload: dict, version: str, platform: str = "LINUX") -> Release:
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise PipelineError(f"Unity's release service knows no version {version}")
    entry = results[0]
    downloads = [
        item
        for item in entry.get("downloads", [])
        if item.get("platform") == platform and item.get("architecture") == "X86_64"
    ]
    if not downloads:
        raise PipelineError(f"Unity {version} has no {platform} X86_64 editor download")
    editor = downloads[0]
    url = str(editor.get("url", ""))
    changeset_match = CHANGESET.search(url)
    if not changeset_match:
        raise PipelineError(f"cannot read a changeset from Unity's download URL: {url}")
    module = next(
        (item for item in editor.get("modules", []) if item.get("id") == WINDOWS_MONO_MODULE),
        None,
    )
    return Release(
        version=str(entry.get("version", version)),
        changeset=changeset_match.group(1),
        editor=Download(url, _md5(editor.get("integrity"))),
        windows_mono=(
            Download(str(module.get("url", "")), _md5(module.get("integrity"))) if module else None
        ),
    )


def fetch_release(version: str, platform: str = "LINUX", timeout: int = 30) -> Release:
    query = urllib.parse.urlencode({"version": version, "limit": 1})
    request = urllib.request.Request(
        f"{RELEASE_API}?{query}", headers={"Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise PipelineError(
            f"cannot reach Unity's release service for {version}: {exc}. "
            "Pass the changeset and download URLs explicitly when offline."
        ) from exc
    return parse_release(payload, version, platform)


def version_from_project(project: Path) -> str:
    from .game import project_unity_version

    return project_unity_version(project)
