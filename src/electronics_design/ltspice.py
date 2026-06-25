"""LTspice netlist validation helpers and public API functions."""  # Document the module purpose.

from __future__ import annotations  # Postpone annotation evaluation for forward references.

from dataclasses import dataclass  # Use a small record type for parsed element lines.
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

_VALID_ASC_KEYWORDS = {  # Define the supported line-leading keywords for LTspice schematic files.
    "VERSION",  # Schematic file format version header.
    "SHEET",  # Sheet metadata line.
    "WIRE",  # Electrical wire segment.
    "FLAG",  # Net label or ground flag.
    "DATAFLAG",  # Data flag expression marker.
    "SYMBOL",  # Symbol placement line.
    "WINDOW",  # Symbol attribute window line.
    "SYMATTR",  # Symbol attribute assignment line.
    "TEXT",  # Annotation or directive carrier line.
    "LINE",  # Decorative line primitive.
    "RECTANGLE",  # Decorative rectangle primitive.
    "CIRCLE",  # Decorative circle primitive.
    "ARC",  # Decorative arc primitive.
    "IOPIN",  # Hierarchical I/O pin marker.
    "BUSTAP",  # Bus tap primitive.
}  # Finish the ASC keyword whitelist.

_ASC_SYMBOL_ORIENTATIONS = {  # Define the accepted LTspice symbol orientation tokens.
    "R0",  # Rotate zero degrees.
    "R90",  # Rotate ninety degrees.
    "R180",  # Rotate one hundred eighty degrees.
    "R270",  # Rotate two hundred seventy degrees.
    "M0",  # Mirror zero degrees.
    "M90",  # Mirror ninety degrees.
    "M180",  # Mirror one hundred eighty degrees.
    "M270",  # Mirror two hundred seventy degrees.
}  # Finish the orientation whitelist.

_ASC_TEXT_JUSTIFICATIONS = {  # Define the accepted LTspice text and window justification tokens.
    "LEFT",  # Left-aligned horizontal text.
    "CENTER",  # Center-aligned horizontal text.
    "RIGHT",  # Right-aligned horizontal text.
    "TOP",  # Top-aligned text.
    "BOTTOM",  # Bottom-aligned text.
    "VLEFT",  # Left-aligned vertical text.
    "VCENTER",  # Center-aligned vertical text.
    "VRIGHT",  # Right-aligned vertical text.
    "VTOP",  # Top-aligned vertical text.
    "VBOTTOM",  # Bottom-aligned vertical text.
    "INVISIBLE",  # Hidden text or window.
}  # Finish the justification whitelist.

_ASC_DRAWING_WIDTHS = {  # Define the accepted LTspice drawing width tokens.
    "NORMAL",  # Default line width.
    "WIDE",  # Wider drawing line width.
}  # Finish the drawing width whitelist.

_ASC_IOPIN_POLARITIES = {  # Define the accepted LTspice IOPIN direction markers.
    "IN",  # Input pin direction.
    "OUT",  # Output pin direction.
    "BIDIR",  # Bidirectional pin direction.
    "I",  # Short-form input direction.
    "O",  # Short-form output direction.
    "B",  # Short-form bidirectional direction.
}  # Finish the IOPIN polarity whitelist.

_EXEMPT_NODE_PREFIXES = ("NC", "NC_", "NC-")  # Exempt explicit no-connect node names from connectivity checks.

_PNG_BACKGROUND = (248, 250, 252)  # Use a light background for generated network graph images.
_PNG_EDGE_COLOR = (148, 163, 184)  # Use a muted line color for component-to-net edges.
_PNG_NET_FILL = (37, 99, 235)  # Use a blue fill color for net nodes in the generated graph.
_PNG_NET_BORDER = (30, 64, 175)  # Use a darker blue border for net nodes in the generated graph.
_PNG_COMPONENT_BORDER = (30, 41, 59)  # Use a dark neutral border for component nodes in the generated graph.
_PNG_COMPONENT_COLORS = [  # Cycle through a compact palette so different component prefixes are easy to distinguish.
    (251, 191, 36),  # Amber component fill color.
    (52, 211, 153),  # Emerald component fill color.
    (96, 165, 250),  # Sky component fill color.
    (248, 113, 113),  # Red component fill color.
    (196, 181, 253),  # Violet component fill color.
    (244, 114, 182),  # Pink component fill color.
]  # Finish the component fill palette.


