"""LTspice ASY symbol validation, size extraction, and pin parsing APIs."""

from __future__ import annotations

from numbers import Integral
import os
import re
from typing import Any
from typing import List
from typing import Sequence
from typing import Tuple

import numpy as np

ValidationResult = Tuple[bool, str]
ReadLinesResult = Tuple[bool, List[str], str]
PinInfo = Tuple[int, int, str, int]
PinParseResult = Tuple[bool, List[PinInfo], int]

_VALID_ASY_KEYWORDS = {
    "VERSION",
    "SYMBOLTYPE",
    "LINE",
    "RECTANGLE",
    "CIRCLE",
    "ARC",
    "WINDOW",
    "SYMATTR",
    "TEXT",
    "PIN",
    "PINATTR",
}
_VALID_SYMBOL_TYPES = {"CELL", "BLOCK"}
_VALID_DRAWING_WIDTHS = {"NORMAL", "WIDE"}
_VALID_TEXT_JUSTIFICATIONS = {
    "LEFT",
    "CENTER",
    "RIGHT",
    "TOP",
    "BOTTOM",
    "VLEFT",
    "VCENTER",
    "VRIGHT",
    "VTOP",
    "VBOTTOM",
    "INVISIBLE",
}
_VALID_PIN_JUSTIFICATIONS = {
    "NONE",
    "LEFT",
    "RIGHT",
    "TOP",
    "BOTTOM",
    "VLEFT",
    "VRIGHT",
    "VTOP",
    "VBOTTOM",
}
_UTF16_LE_BOM = b"\xff\xfe"
_UTF16_BE_BOM = b"\xfe\xff"


def is_valid_ltspice_asy(filepath: str) -> ValidationResult:
    """Return whether one LTspice .asy file is structurally valid."""

    read_result = _read_text_file_lines(filepath)
    if not read_result[0]:
        return False, read_result[2]
    validation_result = _validate_asy_lines(read_result[1])
    if not validation_result[0]:
        return False, _format_line_message("LTspice ASY file is invalid!", validation_result[1])
    return True, ""


def get_ltspice_asy_size(filepath: str) -> np.ndarray:
    """Return the drawable bounding rectangle for one LTspice .asy file."""

    validation_result = is_valid_ltspice_asy(filepath)
    if not validation_result[0]:
        raise ValueError(validation_result[1])
    read_result = _read_text_file_lines(filepath)
    if not read_result[0]:
        raise ValueError(read_result[2])
    bounds = _extract_asy_shape_bounds(read_result[1])
    if bounds is None:
        raise ValueError("LTspice ASY file does not contain any drawable geometry!")
    return np.array([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], dtype=int)


def rectangle_points_to_lines(points: np.ndarray) -> np.ndarray:
    """Return the four axis-aligned rectangle edges for two opposite corner points."""

    normalized_points = _normalize_rectangle_points(points)
    x1 = min(normalized_points[0][0], normalized_points[1][0])
    y1 = min(normalized_points[0][1], normalized_points[1][1])
    x2 = max(normalized_points[0][0], normalized_points[1][0])
    y2 = max(normalized_points[0][1], normalized_points[1][1])
    return np.array(
        [
            [x1, y1, x2, y1],
            [x2, y1, x2, y2],
            [x1, y1, x1, y2],
            [x1, y2, x2, y2],
        ],
        dtype=int,
    )


def get_ltspice_asy_pins(filepath: str) -> List[List[Any]]:
    """Return LTspice ASY pins as ``[x, y, pin_name, spice_order]`` rows."""

    validation_result = is_valid_ltspice_asy(filepath)
    if not validation_result[0]:
        raise ValueError(validation_result[1])
    read_result = _read_text_file_lines(filepath)
    if not read_result[0]:
        raise ValueError(read_result[2])
    parse_result = _extract_asy_pins(read_result[1])
    if not parse_result[0]:
        raise ValueError(_format_line_message("LTspice ASY pin information is incomplete!", parse_result[2]))
    return [[pin_x, pin_y, pin_name, spice_order] for pin_x, pin_y, pin_name, spice_order in parse_result[1]]


