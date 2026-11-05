"""The shipped item set of the pinned build: icons, new items, new config file.

These tests read the installed game read-only and are skipped unless
``SEVEN_DAYS_TO_DIE_DIR`` names an install. They pin the *shipped* content of
V3.4.0 b10, not a pipeline behavior: when the game updates, the set below
changes on purpose and this file is where that is noticed. Update the expected
values and the pages that quote them in the same change, deliberately, rather
than letting a stale expectation silently describe the old build.
"""

from __future__ import annotations

import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from sevendtd_asset_pipeline.game import validate_game_dir
from sevendtd_asset_pipeline.icon_check import DEFAULT_CELL, read_png_header
from sevendtd_asset_pipeline.patch_check import check_patches

# Data/ItemIcons PNGs on V3.4.0 b10 (b18 shipped 5188: 73 were added, none
# removed). The other 65 added PNGs are block art: 63 banditMetal* stems with no
# block definition in this build's Data/Config, and screenKeyPad_01/_02.
V340_ICON_COUNT = 5261
# Added by V3.4.0 b10: the four pieces of each new DLC armour set.
V340_ADDED_ICONS = (
    "armorRedRidingRogueHelmet",
    "armorRedRidingRogueOutfit",
    "armorRedRidingRogueGloves",
    "armorRedRidingRogueBoots",
    "armorScarletScoundrelHelmet",
    "armorScarletScoundrelOutfit",
    "armorScarletScoundrelGloves",
    "armorScarletScoundrelBoots",
)
# Unchanged since b18.
V340_BACKPACK_ITEMS = (
    "backpackMaster",
    "backpackSmall",
    "backpackMedium",
    "backpackLarge",
    "backpackSkillMagazine",
)
V340_ARMOR_SETS = (
    "armorKegBreaker",
    "armorWraithWoodWitch",
    "armorRedRidingRogue",
    "armorScarletScoundrel",
)
# The new helmet pieces introduce a per-set DisplayType; the other three pieces
# of each set inherit it through Extends. Both are new against b18.
V340_NEW_DISPLAY_TYPES = ("armorRedRidingRogueHelmet", "armorScarletScoundrelHelmet")
# b18 showed 50 on drugSteroids and 27 on foodChickenNuggets; V3.4.0 reports the
# flat capacity both items grant.
V340_FLAT_CARRY_CAPACITY = "96"


