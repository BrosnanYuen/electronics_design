"""LTspice ASY symbol validation helpers and size extraction APIs."""

from __future__ import annotations

import os
import re
from typing import List
from typing import Sequence
from typing import Tuple

import numpy as np

ValidationResult = Tuple[bool, str]
ReadLinesResult = Tuple[bool, List[str], str]

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


def _shape_coordinate_values(raw_line: str, keyword: str) -> Tuple[int, ...] | None:
    tokens = raw_line.split()
    if keyword in {"LINE", "RECTANGLE", "CIRCLE"}:
        return tuple(int(token) for token in tokens[2:6])
    if keyword == "ARC":
        return tuple(int(token) for token in tokens[2:10])
    return None


def _is_integer_token(token: str) -> bool:
    return re.match(r"^-?\d+$", token) is not None


def _format_line_message(prefix: str, line_number: int) -> str:
    return f"{prefix} Line {line_number}"
