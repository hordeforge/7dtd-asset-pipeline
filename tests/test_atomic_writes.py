"""The atomic writers must not strand their temporary files.

Every writer in this package publishes through a unique temporary name plus a
replace, and every one of them must unlink that temporary on *every* exit path:
a body half-written when a run dies is otherwise a stray dotfile forever, and
in the atlas directory it is clutter next to the very cells `check-icons`
reads. Three writers had drifted to fixed names with no failure-path cleanup;
these tests pin the house pattern (`client._write_lock`, `build._atomic_copy`,
the four generators) so the next writer copies it rather than the drift.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sevendtd_asset_pipeline.capabilities import has_capability


def dotfiles(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir() if path.name.startswith("."))


class ReplaceFails(OSError):
    """A replace that dies the way an interrupted run would."""


@unittest.skipUnless(has_capability("pillow"), "cutout.save needs Pillow")
class CutoutSaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.destination = self.root / "cell.png"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _image(self):
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
            raise ReplaceFails(28, "No space left on device")

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
            raise ReplaceFails(28, "No space left on device")

        with (
            mock.patch.object(Path, "replace", exploding),
            self.assertRaises(OSError),
        ):
            _downscale(self.source, self.destination, 4)
        self.assertEqual([], dotfiles(self.destination.parent))


if __name__ == "__main__":
    unittest.main()