@dataclass(frozen=True)  # Freeze parsed element records so tests and callers can rely on immutability.
class ParsedElement:  # Represent a parsed device line and its connectivity nodes.
    line_number: int  # Store the one-based source line number.
    prefix: str  # Store the validated device prefix.
    tokens: List[str]  # Store the whitespace-tokenized line content without comments.
    nodes: List[str]  # Store the extracted connectivity nodes for the element.


def is_valid_ltspice_asc_header(filepath: str) -> ValidationResult:  # Validate the opening structure of an LTspice ASC schematic file.
    read_result = _read_text_file_lines(filepath)  # Load the file lines through the shared safe reader.
    if not read_result[0]:  # Stop immediately when the shared file reader reports an error.
        return False, read_result[2]  # Propagate the exact file access error message.
    header_result = _validate_asc_header_lines(read_result[1])  # Validate the ASC header once the file is available.
    if not header_result[0]:  # Stop when a header problem is detected.
        return False, _format_line_message("Header information is invalid!", header_result[1])  # Return the required header error message.
    return True, ""  # Return success when the ASC header validates successfully.


def is_valid_ltspice_asc_spacing(filepath: str) -> ValidationResult:  # Validate line-level spacing and token structure for an LTspice ASC file.
    read_result = _read_text_file_lines(filepath)  # Load the file lines through the shared safe reader.
    if not read_result[0]:  # Stop immediately when the shared file reader reports an error.
        return False, read_result[2]  # Propagate the exact file access error message.
    spacing_result = _validate_asc_spacing_lines(read_result[1])  # Validate the ASC line structure now that reading succeeded.
    if not spacing_result[0]:  # Stop when a spacing problem is detected.
        return False, _format_line_message("Line format/spacing is invalid!", spacing_result[1])  # Return the required spacing error message.
    return True, ""  # Return success when every ASC line conforms to the expected structure.


def is_valid_ltspice_asc_footer(filepath: str) -> ValidationResult:  # Validate the simulation-directive region of an LTspice ASC file.
    read_result = _read_text_file_lines(filepath)  # Load the file lines through the shared safe reader.
    if not read_result[0]:  # Stop immediately when the shared file reader reports an error.
        return False, read_result[2]  # Propagate the exact file access error message.
    footer_result = _validate_asc_footer_lines(read_result[1])  # Validate the ASC footer-like directive content after a successful read.
    if not footer_result[0]:  # Stop when a footer problem is detected.
        return False, _format_line_message("Footer information is invalid!", footer_result[1])  # Return the required footer error message.
    return True, ""  # Return success when the ASC schematic contains valid simulation directives.


def is_valid_ltspice_asc_file(filepath: str) -> ValidationResult:  # Validate an LTspice ASC file by composing the three public ASC validators.
    header_result = is_valid_ltspice_asc_header(filepath)  # Execute the header validator first.
    if not header_result[0]:  # Stop when the header validator reports any failure.
        return header_result  # Return the exact public failure tuple unchanged.
    spacing_result = is_valid_ltspice_asc_spacing(filepath)  # Execute the spacing validator second.
    if not spacing_result[0]:  # Stop when the spacing validator reports any failure.
        return spacing_result  # Return the exact public failure tuple unchanged.
    footer_result = is_valid_ltspice_asc_footer(filepath)  # Execute the footer validator third.
    if not footer_result[0]:  # Stop when the footer validator reports any failure.
        return footer_result  # Return the exact public failure tuple unchanged.
    return True, ""  # Return success only when all three ASC validators succeed.


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


def ltspice_netlist_plot_networkx(netlist_filepath: str, networkx_png_filepath: str) -> ValidationResult:  # Plot a validated LTspice netlist as a networkx-derived PNG image.
    validation_result = is_valid_ltspice_netlist_file(netlist_filepath)  # Validate the input netlist through the required public wrapper first.
    if not validation_result[0]:  # Stop immediately when the netlist is not fully valid.
        return validation_result  # Return the exact validation failure tuple unchanged.
    parse_result = _load_parsed_elements(netlist_filepath)  # Parse the validated file into graph-ready device elements.
    if not parse_result[0]:  # Stop when internal parsing unexpectedly fails after validation.
        return False, "Unable to plot network graph!"  # Return a stable plotting failure message.
    output_path_result = _coerce_path(networkx_png_filepath)  # Convert the caller-supplied PNG path into a usable filesystem string.
    if not output_path_result[0]:  # Stop when the output path cannot be converted safely.
        return False, "Unable to write PNG file!"  # Return a stable write-path failure message.
    graph = _build_networkx_graph(parse_result[1], include_visual_labels=True)  # Build the plotting graph from the parsed device elements.
    try:  # Attempt to render and write the graph image to disk.
        _write_networkx_graph_png(graph, output_path_result[1])  # Draw the graph into a PNG file using the local renderer.
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


