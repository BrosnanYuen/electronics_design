"""Unit tests for LTspice ASC symbol extraction and ASY-backed pin transforms."""

from __future__ import annotations

from pathlib import Path
import re
import unittest

from electronics_design import get_ltspice_asc_symbol_info
from electronics_design import get_ltspice_asy_pins
from electronics_design import get_ltspice_asy_size

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_FIXTURE_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "get_ltspice_asc_symbols"
_VALID_ASY_DIRECTORY = _ROOT_DIRECTORY / "valid_asy"

_CASE_SPECS = {
    "case_01.asc": (
        {
            "inst": "R1",
            "symbol": "res",
            "asy": "res.asy",
            "origin": (160, 96),
            "orientation": "R0",
            "value": "10k",
            "spiceline": "tc=0.01",
        },
        {
            "inst": "C1",
            "symbol": "cap",
            "asy": "cap.asy",
            "origin": (320, 96),
            "orientation": "R90",
            "value": "22u",
            "type": "cap",
        },
    ),
    "case_02.asc": (
        {
            "inst": "L1",
            "symbol": "ind",
            "asy": "ind.asy",
            "origin": (480, 144),
            "orientation": "R180",
            "value": "16u",
            "type": "ind",
        },
        {
            "inst": "D1",
            "symbol": "diode",
            "asy": "diode.asy",
            "origin": (624, 176),
            "orientation": "R270",
            "value": "1N4148",
            "spiceline": "Ron=0.2",
        },
    ),
    "case_03.asc": (
        {
            "inst": "Q1",
            "symbol": "Semiconductors\\npn",
            "asy": "npn.asy",
            "origin": (256, 240),
            "orientation": "R0",
            "value": "2N3904",
            "spiceline": "Bf=200",
            "type": "npn",
        },
    ),
    "case_04.asc": (
        {
            "inst": "Q2",
            "symbol": "Semiconductors\\pnp",
            "asy": "pnp.asy",
            "origin": (544, 176),
            "orientation": "R90",
            "value": "2N3906",
            "type": "pnp",
        },
    ),
    "case_05.asc": (
        {
            "inst": "M1",
            "symbol": "nmos",
            "asy": "nmos.asy",
            "origin": (608, 352),
            "orientation": "R180",
            "value": "IRF530",
            "spiceline": "m=2",
            "type": "nmos",
        },
    ),
    "case_06.asc": (
        {
            "inst": "M2",
            "symbol": "Power\\pmos",
            "asy": "pmos.asy",
            "origin": (704, 192),
            "orientation": "R270",
            "value": "IRF9540",
            "spiceline": "m=4",
            "type": "pmos",
        },
    ),
    "case_07.asc": (
        {
            "inst": "U1",
            "symbol": "OpAmps\\AD823",
            "asy": "AD823.asy",
            "origin": (480, 320),
            "orientation": "R180",
            "value": "AD823",
            "spiceline": "GBW=16Meg",
            "type": "opamp",
        },
    ),
    "case_08.asc": (
        {
            "inst": "V1",
            "symbol": "Sources\\voltage",
            "asy": "voltage.asy",
            "origin": (128, 192),
            "orientation": "M0",
            "value": "5",
            "spiceline": "Rser=0.01",
        },
        {
            "inst": "I1",
            "symbol": "current",
            "asy": "current.asy",
            "origin": (304, 224),
            "orientation": "M90",
            "value": "{A}",
            "type": "current",
        },
    ),
    "case_09.asc": (
        {
            "inst": "R2",
            "symbol": "Passive\\res",
            "asy": "res.asy",
            "origin": (432, 112),
            "orientation": "M180",
            "value": "47k",
            "type": "resistor",
        },
        {
            "inst": "D2",
            "symbol": "Diodes\\diode",
            "asy": "diode.asy",
            "origin": (576, 208),
            "orientation": "M270",
            "value": "BAT54",
            "spiceline": "Vfwd=0.24",
        },
    ),
    "case_10.asc": (
        {
            "inst": "M3",
            "symbol": "pmos",
            "asy": "pmos.asy",
            "origin": (304, 144),
            "orientation": "R0",
            "value": "PMOS_A",
            "type": "pmos",
        },
        {
            "inst": "M4",
            "symbol": "Power\\pmos",
            "asy": "pmos.asy",
            "origin": (640, 256),
            "orientation": "R90",
            "value": "PMOS_B",
            "spiceline": "m=8",
        },
    ),
    "case_11.asc": (
        {
            "inst": "M5",
            "symbol": "Semiconductors\\nmos",
            "asy": "nmos.asy",
            "origin": (256, 400),
            "orientation": "M0",
            "value": "NMOS_SW",
            "spiceline": "m=3",
        },
        {
            "inst": "Q3",
            "symbol": "npn",
            "asy": "npn.asy",
            "origin": (448, 336),
            "orientation": "M90",
            "value": "BC547",
            "type": "npn",
        },
    ),
    "case_12.asc": (
        {
            "inst": "C2",
            "symbol": "cap",
            "asy": "cap.asy",
            "origin": (192, 256),
            "orientation": "M180",
            "value": "100n",
            "spiceline": "Rpar=1Meg",
        },
        {
            "inst": "L2",
            "symbol": "Passive\\ind",
            "asy": "ind.asy",
            "origin": (384, 416),
            "orientation": "M270",
            "value": "8u",
            "type": "ind",
        },
    ),
    "case_13.asc": (
        {
            "inst": "U2",
            "symbol": "OpAmps\\AD823",
            "asy": "AD823.asy",
            "origin": (320, 224),
            "orientation": "R0",
            "value": "AD823",
            "type": "opamp",
        },
        {
            "inst": "U3",
            "symbol": "OpAmps\\AD823",
            "asy": "AD823.asy",
            "origin": (672, 352),
            "orientation": "R270",
            "value": "AD823",
            "spiceline": "Vos=50u",
        },
    ),
    "case_14.asc": (
        {
            "inst": "Q4",
            "symbol": "pnp",
            "asy": "pnp.asy",
            "origin": (272, 192),
            "orientation": "R180",
            "value": "2N3906",
            "type": "pnp",
        },
        {
            "inst": "D3",
            "symbol": "Diodes\\diode",
            "asy": "diode.asy",
            "origin": (448, 160),
            "orientation": "M0",
            "value": "1N5819",
            "spiceline": "Ron=0.05",
        },
        {
            "inst": "R3",
            "symbol": "res",
            "asy": "res.asy",
            "origin": (560, 304),
            "orientation": "R270",
            "value": "1k",
        },
    ),
    "case_15.asc": (
        {
            "inst": "V2",
            "symbol": "voltage",
            "asy": "voltage.asy",
            "origin": (144, 96),
            "orientation": "R90",
            "value": "PULSE(0 5 0 1u 1u 10u 20u)",
            "spiceline": "Rser=0.001",
        },
        {
            "inst": "I2",
            "symbol": "Sources\\current",
            "asy": "current.asy",
            "origin": (320, 96),
            "orientation": "R270",
            "value": "AC 2",
            "type": "source",
        },
        {
            "inst": "M6",
            "symbol": "nmos",
            "asy": "nmos.asy",
            "origin": (528, 208),
            "orientation": "R90",
            "value": "SI2302",
            "type": "nmos",
        },
        {
            "inst": "M7",
            "symbol": "Power\\pmos",
            "asy": "pmos.asy",
            "origin": (736, 272),
            "orientation": "M180",
            "value": "FQP27P06",
            "spiceline": "m=6",
        },
    ),
}


