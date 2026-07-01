"""Convert LTspice ASC schematics into LTspice netlists."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import os
import re
import tempfile
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
from . import ltspice_asy as _asy
from . import ltspice_net as _net
from .pathtracing import find_wire_group_index
from .pathtracing import place_wires_into_groups

ConversionResult = Tuple[bool, str, int]
StructureCompareResult = Tuple[bool, str, int]
Point = Tuple[int, int]

_LINE_NUMBER_PATTERN = re.compile(r"Line (?P<line>\d+)")
_DIRECTIVE_SPLIT_PATTERN = re.compile(r"(?:\\n|\r\n|\r|\n)+")
_DEFAULT_ANALYSIS_DIRECTIVE = ".op"
_OK_RESULT: ConversionResult = (True, "OK", 0)
_LIBRARY_FILE_SUFFIXES = {".bjt", ".dio", ".jft", ".lib", ".mos", ".sub"}
_SYMBOL_LOOKUP_CACHE: Dict[Tuple[str, ...], Dict[str, "SymbolDefinition"]] = {}
_SYMBOL_FILEPATH_LOOKUP_CACHE: Dict[Tuple[str, ...], Dict[str, str]] = {}
_LIBRARY_LOOKUP_CACHE: Dict[Tuple[str, ...], Dict[str, str]] = {}


def _default_asc_compare_convert_settings() -> Mapping[str, object]:
    custom_search_paths_text = os.environ.get("LTSPICE_CUSTOM_SEARCH_PATHS", "")
    return {
        "ltspice_windows_path": os.environ.get("LTSPICE_WINDOWS_PATH", ""),
        "ltspice_wine_path": os.environ.get("LTSPICE_WINE_PATH", ""),
        "custom_search_paths": [path for path in custom_search_paths_text.split(os.pathsep) if path.strip() != ""],
    }


_DEFAULT_ASC_COMPARE_CONVERT_SETTINGS: Mapping[str, object] = _default_asc_compare_convert_settings()

_STANDARD_LIBRARY_RULES = {
    "D": ((".model D D",), "standard.dio"),
    "Q": ((".model NPN NPN", ".model PNP PNP"), "standard.bjt"),
    "J": ((".model NJF NJF", ".model PJF PJF"), "standard.jft"),
    "M": ((".model NMOS NMOS", ".model PMOS PMOS"), "standard.mos"),
}


@dataclass(frozen=True)
class Wire:
    start: Point
    end: Point


@dataclass(frozen=True)
class Flag:
    point: Point
    name: str


@dataclass(frozen=True)
class PinDefinition:
    pin_name: str
    spice_order: int
    point: Point


@dataclass(frozen=True)
class SymbolDefinition:
    relative_path: str
    prefix: str
    default_value: str
    default_value2: str
    default_spice_model: str
    default_spice_line: str
    default_spice_line2: str
    model_file: str
    pins: Tuple[PinDefinition, ...]


@dataclass
class SymbolInstance:
    symbol_name: str
    origin: Point
    orientation: str
    line_number: int
    attributes: Dict[str, str]


@dataclass(frozen=True)
class TextCommand:
    line_number: int
    text: str


@dataclass(frozen=True)
class ParsedAsc:
    wires: Tuple[Wire, ...]
    flags: Tuple[Flag, ...]
    symbols: Tuple[SymbolInstance, ...]
    text_commands: Tuple[TextCommand, ...]


@dataclass(frozen=True)
class PinNet:
    pin_name: str
    spice_order: int
    net_name: str


def ltspice_asc_to_netlist(
    asc_filepath: str,
    net_filepath_out: str,
    convert_settings: Mapping[str, object],
) -> ConversionResult:
    if not isinstance(convert_settings, Mapping):
        return False, "INVALID_CONVERT_SETTINGS", 0
    if not _coerce_path_success(net_filepath_out):
        return False, "INVALID_OUTPUT_PATH", 0
    asc_validation_result = _asc.is_valid_ltspice_asc_file(asc_filepath)
    if not asc_validation_result[0]:
        relaxed_validation_result = _validate_asc_for_conversion(asc_filepath)
        if not relaxed_validation_result[0]:
            return False, "INVALID_ASC_FILE", _line_number_from_message(asc_validation_result[1], relaxed_validation_result[1])
    read_result = _asc._read_text_file_lines(asc_filepath)
    if not read_result[0]:
        return False, "ASC_READ_ERROR", 0
    parse_result = _parse_asc_for_conversion(read_result[1])
    if not parse_result[0]:
        return False, "ASC_PARSE_ERROR", parse_result[2]
    try:
        symbol_info = get_ltspice_asc_symbol_info(asc_filepath, convert_settings)
    except ValueError as error:
        return _symbol_info_error_to_conversion_result(str(error))
    search_roots = _resolve_search_roots_for_asc(asc_filepath, convert_settings)
    symbol_definitions = _build_symbol_lookup(search_roots)
    library_lookup = _build_library_lookup(search_roots)
    net_build_result = _build_netlist_lines(
        parse_result[1],
        symbol_info,
        symbol_definitions,
        library_lookup,
        convert_settings,
    )
    if not net_build_result[0]:
        return False, net_build_result[1], net_build_result[2]
    write_result = _write_netlist_file(net_filepath_out, net_build_result[3])
    if not write_result[0]:
        return False, write_result[1], 0
    generated_validation_result = _net.is_valid_ltspice_netlist_file(net_filepath_out)
    if not generated_validation_result[0]:
        return False, "INVALID_GENERATED_NETLIST", _line_number_from_message(generated_validation_result[1], 0)
    return _OK_RESULT


def get_ltspice_asc_symbol_info(
    asc_filepath: str,
    convert_settings: Mapping[str, object],
) -> Dict[str, Dict[str, object]]:
    if not isinstance(convert_settings, Mapping):
        raise ValueError("convert_settings must be a mapping")
    read_result = _asc._read_text_file_lines(asc_filepath)
    if not read_result[0]:
        raise ValueError(read_result[2])
    parse_result = _parse_asc_for_conversion(read_result[1])
    if not parse_result[0]:
        raise ValueError(f"Unable to parse LTspice ASC file! Line {parse_result[2]}")
    search_roots = _resolve_search_roots_for_asc(asc_filepath, convert_settings)
    symbol_path_lookup = _build_symbol_filepath_lookup(search_roots)
    symbol_info: Dict[str, Dict[str, object]] = {}
    for symbol_instance in parse_result[1].symbols:
        instance_name = symbol_instance.attributes.get("InstName", "").strip()
        if instance_name == "":
            raise ValueError(f"LTspice ASC symbol is missing InstName! Line {symbol_instance.line_number}")
        if instance_name in symbol_info:
            raise ValueError(f"Duplicate LTspice ASC symbol InstName '{instance_name}'! Line {symbol_instance.line_number}")
        symbol_filepath = _resolve_symbol_filepath(symbol_instance.symbol_name, symbol_path_lookup)
        if symbol_filepath is None:
            raise ValueError(f"Unable to locate LTspice symbol file for '{symbol_instance.symbol_name}'! Line {symbol_instance.line_number}")
        pins = _asy.get_ltspice_asy_pins(symbol_filepath)
        bounds = _asy.get_ltspice_asy_size(symbol_filepath)
        transformed_pins = [
            [
                transformed_point[0],
                transformed_point[1],
                pin_name,
                spice_order,
            ]
            for pin_x, pin_y, pin_name, spice_order in pins
            for transformed_point in [_transform_pin_point((int(pin_x), int(pin_y)), symbol_instance.origin, symbol_instance.orientation)]
        ]
        symbol_info[instance_name] = {
            "SYMBOL": _display_symbol_name(symbol_instance.symbol_name),
            "X": symbol_instance.origin[0],
            "Y": symbol_instance.origin[1],
            "ROTATION": _orientation_angle(symbol_instance.orientation),
            "RECTANGLE": _transform_symbol_rectangle(bounds, symbol_instance.origin, symbol_instance.orientation),
            "PINS": transformed_pins,
        }
    return symbol_info


def ltspice_asc_structure_cmp(
    filepath1: str,
    filepath2: str,
    convert_settings: Optional[Mapping[str, object]] = None,
) -> StructureCompareResult:
    first_validation_result = _asc.is_valid_ltspice_asc_file(filepath1)
    if not first_validation_result[0]:
        return False, _message_without_line_number(first_validation_result[1]), _line_number_from_message(first_validation_result[1], 0)
    second_validation_result = _asc.is_valid_ltspice_asc_file(filepath2)
    if not second_validation_result[0]:
        return False, _message_without_line_number(second_validation_result[1]), _line_number_from_message(second_validation_result[1], 0)
    effective_convert_settings = convert_settings if convert_settings is not None else _DEFAULT_ASC_COMPARE_CONVERT_SETTINGS
    with tempfile.TemporaryDirectory() as temporary_directory:
        first_netlist_path = Path(temporary_directory) / "first.net"
        second_netlist_path = Path(temporary_directory) / "second.net"
        first_convert_result = ltspice_asc_to_netlist(filepath1, str(first_netlist_path), effective_convert_settings)
        if not first_convert_result[0]:
            return False, first_convert_result[1], first_convert_result[2]
        second_convert_result = ltspice_asc_to_netlist(filepath2, str(second_netlist_path), effective_convert_settings)
        if not second_convert_result[0]:
            return False, second_convert_result[1], second_convert_result[2]
        if _net.ltspice_netlist_structure_cmp(str(first_netlist_path), str(second_netlist_path)):
            return True, "", 0
    return _diagnose_asc_structure_difference(filepath1, filepath2, effective_convert_settings)


def _validate_asc_for_conversion(filepath: str) -> Tuple[bool, int]:
    header_result = _asc.is_valid_ltspice_asc_header(filepath)
    if not header_result[0]:
        return False, _line_number_from_message(header_result[1], 0)
    spacing_result = _asc.is_valid_ltspice_asc_spacing(filepath)
    if not spacing_result[0]:
        return False, _line_number_from_message(spacing_result[1], 0)
    return True, 0


def _diagnose_asc_structure_difference(
    filepath1: str,
    filepath2: str,
    convert_settings: Mapping[str, object],
) -> StructureCompareResult:
    first_signature_result = _build_asc_component_signature_records(filepath1, convert_settings)
    if not first_signature_result[0]:
        return False, first_signature_result[1], first_signature_result[2]
    second_signature_result = _build_asc_component_signature_records(filepath2, convert_settings)
    if not second_signature_result[0]:
        return False, second_signature_result[1], second_signature_result[2]
    first_records = first_signature_result[3]
    second_records = second_signature_result[3]
    first_counts = Counter(signature for signature, _line_number in first_records)
    second_counts = Counter(signature for signature, _line_number in second_records)
    for signature, line_number in second_records:
        if second_counts[signature] > first_counts[signature]:
            return False, "ASC structures are different!", line_number
    for signature, line_number in first_records:
        if first_counts[signature] > second_counts[signature]:
            return False, "ASC structures are different!", line_number
    return False, "ASC structures are different!", 0


def _build_asc_component_signature_records(
    filepath: str,
    convert_settings: Mapping[str, object],
) -> Tuple[bool, str, int, Tuple[Tuple[Tuple[str, Tuple[str, ...]], int], ...]]:
    read_result = _asc._read_text_file_lines(filepath)
    if not read_result[0]:
        return False, read_result[2], 0, ()
    parse_result = _parse_asc_for_conversion(read_result[1])
    if not parse_result[0]:
        return False, "ASC_PARSE_ERROR", parse_result[2], ()
    try:
        symbol_info = get_ltspice_asc_symbol_info(filepath, convert_settings)
    except ValueError as error:
        conversion_result = _symbol_info_error_to_conversion_result(str(error))
        return conversion_result[0], conversion_result[1], conversion_result[2], ()
    search_roots = _resolve_search_roots_for_asc(filepath, convert_settings)
    symbol_definitions = _build_symbol_lookup(search_roots)
    connectivity_result = _resolve_symbol_nets(parse_result[1], symbol_info)
    if not connectivity_result[0]:
        return False, connectivity_result[1], connectivity_result[2], ()
    symbol_pin_nets = connectivity_result[3]
    signature_records: List[Tuple[Tuple[str, Tuple[str, ...]], int]] = []
    for symbol_instance in parse_result[1].symbols:
        symbol_definition = _resolve_symbol_definition(symbol_instance.symbol_name, symbol_definitions)
        if symbol_definition is None:
            return False, "UNKNOWN_SYMBOL", symbol_instance.line_number, ()
        instance_name = symbol_instance.attributes.get("InstName", "").strip()
        if instance_name == "" or instance_name not in symbol_pin_nets:
            return False, "UNKNOWN_SYMBOL", symbol_instance.line_number, ()
        component_line_result = _build_component_line(symbol_instance, symbol_definition, symbol_pin_nets[instance_name])
        if not component_line_result[0]:
            return False, component_line_result[1], symbol_instance.line_number, ()
        tokens = component_line_result[3].split()
        node_result = _net._extract_nodes(tokens)
        if not node_result[0]:
            return False, "ASC_COMPARE_DIAGNOSTIC_ERROR", symbol_instance.line_number, ()
        parsed_element = _net.ParsedElement(
            line_number=symbol_instance.line_number,
            prefix=tokens[0][0].upper(),
            tokens=tokens,
            nodes=node_result[1],
        )
        signature_records.append((_net._component_signature(parsed_element), symbol_instance.line_number))
    return True, "", 0, tuple(signature_records)


def _parse_asc_for_conversion(lines: Sequence[str]) -> Tuple[bool, ParsedAsc, int]:
    wires: List[Wire] = []
    flags: List[Flag] = []
    symbols: List[SymbolInstance] = []
    text_commands: List[TextCommand] = []
    current_symbol: Optional[SymbolInstance] = None
    for line_number, raw_line in enumerate(lines, start=1):
        if raw_line.strip() == "":
            continue
        tokens = raw_line.split()
        keyword = tokens[0].upper()
        if keyword == "WIRE":
            wires.append(Wire((int(tokens[1]), int(tokens[2])), (int(tokens[3]), int(tokens[4]))))
            current_symbol = None
            continue
        if keyword == "FLAG":
            flags.append(Flag((int(tokens[1]), int(tokens[2])), " ".join(tokens[3:])))
            current_symbol = None
            continue
        if keyword == "SYMBOL":
            current_symbol = SymbolInstance(
                symbol_name=tokens[1],
                origin=(int(tokens[2]), int(tokens[3])),
                orientation=tokens[4],
                line_number=line_number,
                attributes={},
            )
            symbols.append(current_symbol)
            continue
        if keyword == "SYMATTR" and current_symbol is not None:
            attr_tokens = raw_line.split(maxsplit=2)
            if len(attr_tokens) >= 3:
                current_symbol.attributes[attr_tokens[1]] = attr_tokens[2]
            continue
        if keyword == "WINDOW" and current_symbol is not None:
            continue
        if keyword == "TEXT":
            directive_extract_result = _asc._extract_asc_text_directive(raw_line)
            if directive_extract_result[0] and directive_extract_result[1] != "":
                for command_text in _split_embedded_commands(directive_extract_result[1]):
                    text_commands.append(TextCommand(line_number=line_number, text=command_text))
            current_symbol = None
            continue
        current_symbol = None
    return True, ParsedAsc(tuple(wires), tuple(flags), tuple(symbols), tuple(text_commands)), 0


def _split_embedded_commands(command_text: str) -> Tuple[str, ...]:
    commands = tuple(part.strip() for part in _DIRECTIVE_SPLIT_PATTERN.split(command_text) if part.strip() != "")
    return commands


def _resolve_search_roots(convert_settings: Mapping[str, object]) -> Tuple[str, ...]:
    custom_search_paths = _normalize_custom_search_paths(convert_settings.get("custom_search_paths", ()))
    wine_path = _normalize_search_path(convert_settings.get("ltspice_wine_path", ""))
    windows_path = _normalize_search_path(convert_settings.get("ltspice_windows_path", ""))
    search_roots: List[str] = []
    for candidate_path in (*custom_search_paths, wine_path, windows_path):
        if candidate_path == "" or candidate_path in search_roots:
            continue
        search_roots.append(candidate_path)
    return tuple(search_roots)


def _resolve_search_roots_for_asc(asc_filepath: str, convert_settings: Mapping[str, object]) -> Tuple[str, ...]:
    search_roots = list(_resolve_search_roots(convert_settings))
    for candidate_path in _discover_local_search_roots(asc_filepath):
        if candidate_path not in search_roots:
            search_roots.append(candidate_path)
    return tuple(search_roots)


def _discover_local_search_roots(asc_filepath: str) -> Tuple[str, ...]:
    coerced_path_result = _asc._coerce_path(asc_filepath)
    if not coerced_path_result[0]:
        return ()
    asc_path = Path(coerced_path_result[1]).resolve()
    if not asc_path.exists():
        return ()
    search_roots = [str(asc_path.parent)]
    for parent in asc_path.parents:
        if parent == asc_path.parent:
            continue
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            search_roots.append(str(parent))
            break
    return tuple(search_roots)


def _normalize_custom_search_paths(value: object) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, os.PathLike)):
        return (_normalize_search_path(value),)
    try:
        values = tuple(value)
    except TypeError:
        return ()
    return tuple(
        normalized_path
        for normalized_path in (_normalize_search_path(item) for item in values)
        if normalized_path != ""
    )


def _normalize_search_path(value: object) -> str:
    try:
        path_string = os.fspath(value).strip()
    except TypeError:
        return ""
    if path_string == "":
        return ""
    return os.path.expanduser(path_string)


def _resolve_windows_ltspice_path(convert_settings: Mapping[str, object]) -> str:
    return str(convert_settings.get("ltspice_windows_path", "")).strip()


def _build_symbol_lookup(search_roots: Sequence[str]) -> Dict[str, SymbolDefinition]:
    cache_key = tuple(search_roots)
    if cache_key in _SYMBOL_LOOKUP_CACHE:
        return _SYMBOL_LOOKUP_CACHE[cache_key]
    lookup: Dict[str, SymbolDefinition] = {}
    for symbol_root in search_roots:
        if not os.path.isdir(symbol_root):
            continue
        for symbol_path in Path(symbol_root).rglob("*.asy"):
            relative_path = symbol_path.relative_to(symbol_root).as_posix()
            definition = _load_symbol_definition(str(symbol_path), relative_path)
            if definition is not None:
                lookup.setdefault(relative_path.lower(), definition)
                lookup.setdefault(symbol_path.name.lower(), definition)
    _SYMBOL_LOOKUP_CACHE[cache_key] = lookup
    return lookup


def _build_symbol_filepath_lookup(search_roots: Sequence[str]) -> Dict[str, str]:
    cache_key = tuple(search_roots)
    if cache_key in _SYMBOL_FILEPATH_LOOKUP_CACHE:
        return _SYMBOL_FILEPATH_LOOKUP_CACHE[cache_key]
    lookup: Dict[str, str] = {}
    for symbol_root in search_roots:
        if not os.path.isdir(symbol_root):
            continue
        for symbol_path in Path(symbol_root).rglob("*.asy"):
            normalized_relative_path = symbol_path.relative_to(symbol_root).as_posix().lower()
            normalized_filename = symbol_path.name.lower()
            normalized_stem = symbol_path.stem.lower()
            symbol_path_string = str(symbol_path)
            lookup.setdefault(normalized_relative_path, symbol_path_string)
            lookup.setdefault(normalized_filename, symbol_path_string)
            lookup.setdefault(normalized_stem, symbol_path_string)
    _SYMBOL_FILEPATH_LOOKUP_CACHE[cache_key] = lookup
    return lookup


def _build_library_lookup(search_roots: Sequence[str]) -> Dict[str, str]:
    cache_key = tuple(search_roots)
    if cache_key in _LIBRARY_LOOKUP_CACHE:
        return _LIBRARY_LOOKUP_CACHE[cache_key]
    lookup: Dict[str, str] = {}
    for search_root in search_roots:
        if not os.path.isdir(search_root):
            continue
        for library_path in Path(search_root).rglob("*"):
            if not library_path.is_file():
                continue
            if library_path.suffix.lower() not in _LIBRARY_FILE_SUFFIXES and not library_path.name.lower().startswith("standard."):
                continue
            relative_path = library_path.relative_to(search_root).as_posix()
            normalized_relative_path = relative_path.lower()
            lookup.setdefault(normalized_relative_path, relative_path)
            lookup.setdefault(library_path.name.lower(), relative_path)
            if normalized_relative_path.startswith("lib/"):
                lookup.setdefault(normalized_relative_path[4:], relative_path)
    _LIBRARY_LOOKUP_CACHE[cache_key] = lookup
    return lookup


def _load_symbol_definition(filepath: str, relative_path: str) -> Optional[SymbolDefinition]:
    try:
        symbol_text = Path(filepath).read_text(encoding="latin-1")
    except OSError:
        return None
    prefix = ""
    default_value = ""
    default_value2 = ""
    default_spice_model = ""
    default_spice_line = ""
    default_spice_line2 = ""
    model_file = ""
    pins: List[PinDefinition] = []
    pending_pin_point: Optional[Point] = None
    pending_pin_name = ""
    pending_pin_order = 0
    for raw_line in symbol_text.splitlines():
        if raw_line.startswith("SYMATTR Prefix "):
            prefix = raw_line.split(" ", 2)[2].strip()
            continue
        if raw_line.startswith("SYMATTR Value2 "):
            default_value2 = raw_line.split(" ", 2)[2].strip()
            continue
        if raw_line.startswith("SYMATTR Value "):
            default_value = raw_line.split(" ", 2)[2].strip()
            continue
        if raw_line.startswith("SYMATTR SpiceModel "):
            default_spice_model = raw_line.split(" ", 2)[2].strip()
            continue
        if raw_line.startswith("SYMATTR SpiceLine2 "):
            default_spice_line2 = raw_line.split(" ", 2)[2].strip()
            continue
        if raw_line.startswith("SYMATTR SpiceLine "):
            default_spice_line = raw_line.split(" ", 2)[2].strip()
            continue
        if raw_line.startswith("SYMATTR ModelFile "):
            model_file = raw_line.split(" ", 2)[2].strip()
            continue
        if raw_line.startswith("PIN "):
            pin_tokens = raw_line.split()
            pending_pin_point = (int(pin_tokens[1]), int(pin_tokens[2]))
            pending_pin_name = ""
            pending_pin_order = 0
            continue
        if raw_line.startswith("PINATTR PinName ") and pending_pin_point is not None:
            pending_pin_name = raw_line.split(" ", 2)[2].strip()
            continue
        if raw_line.startswith("PINATTR SpiceOrder ") and pending_pin_point is not None:
            try:
                pending_pin_order = int(raw_line.split(" ", 2)[2].strip())
            except ValueError:
                pending_pin_point = None
                pending_pin_name = ""
                pending_pin_order = 0
                continue
            pins.append(PinDefinition(pending_pin_name, pending_pin_order, pending_pin_point))
            pending_pin_point = None
            pending_pin_name = ""
            pending_pin_order = 0
            continue
    if prefix == "" or not pins:
        return None
    return SymbolDefinition(
        relative_path=relative_path,
        prefix=prefix,
        default_value=default_value,
        default_value2=default_value2,
        default_spice_model=default_spice_model,
        default_spice_line=default_spice_line,
        default_spice_line2=default_spice_line2,
        model_file=model_file,
        pins=tuple(sorted(pins, key=lambda pin: pin.spice_order)),
    )


def _build_netlist_lines(
    parsed_asc: ParsedAsc,
    symbol_info: Mapping[str, Dict[str, object]],
    symbol_definitions: Mapping[str, SymbolDefinition],
    library_lookup: Mapping[str, str],
    convert_settings: Mapping[str, object],
) -> Tuple[bool, str, int, Tuple[str, ...]]:
    connectivity_result = _resolve_symbol_nets(parsed_asc, symbol_info)
    if not connectivity_result[0]:
        return False, connectivity_result[1], connectivity_result[2], ()
    symbol_pin_nets = connectivity_result[3]
    component_lines: List[str] = []
    auxiliary_device_lines: List[str] = []
    directive_lines: List[str] = []
    standard_footer_lines: List[str] = []
    analysis_found = False
    used_standard_prefixes: Set[str] = set()
    used_symbol_libraries: Dict[str, None] = {}
    for symbol_instance in parsed_asc.symbols:
        symbol_definition = _resolve_symbol_definition(symbol_instance.symbol_name, symbol_definitions)
        if symbol_definition is None:
            return False, "UNKNOWN_SYMBOL", symbol_instance.line_number, ()
        instance_name = symbol_instance.attributes.get("InstName", "").strip()
        if instance_name == "" or instance_name not in symbol_pin_nets:
            return False, "UNKNOWN_SYMBOL", symbol_instance.line_number, ()
        line_result = _build_component_line(symbol_instance, symbol_definition, symbol_pin_nets[instance_name])
        if not line_result[0]:
            return False, line_result[1], symbol_instance.line_number, ()
        component_lines.append(line_result[3])
        normalized_prefix = line_result[4]
        if normalized_prefix in _STANDARD_LIBRARY_RULES and normalized_prefix not in used_standard_prefixes:
            used_standard_prefixes.add(normalized_prefix)
        library_reference = _infer_symbol_library_reference(symbol_instance, symbol_definition)
        if library_reference is not None:
            resolved_library_reference = _resolve_library_relative_path(library_reference, library_lookup)
            if resolved_library_reference is not None:
                used_symbol_libraries[_library_basename(resolved_library_reference)] = None
    for text_command in parsed_asc.text_commands:
        if text_command.text.startswith("."):
            if text_command.text.lower() in {".backanno", ".end"}:
                continue
            directive_lines.append(text_command.text)
            directive_parse_result = _asc._parse_directive_name(text_command.text)
            if directive_parse_result[0] and directive_parse_result[1] in _asc._ANALYSIS_DIRECTIVES:
                analysis_found = True
            continue
        auxiliary_device_lines.append(text_command.text)
    if not analysis_found:
        directive_lines.append(_DEFAULT_ANALYSIS_DIRECTIVE)
    windows_ltspice_path = _resolve_windows_ltspice_path(convert_settings)
    for prefix in _STANDARD_LIBRARY_RULES:
        if prefix not in used_standard_prefixes:
            continue
        model_lines_for_prefix, library_name = _STANDARD_LIBRARY_RULES[prefix]
        for model_line in model_lines_for_prefix:
            standard_footer_lines.append(model_line)
        if library_name is not None:
            resolved_standard_library = _resolve_library_relative_path(library_name, library_lookup)
            if resolved_standard_library is not None:
                standard_footer_lines.append(_build_library_line(windows_ltspice_path, resolved_standard_library))
    symbol_include_lines = tuple(f".lib {library_name}" for library_name in used_symbol_libraries)
    final_lines = _dedupe_lines(
        tuple(component_lines)
        + tuple(auxiliary_device_lines)
        + tuple(standard_footer_lines)
        + tuple(directive_lines)
        + symbol_include_lines
        + (".backanno", ".end")
    )
    return True, "OK", 0, final_lines


def _resolve_symbol_nets(
    parsed_asc: ParsedAsc,
    symbol_info: Mapping[str, Dict[str, object]],
) -> Tuple[bool, str, int, Dict[str, Tuple[PinNet, ...]]]:
    wire_groups = _wire_groups_from_parsed_asc(parsed_asc)
    entity_names: Dict[Tuple[str, object], List[str]] = {}
    entity_first_seen: Dict[Tuple[str, object], int] = {}
    entity_pin_counts: Dict[Tuple[str, object], int] = {}
    coordinate_entities: Dict[Point, Tuple[str, object]] = {}
    next_standalone_net = 0
    pin_entity_records: Dict[str, List[Tuple[str, int, Tuple[str, object]]]] = {}
    for symbol_instance in parsed_asc.symbols:
        instance_name = symbol_instance.attributes.get("InstName", "").strip()
        if instance_name == "" or instance_name not in symbol_info:
            return False, "UNKNOWN_SYMBOL", symbol_instance.line_number, {}
        raw_pins = symbol_info[instance_name].get("PINS", ())
        try:
            pins = tuple(raw_pins)
        except TypeError:
            return False, "ASC_PARSE_ERROR", symbol_instance.line_number, {}
        pin_entity_records[instance_name] = []
        for pin_row in pins:
            try:
                pin_coordinate, pin_name, spice_order = _extract_symbol_info_pin(pin_row, symbol_instance.line_number)
            except ValueError:
                return False, "ASC_PARSE_ERROR", symbol_instance.line_number, {}
            entity_key = _entity_for_grouped_point(pin_coordinate, wire_groups, coordinate_entities, next_standalone_net)
            if entity_key[0] == "coord" and entity_key[1] == next_standalone_net:
                next_standalone_net += 1
            pin_entity_records[instance_name].append((pin_name, spice_order, entity_key))
            entity_first_seen.setdefault(entity_key, len(entity_first_seen))
            entity_pin_counts[entity_key] = entity_pin_counts.get(entity_key, 0) + 1
    for flag in parsed_asc.flags:
        entity_key = _entity_for_grouped_point(flag.point, wire_groups, coordinate_entities, next_standalone_net)
        if entity_key[0] == "coord" and entity_key[1] == next_standalone_net:
            next_standalone_net += 1
        entity_names.setdefault(entity_key, []).append(flag.name.strip())
        entity_first_seen.setdefault(entity_key, len(entity_first_seen))
    named_groups: Dict[str, List[Tuple[str, object]]] = {}
    for entity_key, names in entity_names.items():
        for raw_name in names:
            normalized_name = raw_name.strip()
            if normalized_name == "":
                continue
            named_groups.setdefault(normalized_name.upper(), []).append(entity_key)
    merged_entities: Dict[Tuple[str, object], Tuple[str, object]] = {}
    for entity_key in entity_first_seen:
        merged_entities[entity_key] = entity_key
    for group_entities in named_groups.values():
        canonical_entity = min(group_entities, key=lambda entity_key: entity_first_seen.get(entity_key, 0))
        for entity_key in group_entities:
            merged_entities[entity_key] = canonical_entity
    canonical_names: Dict[Tuple[str, object], str] = {}
    auto_index = 1
    no_connect_index = 1
    for entity_key in sorted(entity_first_seen, key=lambda entry: entity_first_seen[entry]):
        canonical_entity = merged_entities[entity_key]
        if canonical_entity in canonical_names:
            continue
        explicit_names = []
        canonical_pin_count = 0
        for grouped_entity, names in entity_names.items():
            if merged_entities[grouped_entity] == canonical_entity:
                explicit_names.extend(name for name in names if name.strip() != "")
        for grouped_entity, pin_count in entity_pin_counts.items():
            if merged_entities[grouped_entity] == canonical_entity:
                canonical_pin_count += pin_count
        if canonical_pin_count == 1:
            canonical_names[canonical_entity] = _choose_single_pin_net_name(explicit_names, no_connect_index)
            no_connect_index += 1
            continue
        if explicit_names:
            canonical_names[canonical_entity] = _choose_explicit_net_name(explicit_names)
            continue
        canonical_names[canonical_entity] = f"N{auto_index:03d}"
        auto_index += 1
    symbol_pin_nets: Dict[str, Tuple[PinNet, ...]] = {}
    for instance_name, pin_records in pin_entity_records.items():
        symbol_pin_nets[instance_name] = tuple(
            PinNet(
                pin_name=pin_name,
                spice_order=spice_order,
                net_name=canonical_names[merged_entities[entity_key]],
            )
            for pin_name, spice_order, entity_key in sorted(pin_records, key=lambda record: record[1])
        )
    return True, "OK", 0, symbol_pin_nets


def _wire_groups_from_parsed_asc(parsed_asc: ParsedAsc) -> List[np.ndarray]:
    if not parsed_asc.wires:
        return []
    wire_rows = np.array(
        [[wire.start[0], wire.start[1], wire.end[0], wire.end[1]] for wire in parsed_asc.wires],
        dtype=int,
    )
    return place_wires_into_groups(wire_rows)


def _extract_symbol_info_pin(pin_row: object, line_number: int) -> Tuple[Point, str, int]:
    try:
        pin_x, pin_y, pin_name, spice_order = pin_row
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid symbol pin information! Line {line_number}") from error
    return (int(pin_x), int(pin_y)), str(pin_name), int(spice_order)


def _entity_for_grouped_point(
    point: Point,
    wire_groups: Sequence[np.ndarray],
    coordinate_entities: Dict[Point, Tuple[str, object]],
    next_standalone_net: int,
) -> Tuple[str, object]:
    group_index = find_wire_group_index(np.array([point[0], point[1]], dtype=int), list(wire_groups))
    if group_index >= 0:
        return ("wire_group", group_index)
    if point not in coordinate_entities:
        coordinate_entities[point] = ("coord", next_standalone_net)
    return coordinate_entities[point]


def _choose_explicit_net_name(names: Sequence[str]) -> str:
    for candidate_name in names:
        normalized_name = candidate_name.strip()
        if normalized_name.upper() in {"0", "GND"}:
            return "0"
    return names[0].strip()


def _choose_single_pin_net_name(names: Sequence[str], no_connect_index: int) -> str:
    for candidate_name in names:
        normalized_name = candidate_name.strip()
        if normalized_name.upper() in {"0", "GND"}:
            return "0"
        if normalized_name.upper().startswith(("NC", "NC_", "NC-")):
            return normalized_name
    return f"NC_{no_connect_index:02d}"


def _build_component_line(
    symbol_instance: SymbolInstance,
    symbol_definition: SymbolDefinition,
    pin_nets_by_order: Sequence[PinNet],
) -> Tuple[bool, str, int, str, str]:
    if not pin_nets_by_order:
        return False, "UNCONNECTED_SYMBOL_PIN", symbol_instance.line_number, "", ""
    normalized_prefix = _normalized_component_prefix(symbol_definition.prefix)
    ordered_nets = _expand_component_nodes(symbol_instance.symbol_name, normalized_prefix, pin_nets_by_order)
    component_instance_name = _component_instance_name(symbol_instance.attributes.get("InstName", ""), normalized_prefix)
    payload_tokens = _component_payload_tokens(symbol_instance, symbol_definition)
    if not payload_tokens and not _payload_optional_for_prefix(normalized_prefix):
        return False, "MISSING_COMPONENT_PAYLOAD", symbol_instance.line_number, "", ""
    component_line = " ".join((component_instance_name, *ordered_nets, *payload_tokens)).strip()
    return True, "OK", 0, component_line, normalized_prefix


def _normalized_component_prefix(prefix: str) -> str:
    upper_prefix = prefix.upper()
    if upper_prefix in {"QN", "QP"}:
        return "Q"
    if upper_prefix == "MN":
        return "M"
    if upper_prefix == "JN":
        return "J"
    return upper_prefix[:1]


def _expand_component_nodes(
    symbol_name: str,
    normalized_prefix: str,
    pin_nets_by_order: Sequence[PinNet],
) -> Tuple[str, ...]:
    pin_nets = tuple(pin_net.net_name for pin_net in pin_nets_by_order)
    lowered_symbol_name = symbol_name.lower()
    if normalized_prefix == "A":
        ordered_pin_nets = {}
        for pin_net in pin_nets_by_order:
            normalized_net_name = pin_net.net_name
            if pin_net.pin_name.strip().lower() == "com" and pin_net.net_name.upper().startswith(("NC", "NC_", "NC-")):
                normalized_net_name = "0"
            ordered_pin_nets[pin_net.spice_order] = normalized_net_name
        highest_order = max((pin_net.spice_order for pin_net in pin_nets_by_order), default=0)
        return tuple(ordered_pin_nets.get(spice_order, "0") for spice_order in range(1, max(8, highest_order) + 1))
    if normalized_prefix == "Q":
        return tuple(pin_nets) + ("0",)
    if normalized_prefix == "M":
        source_node = pin_nets[2] if len(pin_nets) >= 3 else "0"
        return tuple(pin_nets) + (source_node,)
    if lowered_symbol_name.endswith("gain") or lowered_symbol_name == "gain":
        return tuple(pin_nets)
    return tuple(pin_nets)


def _component_instance_name(instance_name: str, normalized_prefix: str) -> str:
    clean_name = instance_name.strip()
    if clean_name == "":
        return f"{normalized_prefix}§AUTO"
    if clean_name[0].upper() == normalized_prefix:
        return clean_name
    return f"{normalized_prefix}§{clean_name}"


def _component_payload_tokens(symbol_instance: SymbolInstance, symbol_definition: SymbolDefinition) -> Tuple[str, ...]:
    normalized_prefix = _normalized_component_prefix(symbol_definition.prefix)
    explicit_value = _clean_optional_text(symbol_instance.attributes.get("Value", ""))
    explicit_value2 = _clean_optional_text(symbol_instance.attributes.get("Value2", ""))
    explicit_spice_model = _clean_optional_text(symbol_instance.attributes.get("SpiceModel", ""))
    explicit_spice_line = _clean_optional_text(symbol_instance.attributes.get("SpiceLine", ""))
    explicit_spice_line2 = _clean_optional_text(symbol_instance.attributes.get("SpiceLine2", ""))
    default_value = _clean_optional_text(symbol_definition.default_value)
    default_value2 = _clean_optional_text(symbol_definition.default_value2)
    default_spice_line = _clean_optional_text(symbol_definition.default_spice_line)
    default_spice_line2 = _clean_optional_text(symbol_definition.default_spice_line2)
    default_spice_model = _clean_optional_text(symbol_definition.default_spice_model)
    if normalized_prefix in {"R", "C", "L", "D", "V", "I", "J", "Q", "M", "S", "T", "B"}:
        return _join_payload_tokens(
            explicit_value if explicit_value != "" else _default_payload_value_for_prefix(normalized_prefix, default_value),
            explicit_value2 if explicit_value2 != "" else _default_secondary_payload_value_for_prefix(normalized_prefix, default_value2),
            explicit_spice_line if explicit_spice_line != "" else default_spice_line,
            explicit_spice_line2 if explicit_spice_line2 != "" else default_spice_line2,
        )
    if normalized_prefix == "A":
        model_token = explicit_spice_model or default_spice_model or explicit_value or default_value or explicit_value2 or default_value2
        if model_token == "":
            return ()
        trailing_tokens = [
            token
            for token in _non_empty_tokens(explicit_value, explicit_value2, explicit_spice_line, explicit_spice_line2, default_spice_line, default_spice_line2)
            if token != model_token
        ]
        return (model_token, *trailing_tokens)
    if normalized_prefix in {"E", "G"}:
        gain_token = explicit_value if explicit_value != "" else "G={G}"
        return _join_payload_tokens(gain_token, explicit_value2, explicit_spice_line, explicit_spice_line2)
    if normalized_prefix == "X":
        return _subcircuit_payload_tokens(symbol_instance, symbol_definition)
    return _join_payload_tokens(explicit_value, explicit_value2, explicit_spice_line, explicit_spice_line2)


def _payload_optional_for_prefix(normalized_prefix: str) -> bool:
    return normalized_prefix in {"V", "I"}


def _subcircuit_payload_tokens(symbol_instance: SymbolInstance, symbol_definition: SymbolDefinition) -> Tuple[str, ...]:
    explicit_value = _clean_optional_text(symbol_instance.attributes.get("Value", ""))
    explicit_value2 = _clean_optional_text(symbol_instance.attributes.get("Value2", ""))
    explicit_spice_model = _clean_optional_text(symbol_instance.attributes.get("SpiceModel", ""))
    explicit_spice_line = _clean_optional_text(symbol_instance.attributes.get("SpiceLine", ""))
    explicit_spice_line2 = _clean_optional_text(symbol_instance.attributes.get("SpiceLine2", ""))
    default_value = _clean_optional_text(symbol_definition.default_value)
    default_value2 = _clean_optional_text(symbol_definition.default_value2)
    default_spice_model = _clean_optional_text(symbol_definition.default_spice_model)
    default_spice_line = _clean_optional_text(symbol_definition.default_spice_line)
    default_spice_line2 = _clean_optional_text(symbol_definition.default_spice_line2)
    model_token = ""
    extra_tokens: List[str] = []
    if _is_parameter_block(default_value2) and default_spice_model != "":
        model_token = explicit_spice_model or default_spice_model
        extra_tokens.extend(_non_empty_tokens(explicit_value2 or default_value2, explicit_spice_line or default_spice_line, explicit_spice_line2 or default_spice_line2))
        return (model_token, *extra_tokens)
    model_token = explicit_value2 or default_value2 or explicit_value or default_value
    if model_token == "" and explicit_spice_model != "" and not _looks_like_library_reference(explicit_spice_model):
        model_token = explicit_spice_model
    if model_token == "" and default_spice_model != "" and not _looks_like_library_reference(default_spice_model):
        model_token = default_spice_model
    if model_token == "":
        model_token = explicit_value or default_value
    extra_tokens.extend(_non_empty_tokens(explicit_spice_line or default_spice_line, explicit_spice_line2 or default_spice_line2))
    if model_token == "":
        return tuple(extra_tokens)
    return (model_token, *extra_tokens)


def _default_payload_value_for_prefix(normalized_prefix: str, default_value: str) -> str:
    if normalized_prefix in {"V", "I", "B"}:
        return ""
    return default_value


def _default_secondary_payload_value_for_prefix(normalized_prefix: str, default_value2: str) -> str:
    if normalized_prefix in {"V", "I"}:
        return default_value2
    return default_value2


def _is_parameter_block(value: str) -> bool:
    return value != "" and ("=" in value or " " in value)


def _join_payload_tokens(*values: str) -> Tuple[str, ...]:
    return _non_empty_tokens(*values)


def _non_empty_tokens(*values: str) -> Tuple[str, ...]:
    tokens: List[str] = []
    for value in values:
        clean_value = _clean_optional_text(value)
        if clean_value != "":
            tokens.append(clean_value)
    return tuple(tokens)


def _clean_optional_text(value: str) -> str:
    cleaned_value = value.strip()
    if cleaned_value in {"", '""'}:
        return ""
    return cleaned_value


def _resolve_symbol_definition(symbol_name: str, symbol_definitions: Mapping[str, SymbolDefinition]) -> Optional[SymbolDefinition]:
    normalized_symbol = symbol_name.replace("\\", "/").lower()
    direct_key = f"{normalized_symbol}.asy"
    if direct_key in symbol_definitions:
        return symbol_definitions[direct_key]
    base_name = normalized_symbol.split("/")[-1]
    if base_name in symbol_definitions:
        return symbol_definitions[base_name]
    for relative_path, definition in symbol_definitions.items():
        if relative_path.endswith(f"/{base_name}.asy") or relative_path == f"{base_name}.asy":
            return definition
    return None


def _resolve_symbol_filepath(symbol_name: str, symbol_paths: Mapping[str, str]) -> Optional[str]:
    normalized_symbol = symbol_name.replace("\\", "/").strip().lstrip("./").lower()
    direct_key = f"{normalized_symbol}.asy"
    basename = normalized_symbol.split("/")[-1]
    for lookup_key in (direct_key, normalized_symbol, f"{basename}.asy", basename):
        if lookup_key in symbol_paths:
            return symbol_paths[lookup_key]
    return None


def _display_symbol_name(symbol_name: str) -> str:
    return symbol_name.replace("\\", "/").split("/")[-1]


def _transform_symbol_rectangle(bounds, origin: Point, orientation: str) -> List[List[int]]:
    minimum_point = (int(bounds[0][0]), int(bounds[0][1]))
    maximum_point = (int(bounds[1][0]), int(bounds[1][1]))
    corners = (
        minimum_point,
        (maximum_point[0], minimum_point[1]),
        (minimum_point[0], maximum_point[1]),
        maximum_point,
    )
    transformed_corners = [_transform_pin_point(corner, origin, orientation) for corner in corners]
    x_positions = [point[0] for point in transformed_corners]
    y_positions = [point[1] for point in transformed_corners]
    return [[min(x_positions), min(y_positions)], [max(x_positions), max(y_positions)]]


def _transform_pin_point(local_point: Point, origin: Point, orientation: str) -> Point:
    x_position, y_position = local_point
    normalized_orientation = orientation.upper()
    angle = _orientation_angle(normalized_orientation)
    if angle == 90:
        x_position, y_position = -y_position, x_position
    elif angle == 180:
        x_position, y_position = -x_position, -y_position
    elif angle == 270:
        x_position, y_position = y_position, -x_position
    if normalized_orientation.startswith("M"):
        x_position = -x_position
    return origin[0] + x_position, origin[1] + y_position


def _orientation_angle(orientation: str) -> int:
    angle_match = re.search(r"(\d+)$", orientation)
    if angle_match is None:
        return 0
    return int(angle_match.group(1)) % 360


def _infer_symbol_library_reference(symbol_instance: SymbolInstance, symbol_definition: SymbolDefinition) -> Optional[str]:
    explicit_model_file = _clean_optional_text(symbol_instance.attributes.get("ModelFile", ""))
    if explicit_model_file != "":
        return _library_basename(explicit_model_file)
    explicit_spice_model = _clean_optional_text(symbol_instance.attributes.get("SpiceModel", ""))
    if _looks_like_library_reference(explicit_spice_model):
        return _library_basename(explicit_spice_model)
    if symbol_definition.model_file != "":
        return _library_basename(symbol_definition.model_file)
    if _looks_like_library_reference(symbol_definition.default_spice_model):
        return _library_basename(symbol_definition.default_spice_model)
    if symbol_instance.symbol_name.replace("\\", "/").lower() == "opamps/opamp":
        return "opamp.sub"
    return None


def _looks_like_library_reference(value: str) -> bool:
    lowered_value = value.lower()
    return lowered_value.endswith(".lib") or lowered_value.endswith(".sub")


def _library_basename(value: str) -> str:
    normalized_value = value.replace("\\", "/")
    return normalized_value.split("/")[-1]


def _resolve_library_relative_path(library_reference: str, library_lookup: Mapping[str, str]) -> Optional[str]:
    normalized_reference = library_reference.replace("\\", "/").lstrip("./").lower()
    for lookup_key in (
        normalized_reference,
        normalized_reference[4:] if normalized_reference.startswith("lib/") else normalized_reference,
        normalized_reference.split("/")[-1],
    ):
        if lookup_key in library_lookup:
            return library_lookup[lookup_key]
    return None


def _build_library_line(windows_root_path: str, relative_library_path: str) -> str:
    normalized_relative_path = relative_library_path.replace("/", "\\")
    normalized_windows_root_path = windows_root_path.rstrip("\\/")
    if normalized_windows_root_path == "":
        return f".lib {normalized_relative_path}"
    return f".lib {normalized_windows_root_path}\\{normalized_relative_path}"


def _dedupe_lines(lines: Iterable[str]) -> Tuple[str, ...]:
    seen_lines: Set[str] = set()
    deduped_lines: List[str] = []
    for line in lines:
        stripped_line = line.strip()
        if stripped_line == "":
            continue
        normalized_line = stripped_line.lower()
        if normalized_line in seen_lines:
            continue
        seen_lines.add(normalized_line)
        deduped_lines.append(stripped_line)
    return tuple(deduped_lines)


def _write_netlist_file(filepath: str, lines: Sequence[str]) -> Tuple[bool, str]:
    output_path_result = _asc._coerce_path(filepath)
    if not output_path_result[0]:
        return False, "INVALID_OUTPUT_PATH"
    output_path = Path(output_path_result[1])
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        return False, "WRITE_ERROR"
    return True, "OK"


def _line_number_from_message(message: str, default_line: int) -> int:
    line_match = _LINE_NUMBER_PATTERN.search(message)
    if line_match is None:
        return default_line
    return int(line_match.group("line"))


def _symbol_info_error_to_conversion_result(message: str) -> ConversionResult:
    if "Unable to locate LTspice symbol file" in message:
        return False, "UNKNOWN_SYMBOL", _line_number_from_message(message, 0)
    if "Unable to parse LTspice ASC file!" in message:
        return False, "ASC_PARSE_ERROR", _line_number_from_message(message, 0)
    return False, "ASC_PARSE_ERROR", _line_number_from_message(message, 0)


def _message_without_line_number(message: str) -> str:
    return _LINE_NUMBER_PATTERN.sub("", message).strip()


def _coerce_path_success(filepath: str) -> bool:
    path_result = _asc._coerce_path(filepath)
    return bool(path_result[0])