def _validate_asc_header_lines(lines: Sequence[str]) -> Tuple[bool, int]:  # Validate that an ASC file begins with the required Version and SHEET records.
    first_structural_entry = None  # Track the first nonblank structural ASC line.
    second_structural_entry = None  # Track the second nonblank structural ASC line.
    for line_number, raw_line in enumerate(lines, start=1):  # Walk every source line with a one-based line number.
        if raw_line.strip() == "":  # Ignore completely blank lines when locating the structural header.
            continue  # Move to the next source line because blank lines do not define the ASC header.
        classification_result = _classify_asc_line(raw_line)  # Classify the current ASC record before header checks.
        if not classification_result[0]:  # Stop when the line cannot even be classified as a supported ASC record.
            return False, line_number  # Report the failing line number as a header problem.
        if first_structural_entry is None:  # Capture the first structural line that defines the header.
            first_structural_entry = (line_number, classification_result[1], raw_line)  # Save the first structural line metadata.
            continue  # Continue scanning so the second structural line can be validated.
        second_structural_entry = (line_number, classification_result[1], raw_line)  # Save the second structural line metadata.
        break  # Stop once both required structural header lines have been captured.
    if first_structural_entry is None:  # Reject empty files because they cannot contain a valid ASC header.
        return False, 1  # Report line one for an empty or blank-only file.
    if first_structural_entry[1] != "VERSION":  # Require the first structural line to be a Version header.
        return False, first_structural_entry[0]  # Report the first structural line as invalid.
    first_validation_result = _validate_asc_record_tokens(first_structural_entry[2])  # Validate the token structure of the Version record.
    if not first_validation_result[0]:  # Stop when the Version record is malformed.
        return False, first_structural_entry[0]  # Report the first structural line as invalid.
    if second_structural_entry is None:  # Reject files that end before a SHEET record appears.
        return False, first_structural_entry[0]  # Report the header region because it is incomplete.
    if second_structural_entry[1] != "SHEET":  # Require the second structural line to be a SHEET record.
        return False, second_structural_entry[0]  # Report the second structural line as invalid.
    second_validation_result = _validate_asc_record_tokens(second_structural_entry[2])  # Validate the token structure of the SHEET record.
    if not second_validation_result[0]:  # Stop when the SHEET record is malformed.
        return False, second_structural_entry[0]  # Report the second structural line as invalid.
    return True, 0  # Return success when the ASC header starts with a valid Version and SHEET pair.


def _validate_asc_spacing_lines(lines: Sequence[str]) -> Tuple[bool, int]:  # Validate every ASC source line for supported keywords and token structure.
    for line_number, raw_line in enumerate(lines, start=1):  # Walk every line with a one-based line number.
        if raw_line.strip() == "":  # Ignore blank lines because they do not affect ASC spacing validity.
            continue  # Move to the next input line.
        record_result = _validate_asc_record_tokens(raw_line)  # Validate the current ASC record structure directly.
        if not record_result[0]:  # Stop when the record keyword or token structure is invalid.
            return False, line_number  # Report the failing line number.
    return True, 0  # Return success when all ASC lines validate.


