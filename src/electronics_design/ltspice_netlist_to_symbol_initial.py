"""Convert LTspice netlists into initial symbol JSON records."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Dict
from typing import List
from typing import Mapping
from typing import Optional
from typing import Sequence
from typing import Set
from typing import Tuple

from . import ltspice_asc as _asc
from . import ltspice_asc_to_netlist as _asc_to_netlist
from . import ltspice_net as _net

ConversionResult = Tuple[bool, str, int]

_OK_RESULT: ConversionResult = (True, "OK", 0)
_LINE_NUMBER_PATTERN = re.compile(r"Line (?P<line>\d+)")
_MODELFILE_HINT_PATTERN = re.compile(
    r"ModelFile attribute of instance (?P<instances>.+?) \((?P<symbol_path>[^)]+\.asy)\)",
    re.IGNORECASE,
)
_MODEL_DIRECTIVE_PATTERN = re.compile(r"^\.model\s+(?P<name>\S+)\s+(?P<body>.+)$", re.IGNORECASE)
_SUBCKT_DIRECTIVE_PATTERN = re.compile(r"^\.subckt\s+(?P<name>\S+)", re.IGNORECASE)
_INCLUDE_DIRECTIVE_PATTERN = re.compile(r"^\.(?:include|lib)\s+(?P<reference>.+)$", re.IGNORECASE)


@dataclass(frozen=True)
class LogicalCodeLine:
    line_number: int
    kind: str
    text: str


@dataclass(frozen=True)
class ModelDefinition:
    kind: str
    parameters_text: str
    source_path: str
    type_hint: str


@dataclass(frozen=True)
class LibraryContext:
    models: Mapping[str, ModelDefinition]
    subcircuits: Mapping[str, str]
    included_libraries: Tuple[str, ...]


def ltspice_netlist_to_symbol_initial(
    netlist_filepath: str,
    symbol_json_filepath_out: str,
    convert_settings: Mapping[str, object],
) -> ConversionResult:
    if not isinstance(convert_settings, Mapping):
        return False, "INVALID_CONVERT_SETTINGS", 0
    voltage_must_have_dc = _net._resolve_voltage_must_have_dc(convert_settings)
    if voltage_must_have_dc is None:
        return False, "INVALID_CONVERT_SETTINGS", 0
    if not _coerce_path_success(symbol_json_filepath_out):
        return False, "INVALID_OUTPUT_PATH", 0
    _net.is_valid_ltspice_netlist_file(netlist_filepath)
    format_validation_result = _net.is_valid_ltspice_netlist_format(netlist_filepath)
    if not format_validation_result[0]:
        return False, "INVALID_NETLIST_FILE", _line_number_from_message(format_validation_result[1], 0)
    read_result = _net._read_text_file_lines(netlist_filepath)
    if not read_result[0]:
        return False, "NETLIST_READ_ERROR", 0
    logical_lines = _collect_logical_code_lines(read_result[1])
    search_roots = _resolve_search_roots_for_netlist(netlist_filepath, convert_settings)
    library_context = _build_library_context(netlist_filepath, logical_lines, search_roots)
    coupled_inductors = _collect_coupled_inductor_names(logical_lines)
    symbol_path_lookup = _asc_to_netlist._build_symbol_filepath_lookup(search_roots)
    comment_symbol_hints = _extract_comment_symbol_hints(read_result[1])
    symbol_initial = _build_symbol_initial_records(
        logical_lines,
        library_context,
        coupled_inductors,
        symbol_path_lookup,
        {},
        comment_symbol_hints,
        voltage_must_have_dc,
    )
    write_result = _write_symbol_json_file(symbol_json_filepath_out, symbol_initial)
    if not write_result[0]:
        return False, write_result[1], 0
    return _OK_RESULT


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


def _resolve_search_roots_for_netlist(netlist_filepath: str, convert_settings: Mapping[str, object]) -> Tuple[str, ...]:
    search_roots = list(_asc_to_netlist._resolve_search_roots(convert_settings))
    for candidate_path in _discover_local_search_roots(netlist_filepath):
        if candidate_path not in search_roots:
            search_roots.append(candidate_path)
    return tuple(search_roots)


def _discover_local_search_roots(filepath: str) -> Tuple[str, ...]:
    coerced_path_result = _asc._coerce_path(filepath)
    if not coerced_path_result[0]:
        return ()
    source_path = Path(coerced_path_result[1]).resolve()
    if not source_path.exists():
        return ()
    search_roots = [str(source_path.parent)]
    for parent in source_path.parents:
        if parent == source_path.parent:
            continue
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            search_roots.append(str(parent))
            break
    return tuple(search_roots)


def _build_library_context(
    netlist_filepath: str,
    logical_lines: Sequence[LogicalCodeLine],
    search_roots: Sequence[str],
) -> LibraryContext:
    library_lookup = _asc_to_netlist._build_library_lookup(search_roots)
    models: Dict[str, ModelDefinition] = {}
    subcircuits: Dict[str, str] = {}
    included_libraries: List[str] = []
    visited_libraries: Set[str] = set()
    for logical_line in logical_lines:
        if logical_line.kind != "directive":
            continue
        _collect_directive_metadata(
            logical_line.text,
            netlist_filepath,
            search_roots,
            library_lookup,
            models,
            subcircuits,
            included_libraries,
            visited_libraries,
        )
    return LibraryContext(
        models=models,
        subcircuits=subcircuits,
        included_libraries=tuple(dict.fromkeys(included_libraries)),
    )


def _collect_directive_metadata(
    directive_text: str,
    origin_filepath: str,
    search_roots: Sequence[str],
    library_lookup: Mapping[str, str],
    models: Dict[str, ModelDefinition],
    subcircuits: Dict[str, str],
    included_libraries: List[str],
    visited_libraries: Set[str],
) -> None:
    model_definition = _parse_model_definition(directive_text, origin_filepath)
    if model_definition is not None:
        models.setdefault(model_definition[0], model_definition[1])
        return
    subcircuit_name = _parse_subcircuit_name(directive_text)
    if subcircuit_name is not None:
        subcircuits.setdefault(subcircuit_name, origin_filepath)
        return
    include_reference = _parse_include_reference(directive_text)
    if include_reference is None:
        return
    included_libraries.append(_library_basename(include_reference))
    resolved_library_path = _resolve_library_reference_path(include_reference, origin_filepath, search_roots, library_lookup)
    if resolved_library_path is None:
        return
    normalized_library_path = str(Path(resolved_library_path).resolve())
    if normalized_library_path in visited_libraries:
        return
    visited_libraries.add(normalized_library_path)
    library_lines = _read_library_text_lines(resolved_library_path)
    if library_lines is None:
        return
    for logical_line in _collect_logical_code_lines(library_lines):
        if logical_line.kind != "directive":
            continue
        _collect_directive_metadata(
            logical_line.text,
            resolved_library_path,
            search_roots,
            library_lookup,
            models,
            subcircuits,
            included_libraries,
            visited_libraries,
        )


def _read_library_text_lines(filepath: str) -> Optional[List[str]]:
    """Read text and UTF-16 LTspice libraries without assuming an OS path."""

    try:
        raw_bytes = Path(filepath).read_bytes()
    except OSError:
        return None
    try:
        if raw_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = raw_bytes.decode("utf-16")
        elif b"\x00" in raw_bytes[:256]:
            text = raw_bytes.decode("utf-16-le")
        else:
            text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1")
    return text.splitlines()


def _parse_model_definition(directive_text: str, source_path: str) -> Optional[Tuple[str, ModelDefinition]]:
    model_match = _MODEL_DIRECTIVE_PATTERN.match(directive_text.strip())
    if model_match is None:
        return None
    model_name = model_match.group("name").strip()
    body_text = model_match.group("body").strip()
    kind_match = re.match(r"(?P<kind>[A-Za-z0-9_]+)", body_text)
    if kind_match is None:
        return None
    kind = kind_match.group("kind").upper()
    parameters_text = body_text[kind_match.end() :].strip()
    type_hint = ""
    if kind == "D":
        diode_type_match = re.search(r"\btype\s*=\s*(?P<type>[A-Za-z0-9_]+)", parameters_text, re.IGNORECASE)
        if diode_type_match is not None:
            type_hint = diode_type_match.group("type").upper()
    if kind == "VDMOS" and re.search(r"\bpchan\b", parameters_text, re.IGNORECASE) is not None:
        type_hint = "PCHAN"
    model_definition = ModelDefinition(
        kind=kind,
        parameters_text=parameters_text,
        source_path=source_path,
        type_hint=type_hint,
    )
    return model_name.lower(), model_definition


def _parse_subcircuit_name(directive_text: str) -> Optional[str]:
    subckt_match = _SUBCKT_DIRECTIVE_PATTERN.match(directive_text.strip())
    if subckt_match is None:
        return None
    return subckt_match.group("name").strip().lower()


def _parse_include_reference(directive_text: str) -> Optional[str]:
    include_match = _INCLUDE_DIRECTIVE_PATTERN.match(directive_text.strip())
    if include_match is None:
        return None
    reference_text = include_match.group("reference").strip()
    if reference_text == "":
        return None
    return reference_text.strip().strip("\"'")


def _resolve_library_reference_path(
    library_reference: str,
    origin_filepath: str,
    search_roots: Sequence[str],
    library_lookup: Mapping[str, str],
) -> Optional[str]:
    normalized_reference = os.path.expanduser(library_reference.strip())
    if normalized_reference == "":
        return None
    direct_path = Path(normalized_reference)
    if direct_path.exists():
        return str(direct_path)
    origin_parent = Path(origin_filepath).resolve().parent
    relative_origin_path = origin_parent / normalized_reference
    if relative_origin_path.exists():
        return str(relative_origin_path)
    relative_reference = normalized_reference.replace("\\", "/").lstrip("./")
    resolved_relative_path = _asc_to_netlist._resolve_library_relative_path(relative_reference, library_lookup)
    if resolved_relative_path is not None:
        for search_root in search_roots:
            candidate_path = Path(search_root) / resolved_relative_path
            if candidate_path.exists():
                return str(candidate_path)
    basename_reference = _library_basename(normalized_reference)
    resolved_basename_path = _asc_to_netlist._resolve_library_relative_path(basename_reference, library_lookup)
    if resolved_basename_path is not None:
        for search_root in search_roots:
            candidate_path = Path(search_root) / resolved_basename_path
            if candidate_path.exists():
                return str(candidate_path)
    for search_root in search_roots:
        candidate_path = Path(search_root) / relative_reference
        if candidate_path.exists():
            return str(candidate_path)
    return None


def _collect_coupled_inductor_names(logical_lines: Sequence[LogicalCodeLine]) -> Set[str]:
    coupled_inductors: Set[str] = set()
    for logical_line in logical_lines:
        if logical_line.kind != "device":
            continue
        tokens = logical_line.text.split()
        if not tokens or tokens[0][0].upper() != "K" or len(tokens) < 4:
            continue
        for token in tokens[1:-1]:
            coupled_inductors.add(token.lower())
    return coupled_inductors


def _extract_comment_symbol_hints(lines: Sequence[str]) -> Dict[str, str]:
    hints: Dict[str, str] = {}
    for raw_line in lines:
        stripped_line = raw_line.strip()
        if not stripped_line.startswith("*"):
            continue
        hint_match = _MODELFILE_HINT_PATTERN.search(stripped_line)
        if hint_match is None:
            continue
        symbol_name = _symbol_relative_path_from_hint(hint_match.group("symbol_path"))
        for raw_instance in hint_match.group("instances").split(","):
            normalized_instance = _normalize_instance_name(raw_instance.strip())
            if normalized_instance != "":
                hints[normalized_instance] = symbol_name
    return hints


def _symbol_relative_path_from_hint(raw_symbol_path: str) -> str:
    """Return a portable symbol stem from an LTspice path hint."""
    normalized_path = raw_symbol_path.replace("\\", "/")
    return Path(normalized_path).stem


def _build_symbol_initial_records(
    logical_lines: Sequence[LogicalCodeLine],
    library_context: LibraryContext,
    coupled_inductors: Set[str],
    symbol_path_lookup: Mapping[str, str],
    asc_symbol_hints: Mapping[str, Mapping[str, object]],
    comment_symbol_hints: Mapping[str, str],
    voltage_must_have_dc: bool,
) -> Dict[str, Dict[str, object]]:
    symbol_records: Dict[str, Dict[str, object]] = {}
    for logical_line in logical_lines:
        if logical_line.kind != "device":
            continue
        tokens = _net._normalize_voltage_source_tokens(
            logical_line.text.split(),
            voltage_must_have_dc,
        )
        if not tokens:
            continue
        prefix = tokens[0][0].upper()
        if prefix == "K":
            continue
        instance_name = _normalize_instance_name(tokens[0])
        if instance_name == "":
            continue
        template_entry = asc_symbol_hints.get(instance_name, {})
        record = {
            "SYMBOL": _resolve_symbol_name(
                prefix,
                tokens,
                instance_name,
                template_entry,
                comment_symbol_hints,
                symbol_path_lookup,
                library_context,
                coupled_inductors,
            ),
            "X": 0,
            "Y": 0,
            "ORIENTATION": "",
            "RECTANGLE": [],
            "PINS": [],
        }
        _add_netlist_fields(record, prefix, tokens, template_entry, library_context, coupled_inductors)
        symbol_records[instance_name] = record
    _apply_circuit_symbol_heuristics(symbol_records, logical_lines, library_context)
    return symbol_records


def _apply_circuit_symbol_heuristics(
    symbol_records: Dict[str, Dict[str, object]],
    logical_lines: Sequence[LogicalCodeLine],
    library_context: LibraryContext,
) -> None:
    """Apply topology-based symbol choices that a flat netlist omits."""

    transistor_collectors: Set[str] = set()
    transistor_bases: Set[str] = set()
    capacitor_nodes: Dict[str, Tuple[str, str]] = {}
    positive_supply_nodes: Set[str] = set()
    passive_neighbors: Dict[str, Set[str]] = {}
    unresolved_bjts_by_model: Dict[str, List[Tuple[str, str]]] = {}
    for logical_line in logical_lines:
        if logical_line.kind != "device":
            continue
        tokens = logical_line.text.split()
        if not tokens:
            continue
        instance_name = _normalize_instance_name(tokens[0])
        node_result = _net._extract_nodes(tokens)
        if not node_result[0]:
            continue
        nodes = tuple(str(node) for node in node_result[1])
        prefix = tokens[0][0].upper()
        if prefix == "Q" and len(nodes) >= 2:
            transistor_collectors.add(nodes[0])
            transistor_bases.add(nodes[1])
            if len(nodes) >= 3:
                model_index = 5 if len(tokens) >= 6 else 4
                model_name = tokens[model_index].lower() if model_index < len(tokens) else ""
                if _model_definition_for_name(model_name, library_context) is None:
                    unresolved_bjts_by_model.setdefault(model_name, []).append((instance_name, nodes[2]))
        elif prefix == "C" and len(nodes) >= 2:
            capacitor_nodes[instance_name] = (nodes[0], nodes[1])
        elif prefix in {"R", "L"} and len(nodes) >= 2:
            passive_neighbors.setdefault(nodes[0], set()).add(nodes[1])
            passive_neighbors.setdefault(nodes[1], set()).add(nodes[0])
        elif prefix == "V" and len(nodes) >= 2 and nodes[1].upper() in {"0", "GND"}:
            positive_supply_nodes.add(nodes[0])

    collector_to_base_capacitors = [
        instance_name
        for instance_name, (first_node, second_node) in capacitor_nodes.items()
        if (
            first_node in transistor_collectors and second_node in transistor_bases
        ) or (
            second_node in transistor_collectors and first_node in transistor_bases
        )
    ]
    if len(collector_to_base_capacitors) >= 2:
        for instance_name in collector_to_base_capacitors:
            symbol_records[instance_name]["SYMBOL"] = "polcap"

    for model_instances in unresolved_bjts_by_model.values():
        model_has_positive_emitter = any(
            emitter_node in positive_supply_nodes
            or bool(passive_neighbors.get(emitter_node, set()) & positive_supply_nodes)
            for _instance_name, emitter_node in model_instances
        )
        if not model_has_positive_emitter:
            continue
        for instance_name, _emitter_node in model_instances:
            if symbol_records.get(instance_name, {}).get("SYMBOL") == "npn":
                symbol_records[instance_name]["SYMBOL"] = "pnp"


def _resolve_symbol_name(
    prefix: str,
    tokens: Sequence[str],
    instance_name: str,
    template_entry: Mapping[str, object],
    comment_symbol_hints: Mapping[str, str],
    symbol_path_lookup: Mapping[str, str],
    library_context: LibraryContext,
    coupled_inductors: Set[str],
) -> str:
    template_symbol_name = _clean_optional_text(template_entry.get("SYMBOL", ""))
    if template_symbol_name != "":
        return template_symbol_name
    if prefix == "A":
        symbol_basename = tokens[-1].lower()
        resolved_symbol_name = _resolve_exact_symbol_basename(symbol_basename, symbol_path_lookup)
        return resolved_symbol_name if resolved_symbol_name is not None else symbol_basename
    if prefix == "B":
        return "bi" if tokens[3].strip().upper().startswith("I=") else "bv"
    if prefix == "C":
        return "cap"
    if prefix == "D":
        return _resolve_diode_symbol_name(tokens[3], library_context)
    if prefix == "E":
        return "Gain" if _net._is_two_node_behavioral_controlled_source(prefix, tokens) else "e"
    if prefix == "F":
        return "f"
    if prefix == "I":
        return "current"
    if prefix == "J":
        return _resolve_jfet_symbol_name(tokens[4], library_context)
    if prefix == "L":
        if tokens[0].lower() in coupled_inductors or (len(tokens) > 3 and tokens[3].upper() == "L"):
            return "ind2"
        return "ind"
    if prefix == "M":
        return _resolve_mosfet_symbol_name(tokens[5], library_context)
    if prefix == "Q":
        model_token_index = 5 if len(tokens) >= 6 else 4
        return _resolve_bjt_symbol_name(tokens[model_token_index], library_context)
    if prefix == "R":
        return "res"
    if prefix == "S":
        return "sw"
    if prefix == "T":
        return "tline"
    if prefix == "V":
        return "voltage"
    if prefix == "X":
        comment_symbol_name = comment_symbol_hints.get(instance_name, "")
        if comment_symbol_name != "":
            return _canonical_symbol_stem(comment_symbol_name)
        subcircuit_name = _extract_x_subcircuit_name(tokens)
        exact_symbol_name = _resolve_exact_symbol_basename(subcircuit_name, symbol_path_lookup)
        if exact_symbol_name is not None:
            return exact_symbol_name
        inferred_symbol_name = _infer_x_symbol_name_from_library_context(subcircuit_name, symbol_path_lookup, library_context)
        if inferred_symbol_name is not None:
            return inferred_symbol_name
        return subcircuit_name
    return prefix.lower()


def _resolve_diode_symbol_name(model_name: str, library_context: LibraryContext) -> str:
    if model_name.upper() == "D":
        return "diode"
    model_definition = _model_definition_for_name(model_name, library_context)
    if model_definition is None:
        return "diode"
    if model_definition.type_hint == "SCHOTTKY":
        return "schottky"
    if model_definition.type_hint == "ZENER":
        return "zener"
    if model_definition.type_hint == "LED":
        return "LED"
    return "diode"


def _resolve_jfet_symbol_name(model_name: str, library_context: LibraryContext) -> str:
    model_upper = model_name.upper()
    if model_upper == "PJF":
        return "pjf"
    if model_upper == "NJF":
        return "njf"
    model_definition = _model_definition_for_name(model_name, library_context)
    if model_definition is None:
        return "njf"
    return "pjf" if model_definition.kind == "PJF" else "njf"


def _resolve_mosfet_symbol_name(model_name: str, library_context: LibraryContext) -> str:
    model_upper = model_name.upper()
    if model_upper == "PMOS":
        return "pmos"
    if model_upper == "NMOS":
        return "nmos"
    model_definition = _model_definition_for_name(model_name, library_context)
    if model_definition is None:
        return "nmos"
    if model_definition.kind == "PMOS":
        return "pmos"
    if model_definition.kind == "VDMOS" and model_definition.type_hint == "PCHAN":
        return "pmos"
    return "nmos"


def _resolve_bjt_symbol_name(model_name: str, library_context: LibraryContext) -> str:
    model_upper = model_name.upper()
    if model_upper == "PNP":
        return "pnp"
    if model_upper == "NPN":
        return "npn"
    model_definition = _model_definition_for_name(model_name, library_context)
    if model_definition is None:
        return "npn"
    return "pnp" if model_definition.kind == "PNP" else "npn"


def _model_definition_for_name(
    model_name: str,
    library_context: LibraryContext,
) -> Optional[ModelDefinition]:
    normalized_name = model_name.lower()
    exact_definition = library_context.models.get(normalized_name)
    if exact_definition is not None:
        return exact_definition
    # Some LTspice device selectors omit a package suffix present in the
    # library model name.  Accept a unique prefix match, but never guess when
    # multiple model definitions could apply.
    prefix_matches = [
        definition
        for candidate_name, definition in library_context.models.items()
        if candidate_name.startswith(normalized_name) or normalized_name.startswith(candidate_name)
    ]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    return None


def _extract_x_subcircuit_name(tokens: Sequence[str]) -> str:
    node_extract_result = _net._extract_nodes(tokens)
    if not node_extract_result[0]:
        return tokens[-1]
    subcircuit_index = 1 + len(node_extract_result[1])
    if subcircuit_index >= len(tokens):
        return tokens[-1]
    return tokens[subcircuit_index]


def _resolve_exact_symbol_basename(symbol_name: str, symbol_path_lookup: Mapping[str, str]) -> Optional[str]:
    resolved_symbol_filepath = _asc_to_netlist._resolve_symbol_filepath(symbol_name, symbol_path_lookup)
    if resolved_symbol_filepath is None:
        return None
    relative_name = _symbol_relative_path_from_lookup(symbol_name, symbol_path_lookup)
    if relative_name is not None:
        return _canonical_symbol_stem(relative_name)
    return _canonical_symbol_stem(Path(resolved_symbol_filepath).stem)


def _canonical_symbol_stem(symbol_name: str) -> str:
    if symbol_name.lower() == "universalopamp2":
        return "UniversalOpamp2"
    return symbol_name


def _symbol_relative_path_from_lookup(symbol_name: str, symbol_path_lookup: Mapping[str, str]) -> Optional[str]:
    """Return a portable symbol stem when a library lookup can resolve it."""
    normalized_stem = symbol_name.replace("\\", "/").split("/")[-1].lower()
    best_key: Optional[str] = None
    best_depth = 0
    for lookup_key in symbol_path_lookup:
        key_path = lookup_key.replace("\\", "/")
        parts = key_path.split("/")
        sym_index = -1
        for index in range(len(parts) - 1, -1, -1):
            if parts[index].lower() == "sym" and index > 0 and parts[index - 1].lower() == "lib":
                sym_index = index
                break
        if sym_index == -1:
            continue
        relative_parts = parts[sym_index + 1:]
        if not relative_parts:
            continue
        key_stem = Path("/".join(relative_parts)).stem.lower()
        if key_stem != normalized_stem:
            continue
        depth = len(relative_parts)
        if depth > best_depth:
            best_depth = depth
            best_key = "/".join(relative_parts)
    if best_key is None:
        return None
    return Path(best_key).stem


def _infer_x_symbol_name_from_library_context(
    subcircuit_name: str,
    symbol_path_lookup: Mapping[str, str],
    library_context: LibraryContext,
) -> Optional[str]:
    if subcircuit_name == "":
        return None
    lowered_subcircuit_name = subcircuit_name.lower()
    if lowered_subcircuit_name in library_context.subcircuits:
        exact_symbol_name = _resolve_exact_symbol_basename(subcircuit_name, symbol_path_lookup)
        if exact_symbol_name is not None:
            return exact_symbol_name
    return None


def _add_netlist_fields(
    record: Dict[str, object],
    prefix: str,
    tokens: Sequence[str],
    template_entry: Mapping[str, object],
    library_context: LibraryContext,
    coupled_inductors: Set[str],
) -> None:
    if prefix == "A":
        _apply_template_field(record, template_entry, "TYPE")
        return
    if prefix == "B":
        record["VALUE"] = " ".join(tokens[3:])
        _apply_template_field(record, template_entry, "TYPE")
        return
    if prefix in {"C", "I", "R", "V"}:
        _add_two_node_value_and_spiceline(
            record,
            tokens,
            template_entry,
            omit_ac_payload=(prefix == "V"),
            value_assignment_key=prefix,
        )
        _apply_template_field(record, template_entry, "TYPE")
        return
    if prefix == "D":
        diode_model_name = tokens[3]
        if diode_model_name.upper() != "D":
            record["VALUE"] = diode_model_name
        symbol_name = str(record.get("SYMBOL", "")).lower()
        if symbol_name == "schottky" or (symbol_name == "zener" and diode_model_name.upper().startswith("BZX")):
            record["TYPE"] = "diode"
        _apply_template_field(record, template_entry, "TYPE")
        return
    if prefix == "E":
        if _net._is_two_node_behavioral_controlled_source(prefix, tokens):
            _add_optional_text_field(record, "SPICELINE", " ".join(tokens[4:]))
        else:
            _add_optional_text_field(record, "VALUE", tokens[5] if len(tokens) > 5 else "")
            _add_optional_text_field(record, "SPICELINE", " ".join(tokens[6:]))
        _apply_template_field(record, template_entry, "TYPE")
        return
    if prefix == "F":
        record["VALUE"] = " ".join(tokens[3:])
        _apply_template_field(record, template_entry, "TYPE")
        return
    if prefix == "J":
        _add_optional_text_field(record, "VALUE", "" if tokens[4].upper() in {"NJF", "PJF"} else tokens[4])
        _apply_template_field(record, template_entry, "TYPE")
        return
    if prefix == "L":
        _add_two_node_value_and_spiceline(
            record,
            tokens,
            template_entry,
            omit_ac_payload=False,
            value_assignment_key=prefix,
        )
        if record["SYMBOL"] == "ind2" or tokens[0].lower() in coupled_inductors:
            record.setdefault("TYPE", "ind")
        _apply_template_field(record, template_entry, "TYPE")
        return
    if prefix == "M":
        _add_optional_text_field(record, "VALUE", tokens[5] if len(tokens) > 5 else "")
        _apply_template_field(record, template_entry, "TYPE")
        return
    if prefix == "Q":
        model_token_index = 5 if len(tokens) >= 6 else 4
        model_name = tokens[model_token_index]
        if model_name.upper() not in {"NPN", "PNP"}:
            record["VALUE"] = model_name
        _apply_template_field(record, template_entry, "TYPE")
        return
    if prefix == "S":
        model_name = tokens[5] if len(tokens) > 5 else ""
        if model_name.upper() != "SW":
            _add_optional_text_field(record, "VALUE", model_name)
        _apply_template_field(record, template_entry, "TYPE")
        return
    if prefix == "T":
        _apply_template_field(record, template_entry, "TYPE")
        return
    if prefix == "X":
        _apply_template_field(record, template_entry, "TYPE")
        return
    _apply_template_field(record, template_entry, "TYPE")


def _add_two_node_value_and_spiceline(
    record: Dict[str, object],
    tokens: Sequence[str],
    template_entry: Mapping[str, object],
    omit_ac_payload: bool,
    value_assignment_key: str,
) -> None:
    if len(tokens) <= 3:
        _apply_template_field(record, template_entry, "TYPE")
        return
    raw_value, raw_spiceline = _split_value_and_spiceline(tokens[3:], omit_ac_payload, value_assignment_key)
    if raw_value == "":
        _apply_template_field(record, template_entry, "TYPE")
        return
    if raw_value.upper() not in {"R", "L"}:
        _add_optional_text_field(record, "VALUE", raw_value)
    _add_optional_text_field(record, "SPICELINE", raw_spiceline)
    _apply_template_field(record, template_entry, "TYPE")


def _split_value_and_spiceline(
    payload_tokens: Sequence[str],
    omit_ac_payload: bool,
    value_assignment_key: str,
) -> Tuple[str, str]:
    if not payload_tokens:
        return "", ""
    effective_tokens = list(payload_tokens)
    if omit_ac_payload:
        for index, token in enumerate(effective_tokens):
            if token.upper() == "AC":
                effective_tokens = effective_tokens[:index]
                break
    if not effective_tokens:
        return "", ""
    if effective_tokens[0].upper().startswith(f"{value_assignment_key.upper()}="):
        return " ".join(effective_tokens).strip(), ""
    parameter_start_index = len(effective_tokens)
    for index, token in enumerate(effective_tokens):
        if "=" in token:
            parameter_start_index = index
            break
    value_tokens = effective_tokens[:parameter_start_index]
    spiceline_tokens = effective_tokens[parameter_start_index:]
    return " ".join(value_tokens).strip(), " ".join(spiceline_tokens).strip()


def _apply_template_field(record: Dict[str, object], template_entry: Mapping[str, object], key: str) -> None:
    template_value = template_entry.get(key, "")
    if key not in template_entry or key in record:
        return
    if template_value is None:
        return
    if isinstance(template_value, str) and template_value.strip() == "":
        return
    if isinstance(template_value, list) and not template_value:
        return
    if isinstance(template_value, tuple) and not template_value:
        return
    record[key] = template_value


def _add_optional_text_field(record: Dict[str, object], key: str, raw_value: object) -> None:
    clean_value = _clean_optional_text(raw_value)
    if clean_value != "":
        record[key] = clean_value


def _clean_optional_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_instance_name(instance_token: str) -> str:
    clean_token = instance_token.strip()
    if clean_token == "":
        return ""
    if "§" in clean_token:
        return clean_token.split("§", 1)[1].strip()
    return clean_token


def _library_basename(value: str) -> str:
    return value.replace("\\", "/").split("/")[-1]


def _write_symbol_json_file(filepath: str, symbol_records: Mapping[str, Mapping[str, object]]) -> Tuple[bool, str]:
    output_path_result = _asc._coerce_path(filepath)
    if not output_path_result[0]:
        return False, "INVALID_OUTPUT_PATH"
    output_path = Path(output_path_result[1])
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(symbol_records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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