def _read_text_file_lines(filepath: str) -> ReadLinesResult:
    coerced_path_result = _coerce_path(filepath)
    if not coerced_path_result[0]:
        return False, [], "File not found!"
    path_string = coerced_path_result[1]
    if not os.path.exists(path_string):
        return False, [], "File not found!"
    if not os.access(path_string, os.R_OK):
        return False, [], "No permission to read file!"
    try:
        with open(path_string, "rb") as file_handle:
            file_bytes = file_handle.read()
    except PermissionError:
        return False, [], "No permission to read file!"
    file_text = _decode_ltspice_text(file_bytes)
    return True, file_text.splitlines(), ""


def _decode_ltspice_text(file_bytes: bytes) -> str:
    if file_bytes.startswith(_UTF16_LE_BOM):
        return file_bytes.decode("utf-16le")
    if file_bytes.startswith(_UTF16_BE_BOM):
        return file_bytes.decode("utf-16be")
    if b"\x00" in file_bytes:
        try:
            return file_bytes.decode("utf-16le")
        except UnicodeDecodeError:
            return file_bytes.decode("utf-16be")
    try:
        return file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return file_bytes.decode("latin-1")


def _coerce_path(filepath: str) -> Tuple[bool, str]:
    try:
        path_string = os.fspath(filepath)
    except TypeError:
        return False, ""
    return True, path_string


def _validate_asy_lines(lines: Sequence[str]) -> Tuple[bool, int]:
    first_structural_entry = None
    second_structural_entry = None
    last_pin_line_number = 0
    for line_number, raw_line in enumerate(lines, start=1):
        if raw_line.strip() == "":
            continue
        classification_result = _classify_asy_line(raw_line)
        if not classification_result[0]:
            return False, line_number
        keyword = classification_result[1]
        if first_structural_entry is None:
            first_structural_entry = (line_number, keyword)
        elif second_structural_entry is None:
            second_structural_entry = (line_number, keyword)
        record_result = _validate_asy_record_tokens(raw_line)
        if not record_result[0]:
            return False, line_number
        if keyword == "PIN":
            last_pin_line_number = line_number
        elif keyword == "PINATTR":
            if last_pin_line_number == 0:
                return False, line_number
        else:
            last_pin_line_number = 0
    if first_structural_entry is None:
        return False, 1
    if first_structural_entry[1] != "VERSION":
        return False, first_structural_entry[0]
    if second_structural_entry is None:
        return False, first_structural_entry[0]
    if second_structural_entry[1] != "SYMBOLTYPE":
        return False, second_structural_entry[0]
    return True, 0


def _classify_asy_line(raw_line: str) -> Tuple[bool, str]:
    stripped_line = raw_line.strip()
    if stripped_line == "":
        return True, "blank"
    keyword = stripped_line.split(maxsplit=1)[0]
    normalized_keyword = keyword.upper()
    if normalized_keyword not in _VALID_ASY_KEYWORDS:
        return False, "invalid"
    return True, normalized_keyword


