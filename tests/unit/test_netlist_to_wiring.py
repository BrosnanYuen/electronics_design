"""Unit tests for LTspice netlist-to-wiring conversion."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from electronics_design import ltspice_netlist_to_wiring
from electronics_design import rectangle_points_to_lines
from electronics_design import ltspice_net as _net_module
from electronics_design.pathtracing import are_wires_connected
from electronics_design.pathtracing import are_wires_horizontal_or_vertical
from electronics_design.pathtracing import are_wires_intersecting_obstacles_fast
from electronics_design.pathtracing import find_wire_group_index
from electronics_design.pathtracing import get_wire_pos
from electronics_design.pathtracing import place_wires_into_groups

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_FIXTURE_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "netlist_to_wire"
_CONVERT_SETTINGS = {
    "ltspice_windows_path": "C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
    "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
    "custom_search_paths": ["./valid_asy/"],
    "minimum_dist": 32,
    "wire_pin_out_dist": 16,
    "grid_size": 16,
}


@dataclass(frozen=True)
class _Attachment:
    pin_point: tuple[int, int]
    exit_point: tuple[int, int]


def _collect_logical_code_lines(lines: list[str]) -> tuple[tuple[int, str], ...]:
    logical_lines: list[tuple[int, str]] = []
    current_line_number = 0
    current_parts: list[str] = []
    for line_number, raw_line in enumerate(lines, start=1):
        classification_result = _net_module._classify_line(raw_line)
        if not classification_result[0]:
            continue
        kind = classification_result[1]
        if kind in {"blank", "comment"}:
            if current_parts:
                logical_lines.append((current_line_number, " ".join(current_parts).strip()))
                current_line_number = 0
                current_parts = []
            continue
        if kind == "continuation":
            continuation_text = _net_module._strip_semicolon_comment(raw_line).lstrip()[1:].strip()
            if current_parts and continuation_text != "":
                current_parts.append(continuation_text)
            continue
        if kind != "device":
            if current_parts:
                logical_lines.append((current_line_number, " ".join(current_parts).strip()))
                current_line_number = 0
                current_parts = []
            continue
        code_text = _net_module._strip_semicolon_comment(raw_line).strip()
        if code_text == "":
            continue
        if current_parts:
            logical_lines.append((current_line_number, " ".join(current_parts).strip()))
        current_line_number = line_number
        current_parts = [code_text]
    if current_parts:
        logical_lines.append((current_line_number, " ".join(current_parts).strip()))
    return tuple(logical_lines)


def _normalize_instance_name(instance_token: str) -> str:
    clean_token = instance_token.strip()
    if "§" in clean_token:
        return clean_token.split("§", 1)[1].strip()
    return clean_token


def _expected_attachments(
    netlist_fixture_path: Path,
    symbol_pose: dict[str, dict[str, object]],
) -> dict[str, tuple[_Attachment, ...]]:
    attachments_by_net: dict[str, list[_Attachment]] = {}
    logical_lines = _collect_logical_code_lines(netlist_fixture_path.read_text(encoding="utf-8").splitlines())
    exit_distance = int(_CONVERT_SETTINGS["minimum_dist"]) + int(_CONVERT_SETTINGS["wire_pin_out_dist"])
    for _line_number, code_text in logical_lines:
        tokens = code_text.split()
        if not tokens or tokens[0][0].upper() == "K":
            continue
        instance_name = _normalize_instance_name(tokens[0])
        symbol_entry = symbol_pose[instance_name]
        pins = sorted(symbol_entry["PINS"], key=lambda pin_row: int(pin_row[3]))
        node_result = _net_module._extract_nodes(tokens)
        if not node_result[0]:
            continue
        for node_name, pin_row in zip(node_result[1][: len(pins)], pins):
            if str(node_name).upper().startswith(("NC", "NC_", "NC-")):
                continue
            pin_point = (int(pin_row[0]), int(pin_row[1]))
            rectangle = symbol_entry["RECTANGLE"]
            exit_point = _pin_exit_point(
                ((int(rectangle[0][0]), int(rectangle[0][1])), (int(rectangle[1][0]), int(rectangle[1][1]))),
                pin_point,
                exit_distance,
                16,
            )
            attachments_by_net.setdefault(str(node_name), []).append(_Attachment(pin_point=pin_point, exit_point=exit_point))
    return {net_name: tuple(attachments) for net_name, attachments in attachments_by_net.items()}


def _pin_exit_point(
    rectangle: tuple[tuple[int, int], tuple[int, int]],
    pin_point: tuple[int, int],
    exit_distance: int,
    routing_grid: int,
) -> tuple[int, int]:
    minimum_x = min(rectangle[0][0], rectangle[1][0])
    maximum_x = max(rectangle[0][0], rectangle[1][0])
    minimum_y = min(rectangle[0][1], rectangle[1][1])
    maximum_y = max(rectangle[0][1], rectangle[1][1])
    center_x = (minimum_x + maximum_x) / 2.0
    center_y = (minimum_y + maximum_y) / 2.0
    pin_x, pin_y = pin_point
    if pin_x <= minimum_x:
        return (_snap_to_grid(pin_x - exit_distance, routing_grid), _snap_to_grid(pin_y, routing_grid))
    if pin_x >= maximum_x:
        return (_snap_to_grid(pin_x + exit_distance, routing_grid), _snap_to_grid(pin_y, routing_grid))
    if pin_y <= minimum_y:
        return (_snap_to_grid(pin_x, routing_grid), _snap_to_grid(pin_y - exit_distance, routing_grid))
    if pin_y >= maximum_y:
        return (_snap_to_grid(pin_x, routing_grid), _snap_to_grid(pin_y + exit_distance, routing_grid))
    if abs(pin_x - center_x) >= abs(pin_y - center_y):
        return (_snap_to_grid(pin_x + (-exit_distance if pin_x < center_x else exit_distance), routing_grid), _snap_to_grid(pin_y, routing_grid))
    return (_snap_to_grid(pin_x, routing_grid), _snap_to_grid(pin_y + (-exit_distance if pin_y < center_y else exit_distance), routing_grid))


def _snap_to_grid(value: int, routing_grid: int) -> int:
    if value % routing_grid == 0:
        return value
    lower_value = value - (value % routing_grid)
    upper_value = lower_value + routing_grid
    return lower_value if abs(value - lower_value) <= abs(upper_value - value) else upper_value


def _obstacle_array(symbol_pose: dict[str, dict[str, object]]) -> np.ndarray:
    obstacle_rows: list[list[int]] = []
    minimum_dist = int(_CONVERT_SETTINGS["minimum_dist"])
    for symbol_entry in symbol_pose.values():
        rectangle = symbol_entry["RECTANGLE"]
        minimum_x = min(int(rectangle[0][0]), int(rectangle[1][0])) - minimum_dist
        minimum_y = min(int(rectangle[0][1]), int(rectangle[1][1])) - minimum_dist
        maximum_x = max(int(rectangle[0][0]), int(rectangle[1][0])) + minimum_dist
        maximum_y = max(int(rectangle[0][1]), int(rectangle[1][1])) + minimum_dist
        rectangle_lines = rectangle_points_to_lines(np.asarray([[minimum_x, minimum_y], [maximum_x, maximum_y]], dtype=int))
        obstacle_rows.extend(rectangle_lines.tolist())
    return np.asarray(obstacle_rows, dtype=int)


class TestNetlistToWiring(unittest.TestCase):
    def test_all_netlist_to_wire_fixtures(self) -> None:
        netlist_fixture_paths = sorted(_FIXTURE_DIRECTORY.glob("case_*.net"))
        self.assertEqual(len(netlist_fixture_paths), 15, msg="The netlist-to-wire tests require exactly 15 netlist fixtures.")
        with tempfile.TemporaryDirectory() as temporary_directory:
            for netlist_fixture_path in netlist_fixture_paths:
                with self.subTest(fixture=netlist_fixture_path.name):
                    symbol_pose_path = _FIXTURE_DIRECTORY / f"{netlist_fixture_path.stem}_symbols.json"
                    self.assertTrue(symbol_pose_path.exists(), msg=f"Missing symbol-pose fixture for {netlist_fixture_path.name}.")
                    output_path = Path(temporary_directory) / f"{netlist_fixture_path.stem}_wires.json"
                    result = ltspice_netlist_to_wiring(
                        str(netlist_fixture_path),
                        str(symbol_pose_path),
                        str(output_path),
                        _CONVERT_SETTINGS,
                    )
                    self.assertEqual(result, (True, "OK", 0), msg=f"{netlist_fixture_path.name} should route successfully.")
                    generated_wires = json.loads(output_path.read_text(encoding="utf-8"))
                    symbol_pose = json.loads(symbol_pose_path.read_text(encoding="utf-8"))
                    attachments_by_net = _expected_attachments(netlist_fixture_path, symbol_pose)
                    self.assertEqual(
                        set(generated_wires.keys()),
                        set(attachments_by_net.keys()),
                        msg=f"{netlist_fixture_path.name} should emit one wire group per routed net.",
                    )
                    obstacle_array = _obstacle_array(symbol_pose)
                    all_wire_arrays = {
                        net_name: np.asarray(wire_rows, dtype=int)
                        for net_name, wire_rows in generated_wires.items()
                    }
                    for net_name, attachments in attachments_by_net.items():
                        wires = all_wire_arrays[net_name]
                        self.assertEqual(wires.ndim, 2, msg=f"{netlist_fixture_path.name}:{net_name} should serialize as a 2D wire array.")
                        self.assertEqual(wires.shape[1], 4, msg=f"{netlist_fixture_path.name}:{net_name} should contain X1 Y1 X2 Y2 rows.")
                        self.assertTrue(len(wires) > 0, msg=f"{netlist_fixture_path.name}:{net_name} should contain at least one wire.")
                        self.assertTrue(are_wires_horizontal_or_vertical(wires), msg=f"{netlist_fixture_path.name}:{net_name} should be axis-aligned.")
                        self.assertTrue(are_wires_connected(wires), msg=f"{netlist_fixture_path.name}:{net_name} should be connected.")
                        stub_rows = {
                            (
                                attachment.pin_point[0],
                                attachment.pin_point[1],
                                attachment.exit_point[0],
                                attachment.exit_point[1],
                            )
                            for attachment in attachments
                            if attachment.pin_point != attachment.exit_point
                        }
                        for stub_row in stub_rows:
                            self.assertIn(
                                list(stub_row),
                                wires.tolist(),
                                msg=f"{netlist_fixture_path.name}:{net_name} should include the required pin escape wire {stub_row}.",
                            )
                        route_rows = [wire_row for wire_row in wires.tolist() if tuple(wire_row) not in stub_rows]
                        if route_rows:
                            self.assertFalse(
                                are_wires_intersecting_obstacles_fast(np.asarray(route_rows, dtype=int), obstacle_array),
                                msg=f"{netlist_fixture_path.name}:{net_name} routed segments should avoid buffered symbol rectangles.",
                            )
                        wire_groups = place_wires_into_groups(wires)
                        for attachment in attachments:
                            point_array = np.asarray([attachment.pin_point[0], attachment.pin_point[1]], dtype=int)
                            self.assertNotEqual(
                                find_wire_group_index(point_array, wire_groups),
                                -1,
                                msg=f"{netlist_fixture_path.name}:{net_name} should connect pin {attachment.pin_point}.",
                            )
                        other_net_rows = [
                            wire_row
                            for other_net_name, other_wires in generated_wires.items()
                            if other_net_name != net_name
                            for wire_row in other_wires
                        ]
                        if other_net_rows:
                            other_groups = place_wires_into_groups(np.asarray(other_net_rows, dtype=int))
                            for point_row in get_wire_pos(wires):
                                self.assertEqual(
                                    find_wire_group_index(np.asarray(point_row, dtype=int), other_groups),
                                    -1,
                                    msg=f"{netlist_fixture_path.name}:{net_name} endpoints should not lie on another net's wire group.",
                                )

    def test_invalid_convert_settings_are_rejected(self) -> None:
        fixture_path = _FIXTURE_DIRECTORY / "case_01.net"
        symbol_pose_path = _FIXTURE_DIRECTORY / "case_01_symbols.json"
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "case_01_wires.json"
            self.assertEqual(
                ltspice_netlist_to_wiring(str(fixture_path), str(symbol_pose_path), str(output_path), {"minimum_dist": -1, "wire_pin_out_dist": 16}),
                (False, "INVALID_CONVERT_SETTINGS", 0),
            )

    def test_routed_net_endpoints_do_not_land_on_other_net_groups(self) -> None:
        netlist_text = """* multi-net routing isolation regression