def _orientation_angle(orientation: str) -> int:
    match = re.search(r"(\d+)$", orientation)
    if match is None:
        return 0
    return int(match.group(1)) % 360


def _transform_point(local_point: tuple[int, int], origin: tuple[int, int], orientation: str) -> tuple[int, int]:
    x_position, y_position = local_point
    angle = _orientation_angle(orientation)
    normalized_orientation = orientation.upper()
    if angle == 90:
        x_position, y_position = -y_position, x_position
    elif angle == 180:
        x_position, y_position = -x_position, -y_position
    elif angle == 270:
        x_position, y_position = y_position, -x_position
    if normalized_orientation.startswith("M"):
        x_position = -x_position
    return origin[0] + x_position, origin[1] + y_position


def _transform_rectangle(bounds, origin: tuple[int, int], orientation: str) -> list[list[int]]:
    minimum_point = (int(bounds[0][0]), int(bounds[0][1]))
    maximum_point = (int(bounds[1][0]), int(bounds[1][1]))
    corners = (
        minimum_point,
        (maximum_point[0], minimum_point[1]),
        (minimum_point[0], maximum_point[1]),
        maximum_point,
    )
    transformed_corners = [_transform_point(corner, origin, orientation) for corner in corners]
    x_positions = [point[0] for point in transformed_corners]
    y_positions = [point[1] for point in transformed_corners]
    return [[min(x_positions), min(y_positions)], [max(x_positions), max(y_positions)]]


