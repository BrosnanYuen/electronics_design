"""LTspice netlist validation helpers and public API functions."""  # Document the module purpose.

from __future__ import annotations  # Postpone annotation evaluation for forward references.

from dataclasses import dataclass  # Use a small record type for parsed element lines.
from html import escape  # Escape text safely when emitting SVG output.
from itertools import combinations  # Build component-to-component projected edges for plotting.
import math  # Compute simple node-layout geometry for PNG graph rendering.
import os  # Access filesystem and permission utilities.
import re  # Validate directive spelling and structure with regular expressions.
import struct  # Encode PNG header fields in network-ordered binary form.
from typing import Dict  # Type the node-count mapping.
from typing import List  # Type collections of lines and nodes.
from typing import Mapping  # Type conversion-setting dictionaries.
from typing import Optional  # Type setting-resolution failures.
from typing import Sequence  # Type immutable views over loaded line lists.
from typing import Set  # Type unique node-name collections extracted from expressions.
from typing import Tuple  # Type tuple-based helper results.
import zlib  # Compress PNG image payloads and compute chunk checksums.

import networkx as nx  # Build comparison and plotting graphs with the required dependency.
from networkx.algorithms import isomorphism  # Compare normalized netlist graphs structurally.

ValidationResult = Tuple[bool, str]  # Represent the public validator return shape.
ReadLinesResult = Tuple[bool, List[str], str]  # Represent file-read helper output.
DirectiveResult = Tuple[bool, str, str]  # Represent directive parsing success, name, and message.
ElementParseResult = Tuple[bool, List["ParsedElement"], int, str]  # Represent parsed element extraction.

_DIRECTIVE_PATTERN = re.compile(r"^\.(?P<name>[A-Za-z]+)(?:\s|$)")  # Match an LTspice dot-directive name.
_NODE_VOLTAGE_REFERENCE_PATTERN = re.compile(r"V\(\s*([^(),\s]+)(?:\s*,\s*([^()\s]+))?\s*\)", re.IGNORECASE)  # Match node references inside LTspice voltage expressions.

_VALID_DEVICE_PREFIXES = {  # Define the supported leading element prefixes from the LTspice manual.
    "A",  # Special function device prefix.
    "B",  # Behavioral source prefix.
    "C",  # Capacitor prefix.
    "D",  # Diode prefix.
    "E",  # Voltage controlled voltage source prefix.
    "F",  # Current controlled current source prefix.
    "G",  # Voltage controlled current source prefix.
    "H",  # Current controlled voltage source prefix.
    "I",  # Independent current source prefix.
    "J",  # JFET prefix.
    "K",  # Mutual inductance prefix.
    "L",  # Inductor prefix.
    "M",  # MOSFET prefix.
    "O",  # Lossy transmission line prefix.
    "Q",  # BJT prefix.
    "R",  # Resistor prefix.
    "S",  # Voltage controlled switch prefix.
    "T",  # Lossless transmission line prefix.
    "U",  # Uniform RC line prefix.
    "V",  # Independent voltage source prefix.
    "W",  # Current controlled switch prefix.
    "X",  # Subcircuit invocation prefix.
    "Z",  # MESFET or IGBT prefix.
    "@",  # FRA analyzer prefix.
    "&",  # FRA probe prefix.
}  # Finish the allowed prefix set.

_DEVICE_MINIMUM_TOKEN_COUNTS = {  # Define the minimum whitespace-separated token count per prefix.
    "A": 10,  # Name plus eight nodes and one model token.
    "B": 4,  # Name plus two nodes and an expression token.
    "C": 4,  # Name plus two nodes and a value token.
    "D": 4,  # Name plus two nodes and a model token.
    "E": 6,  # Name plus four nodes and a gain token.
    "F": 5,  # Name plus two nodes, a source name, and a gain token.
    "G": 6,  # Name plus four nodes and a gain token.
    "H": 5,  # Name plus two nodes, a source name, and a gain token.
    "I": 3,  # Name plus two nodes, with the value token optional for sweep-driven sources.
    "J": 5,  # Name plus three nodes and a model token.
    "K": 4,  # Name plus two coupled inductors and a coupling factor.
    "L": 4,  # Name plus two nodes and a value token.
    "M": 6,  # Name plus four nodes and a model token.
    "O": 6,  # Name plus four nodes and a model token.
    "Q": 6,  # Name plus four nodes and a model token for the project's stricter spacing checks.
    "R": 4,  # Name plus two nodes and a value token.
    "S": 6,  # Name plus four nodes and a model token.
    "T": 6,  # Name plus four nodes and line parameters.
    "U": 5,  # Name plus three nodes and a model token.
    "V": 3,  # Name plus two nodes, with the value token optional for sweep-driven sources.
    "W": 5,  # Name plus two nodes, a source name, and a model token.
    "X": 3,  # Name plus at least one node and a subcircuit name.
    "Z": 5,  # Name plus three nodes and a model token.
    "@": 2,  # Name plus at least one FRA parameter token.
    "&": 5,  # Name plus four FRA probe nodes.
}  # Finish the token-count lookup.

_VALID_DOT_DIRECTIVES = {  # Define dot commands supported by current LTspice manuals plus common legacy/library tokens.
    "ac",  # AC analysis directive.
    "backanno",  # Back-annotation directive.
    "dc",  # DC sweep directive.
    "end",  # Netlist terminator directive.
    "endl",  # Library section terminator directive.
    "ends",  # Subcircuit terminator directive.
    "four",  # Fourier directive.
    "fra",  # FRA analysis directive.
    "func",  # Function definition directive.
    "function",  # Long-form function definition directive used by some LTspice exports.
    "global",  # Global node declaration directive.
    "ic",  # Initial conditions directive.
    "include",  # Include-file directive.
    "keepnode",  # Keep-node directive.
    "lib",  # Library include directive.
    "loadbias",  # Load-bias directive.
    "loadstate",  # Load-state directive.
    "machine",  # State-machine directive.
    "measure",  # Long-form measure directive.
    "meas",  # Short-form measure directive.
    "model",  # Model definition directive.
    "net",  # Network parameter directive.
    "nodeset",  # Node-set directive.
    "noise",  # Noise analysis directive.
    "op",  # Operating-point directive.
    "options",  # Simulator options directive.
    "param",  # Parameter definition directive.
    "save",  # Save waveform directive.
    "savebias",  # Save-bias directive.
    "savestate",  # Save-state directive.
    "step",  # Parameter sweep directive.
    "subckt",  # Subcircuit definition directive.
    "temp",  # Temperature sweep directive.
    "tf",  # Transfer-function directive.
    "tran",  # Transient analysis directive.
    "wave",  # Wave-file output directive.
    "text",  # Legacy text directive.
    "ferret",  # Legacy ferret directive.
}  # Finish the directive whitelist.

