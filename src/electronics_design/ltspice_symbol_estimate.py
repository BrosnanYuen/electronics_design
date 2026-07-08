"""Estimate supporting LTspice symbol placement around one fixed core symbol."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import tempfile
from typing import Dict
from typing import Mapping
from typing import Optional
from typing import Sequence
from typing import Tuple

from .ltspice_resolve_symbol_pose import ltspice_resolve_symbol_pose
from .ltspice_resolve_symbol_pose import ltspice_symbol_facing

Point = Tuple[int, int]
Rectangle = Tuple[int, int, int, int]
FacingRow = Tuple[int, int, str, int, str]

_VALID_ORIENTATIONS = ("R0", "R90", "R180", "R270")
_POSE_KEYS = {"X", "Y", "ORIENTATION", "RECTANGLE", "PINS"}
_POSITIVE_X_DIRECTION = "+X DIRECTION"
_NEGATIVE_X_DIRECTION = "-X DIRECTION"
_POSITIVE_Y_DIRECTION = "+Y DIRECTION"
_NEGATIVE_Y_DIRECTION = "-Y DIRECTION"
_OPPOSITE_DIRECTION = {
    _POSITIVE_X_DIRECTION: _NEGATIVE_X_DIRECTION,
    _NEGATIVE_X_DIRECTION: _POSITIVE_X_DIRECTION,
    _POSITIVE_Y_DIRECTION: _NEGATIVE_Y_DIRECTION,
    _NEGATIVE_Y_DIRECTION: _POSITIVE_Y_DIRECTION,
}


def ltspice_symbol_estimate(
    symbol_pose_filepath: str,
    core_symbol_name: str,
    core_symbol_pin_id: int,
    supporting_symbol_name: str,
    supporting_symbol_pin_id: int,
    convert_settings: Mapping[str, object],
) -> Dict[str, Dict[str, object]]:
    """Return one supporting symbol pose estimated from one fixed core symbol pin."""

    if not isinstance(convert_settings, Mapping):
        raise ValueError("convert_settings must be a mapping")
    minimum_dist = _resolve_non_negative_integer(convert_settings.get("minimum_dist", 0))
    if minimum_dist is None:
        raise ValueError("minimum_dist must be a non-negative integer")
    symbol_json = _read_symbol_json_mapping(symbol_pose_filepath)
    if core_symbol_name not in symbol_json:
        raise ValueError(f"Unknown core symbol '{core_symbol_name}'")
    if supporting_symbol_name not in symbol_json:
        raise ValueError(f"Unknown supporting symbol '{supporting_symbol_name}'")
    core_entry = symbol_json[core_symbol_name]
    supporting_entry = symbol_json[supporting_symbol_name]
    if "SYMBOL" not in supporting_entry:
        raise ValueError(f"Supporting symbol '{supporting_symbol_name}' is missing SYMBOL")
    core_pin_facing = _pin_facing_for_entry(
        symbol_pose_filepath,
        core_symbol_name,
        core_symbol_pin_id,
        convert_settings,
    )
    core_rectangle = _parse_rectangle(core_entry.get("RECTANGLE"), core_symbol_name)
    opposite_support_direction = _OPPOSITE_DIRECTION[core_pin_facing[4]]
    best_candidate: Optional[Tuple[float, Dict[str, object]]] = None
    for orientation_index, orientation in enumerate(_VALID_ORIENTATIONS):
        candidate_result = _resolve_support_candidate(
            supporting_entry,
            supporting_symbol_name,
            supporting_symbol_pin_id,
            orientation,
            convert_settings,
        )
        if candidate_result is None:
            continue
        resolved_support_entry, support_pin_facing = candidate_result
        if support_pin_facing[4] != opposite_support_direction:
            continue
        candidate_origin = _estimate_support_origin(
            core_rectangle,
            core_pin_facing,
            resolved_support_entry,
            support_pin_facing,
            minimum_dist,
        )
        candidate_entry = _translate_symbol_entry(
            supporting_entry,
            resolved_support_entry,
            candidate_origin,
            orientation,
        )
        candidate_rectangle = _parse_rectangle(candidate_entry["RECTANGLE"], supporting_symbol_name)
        if _rectangles_overlap(core_rectangle, candidate_rectangle):
            continue
        if not _satisfies_minimum_distance(core_rectangle, candidate_rectangle, core_pin_facing[4], minimum_dist):
            continue
        candidate_score = _candidate_score(core_rectangle, candidate_rectangle) + (orientation_index * 0.001)
        if best_candidate is None or candidate_score < best_candidate[0]:
            best_candidate = (candidate_score, candidate_entry)
    if best_candidate is None:
        raise ValueError(
            f"Unable to estimate a valid pose for supporting symbol '{supporting_symbol_name}' from core symbol '{core_symbol_name}'"
        )
    return {supporting_symbol_name: best_candidate[1]}


def _read_symbol_json_mapping(symbol_pose_filepath: str) -> Dict[str, Dict[str, object]]:
    try:
        symbol_pose_path = Path(os.fspath(symbol_pose_filepath))
    except TypeError as error:
        raise ValueError("symbol_pose_filepath must be path-like") from error
    try:
        loaded_json = json.loads(symbol_pose_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError("Unable to read symbol pose JSON file") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Unable to parse symbol pose JSON file! Line {error.lineno}") from error
    if not isinstance(loaded_json, dict):
        raise ValueError("symbol pose JSON root must be a dictionary")
    normalized_mapping: Dict[str, Dict[str, object]] = {}
    for instance_name, symbol_entry in loaded_json.items():
        if not isinstance(symbol_entry, dict):
            raise ValueError(f"Symbol entry '{instance_name}' must be a dictionary")
        normalized_mapping[str(instance_name)] = dict(symbol_entry)
    return normalized_mapping


def _resolve_non_negative_integer(value: object) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        integer_value = int(value)
    except (TypeError, ValueError):
        return None
    if integer_value < 0:
        return None
    return integer_value


def _pin_facing_for_entry(
    symbol_pose_filepath: str,
    instance_name: str,
    spice_order: int,
    convert_settings: Mapping[str, object],
) -> FacingRow:
    facing_map = ltspice_symbol_facing(symbol_pose_filepath, convert_settings)
    if instance_name not in facing_map:
        raise ValueError(f"Unknown symbol '{instance_name}' in symbol pose file")
    return _find_pin_facing_row(facing_map[instance_name], instance_name, spice_order)


def _find_pin_facing_row(
    facing_rows: Sequence[Sequence[object]],
    instance_name: str,
    spice_order: int,
) -> FacingRow:
    for raw_row in facing_rows:
        if len(raw_row) != 5:
            continue
        try:
            pin_x = int(raw_row[0])
            pin_y = int(raw_row[1])
            pin_name = str(raw_row[2])
            pin_order = int(raw_row[3])
            pin_direction = str(raw_row[4])
        except (TypeError, ValueError):
            continue
        if pin_order == spice_order:
            return pin_x, pin_y, pin_name, pin_order, pin_direction
    raise ValueError(f"Symbol '{instance_name}' does not contain pin id {spice_order}")


def _resolve_support_candidate(
    supporting_entry: Mapping[str, object],
    supporting_symbol_name: str,
    supporting_symbol_pin_id: int,
    orientation: str,
    convert_settings: Mapping[str, object],
) -> Optional[Tuple[Dict[str, object], FacingRow]]:
    working_entry = {
        key: value
        for key, value in supporting_entry.items()
        if key not in {"RECTANGLE", "PINS"}
    }
    working_entry["X"] = 0
    working_entry["Y"] = 0
    working_entry["ORIENTATION"] = orientation
    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_json_path = Path(temporary_directory) / "support_symbol.json"
        temporary_json_path.write_text(
            json.dumps({supporting_symbol_name: working_entry}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        resolve_result = ltspice_resolve_symbol_pose(str(temporary_json_path), convert_settings)
        if not resolve_result[0]:
            return None
        resolved_payload = json.loads(temporary_json_path.read_text(encoding="utf-8"))
        facing_map = ltspice_symbol_facing(str(temporary_json_path), convert_settings)
    if supporting_symbol_name not in resolved_payload or supporting_symbol_name not in facing_map:
        return None
    return (
        dict(resolved_payload[supporting_symbol_name]),
        _find_pin_facing_row(facing_map[supporting_symbol_name], supporting_symbol_name, supporting_symbol_pin_id),
    )


def _estimate_support_origin(
    core_rectangle: Rectangle,
    core_pin_facing: FacingRow,
    resolved_support_entry: Mapping[str, object],
    support_pin_facing: FacingRow,
    minimum_dist: int,
) -> Point:
    support_rectangle = _parse_rectangle(resolved_support_entry.get("RECTANGLE"), str(resolved_support_entry.get("SYMBOL", "support")))
    direction = core_pin_facing[4]
    if direction == _POSITIVE_X_DIRECTION:
        return (
            (core_rectangle[2] + minimum_dist) - support_rectangle[0],
            core_pin_facing[1] - support_pin_facing[1],
        )
    if direction == _NEGATIVE_X_DIRECTION:
        return (
            (core_rectangle[0] - minimum_dist) - support_rectangle[2],
            core_pin_facing[1] - support_pin_facing[1],
        )
    if direction == _POSITIVE_Y_DIRECTION:
        return (
            core_pin_facing[0] - support_pin_facing[0],
            (core_rectangle[3] + minimum_dist) - support_rectangle[1],
        )
    return (
        core_pin_facing[0] - support_pin_facing[0],
        (core_rectangle[1] - minimum_dist) - support_rectangle[3],
    )


def _translate_symbol_entry(
    original_entry: Mapping[str, object],
    resolved_entry: Mapping[str, object],
    origin: Point,
    orientation: str,
) -> Dict[str, object]:
    translated_entry = {
        key: value
        for key, value in original_entry.items()
        if key not in _POSE_KEYS
    }
    translated_entry["SYMBOL"] = str(original_entry.get("SYMBOL", resolved_entry.get("SYMBOL", "")))
    translated_entry["X"] = int(origin[0])
    translated_entry["Y"] = int(origin[1])
    translated_entry["ORIENTATION"] = orientation
    translated_entry["RECTANGLE"] = _translate_rectangle_points(resolved_entry.get("RECTANGLE"), origin)
    translated_entry["PINS"] = _translate_pin_rows(resolved_entry.get("PINS"), origin)
    return translated_entry


def _translate_rectangle_points(raw_rectangle: object, origin: Point) -> list[list[int]]:
    first_x, first_y, second_x, second_y = _parse_rectangle(raw_rectangle, "support")
    return [
        [first_x + origin[0], first_y + origin[1]],
        [second_x + origin[0], second_y + origin[1]],
    ]


def _translate_pin_rows(raw_pins: object, origin: Point) -> list[list[object]]:
    translated_pins: list[list[object]] = []
    if not isinstance(raw_pins, list):
        raise ValueError("Resolved support symbol is missing PINS")
    for raw_pin in raw_pins:
        if not isinstance(raw_pin, list) or len(raw_pin) != 4:
            raise ValueError("Resolved support symbol contains invalid PINS")
        translated_pins.append(
            [
                int(raw_pin[0]) + origin[0],
                int(raw_pin[1]) + origin[1],
                str(raw_pin[2]),
                int(raw_pin[3]),
            ]
        )
    return translated_pins


def _parse_rectangle(raw_rectangle: object, instance_name: str) -> Rectangle:
    try:
        first_point, second_point = raw_rectangle
        first_x = int(first_point[0])
        first_y = int(first_point[1])
        second_x = int(second_point[0])
        second_y = int(second_point[1])
    except (TypeError, ValueError, IndexError) as error:
        raise ValueError(f"Symbol '{instance_name}' contains an invalid RECTANGLE") from error
    return (
        min(first_x, second_x),
        min(first_y, second_y),
        max(first_x, second_x),
        max(first_y, second_y),
    )


def _rectangles_overlap(first_rectangle: Rectangle, second_rectangle: Rectangle) -> bool:
    overlap_left = max(first_rectangle[0], second_rectangle[0])
    overlap_top = max(first_rectangle[1], second_rectangle[1])
    overlap_right = min(first_rectangle[2], second_rectangle[2])
    overlap_bottom = min(first_rectangle[3], second_rectangle[3])
    return overlap_left < overlap_right and overlap_top < overlap_bottom


def _satisfies_minimum_distance(
    core_rectangle: Rectangle,
    support_rectangle: Rectangle,
    core_direction: str,
    minimum_dist: int,
) -> bool:
    if core_direction == _POSITIVE_X_DIRECTION:
        return (support_rectangle[0] - core_rectangle[2]) >= minimum_dist
    if core_direction == _NEGATIVE_X_DIRECTION:
        return (core_rectangle[0] - support_rectangle[2]) >= minimum_dist
    if core_direction == _POSITIVE_Y_DIRECTION:
        return (support_rectangle[1] - core_rectangle[3]) >= minimum_dist
    return (core_rectangle[1] - support_rectangle[3]) >= minimum_dist


def _candidate_score(core_rectangle: Rectangle, support_rectangle: Rectangle) -> float:
    core_center_x = (core_rectangle[0] + core_rectangle[2]) / 2.0
    core_center_y = (core_rectangle[1] + core_rectangle[3]) / 2.0
    support_center_x = (support_rectangle[0] + support_rectangle[2]) / 2.0
    support_center_y = (support_rectangle[1] + support_rectangle[3]) / 2.0
    return math.hypot(support_center_x - core_center_x, support_center_y - core_center_y)