def _validate_asy_record_tokens(raw_line: str) -> Tuple[bool, str]:
    classification_result = _classify_asy_line(raw_line)
    if not classification_result[0]:
        return False, "invalid_keyword"
    keyword = classification_result[1]
    if keyword == "blank":
        return True, ""
    tokens = raw_line.split()
    if keyword == "VERSION":
        if len(tokens) != 2 or not _is_integer_token(tokens[1]):
            return False, "invalid_version"
        return True, ""
    if keyword == "SYMBOLTYPE":
        if len(tokens) != 2 or tokens[1].upper() not in _VALID_SYMBOL_TYPES:
            return False, "invalid_symboltype"
        return True, ""
    if keyword in {"LINE", "RECTANGLE", "CIRCLE"}:
        if len(tokens) not in {6, 7}:
            return False, "invalid_shape_token_count"
        if tokens[1].upper() not in _VALID_DRAWING_WIDTHS:
            return False, "invalid_shape_width"
        if not all(_is_integer_token(token) for token in tokens[2:6]):
            return False, "invalid_shape_coordinate"
        if len(tokens) == 7 and not _is_integer_token(tokens[6]):
            return False, "invalid_shape_style"
        return True, ""
    if keyword == "ARC":
        if len(tokens) not in {10, 11}:
            return False, "invalid_arc_token_count"
        if tokens[1].upper() not in _VALID_DRAWING_WIDTHS:
            return False, "invalid_arc_width"
        if not all(_is_integer_token(token) for token in tokens[2:10]):
            return False, "invalid_arc_coordinate"
        if len(tokens) == 11 and not _is_integer_token(tokens[10]):
            return False, "invalid_arc_style"
        return True, ""
    if keyword == "WINDOW":
        if len(tokens) != 6:
            return False, "invalid_window_token_count"
        if not all(_is_integer_token(token) for token in tokens[1:4]):
            return False, "invalid_window_coordinate"
        if tokens[4].upper() not in _VALID_TEXT_JUSTIFICATIONS:
            return False, "invalid_window_justification"
        if not _is_integer_token(tokens[5]):
            return False, "invalid_window_font"
        return True, ""
    if keyword == "SYMATTR":
        if len(tokens) < 3:
            return False, "invalid_symattr"
        return True, ""
    if keyword == "TEXT":
        if len(tokens) < 6:
            return False, "invalid_text_token_count"
        if not _is_integer_token(tokens[1]) or not _is_integer_token(tokens[2]):
            return False, "invalid_text_coordinate"
        if tokens[3].upper() not in _VALID_TEXT_JUSTIFICATIONS:
            return False, "invalid_text_justification"
        if not _is_integer_token(tokens[4]):
            return False, "invalid_text_font"
        return True, ""
    if keyword == "PIN":
        if len(tokens) != 5:
            return False, "invalid_pin_token_count"
        if not _is_integer_token(tokens[1]) or not _is_integer_token(tokens[2]):
            return False, "invalid_pin_coordinate"
        if tokens[3].upper() not in _VALID_PIN_JUSTIFICATIONS:
            return False, "invalid_pin_justification"
        if not _is_integer_token(tokens[4]):
            return False, "invalid_pin_offset"
        return True, ""
    if keyword == "PINATTR":
        if len(tokens) < 3:
            return False, "invalid_pinattr"
        if tokens[1].upper() == "SPICEORDER" and not _is_integer_token(tokens[2]):
            return False, "invalid_spiceorder"
        return True, ""
    return False, "unhandled_keyword"


def _extract_asy_shape_bounds(lines: Sequence[str]) -> Tuple[int, int, int, int] | None:
    minimum_x = None
    minimum_y = None
    maximum_x = None
    maximum_y = None
    for raw_line in lines:
        if raw_line.strip() == "":
            continue
        classification_result = _classify_asy_line(raw_line)
        if not classification_result[0]:
            continue
        keyword = classification_result[1]
        coordinate_values = _shape_coordinate_values(raw_line, keyword)
        if coordinate_values is None:
            continue
        x_values = coordinate_values[0::2]
        y_values = coordinate_values[1::2]
        shape_minimum_x = min(x_values)
        shape_minimum_y = min(y_values)
        shape_maximum_x = max(x_values)
        shape_maximum_y = max(y_values)
        minimum_x = shape_minimum_x if minimum_x is None else min(minimum_x, shape_minimum_x)
        minimum_y = shape_minimum_y if minimum_y is None else min(minimum_y, shape_minimum_y)
        maximum_x = shape_maximum_x if maximum_x is None else max(maximum_x, shape_maximum_x)
        maximum_y = shape_maximum_y if maximum_y is None else max(maximum_y, shape_maximum_y)
    if minimum_x is None or minimum_y is None or maximum_x is None or maximum_y is None:
        return None
    return minimum_x, minimum_y, maximum_x, maximum_y