_ANALYSIS_DIRECTIVES = {  # Define directives that satisfy the "simulation analysis exists" requirement.
    "ac",  # AC analysis.
    "dc",  # DC sweep analysis.
    "noise",  # Noise analysis.
    "op",  # Operating-point analysis.
    "tf",  # Transfer-function analysis.
    "tran",  # Transient analysis.
    "fra",  # Time-domain frequency-response analysis.
}  # Finish the analysis directive set.

_FOOTER_DIRECTIVES = {  # Define directives that are acceptable in the footer region.
    "ac",  # Allow AC analysis in the footer.
    "backanno",  # Allow back-annotation in the footer.
    "dc",  # Allow DC analysis in the footer.
    "four",  # Allow Fourier analysis in the footer.
    "fra",  # Allow FRA analysis in the footer.
    "func",  # Allow function helpers in the footer.
    "function",  # Allow long-form function helpers in the footer.
    "global",  # Allow global node declarations in the footer.
    "ic",  # Allow initial condition directives in the footer.
    "include",  # Allow include directives in the footer.
    "keepnode",  # Allow keep-node directives in the footer.
    "lib",  # Allow library directives in the footer.
    "loadbias",  # Allow load-bias directives in the footer.
    "loadstate",  # Allow load-state directives in the footer.
    "measure",  # Allow long-form measurements in the footer.
    "meas",  # Allow short-form measurements in the footer.
    "model",  # Allow model declarations in the footer.
    "net",  # Allow network-parameter directives in the footer.
    "nodeset",  # Allow nodeset directives in the footer.
    "noise",  # Allow noise analysis in the footer.
    "op",  # Allow operating-point analysis in the footer.
    "options",  # Allow options directives in the footer.
    "param",  # Allow parameters in the footer.
    "save",  # Allow save directives in the footer.
    "savebias",  # Allow save-bias directives in the footer.
    "savestate",  # Allow save-state directives in the footer.
    "step",  # Allow parameter sweeps in the footer.
    "temp",  # Allow temperature directives in the footer.
    "tf",  # Allow transfer-function analysis in the footer.
    "tran",  # Allow transient analysis in the footer.
    "wave",  # Allow wave output in the footer.
    "end",  # Allow the terminal .end directive in the footer.
}  # Finish the footer directive whitelist.

_EXEMPT_NODE_PREFIXES = ("NC", "NC_", "NC-")  # Exempt explicit no-connect node names from connectivity checks.

