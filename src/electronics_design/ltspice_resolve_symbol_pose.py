"""Resolve LTspice symbol rectangles and pins inside symbol JSON files."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from typing import Dict
from typing import List
from typing import Mapping
from typing import Optional
from typing import Tuple

import numpy as np

from .ltspice_asc_to_netlist import get_ltspice_asc_symbol_info
from .ltspice_asy import rectangle_points_to_lines
from .pathtracing import are_wires_intersecting_obstacles_detailed

ConversionResult = Tuple[bool, str, int]
SymbolPoseCheckResult = Tuple[bool, Optional[np.ndarray]]
PinFacingRow = List[object]
SymbolFacingResult = Dict[str, List[PinFacingRow]]

_OK_RESULT: ConversionResult = (True, "OK", 0)
_POSITIVE_X_DIRECTION = "+X DIRECTION"
_NEGATIVE_X_DIRECTION = "-X DIRECTION"
_POSITIVE_Y_DIRECTION = "+Y DIRECTION"
_NEGATIVE_Y_DIRECTION = "-Y DIRECTION"


def ltspice_resolve_symbol_pose(
    symbol_json_filepath: str,
    convert_settings: Mapping[str, object],
) -> ConversionResult:
    if not isinstance(convert_settings, Mapping):
        return False, "INVALID_CONVERT_SETTINGS", 0
    try:
        symbol_json_path = Path(os.fspath(symbol_json_filepath))
    except TypeError:
        return False, "INVALID_SYMBOL_JSON_PATH", 0
    try:
        symbol_json = json.loads(symbol_json_path.read_text(encoding="utf-8"))
    except OSError:
        return False, "SYMBOL_JSON_READ_ERROR", 0
    except json.JSONDecodeError as error:
        return False, "SYMBOL_JSON_PARSE_ERROR", error.lineno
    if not isinstance(symbol_json, dict):
        return False, "SYMBOL_JSON_PARSE_ERROR", 0
    temporary_asc_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".asc",
            prefix=f"{symbol_json_path.stem}_",
            dir=symbol_json_path.parent,
            delete=False,
        ) as temporary_asc_file:
            temporary_asc_path = Path(temporary_asc_file.name)
            for instance_name, symbol_entry in symbol_json.items():
                if not isinstance(symbol_entry, dict):
                    return False, "SYMBOL_JSON_PARSE_ERROR", 0
                if "SYMBOL" not in symbol_entry or "X" not in symbol_entry or "Y" not in symbol_entry or "ORIENTATION" not in symbol_entry:
                    return False, "SYMBOL_JSON_PARSE_ERROR", 0
                temporary_asc_file.write(
                    f"SYMBOL {symbol_entry['SYMBOL']} {int(symbol_entry['X'])} {int(symbol_entry['Y'])} {symbol_entry['ORIENTATION']}\n"
                )
                temporary_asc_file.write(f"SYMATTR InstName {instance_name}\n")
                if "VALUE" in symbol_entry and str(symbol_entry["VALUE"]).strip() != "":
                    temporary_asc_file.write(f"SYMATTR Value {symbol_entry['VALUE']}\n")
        try:
            resolved_symbol_info = get_ltspice_asc_symbol_info(str(temporary_asc_path), convert_settings)
        except ValueError as error:
            line_match = re.search(r"Line (?P<line>\d+)", str(error))
            return False, "SYMBOL_POSE_RESOLUTION_ERROR", int(line_match.group("line")) if line_match is not None else 0
        for instance_name, resolved_entry in resolved_symbol_info.items():
            if instance_name not in symbol_json or not isinstance(symbol_json[instance_name], dict):
                return False, "SYMBOL_JSON_PARSE_ERROR", 0
            symbol_json[instance_name]["RECTANGLE"] = resolved_entry["RECTANGLE"]
            symbol_json[instance_name]["PINS"] = resolved_entry["PINS"]
        try:
            symbol_json_path.write_text(json.dumps(symbol_json, indent=2) + "\n", encoding="utf-8")
        except OSError:
            return False, "WRITE_ERROR", 0
    finally:
        if temporary_asc_path is not None:
            try:
                temporary_asc_path.unlink()
            except OSError:
                pass
    return _OK_RESULT


def ltspice_check_symbol_pose(
    symbol_json_filepath: str,
    convert_settings: Mapping[str, object],
) -> SymbolPoseCheckResult:
    if not isinstance(convert_settings, Mapping):
        raise ValueError("convert_settings must be a mapping")
    symbol_json = _read_symbol_json_mapping(symbol_json_filepath)
    minimum_dist = _resolve_minimum_dist(convert_settings)
    buffered_symbol_lines = [
        rectangle_points_to_lines(_buffer_rectangle_points(symbol_entry, minimum_dist))
        for symbol_entry in symbol_json.values()
    ]
    intersections: List[List[int]] = []
    for wire_index in range(len(buffered_symbol_lines)):
        for obstacle_index in range(wire_index + 1, len(buffered_symbol_lines)):
            intersection_result = are_wires_intersecting_obstacles_detailed(
                buffered_symbol_lines[wire_index],
                buffered_symbol_lines[obstacle_index],
            )
            if intersection_result[0]:
                intersections.append([wire_index, obstacle_index])
    if not intersections:
        return False, None
    return True, np.array(intersections, dtype=int)


def ltspice_symbol_facing(
    symbol_pose_filepath: str,
    convert_settings: Mapping[str, object],
) -> SymbolFacingResult:
    if not isinstance(convert_settings, Mapping):
        raise ValueError("convert_settings must be a mapping")
    symbol_json = _read_symbol_json_mapping(symbol_pose_filepath)
    facing_result: SymbolFacingResult = {}
    for instance_name, symbol_entry in symbol_json.items():
        facing_result[instance_name] = _resolve_symbol_entry_pin_facings(instance_name, symbol_entry)
    return facing_result


def _read_symbol_json_mapping(symbol_json_filepath: str) -> dict[str, object]:
    try:
        symbol_json_path = Path(os.fspath(symbol_json_filepath))
    except TypeError as error:
        raise ValueError("symbol_json_filepath must be path-like") from error
    try:
        symbol_json = json.loads(symbol_json_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError("Unable to read symbol JSON file") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Unable to parse symbol JSON file! Line {error.lineno}") from error
    if not isinstance(symbol_json, dict):
        raise ValueError("symbol JSON root must be a dictionary")
    return symbol_json


def _resolve_minimum_dist(convert_settings: Mapping[str, object]) -> int:
    raw_minimum_dist = convert_settings.get("minimum_dist", 0)
    try:
        minimum_dist = int(raw_minimum_dist)
    except (TypeError, ValueError) as error:
        raise ValueError("minimum_dist must be an integer") from error
    if minimum_dist < 0:
        raise ValueError("minimum_dist must be non-negative")
    return minimum_dist


def _buffer_rectangle_points(symbol_entry: object, minimum_dist: int) -> np.ndarray:
    if not isinstance(symbol_entry, dict) or "RECTANGLE" not in symbol_entry:
        raise ValueError("symbol entry must contain RECTANGLE")
    try:
        rectangle_points = np.asarray(symbol_entry["RECTANGLE"], dtype=int)
    except (TypeError, ValueError) as error:
        raise ValueError("RECTANGLE must contain integer coordinates") from error
    if rectangle_points.shape != (2, 2):
        raise ValueError("RECTANGLE must contain exactly two points")
    minimum_x = min(int(rectangle_points[0, 0]), int(rectangle_points[1, 0])) - minimum_dist
    minimum_y = min(int(rectangle_points[0, 1]), int(rectangle_points[1, 1])) - minimum_dist
    maximum_x = max(int(rectangle_points[0, 0]), int(rectangle_points[1, 0])) + minimum_dist
    maximum_y = max(int(rectangle_points[0, 1]), int(rectangle_points[1, 1])) + minimum_dist
    return np.array([[minimum_x, minimum_y], [maximum_x, maximum_y]], dtype=int)


def _resolve_symbol_entry_pin_facings(instance_name: str, symbol_entry: object) -> List[PinFacingRow]:
    if not isinstance(symbol_entry, dict):
        raise ValueError(f"symbol entry '{instance_name}' must be a dictionary")
    minimum_x, minimum_y, maximum_x, maximum_y = _parse_symbol_rectangle_bounds(instance_name, symbol_entry.get("RECTANGLE"))
    pin_rows = _parse_symbol_pins_for_facing(instance_name, symbol_entry.get("PINS"))
    center_x = (minimum_x + maximum_x) / 2.0
    center_y = (minimum_y + maximum_y) / 2.0
    return [
        [pin_x, pin_y, pin_name, spice_order, _resolve_pin_facing(pin_x, pin_y, minimum_x, minimum_y, maximum_x, maximum_y, center_x, center_y)]
        for pin_x, pin_y, pin_name, spice_order in pin_rows
    ]


def _parse_symbol_rectangle_bounds(instance_name: str, raw_rectangle: object) -> Tuple[int, int, int, int]:
    try:
        rectangle_points = np.asarray(raw_rectangle, dtype=int)
    except (TypeError, ValueError) as error:
        raise ValueError(f"symbol entry '{instance_name}' has an invalid RECTANGLE") from error
    if rectangle_points.shape != (2, 2):
        raise ValueError(f"symbol entry '{instance_name}' must contain RECTANGLE with exactly two points")
    minimum_x = min(int(rectangle_points[0, 0]), int(rectangle_points[1, 0]))
    minimum_y = min(int(rectangle_points[0, 1]), int(rectangle_points[1, 1]))
    maximum_x = max(int(rectangle_points[0, 0]), int(rectangle_points[1, 0]))
    maximum_y = max(int(rectangle_points[0, 1]), int(rectangle_points[1, 1]))
    return minimum_x, minimum_y, maximum_x, maximum_y


def _parse_symbol_pins_for_facing(instance_name: str, raw_pins: object) -> List[Tuple[int, int, str, int]]:
    if not isinstance(raw_pins, list):
        raise ValueError(f"symbol entry '{instance_name}' must contain PINS as a list")
    parsed_pins: List[Tuple[int, int, str, int]] = []
    for pin_index, raw_pin in enumerate(raw_pins):
        if not isinstance(raw_pin, list) or len(raw_pin) != 4:
            raise ValueError(f"symbol entry '{instance_name}' contains invalid pin row at index {pin_index}")
        try:
            pin_x = int(raw_pin[0])
            pin_y = int(raw_pin[1])
            pin_name = str(raw_pin[2])
            spice_order = int(raw_pin[3])
        except (TypeError, ValueError) as error:
            raise ValueError(f"symbol entry '{instance_name}' contains invalid pin row at index {pin_index}") from error
        parsed_pins.append((pin_x, pin_y, pin_name, spice_order))
    return parsed_pins


def _resolve_pin_facing(
    pin_x: int,
    pin_y: int,
    minimum_x: int,
    minimum_y: int,
    maximum_x: int,
    maximum_y: int,
    center_x: float,
    center_y: float,
) -> str:
    on_left_edge = pin_x == minimum_x
    on_right_edge = pin_x == maximum_x
    on_top_edge = pin_y == minimum_y
    on_bottom_edge = pin_y == maximum_y
    if (on_left_edge or on_right_edge) and not (on_top_edge or on_bottom_edge):
        return _NEGATIVE_X_DIRECTION if on_left_edge else _POSITIVE_X_DIRECTION
    if (on_top_edge or on_bottom_edge) and not (on_left_edge or on_right_edge):
        return _NEGATIVE_Y_DIRECTION if on_top_edge else _POSITIVE_Y_DIRECTION
    delta_x = float(pin_x) - center_x
    delta_y = float(pin_y) - center_y
    absolute_delta_x = abs(delta_x)
    absolute_delta_y = abs(delta_y)
    if absolute_delta_x > absolute_delta_y:
        return _NEGATIVE_X_DIRECTION if delta_x < 0 else _POSITIVE_X_DIRECTION
    if absolute_delta_y > absolute_delta_x:
        return _NEGATIVE_Y_DIRECTION if delta_y < 0 else _POSITIVE_Y_DIRECTION
    rectangle_width = maximum_x - minimum_x
    rectangle_height = maximum_y - minimum_y
    if rectangle_width > rectangle_height:
        return _NEGATIVE_X_DIRECTION if delta_x < 0 else _POSITIVE_X_DIRECTION
    if rectangle_height > rectangle_width:
        return _NEGATIVE_Y_DIRECTION if delta_y < 0 else _POSITIVE_Y_DIRECTION
    if on_left_edge or on_right_edge:
        return _NEGATIVE_X_DIRECTION if delta_x < 0 else _POSITIVE_X_DIRECTION
    return _NEGATIVE_Y_DIRECTION if delta_y < 0 else _POSITIVE_Y_DIRECTION
