"""LTspice netlist validation helpers and public API functions."""  # Document the module purpose.

from __future__ import annotations  # Postpone annotation evaluation for forward references.

from dataclasses import dataclass  # Use a small record type for parsed element lines.
from itertools import combinations  # Build component-to-component projected edges for plotting.
import math  # Compute simple node-layout geometry for PNG graph rendering.
import os  # Access filesystem and permission utilities.
import re  # Validate directive spelling and structure with regular expressions.
import struct  # Encode PNG header fields in network-ordered binary form.
from typing import Dict  # Type the node-count mapping.
from typing import List  # Type collections of lines and nodes.
from typing import Sequence  # Type immutable views over loaded line lists.
from typing import Tuple  # Type tuple-based helper results.
import zlib  # Compress PNG image payloads and compute chunk checksums.

import networkx as nx  # Build comparison and plotting graphs with the required dependency.
from networkx.algorithms import isomorphism  # Compare normalized netlist graphs structurally.

ValidationResult = Tuple[bool, str]  # Represent the public validator return shape.
ReadLinesResult = Tuple[bool, List[str], str]  # Represent file-read helper output.
DirectiveResult = Tuple[bool, str, str]  # Represent directive parsing success, name, and message.
ElementParseResult = Tuple[bool, List["ParsedElement"], int, str]  # Represent parsed element extraction.

_DIRECTIVE_PATTERN = re.compile(r"^\.(?P<name>[A-Za-z]+)(?:\s|$)")  # Match an LTspice dot-directive name.

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


def ltspice_netlist_plot_networkx(netlist_filepath: str, networkx_png_filepath: str, width: int = 1920, height: int = 1080) -> ValidationResult:  # Plot a validated LTspice netlist as a networkx-derived PNG image.
    validation_result = is_valid_ltspice_netlist_file(netlist_filepath)  # Validate the input netlist through the required public wrapper first.
    if not validation_result[0]:  # Stop immediately when the netlist is not fully valid.
        return validation_result  # Return the exact validation failure tuple unchanged.
    parse_result = _load_parsed_elements(netlist_filepath)  # Parse the validated file into graph-ready device elements.
    if not parse_result[0]:  # Stop when internal parsing unexpectedly fails after validation.
        return False, "Unable to plot network graph!"  # Return a stable plotting failure message.
    output_path_result = _coerce_path(networkx_png_filepath)  # Convert the caller-supplied PNG path into a usable filesystem string.
    if not output_path_result[0]:  # Stop when the output path cannot be converted safely.
        return False, "Unable to write PNG file!"  # Return a stable write-path failure message.
    if not isinstance(width, int) or not isinstance(height, int):  # Reject non-integer image dimensions before attempting layout or PNG encoding.
        return False, "Unable to plot network graph!"  # Return a stable plotting failure message for invalid dimension inputs.
    if width <= 0 or height <= 0:  # Reject zero or negative image dimensions before attempting layout or PNG encoding.
        return False, "Unable to plot network graph!"  # Return a stable plotting failure message for invalid dimension inputs.
    graph = _build_networkx_component_plot_graph(parse_result[1])  # Build the component-only plotting graph from the parsed device elements.
    try:  # Attempt to render and write the graph image to disk.
        _write_networkx_graph_png(graph, output_path_result[1], width, height)  # Draw the graph into a PNG file using the local renderer.
    except OSError:  # Catch filesystem write failures such as missing permissions or invalid parent directories.
        return False, "Unable to write PNG file!"  # Return a stable write failure message.
    except ValueError:  # Catch rendering precondition failures such as impossible image dimensions.
        return False, "Unable to plot network graph!"  # Return a stable plotting failure message.
    return True, ""  # Return success when the PNG file is written successfully.


