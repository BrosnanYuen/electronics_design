"""KiCad schematic (`.kicad_sch`) validation helpers and public API functions."""  # Document the module purpose.

# The validation profile in this module follows the KiCad s-expression
# schematic file format (see kicad_docs/sexpr-schematic.md in this repository)
# and mirrors the minimal schematic shape produced by the KiCAD-MCP-Server
# project's `SchematicManager.create_schematic()` (MIT licensed). Parsing is
# handled by the vendored `kicad_sexp_parser` module copied from kicad-tools
# (MIT licensed, Copyright (c) 2024 RJ Walters).

from __future__ import annotations  # Postpone annotation evaluation for forward references.

import os  # Access filesystem and permission utilities.
import re  # Validate version and path token structure with regular expressions.
from typing import List  # Type collected source lines.
from typing import Optional  # Type optional parsed structure results.
from typing import Sequence  # Type immutable views over loaded line lists.
from typing import Tuple  # Type tuple-based helper results.

from .kicad_sexp_parser import ParseError  # Catch vendored parser syntax failures.
from .kicad_sexp_parser import SExp  # Type parsed schematic nodes.
from .kicad_sexp_parser import parse_string  # Parse schematic text into an S-expression tree.

ValidationResult = Tuple[bool, str]  # Represent the public validator return shape.
ReadLinesResult = Tuple[bool, List[str], str]  # Represent file-read helper output.
ParseResult = Tuple[bool, Optional[SExp], int]  # Represent schematic parse success, tree, and failing line.

_VERSION_PATTERN = re.compile(r"^\d{8}$")  # Match KiCad version tokens in YYYYMMDD date format.

_REQUIRED_ROOT_SECTIONS = (  # Define the header sections that must appear exactly once in a schematic.
    "version",  # Schematic format version using the YYYYMMDD date format.
    "generator",  # Program that wrote the schematic file.
    "uuid",  # Globally unique schematic identifier.
    "paper",  # Drawing page size definition.
)  # Finish the required root section list.


def is_valid_kicad_sch_header(filepath: str) -> ValidationResult:  # Validate the opening structure of a KiCad schematic file.
    read_result = _read_text_file_lines(filepath)  # Load the file lines through the shared safe reader.
    if not read_result[0]:  # Stop immediately when the shared file reader reports an error.
        return False, read_result[2]  # Propagate the exact file access error message.
    parse_result = _parse_sch_text("\n".join(read_result[1]))  # Parse the schematic text into an S-expression tree.
    if not parse_result[0]:  # Stop when the file is not even valid S-expression syntax.
        return False, _format_line_message("Line format/spacing is invalid!", parse_result[2])  # Report the parse failure so callers fix syntax before header checks.
    root = parse_result[1]  # Read the parsed root node.
    header_result = _validate_sch_header_nodes(root)  # Validate the root node header structure.
    if not header_result[0]:  # Stop when a header problem is detected.
        return False, _format_line_message("Header information is invalid!", header_result[1])  # Return the required header error message.
    return True, ""  # Return success when the schematic header validates successfully.


def is_valid_kicad_sch_spacing(filepath: str) -> ValidationResult:  # Validate the S-expression syntax of a KiCad schematic file.
    read_result = _read_text_file_lines(filepath)  # Load the file lines through the shared safe reader.
    if not read_result[0]:  # Stop immediately when the shared file reader reports an error.
        return False, read_result[2]  # Propagate the exact file access error message.
    parse_result = _parse_sch_text("\n".join(read_result[1]))  # Parse the schematic text into an S-expression tree.
    if not parse_result[0]:  # Stop when the parser reports a syntax failure.
        return False, _format_line_message("Line format/spacing is invalid!", parse_result[2])  # Return the required spacing error message.
    return True, ""  # Return success when the whole file parses as valid S-expressions.


