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

from .errors import PipelineError

RELEASE_API = "https://services.api.unity.com/unity/editor/release/v1/releases"
CHANGESET = re.compile(r"/download_unity/([0-9a-f]+)/")
WINDOWS_MONO_MODULE = "windows-mono"
# The installer curl-downloads whatever URL this module returns; keep it on
# Unity's own CDN even if the release JSON names somewhere else.
_DOWNLOAD_HOSTS = frozenset({"download.unity3d.com"})
# The host platform the editor is downloaded for, shared with the published
# schema (operations.py) and the CLI (--platform).
DEFAULT_PLATFORM = "LINUX"
# Hoisted so the request construction stays on one line.
_JSON_HEADERS = {"Accept": "application/json"}


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


def _require_unity_download(url: str, what: str) -> str:
    """Refuse a download URL that is not https://download.unity3d.com/…."""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or host not in _DOWNLOAD_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or any(character in url for character in "\r\n\x00")
    ):
        raise PipelineError(
            f"Unity's release service returned a non-https download.unity3d.com URL for {what}"
        )
    return url


def _md5(integrity: object) -> str | None:
    """Decode Unity's ``md5-<base64 of the hex digest>`` integrity field."""
    if not isinstance(integrity, str) or not integrity.startswith("md5-"):
        return None
    try:
        digest = base64.b64decode(integrity[4:], validate=True).decode("ascii")
    except (ValueError, UnicodeDecodeError):
        return None
    return digest if re.fullmatch(r"[0-9a-f]{32}", digest) else None


def parse_release(
    payload: dict[str, object], version: str, platform: str = DEFAULT_PLATFORM
) -> Release:
    # The body is whatever json.loads produced, so its shape is asserted, not
    # assumed: a changed or hostile response must fail as the module's own
    # PipelineError, not as an AttributeError past every handler.
    if not isinstance(payload, dict):
        raise PipelineError(
            f"Unity's release service returned unexpected JSON for {version}: expected an object"
        )
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise PipelineError(f"Unity's release service knows no version {version}")
    entry = results[0]
    if not isinstance(entry, dict):
        raise PipelineError(
            f"Unity's release service returned an unreadable release entry for {version}"
        )
    raw_downloads = entry.get("downloads", [])
    if not isinstance(raw_downloads, list):
        raise PipelineError(
            f"Unity's release service returned an unreadable download list for {version}"
        )
    downloads = [
        item
        for item in raw_downloads
        if isinstance(item, dict)
        and item.get("platform") == platform
        and item.get("architecture") == "X86_64"
    ]
    if not downloads:
        raise PipelineError(f"Unity {version} has no {platform} X86_64 editor download")
    editor = downloads[0]
    url = _require_unity_download(str(editor.get("url", "")), f"Unity {version}")
    changeset_match = CHANGESET.search(url)
    if not changeset_match:
        raise PipelineError(f"cannot read a changeset from Unity's download URL: {url}")
    raw_modules = editor.get("modules", [])
    module = next(
        (
            item
            for item in (raw_modules if isinstance(raw_modules, list) else [])
            if isinstance(item, dict) and item.get("id") == WINDOWS_MONO_MODULE
        ),
        None,
    )
    return Release(
        version=str(entry.get("version", version)),
        changeset=changeset_match.group(1),
        editor=Download(url, _md5(editor.get("integrity"))),
        windows_mono=(
            Download(
                _require_unity_download(str(module.get("url", "")), "windows-mono"),
                _md5(module.get("integrity")),
            )
            if module
            else None
        ),
    )


def fetch_release(version: str, platform: str = DEFAULT_PLATFORM, timeout: int = 30) -> Release:
    query = urllib.parse.urlencode({"version": version, "limit": 1})
    # RELEASE_API is a fixed https URL; only the urlencoded query varies.
    request = urllib.request.Request(f"{RELEASE_API}?{query}", headers=_JSON_HEADERS)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise PipelineError(
            f"cannot reach Unity's release service for {version}: {exc}. "
            "Pass the changeset and download URLs explicitly when offline."
        ) from exc
    return parse_release(payload, version, platform)