V1 N001 0 6
C1 N002 N004 0.01
L1 N001 N003 0.2 Rser=1m
R1 N004 0 10k
D1 N003 0 D
V2 N002 0 9
R2 N003 0 5k
.model D D
.lib C:\\users\\brosnan\\AppData\\Local\\LTspice\\lib\\cmp\\standard.dio
.tran 0 1 0.1
.backanno
.end
"""
        symbol_pose = {
            "V1": {
                "SYMBOL": "voltage",
                "X": 96,
                "Y": 80,
                "ORIENTATION": "R0",
                "RECTANGLE": [[64, 96], [128, 176]],
                "PINS": [[96, 96, "+", 1], [96, 176, "-", 2]],
                "VALUE": "6",
            },
            "C1": {
                "SYMBOL": "cap",
                "X": 176,
                "Y": 96,
                "ORIENTATION": "R0",
                "RECTANGLE": [[176, 96], [208, 160]],
                "PINS": [[192, 96, "A", 1], [192, 160, "B", 2]],
                "VALUE": "0.01",
            },
            "L1": {
                "SYMBOL": "ind",
                "X": 272,
                "Y": 80,
                "ORIENTATION": "R0",
                "RECTANGLE": [[272, 96], [304, 176]],
                "PINS": [[288, 96, "A", 1], [288, 176, "B", 2]],
                "VALUE": "0.2",
                "SPICELINE": "Rser=1m",
            },
            "R1": {
                "SYMBOL": "res",
                "X": 272,
                "Y": 224,
                "ORIENTATION": "R0",
                "RECTANGLE": [[272, 240], [304, 320]],
                "PINS": [[288, 240, "A", 1], [288, 320, "B", 2]],
                "VALUE": "10k",
            },
            "D1": {
                "SYMBOL": "diode",
                "X": 176,
                "Y": 240,
                "ORIENTATION": "R0",
                "RECTANGLE": [[176, 240], [208, 304]],
                "PINS": [[192, 240, "+", 1], [192, 304, "-", 2]],
            },
            "V2": {
                "SYMBOL": "voltage",
                "X": 384,
                "Y": 80,
                "ORIENTATION": "R0",
                "RECTANGLE": [[352, 96], [416, 176]],
                "PINS": [[384, 96, "+", 1], [384, 176, "-", 2]],
                "VALUE": "9",
            },
            "R2": {
                "SYMBOL": "res",
                "X": 96,
                "Y": 224,
                "ORIENTATION": "R0",
                "RECTANGLE": [[96, 240], [128, 320]],
                "PINS": [[112, 240, "A", 1], [112, 320, "B", 2]],
                "VALUE": "5k",
            },
        }
        expected_net_names = {"N001", "N002", "N003", "N004", "0"}
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            netlist_path = temporary_path / "isolation_case.net"
            symbol_pose_path = temporary_path / "isolation_case_symbols.json"
            output_path = temporary_path / "isolation_case_wires.json"
            netlist_path.write_text(netlist_text, encoding="utf-8")
            symbol_pose_path.write_text(json.dumps(symbol_pose, indent=2) + "\n", encoding="utf-8")

            convert_settings = {
                "ltspice_windows_path": "C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
                "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
                "custom_search_paths": ["./valid_asy/"],
                "minimum_dist": 0,
                "wire_pin_out_dist": 16,
                "grid_size": 16,
            }
            result = ltspice_netlist_to_wiring(
                str(netlist_path),
                str(symbol_pose_path),
                str(output_path),
                convert_settings,
            )

            self.assertEqual(result, (True, "OK", 0))
            generated_wires = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(set(generated_wires.keys()), expected_net_names)

            all_wire_arrays = {
                net_name: np.asarray(wire_rows, dtype=int)
                for net_name, wire_rows in generated_wires.items()
            }
            for net_name, wires in all_wire_arrays.items():
                self.assertTrue(are_wires_connected(wires), msg=f"{net_name} should remain internally connected.")
                other_net_rows = [
                    wire_row
                    for other_net_name, other_wires in generated_wires.items()
                    if other_net_name != net_name
                    for wire_row in other_wires
                ]
                self.assertTrue(other_net_rows, msg=f"{net_name} should be checked against the other routed nets.")
                other_groups = place_wires_into_groups(np.asarray(other_net_rows, dtype=int))
                for point_row in get_wire_pos(wires):
                    self.assertEqual(
                        find_wire_group_index(np.asarray(point_row, dtype=int), other_groups),
                        -1,
                        msg=f"{net_name} endpoints must not start or end on another net's wire group.",
                    )