class ShippedItemSetTests(unittest.TestCase):
    """Pin the V3.4.0 item icons and the backpack config against the install."""

    def setUp(self) -> None:
        game = os.environ.get("SEVEN_DAYS_TO_DIE_DIR")
        if not game:
            self.skipTest("SEVEN_DAYS_TO_DIE_DIR is unset; the shipped set is not readable")
        self.game = Path(game)
        validate_game_dir(self.game)
        self.config = self.game / "Data" / "Config"
        self.icons = self.game / "Data" / "ItemIcons"

    def test_every_shipped_item_icon_is_the_atlas_cell(self) -> None:
        pngs = sorted(self.icons.glob("*.png"))
        self.assertEqual(
            V340_ICON_COUNT,
            len(pngs),
            "the installed build's icon count is not the pinned V3.4.0 b10 set; "
            "retarget the pin and docs/research/research-provenance.md deliberately",
        )
        for png in pngs:
            width, height, _depth, colour = read_png_header(png)
            self.assertEqual(
                (DEFAULT_CELL, DEFAULT_CELL),
                (width, height),
                f"{png.name} is {width}x{height}, not the {DEFAULT_CELL}px atlas cell",
            )
            self.assertEqual(6, colour, f"{png.name} is not RGBA")

    def test_the_new_items_shipped_their_icons(self) -> None:
        for stem in V340_ADDED_ICONS:
            path = self.icons / f"{stem}.png"
            self.assertTrue(path.is_file(), f"the pinned build has no {stem}.png")
            width, height, _depth, colour = read_png_header(path)
            self.assertEqual((DEFAULT_CELL, DEFAULT_CELL), (width, height))
            self.assertEqual(6, colour)

    def test_items_xml_defines_the_backpack_items_and_armor_backpack(self) -> None:
        root = ET.parse(self.config / "items.xml").getroot()  # noqa: S314 - local read-only install
        items = {node.get("name"): node for node in root.iter("item")}
        for name in V340_BACKPACK_ITEMS:
            self.assertIn(name, items, f"items.xml no longer defines {name}")
        # backpackMaster introduces the DisplayType; the three sizes inherit it.
        master = {prop.get("name"): prop for prop in items["backpackMaster"].iter("property")}
        self.assertEqual("armorBackpack", master["DisplayType"].get("value"))
        for name in ("backpackSmall", "backpackMedium", "backpackLarge"):
            props = {prop.get("name"): prop for prop in items[name].iter("property")}
            self.assertEqual("backpackMaster", props["Extends"].get("value"))
            self.assertEqual("CustomIcon", props["Extends"].get("param1"))
        for prefix in V340_ARMOR_SETS:
            pieces = [name for name in items if name and name.startswith(prefix)]
            self.assertEqual(4, len(pieces), f"{prefix} is no longer a four-piece set")

    def test_the_new_armor_sets_extend_the_dlc_master(self) -> None:
        root = ET.parse(self.config / "items.xml").getroot()  # noqa: S314 - local read-only install
        items = {node.get("name"): node for node in root.iter("item")}
        new_sets = ("armorRedRidingRogue", "armorScarletScoundrel")
        for prefix in new_sets:
            pieces = [name for name in items if name and name.startswith(prefix)]
            self.assertEqual(4, len(pieces), f"{prefix} is not a four-piece set")
            for name in pieces:
                props = {prop.get("name"): prop for prop in items[name].iter("property")}
                extends = props["Extends"]
                self.assertEqual("armorDLCMaster", extends.get("value"))
                self.assertEqual("CustomIcon", extends.get("param1"))
        for prefix, display in zip(new_sets, V340_NEW_DISPLAY_TYPES, strict=True):
            helmet = {prop.get("name"): prop for prop in items[f"{prefix}Helmet"].iter("property")}
            self.assertEqual(display, helmet["DisplayType"].get("value"))

    def test_carry_capacity_display_values_are_the_flat_capacity(self) -> None:
        root = ET.parse(self.config / "items.xml").getroot()  # noqa: S314 - local read-only install
        items = {node.get("name"): node for node in root.iter("item")}
        for name in ("drugSteroids", "foodChickenNuggets"):
            values = [
                value.get("value")
                for value in items[name].iter("display_value")
                if value.get("name") == "dCarryCapacity"
            ]
            self.assertEqual([V340_FLAT_CARRY_CAPACITY], values, f"{name} carry capacity moved")

    def test_toolbelt_xml_is_a_patch_target_and_holds_editorconfig_only(self) -> None:
        stock = self.config / "toolbelt.xml"
        self.assertTrue(
            stock.is_file(),
            "this build ships no Data/Config/toolbelt.xml, so a patch named "
            "toolbelt.xml would be reported not checked",
        )
        root = ET.parse(stock).getroot()  # noqa: S314 - local read-only install
        self.assertEqual("toolbelt", root.tag)
        self.assertEqual(["editorconfig"], [child.tag for child in root])
        slots = root.find("editorconfig/slots")
        assert slots is not None
        self.assertEqual(
            {"slot_per_bar": "10", "bar_per_page": "2", "page_count": "1"},
            dict(slots.attrib),
        )
        # A mod patch to the new file must resolve through the real gate.
        with tempfile.TemporaryDirectory() as temporary:
            mod = Path(temporary)
            config = mod / "Config"
            config.mkdir()
            (config / "toolbelt.xml").write_text(
                '<configs><append xpath="/toolbelt/editorconfig/slots">'
                '<extra x="1" /></append></configs>',
                encoding="utf-8",
            )
            report = check_patches(mod, config, self.game)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(1, len(report.resolved))
        self.assertFalse(
            any("no stock toolbelt.xml" in note for note in report.notes),
            report.notes,
        )
