"""LTspice netlist validation helpers and public API functions."""  # Document the module purpose.

from __future__ import annotations  # Postpone annotation evaluation for forward references.

from dataclasses import dataclass  # Use a small record type for parsed element lines.
import os  # Access filesystem and permission utilities.
import re  # Validate directive spelling and structure with regular expressions.
from typing import Dict  # Type the node-count mapping.
from typing import List  # Type collections of lines and nodes.
from typing import Sequence  # Type immutable views over loaded line lists.
from typing import Tuple  # Type tuple-based helper results.

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
