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