def _display_symbol_name(symbol_name: str) -> str:
    return symbol_name.replace("\\", "/").split("/")[-1]


def _build_expected_symbol_entry(spec: dict[str, object]) -> dict[str, object]:
    asy_path = _VALID_ASY_DIRECTORY / str(spec["asy"])
    pins = get_ltspice_asy_pins(str(asy_path))
    bounds = get_ltspice_asy_size(str(asy_path))
    origin = spec["origin"]
    orientation = str(spec["orientation"])
    transformed_pins = [
        [
            transformed_point[0],
            transformed_point[1],
            pin_name,
            spice_order,
        ]
        for pin_x, pin_y, pin_name, spice_order in pins
        for transformed_point in [_transform_point((int(pin_x), int(pin_y)), origin, orientation)]
    ]
    expected_symbol = {
        "SYMBOL": _display_symbol_name(str(spec["symbol"])),
        "X": origin[0],
        "Y": origin[1],
        "ORIENTATION": orientation,
        "RECTANGLE": _transform_rectangle(bounds, origin, orientation),
        "PINS": transformed_pins,
    }
    for spec_key, result_key in (("value", "VALUE"), ("spiceline", "SPICELINE"), ("type", "TYPE")):
        if spec_key in spec:
            expected_symbol[result_key] = spec[spec_key]
    return expected_symbol


class TestGetLtspiceAscSymbolInfo(unittest.TestCase):
    def test_all_symbol_info_fixtures(self) -> None:
        fixture_paths = sorted(_FIXTURE_DIRECTORY.glob("case_*.asc"))
        self.assertEqual(len(fixture_paths), 15, msg="The ASC symbol-info tests require exactly 15 fixtures.")
        convert_settings = {
            "ltspice_windows_path": "C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
            "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
            "custom_search_paths": [str(_VALID_ASY_DIRECTORY)],
            "grid_size": 16,
            "voltage_must_have_dc": False,
        }
        for fixture_path in fixture_paths:
            with self.subTest(fixture=fixture_path.name):
                expected_symbols = {
                    str(spec["inst"]): _build_expected_symbol_entry(spec)
                    for spec in _CASE_SPECS[fixture_path.name]
                }
                result = get_ltspice_asc_symbol_info(str(fixture_path), convert_settings)
                self.assertEqual(result, expected_symbols, msg=f"{fixture_path.name} returned unexpected symbol info.")
                for symbol_entry in result.values():
                    self.assertIn("ORIENTATION", symbol_entry, msg=f"{fixture_path.name} should expose ORIENTATION in symbol info.")
                    self.assertNotIn("ROTATION", symbol_entry, msg=f"{fixture_path.name} should no longer expose ROTATION in symbol info.")
