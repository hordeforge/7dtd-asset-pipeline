"""The hide lane: a whole-coat albedo, and the atlased role-aware variant.

`generate hide` has two modes. Whole-coat (the default) draws one periodic
fur field across the whole texture; every part of a generated entity samples
that one field, so no colour can be reserved for the feet. Atlas mode reads
the per-part UV manifest `generate entity --atlas` writes, and paints each
cell the role colour its part demands — paw dark, limb a shade, body the
coat — with the gutters filled by an outline colour. These tests pin the
atlas contract: each cell gets its own periodic field, each role colour
actually lands in the right cells, and the same seed reproduces the same
bytes.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import TypedDict

from sevendtd_asset_pipeline.generators import run
from sevendtd_asset_pipeline.generators.entity import atlas_cell, part_role

try:  # pragma: no cover - exercised by whether the extra is installed
    import numpy as np
    from PIL import Image

    HAVE_IMAGING = True
except ImportError:  # pragma: no cover
    HAVE_IMAGING = False


class AtlasManifest(TypedDict):
    """The manifest `generate entity --atlas` writes, and `generate hide
    --atlas` reads: one UV cell and a semantic role per part."""

    stem: str
    grid: int
    parts: dict[str, tuple[float, float, float, float]]
    roles: dict[str, str]


def cell_rect(cell: tuple[float, float, float, float], size: int) -> tuple[int, int, int, int]:
    u0, v0, u1, v1 = cell
    return (
        round(u0 * size),
        round((1.0 - v1) * size),
        round(u1 * size),
        round((1.0 - v0) * size),
    )


@unittest.skipUnless(HAVE_IMAGING, "the hide lane needs numpy and Pillow")
class HideAtlasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _hide(self, size: int = 128) -> tuple[Path, AtlasManifest]:
        out = self.root / "creature.glb"
        manifest = self.root / "creature.atlas.json"
        self.assertEqual(
            run("entity", [str(out), "--rig", "quadruped", "--atlas", str(manifest)]), 0
        )
        albedo = self.root / "creature_albedo.png"
        self.assertEqual(
            run(
                "hide",
                [
                    str(albedo),
                    "--atlas",
                    str(manifest),
                    "--seed",
                    "7",
                    "--base",
                    "192,180,152",
                    "--size",
                    str(size),
                ],
            ),
            0,
        )
        return albedo, json.loads(manifest.read_text(encoding="utf-8"))

    def test_atlas_cells_cover_the_grid_without_overlap(self) -> None:
        cells = atlas_cell(["A", "B", "C", "D", "E"])
        # Five parts -> a 3x3 square grid (ceil(sqrt(5)) = 3).
        self.assertEqual(len(cells), 5)
        self.assertAlmostEqual(cells["A"][0], 0.0, places=12)
        self.assertAlmostEqual(cells["A"][1], 2 / 3, places=12)
        self.assertAlmostEqual(cells["A"][2], 1 / 3, places=12)
        self.assertAlmostEqual(cells["A"][3], 1.0, places=12)
        for u0, v0, u1, v1 in cells.values():
            self.assertTrue(0.0 <= u0 < u1 <= 1.0)
            self.assertTrue(0.0 <= v0 < v1 <= 1.0)

    def test_part_role_classifies_paws_limbs_and_body(self) -> None:
        roles = part_role(["Pelvis", "LeftFrontUpper", "LeftFrontPaw", "Head", "Tail", "LeftThigh"])
        self.assertEqual(roles["LeftFrontPaw"], "paw")
        self.assertEqual(roles["LeftFrontUpper"], "limb")
        self.assertEqual(roles["Pelvis"], "body")
        self.assertEqual(roles["Head"], "head")
        self.assertEqual(roles["Tail"], "tail")
        self.assertEqual(roles["LeftThigh"], "limb")

    def test_paws_are_dark_and_body_light(self) -> None:
        albedo, manifest = self._hide()
        rgb = np.asarray(Image.open(albedo).convert("RGB")).astype(float)
        size = 128
        cells = manifest["parts"]
        roles = manifest["roles"]
        means = {}
        for name, cell in cells.items():
            x0, y0, x1, y1 = cell_rect(cell, size)
            means[name] = rgb[y0:y1, x0:x1].reshape(-1, 3).mean(axis=0)
        paw = np.asarray([means[n] for n, r in roles.items() if r == "paw"]).mean(axis=0)
        body = np.asarray([means[n] for n, r in roles.items() if r == "body"]).mean(axis=0)
        # The paw must be clearly darker than the body — the whole point of the
        # atlas is that the feet read against both the legs and the terrain.
        self.assertLess(paw.sum(), body.sum() * 0.6)

    def test_the_same_seed_is_the_same_hide(self) -> None:
        size = 128
        albedo, _manifest = self._hide(size)
        again = self.root / "creature2_albedo.png"
        self.assertEqual(
            run(
                "hide",
                [
                    str(again),
                    "--atlas",
                    str(self.root / "creature.atlas.json"),
                    "--seed",
                    "7",
                    "--base",
                    "192,180,152",
                    "--size",
                    str(size),
                ],
            ),
            0,
        )
        self.assertEqual(albedo.read_bytes(), again.read_bytes())

    def test_a_paw_cell_and_a_limb_cell_are_painted_differently(self) -> None:
        """The atlas assigns each role a distinct colour — the discrimination
        a whole-coat hide cannot make, because no colour can be reserved."""
        albedo, manifest = self._hide(128)
        rgb = np.asarray(Image.open(albedo).convert("RGB")).astype(float)
        roles = manifest["roles"]
        cells = manifest["parts"]
        paw = next(n for n, r in roles.items() if r == "paw")
        limb = next(n for n, r in roles.items() if r == "limb")
        px0, py0, px1, py1 = cell_rect(cells[paw], 128)
        lx0, ly0, lx1, ly1 = cell_rect(cells[limb], 128)
        paw_mean = rgb[py0:py1, px0:px1].reshape(-1, 3).mean(axis=0)
        limb_mean = rgb[ly0:ly1, lx0:lx1].reshape(-1, 3).mean(axis=0)
        self.assertNotEqual(tuple(paw_mean.round()), tuple(limb_mean.round()))

    def test_whole_coat_mode_still_works(self) -> None:
        albedo = self.root / "coat.png"
        self.assertEqual(
            run("hide", [str(albedo), "--seed", "3", "--base", "96,80,60", "--size", "64"]),
            0,
        )
        rgb = np.asarray(Image.open(albedo).convert("RGB"))
        self.assertEqual(rgb.shape, (64, 64, 3))
        self.assertGreater(len(np.unique(rgb.reshape(-1, 3), axis=0)), 8)

    def test_atlas_without_cells_is_refused(self) -> None:
        manifest = self.root / "empty.json"
        manifest.write_text(json.dumps({"grid": 3, "roles": {}}), encoding="utf-8")
        albedo = self.root / "x.png"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            run("hide", [str(albedo), "--atlas", str(manifest)])
        self.assertIn("no per-part cells", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