def _validate_asc_footer_lines(lines: Sequence[str]) -> Tuple[bool, int]:  # Validate that an ASC file contains at least one valid simulation directive in TEXT form.
    spacing_result = _validate_asc_spacing_lines(lines)  # Reuse the ASC spacing validator before inspecting footer-like directives.
    if not spacing_result[0]:  # Stop when a general ASC line-format problem already exists.
        return False, spacing_result[1]  # Report the same failing line number for footer validation.
    analysis_count = 0  # Count valid simulation analysis directives carried by TEXT records.
    last_nonblank_line_number = 1  # Track the last nonblank line so missing-analysis failures have a useful location.
    for line_number, raw_line in enumerate(lines, start=1):  # Walk every line with a one-based line number.
        if raw_line.strip() == "":  # Ignore blank lines because they do not affect footer-like directive validity.
            continue  # Move to the next source line.
        last_nonblank_line_number = line_number  # Update the last nonblank line marker for later error reporting.
        directive_extract_result = _extract_asc_text_directive(raw_line)  # Extract a directive only when the current line is a TEXT carrier.
        if not directive_extract_result[0]:  # Stop when a malformed TEXT directive carrier is encountered.
            return False, line_number  # Report the failing TEXT line number.
        if directive_extract_result[1] == "":  # Ignore ordinary TEXT comments and labels that do not carry a directive.
            continue  # Move to the next line because no directive needs validation.
        directive_result = _parse_directive_name(directive_extract_result[1])  # Parse the embedded SPICE directive name.
        if not directive_result[0]:  # Stop when the directive text is malformed or unsupported.
            return False, line_number  # Report the failing directive carrier line number.
        if directive_result[1] in _ANALYSIS_DIRECTIVES:  # Count analysis directives that satisfy the ASC footer requirement.
            analysis_count += 1  # Record the analysis directive count.
    if analysis_count == 0:  # Require at least one simulation analysis directive somewhere in the schematic text.
        return False, last_nonblank_line_number  # Report the final nonblank line when no valid analysis directive exists.
    return True, 0  # Return success when the ASC file contains at least one valid analysis directive.


def _validate_format_lines(lines: Sequence[str]) -> Tuple[bool, int]:  # Validate each line for directive spelling and minimum token structure.
    previous_logical_line_exists = False  # Track whether a continuation line has something valid to continue.
    for line_number, raw_line in enumerate(lines, start=1):  # Walk every line with a one-based line number.
        line_kind_result = _classify_line(raw_line)  # Classify the line before validating its detailed structure.
        if not line_kind_result[0]:  # Stop when the line classification itself fails.
            return False, line_number  # Return the failing line number.
        line_kind = line_kind_result[1]  # Extract the validated line category.
        if line_kind in {"blank", "comment"}:  # Ignore blank lines and full-line comments.
            continue  # Move to the next input line.
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
            previous_logical_line_exists = True  # Mark the line as a valid logical line for later continuations.
            continue  # Move to the next input line.
        return False, line_number  # Reject any unexpected line type as invalid.
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


def _classify_asc_line(raw_line: str) -> Tuple[bool, str]:  # Classify one LTspice ASC record by its line-leading keyword.
    stripped_line = raw_line.strip()  # Remove surrounding whitespace before the keyword lookup.
    if stripped_line == "":  # Treat empty or all-whitespace records as blank.
        return True, "blank"  # Return the blank-line classification.
    keyword = stripped_line.split(maxsplit=1)[0]  # Read the leading ASC keyword token from the stripped line.
    normalized_keyword = keyword.upper()  # Normalize the keyword for case-insensitive comparison.
    if normalized_keyword not in _VALID_ASC_KEYWORDS:  # Reject unsupported or merged ASC keyword spellings.
        return False, "invalid"  # Signal that the ASC record keyword is invalid.
    return True, normalized_keyword  # Return the validated normalized ASC keyword.


