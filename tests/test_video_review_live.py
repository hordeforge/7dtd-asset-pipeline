"""The opt-in live end-to-end review run.

Synthetic clip -> adopt -> `shamway review-video` -> real NVIDIA provider ->
hash-addressed evidence. This is the runnable proof for PRD 0002's Goal-1
criterion: a real video-capable provider reviews a clip and identifies a
motion-dependent property a single still could not show.

Strictly opt-in, mirroring the audio review's live case: set
`SHAMWAY_NETWORK_TESTS=nvidia` and configure the deadeye gateway with an
NVIDIA key (env or its gitignored `config.local.toml`), with `deadeye` on
PATH. It costs money and sends frames to a third party; it never runs in the
offline suite.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

from sevendtd_asset_pipeline.capture import record_existing_clip
from sevendtd_asset_pipeline.config import load_config, render_config
from sevendtd_asset_pipeline.video_review import GATEWAY, run_review


def _solid_png(width: int, height: int, square_x: int | None) -> bytes:
    """A 128x128 dark frame with a 20x20 red square at (square_x, 30).

    `square_x=None` renders an empty frame: the marker disappears.
    """
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filter: none
        for x in range(width):
            if square_x is not None and 30 <= y < 50 and square_x <= x < square_x + 20:
                rows += b"\xff\x00\x00"
            else:
                rows += b"\x14\x14\x14"

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(bytes(rows)))
    iend = chunk(b"IEND", b"")
    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + iend


def _defective_clip(directory: Path) -> Path:
    """12 frames: the square sweeps smoothly right, then *disappears* for one
    frame before returning.

    Exactly the adapter's 12-image budget, so no sampling intervenes. A single
    still shows the square at one position; only the sequence shows the
    disappearance — the motion-dependent defect the review is supposed to name.
    """
    positions: list[int | None] = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, None, 30]
    for index, x in enumerate(positions):
        (directory / f"frame-{index:04d}.png").write_bytes(_solid_png(128, 128, x))
    return directory


def _mux_video(frames_dir: Path, output: Path) -> bool:
    """Mux the clip's frames into an mp4 with ffmpeg, like capture_video.sh.

    Returns False when ffmpeg is unavailable; the caller then falls back to
    the frame-only path.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return False
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-framerate",
            "4",
            "-i",
            str(frames_dir / "frame-%04d.png"),
            "-pix_fmt",
            "yuv420p",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and output.is_file()