def is_valid_kicad_sch_footer(filepath: str) -> ValidationResult:  # Validate the closing region of a KiCad schematic file.
    read_result = _read_text_file_lines(filepath)  # Load the file lines through the shared safe reader.
    if not read_result[0]:  # Stop immediately when the shared file reader reports an error.
        return False, read_result[2]  # Propagate the exact file access error message.
    lines = read_result[1]  # Read the loaded source lines.
    last_nonblank_line_number = 1  # Track the last nonblank line so missing-section failures have a useful location.
    for line_number, raw_line in enumerate(lines, start=1):  # Walk every line with a one-based line number.
        if raw_line.strip() == "":  # Ignore blank lines when locating the final nonblank line.
            continue  # Move to the next source line.
        last_nonblank_line_number = line_number  # Update the last nonblank line marker.
    parse_result = _parse_sch_text("\n".join(lines))  # Reuse the shared parser so footer validation implies spacing validity.
    if not parse_result[0]:  # Stop when a general schematic syntax problem already exists.
        return False, _format_line_message("Footer information is invalid!", parse_result[2])  # Report the same failing line for footer validation.
    root = parse_result[1]  # Read the parsed root node.
    sheet_instances = root.find_child("sheet_instances")  # Locate the required closing sheet instance section.
    if sheet_instances is None:  # Require the root sheet instance section to exist.
        return False, _format_line_message("Footer information is invalid!", last_nonblank_line_number)  # Report the final nonblank line when the section is missing.
    path_children = sheet_instances.find_children("path")  # Collect the sheet instance path entries.
    if not path_children:  # Require at least one path entry inside sheet_instances.
        return False, _format_line_message("Footer information is invalid!", _node_line_or(sheet_instances, last_nonblank_line_number))  # Report the sheet_instances location.
    for path_child in path_children:  # Walk the path entries.
        path_value = _first_atom_value(path_child)  # Extract the first atom value from the path entry.
        if path_value is None or not str(path_value).startswith("/"):  # Require each path to begin with the root slash marker.
            return False, _format_line_message("Footer information is invalid!", _node_line_or(path_child, last_nonblank_line_number))  # Report the failing path location.
    final_line = lines[last_nonblank_line_number - 1].strip()  # Read the stripped final nonblank source line.
    if not final_line.endswith(")"):  # Require the file to close with the root expression terminator.
        return False, _format_line_message("Footer information is invalid!", last_nonblank_line_number)  # Report the final nonblank line.
    return True, ""  # Return success when the schematic footer structure validates successfully.


def is_valid_kicad_sch_file(filepath: str) -> ValidationResult:  # Validate a KiCad schematic file by composing the three public validators.
    header_result = is_valid_kicad_sch_header(filepath)  # Execute the header validator first.
    if not header_result[0]:  # Stop when the header validator reports any failure.
        return header_result  # Return the exact public failure tuple unchanged.
    spacing_result = is_valid_kicad_sch_spacing(filepath)  # Execute the spacing validator second.
    if not spacing_result[0]:  # Stop when the spacing validator reports any failure.
        return spacing_result  # Return the exact public failure tuple unchanged.
    footer_result = is_valid_kicad_sch_footer(filepath)  # Execute the footer validator third.
    if not footer_result[0]:  # Stop when the footer validator reports any failure.
        return footer_result  # Return the exact public failure tuple unchanged.
    return True, ""  # Return success only when all three validators succeed.


def _read_text_file_lines(filepath: str) -> ReadLinesResult:  # Load a file while mapping filesystem errors to the required API messages.
    coerced_path_result = _coerce_path(filepath)  # Convert the caller-supplied path into a filesystem string.
    if not coerced_path_result[0]:  # Stop when the path cannot be converted to a usable string.
        return False, [], "File not found!"  # Treat an unusable path like a missing file for this API.
    path_string = coerced_path_result[1]  # Extract the checked filesystem path string.
    if not os.path.exists(path_string):  # Check existence before attempting access or opening the file.
        return False, [], "File not found!"  # Return the required not-found message.
    if not os.access(path_string, os.R_OK):  # Check read permission before opening the file.
        return False, [], "No permission to read file!"  # Return the required permission message.
    try:  # Try the preferred UTF-8 decoding first.
        with open(path_string, "r", encoding="utf-8") as file_handle:  # Open the file using the modern KiCad encoding.
            file_text = file_handle.read()  # Read the entire file text from disk.
    except PermissionError:  # Catch late permission failures that bypassed the earlier access check.
        return False, [], "No permission to read file!"  # Return the required permission message.
    except UnicodeDecodeError:  # Fall back when the file is not valid UTF-8.
        try:  # Try a Latin-1 fallback to mirror the LTspice validator behavior.
            with open(path_string, "r", encoding="latin-1") as file_handle:  # Re-open the file with Latin-1 decoding.
                file_text = file_handle.read()  # Read the fallback-decoded file text from disk.
        except PermissionError:  # Catch permission errors from the fallback open path as well.
            return False, [], "No permission to read file!"  # Return the required permission message.
    lines = file_text.splitlines()  # Split the file into logical source lines without trailing newline markers.
    return True, lines, ""  # Return the successfully loaded lines.