def _validate_asc_record_tokens(raw_line: str) -> Tuple[bool, str]:  # Validate one ASC record for keyword support and token structure.
    classification_result = _classify_asc_line(raw_line)  # Classify the record before validating keyword-specific structure.
    if not classification_result[0]:  # Stop when the record keyword is unsupported or malformed.
        return False, "invalid_keyword"  # Signal that the record keyword is invalid.
    keyword = classification_result[1]  # Extract the normalized keyword for the current ASC record.
    if keyword == "blank":  # Treat blank records as structurally valid.
        return True, ""  # Return success because blank lines are allowed.
    tokens = raw_line.split()  # Split the ASC record into whitespace-separated tokens for structural validation.
    if keyword == "VERSION":  # Validate the Version header record.
        if len(tokens) != 2:  # Require exactly a keyword and a version token.
            return False, "invalid_version_token_count"  # Signal that the Version record is malformed.
        if not _is_integer_token(tokens[1]):  # Require the version value to be an integer token such as 4.
            return False, "invalid_version_value"  # Signal that the version value is malformed.
        return True, ""  # Return success when the Version record is well formed.
    if keyword == "SHEET":  # Validate the SHEET metadata record.
        if len(tokens) != 4:  # Require exactly the sheet id, width, and height fields.
            return False, "invalid_sheet_token_count"  # Signal that the SHEET record is malformed.
        if not all(_is_integer_token(token) for token in tokens[1:]):  # Require all SHEET numeric fields to be integer tokens.
            return False, "invalid_sheet_value"  # Signal that a SHEET numeric value is malformed.
        return True, ""  # Return success when the SHEET record is well formed.
    if keyword == "WIRE":  # Validate the electrical wire segment record.
        if len(tokens) != 5:  # Require exactly four coordinate fields after the keyword.
            return False, "invalid_wire_token_count"  # Signal that the WIRE record is malformed.
        if not all(_is_integer_token(token) for token in tokens[1:]):  # Require all WIRE coordinates to be integer tokens.
            return False, "invalid_wire_value"  # Signal that a WIRE coordinate is malformed.
        return True, ""  # Return success when the WIRE record is well formed.
    if keyword == "FLAG":  # Validate the net flag record.
        if len(tokens) != 4:  # Require exactly two coordinates and one net-name token after the keyword.
            return False, "invalid_flag_token_count"  # Signal that the FLAG record is malformed.
        if not _is_integer_token(tokens[1]) or not _is_integer_token(tokens[2]):  # Require both FLAG coordinates to be integers.
            return False, "invalid_flag_coordinate"  # Signal that a FLAG coordinate is malformed.
        return True, ""  # Return success when the FLAG record is well formed.
    if keyword == "DATAFLAG":  # Validate the data flag record.
        if len(tokens) < 4:  # Require coordinates plus at least one expression token.
            return False, "invalid_dataflag_token_count"  # Signal that the DATAFLAG record is malformed.
        if not _is_integer_token(tokens[1]) or not _is_integer_token(tokens[2]):  # Require both DATAFLAG coordinates to be integers.
            return False, "invalid_dataflag_coordinate"  # Signal that a DATAFLAG coordinate is malformed.
        return True, ""  # Return success when the DATAFLAG record is well formed.
    if keyword == "SYMBOL":  # Validate the symbol placement record.
        if len(tokens) != 5:  # Require a symbol name, two coordinates, and an orientation token.
            return False, "invalid_symbol_token_count"  # Signal that the SYMBOL record is malformed.
        if not _is_integer_token(tokens[2]) or not _is_integer_token(tokens[3]):  # Require both SYMBOL coordinates to be integers.
            return False, "invalid_symbol_coordinate"  # Signal that a SYMBOL coordinate is malformed.
        if tokens[4].upper() not in _ASC_SYMBOL_ORIENTATIONS:  # Require the SYMBOL orientation token to be one of the supported values.
            return False, "invalid_symbol_orientation"  # Signal that the SYMBOL orientation is malformed.
        return True, ""  # Return success when the SYMBOL record is well formed.
    if keyword == "WINDOW":  # Validate the attribute-window record.
        if len(tokens) != 6:  # Require the stable five-field WINDOW structure after the keyword.
            return False, "invalid_window_token_count"  # Signal that the WINDOW record is malformed.
        if not all(_is_integer_token(token) for token in tokens[1:4]):  # Require the WINDOW number and coordinates to be integer tokens.
            return False, "invalid_window_coordinate"  # Signal that a WINDOW numeric field is malformed.
        if tokens[4].upper() not in _ASC_TEXT_JUSTIFICATIONS:  # Require a supported WINDOW justification token.
            return False, "invalid_window_justification"  # Signal that the WINDOW justification is malformed.
        if not _is_integer_token(tokens[5]):  # Require the WINDOW font size to be an integer token.
            return False, "invalid_window_font_size"  # Signal that the WINDOW font size is malformed.
        return True, ""  # Return success when the WINDOW record is well formed.
    if keyword == "SYMATTR":  # Validate the symbol attribute record.
        if len(tokens) < 3:  # Require a key token plus at least one value token after the keyword.
            return False, "invalid_symattr_token_count"  # Signal that the SYMATTR record is malformed.
        return True, ""  # Return success when the SYMATTR record is minimally well formed.
    if keyword == "TEXT":  # Validate the free-form text or directive carrier record.
        if len(tokens) < 6:  # Require coordinates, justification, font size, and at least one payload token.
            return False, "invalid_text_token_count"  # Signal that the TEXT record is malformed.
        if not _is_integer_token(tokens[1]) or not _is_integer_token(tokens[2]):  # Require both TEXT coordinates to be integers.
            return False, "invalid_text_coordinate"  # Signal that a TEXT coordinate is malformed.
        if tokens[3].upper() not in _ASC_TEXT_JUSTIFICATIONS:  # Require a supported TEXT justification token.
            return False, "invalid_text_justification"  # Signal that the TEXT justification is malformed.
        if not _is_integer_token(tokens[4]):  # Require the TEXT font size to be an integer token.
            return False, "invalid_text_font_size"  # Signal that the TEXT font size is malformed.
        return True, ""  # Return success when the TEXT record is well formed.
    if keyword in {"LINE", "RECTANGLE", "CIRCLE"}:  # Validate the common geometric primitive records with optional style fields.
        if len(tokens) not in {6, 7}:  # Require either the base form or the optional trailing style form.
            return False, "invalid_shape_token_count"  # Signal that the geometric primitive is malformed.
        if tokens[1].upper() not in _ASC_DRAWING_WIDTHS:  # Require a supported line-width token.
            return False, "invalid_shape_width"  # Signal that the drawing width token is malformed.
        if not all(_is_integer_token(token) for token in tokens[2:6]):  # Require all geometric coordinates to be integer tokens.
            return False, "invalid_shape_coordinate"  # Signal that a geometric coordinate is malformed.
        if len(tokens) == 7 and not _is_integer_token(tokens[6]):  # Require the optional style token to be an integer when present.
            return False, "invalid_shape_style"  # Signal that the optional drawing style token is malformed.
        return True, ""  # Return success when the geometric primitive record is well formed.
    if keyword == "ARC":  # Validate the arc primitive record with optional style field.
        if len(tokens) not in {10, 11}:  # Require the base arc form or the optional trailing style form.
            return False, "invalid_arc_token_count"  # Signal that the ARC record is malformed.
        if tokens[1].upper() not in _ASC_DRAWING_WIDTHS:  # Require a supported line-width token.
            return False, "invalid_arc_width"  # Signal that the ARC drawing width token is malformed.
        if not all(_is_integer_token(token) for token in tokens[2:10]):  # Require all ARC coordinates to be integer tokens.
            return False, "invalid_arc_coordinate"  # Signal that an ARC coordinate is malformed.
        if len(tokens) == 11 and not _is_integer_token(tokens[10]):  # Require the optional style token to be an integer when present.
            return False, "invalid_arc_style"  # Signal that the ARC style token is malformed.
        return True, ""  # Return success when the ARC record is well formed.
    if keyword == "IOPIN":  # Validate the hierarchical I/O pin marker record.
        if len(tokens) != 4:  # Require two coordinates and one polarity token after the keyword.
            return False, "invalid_iopin_token_count"  # Signal that the IOPIN record is malformed.
        if not _is_integer_token(tokens[1]) or not _is_integer_token(tokens[2]):  # Require the IOPIN coordinates to be integer tokens.
            return False, "invalid_iopin_coordinate"  # Signal that an IOPIN coordinate is malformed.
        if tokens[3].upper() not in _ASC_IOPIN_POLARITIES:  # Require a supported IOPIN polarity token.
            return False, "invalid_iopin_polarity"  # Signal that the IOPIN polarity token is malformed.
        return True, ""  # Return success when the IOPIN record is well formed.
    if keyword == "BUSTAP":  # Validate the bus tap geometry record.
        if len(tokens) != 5:  # Require exactly four coordinates after the keyword.
            return False, "invalid_bustap_token_count"  # Signal that the BUSTAP record is malformed.
        if not all(_is_integer_token(token) for token in tokens[1:]):  # Require all BUSTAP coordinates to be integer tokens.
            return False, "invalid_bustap_coordinate"  # Signal that a BUSTAP coordinate is malformed.
        return True, ""  # Return success when the BUSTAP record is well formed.
    return False, "unhandled_keyword"  # Reject any unexpected keyword that reached this point.


