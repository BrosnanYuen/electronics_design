"""Unit tests for LTspice symbol autoplace and automatic wiring generation."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from electronics_design import ltspice_autoplace_symbol_pose
from electronics_design import ltspice_check_symbol_pose

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_VALID_NETLIST_DIRECTORY = _ROOT_DIRECTORY / "valid_convert" / "netlist"
_VALID_SYMBOL_INITIAL_DIRECTORY = _ROOT_DIRECTORY / "valid_convert" / "symbol_initial"
_VALID_SYMBOL_FINAL_DIRECTORY = _ROOT_DIRECTORY / "valid_convert" / "symbol_final"
_CONVERT_SETTINGS = {
    "ltspice_windows_path": "C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
    "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
    "custom_search_paths": ["./valid_asy/"],
    "minimum_dist": 32,
    "wire_pin_out_dist": 16,
    "autoplace_iter": 12,
    "grid_size": 16,
}
_BULK_AUTOPLACE_CONVERT_SETTINGS = {
    **_CONVERT_SETTINGS,
    "autoplace_skip_routing": True,
}
_POSE_KEYS = {"X", "Y", "ORIENTATION", "PINS", "RECTANGLE"}


def _load_json(filepath: Path) -> dict[str, object]:
    return json.loads(filepath.read_text(encoding="utf-8"))


class TestLtspiceAutoplaceSymbolPose(unittest.TestCase):
    def test_all_valid_convert_symbol_layouts(self) -> None:
        netlist_fixture_paths = sorted(_VALID_NETLIST_DIRECTORY.glob("*.net"))
        initial_fixture_paths = sorted(_VALID_SYMBOL_INITIAL_DIRECTORY.glob("*.json"))
        final_fixture_paths = sorted(_VALID_SYMBOL_FINAL_DIRECTORY.glob("*.json"))
        self.assertTrue(netlist_fixture_paths, msg="The autoplace tests require at least one netlist fixture.")
        self.assertEqual(
            [fixture.stem for fixture in netlist_fixture_paths],
            [fixture.stem for fixture in initial_fixture_paths],
            msg="The netlist and symbol-initial fixture sets must match one-to-one.",
        )
        self.assertEqual(
            [fixture.stem for fixture in netlist_fixture_paths],
            [fixture.stem for fixture in final_fixture_paths],
            msg="The netlist and symbol-final fixture sets must match one-to-one.",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_directory_path = Path(temporary_directory)
            for netlist_fixture_path in netlist_fixture_paths:
                with self.subTest(fixture=netlist_fixture_path.name):
                    initial_symbol_path = _VALID_SYMBOL_INITIAL_DIRECTORY / f"{netlist_fixture_path.stem}.json"
                    expected_final_symbol_path = _VALID_SYMBOL_FINAL_DIRECTORY / f"{netlist_fixture_path.stem}.json"
                    generated_symbol_path = temporary_directory_path / f"{netlist_fixture_path.stem}.json"
                    generated_wire_path = temporary_directory_path / f"{netlist_fixture_path.stem}_wires.json"
                    generated_symbol_path.write_text(initial_symbol_path.read_text(encoding="utf-8"), encoding="utf-8")
                    initial_symbol_pose = _load_json(initial_symbol_path)
                    expected_final_symbol_pose = _load_json(expected_final_symbol_path)
                    result = ltspice_autoplace_symbol_pose(
                        str(netlist_fixture_path),
                        str(generated_symbol_path),
                        str(generated_wire_path),
                        _BULK_AUTOPLACE_CONVERT_SETTINGS,
                    )
                    self.assertEqual(result, (True, "OK", 0), msg=f"{netlist_fixture_path.name} should autoplace successfully.")
                    generated_symbol_pose = _load_json(generated_symbol_path)
                    generated_wires = _load_json(generated_wire_path)
                    self.assertEqual(
                        set(generated_symbol_pose.keys()),
                        set(expected_final_symbol_pose.keys()),
                        msg=f"{netlist_fixture_path.name} should preserve the symbol instance set.",
                    )
                    self.assertIsInstance(generated_wires, dict, msg=f"{netlist_fixture_path.name} should emit a JSON wire mapping.")
                    self.assertEqual(
                        ltspice_check_symbol_pose(str(generated_symbol_path), _CONVERT_SETTINGS),
                        (False, None),
                        msg=f"{netlist_fixture_path.name} should not contain overlapping buffered symbols after autoplace.",
                    )
                    for instance_name in sorted(expected_final_symbol_pose):
                        generated_entry = generated_symbol_pose[instance_name]
                        expected_entry = expected_final_symbol_pose[instance_name]
                        initial_entry = initial_symbol_pose[instance_name]
                        self.assertTrue(str(generated_entry.get("ORIENTATION", "")).strip() != "", msg=f"{netlist_fixture_path.name}:{instance_name} should resolve a non-empty orientation.")
                        self.assertTrue(generated_entry.get("PINS"), msg=f"{netlist_fixture_path.name}:{instance_name} should resolve pins.")
                        self.assertTrue(generated_entry.get("RECTANGLE"), msg=f"{netlist_fixture_path.name}:{instance_name} should resolve a rectangle.")
                        generated_non_pose = {key: value for key, value in generated_entry.items() if key not in _POSE_KEYS}
                        initial_non_pose = {key: value for key, value in initial_entry.items() if key not in _POSE_KEYS}
                        self.assertEqual(
                            generated_non_pose,
                            initial_non_pose,
                            msg=f"{netlist_fixture_path.name}:{instance_name} should preserve all non-pose attributes.",
                        )
                        self.assertEqual(
                            len(generated_entry["PINS"]),
                            len(expected_entry["PINS"]),
                            msg=f"{netlist_fixture_path.name}:{instance_name} should preserve the resolved pin count from the ground-truth pose.",
                        )
                        generated_rectangle = generated_entry["RECTANGLE"]
                        expected_rectangle = expected_entry["RECTANGLE"]
                        generated_width = abs(int(generated_rectangle[1][0]) - int(generated_rectangle[0][0]))
                        generated_height = abs(int(generated_rectangle[1][1]) - int(generated_rectangle[0][1]))
                        expected_width = abs(int(expected_rectangle[1][0]) - int(expected_rectangle[0][0]))
                        expected_height = abs(int(expected_rectangle[1][1]) - int(expected_rectangle[0][1]))
                        self.assertEqual(
                            generated_width * generated_height,
                            expected_width * expected_height,
                            msg=f"{netlist_fixture_path.name}:{instance_name} should preserve the drawable rectangle area from the ground-truth pose.",
                        )

    def test_voltage_sources_are_forced_to_r0_orientation(self) -> None:
        netlist_fixture_path = _VALID_NETLIST_DIRECTORY / "RC-lowpass.net"
        initial_symbol_path = _VALID_SYMBOL_INITIAL_DIRECTORY / "RC-lowpass.json"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_directory_path = Path(temporary_directory)
            generated_symbol_path = temporary_directory_path / "RC-lowpass.json"
            generated_wire_path = temporary_directory_path / "RC-lowpass_wires.json"
            initial_symbol_pose = _load_json(initial_symbol_path)
            initial_symbol_pose["Vin"]["ORIENTATION"] = "R90"
            generated_symbol_path.write_text(
                json.dumps(initial_symbol_pose, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            result = ltspice_autoplace_symbol_pose(
                str(netlist_fixture_path),
                str(generated_symbol_path),
                str(generated_wire_path),
                _CONVERT_SETTINGS,
            )
            self.assertEqual(result, (True, "OK", 0))
            generated_symbol_pose = _load_json(generated_symbol_path)
            self.assertEqual(
                generated_symbol_pose["Vin"]["ORIENTATION"],
                "R0",
                msg="Voltage sources should always resolve to R0 orientation during autoplace.",
            )