def ltspice_netlist_structure_cmp(filepath1: str, filepath2: str) -> bool:  # Compare two validated LTspice netlists for structural equivalence while ignoring footer directives.
    first_validation_result = is_valid_ltspice_netlist_file(filepath1)  # Validate the first input file before attempting any comparison.
    if not first_validation_result[0]:  # Stop when the first file is not a valid LTspice netlist for this project.
        return False  # Return False because comparison cannot proceed on an invalid first file.
    second_validation_result = is_valid_ltspice_netlist_file(filepath2)  # Validate the second input file before attempting any comparison.
    if not second_validation_result[0]:  # Stop when the second file is not a valid LTspice netlist for this project.
        return False  # Return False because comparison cannot proceed on an invalid second file.
    first_parse_result = _load_parsed_elements(filepath1)  # Parse the first validated file into device elements.
    if not first_parse_result[0]:  # Stop when internal parsing unexpectedly fails after validation.
        return False  # Return False because the first graph cannot be built reliably.
    second_parse_result = _load_parsed_elements(filepath2)  # Parse the second validated file into device elements.
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
        path_string = os.fspath(filepath)  # Convert a string or path-like object into a filesystem path string.
    except TypeError:  # Catch invalid path-like objects.
        return False, ""  # Signal failure so the caller can map it to the public API error.
    return True, path_string  # Return the usable path string.


def _load_parsed_elements(filepath: str) -> ElementParseResult:  # Load a file and parse its device elements through the existing internal helpers.
    read_result = _read_text_file_lines(filepath)  # Re-read the file through the shared safe text loader.
    if not read_result[0]:  # Stop when the file cannot be read safely.
        return False, [], 0, "read_error"  # Return a generic parse failure marker for the caller.
    return _parse_elements(read_result[1])  # Parse the loaded source lines into structured device elements.


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


def _validate_connectivity(lines: Sequence[str]) -> Tuple[bool, int]:  # Validate that every non-exempt node is connected in at least two element pins.
    parse_result = _parse_elements(lines)  # Parse device lines into connectivity-aware element records.
    if not parse_result[0]:  # Stop when element parsing fails.
        return False, parse_result[2]  # Report the parser's failing line number.
    elements = parse_result[1]  # Extract the parsed elements after confirming parsing succeeded.
    node_counts = _count_element_nodes(elements)  # Count how many times each relevant node appears across all device ports.
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
    if len(instance_name) < 2:  # Require an instance name longer than the one-character prefix.
        return False, "short_instance_name"  # Signal an instance-name failure.
    if re.match(r"^[A-Za-z@&]\d+[A-Za-z].*$", instance_name) is not None:  # Reject merged instance-name and node-name patterns such as R1Vcc.
        return False, "merged_instance_name"  # Signal an instance-name spacing failure.
    prefix = instance_name[0].upper()  # Normalize the leading device prefix character.
    if prefix not in _VALID_DEVICE_PREFIXES:  # Reject unsupported device prefixes.
        return False, "invalid_prefix"  # Signal an invalid-prefix failure.
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
    if prefix == "E":  # Handle VCVS elements with output and control nodes.
        return True, list(tokens[1:5])  # Return the four node tokens.
    if prefix == "F":  # Handle CCCS elements with two output nodes only.
        return True, list(tokens[1:3])  # Return the two node tokens.
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
    return node_counts  # Return the completed node-count mapping.


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


def _build_networkx_component_plot_graph(elements: Sequence[ParsedElement]) -> nx.MultiGraph:  # Build a component-only projection graph for PNG plotting.
    graph = nx.MultiGraph()  # Create the multigraph used only for component-level visualization.
    node_to_component_ids: Dict[str, List[str]] = {}  # Track which plotted components touch each electrical net.
    ground_component_ids: List[str] = []  # Track the components that connect directly to ground-like nets.
    for element in elements:  # Walk every parsed device element in source order.
        component_node_id = _component_node_id(element)  # Derive the stable node id for the current component.
        graph.add_node(
            component_node_id,
            kind="component",
            prefix=element.prefix,
            label=element.tokens[0],
            value_label=_component_visual_value(element),
        )  # Add the component node with the labels required by the PNG renderer.
        for node_name in element.nodes:  # Associate each electrical net with the components that touch it.
            if _is_ground_node(node_name):  # Preserve visible ground connectivity through a dedicated visual ground symbol.
                if component_node_id not in ground_component_ids:  # Avoid duplicate ground membership when a device references ground more than once.
                    ground_component_ids.append(component_node_id)  # Record that the current component connects directly to ground.
                continue  # Move to the next node because ground is rendered through a dedicated symbol, not a net node.
            if _is_exempt_node(node_name):  # Skip no-connect pseudo-nets from the component projection.
                continue  # Move to the next node because exempt nodes would only add clutter to the visual projection.
            component_ids = node_to_component_ids.setdefault(node_name, [])  # Load or create the component list for this electrical net.
            if component_node_id not in component_ids:  # Avoid duplicate component membership when a device references the same net twice.
                component_ids.append(component_node_id)  # Record that the current component touches this electrical net.
    for node_name, component_ids in node_to_component_ids.items():  # Project every shared electrical net into component-to-component edges.
        if len(component_ids) < 2:  # Skip nets that touch only one plotted component because they do not create a visible connection.
            continue  # Move to the next electrical net.
        for first_component_id, second_component_id in combinations(sorted(component_ids), 2):  # Connect each pair of components that share the same net.
            graph.add_edge(first_component_id, second_component_id, net=node_name)  # Preserve the original net name as edge metadata for deterministic offsets.
    if ground_component_ids:  # Add one dedicated visual ground node when the netlist contains any ground-connected component.
        ground_node_id = "ground:GND"  # Use one stable plotting-only node id for the shared ground symbol.
        graph.add_node(ground_node_id, kind="ground", label="GND")  # Add the dedicated visual ground symbol node.
        for component_node_id in sorted(ground_component_ids):  # Connect every ground-referenced component to the visual ground symbol.
            graph.add_edge(component_node_id, ground_node_id, net="GND")  # Preserve the ground edge as a visible connection in the plot.
    return graph  # Return the completed component-only plotting graph.