def _extract_asc_text_value(raw_line: str) -> Tuple[bool, str]:  # Extract the free-form payload carried by one ASC TEXT record.
    tokens = raw_line.split(maxsplit=5)  # Split only the fixed TEXT prefix so the payload can retain its internal spaces.
    if len(tokens) < 6:  # Reject malformed TEXT records that do not contain a payload field.
        return False, ""  # Signal extraction failure so callers can map it to a spacing error.
    return True, tokens[5]  # Return the free-form TEXT payload exactly as stored in the source line.


def _extract_asc_text_directive(raw_line: str) -> Tuple[bool, str]:  # Extract an embedded SPICE directive from one ASC TEXT record when present.
    classification_result = _classify_asc_line(raw_line)  # Classify the record before trying to extract a TEXT payload.
    if not classification_result[0]:  # Stop when the record itself is not a valid ASC line.
        return False, ""  # Signal extraction failure because the record cannot be parsed safely.
    if classification_result[1] != "TEXT":  # Ignore non-TEXT records because only TEXT carries schematic directives.
        return True, ""  # Return an empty directive string to indicate there is nothing to validate here.
    text_value_result = _extract_asc_text_value(raw_line)  # Extract the free-form TEXT payload from the record.
    if not text_value_result[0]:  # Stop when the TEXT payload cannot be extracted reliably.
        return False, ""  # Signal extraction failure because the TEXT record is malformed.
    text_value = text_value_result[1].strip()  # Normalize surrounding whitespace before inspecting the TEXT payload.
    if not text_value.startswith("!"):  # Ignore ordinary labels and semicolon comments that are not directives.
        return True, ""  # Return an empty directive string because this TEXT line is not a SPICE directive carrier.
    directive_text = text_value[1:].strip()  # Remove the leading exclamation mark and normalize surrounding whitespace.
    if directive_text.startswith(";"):  # Ignore disabled schematic directives written as !;... in repository samples.
        return True, ""  # Treat commented-out directive carriers like ordinary annotation text.
    if directive_text == "":  # Reject empty directive carriers such as a bare exclamation mark.
        return False, ""  # Signal extraction failure because the directive payload is malformed.
    return True, directive_text  # Return the embedded directive text for later dot-directive parsing.


