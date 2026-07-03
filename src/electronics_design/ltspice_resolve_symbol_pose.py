"""Resolve LTspice symbol rectangles and pins inside symbol JSON files."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
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

_OK_RESULT: ConversionResult = (True, "OK", 0)


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
