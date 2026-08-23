from __future__ import annotations

import unittest

from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.operations import OPERATIONS
from sevendtd_asset_pipeline.prompts import COMMON_NEGATIVES, KINDS, kinds, render


class PromptTests(unittest.TestCase):
    def test_every_kind_renders_the_six_part_skeleton(self) -> None:
        """A prompt missing any of these lines produced a reject in the source
        project, so every kind must carry every one of them."""
        for name in KINDS:
            with self.subTest(kind=name):
                result = render(name, subject="a thing")
                prompt = result["prompt"]
                for label in ("Asset type", "Create", "Style", "Composition",
                              "Lighting", "Palette", "Readability", "Constraints"):
                    self.assertIn(f"{label}:", prompt)
                # The constraint line is wrapped for the terminal, so a
                # multi-word negative is split across lines in the rendering.
                flat = " ".join(prompt.split())
                for negative in COMMON_NEGATIVES:
                    self.assertIn(negative, flat)

    def test_a_subject_is_required_because_the_model_picks_one_otherwise(self) -> None:
        with self.assertRaises(PipelineError):
            render("item-icon", subject="   ")

    def test_unknown_kind_names_the_known_ones(self) -> None:
        with self.assertRaises(PipelineError) as caught:
            render("sprite-sheet", subject="a thing")
        self.assertIn("item-icon", str(caught.exception))

    def test_an_opacity_mask_is_forced_onto_black(self) -> None:
        """Brightness is the alpha channel here; a colour key cannot survive
        soft smoke edges, so the key is not the caller's to choose."""
        result = render("opacity-mask", subject="a smoke cluster")
        self.assertEqual(result["key"], "black")
        self.assertEqual(result["key_hex"], "#000000")
        self.assertIn("exactly flat #000000", result["prompt"])
        with self.assertRaises(PipelineError):
            render("opacity-mask", subject="a smoke cluster", key="magenta")

    def test_an_albedo_has_no_key_because_it_is_never_cut_out(self) -> None:
        result = render("material-albedo", subject="battered olive-drab steel")
        self.assertEqual(result["key"], "")
        self.assertNotIn("Background:", result["prompt"])

    def test_the_green_key_is_available_for_a_magenta_subject(self) -> None:
        result = render("item-icon", subject="a hot pink warning lamp", key="green")
        self.assertIn("exactly flat #00ff00", result["prompt"])

    def test_named_artefacts_join_the_negative_list(self) -> None:
        """Generic negatives do not remove a specific recurring artefact."""
        result = render("item-icon", subject="a nuke", avoid=("carry handle", "bail"))
        self.assertIn("carry handle", result["prompt"])
        self.assertIn("bail", result["prompt"])

    def test_the_lane_commands_carry_the_stem(self) -> None:
        result = render("item-icon", subject="a nuke", stem="myModNuke")
        joined = "\n".join(result["next"])
        self.assertIn("myModNuke", joined)
        self.assertIn("shamway check-icons", joined)
        self.assertNotIn("{stem}", joined)

    def test_an_unknown_key_colour_names_the_known_ones(self) -> None:
        with self.assertRaises(PipelineError) as caught:
            render("item-icon", subject="a thing", key="chartreuse")
        self.assertIn("magenta", str(caught.exception))
        self.assertIn("green", str(caught.exception))

    def test_the_cli_lists_kinds_and_renders_json(self) -> None:
        """`shamway prompt` is an agent surface, so both output shapes are pinned."""
        import contextlib
        import io
        import json

        from sevendtd_asset_pipeline.prompts import main

        listing = io.StringIO()
        with contextlib.redirect_stdout(listing):
            self.assertEqual(0, main(["--list"]))
        self.assertIn("item-icon", listing.getvalue())

        payload = io.StringIO()
        with contextlib.redirect_stdout(payload):
            self.assertEqual(0, main(["--json", "--list"]))
        kinds = json.loads(payload.getvalue())
        self.assertEqual({entry["kind"] for entry in kinds}, set(KINDS))

        rendered = io.StringIO()
        with contextlib.redirect_stdout(rendered):
            self.assertEqual(0, main(["--json", "item-icon", "--subject", "a nuke"]))
        result = json.loads(rendered.getvalue())
        self.assertIn("Asset type:", result["prompt"])
        self.assertEqual("a nuke", result["subject"])

    def test_no_line_runs_past_the_margin(self) -> None:
        """Terminal output is read in a terminal: reference detail gets its own
        column, and nothing wraps past it."""
        for name in KINDS:
            for line in render(name, subject="a thing " * 30)["prompt"].splitlines():
                self.assertLessEqual(len(line), 78, f"{name}: {line!r}")

    def test_the_registered_operation_matches_the_module(self) -> None:
        operation = OPERATIONS["prompt"]
        self.assertFalse(operation.writes)
        self.assertFalse(operation.needs_config)
        self.assertEqual(sorted(operation.parameters["required"]), ["kind", "subject"])
        self.assertEqual({entry["kind"] for entry in kinds()}, set(KINDS))


if __name__ == "__main__":
    unittest.main()