def _extract_asy_pins(lines: Sequence[str]) -> PinParseResult:
    pins: List[PinInfo] = []
    current_pin_x = 0
    current_pin_y = 0
    current_pin_name = ""
    current_pin_order = None
    current_pin_line_number = 0
    for line_number, raw_line in enumerate(lines, start=1):
        if raw_line.strip() == "":
            continue
        classification_result = _classify_asy_line(raw_line)
        if not classification_result[0]:
            continue
        keyword = classification_result[1]
        if keyword == "PIN":
            finalize_result = _finalize_asy_pin(
                pins,
                current_pin_x,
                current_pin_y,
                current_pin_name,
                current_pin_order,
                current_pin_line_number,
            )
            if not finalize_result[0]:
                return False, [], finalize_result[1]
            pin_tokens = raw_line.split()
            current_pin_x = int(pin_tokens[1])
            current_pin_y = int(pin_tokens[2])
            current_pin_name = ""
            current_pin_order = None
            current_pin_line_number = line_number
            continue
        if keyword == "PINATTR" and current_pin_line_number != 0:
            attribute_tokens = raw_line.split(maxsplit=2)
            attribute_name = attribute_tokens[1].upper()
            attribute_value = attribute_tokens[2]
            if attribute_name == "PINNAME":
                current_pin_name = attribute_value
            elif attribute_name == "SPICEORDER":
                current_pin_order = int(attribute_value)
            continue
        finalize_result = _finalize_asy_pin(
            pins,
            current_pin_x,
            current_pin_y,
            current_pin_name,
            current_pin_order,
            current_pin_line_number,
        )
        if not finalize_result[0]:
            return False, [], finalize_result[1]
        current_pin_line_number = 0
    finalize_result = _finalize_asy_pin(
        pins,
        current_pin_x,
        current_pin_y,
        current_pin_name,
        current_pin_order,
        current_pin_line_number,
    )
    if not finalize_result[0]:
        return False, [], finalize_result[1]
    pins.sort(key=lambda pin: pin[3])
    return True, pins, 0


def _finalize_asy_pin(
    pins: List[PinInfo],
    pin_x: int,
    pin_y: int,
    pin_name: str,
    pin_order: int | None,
    pin_line_number: int,
) -> Tuple[bool, int]:
    if pin_line_number == 0:
        return True, 0
    if pin_order is None:
        return False, pin_line_number
    pins.append((pin_x, pin_y, pin_name, pin_order))
    return True, 0


def _shape_coordinate_values(raw_line: str, keyword: str) -> Tuple[int, ...] | None:
    tokens = raw_line.split()
    if keyword in {"LINE", "RECTANGLE", "CIRCLE"}:
        return tuple(int(token) for token in tokens[2:6])
    if keyword == "ARC":
        return tuple(int(token) for token in tokens[2:10])
    return None


def _is_integer_token(token: str) -> bool:
    return re.match(r"^-?\d+$", token) is not None


def _normalize_rectangle_points(points: np.ndarray) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    point_array = np.asarray(points)
    if point_array.ndim != 2 or point_array.shape != (2, 2):
        raise ValueError("points must be a 2D array with shape (2, 2)")
    normalized_points: List[Tuple[int, int]] = []
    for row_index in range(2):
        coordinate_pair: List[int] = []
        for column_index in range(2):
            raw_value = point_array[row_index, column_index]
            if isinstance(raw_value, bool) or not isinstance(raw_value, Integral):
                raise ValueError(f"points[{row_index}, {column_index}] must be an integer")
            coordinate_pair.append(int(raw_value))
        normalized_points.append((coordinate_pair[0], coordinate_pair[1]))
    return normalized_points[0], normalized_points[1]


def _format_line_message(prefix: str, line_number: int) -> str:
    return f"{prefix} Line {line_number}"
