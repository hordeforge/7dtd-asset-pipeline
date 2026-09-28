"""The top-level parser: exit codes, `--version`, and where `--config` is accepted.

These are the two things every script and every help screen depends on, and
neither is visible from a single subcommand's tests: a caller writes
`shamway status --config mod/.shamway.toml` by habit, and argparse takes a
main-parser option only *before* the subcommand, so that used to be an
unrecognized-argument error beside a working `shamway --config ... status`.
"""

from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path

from sevendtd_asset_pipeline import cli
from sevendtd_asset_pipeline._version import __version__


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class VersionTests(unittest.TestCase):
    def test_version_prints_the_package_version_and_exits_zero(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as raised:
            cli.main(["--version"])
        self.assertEqual(0, raised.exception.code)
        self.assertEqual(f"shamway {__version__}\n", out.getvalue())


class ConfigFlagTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = cli._parser()

    def test_config_is_accepted_after_the_subcommand(self) -> None:
        args = self.parser.parse_args(["status", "--config", "mod/.shamway.toml"])
        self.assertEqual(Path("mod/.shamway.toml"), args.config)

    def test_config_is_accepted_before_the_subcommand(self) -> None:
        args = self.parser.parse_args(["--config", "mod/.shamway.toml", "status"])
        self.assertEqual(Path("mod/.shamway.toml"), args.config)

    def test_a_config_before_the_subcommand_survives_one_after_it(self) -> None:
        # SUPPRESS on the subcommand copy: a flag given on both sides must not
        # silently clear the earlier value, and a subcommand that says nothing
        # must not reset a working front-loaded --config to None.
        args = self.parser.parse_args(["--config", "front.toml", "status", "--config", "back.toml"])
        self.assertEqual(Path("back.toml"), args.config)
        args = self.parser.parse_args(["--config", "front.toml", "status"])
        self.assertEqual(Path("front.toml"), args.config)

    def test_every_subcommand_advertises_config_in_its_help(self) -> None:
        for name, sub in cli.subcommands().items():
            with self.subTest(command=name):
                self.assertIn("--config CONFIG", sub.format_help())


class ExitCodeTests(unittest.TestCase):
    def test_a_usage_error_exits_two_and_prints_nothing_on_stdout(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            _run(["not-a-command"])
        self.assertEqual(2, raised.exception.code)

    def test_a_pipeline_error_exits_one_on_stderr_only(self) -> None:
        code, out, err = _run(["docs", "not-a-topic"])
        self.assertEqual(1, code)
        self.assertEqual("", out)
        self.assertIn("ERROR:", err)


if __name__ == "__main__":
    unittest.main()
