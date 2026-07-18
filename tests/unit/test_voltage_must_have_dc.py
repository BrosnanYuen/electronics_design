"""Unit tests for opt-in DC values on AC-only voltage sources."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from electronics_design import ltspice_netlist_symbol_wire_to_asc
from electronics_design import ltspice_netlist_to_asc
from electronics_design import ltspice_netlist_to_symbol_initial


_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_BASE_CONVERT_SETTINGS = {
    "ltspice_windows_path": "C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
    "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
    "custom_search_paths": [str(_ROOT_DIRECTORY / "valid_asy")],
    "minimum_dist": 16,
    "wire_pin_out_dist": 16,
    "autoplace_iter": 12,
    "grid_size": 16,
    "ltspice_version": 4.1,
    "voltage_must_have_dc": False,
}
_NETLIST_TEXT = "\n".join(
    (
        "V1 IN 0 AC 2",
        "V6 VCC Vee AC 5",
        "V2 OUT 0 4 AC 2",
        ".ac dec 10 1 1k",
        ".backanno",
        ".end",
    )
) + "\n"


def _symbol_pose() -> dict[str, dict[str, object]]:
    return {
        "V1": {
            "SYMBOL": "voltage",
            "X": 0,
            "Y": 0,
            "ORIENTATION": "R0",
            "RECTANGLE": [],
            "PINS": [],
        },
        "V6": {
            "SYMBOL": "voltage",
            "X": 128,
            "Y": 0,
            "ORIENTATION": "R0",
            "RECTANGLE": [],
            "PINS": [],
        },
        "V2": {
            "SYMBOL": "voltage",
            "X": 256,
            "Y": 0,
            "ORIENTATION": "R0",
            "RECTANGLE": [],
            "PINS": [],
        },
    }


def _read_asc_symbol_attributes(filepath: Path) -> dict[str, dict[str, str]]:
    attributes_by_instance: dict[str, dict[str, str]] = {}
    pending_attributes: dict[str, str] = {}
    for raw_line in filepath.read_text(encoding="latin-1").splitlines():
        stripped_line = raw_line.strip()
        if stripped_line.startswith("SYMBOL "):
            pending_attributes = {}
            continue
        if not stripped_line.startswith("SYMATTR "):
            continue
        tokens = stripped_line.split(maxsplit=2)
        key = tokens[1]
        value = tokens[2] if len(tokens) > 2 else ""
        if key == "InstName":
            attributes_by_instance[value] = pending_attributes
            continue
        pending_attributes[key] = value
    return attributes_by_instance


class TestVoltageMustHaveDc(unittest.TestCase):
    def test_symbol_initial_adds_zero_only_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            netlist_path = temporary_path / "ac-only-voltage.net"
            netlist_path.write_text(_NETLIST_TEXT, encoding="utf-8")
            for setting_value, expected_zero in ((False, False), (True, True)):
                with self.subTest(voltage_must_have_dc=setting_value):
                    output_path = temporary_path / f"symbols-{setting_value}.json"
                    convert_settings = dict(_BASE_CONVERT_SETTINGS)
                    convert_settings["voltage_must_have_dc"] = setting_value
                    self.assertEqual(
                        ltspice_netlist_to_symbol_initial(
                            str(netlist_path),
                            str(output_path),
                            convert_settings,
                        ),
                        (True, "OK", 0),
                    )
                    symbol_initial = json.loads(output_path.read_text(encoding="utf-8"))
                    for instance_name in ("V1", "V6"):
                        if expected_zero:
                            self.assertEqual(symbol_initial[instance_name]["VALUE"], "0")
                        else:
                            self.assertNotIn("VALUE", symbol_initial[instance_name])
                    self.assertEqual(symbol_initial["V2"]["VALUE"], "4")

    def test_omitted_setting_defaults_to_false(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            netlist_path = temporary_path / "ac-only-voltage.net"
            output_path = temporary_path / "symbols.json"
            netlist_path.write_text(_NETLIST_TEXT, encoding="utf-8")
            convert_settings = dict(_BASE_CONVERT_SETTINGS)
            del convert_settings["voltage_must_have_dc"]
            self.assertEqual(
                ltspice_netlist_to_symbol_initial(
                    str(netlist_path),
                    str(output_path),
                    convert_settings,
                ),
                (True, "OK", 0),
            )
            symbol_initial = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertNotIn("VALUE", symbol_initial["V1"])
            self.assertNotIn("VALUE", symbol_initial["V6"])

    def test_symbol_wire_to_asc_adds_zero_before_ac_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            netlist_path = temporary_path / "ac-only-voltage.net"
            symbol_path = temporary_path / "symbols.json"
            wire_path = temporary_path / "wires.json"
            netlist_path.write_text(_NETLIST_TEXT, encoding="utf-8")
            symbol_path.write_text(json.dumps(_symbol_pose()), encoding="utf-8")
            wire_path.write_text("{}\n", encoding="utf-8")
            for setting_value in (False, True):
                with self.subTest(voltage_must_have_dc=setting_value):
                    output_path = temporary_path / f"output-{setting_value}.asc"
                    convert_settings = dict(_BASE_CONVERT_SETTINGS)
                    convert_settings["voltage_must_have_dc"] = setting_value
                    self.assertEqual(
                        ltspice_netlist_symbol_wire_to_asc(
                            str(netlist_path),
                            str(symbol_path),
                            str(wire_path),
                            str(output_path),
                            convert_settings,
                        ),
                        (True, "OK", 0),
                    )
                    attributes = _read_asc_symbol_attributes(output_path)
                    self.assertEqual(attributes["V1"].get("Value"), "0" if setting_value else None)
                    self.assertEqual(attributes["V1"]["Value2"], "AC 2")
                    self.assertEqual(attributes["V6"].get("Value"), "0" if setting_value else None)
                    self.assertEqual(attributes["V6"]["Value2"], "AC 5")
                    self.assertEqual(attributes["V2"]["Value"], "4")
                    self.assertEqual(attributes["V2"]["Value2"], "AC 2")

    def test_non_boolean_setting_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "symbols.json"
            convert_settings = dict(_BASE_CONVERT_SETTINGS)
            convert_settings["voltage_must_have_dc"] = "true"
            self.assertEqual(
                ltspice_netlist_to_symbol_initial(
                    "unused.net",
                    str(output_path),
                    convert_settings,
                ),
                (False, "INVALID_CONVERT_SETTINGS", 0),
            )
            self.assertEqual(
                ltspice_netlist_symbol_wire_to_asc(
                    "unused.net",
                    "unused-symbols.json",
                    "unused-wires.json",
                    str(output_path.with_suffix(".asc")),
                    convert_settings,
                ),
                (False, "INVALID_CONVERT_SETTINGS", 0),
            )

    def test_end_to_end_netlist_to_asc_uses_normalized_voltage(self) -> None:
        connected_netlist_text = "\n".join(
            (
                "V1 IN 0 AC 2",
                "R1 IN 0 1k",
                ".ac dec 10 1 1k",
                ".backanno",
                ".end",
            )
        ) + "\n"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            netlist_path = temporary_path / "connected-ac-only-voltage.net"
            output_path = temporary_path / "connected-ac-only-voltage.asc"
            netlist_path.write_text(connected_netlist_text, encoding="utf-8")
            convert_settings = dict(_BASE_CONVERT_SETTINGS)
            convert_settings["voltage_must_have_dc"] = True
            self.assertEqual(
                ltspice_netlist_to_asc(
                    str(netlist_path),
                    str(output_path),
                    convert_settings,
                ),
                (True, "OK", 0),
            )
            attributes = _read_asc_symbol_attributes(output_path)
            self.assertEqual(attributes["V1"]["Value"], "0")
            self.assertEqual(attributes["V1"]["Value2"], "AC 2")


if __name__ == "__main__":
    unittest.main()
