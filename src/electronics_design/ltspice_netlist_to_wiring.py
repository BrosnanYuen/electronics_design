"""Convert LTspice netlists plus symbol-pose JSON into routed wiring JSON."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
from typing import Dict
from typing import Iterable
from typing import List
from typing import Mapping
from typing import Optional
from typing import Sequence
from typing import Set
from typing import Tuple

import numpy as np

from . import ltspice_asc as _asc
from . import ltspice_net as _net
from .autoroute import _build_visibility_graph_for_terminals
from .autoroute import _route_simple_orthogonal
from .autoroute import _route_with_visibility_graph
from .ltspice_asy import rectangle_points_to_lines
from .pathtracing import are_wires_connected
from .pathtracing import are_wires_horizontal_or_vertical
from .pathtracing import find_wire_group_index
from .pathtracing import get_wire_pos
from .pathtracing import place_wires_into_groups

ConversionResult = Tuple[bool, str, int]
Point = Tuple[int, int]
WireRow = Tuple[int, int, int, int]

_OK_RESULT: ConversionResult = (True, "OK", 0)
_LINE_NUMBER_PATTERN = re.compile(r"Line (?P<line>\d+)")
_NO_CONNECT_PREFIXES = ("NC", "NC_", "NC-")


@dataclass(frozen=True)
class SymbolPosePin:
    point: Point
    pin_name: str
    spice_order: int


@dataclass(frozen=True)
class SymbolPoseEntry:
    instance_name: str
    rectangle: Tuple[Point, Point]
    pins: Tuple[SymbolPosePin, ...]


@dataclass(frozen=True)
class NetPinAttachment:
    net_name: str
    instance_name: str
    line_number: int
    pin_name: str
    spice_order: int
    pin_point: Point
    exit_point: Point


def ltspice_netlist_to_wiring(
    netlist_filepath: str,
    symbol_pose_filepath: str,
    wire_filepath_out: str,
    convert_settings: Mapping[str, object],
) -> ConversionResult:
    if not isinstance(convert_settings, Mapping):
        return False, "INVALID_CONVERT_SETTINGS", 0
    if not _coerce_path_success(wire_filepath_out):
        return False, "INVALID_OUTPUT_PATH", 0
    route_settings = _resolve_route_settings(convert_settings)
    if route_settings is None:
        return False, "INVALID_CONVERT_SETTINGS", 0
    format_validation_result = _net.is_valid_ltspice_netlist_format(netlist_filepath)
    if not format_validation_result[0]:
        return False, "INVALID_NETLIST_FILE", _line_number_from_message(format_validation_result[1], 0)
    read_result = _net._read_text_file_lines(netlist_filepath)
    if not read_result[0]:
        return False, "NETLIST_READ_ERROR", 0
    symbol_pose_result = _read_symbol_pose_entries(symbol_pose_filepath)
    if not symbol_pose_result[0]:
        return symbol_pose_result[1]
    logical_lines = _collect_logical_code_lines(read_result[1])
    routing_grid = _infer_routing_grid(
        symbol_pose_result[2],
        route_settings["minimum_dist"],
        route_settings["wire_pin_out_dist"],
        route_settings.get("grid_size"),
    )
    net_attachments_result = _collect_net_pin_attachments(
        logical_lines,
        symbol_pose_result[2],
        route_settings["minimum_dist"],
        route_settings["wire_pin_out_dist"],
        routing_grid,
    )
    if not net_attachments_result[0]:
        return False, net_attachments_result[1], net_attachments_result[2]
    symbol_obstacles = _build_symbol_obstacles(symbol_pose_result[2], route_settings["minimum_dist"])
    all_net_exit_points = {
        net_name: tuple(attachment.exit_point for attachment in attachments)
        for net_name, attachments in net_attachments_result[3].items()
    }
    ordered_attachments = _ordered_net_attachments(net_attachments_result[3])
    route_result = _route_all_nets(
        ordered_attachments,
        symbol_obstacles,
        routing_grid,
        all_net_exit_points,
    )
    if not route_result[0] and route_result[4] is not None:
        fallback_order = _promote_failed_net_first(ordered_attachments, route_result[4])
        route_result = _route_all_nets(
            fallback_order,
            symbol_obstacles,
            routing_grid,
            all_net_exit_points,
        )
    if not route_result[0]:
        return False, route_result[1], route_result[2]
    routed_wires = {
        net_name: [list(wire_row) for wire_row in wire_rows]
        for net_name, wire_rows in route_result[3].items()
    }
    write_result = _write_wire_json_file(wire_filepath_out, routed_wires)
    if not write_result[0]:
        return False, write_result[1], 0
    return _OK_RESULT


def _resolve_route_settings(convert_settings: Mapping[str, object]) -> Optional[Dict[str, int]]:
    minimum_dist = _coerce_non_negative_integer(convert_settings.get("minimum_dist", 0))
    wire_pin_out_dist = _coerce_non_negative_integer(convert_settings.get("wire_pin_out_dist", 0))
    grid_size = _coerce_positive_integer(convert_settings.get("grid_size", 0))
    if minimum_dist is None or wire_pin_out_dist is None:
        return None
    route_settings: Dict[str, int] = {
        "minimum_dist": minimum_dist,
        "wire_pin_out_dist": wire_pin_out_dist,
    }
    if grid_size is not None:
        route_settings["grid_size"] = grid_size
    return route_settings


def _coerce_non_negative_integer(value: object) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        integer_value = int(value)
    except (TypeError, ValueError):
        return None
    if integer_value < 0:
        return None
    return integer_value


def _coerce_positive_integer(value: object) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        integer_value = int(value)
    except (TypeError, ValueError):
        return None
    if integer_value <= 0:
        return None
    return integer_value


def _read_symbol_pose_entries(symbol_pose_filepath: str) -> Tuple[bool, ConversionResult, Dict[str, SymbolPoseEntry]]:
    try:
        symbol_pose_path = Path(os.fspath(symbol_pose_filepath))
    except TypeError:
        return False, (False, "INVALID_SYMBOL_POSE_PATH", 0), {}
    try:
        symbol_pose_json = json.loads(symbol_pose_path.read_text(encoding="utf-8"))
    except OSError:
        return False, (False, "SYMBOL_POSE_READ_ERROR", 0), {}
    except json.JSONDecodeError as error:
        return False, (False, "SYMBOL_POSE_PARSE_ERROR", error.lineno), {}
    if not isinstance(symbol_pose_json, dict):
        return False, (False, "SYMBOL_POSE_PARSE_ERROR", 0), {}
    entries: Dict[str, SymbolPoseEntry] = {}
    for instance_name, raw_entry in symbol_pose_json.items():
        try:
            entries[str(instance_name)] = _parse_symbol_pose_entry(str(instance_name), raw_entry)
        except (TypeError, ValueError):
            return False, (False, "SYMBOL_POSE_PARSE_ERROR", 0), {}
    return True, _OK_RESULT, entries


def _parse_symbol_pose_entry(instance_name: str, raw_entry: object) -> SymbolPoseEntry:
    if not isinstance(raw_entry, dict):
        raise ValueError("symbol pose entry must be a dictionary")
    rectangle = _parse_symbol_rectangle(raw_entry.get("RECTANGLE"))
    pins = _parse_symbol_pins(raw_entry.get("PINS"))
    return SymbolPoseEntry(instance_name=instance_name, rectangle=rectangle, pins=pins)


def _parse_symbol_rectangle(raw_rectangle: object) -> Tuple[Point, Point]:
    try:
        first_point, second_point = raw_rectangle
        first_x = int(first_point[0])
        first_y = int(first_point[1])
        second_x = int(second_point[0])
        second_y = int(second_point[1])
    except (TypeError, ValueError, IndexError) as error:
        raise ValueError("invalid rectangle") from error
    return (first_x, first_y), (second_x, second_y)


def _parse_symbol_pins(raw_pins: object) -> Tuple[SymbolPosePin, ...]:
    try:
        pin_rows = list(raw_pins)
    except TypeError as error:
        raise ValueError("invalid pins") from error
    pins: List[SymbolPosePin] = []
    for pin_row in pin_rows:
        try:
            pin_x, pin_y, pin_name, spice_order = pin_row
        except (TypeError, ValueError) as error:
            raise ValueError("invalid pin row") from error
        pins.append(
            SymbolPosePin(
                point=(int(pin_x), int(pin_y)),
                pin_name=str(pin_name),
                spice_order=int(spice_order),
            )
        )
    return tuple(sorted(pins, key=lambda pin: pin.spice_order))


@dataclass(frozen=True)
class LogicalCodeLine:
    line_number: int
    kind: str
    text: str


def _collect_logical_code_lines(lines: Sequence[str]) -> Tuple[LogicalCodeLine, ...]:
    logical_lines: List[LogicalCodeLine] = []
    current_line_number = 0
    current_kind = ""
    current_parts: List[str] = []
    for line_number, raw_line in enumerate(lines, start=1):
        classification_result = _net._classify_line(raw_line)
        if not classification_result[0]:
            continue
        kind = classification_result[1]
        if kind in {"blank", "comment"}:
            if current_parts:
                logical_lines.append(LogicalCodeLine(current_line_number, current_kind, " ".join(current_parts).strip()))
                current_line_number = 0
                current_kind = ""
                current_parts = []
            continue
        if kind == "continuation":
            continuation_text = _net._strip_semicolon_comment(raw_line).lstrip()[1:].strip()
            if current_parts and continuation_text != "":
                current_parts.append(continuation_text)
            continue
        code_text = _net._strip_semicolon_comment(raw_line).strip()
        if code_text == "":
            continue
        if current_parts:
            logical_lines.append(LogicalCodeLine(current_line_number, current_kind, " ".join(current_parts).strip()))
        current_line_number = line_number
        current_kind = kind
        current_parts = [code_text]
    if current_parts:
        logical_lines.append(LogicalCodeLine(current_line_number, current_kind, " ".join(current_parts).strip()))
    return tuple(logical_lines)


def _infer_routing_grid(
    symbol_pose_entries: Mapping[str, SymbolPoseEntry],
    minimum_dist: int,
    wire_pin_out_dist: int,
    explicit_grid_size: Optional[int] = None,
) -> int:
    if explicit_grid_size is not None and explicit_grid_size > 0:
        return explicit_grid_size
    coordinate_values: List[int] = [minimum_dist, wire_pin_out_dist]
    for symbol_entry in symbol_pose_entries.values():
        coordinate_values.extend(
            [
                symbol_entry.rectangle[0][0],
                symbol_entry.rectangle[0][1],
                symbol_entry.rectangle[1][0],
                symbol_entry.rectangle[1][1],
            ]
        )
        for pin in symbol_entry.pins:
            coordinate_values.extend([pin.point[0], pin.point[1]])
    grid = 0
    for value in coordinate_values:
        integer_value = abs(int(value))
        if integer_value == 0:
            continue
        grid = integer_value if grid == 0 else math.gcd(grid, integer_value)
    return max(grid, 16)


def _collect_net_pin_attachments(
    logical_lines: Sequence[LogicalCodeLine],
    symbol_pose_entries: Mapping[str, SymbolPoseEntry],
    minimum_dist: int,
    wire_pin_out_dist: int,
    routing_grid: int,
) -> Tuple[bool, str, int, Dict[str, Tuple[NetPinAttachment, ...]]]:
    attachments_by_net: Dict[str, List[NetPinAttachment]] = {}
    exit_distance = minimum_dist + wire_pin_out_dist
    for logical_line in logical_lines:
        if logical_line.kind != "device":
            continue
        tokens = logical_line.text.split()
        if not tokens or tokens[0][0].upper() == "K":
            continue
        instance_name = _normalize_instance_name(tokens[0])
        if instance_name == "":
            return False, "WIRING_GENERATION_ERROR", logical_line.line_number, {}
        if instance_name not in symbol_pose_entries:
            return False, "WIRING_GENERATION_ERROR", logical_line.line_number, {}
        node_result = _net._extract_nodes(tokens)
        if not node_result[0]:
            return False, "WIRING_GENERATION_ERROR", logical_line.line_number, {}
        symbol_entry = symbol_pose_entries[instance_name]
        node_names = node_result[1]
        if not node_names or not symbol_entry.pins:
            continue
        for pin in symbol_entry.pins:
            node_index = pin.spice_order - 1
            if node_index < 0 or node_index >= len(node_names):
                continue
            node_name = node_names[node_index]
            net_name = str(node_name).strip()
            if net_name == "":
                return False, "WIRING_GENERATION_ERROR", logical_line.line_number, {}
            exit_point = _pin_exit_point(symbol_entry.rectangle, pin.point, exit_distance, routing_grid)
            exit_point = _nudge_exit_point_off_buffered_boundary(
                symbol_entry.rectangle,
                pin.point,
                exit_point,
                minimum_dist,
                routing_grid,
            )
            attachment = NetPinAttachment(
                net_name=net_name,
                instance_name=instance_name,
                line_number=logical_line.line_number,
                pin_name=pin.pin_name,
                spice_order=pin.spice_order,
                pin_point=pin.point,
                exit_point=exit_point,
            )
            attachments_by_net.setdefault(net_name, []).append(attachment)
    normalized_attachments: Dict[str, Tuple[NetPinAttachment, ...]] = {}
    for net_name, attachments in attachments_by_net.items():
        if net_name.upper().startswith(_NO_CONNECT_PREFIXES):
            continue
        normalized_attachments[net_name] = tuple(
            sorted(
                attachments,
                key=lambda attachment: (
                    attachment.instance_name,
                    attachment.spice_order,
                    attachment.pin_name,
                ),
            )
        )
    return True, "OK", 0, normalized_attachments


def _normalize_instance_name(instance_token: str) -> str:
    cleaned_token = instance_token.strip()
    if cleaned_token == "":
        return ""
    if "§" in cleaned_token:
        return cleaned_token.split("§", 1)[1].strip()
    return cleaned_token


def _pin_exit_point(
    rectangle: Tuple[Point, Point],
    pin_point: Point,
    exit_distance: int,
    routing_grid: int,
) -> Point:
    minimum_x = min(rectangle[0][0], rectangle[1][0])
    maximum_x = max(rectangle[0][0], rectangle[1][0])
    minimum_y = min(rectangle[0][1], rectangle[1][1])
    maximum_y = max(rectangle[0][1], rectangle[1][1])
    center_x = (minimum_x + maximum_x) / 2.0
    center_y = (minimum_y + maximum_y) / 2.0
    pin_x, pin_y = pin_point
    effective_exit_distance = max(exit_distance, routing_grid)
    if pin_x <= minimum_x:
        return _snap_point_to_grid((pin_x - effective_exit_distance, pin_y), routing_grid)
    if pin_x >= maximum_x:
        return _snap_point_to_grid((pin_x + effective_exit_distance, pin_y), routing_grid)
    if pin_y <= minimum_y:
        return _snap_point_to_grid((pin_x, pin_y - effective_exit_distance), routing_grid)
    if pin_y >= maximum_y:
        return _snap_point_to_grid((pin_x, pin_y + effective_exit_distance), routing_grid)
    if abs(pin_x - center_x) >= abs(pin_y - center_y):
        return _snap_point_to_grid((pin_x + (-effective_exit_distance if pin_x < center_x else effective_exit_distance), pin_y), routing_grid)
    return _snap_point_to_grid((pin_x, pin_y + (-effective_exit_distance if pin_y < center_y else effective_exit_distance)), routing_grid)


def _snap_point_to_grid(point: Tuple[int, int], routing_grid: int) -> Point:
    return (
        _snap_coordinate_to_grid(point[0], routing_grid),
        _snap_coordinate_to_grid(point[1], routing_grid),
    )


def _snap_coordinate_to_grid(value: int, routing_grid: int) -> int:
    if routing_grid <= 0:
        return int(value)
    normalized_value = int(value)
    remainder = normalized_value % routing_grid
    if remainder == 0:
        return normalized_value
    lower_value = normalized_value - remainder
    upper_value = lower_value + routing_grid
    return lower_value if abs(normalized_value - lower_value) <= abs(upper_value - normalized_value) else upper_value


def _nudge_exit_point_off_buffered_boundary(
    rectangle: Tuple[Point, Point],
    pin_point: Point,
    exit_point: Point,
    minimum_dist: int,
    routing_grid: int,
) -> Point:
    buffered_rectangle = _buffer_rectangle(rectangle, minimum_dist)
    nudged_point = exit_point
    if not _point_is_inside_or_on_rectangle(nudged_point, buffered_rectangle):
        return nudged_point
    direction_x = 0
    direction_y = 0
    if exit_point[0] != pin_point[0]:
        direction_x = -1 if exit_point[0] < pin_point[0] else 1
    elif exit_point[1] != pin_point[1]:
        direction_y = -1 if exit_point[1] < pin_point[1] else 1
    else:
        minimum_x = min(rectangle[0][0], rectangle[1][0])
        maximum_x = max(rectangle[0][0], rectangle[1][0])
        minimum_y = min(rectangle[0][1], rectangle[1][1])
        maximum_y = max(rectangle[0][1], rectangle[1][1])
        center_x = (minimum_x + maximum_x) / 2.0
        center_y = (minimum_y + maximum_y) / 2.0
        if abs(pin_point[0] - center_x) >= abs(pin_point[1] - center_y):
            direction_x = -1 if pin_point[0] < center_x else 1
        else:
            direction_y = -1 if pin_point[1] < center_y else 1
    while _point_is_inside_or_on_rectangle(nudged_point, buffered_rectangle):
        nudged_point = (
            nudged_point[0] + (direction_x * routing_grid),
            nudged_point[1] + (direction_y * routing_grid),
        )
    return nudged_point


def _point_is_inside_or_on_rectangle(point: Point, rectangle: Tuple[Point, Point]) -> bool:
    minimum_x = min(rectangle[0][0], rectangle[1][0])
    maximum_x = max(rectangle[0][0], rectangle[1][0])
    minimum_y = min(rectangle[0][1], rectangle[1][1])
    maximum_y = max(rectangle[0][1], rectangle[1][1])
    point_x, point_y = point
    return minimum_x <= point_x <= maximum_x and minimum_y <= point_y <= maximum_y


def _build_symbol_obstacles(
    symbol_pose_entries: Mapping[str, SymbolPoseEntry],
    minimum_dist: int,
) -> Tuple[WireRow, ...]:
    obstacle_rows: List[WireRow] = []
    for symbol_entry in symbol_pose_entries.values():
        buffered_rectangle = _buffer_rectangle(symbol_entry.rectangle, minimum_dist)
        rectangle_lines = rectangle_points_to_lines(np.asarray(buffered_rectangle, dtype=int))
        obstacle_rows.extend(tuple(int(value) for value in line_row) for line_row in rectangle_lines.tolist())
    return tuple(obstacle_rows)


def _buffer_rectangle(rectangle: Tuple[Point, Point], minimum_dist: int) -> Tuple[Point, Point]:
    minimum_x = min(rectangle[0][0], rectangle[1][0]) - minimum_dist
    minimum_y = min(rectangle[0][1], rectangle[1][1]) - minimum_dist
    maximum_x = max(rectangle[0][0], rectangle[1][0]) + minimum_dist
    maximum_y = max(rectangle[0][1], rectangle[1][1]) + minimum_dist
    return (minimum_x, minimum_y), (maximum_x, maximum_y)


def _ordered_net_attachments(
    attachments_by_net: Mapping[str, Tuple[NetPinAttachment, ...]],
) -> Tuple[Tuple[str, Tuple[NetPinAttachment, ...]], ...]:
    return tuple(
        sorted(
            attachments_by_net.items(),
            key=lambda item: (
                item[0] == "0",
                -len(item[1]),
                item[0],
            ),
        )
    )


def _route_all_nets(
    ordered_attachments: Sequence[Tuple[str, Tuple[NetPinAttachment, ...]]],
    symbol_obstacles: Sequence[WireRow],
    routing_grid: int,
    all_net_exit_points: Mapping[str, Tuple[Point, ...]],
) -> Tuple[bool, str, int, Dict[str, Tuple[WireRow, ...]], Optional[str]]:
    routed_wires: Dict[str, Tuple[WireRow, ...]] = {}
    processed_other_net_wires: List[WireRow] = []
    for net_name, attachments in ordered_attachments:
        other_net_exit_points = {
            exit_point
            for other_net, exit_points in all_net_exit_points.items()
            if other_net != net_name
            for exit_point in exit_points
        }
        route_result = _route_single_net(
            attachments,
            symbol_obstacles,
            processed_other_net_wires,
            routing_grid,
            other_net_exit_points,
        )
        if not route_result[0]:
            return False, route_result[1], route_result[2], {}, net_name
        routed_wires[net_name] = route_result[3]
        processed_other_net_wires.extend(route_result[3])
    return True, "OK", 0, routed_wires, None


def _promote_failed_net_first(
    ordered_attachments: Sequence[Tuple[str, Tuple[NetPinAttachment, ...]]],
    failed_net_name: str,
) -> Tuple[Tuple[str, Tuple[NetPinAttachment, ...]], ...]:
    failed_items = [item for item in ordered_attachments if item[0] == failed_net_name]
    remaining_items = [item for item in ordered_attachments if item[0] != failed_net_name]
    return tuple(failed_items + remaining_items)


def _route_single_net(
    attachments: Sequence[NetPinAttachment],
    symbol_obstacles: Sequence[WireRow],
    processed_other_net_wires: Sequence[WireRow],
    routing_grid: int,
    other_net_exit_points: Set[Point] = (),
) -> Tuple[bool, str, int, Tuple[WireRow, ...]]:
    if not attachments:
        return True, "OK", 0, ()
    stub_wires = _dedupe_wire_rows(
        _stub_wire_for_attachment(attachment)
        for attachment in attachments
        if attachment.pin_point != attachment.exit_point
    )
    unique_exit_points = _unique_exit_points(attachments)
    if stub_wires:
        stub_validation_result = _validate_routed_net(attachments, stub_wires, processed_other_net_wires)
        if stub_validation_result[0]:
            return True, "OK", 0, stub_wires
    routed_segments: List[WireRow] = []
    if len(unique_exit_points) > 1:
        route_segments_result = _route_net_exit_points(
            attachments,
            unique_exit_points,
            symbol_obstacles,
            processed_other_net_wires,
            routing_grid,
            other_net_exit_points,
        )
        if not route_segments_result[0]:
            return False, route_segments_result[1], route_segments_result[2], ()
        routed_segments.extend(route_segments_result[3])
    wire_rows = _dedupe_wire_rows((*stub_wires, *routed_segments))
    validation_result = _validate_routed_net(attachments, wire_rows, processed_other_net_wires)
    if not validation_result[0]:
        return False, validation_result[1], validation_result[2], ()
    return True, "OK", 0, wire_rows


def _stub_wire_for_attachment(attachment: NetPinAttachment) -> WireRow:
    return (
        attachment.pin_point[0],
        attachment.pin_point[1],
        attachment.exit_point[0],
        attachment.exit_point[1],
    )


def _unique_exit_points(attachments: Sequence[NetPinAttachment]) -> Tuple[Point, ...]:
    unique_points: List[Point] = []
    seen_points: set[Point] = set()
    for attachment in attachments:
        if attachment.exit_point in seen_points:
            continue
        seen_points.add(attachment.exit_point)
        unique_points.append(attachment.exit_point)
    return tuple(unique_points)


def _route_net_exit_points(
    attachments: Sequence[NetPinAttachment],
    unique_exit_points: Sequence[Point],
    symbol_obstacles: Sequence[WireRow],
    processed_other_net_wires: Sequence[WireRow],
    routing_grid: int,
    other_net_exit_points: Set[Point] = (),
) -> Tuple[bool, str, int, Tuple[WireRow, ...]]:
    strict_route_result = _route_net_exit_points_with_obstacles(
        attachments,
        unique_exit_points,
        symbol_obstacles,
        processed_other_net_wires,
        routing_grid,
        other_net_exit_points,
    )
    if strict_route_result[0]:
        return strict_route_result
    return _route_net_exit_points_with_obstacles(
        attachments,
        unique_exit_points,
        symbol_obstacles,
        processed_other_net_wires,
        routing_grid,
        set(),
    )


def _route_net_exit_points_with_obstacles(
    attachments: Sequence[NetPinAttachment],
    unique_exit_points: Sequence[Point],
    symbol_obstacles: Sequence[WireRow],
    processed_other_net_wires: Sequence[WireRow],
    routing_grid: int,
    other_net_exit_points: Set[Point],
) -> Tuple[bool, str, int, Tuple[WireRow, ...]]:
    connected_points = [unique_exit_points[0]]
    disconnected_points = list(unique_exit_points[1:])
    route_segments: List[WireRow] = []
    other_net_endpoint_obstacles = _other_net_endpoint_obstacles(
        processed_other_net_wires,
        other_net_exit_points,
    )
    obstacle_array = _wire_rows_to_array((*symbol_obstacles, *other_net_endpoint_obstacles))
    visibility_graph = None
    while disconnected_points:
        connected_points = list(
            dict.fromkeys(
                (
                    *connected_points,
                    *_same_net_junction_candidates(route_segments, disconnected_points),
                )
            )
        )
        candidate_edges = sorted(
            (
                _manhattan_distance(connected_point, disconnected_point),
                connected_point,
                disconnected_point,
            )
            for connected_point in connected_points
            for disconnected_point in disconnected_points
        )
        routed_edge = None
        for _distance, start_point, end_point in candidate_edges:
            try:
                routed_wires = _route_simple_orthogonal(
                    start_point,
                    end_point,
                    obstacle_array,
                    routing_grid,
                    routing_grid,
                )
            except ValueError:
                continue
            routed_edge = tuple(tuple(int(value) for value in row) for row in routed_wires.tolist())
            if routed_edge:
                break
        if routed_edge is None:
            if visibility_graph is None:
                visibility_graph = _build_visibility_graph_for_terminals(
                    (*connected_points, *disconnected_points),
                    obstacle_array,
                    routing_grid,
                    routing_grid,
                )
            for _distance, start_point, end_point in candidate_edges:
                try:
                    routed_wires = _route_with_visibility_graph(
                        start_point,
                        end_point,
                        visibility_graph,
                        obstacle_array,
                        routing_grid,
                        routing_grid,
                    )
                except ValueError:
                    continue
                routed_edge = tuple(tuple(int(value) for value in row) for row in routed_wires.tolist())
                if routed_edge:
                    break
        if routed_edge is None:
            return False, "WIRING_GENERATION_ERROR", min(attachment.line_number for attachment in attachments), ()
        route_segments = list(_split_wire_rows_at_point(route_segments, start_point))
        route_segments.extend(routed_edge)
        for x1, y1, x2, y2 in routed_edge:
            for route_point in ((x1, y1), (x2, y2)):
                if route_point not in connected_points:
                    connected_points.append(route_point)
        visibility_graph = None
        disconnected_points.remove(end_point)
    return True, "OK", 0, _dedupe_wire_rows(route_segments)


def _same_net_junction_candidates(
    routed_segments: Sequence[WireRow],
    disconnected_points: Sequence[Point],
) -> Tuple[Point, ...]:
    """Offer T-junctions on an existing same-net trunk as routing targets."""

    candidates: List[Point] = []
    for x1, y1, x2, y2 in routed_segments:
        candidates.extend(((x1, y1), (x2, y2)))
        for point_x, point_y in disconnected_points:
            if y1 == y2 and min(x1, x2) <= point_x <= max(x1, x2):
                candidates.append((point_x, y1))
            elif x1 == x2 and min(y1, y2) <= point_y <= max(y1, y2):
                candidates.append((x1, point_y))
    return tuple(dict.fromkeys(candidates))


def _split_wire_rows_at_point(
    wire_rows: Sequence[WireRow],
    junction_point: Point,
) -> Tuple[WireRow, ...]:
    """Split any same-net segment whose interior receives a T-junction."""

    junction_x, junction_y = junction_point
    split_rows: List[WireRow] = []
    for x1, y1, x2, y2 in wire_rows:
        point_is_interior = (
            y1 == y2 == junction_y and min(x1, x2) < junction_x < max(x1, x2)
        ) or (
            x1 == x2 == junction_x and min(y1, y2) < junction_y < max(y1, y2)
        )
        if not point_is_interior:
            split_rows.append((x1, y1, x2, y2))
            continue
        split_rows.append((x1, y1, junction_x, junction_y))
        split_rows.append((junction_x, junction_y, x2, y2))
    return _dedupe_wire_rows(split_rows)


def _manhattan_distance(first_point: Point, second_point: Point) -> int:
    return abs(first_point[0] - second_point[0]) + abs(first_point[1] - second_point[1])


def _other_net_endpoint_obstacles(
    wire_rows: Sequence[WireRow],
    other_net_exit_points: Set[Point] = (),
) -> Tuple[WireRow, ...]:
    unique_points: set = set()
    for x1, y1, x2, y2 in wire_rows:
        unique_points.add((int(x1), int(y1)))
        unique_points.add((int(x2), int(y2)))
    unique_points.update((int(x), int(y)) for x, y in other_net_exit_points)
    return tuple((x, y, x, y) for x, y in sorted(unique_points))


def _wire_rows_to_array(wire_rows: Iterable[WireRow]) -> np.ndarray:
    rows = list(wire_rows)
    if not rows:
        return np.empty((0, 4), dtype=int)
    return np.asarray(rows, dtype=int)


def _validate_routed_net(
    attachments: Sequence[NetPinAttachment],
    wire_rows: Sequence[WireRow],
    processed_other_net_wires: Sequence[WireRow],
) -> ConversionResult:
    if not wire_rows:
        return False, "WIRING_GENERATION_ERROR", min(attachment.line_number for attachment in attachments)
    wire_array = _wire_rows_to_array(wire_rows)
    if not are_wires_horizontal_or_vertical(wire_array):
        return False, "WIRING_GENERATION_ERROR", min(attachment.line_number for attachment in attachments)
    if not are_wires_connected(wire_array):
        return False, "WIRING_GENERATION_ERROR", min(attachment.line_number for attachment in attachments)
    for attachment in attachments:
        if not _point_is_on_any_wire(attachment.pin_point, wire_rows):
            return False, "WIRING_GENERATION_ERROR", attachment.line_number
    if not processed_other_net_wires:
        return _OK_RESULT
    other_groups = place_wires_into_groups(_wire_rows_to_array(processed_other_net_wires))
    for point_row in get_wire_pos(wire_array):
        point = np.asarray(point_row, dtype=int)
        if find_wire_group_index(point, other_groups) != -1:
            return False, "WIRING_GENERATION_ERROR", min(attachment.line_number for attachment in attachments)
    return _OK_RESULT


def _point_is_on_any_wire(point: Point, wire_rows: Sequence[WireRow]) -> bool:
    point_array = np.asarray([point[0], point[1]], dtype=int)
    groups = place_wires_into_groups(_wire_rows_to_array(wire_rows))
    return find_wire_group_index(point_array, groups) != -1


def _dedupe_wire_rows(wire_rows: Iterable[WireRow]) -> Tuple[WireRow, ...]:
    deduped_rows: List[WireRow] = []
    seen_rows: set[WireRow] = set()
    for wire_row in wire_rows:
        normalized_row = tuple(int(value) for value in wire_row)
        if normalized_row in seen_rows:
            continue
        seen_rows.add(normalized_row)
        deduped_rows.append(normalized_row)
    return tuple(deduped_rows)


def _write_wire_json_file(filepath: str, wire_rows_by_net: Mapping[str, Sequence[Sequence[int]]]) -> Tuple[bool, str]:
    output_path_result = _asc._coerce_path(filepath)
    if not output_path_result[0]:
        return False, "INVALID_OUTPUT_PATH"
    output_path = Path(output_path_result[1])
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(wire_rows_by_net, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return False, "WRITE_ERROR"
    return True, "OK"


def _line_number_from_message(message: str, default_line: int) -> int:
    line_match = _LINE_NUMBER_PATTERN.search(message)
    if line_match is None:
        return default_line
    return int(line_match.group("line"))


def _coerce_path_success(filepath: str) -> bool:
    path_result = _asc._coerce_path(filepath)
    return bool(path_result[0])
