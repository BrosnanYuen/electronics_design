"""KiCad symbol library (`.kicad_sym`) validation helpers and public API functions."""  # Document the module purpose.

# The validation profile in this module follows the KiCad s-expression symbol
# library file format (see kicad_docs/sexpr-symbol-lib.md in this repository)
# and mirrors the symbol shape produced by the kicad-tools project's
# `kicad_tools.schema.library` module (MIT licensed, Copyright (c) 2024 RJ
# Walters) and the KiCAD-MCP-Server project's `SymbolCreator` (MIT licensed).
# The pin electrical types and graphic styles accepted below are copied from
# those same two MIT-licensed reference projects. Parsing is handled by the
# vendored `kicad_sexp_parser` module copied from kicad-tools (MIT licensed,
# Copyright (c) 2024 RJ Walters).

from __future__ import annotations  # Postpone annotation evaluation for forward references.

import re  # Validate version tokens with regular expressions.
from typing import List  # Type collected node lists.
from typing import Optional  # Type optional parsed structure results.
from typing import Tuple  # Type tuple-based helper results.

from .kicad_sch import _first_atom_value  # Reuse the shared atom extraction helper.
from .kicad_sch import _format_line_message  # Reuse the shared error message builder.
from .kicad_sch import _node_line_or  # Reuse the shared node line helper.
from .kicad_sch import _parse_sch_text  # Reuse the shared text-to-S-expression parser wrapper.
from .kicad_sch import _read_text_file_lines  # Reuse the shared safe file reader.
from .kicad_sch import ValidationResult  # Reuse the shared public return shape.
from .kicad_sexp_parser import SExp  # Type parsed symbol nodes.

_VERSION_PATTERN = re.compile(r"^\d{8}$")  # Match KiCad version tokens in YYYYMMDD date format.

_YES_NO = frozenset({"yes", "no"})  # Collect the allowed values for in_bom and on_board flags.

_VALID_PIN_TYPES = frozenset(  # Collect the pin electrical types accepted by KiCad symbol libraries.
    {
        "input",  # Pin is an input.
        "output",  # Pin is an output.
        "bidirectional",  # Pin can be both input and output.
        "tri_state",  # Pin is a tri-state output.
        "passive",  # Pin is electrically passive.
        "free",  # Pin is not internally connected.
        "unspecified",  # Pin has no specified electrical type.
        "power_in",  # Pin is a power input.
        "power_out",  # Pin is a power output.
        "open_collector",  # Pin is an open collector output.
        "open_emitter",  # Pin is an open emitter output.
        "no_connect",  # Pin has no electrical connection.
    }
)  # Finish the valid pin electrical type set.

_VALID_PIN_SHAPES = frozenset(  # Collect the pin graphic styles accepted by KiCad symbol libraries.
    {
        "line",  # Ordinary line pin.
        "inverted",  # Inverted pin.
        "clock",  # Clock pin.
        "inverted_clock",  # Inverted clock pin.
        "input_low",  # Active-low input pin.
        "clock_low",  # Active-low clock pin.
        "output_low",  # Active-low output pin.
        "edge_clock_high",  # Edge-triggered clock pin.
        "non_logic",  # Non-logic pin.
        # `falling_edge_clock` is accepted as a legacy spelling emitted by
        # some third-party generators (KiCAD-MCP-Server).
        "falling_edge_clock",  # Legacy edge-clock spelling.
    }
)  # Finish the valid pin graphic style set.

_MANDATORY_PROPERTY_KEYS = ("Reference", "Value", "Footprint", "Datasheet")  # Define the properties required on every parent symbol.

_REQUIRED_HEADER_SECTIONS = ("version", "generator")  # Define the header sections that must appear exactly once in a symbol library.