def _is_integer_token(token: str) -> bool:  # Decide whether one token is a valid integer field for ASC coordinate-style records.
    return re.match(r"^-?\d+$", token) is not None  # Accept optional leading minus signs followed by one or more digits.


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


def _write_networkx_graph_png(graph: nx.MultiGraph, output_path: str) -> None:  # Render a component-net graph into a standalone PNG file.
    component_nodes = sorted(node_id for node_id, attributes in graph.nodes(data=True) if attributes.get("kind") == "component")  # Collect component node ids in deterministic order.
    net_nodes = sorted(node_id for node_id, attributes in graph.nodes(data=True) if attributes.get("kind") == "net")  # Collect net node ids in deterministic order.
    component_columns = max(1, math.ceil(max(len(component_nodes), 1) / 18))  # Choose enough component columns to avoid an overly tall image.
    net_columns = max(1, math.ceil(max(len(net_nodes), 1) / 18))  # Choose enough net columns to avoid an overly tall image.
    row_count = max(1, math.ceil(max(len(component_nodes), 1) / component_columns), math.ceil(max(len(net_nodes), 1) / net_columns))  # Compute the maximum rows needed by either partition.
    width = max(960, 180 + (component_columns + net_columns) * 220)  # Scale the image width to leave room for both partitions and the edge bundle.
    height = max(480, 140 + row_count * 38)  # Scale the image height to the larger partition while keeping a useful minimum size.
    canvas = bytearray(width * height * 3)  # Allocate a flat RGB canvas for the PNG renderer.
    _fill_canvas(canvas, width, height, _PNG_BACKGROUND)  # Paint the full canvas with the light background color.
    component_positions = _assign_partition_positions(component_nodes, width, height, True)  # Place components in the left partition region.
    net_positions = _assign_partition_positions(net_nodes, width, height, False)  # Place nets in the right partition region.
    positions = {}  # Merge both partition position maps into one lookup dictionary.
    positions.update(component_positions)  # Add the component positions to the shared lookup.
    positions.update(net_positions)  # Add the net positions to the shared lookup.
    for first_node, second_node, edge_key, edge_attributes in graph.edges(keys=True, data=True):  # Draw every component-to-net edge in deterministic multigraph order.
        _draw_graph_edge(canvas, width, height, positions[first_node], positions[second_node], edge_attributes.get("port", 0), edge_key)  # Render the current edge with a small deterministic offset.
    for component_node_id in component_nodes:  # Draw every component node after the edges so boxes remain visible.
        center_x, center_y = component_positions[component_node_id]  # Read the component center coordinates from the layout map.
        fill_color = _component_fill_color(graph.nodes[component_node_id].get("prefix", "?"))  # Choose a stable component fill color from the device prefix.
        _draw_rectangle(canvas, width, height, center_x - 24, center_y - 11, center_x + 24, center_y + 11, fill_color, _PNG_COMPONENT_BORDER)  # Render the component as a filled bordered box.
    for net_node_id in net_nodes:  # Draw every net node after the edges so circles remain visible.
        center_x, center_y = net_positions[net_node_id]  # Read the net center coordinates from the layout map.
        _draw_circle(canvas, width, height, center_x, center_y, 8, _PNG_NET_FILL, _PNG_NET_BORDER)  # Render the net as a filled bordered circle.
    _write_png_rgb(output_path, width, height, canvas)  # Encode and write the final RGB canvas as a PNG file.