def _coerce_path(filepath: str) -> Tuple[bool, str]:  # Convert a path-like input into a string path safely.
    try:  # Attempt filesystem coercion through the standard library.
        path_string = os.fsdecode(os.fspath(filepath))  # Convert string, bytes, or path-like input into a text path.
    except TypeError:  # Catch invalid path-like objects.
        return False, ""  # Signal failure so the caller can map it to the public API error.
    return True, os.path.expanduser(path_string)  # Expand a configurable user-relative path without embedding a home directory.


def _parse_sch_text(text: str) -> ParseResult:  # Parse schematic text while converting syntax failures into line numbers.
    try:  # Attempt the tracked parse so node positions are available for reporting.
        root = parse_string(text, track_positions=True)  # Parse the full schematic text into one root node.
    except ParseError as parse_error:  # Convert parser syntax failures into the shared result shape.
        return False, None, _offset_to_line(text, parse_error.pos)  # Report the failing source line.
    return True, root, 0  # Return the parsed root node on success.


def _validate_sch_header_nodes(root: Optional[SExp]) -> Tuple[bool, int]:  # Validate the required header sections of a parsed schematic root.
    if root is None:  # Reject missing parse results before inspecting the tree.
        return False, 1  # Report line one for an empty or unparseable file.
    if root.name != "kicad_sch":  # Require the root node to be a KiCad schematic.
        return False, _node_line_or(root, 1)  # Report the root node location.
    for section_name in _REQUIRED_ROOT_SECTIONS:  # Walk every required header section.
        matches = root.find_children(section_name)  # Collect the direct child sections with the required name.
        if len(matches) != 1:  # Require each header section to appear exactly once.
            return False, _node_line_or(root, 1)  # Report the root node location when a section is missing or duplicated.
        if section_name == "version":  # Apply the YYYYMMDD format check to the version section only.
            version_node = matches[0]  # Read the version section node.
            version_value = _first_atom_value(version_node)  # Extract the version token value.
            if version_value is None or not _VERSION_PATTERN.match(str(version_value)):  # Require an eight-digit date-format version token.
                return False, _node_line_or(version_node, _node_line_or(root, 1))  # Report the version node location.
    return True, 0  # Return success when every required header section validates.


def _first_atom_value(node: SExp) -> Optional[object]:  # Extract the first atom value carried by one list node.
    for child in node.children:  # Walk the direct children in order.
        if child.is_atom:  # Stop at the first leaf atom.
            return child.value  # Return the atom value.
    return None  # Return None when the node carries no atom children.


def _node_line_or(node: SExp, fallback_line: int) -> int:  # Return the tracked source line of a node or a fallback line.
    if node.has_position:  # Check whether the parser attached a source position.
        return node.line  # Return the tracked one-based line.
    return fallback_line  # Return the fallback line when positions are unavailable.


def _offset_to_line(text: str, offset: int) -> int:  # Convert a byte offset into a one-based source line number.
    return text.count("\n", 0, max(offset, 0)) + 1  # Count preceding newlines and add one for the line itself.


def _format_line_message(prefix: str, line_number: int) -> str:  # Build the required public error message with a line number suffix.
    return f"{prefix} Line {line_number}"  # Return the final user-facing message.