def is_valid_kicad_symbol_file(filepath: str) -> ValidationResult:  # Validate a KiCad symbol library file structure.
    """Validate a KiCad symbol library (`.kicad_sym`) file.

    The validator checks the file access, S-expression syntax, the library
    header (root, version, generator), the symbol entries (name, in_bom,
    on_board, mandatory properties, pin structure), and the closing line of
    the file. It implements a project-specific structural profile over the
    KiCad symbol library format; it does not attempt full semantic symbol
    validation.
    """
    read_result = _read_text_file_lines(filepath)  # Load the file lines through the shared safe reader.
    if not read_result[0]:  # Stop immediately when the shared file reader reports an error.
        return False, read_result[2]  # Propagate the exact file access error message.
    lines = read_result[1]  # Read the loaded source lines.
    last_nonblank_line_number = 1  # Track the last nonblank line so missing-section failures have a useful location.
    for line_number, raw_line in enumerate(lines, start=1):  # Walk every line with a one-based line number.
        if raw_line.strip() == "":  # Ignore blank lines when locating the final nonblank line.
            continue  # Move to the next source line.
        last_nonblank_line_number = line_number  # Update the last nonblank line marker.
    parse_result = _parse_sch_text("\n".join(lines))  # Reuse the shared parser so symbol validation implies spacing validity.
    if not parse_result[0]:  # Stop when the file is not even valid S-expression syntax.
        return False, _format_line_message("Line format/spacing is invalid!", parse_result[2])  # Report the parse failure so callers fix syntax before symbol checks.
    root = parse_result[1]  # Read the parsed root node.
    header_result = _validate_symbol_lib_header(root)  # Validate the root node header structure.
    if not header_result[0]:  # Stop when a header problem is detected.
        return False, _format_line_message("Header information is invalid!", header_result[1])  # Return the required header error message.
    symbols_result = _validate_symbol_nodes(root, last_nonblank_line_number)  # Validate the symbol entries carried by the library.
    if not symbols_result[0]:  # Stop when a symbol structure problem is detected.
        return False, _format_line_message("Symbol information is invalid!", symbols_result[1])  # Return the required symbol error message.
    final_line = lines[last_nonblank_line_number - 1].strip()  # Read the stripped final nonblank source line.
    if not final_line.endswith(")"):  # Require the file to close with the root expression terminator.
        return False, _format_line_message("Footer information is invalid!", last_nonblank_line_number)  # Report the final nonblank line.
    return True, ""  # Return success when the symbol library validates successfully.


def _validate_symbol_lib_header(root: Optional[SExp]) -> Tuple[bool, int]:  # Validate the required header sections of a parsed symbol library root.
    if root is None:  # Reject missing parse results before inspecting the tree.
        return False, 1  # Report line one for an empty or unparseable file.
    if root.name != "kicad_symbol_lib":  # Require the root node to be a KiCad symbol library.
        return False, _node_line_or(root, 1)  # Report the root node location.
    for section_name in _REQUIRED_HEADER_SECTIONS:  # Walk every required header section.
        matches = root.find_children(section_name)  # Collect the direct child sections with the required name.
        if len(matches) != 1:  # Require each header section to appear exactly once.
            return False, _node_line_or(root, 1)  # Report the root node location when a section is missing or duplicated.
        if section_name == "version":  # Apply the YYYYMMDD format check to the version section only.
            version_node = matches[0]  # Read the version section node.
            version_value = _first_atom_value(version_node)  # Extract the version token value.
            if version_value is None or not _VERSION_PATTERN.match(str(version_value)):  # Require an eight-digit date-format version token.
                return False, _node_line_or(version_node, _node_line_or(root, 1))  # Report the version node location.
    return True, 0  # Return success when every required header section validates.


def _validate_symbol_nodes(root: SExp, fallback_line: int) -> Tuple[bool, int]:  # Validate the symbol entries carried by a parsed symbol library root.
    top_symbols = root.find_children("symbol")  # Collect the direct child symbol entries.
    if not top_symbols:  # Require the library to define at least one symbol.
        return False, fallback_line  # Report the final nonblank line when no symbols exist.
    for symbol_node in top_symbols:  # Walk every top-level symbol entry.
        symbol_result = _validate_one_symbol(symbol_node, fallback_line)  # Validate the current symbol entry.
        if not symbol_result[0]:  # Stop at the first failing symbol entry.
            return symbol_result  # Return the exact failing symbol result.
    return True, 0  # Return success when every symbol entry validates.


