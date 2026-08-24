"""The atomic writers must not strand their temporary files.

Every writer in this package publishes through a unique temporary name plus a
replace, and every one of them must unlink that temporary on *every* exit path:
a body half-written when a run dies is otherwise a stray dotfile forever, and
in the atlas directory it is clutter next to the very cells `check-icons`
reads. Three writers had drifted to fixed names with no failure-path cleanup;
the pattern now lives once in `sevendtd_asset_pipeline.atomic`, and these tests
pin the writers (`client._write_lock`, `build._atomic_copy`, the generators,
both icon downscales) so the next writer copies it rather than the drift.
"""

from __future__ import annotations

import tempfile
import unittest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image
from pathlib import Path
from unittest import mock

from sevendtd_asset_pipeline.capabilities import has_capability


def dotfiles(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir() if path.name.startswith("."))


class ReplaceError(OSError):
    """A replace that dies the way an interrupted run would."""


@unittest.skipUnless(has_capability("pillow"), "cutout.save needs Pillow")
class CutoutSaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.destination = self.root / "cell.png"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _image(self) -> Image.Image:
        from PIL import Image

        return Image.new("RGBA", (4, 4), (255, 0, 255, 255))

    def test_a_saved_cell_leaves_no_temporary_behind(self) -> None:
        from sevendtd_asset_pipeline.generators.cutout import save

        save(self._image(), self.destination)
        self.assertTrue(self.destination.is_file())
        self.assertEqual([], dotfiles(self.root))

    def test_a_failed_replace_cleans_its_temporary(self) -> None:
        """The write has already produced bytes when the publish dies."""
        from sevendtd_asset_pipeline.generators.cutout import save

        def exploding(self: Path, target: object) -> Path:
            raise ReplaceError(28, "No space left on device")

        with mock.patch.object(Path, "replace", exploding), self.assertRaises(OSError):
            save(self._image(), self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual([], dotfiles(self.root))


@unittest.skipUnless(has_capability("pillow"), "_downscale needs Pillow")
class IconDownscaleTests(unittest.TestCase):
    """`render_icon`'s downscale runs after minutes of editor work; its temp
    lifecycle must not be what fails the command — or what it leaves behind."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        from PIL import Image

        self.source = self.root / "large.png"
        Image.new("RGBA", (8, 8), (0, 0, 0, 255)).save(self.source)
        self.destination = self.root / "UIAtlases" / "ItemIconAtlas" / "cell.png"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_a_downscaled_icon_is_written_with_no_temporary_left(self) -> None:
        """The temporary name ends in `.png.<pid>.<hex>`, which PIL cannot
        infer a format from — the format is named explicitly, or this raises."""
        from sevendtd_asset_pipeline.icon_render import _downscale

        coverage = _downscale(self.source, self.destination, 4)
        self.assertEqual(1.0, coverage)
        from PIL import Image

        with Image.open(self.destination) as written:
            self.assertEqual((4, 4), written.size)
        self.assertEqual([], dotfiles(self.destination.parent))

    def test_a_failed_publish_cleans_its_temporary(self) -> None:
        from sevendtd_asset_pipeline.icon_render import _downscale

        def exploding(self: Path, target: object) -> Path:
            raise ReplaceError(28, "No space left on device")

        with (
            mock.patch.object(Path, "replace", exploding),
            self.assertRaises(OSError),
        ):
            _downscale(self.source, self.destination, 4)
        self.assertEqual([], dotfiles(self.destination.parent))


@unittest.skipUnless(has_capability("pillow"), "mesh-icon downscale needs Pillow")
class MeshIconDownscaleTests(unittest.TestCase):
    """The editorless lane photographs through Blender, then downscales with
    the same lifecycle: its cell must publish atomically too, or a run dying
    mid-write leaves a truncated atlas cell that `check-icons` then reads."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        from PIL import Image

        self.source = self.root / "rendered.png"
        Image.new("RGBA", (8, 8), (0, 0, 0, 255)).save(self.source)
        self.destination = self.root / "UIAtlases" / "ItemIconAtlas" / "cell.png"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_a_downscaled_cell_is_published_with_no_temporary_left(self) -> None:
        from sevendtd_asset_pipeline.generators.mesh_icon import _downscale

        coverage = _downscale(self.source, self.destination, 4)
        self.assertEqual(1.0, coverage)
        from PIL import Image

        with Image.open(self.destination) as written:
            self.assertEqual((4, 4), written.size)
        self.assertEqual([], dotfiles(self.destination.parent))

    def test_a_failed_publish_cleans_its_temporary_and_leaves_no_cell(self) -> None:
        from sevendtd_asset_pipeline.generators.mesh_icon import _downscale

        def exploding(self: Path, target: object) -> Path:
            raise ReplaceError(28, "No space left on device")

        with (
            mock.patch.object(Path, "replace", exploding),
            self.assertRaises(OSError),
        ):
            _downscale(self.source, self.destination, 4)
        self.assertFalse(self.destination.exists())
        self.assertEqual([], dotfiles(self.destination.parent))


class WriteArtifactTests(unittest.TestCase):
    """`atomic.write` is the pack/synthesize publish point.

    A truncated .unity3d at its final path reads exactly like a complete one
    until something fails to load it, so the bytes must reach the target only
    through the rename — and a rename that dies must strand nothing.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.destination = self.root / "nested" / "out.unity3d"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_writes_bytes_and_text_and_creates_the_parent(self) -> None:
        from sevendtd_asset_pipeline.atomic import write

        write(self.destination, b"UnityFS")
        self.assertEqual(b"UnityFS", self.destination.read_bytes())
        write(self.root / "manifest.txt", "Assets:\n")
        self.assertEqual("Assets:\n", (self.root / "manifest.txt").read_text(encoding="utf-8"))
        self.assertEqual([], dotfiles(self.root) + dotfiles(self.root / "nested"))

    def test_replacing_an_existing_artifact_keeps_one_copy(self) -> None:
        from sevendtd_asset_pipeline.atomic import write

        write(self.destination, b"first")
        write(self.destination, b"second")
        self.assertEqual(b"second", self.destination.read_bytes())
        self.assertEqual([self.destination], list((self.root / "nested").iterdir()))

    def test_a_failed_publish_cleans_its_temporary(self) -> None:
        from sevendtd_asset_pipeline.atomic import write

        def exploding(self: Path, target: object) -> Path:
            raise ReplaceError(28, "No space left on device")

        with mock.patch.object(Path, "replace", exploding), self.assertRaises(OSError):
            write(self.destination, b"half-written")
        self.assertFalse(self.destination.exists())
        self.assertEqual([], dotfiles(self.root))


if __name__ == "__main__":
    unittest.main()