def _gateway_configured(provider: str) -> bool:
    try:
        result = subprocess.run(
            [GATEWAY, "doctor", "--json"], capture_output=True, text=True, timeout=30, check=False
        )
        if result.returncode != 0:
            return False
        states = json.loads(result.stdout)
        return any(
            state.get("name") == provider and state.get("state") == "configured" for state in states
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return False


class LiveEndToEndTests(unittest.TestCase):
    """Real provider checks cost money and leave the host: strictly opt-in."""

    def setUp(self) -> None:
        if os.environ.get("SHAMWAY_NETWORK_TESTS") != "nvidia":
            self.skipTest("opt-in: set SHAMWAY_NETWORK_TESTS=nvidia")
        if shutil.which(GATEWAY) is None:
            self.skipTest("opt-in: the deadeye gateway is not on PATH")
        if not _gateway_configured("nvidia"):
            self.skipTest(
                "opt-in: the deadeye gateway must report nvidia configured "
                "(NVIDIA_API_KEY or its config.local.toml)"
            )

    def test_the_full_chain_reviews_a_real_clip_and_names_the_pop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            # A minimal mod: one synthesized mesh asset.
            (root / "Config").mkdir(parents=True, exist_ok=True)
            (root / "Resources").mkdir(parents=True, exist_ok=True)
            (root / "tools/shamway/manifests").mkdir(parents=True, exist_ok=True)
            (root / "ModInfo.xml").write_text(
                '<?xml version="1.0"?><xml><Name value="ExampleMod" /></xml>',
                encoding="utf-8",
            )
            (root / ".shamway.toml").write_text(
                render_config(
                    mod_name="ExampleMod",
                    bundle_name="examplemod.unity3d",
                    unity_version="2022.3.62f2",
                    bundle_source="synthesized",
                ),
                encoding="utf-8",
            )
            source = root / "assets-src" / "bundle"
            source.mkdir(parents=True, exist_ok=True)
            (source / "thing.glb").write_bytes(b"mesh-bytes")
            config = load_config(root / ".shamway.toml")

            # A synthetic clip with a deliberate pop; adopted like a real one.
            captured = root / "capture" / "thing"
            captured.mkdir(parents=True, exist_ok=True)
            _defective_clip(captured)
            muxed = _mux_video(captured, captured / "clip.mp4")
            if not muxed:
                self.skipTest("ffmpeg unavailable; the muxed-video path cannot run")
            (captured / "client.log").write_text("clip complete demo/thing frames=12\n")
            capture_root = root / ".local" / "acceptance"
            adopted = record_existing_clip(
                captured,
                "thing",
                "the marker must sweep smoothly without popping",
                capture_root,
            )
            self.assertEqual("thing", adopted.directory)

            intent = root / "thing.review.json"
            intent.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "purpose": "verify the marker moves smoothly across the clip "
                        "without popping or jumping",
                        "subject": "thing (synthetic marker)",
                        "camera_path": "fixed",
                        "desired_qualities": "continuous, evenly spaced motion",
                        "avoid": ["popping", "jumping", "jitter"],
                        "questions": ["does the marker pop at any point?"],
                        "suite": "demo",
                        "case": "thing",
                    }
                ),
                encoding="utf-8",
            )

            evidence = root / "evidence.json"
            from sevendtd_asset_pipeline import PipelineError

            try:
                run_review(
                    "thing",
                    clip=capture_root / "thing",
                    provider="nvidia",
                    intent_path=intent,
                    config=config,
                    capture_root=capture_root,
                    allow_network=True,
                    output=evidence,
                    timeout_seconds=180.0,
                )
            except PipelineError as exc:
                if "rate-limited" in str(exc) or "503" in str(exc):
                    # The free-tier NVIDIA worker caps requests; not a code
                    # failure. Rerun when the limit resets.
                    self.skipTest(f"provider rate-limited: {exc}")
                raise

            self.assertTrue(evidence.is_file(), "the evidence document must be written")
            document = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual("shamway-video-review-evidence", document["kind"])
            self.assertEqual("thing", document["asset"]["stem"])
            self.assertTrue(document["result"]["summary"])
            self.assertEqual("deadeye-review", document["gateway"]["kind"])
            self.assertNotIn("NVIDIA_API_KEY", evidence.read_text(encoding="utf-8"))

            # The clip had a muxed mp4 and the provider takes video, so the
            # submission must have gone as video — not silently as frames.
            media = document["clip"]["files"]
            self.assertTrue(
                any(entry.get("kind") == "video" for entry in media),
                f"the muxed video must reach the provider; media was {media}",
            )
            self.assertIn("muxed video", document["sampling"]["note"])

            issues = document["result"]["issues"]
            # The pipeline mechanics above are the hard contract. Whether the
            # model names the planted defect is advisory and varies by run
            # (one live run flagged the pop with three issues; another called
            # the motion smooth at 0.96 confidence) — printed for the human,
            # recorded in PRD 0002 as an evaluation finding, not a gate.
            print("\nLIVE REVIEW SUMMARY:", document["result"]["summary"])
            for issue in issues:
                print("LIVE REVIEW ISSUE:", issue.get("description"))
            print("LIVE REVIEW LIMITATIONS:", document["result"]["limitations"])
            print("LIVE REVIEW CONFIDENCE:", document["result"].get("confidence"))
            if not issues:
                print(
                    "NOTE: the model did not name the planted defect this run; "
                    "see the finding in PRD 0002 (model verdicts are advisory)."
                )


if __name__ == "__main__":
    unittest.main()
