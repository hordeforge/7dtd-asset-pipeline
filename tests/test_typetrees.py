from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

from sevendtd_asset_pipeline import PipelineError, typetrees, unityz

TABLE: dict[str, Any] = {"__class_ids__": {"Texture2D": 28}, "Texture2D": []}
UPGRADED: dict[str, Any] = {"__class_ids__": {"Texture2D": 28, "AudioClip": 83}, "Texture2D": []}
WHICH = "sevendtd_asset_pipeline.typetrees.shutil.which"


def _completed(table: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["unityz", "trees"], returncode=0, stdout=json.dumps(table), stderr=""
    )


def _ids(table: typetrees.TreesTable) -> dict[str, int]:
    return cast("dict[str, int]", table["__class_ids__"])


class TreesTableCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        typetrees._release_table.cache_clear()
        self.addCleanup(typetrees._release_table.cache_clear)

    def test_one_reader_serves_one_table_from_cache(self) -> None:
        with (
            mock.patch.object(typetrees, "backend_identity", return_value="unityz:/bin/unityz:1:2"),
            mock.patch.object(unityz, "invoke", return_value=_completed(TABLE)) as invoke,
        ):
            first = typetrees.release_table("2022.3.62f2")
            second = typetrees.release_table("2022.3.62f2")
        self.assertIs(first, second, "one reader and one revision is one table")
        invoke.assert_called_once()

    def test_a_replaced_reader_is_not_served_from_the_cache(self) -> None:
        """The table is the reader's database, so the reader is part of the key.

        A `shamway serve` session outlives `shamway script install-unityz`. Keyed
        by the revision alone, that session kept embedding the previous
        reader's type tree into every bundle it wrote, which is the silent load
        failure this module refuses rather than infers.
        """
        with (
            mock.patch.object(
                typetrees,
                "backend_identity",
                side_effect=["unityz:/bin/unityz:1:2", "unityz:/bin/unityz:9:9"],
            ) as identity,
            mock.patch.object(
                unityz, "invoke", side_effect=[_completed(TABLE), _completed(UPGRADED)]
            ) as invoke,
        ):
            before = typetrees.release_table("2022.3.62f2")
            after = typetrees.release_table("2022.3.62f2")
        self.assertEqual(identity.call_count, 2)
        self.assertEqual(invoke.call_count, 2)
        self.assertNotIn("AudioClip", _ids(before))
        self.assertIn("AudioClip", _ids(after))

    def test_a_failed_fetch_is_not_cached_as_a_table(self) -> None:
        failure = subprocess.CompletedProcess(
            args=["unityz", "trees"], returncode=1, stdout="", stderr="no such revision"
        )
        with (
            mock.patch.object(typetrees, "backend_identity", return_value="unityz:/bin/unityz:1:2"),
            mock.patch.object(unityz, "invoke", side_effect=[failure, _completed(TABLE)]) as invoke,
        ):
            with self.assertRaises(PipelineError):
                typetrees.release_table("2022.3.62f2")
            # The next ask probes again: an error is not an answer.
            recovered = typetrees.release_table("2022.3.62f2")
        self.assertEqual(invoke.call_count, 2)
        self.assertIn("Texture2D", _ids(recovered))


class DerivedCacheKeyTests(unittest.TestCase):
    """The caches derived from the table carry the reader too, not just the revision.

    `release_table` was keyed on the reader, and the id map and the nested
    trees on top of it were not. A `shamway serve` session outliving
    `shamway script install-unityz` therefore reloaded the table and kept
    serving class names and field layouts from the reader it had replaced,
    which is the stale type tree embedded in a bundle the module refuses to
    guess at.
    """

    def setUp(self) -> None:
        for cached in (
            typetrees._release_table,
            typetrees._class_ids,
            typetrees._release_tree,
        ):
            cached.cache_clear()
            self.addCleanup(cached.cache_clear)

    def test_a_replaced_reader_renames_nothing_the_derived_caches_still_serve(self) -> None:
        before = typetrees.TreesTable(
            {
                "__class_ids__": {"Texture2D": 28, "Removed": 99},
                "Texture2D": [
                    {
                        "m_Type": "Texture2D",
                        "m_Name": "m_Width",
                        "m_Level": 0,
                        "m_Version": 1,
                    }
                ],
                "Removed": [{"m_Type": "Gone", "m_Name": "m_Old", "m_Level": 0, "m_Version": 1}],
            }
        )
        after = typetrees.TreesTable(
            {
                "__class_ids__": {"Texture2D": 28, "Replacement": 99},
                "Texture2D": [
                    {
                        "m_Type": "Texture2D",
                        "m_Name": "m_Width",
                        "m_Level": 0,
                        "m_Version": 1,
                    }
                ],
                "Replacement": [{"m_Type": "New", "m_Name": "m_New", "m_Level": 0, "m_Version": 1}],
            }
        )
        # The reader is swapped for the second reader, once, rather than per
        # call: each public entry point probes it, and a per-call list would
        # model a host flapping rather than a reinstall.
        replaced = False

        def identity() -> str:
            nonlocal replaced
            if replaced:
                return "unityz:/bin/unityz:9:9"
            return "unityz:/bin/unityz:1:2"

        with (
            mock.patch.object(typetrees, "backend_identity", side_effect=identity),
            mock.patch.object(
                unityz, "invoke", side_effect=[_completed(before), _completed(after)]
            ),
        ):
            self.assertEqual(typetrees.class_name(99, "2022.3.62f2"), "Removed")
            self.assertEqual(typetrees.release_tree(99, "2022.3.62f2").kind, "Gone")
            replaced = True
            self.assertEqual(typetrees.class_name(99, "2022.3.62f2"), "Replacement")
            self.assertEqual(typetrees.release_tree(99, "2022.3.62f2").kind, "New")

    def test_an_absent_reader_raises_rather_than_serving_the_replaced_table(self) -> None:
        with (
            mock.patch.object(
                typetrees,
                "backend_identity",
                side_effect=["unityz:/bin/unityz:1:2", "unityz:absent"],
            ),
            mock.patch.object(
                unityz, "invoke", side_effect=[_completed(TABLE), RuntimeError("no reader")]
            ),
        ):
            self.assertEqual(typetrees.class_name(28, "2022.3.62f2"), "Texture2D")
            with self.assertRaises(RuntimeError):
                typetrees.class_name(28, "2022.3.62f2")


class BackendIdentityTests(unittest.TestCase):
    def test_the_identity_names_the_executable_and_what_a_replacement_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory) / "unityz"
            installed.write_text("#!/bin/sh\n", encoding="utf-8")
            with mock.patch(WHICH, return_value=str(installed)):
                first = typetrees.backend_identity()
            installed.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            with mock.patch(WHICH, return_value=str(installed)):
                second = typetrees.backend_identity()
        self.assertIn(str(installed), first)
        self.assertNotEqual(first, second, "a replaced executable is a different database")

    def test_an_absent_reader_is_its_own_identity(self) -> None:
        with mock.patch(WHICH, return_value=None):
            self.assertEqual(typetrees.backend_identity(), "unityz:absent")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
