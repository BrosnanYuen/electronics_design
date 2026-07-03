"""Resolve LTspice symbol rectangles and pins inside symbol JSON files."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from typing import Mapping
from typing import Tuple

from .ltspice_asc_to_netlist import get_ltspice_asc_symbol_info

ConversionResult = Tuple[bool, str, int]

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
