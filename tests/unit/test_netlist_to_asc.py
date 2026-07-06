"""Unit tests for end-to-end LTspice netlist-to-ASC conversion."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from electronics_design import is_valid_ltspice_asc_file
from electronics_design import ltspice_autoplace_symbol_pose
from electronics_design import ltspice_netlist_to_asc
from electronics_design import ltspice_netlist_symbol_wire_to_asc
from electronics_design import ltspice_netlist_to_symbol_initial
from electronics_design.pathtracing import are_wires_connected
from electronics_design.pathtracing import place_wires_into_groups

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_VALID_CONVERT_DIRECTORY = _ROOT_DIRECTORY / "valid_convert"
_VALID_NETLIST_DIRECTORY = _VALID_CONVERT_DIRECTORY / "netlist"
_VALID_ASC_GEN_DIRECTORY = _VALID_CONVERT_DIRECTORY / "asc_gen"
_CONVERT_SETTINGS = {
    "ltspice_windows_path": "C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
    "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
    "custom_search_paths": ["./valid_asy/"],
    "minimum_dist": 16,
    "wire_pin_out_dist": 16,
    "autoplace_iter": 12,
    "grid_size": 16,
    "ltspice_version": 4.1,
}
_SELECTED_FIXTURES = (
    "RC-lowpass.net",
    "Astable-multivibrator.net",
)


def _load_wire_arrays(filepath: Path) -> dict[str, np.ndarray]:
    wire_mapping = json.loads(filepath.read_text(encoding="utf-8"))
    return {
        net_name: np.asarray(wire_rows, dtype=int)
        for net_name, wire_rows in wire_mapping.items()
    }


def _read_asc_wire_rows(filepath: Path) -> tuple[tuple[int, int, int, int], ...]:
    wire_rows: list[tuple[int, int, int, int]] = []
    for raw_line in filepath.read_text(encoding="latin-1").splitlines():
        stripped_line = raw_line.strip()
        if not stripped_line.startswith("WIRE "):
            continue
        tokens = stripped_line.split()
        wire_rows.append((int(tokens[1]), int(tokens[2]), int(tokens[3]), int(tokens[4])))
    return tuple(wire_rows)


def _wire_group_signatures(wire_groups: list[np.ndarray]) -> set[frozenset[tuple[int, int, int, int]]]:
    return {
        frozenset(tuple(int(value) for value in wire_row) for wire_row in wire_group.tolist())
        for wire_group in wire_groups
    }


class TestNetlistToAsc(unittest.TestCase):
    def test_selected_valid_convert_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            for fixture_name in _SELECTED_FIXTURES:
                with self.subTest(fixture=fixture_name):
                    netlist_path = _VALID_NETLIST_DIRECTORY / fixture_name
                    expected_asc_path = _VALID_ASC_GEN_DIRECTORY / f"{netlist_path.stem}.asc"
                    self.assertTrue(netlist_path.exists(), msg=f"Missing netlist fixture {fixture_name}.")
                    self.assertTrue(expected_asc_path.exists(), msg=f"Missing ASC fixture for {fixture_name}.")
                    output_path = Path(temporary_directory) / f"{netlist_path.stem}.asc"
                    result = ltspice_netlist_to_asc(
                        str(netlist_path),
                        str(output_path),
                        _CONVERT_SETTINGS,
                    )
                    self.assertEqual(result, (True, "OK", 0), msg=f"{fixture_name} should convert successfully.")
                    self.assertEqual(
                        is_valid_ltspice_asc_file(str(output_path)),
                        (True, ""),
                        msg=f"{fixture_name} should generate a valid ASC file.",
                    )
                    manual_symbol_path = Path(temporary_directory) / f"{netlist_path.stem}_manual_symbol.json"
                    manual_wire_path = Path(temporary_directory) / f"{netlist_path.stem}_manual_wires.json"
                    manual_asc_path = Path(temporary_directory) / f"{netlist_path.stem}_manual.asc"
                    self.assertEqual(
                        ltspice_netlist_to_symbol_initial(
                            str(netlist_path),
                            str(manual_symbol_path),
                            _CONVERT_SETTINGS,
                        ),
                        (True, "OK", 0),
                        msg=f"{fixture_name} should generate the initial symbol JSON through the public pipeline.",
                    )
                    self.assertEqual(
                        ltspice_autoplace_symbol_pose(
                            str(netlist_path),
                            str(manual_symbol_path),
                            str(manual_wire_path),
                            _CONVERT_SETTINGS,
                        ),
                        (True, "OK", 0),
                        msg=f"{fixture_name} should autoplace successfully through the public pipeline.",
                    )
                    manual_wires_by_net = _load_wire_arrays(manual_wire_path)
                    self.assertTrue(
                        manual_wires_by_net,
                        msg=f"{fixture_name} should generate at least one routed net in the intermediate wire JSON.",
                    )
                    for net_name, wire_array in manual_wires_by_net.items():
                        self.assertEqual(
                            wire_array.ndim,
                            2,
                            msg=f"{fixture_name}:{net_name} should serialize wires as a 2D array.",
                        )
                        self.assertEqual(
                            wire_array.shape[1],
                            4,
                            msg=f"{fixture_name}:{net_name} should contain X1 Y1 X2 Y2 wire rows.",
                        )
                        self.assertTrue(
                            len(wire_array) > 0,
                            msg=f"{fixture_name}:{net_name} should contain at least one generated wire segment.",
                        )
                        self.assertTrue(
                            are_wires_connected(wire_array),
                            msg=f"{fixture_name}:{net_name} should remain internally connected after routing.",
                        )
                    self.assertEqual(
                        ltspice_netlist_symbol_wire_to_asc(
                            str(netlist_path),
                            str(manual_symbol_path),
                            str(manual_wire_path),
                            str(manual_asc_path),
                            _CONVERT_SETTINGS,
                        ),
                        (True, "OK", 0),
                        msg=f"{fixture_name} should generate the final ASC through the public pipeline.",
                    )
                    manual_wire_rows = tuple(
                        tuple(int(value) for value in wire_row)
                        for wire_array in manual_wires_by_net.values()
                        for wire_row in wire_array.tolist()
                    )
                    generated_asc_wires = _read_asc_wire_rows(output_path)
                    manual_asc_wires = _read_asc_wire_rows(manual_asc_path)
                    self.assertTrue(
                        generated_asc_wires,
                        msg=f"{fixture_name} should emit WIRE records in the generated ASC output.",
                    )
                    self.assertEqual(
                        sorted(generated_asc_wires),
                        sorted(manual_wire_rows),
                        msg=f"{fixture_name} should preserve every routed wire segment in the direct ASC output.",
                    )
                    self.assertEqual(
                        sorted(manual_asc_wires),
                        sorted(manual_wire_rows),
                        msg=f"{fixture_name} should preserve every routed wire segment in the explicit three-step ASC output.",
                    )
                    self.assertEqual(
                        _wire_group_signatures(place_wires_into_groups(np.asarray(generated_asc_wires, dtype=int))),
                        _wire_group_signatures(list(manual_wires_by_net.values())),
                        msg=f"{fixture_name} should preserve the same connected wire groups in the final ASC output.",
                    )
                    self.assertEqual(
                        output_path.read_text(encoding="latin-1"),
                        manual_asc_path.read_text(encoding="latin-1"),
                        msg=f"{fixture_name} should match the explicit three-step public pipeline exactly.",
                    )

    def test_invalid_convert_settings_are_rejected(self) -> None:
        netlist_path = _VALID_NETLIST_DIRECTORY / "RC-lowpass.net"
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "RC-lowpass.asc"
            self.assertEqual(
                ltspice_netlist_to_asc(
                    str(netlist_path),
                    str(output_path),
                    [],
                ),
                (False, "INVALID_CONVERT_SETTINGS", 0),
            )
