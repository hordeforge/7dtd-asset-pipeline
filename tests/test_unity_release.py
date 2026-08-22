from __future__ import annotations

import base64
import unittest

from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.unity_release import parse_release


def integrity(digest: str) -> str:
    return "md5-" + base64.b64encode(digest.encode()).decode()


# Shape captured from the live release service for 2022.3.62f2 on 2026-08-23.
PAYLOAD = {
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
        payload = {
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


if __name__ == "__main__":
    unittest.main()