def _comparison_net_class(node_name: str) -> str:  # Normalize net names into comparison classes so ordinary node renaming is ignored.
    uppercase_name = node_name.upper()  # Normalize the net name for case-insensitive class checks.
    if uppercase_name in {"0", "GND"}:  # Preserve global ground as a special net class across comparisons.
        return "ground"  # Mark ground-like nodes with the dedicated ground class.
    if uppercase_name.startswith("NC_") or uppercase_name.startswith("NC-"):  # Preserve only explicit project-style no-connect markers as a dedicated class.
        return "no_connect"  # Mark only explicit no-connect labels with the dedicated no-connect class.
    return "net"  # Treat every other electrical node as a generic renameable net.


def _networkx_graph_node_match(first_attributes: Dict[str, object], second_attributes: Dict[str, object]) -> bool:  # Compare two graph nodes for structural equality.
    if first_attributes.get("kind") != second_attributes.get("kind"):  # Reject nodes whose graph roles differ.
        return False  # Return False because component nodes cannot match net nodes.
    if first_attributes.get("kind") == "component":  # Compare component nodes using their normalized structural signatures.
        return first_attributes.get("signature") == second_attributes.get("signature")  # Return True only when the component signatures match exactly.
    return first_attributes.get("net_class") == second_attributes.get("net_class")  # Compare net nodes using only their normalized comparison class.


