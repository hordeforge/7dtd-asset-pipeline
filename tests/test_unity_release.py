from __future__ import annotations

import base64
import json
import unittest
import urllib.error
from unittest import mock

from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.unity_release import fetch_release, parse_release


def integrity(digest: str) -> str:
    return "md5-" + base64.b64encode(digest.encode()).decode()


# Shape captured from the live release service for 2022.3.62f2 on 2026-08-23.
PAYLOAD: dict[str, object] = {
    "results": [
        {
            "version": "2022.3.62f2",
            "downloads": [
                {
                    "platform": "WINDOWS",
                    "architecture": "X86_64",
                    "url": "https://download.unity3d.com/download_unity/7670c08855a9/W/x.exe",
                    "modules": [],
                },
                {
                    "platform": "LINUX",
                    "architecture": "X86_64",
                    "url": "https://download.unity3d.com/download_unity/7670c08855a9/LinuxEditorInstaller/Unity-2022.3.62f2.tar.xz",
                    "integrity": integrity("7dffabdd28d7f2e5d5f2f1f8f2323d21"),
                    "modules": [
                        {"id": "mac-mono", "url": "https://example.invalid/mac.pkg"},
                        {
                            "id": "windows-mono",
                            "url": "https://download.unity3d.com/download_unity/7670c08855a9/MacEditorTargetInstaller/UnitySetup-Windows-Mono-Support-for-Editor-2022.3.62f2.pkg",
                            "integrity": integrity("b5adce741fb7633c039e216348110332"),
                        },
                    ],
                },
            ],
        }
    ]
}


class UnityReleaseTests(unittest.TestCase):
    def test_resolves_changeset_editor_and_windows_module(self) -> None:
        release = parse_release(PAYLOAD, "2022.3.62f2")
        self.assertEqual("7670c08855a9", release.changeset)
        self.assertEqual("7dffabdd28d7f2e5d5f2f1f8f2323d21", release.editor.md5)
        self.assertIsNotNone(release.windows_mono)
        assert release.windows_mono is not None
        self.assertEqual("b5adce741fb7633c039e216348110332", release.windows_mono.md5)
        self.assertTrue(release.editor.url.endswith(".tar.xz"))

    def test_missing_integrity_is_reported_as_absent_not_invented(self) -> None:
        payload: dict[str, object] = {
            "results": [
                {
                    "version": "1.2.3f4",
                    "downloads": [
                        {
                            "platform": "LINUX",
                            "architecture": "X86_64",
                            "url": "https://download.unity3d.com/download_unity/abc123/L/u.tar.xz",
                            "modules": [],
                        }
                    ],
                }
            ]
        }
        release = parse_release(payload, "1.2.3f4")
        self.assertIsNone(release.editor.md5)
        self.assertIsNone(release.windows_mono)

    def test_unknown_version_fails(self) -> None:
        with self.assertRaisesRegex(PipelineError, "knows no version"):
            parse_release({"results": []}, "9.9.9f9")

    def test_missing_platform_fails(self) -> None:
        with self.assertRaisesRegex(PipelineError, "no MACOS"):
            parse_release(PAYLOAD, "2022.3.62f2", platform="MACOS")

    def test_a_non_object_payload_is_refused_not_crashed(self) -> None:
        # A changed or hostile response must fail as the module's own error;
        # an AttributeError escapes cli.main's handler as a raw traceback.
        with self.assertRaisesRegex(PipelineError, "unexpected JSON"):
            parse_release(["not", "an", "object"], "1.2.3f4")  # type: ignore[arg-type]

    def test_an_unreadable_release_entry_is_refused_not_crashed(self) -> None:
        with self.assertRaisesRegex(PipelineError, "unreadable release entry"):
            parse_release({"results": ["2022.3.62f2"]}, "1.2.3f4")

    def test_an_unreadable_download_list_is_refused_not_crashed(self) -> None:
        payload: dict[str, object] = {"results": [{"version": "1.2.3f4", "downloads": "none"}]}
        with self.assertRaisesRegex(PipelineError, "unreadable download list"):
            parse_release(payload, "1.2.3f4")

    def test_non_dict_download_entries_are_skipped_not_crashed(self) -> None:
        payload = json.loads(json.dumps(PAYLOAD))
        assert isinstance(payload, dict)
        entry = payload["results"][0]
        assert isinstance(entry, dict)
        entry["downloads"].insert(0, "https://example.invalid/not-an-object")
        release = parse_release(payload, "2022.3.62f2")
        self.assertEqual("7670c08855a9", release.changeset)

    def test_non_dict_module_entries_are_skipped_not_crashed(self) -> None:
        payload = json.loads(json.dumps(PAYLOAD))
        assert isinstance(payload, dict)
        linux = payload["results"][0]["downloads"][1]
        linux["modules"].insert(0, "windows-mono")
        release = parse_release(payload, "2022.3.62f2")
        self.assertIsNotNone(release.windows_mono)

    def test_a_non_unity_cdn_url_is_refused(self) -> None:
        payload: dict[str, object] = {
            "results": [
                {
                    "version": "1.2.3f4",
                    "downloads": [
                        {
                            "platform": "LINUX",
                            "architecture": "X86_64",
                            "url": "https://evil.example/download_unity/abc123/L/u.tar.xz",
                            "modules": [],
                        }
                    ],
                }
            ]
        }
        with self.assertRaisesRegex(PipelineError, "download.unity3d.com"):
            parse_release(payload, "1.2.3f4")


class _Response:
    """The slice of urlopen's context manager fetch_release uses."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        """Never suppress: a failing body must keep failing."""


class FetchReleaseTests(unittest.TestCase):
    """The network seam, without a network.

    `init` degrades to 'Unity will add it on first open' only for a
    PipelineError; any other escape from fetch_release crashes the scaffold.
    """

    def test_a_payload_parses_into_the_release(self) -> None:
        with mock.patch(
            "urllib.request.urlopen", return_value=_Response(json.dumps(PAYLOAD).encode())
        ):
            release = fetch_release("2022.3.62f2")
        self.assertEqual("7670c08855a9", release.changeset)
        self.assertEqual("7dffabdd28d7f2e5d5f2f1f8f2323d21", release.editor.md5)

    def test_an_unreachable_service_is_a_pipeline_error_with_the_next_step(self) -> None:
        with (
            mock.patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("no route to host"),
            ),
            self.assertRaisesRegex(PipelineError, "cannot reach Unity's release service"),
        ):
            fetch_release("2022.3.62f2")


if __name__ == "__main__":
    unittest.main()