def _assign_partition_positions(node_ids: Sequence[str], width: int, height: int, is_component_partition: bool) -> Dict[str, Tuple[int, int]]:  # Assign deterministic positions within one graph partition.
    if not node_ids:  # Return early when the partition is empty.
        return {}  # Return an empty position map for the empty partition.
    column_count = max(1, math.ceil(len(node_ids) / 18))  # Compute enough columns to keep the partition at a manageable height.
    row_count = max(1, math.ceil(len(node_ids) / column_count))  # Compute the row count implied by the chosen column count.
    left_margin = 90 if is_component_partition else width // 2 + 60  # Place components on the left half and nets on the right half.
    right_margin = width // 2 - 60 if is_component_partition else width - 90  # Reserve a gap in the middle for the edge bundle.
    top_margin = 70  # Leave a comfortable top margin for the rendered image.
    bottom_margin = height - 70  # Leave a comfortable bottom margin for the rendered image.
    if bottom_margin <= top_margin:  # Guard against impossible image dimensions before computing positions.
        raise ValueError("image_height_too_small")  # Signal that the computed image dimensions are invalid.
    usable_width = max(1, right_margin - left_margin)  # Compute the usable horizontal width for the partition columns.
    usable_height = bottom_margin - top_margin  # Compute the usable vertical height for the partition rows.
    horizontal_step = 0 if column_count == 1 else usable_width / (column_count - 1)  # Spread columns evenly across the partition width.
    vertical_step = 0 if row_count == 1 else usable_height / (row_count - 1)  # Spread rows evenly across the partition height.
    positions: Dict[str, Tuple[int, int]] = {}  # Collect the computed center coordinates for each node id.
    for index, node_id in enumerate(node_ids):  # Walk every partition node in deterministic order.
        column_index = index // row_count  # Place nodes into columns first so each column receives roughly equal height.
        row_index = index % row_count  # Place nodes into rows within the selected column.
        center_x = int(round(left_margin + column_index * horizontal_step))  # Compute the node center x coordinate for the current column.
        center_y = int(round(top_margin + row_index * vertical_step))  # Compute the node center y coordinate for the current row.
        positions[node_id] = (center_x, center_y)  # Save the computed center coordinates in the position map.
    return positions  # Return the completed position map for the partition.


def _draw_graph_edge(canvas: bytearray, width: int, height: int, first_point: Tuple[int, int], second_point: Tuple[int, int], port_index: int, edge_key: int) -> None:  # Draw one graph edge with a deterministic vertical offset.
    first_x, first_y = first_point  # Unpack the source point coordinates for the current edge.
    second_x, second_y = second_point  # Unpack the destination point coordinates for the current edge.
    offset = (port_index * 3) + (edge_key * 2)  # Compute a small deterministic offset so repeated edges do not fully overlap.
    _draw_line(canvas, width, height, first_x + 24, first_y + offset, second_x - 8, second_y + offset, _PNG_EDGE_COLOR)  # Render the edge as a single straight line segment.


def _component_fill_color(prefix: str) -> Tuple[int, int, int]:  # Choose a stable component fill color from a device prefix.
    palette_index = ord(prefix[0]) % len(_PNG_COMPONENT_COLORS)  # Map the prefix character into the compact component color palette.
    return _PNG_COMPONENT_COLORS[palette_index]  # Return the selected component fill color tuple.


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