def _write_networkx_graph_png(graph: nx.MultiGraph, output_path: str, width: int, height: int) -> None:  # Render a component-only graph into a standalone PNG file using the caller-requested dimensions.
    component_nodes = sorted(node_id for node_id, attributes in graph.nodes(data=True) if attributes.get("kind") == "component")  # Collect component node ids in deterministic order.
    ground_nodes = sorted(node_id for node_id, attributes in graph.nodes(data=True) if attributes.get("kind") == "ground")  # Collect plotting-only ground symbol node ids.
    canvas = bytearray(width * height * 3)  # Allocate a flat RGB canvas for the PNG renderer.
    _fill_canvas(canvas, width, height, _PNG_BACKGROUND)  # Paint the full canvas with the light background color.
    positions = _assign_component_plot_positions(graph, component_nodes + ground_nodes, width, height)  # Place components and the visual ground symbol using a deterministic NetworkX spring layout.
    for first_node, second_node, edge_key, edge_attributes in graph.edges(keys=True, data=True):  # Draw every component-to-component edge in deterministic multigraph order.
        _draw_graph_edge(
            canvas,
            width,
            height,
            positions[first_node],
            positions[second_node],
            str(graph.nodes[first_node].get("kind", "")),
            str(graph.nodes[second_node].get("kind", "")),
            edge_attributes.get("port", 0),
            edge_key,
        )  # Render the current edge with anchors that attach cleanly to the component boxes and ground symbols.
    for component_node_id in component_nodes:  # Draw every component node after the edges so boxes remain visible.
        center_x, center_y = positions[component_node_id]  # Read the component center coordinates from the layout map.
        fill_color = _component_fill_color(graph.nodes[component_node_id].get("prefix", "?"))  # Choose a stable component fill color from the device prefix.
        _draw_rectangle(
            canvas,
            width,
            height,
            center_x - _COMPONENT_BOX_HALF_WIDTH,
            center_y - _COMPONENT_BOX_HALF_HEIGHT,
            center_x + _COMPONENT_BOX_HALF_WIDTH,
            center_y + _COMPONENT_BOX_HALF_HEIGHT,
            fill_color,
            _PNG_COMPONENT_BORDER,
        )  # Render the component as a filled bordered box.
        _draw_centered_text(
            canvas,
            width,
            height,
            center_x,
            center_y - 4,
            str(graph.nodes[component_node_id].get("label", "")),
            _PNG_TEXT_COLOR,
            2,
            16,
        )  # Render the component instance name such as R1 inside the component box.
        value_label = str(graph.nodes[component_node_id].get("value_label", ""))  # Read the secondary component label for the current node.
        if value_label != "":  # Skip the secondary label when the component does not carry a stable displayed value.
            _draw_centered_text(canvas, width, height, center_x, center_y + 28, value_label, _PNG_TEXT_MUTED, 2, 22)  # Render the value/model text such as 10k below the box.
    for ground_node_id in ground_nodes:  # Draw the visual ground symbol after the edges so its strokes remain crisp.
        center_x, center_y = positions[ground_node_id]  # Read the ground symbol center coordinates from the layout map.
        _draw_ground_symbol(canvas, width, height, center_x, center_y, _PNG_GROUND_COLOR)  # Render the dedicated ground symbol.
        _draw_centered_text(canvas, width, height, center_x, center_y + 24, str(graph.nodes[ground_node_id].get("label", "GND")), _PNG_TEXT_MUTED, 1, 8)  # Render a short GND label below the symbol.
    _write_png_rgb(output_path, width, height, canvas)  # Encode and write the final RGB canvas as a PNG file.