_PNG_BACKGROUND = (248, 250, 252)  # Use a light background for generated network graph images.
_PNG_EDGE_COLOR = (148, 163, 184)  # Use a muted line color for component-to-component edges.
_PNG_COMPONENT_BORDER = (30, 41, 59)  # Use a dark neutral border for component nodes in the generated graph.
_PNG_GROUND_COLOR = (51, 65, 85)  # Use a dark neutral color for the rendered ground symbol.
_PNG_TEXT_COLOR = (15, 23, 42)  # Use a dark text color for labels rendered into the PNG image.
_PNG_TEXT_MUTED = (71, 85, 105)  # Use a softer text color for secondary labels such as component values.
_PNG_COMPONENT_COLORS = [  # Cycle through a compact palette so different component prefixes are easy to distinguish.
    (251, 191, 36),  # Amber component fill color.
    (52, 211, 153),  # Emerald component fill color.
    (96, 165, 250),  # Sky component fill color.
    (248, 113, 113),  # Red component fill color.
    (196, 181, 253),  # Violet component fill color.
    (244, 114, 182),  # Pink component fill color.
]  # Finish the component fill palette.
_COMPONENT_BOX_HALF_WIDTH = 70  # Reserve enough width for component labels in the higher-resolution plot.
_COMPONENT_BOX_HALF_HEIGHT = 22  # Reserve enough height for the component box shape in the higher-resolution plot.
_GROUND_SYMBOL_HALF_WIDTH = 18  # Reserve enough width for the visual ground symbol anchor calculations.
_GROUND_SYMBOL_HEIGHT = 22  # Reserve enough height for the rendered ground symbol.
_BITMAP_FONT_GLYPHS = {  # Define a compact 5x7 bitmap font for the labels rendered into PNG outputs.
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    "?": ("01110", "10001", "00001", "00010", "00100", "00000", "00100"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    ",": ("00000", "00000", "00000", "00000", "01100", "01100", "01000"),
    ":": ("00000", "01100", "01100", "00000", "01100", "01100", "00000"),
    ";": ("00000", "01100", "01100", "00000", "01100", "01100", "01000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "_": ("00000", "00000", "00000", "00000", "00000", "00000", "11111"),
    "/": ("00001", "00010", "00100", "01000", "10000", "00000", "00000"),
    "\\": ("10000", "01000", "00100", "00010", "00001", "00000", "00000"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    "=": ("00000", "11111", "00000", "11111", "00000", "00000", "00000"),
    "(": ("00010", "00100", "01000", "01000", "01000", "00100", "00010"),
    ")": ("01000", "00100", "00010", "00010", "00010", "00100", "01000"),
    "[": ("01110", "01000", "01000", "01000", "01000", "01000", "01110"),
    "]": ("01110", "00010", "00010", "00010", "00010", "00010", "01110"),
    "*": ("00000", "10101", "01110", "11111", "01110", "10101", "00000"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11100", "10010", "10001", "10001", "10001", "10010", "11100"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01110"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "J": ("00001", "00001", "00001", "00001", "10001", "10001", "01110"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
}  # Finish the bitmap font glyph table.


@dataclass(frozen=True)  # Freeze parsed element records so tests and callers can rely on immutability.
class ParsedElement:  # Represent a parsed device line and its connectivity nodes.
    line_number: int  # Store the one-based source line number.
    prefix: str  # Store the validated device prefix.
    tokens: List[str]  # Store the whitespace-tokenized line content without comments.
    nodes: List[str]  # Store the extracted connectivity nodes for the element.


def _resolve_voltage_must_have_dc(convert_settings: Mapping[str, object]) -> Optional[bool]:
    """Resolve the opt-in AC-only voltage normalization setting."""

    raw_value = convert_settings.get("voltage_must_have_dc", False)
    if not isinstance(raw_value, bool):
        return None
    return raw_value


def _normalize_voltage_source_tokens(
    tokens: Sequence[str],
    voltage_must_have_dc: bool,
) -> Tuple[str, ...]:
    """Insert a zero DC value before an AC-only voltage-source payload."""

    normalized_tokens = tuple(tokens)
    if not voltage_must_have_dc or len(normalized_tokens) < 4:
        return normalized_tokens
    instance_token = normalized_tokens[0].strip()
    if instance_token == "" or instance_token[0].upper() != "V":
        return normalized_tokens
    if normalized_tokens[3].upper() != "AC":
        return normalized_tokens
    return (*normalized_tokens[:3], "0", *normalized_tokens[3:])


def is_valid_ltspice_netlist_format(filepath: str) -> ValidationResult:  # Validate line-level LTspice netlist spacing and syntax.
    read_result = _read_text_file_lines(filepath)  # Load the file lines through the shared safe reader.
    if not read_result[0]:  # Stop immediately when the shared file reader reports an error.
        return False, read_result[2]  # Propagate the exact file access error message.
    format_result = _validate_format_lines(read_result[1])  # Validate the loaded lines now that reading succeeded.
    if not format_result[0]:  # Stop when a line-format problem is detected.
        return False, _format_line_message("Line format/spacing is invalid!", format_result[1])  # Return the required message.
    return True, ""  # Return success when every line conforms to the expected structure.


def is_valid_ltspice_netlist_footer(filepath: str) -> ValidationResult:  # Validate footer directives and simulation termination structure.
    read_result = _read_text_file_lines(filepath)  # Load the file lines through the shared safe reader.
    if not read_result[0]:  # Stop immediately when the shared file reader reports an error.
        return False, read_result[2]  # Propagate the exact file access error message.
    footer_result = _validate_footer_lines(read_result[1])  # Validate the footer region now that reading succeeded.
    if not footer_result[0]:  # Stop when a footer problem is detected.
        return False, _format_line_message("Footer information is invalid!", footer_result[1])  # Return the required footer error.
    return True, ""  # Return success when the footer is valid.


def is_ltspice_netlist_structure_connected(filepath: str) -> ValidationResult:  # Validate that all non-exempt nodes are connected to at least two ports.
    read_result = _read_text_file_lines(filepath)  # Load the file lines through the shared safe reader.
    if not read_result[0]:  # Stop immediately when the shared file reader reports an error.
        return False, read_result[2]  # Propagate the exact file access error message.
    connectivity_result = _validate_connectivity(read_result[1])  # Validate connectivity using the successfully read lines.
    if not connectivity_result[0]:  # Stop when a connectivity problem is detected.
        return False, _format_line_message("Node is not connected correctly!", connectivity_result[1])  # Return the required node error.
    return True, ""  # Return success when all required nodes are connected.


def is_valid_ltspice_netlist_file(filepath: str) -> ValidationResult:  # Validate a netlist by delegating only to the three required public validators.
    format_result = is_valid_ltspice_netlist_format(filepath)  # Execute the required format validator first.
    if not format_result[0]:  # Stop when the format validator reports any failure.
        return format_result  # Return the exact public failure tuple unchanged.
    footer_result = is_valid_ltspice_netlist_footer(filepath)  # Execute the required footer validator second.
    if not footer_result[0]:  # Stop when the footer validator reports any failure.
        return footer_result  # Return the exact public failure tuple unchanged.
    connectivity_result = is_ltspice_netlist_structure_connected(filepath)  # Execute the required connectivity validator last.
    if not connectivity_result[0]:  # Stop when the connectivity validator reports any failure.
        return connectivity_result  # Return the exact public failure tuple unchanged.
    return True, ""  # Return success only when all three required validators succeed.


def ltspice_netlist_footer_cmp(filepath1: str, filepath2: str) -> bool:  # Compare two valid LTspice netlist footers while ignoring comments and component sections.
    first_footer_result = _load_normalized_footer_lines(filepath1)  # Load the normalized comparable footer sequence for the first netlist.
    if not first_footer_result[0]:  # Stop when the first footer cannot be read or derived reliably.
        return False  # Return False because the footer comparison cannot proceed safely.
    second_footer_result = _load_normalized_footer_lines(filepath2)  # Load the normalized comparable footer sequence for the second netlist.
    if not second_footer_result[0]:  # Stop when the second footer cannot be read or derived reliably.
        return False  # Return False because the footer comparison cannot proceed safely.
    first_footer_lines = first_footer_result[1]  # Extract the comparable footer sequence for the first file.
    second_footer_lines = second_footer_result[1]  # Extract the comparable footer sequence for the second file.
    if first_footer_lines == second_footer_lines:  # Fast-path exact equality for the common case.
        return True  # Return True immediately when the normalized footer sequences already match.
    return _normalize_optional_default_op(first_footer_lines) == _normalize_optional_default_op(second_footer_lines)  # Treat an injected fallback .op as optional when it is the only analysis directive.


def ltspice_netlist_structure_cmp(filepath1: str, filepath2: str) -> bool:  # Compare two validated LTspice netlists for structural equivalence while ignoring footer directives.
    first_parse_result = _load_parsed_elements(filepath1)  # Parse the first input file into device elements after format validation.
    if not first_parse_result[0]:  # Stop when internal parsing unexpectedly fails after validation.
        return False  # Return False because the first graph cannot be built reliably.
    second_parse_result = _load_parsed_elements(filepath2)  # Parse the second input file into device elements after format validation.
    if not second_parse_result[0]:  # Stop when internal parsing unexpectedly fails after validation.
        return False  # Return False because the second graph cannot be built reliably.
    first_graph = _build_networkx_graph(first_parse_result[1], include_visual_labels=False)  # Build the normalized comparison graph for the first file.
    second_graph = _build_networkx_graph(second_parse_result[1], include_visual_labels=False)  # Build the normalized comparison graph for the second file.
    matcher = isomorphism.MultiGraphMatcher(  # Create a multigraph isomorphism matcher for the two normalized graphs.
        first_graph,  # Provide the normalized graph built from the first netlist.
        second_graph,  # Provide the normalized graph built from the second netlist.
        node_match=_networkx_graph_node_match,  # Compare component signatures and special net classes exactly.
        edge_match=isomorphism.categorical_multiedge_match("port", -1),  # Preserve device-port positions across the comparison.
    )  # Finish the graph matcher construction.
    return matcher.is_isomorphic()  # Return True only when the two normalized graphs are structurally equivalent.


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
        with open(path_string, "r", encoding="utf-8") as file_handle:  # Open the file using the common modern LTspice encoding.
            file_text = file_handle.read()  # Read the entire file text from disk.
    except PermissionError:  # Catch late permission failures that bypassed the earlier access check.
        return False, [], "No permission to read file!"  # Return the required permission message.
    except UnicodeDecodeError:  # Fall back when the file is not valid UTF-8.
        try:  # Try a Latin-1 fallback because LTspice documentation allows that fallback mode.
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
    return True, os.path.expanduser(path_string)  # Expand configurable user-relative paths without embedding a home directory.


def _load_parsed_elements(filepath: str) -> ElementParseResult:  # Load a file and parse its device elements through the existing internal helpers.
    read_result = _read_text_file_lines(filepath)  # Re-read the file through the shared safe text loader.
    if not read_result[0]:  # Stop when the file cannot be read safely.
        return False, [], 0, "read_error"  # Return a generic parse failure marker for the caller.
    return _parse_elements(read_result[1])  # Parse the loaded source lines into structured device elements.


def _load_normalized_footer_lines(filepath: str) -> Tuple[bool, Tuple[str, ...]]:  # Load one validated netlist footer into a normalized comparable sequence.
    read_result = _read_text_file_lines(filepath)  # Re-read the file through the shared safe text loader after validation succeeds.
    if not read_result[0]:  # Stop when the file cannot be read safely.
        return False, ()  # Signal footer-loading failure to the caller.
    return _extract_normalized_footer_lines(read_result[1])  # Extract the normalized footer sequence from the loaded source lines.


def _validate_format_lines(lines: Sequence[str]) -> Tuple[bool, int]:  # Validate each line for directive spelling and minimum token structure.
    previous_logical_line_exists = False  # Track whether a continuation line has something valid to continue.
    first_code_line_number = 0  # Track the first non-comment, nonblank source line for directive-only deck rejection.
    found_device_line = False  # Require at least one device line for a structurally meaningful netlist.
    for line_number, raw_line in enumerate(lines, start=1):  # Walk every line with a one-based line number.
        line_kind_result = _classify_line(raw_line)  # Classify the line before validating its detailed structure.
        if not line_kind_result[0]:  # Stop when the line classification itself fails.
            return False, line_number  # Return the failing line number.
        line_kind = line_kind_result[1]  # Extract the validated line category.
        if line_kind in {"blank", "comment"}:  # Ignore blank lines and full-line comments.
            continue  # Move to the next input line.
        if first_code_line_number == 0:  # Record the first structural line in case the file never defines a device.
            first_code_line_number = line_number  # Save the earliest non-comment, nonblank line number.
        if line_kind == "continuation":  # Handle LTspice continuation lines explicitly.
            if not previous_logical_line_exists:  # Reject a continuation with no prior logical line.
                return False, line_number  # Report the failing line number.
            previous_logical_line_exists = True  # Keep the logical-line state active after a valid continuation.
            continue  # Move to the next input line.
        code_part = _strip_semicolon_comment(raw_line).strip()  # Remove any inline semicolon comment before token checks.
        if line_kind == "directive":  # Validate a dot-directive line.
            directive_result = _parse_directive_name(code_part)  # Parse and validate the directive keyword.
            if not directive_result[0]:  # Stop when the directive name is malformed or unsupported.
                return False, line_number  # Report the failing line number.
            previous_logical_line_exists = True  # Mark the line as a valid logical line for later continuations.
            continue  # Move to the next input line.
        if line_kind == "device":  # Validate a circuit element line.
            tokens = code_part.split()  # Split the device line into whitespace-separated tokens.
            device_check_result = _validate_device_tokens(tokens)  # Validate prefix and minimum token count.
            if not device_check_result[0]:  # Stop when the device line structure is invalid.
                return False, line_number  # Report the failing line number.
            found_device_line = True  # Record that the file contains at least one device statement.
            previous_logical_line_exists = True  # Mark the line as a valid logical line for later continuations.
            continue  # Move to the next input line.
        return False, line_number  # Reject any unexpected line type as invalid.
    if first_code_line_number != 0 and not found_device_line:  # Reject directive-only decks because the project expects a circuit netlist.
        return False, first_code_line_number  # Report the first structural line as the invalid starting point.
    return True, 0  # Return success when all lines validate.


def _validate_footer_lines(lines: Sequence[str]) -> Tuple[bool, int]:  # Validate footer directives, sequencing, and required termination lines.
    format_result = _validate_format_lines(lines)  # Reuse the line-format validator before inspecting footer semantics.
    if not format_result[0]:  # Stop when a general line-format problem already exists.
        return False, format_result[1]  # Report the same failing line number for footer validation.
    nonblank_entries = _collect_nonblank_entries(lines)  # Collect nonblank lines for footer sequencing checks.
    if not nonblank_entries[0]:  # Stop when the file contains no usable content.
        return False, 1  # Report line one for an empty file.
    nonblank_lines = nonblank_entries[1]  # Extract the nonblank line metadata after the helper succeeds.
    last_line_number, last_line_text = nonblank_lines[-1]  # Read the final nonblank line for the .end check.
    if last_line_text.lower() != ".end":  # Require the final nonblank line to be .end exactly.
        return False, last_line_number  # Report the last nonblank line as invalid.
    if len(nonblank_lines) < 2:  # Require at least one line before .end so .backanno can exist.
        return False, last_line_number  # Report the final line because the footer is incomplete.
    previous_line_number, previous_line_text = nonblank_lines[-2]  # Read the penultimate nonblank line for the .backanno check.
    if previous_line_text.lower() != ".backanno":  # Require .backanno immediately before .end.
        return False, previous_line_number  # Report the penultimate line as invalid.
    analysis_count = 0  # Count valid analysis directives across the entire file.
    last_device_line_number = 0  # Track the most recent device line to define the footer boundary.
    for line_number, raw_line in enumerate(lines, start=1):  # Walk every source line with its line number.
        classification_result = _classify_line(raw_line)  # Classify the current line before semantic checks.
        if not classification_result[0]:  # Stop when classification fails unexpectedly.
            return False, line_number  # Report the failing line number.
        line_kind = classification_result[1]  # Extract the validated line category.
        if line_kind == "device":  # Track the last device line to anchor the footer region.
            last_device_line_number = line_number  # Update the footer boundary marker.
            continue  # Skip to the next line because device lines are not footer directives.
        if line_kind not in {"directive", "comment", "blank", "continuation"}:  # Reject any other unexpected line category.
            return False, line_number  # Report the failing line number.
        if line_kind != "directive":  # Ignore non-directive lines for directive-specific footer checks.
            continue  # Move to the next line.
        code_part = _strip_semicolon_comment(raw_line).strip()  # Remove any semicolon comment before parsing the directive.
        directive_result = _parse_directive_name(code_part)  # Parse and validate the dot-directive name.
        if not directive_result[0]:  # Stop when the directive keyword is malformed or unsupported.
            return False, line_number  # Report the failing line number.
        directive_name = directive_result[1]  # Extract the validated directive name.
        if directive_name in _ANALYSIS_DIRECTIVES:  # Track the presence of a simulation analysis command.
            analysis_count += 1  # Record the analysis directive count.
        if line_number > last_device_line_number and directive_name not in _FOOTER_DIRECTIVES:  # Restrict post-device directives to footer-safe commands.
            return False, line_number  # Report the failing line number.
        if directive_name == "end" and line_number != last_line_number:  # Reject .end if it appears before the final nonblank line.
            return False, line_number  # Report the early .end line number.
        if directive_name == "backanno" and line_number != previous_line_number:  # Reject .backanno when it is not the penultimate nonblank line.
            return False, line_number  # Report the misplaced .backanno line number.
    if analysis_count == 0:  # Require at least one LTspice analysis directive somewhere in the deck.
        return False, previous_line_number  # Report the footer region because the simulation command is missing.
    return True, 0  # Return success when the footer is valid.


def _extract_normalized_footer_lines(lines: Sequence[str]) -> Tuple[bool, Tuple[str, ...]]:  # Extract a comparable footer sequence while ignoring blank lines and comments.
    format_result = _validate_format_lines(lines)  # Reuse the line-format validator before deriving the footer region.
    if not format_result[0]:  # Stop when the file is not even structurally parseable.
        return False, ()  # Signal extraction failure because the footer boundary cannot be trusted.
    last_device_line_number = 0  # Track the final device line so the footer region starts immediately after it.
    normalized_footer_lines: List[str] = []  # Collect the normalized comparable footer lines in source order.
    for line_number, raw_line in enumerate(lines, start=1):  # Walk every source line with its one-based line number.
        classification_result = _classify_line(raw_line)  # Classify the line before deciding whether it belongs to the footer sequence.
        if not classification_result[0]:  # Stop when line classification fails unexpectedly.
            return False, ()  # Signal extraction failure because the footer cannot be derived safely.
        line_kind = classification_result[1]  # Extract the validated line category.
        if line_kind == "device":  # Update the footer boundary whenever a device statement is encountered.
            last_device_line_number = line_number  # Record the current line as the latest device line.
            continue  # Move to the next line because component lines are never part of the compared footer sequence.
        if line_number <= last_device_line_number:  # Ignore everything before or on the final device line.
            continue  # Move to the next line because only the post-device footer region is compared.
        if line_kind in {"blank", "comment"}:  # Ignore blank lines and whole-line comments in the footer region.
            continue  # Move to the next line because comments do not affect footer equivalence.
        if line_kind == "continuation":  # Preserve valid continuation lines because they are part of the logical footer content.
            normalized_footer_lines.append(raw_line.lstrip())  # Record the continuation line text with leading whitespace removed.
            continue  # Move to the next line after saving the continuation.
        code_part = _strip_semicolon_comment(raw_line).strip()  # Remove inline semicolon comments before comparing the footer line text.
        if code_part != "":  # Ignore lines that become empty after semicolon-comment stripping.
            normalized_footer_lines.append(code_part)  # Record the normalized footer line in source order.
    return True, tuple(normalized_footer_lines)  # Return the final normalized footer sequence for comparison.


def _normalize_optional_default_op(footer_lines: Sequence[str]) -> Tuple[str, ...]:  # Remove an auto-inserted fallback .op when it is the only analysis directive in the footer.
    analysis_line_indexes: List[int] = []
    for index, footer_line in enumerate(footer_lines):
        directive_result = _parse_directive_name(footer_line)
        if directive_result[0] and directive_result[1] in _ANALYSIS_DIRECTIVES:
            analysis_line_indexes.append(index)
    if len(analysis_line_indexes) != 1:
        return tuple(footer_lines)
    analysis_line = footer_lines[analysis_line_indexes[0]].strip().lower()
    if analysis_line != ".op":
        return tuple(footer_lines)
    return tuple(
        footer_line
        for index, footer_line in enumerate(footer_lines)
        if index != analysis_line_indexes[0]
    )


def _validate_connectivity(lines: Sequence[str]) -> Tuple[bool, int]:  # Validate that every non-exempt node is connected in at least two element pins.
    parse_result = _parse_elements(lines)  # Parse device lines into connectivity-aware element records.
    if not parse_result[0]:  # Stop when element parsing fails.
        return False, parse_result[2]  # Report the parser's failing line number.
    elements = parse_result[1]  # Extract the parsed elements after confirming parsing succeeded.
    node_counts = _count_element_nodes(elements)  # Count how many times each relevant node appears across all element ports and expression references.
    for element in elements:  # Walk elements in source order so the earliest problem line is reported.
        for node_name in element.nodes:  # Check each connectivity node attached to the element.
            if _is_exempt_node(node_name):  # Skip ground and explicit no-connect nodes.
                continue  # Move to the next node because exempt nodes do not need multiple connections.
            node_occurrences = node_counts.get(node_name, 0)  # Look up how many ports reference this node.
            if node_occurrences < 2:  # Require at least two references to consider the node connected.
                return False, element.line_number  # Report the element line containing the first orphan node.
    return True, 0  # Return success when every relevant node is connected.


def _parse_elements(lines: Sequence[str]) -> ElementParseResult:  # Parse device lines into node-aware element records.
    format_result = _validate_format_lines(lines)  # Reuse the line-format validator before extracting element nodes.
    if not format_result[0]:  # Stop when the file structure is already invalid.
        return False, [], format_result[1], "format_error"  # Return the failing line number for the connectivity validator.
    parsed_elements: List[ParsedElement] = []  # Collect validated device elements for connectivity analysis.
    for line_number, raw_line in enumerate(lines, start=1):  # Walk every line with its one-based line number.
        classification_result = _classify_line(raw_line)  # Classify the line before device extraction.
        if not classification_result[0]:  # Stop when classification fails unexpectedly.
            return False, [], line_number, "classification_error"  # Return the failing line number.
        if classification_result[1] != "device":  # Skip non-device lines because they do not add device-port connectivity.
            continue  # Move to the next line.
        code_part = _strip_semicolon_comment(raw_line).strip()  # Remove inline comments before token parsing.
        tokens = code_part.split()  # Split the device line into whitespace-separated tokens.
        device_check_result = _validate_device_tokens(tokens)  # Re-check the token structure before extracting nodes.
        if not device_check_result[0]:  # Stop when the token structure is unexpectedly invalid.
            return False, [], line_number, "device_error"  # Return the failing line number.
        node_extract_result = _extract_nodes(tokens)  # Extract the connectivity nodes for the specific device class.
        if not node_extract_result[0]:  # Stop when node extraction cannot determine the proper node list.
            return False, [], line_number, "node_error"  # Return the failing line number.
        parsed_elements.append(ParsedElement(line_number=line_number, prefix=tokens[0][0].upper(), tokens=tokens, nodes=node_extract_result[1]))  # Save the parsed element record.
    return True, parsed_elements, 0, ""  # Return the parsed element collection.


def _classify_line(raw_line: str) -> Tuple[bool, str]:  # Classify a raw source line into an LTspice line category.
    stripped_line = raw_line.lstrip()  # Ignore leading whitespace when determining the line class.
    if stripped_line == "":  # Treat empty or all-whitespace lines as blank.
        return True, "blank"  # Return the blank-line classification.
    leading_character = stripped_line[0]  # Read the first nonblank character to classify the line.
    if leading_character == "*":  # Treat leading asterisk lines as whole-line comments.
        return True, "comment"  # Return the comment classification.
    if leading_character == ";":  # Treat leading semicolons as comment lines because LTspice sample decks use that form.
        return True, "comment"  # Return the comment classification.
    if leading_character == "+":  # Treat leading plus lines as continuations.
        return True, "continuation"  # Return the continuation classification.
    if leading_character == ".":  # Treat leading dot lines as simulator directives.
        return True, "directive"  # Return the directive classification.
    if leading_character.upper() in _VALID_DEVICE_PREFIXES:  # Treat supported device prefixes as element lines.
        return True, "device"  # Return the device classification.
    return False, "invalid"  # Reject any unsupported leading character.


def _parse_directive_name(code_part: str) -> DirectiveResult:  # Parse and validate a dot-directive keyword.
    directive_match = _DIRECTIVE_PATTERN.match(code_part)  # Match the directive name at the start of the code portion.
    if directive_match is None:  # Reject directives without a valid dot-command name boundary.
        return False, "", "invalid_directive"  # Signal directive parsing failure.
    directive_name = directive_match.group("name").lower()  # Normalize the matched directive name to lowercase.
    if directive_name not in _VALID_DOT_DIRECTIVES:  # Reject unsupported or merged directive spellings.
        return False, "", "unknown_directive"  # Signal directive validation failure.
    return True, directive_name, ""  # Return the validated directive name.


def _validate_device_tokens(tokens: Sequence[str]) -> Tuple[bool, str]:  # Validate a device line's prefix and minimum whitespace token structure.
    if len(tokens) < 2:  # Require at least an instance name and one additional token.
        return False, "too_few_tokens"  # Signal a token-count failure.
    instance_name = tokens[0]  # Read the element instance token.
    prefix = instance_name[0].upper()  # Normalize the leading device prefix character.
    if prefix not in _VALID_DEVICE_PREFIXES:  # Reject unsupported device prefixes.
        return False, "invalid_prefix"  # Signal an invalid-prefix failure.
    if len(instance_name) < 2 and prefix != "K":  # Permit LTspice mutual-coupling statements like K L1 L2 0.9 used in the fixture corpus.
        return False, "short_instance_name"  # Signal an instance-name failure.
    if re.match(r"^[A-Za-z@&]\d+[A-Za-z].*$", instance_name) is not None:  # Reject merged instance-name and node-name patterns such as R1Vcc.
        return False, "merged_instance_name"  # Signal an instance-name spacing failure.
    if _is_two_node_behavioral_controlled_source(prefix, tokens):  # Accept LTspice's behavioral E/G source form with only output nodes and an expression payload.
        return True, ""  # Return success when the reduced-node behavioral form is structurally valid.
    minimum_token_count = _DEVICE_MINIMUM_TOKEN_COUNTS[prefix]  # Look up the minimum token count for this device prefix.
    if len(tokens) < minimum_token_count:  # Reject lines that are too short for the prefix grammar.
        return False, "too_few_prefix_tokens"  # Signal a prefix-specific token-count failure.
    return True, ""  # Return success when the device line is minimally well-formed.


def _extract_nodes(tokens: Sequence[str]) -> Tuple[bool, List[str]]:  # Extract connectivity node tokens according to the device prefix grammar.
    prefix = tokens[0][0].upper()  # Read the normalized device prefix from the instance name.
    if prefix == "A":  # Handle special-function devices with eight positional nodes.
        return True, list(tokens[1:9])  # Return the eight node tokens.
    if prefix == "B":  # Handle behavioral sources with two nodes.
        return True, list(tokens[1:3])  # Return the two node tokens.
    if prefix == "C":  # Handle capacitors with two nodes.
        return True, list(tokens[1:3])  # Return the two node tokens.
    if prefix == "D":  # Handle diodes with two nodes.
        return True, list(tokens[1:3])  # Return the two node tokens.
    if prefix == "E" and _is_two_node_behavioral_controlled_source(prefix, tokens):  # Handle LTspice's behavioral VCVS shorthand with only output nodes.
        return True, list(tokens[1:3])  # Return only the two explicit output nodes.
    if prefix == "E":  # Handle VCVS elements with output and control nodes.
        return True, list(tokens[1:5])  # Return the four node tokens.
    if prefix == "F":  # Handle CCCS elements with two output nodes only.
        return True, list(tokens[1:3])  # Return the two node tokens.
    if prefix == "G" and _is_two_node_behavioral_controlled_source(prefix, tokens):  # Handle LTspice's behavioral VCCS shorthand with only output nodes.
        return True, list(tokens[1:3])  # Return only the two explicit output nodes.
    if prefix == "G":  # Handle VCCS elements with output and control nodes.
        return True, list(tokens[1:5])  # Return the four node tokens.
    if prefix == "H":  # Handle CCVS elements with two output nodes only.
        return True, list(tokens[1:3])  # Return the two node tokens.
    if prefix == "I":  # Handle independent current sources with two nodes.
        return True, list(tokens[1:3])  # Return the two node tokens.
    if prefix == "J":  # Handle JFET devices with drain, gate, and source.
        return True, list(tokens[1:4])  # Return the three node tokens.
    if prefix == "K":  # Ignore coupling statements because they reference inductors, not nets.
        return True, []  # Return an empty node list.
    if prefix == "L":  # Handle inductors with two nodes.
        return True, list(tokens[1:3])  # Return the two node tokens.
    if prefix == "M":  # Handle MOSFET devices with drain, gate, source, and bulk.
        return True, list(tokens[1:5])  # Return the four node tokens.
    if prefix == "O":  # Handle lossy transmission lines with four nodes.
        return True, list(tokens[1:5])  # Return the four node tokens.
    if prefix == "Q":  # Handle BJTs with either three or four connectivity nodes.
        if len(tokens) >= 6:  # Use the four-node form when a substrate node is present.
            return True, list(tokens[1:5])  # Return collector, base, emitter, and substrate nodes.
        return True, list(tokens[1:4])  # Return collector, base, and emitter nodes for the three-node form.
    if prefix == "R":  # Handle resistors with two nodes.
        return True, list(tokens[1:3])  # Return the two node tokens.
    if prefix == "S":  # Handle voltage-controlled switches with two output and two control nodes.
        return True, list(tokens[1:5])  # Return the four node tokens.
    if prefix == "T":  # Handle lossless transmission lines with four nodes.
        return True, list(tokens[1:5])  # Return the four node tokens.
    if prefix == "U":  # Handle uniform RC lines with three nodes.
        return True, list(tokens[1:4])  # Return the three node tokens.
    if prefix == "V":  # Handle independent voltage sources with two nodes.
        return True, list(tokens[1:3])  # Return the two node tokens.
    if prefix == "W":  # Handle current-controlled switches with two output nodes only.
        return True, list(tokens[1:3])  # Return the two node tokens.
    if prefix == "X":  # Handle subcircuit calls with variable node counts.
        positional_tokens = list(tokens[1:])  # Copy all tokens after the instance name.
        parameter_start_index = len(positional_tokens)  # Default the parameter boundary to the end of the token list.
        for index, token in enumerate(positional_tokens):  # Scan for the first named-parameter token.
            if "=" in token:  # Treat named-parameter tokens as the start of the parameter section.
                parameter_start_index = index  # Record the position of the first named parameter.
                break  # Stop scanning after the first parameter token.
        structural_tokens = positional_tokens[:parameter_start_index]  # Keep only nodes plus the subcircuit name.
        if len(structural_tokens) < 2:  # Require at least one node and one subcircuit name.
            return False, []  # Signal that node extraction failed.
        return True, structural_tokens[:-1]  # Return all structural tokens except the final subcircuit name.
    if prefix == "Z":  # Handle MESFET or IGBT devices with three nodes.
        return True, list(tokens[1:4])  # Return the three node tokens.
    if prefix == "@":  # Ignore FRA analyzer records because they do not add standard circuit nodes.
        return True, []  # Return an empty node list.
    if prefix == "&":  # Handle FRA probe records with four nodes.
        return True, list(tokens[1:5])  # Return the four probe node tokens.
    return False, []  # Signal failure for any unhandled prefix.


def _count_element_nodes(elements: Sequence[ParsedElement]) -> Dict[str, int]:  # Count how many times each relevant node appears across all element ports.
    node_counts: Dict[str, int] = {}  # Collect node occurrence counts keyed by node name.
    for element in elements:  # Walk every parsed device element.
        for node_name in element.nodes:  # Walk every connectivity node attached to the element.
            if _is_exempt_node(node_name):  # Skip ground and explicit no-connect nodes.
                continue  # Move to the next node because exempt nodes do not need counting.
            current_count = node_counts.get(node_name, 0)  # Read the current occurrence count safely.
            node_counts[node_name] = current_count + 1  # Increment the occurrence count for the node.
        for node_name in _extract_expression_nodes(element):  # Count additional node references embedded in behavioral expressions.
            if _is_exempt_node(node_name):  # Skip ground and explicit no-connect nodes inside expressions as well.
                continue  # Move to the next node because exempt nodes do not need counting.
            current_count = node_counts.get(node_name, 0)  # Read the current occurrence count safely.
            node_counts[node_name] = current_count + 1  # Increment the occurrence count for the referenced node.
    return node_counts  # Return the completed node-count mapping.


def _is_two_node_behavioral_controlled_source(prefix: str, tokens: Sequence[str]) -> bool:  # Detect LTspice's reduced-node behavioral E/G forms such as E1 out 0 G={G}.
    if prefix not in {"E", "G"}:  # Restrict this reduced-node detection to the controlled-source prefixes that support it in the fixture corpus.
        return False  # Return False because all other prefixes keep their existing node-count rules.
    if len(tokens) < 4:  # Require at least an instance token, two explicit nodes, and one payload token.
        return False  # Return False because shorter lines are always invalid.
    payload_tokens = tokens[3:]  # Read the source payload after the two explicit output nodes.
    if any("=" in token for token in payload_tokens):  # Treat inline assignments such as G={G} or VALUE={...} as the reduced-node behavioral form.
        return True  # Return True because the line uses the behavioral shorthand syntax.
    behavioral_keywords = {"VALUE", "VAL", "VOL", "CUR", "TABLE", "LAPLACE"}  # Cover the common LTspice behavioral-source keywords that replace the explicit control-node pair.
    return payload_tokens[0].upper() in behavioral_keywords  # Return True only when the leading payload token matches a known behavioral-source keyword.


def _extract_expression_nodes(element: ParsedElement) -> Tuple[str, ...]:  # Extract node names referenced inside behavioral voltage expressions for connectivity counting.
    expression_text = " ".join(element.tokens[1 + len(element.nodes) :])  # Collapse the non-node payload back into one expression string.
    if expression_text == "":  # Return early when the element carries no expression-like payload.
        return ()  # Return an empty tuple because there are no referenced nodes to count.
    referenced_nodes: List[str] = []  # Collect every node reference found inside the expression payload.
    seen_nodes: Set[str] = set()  # Deduplicate repeated node references inside the same element expression.
    for voltage_match in _NODE_VOLTAGE_REFERENCE_PATTERN.finditer(expression_text):  # Scan every V(node) or V(node1,node2) expression occurrence.
        for matched_node in voltage_match.groups():  # Walk both optional captured node names for the current voltage expression.
            if matched_node is None:  # Skip the optional second capture group when it is absent.
                continue  # Move to the next captured group.
            normalized_node = matched_node.strip()  # Normalize surrounding whitespace from the captured node token.
            if normalized_node == "" or normalized_node in seen_nodes:  # Skip empty captures and duplicates within the same element.
                continue  # Move to the next captured node.
            seen_nodes.add(normalized_node)  # Mark the node as seen inside this element expression.
            referenced_nodes.append(normalized_node)  # Preserve the referenced node in source order for later counting.
    return tuple(referenced_nodes)  # Return the collected referenced node names as an immutable tuple.


def _is_exempt_node(node_name: str) -> bool:  # Decide whether a node should be ignored by connectivity validation.
    uppercase_node = node_name.upper()  # Normalize the node name for case-insensitive checks.
    if uppercase_node in {"0", "GND"}:  # Treat the LTspice global ground names as exempt.
        return True  # Exempt global ground from the connectivity count rule.
    for exempt_prefix in _EXEMPT_NODE_PREFIXES:  # Check each supported no-connect prefix.
        if uppercase_node.startswith(exempt_prefix):  # Exempt explicit no-connect node labels.
            return True  # Exempt the named no-connect node.
    return False  # Require all other nodes to have at least two connections.


def _collect_nonblank_entries(lines: Sequence[str]) -> Tuple[bool, List[Tuple[int, str]]]:  # Collect normalized nonblank source lines with their line numbers.
    nonblank_entries: List[Tuple[int, str]] = []  # Collect line-number and stripped-text pairs.
    for line_number, raw_line in enumerate(lines, start=1):  # Walk every source line with a one-based line number.
        stripped_line = _strip_semicolon_comment(raw_line).strip()  # Remove semicolon comments and surrounding whitespace.
        if stripped_line == "":  # Skip lines that become empty after stripping.
            continue  # Move to the next line.
        nonblank_entries.append((line_number, stripped_line))  # Save the normalized nonblank line entry.
    if not nonblank_entries:  # Reject empty files or files containing only blank/comment lines.
        return False, []  # Signal that no nonblank content exists.
    return True, nonblank_entries  # Return the collected nonblank line entries.


def _strip_semicolon_comment(raw_line: str) -> str:  # Remove any inline semicolon comment from a source line.
    if ";" not in raw_line:  # Avoid splitting when no semicolon comment exists.
        return raw_line  # Return the original line unchanged.
    return raw_line.split(";", 1)[0]  # Return only the code portion before the first semicolon.


def _format_line_message(prefix: str, line_number: int) -> str:  # Build the required public error message with a line number suffix.
    return f"{prefix} Line {line_number}"  # Return the final user-facing message.


def _build_networkx_graph(elements: Sequence[ParsedElement], include_visual_labels: bool) -> nx.MultiGraph:  # Build a component-to-net multigraph from parsed device elements.
    graph = nx.MultiGraph()  # Create the multigraph that will back plotting and structural comparison.
    for element in elements:  # Walk every parsed device element in source order.
        component_node_id = _component_node_id(element)  # Derive a unique graph node id for the current component.
        component_attributes = {  # Assemble the normalized component attributes used by the graph.
            "kind": "component",  # Mark this node as a component node.
            "prefix": element.prefix,  # Preserve the device prefix for styling and comparison.
            "signature": _component_signature(element),  # Store the instance-name-free structural signature for comparison.
        }  # Finish the base component attribute dictionary.
        if include_visual_labels:  # Attach user-facing labels only when the graph is meant for rendering.
            component_attributes["label"] = element.tokens[0]  # Expose the original component instance name for the image renderer.
            component_attributes["value_label"] = _component_visual_value(element)  # Expose the primary component value/model text for the image renderer.
        graph.add_node(component_node_id, **component_attributes)  # Add the component node to the multigraph.
        for port_index, node_name in enumerate(element.nodes):  # Walk every connectivity node attached to the component in pin order.
            net_node_id = _net_node_id(node_name)  # Derive a stable graph node id for the electrical net.
            net_attributes = {  # Assemble the normalized net attributes used by the graph.
                "kind": "net",  # Mark this node as a net node.
                "net_class": _comparison_net_class(node_name),  # Preserve only the structural net class needed for comparison.
            }  # Finish the base net attribute dictionary.
            if include_visual_labels:  # Attach user-facing labels only when the graph is meant for rendering.
                net_attributes["label"] = node_name  # Expose the original net name for the image renderer.
            graph.add_node(net_node_id, **net_attributes)  # Add or update the net node in the multigraph.
            graph.add_edge(component_node_id, net_node_id, port=port_index)  # Connect the component pin to the net node with its port index preserved.
    return graph  # Return the completed multigraph.


def _component_node_id(element: ParsedElement) -> str:  # Build a unique graph node id for one parsed component.
    return f"component:{element.line_number}:{element.tokens[0]}"  # Combine line number and instance token into a stable unique id.


def _net_node_id(node_name: str) -> str:  # Build a stable graph node id for one electrical net name.
    return f"net:{node_name}"  # Prefix the raw node name so net ids do not collide with component ids.


def _component_signature(element: ParsedElement) -> Tuple[str, Tuple[str, ...]]:  # Build an instance-name-free structural signature for comparison.
    non_node_tokens = tuple(element.tokens[1 + len(element.nodes):])  # Drop the instance name and explicit connectivity nodes from the signature.
    return element.prefix, non_node_tokens  # Return the normalized component signature tuple.


def _component_visual_value(element: ParsedElement) -> str:  # Build a compact human-readable component value or model label for graph rendering.
    value_tokens = element.tokens[1 + len(element.nodes):]  # Drop the instance token and the extracted connectivity nodes.
    if not value_tokens:  # Return early when the component does not carry any remaining value-like tokens.
        return ""  # Render no secondary label for components without a stable non-node token.
    return " ".join(value_tokens)  # Preserve the remaining LTspice tokens as the displayed value/model label.


def _comparison_net_class(node_name: str) -> str:  # Normalize net names into comparison classes so ordinary node renaming is ignored.
    uppercase_name = node_name.upper()  # Normalize the net name for case-insensitive class checks.
    if uppercase_name in {"0", "GND"}:  # Preserve global ground as a special net class across comparisons.
        return "ground"  # Mark ground-like nodes with the dedicated ground class.
    return "net"  # Treat every other electrical node as a generic renameable net.


def _networkx_graph_node_match(first_attributes: Dict[str, object], second_attributes: Dict[str, object]) -> bool:  # Compare two graph nodes for structural equality.
    if first_attributes.get("kind") != second_attributes.get("kind"):  # Reject nodes whose graph roles differ.
        return False  # Return False because component nodes cannot match net nodes.
    if first_attributes.get("kind") == "component":  # Compare component nodes using their normalized structural signatures.
        return first_attributes.get("signature") == second_attributes.get("signature")  # Return True only when the component signatures match exactly.
    return first_attributes.get("net_class") == second_attributes.get("net_class")  # Compare net nodes using only their normalized comparison class.


from .ltspice_netlist_plot_networkx import ltspice_netlist_plot_networkx  # Re-export the plotting API from the dedicated module.
