"""Unit tests for LTspice symbol pin-facing resolution."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from electronics_design import ltspice_symbol_facing

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_FIXTURE_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "symbol_facing"
_CONVERT_SETTINGS = {
    "ltspice_windows_path": "C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
    "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
    "custom_search_paths": ["./valid_asy/"],
    "grid_size": 16,
}
_EXPECTED_RESULTS = {
    "example_case_01.json": {
        "M1": [
            [224, 128, "D", 1, "-Y DIRECTION"],
            [176, 208, "G", 2, "-X DIRECTION"],
            [224, 224, "S", 3, "+Y DIRECTION"],
        ]
    },
    "example_case_02.json": {
        "M5": [
            [256, 192, "D", 1, "+X DIRECTION"],
            [176, 144, "G", 2, "-Y DIRECTION"],
            [160, 192, "S", 3, "-X DIRECTION"],
        ]
    },
    "example_case_03.json": {
        "M2": [
            [208, 160, "D", 1, "-X DIRECTION"],
            [288, 112, "G", 2, "-Y DIRECTION"],
            [304, 160, "S", 3, "+X DIRECTION"],
        ]
    },
    "example_case_04.json": {
        "M1": [
            [288, 192, "D", 1, "+Y DIRECTION"],
            [240, 112, "G", 2, "-X DIRECTION"],
            [288, 96, "S", 3, "-Y DIRECTION"],
        ]
    },
    "case_01.json": {
        "R1": [
            [176, 112, "A", 1, "-Y DIRECTION"],
            [176, 192, "B", 2, "+Y DIRECTION"],
        ]
    },
    "case_02.json": {
        "R2": [
            [224, 176, "A", 1, "+X DIRECTION"],
            [144, 176, "B", 2, "-X DIRECTION"],
        ]
    },
    "case_03.json": {
        "R3": [
            [448, 96, "A", 1, "+Y DIRECTION"],
            [448, 16, "B", 2, "-Y DIRECTION"],
        ]
    },
    "case_04.json": {
        "R4": [
            [544, 288, "A", 1, "+X DIRECTION"],
            [464, 288, "B", 2, "-X DIRECTION"],
        ]
    },
    "case_05.json": {
        "C1": [
            [208, 160, "A", 1, "-Y DIRECTION"],
            [208, 224, "B", 2, "+Y DIRECTION"],
        ]
    },
    "case_06.json": {
        "C2": [
            [320, 112, "A", 1, "+X DIRECTION"],
            [256, 112, "B", 2, "-X DIRECTION"],
        ]
    },
    "case_07.json": {
        "C3": [
            [208, 256, "A", 1, "+Y DIRECTION"],
            [208, 192, "B", 2, "-Y DIRECTION"],
        ]
    },
    "case_08.json": {
        "L1": [
            [464, 128, "A", 1, "+Y DIRECTION"],
            [464, 48, "B", 2, "-Y DIRECTION"],
        ]
    },
    "case_09.json": {
        "L2": [
            [336, 224, "A", 1, "+X DIRECTION"],
            [256, 224, "B", 2, "-X DIRECTION"],
        ]
    },
    "case_10.json": {
        "L3": [
            [368, 400, "A", 1, "+X DIRECTION"],
            [288, 400, "B", 2, "-X DIRECTION"],
        ]
    },
    "case_11.json": {
        "U1": [
            [288, 304, "In+", 1, "-X DIRECTION"],
            [288, 272, "In-", 2, "-X DIRECTION"],
            [320, 256, "V+", 3, "-Y DIRECTION"],
            [320, 320, "V-", 4, "+Y DIRECTION"],
            [352, 288, "OUT", 5, "+X DIRECTION"],
        ]
    },
    "case_12.json": {
        "U2": [
            [512, 240, "In+", 1, "+X DIRECTION"],
            [512, 272, "In-", 2, "+X DIRECTION"],
            [480, 288, "V+", 3, "+Y DIRECTION"],
            [480, 224, "V-", 4, "-Y DIRECTION"],
            [448, 256, "OUT", 5, "-X DIRECTION"],
        ]
    },
    "case_13.json": {
        "U3": [
            [752, 384, "In+", 1, "+Y DIRECTION"],
            [720, 384, "In-", 2, "+Y DIRECTION"],
            [704, 352, "V+", 3, "-X DIRECTION"],
            [768, 352, "V-", 4, "+X DIRECTION"],
            [736, 320, "OUT", 5, "-Y DIRECTION"],
        ]
    },
    "case_14.json": {
        "U4": [
            [448, 256, "In+", 1, "+X DIRECTION"],
            [448, 224, "In-", 2, "+X DIRECTION"],
            [416, 208, "V+", 3, "-Y DIRECTION"],
            [416, 272, "V-", 4, "+Y DIRECTION"],
            [384, 240, "OUT", 5, "-X DIRECTION"],
        ]
    },
    "case_15.json": {
        "U5": [
            [624, 224, "In+", 1, "-Y DIRECTION"],
            [592, 224, "In-", 2, "-Y DIRECTION"],
            [576, 256, "V+", 3, "-X DIRECTION"],
            [640, 256, "V-", 4, "+X DIRECTION"],
            [608, 288, "OUT", 5, "+Y DIRECTION"],
        ]
    },
}


class TestSymbolFacing(unittest.TestCase):
    def test_all_symbol_facing_fixtures(self) -> None:
        fixture_paths = sorted(_FIXTURE_DIRECTORY.glob("*.json"))
        self.assertEqual(
            [fixture_path.name for fixture_path in fixture_paths],
            sorted(_EXPECTED_RESULTS),
            msg="The symbol-facing fixtures on disk should match the expected fixture map exactly.",
        )
        for fixture_path in fixture_paths:
            with self.subTest(fixture=fixture_path.name):
                loaded_fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
                result = ltspice_symbol_facing(str(fixture_path), _CONVERT_SETTINGS)
                self.assertEqual(result, _EXPECTED_RESULTS[fixture_path.name], msg=f"{fixture_path.name} should resolve all pin facings exactly.")
                self.assertEqual(set(result), set(loaded_fixture), msg=f"{fixture_path.name} should preserve the symbol instance names.")