def _assign_component_plot_positions(graph: nx.MultiGraph, plot_node_ids: Sequence[str], width: int, height: int) -> Dict[str, Tuple[int, int]]:  # Assign deterministic spring-layout positions for the component-only plot graph.
    if not plot_node_ids:  # Return early when the graph is empty.
        return {}  # Return an empty position map for the empty graph.
    left_margin = 180  # Leave a generous horizontal margin for the higher-resolution labels.
    right_margin = width - 180  # Leave a generous horizontal margin for the higher-resolution labels.
    top_margin = 160  # Leave extra room above the top row for the larger glyph scale.
    bottom_margin = height - 160  # Leave extra room below the bottom row for value labels.
    if bottom_margin <= top_margin or right_margin <= left_margin:  # Guard against impossible image dimensions before computing the layout.
        raise ValueError("image_dimensions_too_small")  # Signal that the computed image dimensions are invalid.
    if len(plot_node_ids) == 1:  # Special-case one-node plots so they render centered without calling the spring layout.
        only_node_id = plot_node_ids[0]  # Read the single plotted node id.
        return {only_node_id: ((left_margin + right_margin) // 2, (top_margin + bottom_margin) // 2)}  # Center the lone plotted node inside the drawable area.
    spring_positions = nx.spring_layout(graph, seed=7, k=1.35 / math.sqrt(len(plot_node_ids)), iterations=300)  # Use a deterministic NetworkX layout for a clearer higher-resolution component graph.
    x_values = [spring_positions[node_id][0] for node_id in plot_node_ids]  # Collect the raw spring-layout x coordinates for normalization.
    y_values = [spring_positions[node_id][1] for node_id in plot_node_ids]  # Collect the raw spring-layout y coordinates for normalization.
    minimum_x = min(x_values)  # Read the smallest x coordinate for normalization.
    maximum_x = max(x_values)  # Read the largest x coordinate for normalization.
    minimum_y = min(y_values)  # Read the smallest y coordinate for normalization.
    maximum_y = max(y_values)  # Read the largest y coordinate for normalization.
    x_span = maximum_x - minimum_x  # Compute the total x-range produced by the spring layout.
    y_span = maximum_y - minimum_y  # Compute the total y-range produced by the spring layout.
    positions: Dict[str, Tuple[int, int]] = {}  # Collect the scaled integer image coordinates for each component node.
    for node_id in plot_node_ids:  # Walk every plotted node in deterministic order.
        raw_x, raw_y = spring_positions[node_id]  # Read the normalized spring-layout coordinate pair for the current plotted node.
        normalized_x = 0.5 if x_span == 0 else (raw_x - minimum_x) / x_span  # Normalize the x coordinate into the [0, 1] interval.
        normalized_y = 0.5 if y_span == 0 else (raw_y - minimum_y) / y_span  # Normalize the y coordinate into the [0, 1] interval.
        center_x = int(round(left_margin + normalized_x * (right_margin - left_margin)))  # Scale the normalized x coordinate into the drawable image area.
        center_y = int(round(top_margin + normalized_y * (bottom_margin - top_margin)))  # Scale the normalized y coordinate into the drawable image area.
        positions[node_id] = (center_x, center_y)  # Save the scaled image-space position for the current plotted node.
    return positions  # Return the completed position map for the component plot graph.


def _draw_graph_edge(canvas: bytearray, width: int, height: int, first_point: Tuple[int, int], second_point: Tuple[int, int], first_kind: str, second_kind: str, port_index: int, edge_key: int) -> None:  # Draw one graph edge with anchors that touch the visual node shapes cleanly.
    offset = (port_index * 3) + (edge_key * 2)  # Compute a small deterministic offset so repeated edges do not fully overlap.
    first_anchor = _plot_node_edge_anchor(first_point, second_point, first_kind, offset)  # Place the first endpoint on the first node perimeter.
    second_anchor = _plot_node_edge_anchor(second_point, first_point, second_kind, offset)  # Place the second endpoint on the second node perimeter.
    _draw_line(canvas, width, height, first_anchor[0], first_anchor[1], second_anchor[0], second_anchor[1], _PNG_EDGE_COLOR)  # Render the edge as one anchored line segment.


def _plot_node_edge_anchor(origin: Tuple[int, int], target: Tuple[int, int], node_kind: str, offset: int) -> Tuple[int, int]:  # Compute one edge anchor on the perimeter of a plotted node shape.
    origin_x, origin_y = origin  # Unpack the node center coordinates.
    target_x, target_y = target  # Unpack the other endpoint coordinates used to determine the edge direction.
    if node_kind == "ground":  # Attach ground edges to the top of the rendered ground symbol.
        horizontal_offset = max(-(_GROUND_SYMBOL_HALF_WIDTH - 2), min(_GROUND_SYMBOL_HALF_WIDTH - 2, offset))  # Keep the offset inside the ground symbol width.
        return origin_x + horizontal_offset, origin_y - _GROUND_SYMBOL_HEIGHT  # Return the ground-symbol anchor at the top of the vertical stem.
    vertical_offset = max(-(_COMPONENT_BOX_HALF_HEIGHT - 2), min(_COMPONENT_BOX_HALF_HEIGHT - 2, offset))  # Keep the offset inside the component height when anchoring to a box.
    horizontal_anchor = origin_x + _COMPONENT_BOX_HALF_WIDTH if target_x >= origin_x else origin_x - _COMPONENT_BOX_HALF_WIDTH  # Choose the outward-facing box side.
    return horizontal_anchor, origin_y + vertical_offset  # Return the component perimeter anchor.


def _component_fill_color(prefix: str) -> Tuple[int, int, int]:  # Choose a stable component fill color from a device prefix.
    palette_index = ord(prefix[0]) % len(_PNG_COMPONENT_COLORS)  # Map the prefix character into the compact component color palette.
    return _PNG_COMPONENT_COLORS[palette_index]  # Return the selected component fill color tuple.


def _is_ground_node(node_name: str) -> bool:  # Decide whether a node name refers to the global ground connection.
    return node_name.upper() in {"0", "GND"}  # Treat LTspice numeric and named ground identically for plotting.


def _normalize_bitmap_text(text: str, max_characters: int) -> str:  # Normalize arbitrary node labels into the limited bitmap-font character set.
    normalized_characters: List[str] = []  # Collect normalized characters one by one.
    for raw_character in text:  # Walk each source character in order.
        if raw_character == "µ" or raw_character == "μ":  # Replace Greek mu variants with the ASCII letter used in LTspice values.
            candidate_character = "U"  # Render the micro prefix as U so the bitmap font stays ASCII-only.
        elif raw_character.isalpha():  # Normalize alphabetic characters to uppercase because the font is uppercase-only.
            candidate_character = raw_character.upper()  # Convert alphabetic characters into the font alphabet.
        else:  # Preserve supported punctuation and digits directly.
            candidate_character = raw_character  # Keep the non-alphabetic character unchanged for the glyph lookup.
        normalized_characters.append(candidate_character if candidate_character in _BITMAP_FONT_GLYPHS else "?")  # Replace unsupported glyphs with a visible fallback.
    normalized_text = "".join(normalized_characters).strip()  # Recombine the glyphs and trim surrounding whitespace.
    if normalized_text == "":  # Return early when nothing printable remains.
        return ""  # Skip rendering blank labels.
    if len(normalized_text) <= max_characters:  # Return early when the label already fits.
        return normalized_text  # Keep the normalized text unchanged.
    if max_characters <= 3:  # Guard against a degenerate truncation budget.
        return normalized_text[:max_characters]  # Return the hard-truncated text when no room exists for an ellipsis marker.
    return normalized_text[: max_characters - 3] + "..."  # Add an ASCII ellipsis marker to visibly show truncation.


def _draw_centered_text(canvas: bytearray, width: int, height: int, center_x: int, top_y: int, text: str, color: Tuple[int, int, int], scale: int, max_characters: int) -> None:  # Draw one normalized text label centered around a given x coordinate.
    normalized_text = _normalize_bitmap_text(text, max_characters)  # Normalize the text into printable bitmap glyphs.
    if normalized_text == "":  # Skip drawing when the label collapses to nothing printable.
        return  # Return immediately because there is nothing meaningful to render.
    text_width = _bitmap_text_width(normalized_text, scale)  # Measure the label width before centering.
    _draw_text(canvas, width, height, center_x - text_width // 2, top_y, normalized_text, color, scale, max_characters)  # Draw the centered label using the shared bitmap text helper.


def _draw_text(canvas: bytearray, width: int, height: int, left_x: int, top_y: int, text: str, color: Tuple[int, int, int], scale: int, max_characters: int) -> None:  # Draw one normalized text label from a given left origin.
    normalized_text = _normalize_bitmap_text(text, max_characters)  # Normalize the text into printable bitmap glyphs.
    if normalized_text == "":  # Skip drawing when the label collapses to nothing printable.
        return  # Return immediately because there is nothing meaningful to render.
    cursor_x = left_x  # Start drawing at the requested left origin.
    for character in normalized_text:  # Walk each printable character in sequence.
        glyph_rows = _BITMAP_FONT_GLYPHS.get(character, _BITMAP_FONT_GLYPHS["?"])  # Look up the 5x7 bitmap glyph for the current character.
        for row_index, glyph_row in enumerate(glyph_rows):  # Walk each row of the glyph bitmap.
            for column_index, bit in enumerate(glyph_row):  # Walk each column bit in the current glyph row.
                if bit != "1":  # Skip unset pixels so only the visible glyph strokes are painted.
                    continue  # Move to the next glyph pixel when the current bit is empty.
                for delta_y in range(scale):  # Expand the glyph vertically when scaled.
                    for delta_x in range(scale):  # Expand the glyph horizontally when scaled.
                        _set_pixel(canvas, width, height, cursor_x + column_index * scale + delta_x, top_y + row_index * scale + delta_y, color)  # Paint the scaled glyph pixel on the canvas.
        cursor_x += (5 * scale) + scale  # Advance by the glyph width plus one scaled pixel of letter spacing.


def _bitmap_text_width(text: str, scale: int) -> int:  # Measure the rendered width of a normalized bitmap-font string.
    if text == "":  # Return early for empty labels.
        return 0  # Measure empty text as zero width.
    return len(text) * (5 * scale) + (len(text) - 1) * scale  # Account for the five-pixel glyph width plus one scaled pixel of spacing per interior gap.


def _fill_canvas(canvas: bytearray, width: int, height: int, color: Tuple[int, int, int]) -> None:  # Paint the entire RGB canvas with one solid background color.
    red_channel, green_channel, blue_channel = color  # Unpack the requested RGB background color.
    for pixel_offset in range(0, width * height * 3, 3):  # Walk every pixel position across the flat RGB byte buffer.
        canvas[pixel_offset] = red_channel  # Write the red channel byte for the current pixel.
        canvas[pixel_offset + 1] = green_channel  # Write the green channel byte for the current pixel.
        canvas[pixel_offset + 2] = blue_channel  # Write the blue channel byte for the current pixel.


def _set_pixel(canvas: bytearray, width: int, height: int, x_position: int, y_position: int, color: Tuple[int, int, int]) -> None:  # Paint one pixel when the requested position lies inside the canvas.
    if x_position < 0 or y_position < 0 or x_position >= width or y_position >= height:  # Ignore drawing requests that land outside the RGB canvas.
        return  # Return immediately because the pixel lies outside the image bounds.
    pixel_offset = (y_position * width + x_position) * 3  # Convert the pixel coordinates into a flat RGB byte offset.
    canvas[pixel_offset] = color[0]  # Write the red channel byte for the selected pixel.
    canvas[pixel_offset + 1] = color[1]  # Write the green channel byte for the selected pixel.
    canvas[pixel_offset + 2] = color[2]  # Write the blue channel byte for the selected pixel.


def _draw_line(canvas: bytearray, width: int, height: int, start_x: int, start_y: int, end_x: int, end_y: int, color: Tuple[int, int, int]) -> None:  # Draw a straight line segment using integer Bresenham stepping.
    delta_x = abs(end_x - start_x)  # Compute the absolute horizontal travel distance for the line segment.
    delta_y = -abs(end_y - start_y)  # Compute the negative absolute vertical travel distance for the line segment.
    step_x = 1 if start_x < end_x else -1  # Choose the horizontal step direction that moves the cursor toward the endpoint.
    step_y = 1 if start_y < end_y else -1  # Choose the vertical step direction that moves the cursor toward the endpoint.
    error_term = delta_x + delta_y  # Initialize the Bresenham accumulated error term.
    current_x = start_x  # Start the drawing cursor at the source x coordinate.
    current_y = start_y  # Start the drawing cursor at the source y coordinate.
    while True:  # Iterate until the cursor reaches the target endpoint.
        _set_pixel(canvas, width, height, current_x, current_y, color)  # Paint the current line pixel on the RGB canvas.
        if current_x == end_x and current_y == end_y:  # Stop once the line endpoint has been painted.
            break  # Exit the Bresenham loop at the destination pixel.
        doubled_error = error_term * 2  # Double the error term to decide which axes to advance next.
        if doubled_error >= delta_y:  # Advance horizontally when the horizontal error threshold is met.
            error_term += delta_y  # Update the accumulated error after the horizontal movement.
            current_x += step_x  # Move the drawing cursor one step horizontally toward the endpoint.
        if doubled_error <= delta_x:  # Advance vertically when the vertical error threshold is met.
            error_term += delta_x  # Update the accumulated error after the vertical movement.
            current_y += step_y  # Move the drawing cursor one step vertically toward the endpoint.


def _draw_rectangle(canvas: bytearray, width: int, height: int, left: int, top: int, right: int, bottom: int, fill_color: Tuple[int, int, int], border_color: Tuple[int, int, int]) -> None:  # Draw a filled bordered rectangle for a component node.
    for y_position in range(top, bottom + 1):  # Walk every scanline covered by the rectangle.
        for x_position in range(left, right + 1):  # Walk every pixel covered by the current scanline.
            is_border_pixel = x_position in {left, right} or y_position in {top, bottom}  # Detect whether the current pixel lies on the rectangle border.
            _set_pixel(canvas, width, height, x_position, y_position, border_color if is_border_pixel else fill_color)  # Paint either the border color or the fill color.


def _draw_ground_symbol(canvas: bytearray, width: int, height: int, center_x: int, center_y: int, color: Tuple[int, int, int]) -> None:  # Draw a standard three-bar ground symbol centered around a vertical stem.
    stem_top_y = center_y - _GROUND_SYMBOL_HEIGHT  # Place the top of the vertical stem above the ground bars.
    stem_bottom_y = center_y - 4  # Stop the stem just above the top horizontal ground bar.
    _draw_line(canvas, width, height, center_x, stem_top_y, center_x, stem_bottom_y, color)  # Draw the vertical ground stem first.
    _draw_line(canvas, width, height, center_x - 18, center_y, center_x + 18, center_y, color)  # Draw the widest ground bar.
    _draw_line(canvas, width, height, center_x - 12, center_y + 6, center_x + 12, center_y + 6, color)  # Draw the middle ground bar.
    _draw_line(canvas, width, height, center_x - 6, center_y + 12, center_x + 6, center_y + 12, color)  # Draw the shortest ground bar.


def _draw_circle(canvas: bytearray, width: int, height: int, center_x: int, center_y: int, radius: int, fill_color: Tuple[int, int, int], border_color: Tuple[int, int, int]) -> None:  # Draw a filled bordered circle for a net node.
    radius_squared = radius * radius  # Precompute the filled-circle radius threshold.
    border_inner_squared = max(0, (radius - 2) * (radius - 2))  # Precompute the inner threshold used to distinguish border pixels from fill pixels.
    for y_position in range(center_y - radius, center_y + radius + 1):  # Walk every scanline touched by the circle bounding box.
        for x_position in range(center_x - radius, center_x + radius + 1):  # Walk every pixel touched by the current scanline.
            delta_x = x_position - center_x  # Measure the horizontal distance from the current pixel to the circle center.
            delta_y = y_position - center_y  # Measure the vertical distance from the current pixel to the circle center.
            distance_squared = delta_x * delta_x + delta_y * delta_y  # Compute the squared radial distance from the center.
            if distance_squared > radius_squared:  # Skip pixels that lie outside the circle radius.
                continue  # Move to the next candidate pixel because it is outside the circle.
            pixel_color = border_color if distance_squared >= border_inner_squared else fill_color  # Choose border color near the perimeter and fill color elsewhere.
            _set_pixel(canvas, width, height, x_position, y_position, pixel_color)  # Paint the current circle pixel onto the canvas.


def _write_png_rgb(output_path: str, width: int, height: int, canvas: bytearray) -> None:  # Encode a flat RGB canvas into a standards-compliant PNG file.
    if width <= 0 or height <= 0:  # Guard against impossible image dimensions before encoding.
        raise ValueError("invalid_image_dimensions")  # Signal that the caller computed invalid image dimensions.
    parent_directory = os.path.dirname(output_path)  # Resolve the parent directory for the requested PNG output path.
    if parent_directory != "":  # Create the output directory tree only when the caller provided one.
        os.makedirs(parent_directory, exist_ok=True)  # Ensure the parent directory exists before writing the PNG file.
    scanlines = bytearray()  # Collect the PNG scanline payload with one filter byte per row.
    row_width = width * 3  # Compute the number of RGB bytes stored in each image row.
    for row_index in range(height):  # Walk every encoded image row in top-to-bottom order.
        scanlines.append(0)  # Prefix the row with PNG filter type zero for unfiltered scanlines.
        row_start = row_index * row_width  # Compute the flat RGB offset where the current row begins.
        row_end = row_start + row_width  # Compute the flat RGB offset where the current row ends.
        scanlines.extend(canvas[row_start:row_end])  # Append the raw RGB bytes for the current row to the scanline payload.
    compressed_payload = zlib.compress(bytes(scanlines), level=9)  # Compress the PNG scanlines with the standard zlib deflater.
    png_header = struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)  # Encode the IHDR payload for an 8-bit truecolor non-interlaced PNG.
    with open(output_path, "wb") as file_handle:  # Open the output file in binary write mode for PNG serialization.
        file_handle.write(b"\x89PNG\r\n\x1a\n")  # Write the fixed PNG file signature.
        file_handle.write(_png_chunk(b"IHDR", png_header))  # Write the IHDR chunk containing the image dimensions and pixel format.
        file_handle.write(_png_chunk(b"IDAT", compressed_payload))  # Write the compressed image data chunk.
        file_handle.write(_png_chunk(b"IEND", b""))  # Write the terminal IEND chunk to finish the PNG stream.


def _png_chunk(chunk_type: bytes, chunk_payload: bytes) -> bytes:  # Serialize one PNG chunk with its length prefix and CRC checksum.
    checksum = zlib.crc32(chunk_type + chunk_payload) & 0xFFFFFFFF  # Compute the unsigned CRC-32 over the chunk type and payload bytes.
    return struct.pack("!I", len(chunk_payload)) + chunk_type + chunk_payload + struct.pack("!I", checksum)  # Return the complete serialized chunk bytes.