def _validate_one_symbol(symbol_node: SExp, fallback_line: int) -> Tuple[bool, int]:  # Validate one parent symbol entry.
    symbol_line = _node_line_or(symbol_node, fallback_line)  # Resolve the symbol entry location.
    name_value = _first_atom_value(symbol_node)  # Extract the symbol name atom.
    if name_value is None or not isinstance(name_value, str) or name_value == "":  # Require a nonempty quoted symbol name.
        return False, symbol_line  # Report the symbol entry location.
    for flag_name in ("in_bom", "on_board"):  # Walk the required presence flags.
        flag_node = symbol_node.find_child(flag_name)  # Locate the flag section.
        flag_value = _first_atom_value(flag_node) if flag_node is not None else None  # Extract the flag value.
        if flag_value is None or str(flag_value) not in _YES_NO:  # Require each flag to carry a yes or no value.
            return False, symbol_line  # Report the symbol entry location.
    property_nodes = symbol_node.find_children("property")  # Collect the symbol property entries.
    for key in _MANDATORY_PROPERTY_KEYS:  # Walk the mandatory property keys.
        if not any(_first_atom_value(property_node) == key for property_node in property_nodes):  # Require each mandatory property to exist.
            return False, symbol_line  # Report the symbol entry location.
    for pin_node in _collect_named_nodes(symbol_node, "pin"):  # Walk every pin anywhere under the symbol entry.
        pin_result = _validate_pin_node(pin_node, symbol_line)  # Validate the current pin node.
        if not pin_result[0]:  # Stop at the first failing pin node.
            return pin_result  # Return the exact failing pin result.
    return True, 0  # Return success when the symbol entry validates.


def _validate_pin_node(pin_node: SExp, fallback_line: int) -> Tuple[bool, int]:  # Validate one pin entry inside a symbol.
    pin_line = _node_line_or(pin_node, fallback_line)  # Resolve the pin node location.
    children = pin_node.children  # Read the pin node children.
    if len(children) < 2 or not children[0].is_atom or not children[1].is_atom:  # Require the electrical type and graphic style atoms.
        return False, pin_line  # Report the pin node location.
    pin_type = children[0].value  # Read the pin electrical type token.
    pin_shape = children[1].value  # Read the pin graphic style token.
    if not isinstance(pin_type, str) or pin_type not in _VALID_PIN_TYPES:  # Require a known pin electrical type.
        return False, pin_line  # Report the pin node location.
    if not isinstance(pin_shape, str) or pin_shape not in _VALID_PIN_SHAPES:  # Require a known pin graphic style.
        return False, pin_line  # Report the pin node location.
    at_node = pin_node.find_child("at")  # Locate the pin position section.
    if at_node is None or not _node_has_numeric_atoms(at_node, minimum=2, maximum=3):  # Require an X/Y position with an optional angle.
        return False, pin_line  # Report the pin node location.
    length_node = pin_node.find_child("length")  # Locate the pin length section.
    if length_node is None or not _node_has_numeric_atoms(length_node, minimum=1):  # Require a numeric pin length.
        return False, pin_line  # Report the pin node location.
    for section_name in ("name", "number"):  # Walk the required pin label sections.
        section_node = pin_node.find_child(section_name)  # Locate the current label section.
        if section_node is None or _first_atom_value(section_node) is None:  # Require each pin label section to carry a value.
            return False, pin_line  # Report the pin node location.
    return True, 0  # Return success when the pin node validates.


def _node_has_numeric_atoms(node: SExp, minimum: int, maximum: Optional[int] = None) -> bool:  # Check that a node carries the required count of numeric atom children.
    atom_values = [child.value for child in node.children if child.is_atom]  # Collect the atom values carried by the node.
    if len(atom_values) < minimum:  # Reject nodes with too few atoms.
        return False  # Report the numeric atom check failure.
    if maximum is not None and len(atom_values) > maximum:  # Reject nodes with too many atoms.
        return False  # Report the numeric atom check failure.
    return all(isinstance(value, (int, float)) for value in atom_values)  # Require every atom to be numeric.


def _collect_named_nodes(node: SExp, tag: str) -> List[SExp]:  # Collect every node with the given name anywhere below the starting node.
    results: List[SExp] = []  # Start an empty result list.
    _collect_named_nodes_recursive(node, tag, results)  # Fill the result list recursively.
    return results  # Return the collected nodes.


def _collect_named_nodes_recursive(node: SExp, tag: str, results: List[SExp]) -> None:  # Recursively collect nodes whose name matches the requested tag.
    for child in node.children:  # Walk the direct children.
        if child.is_list:  # Skip atom leaves.
            if child.name == tag:  # Match list nodes by exact name.
                results.append(child)  # Record the matching node.
            _collect_named_nodes_recursive(child, tag, results)  # Descend into nested lists.
