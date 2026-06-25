"""LTspice ASC schematic validation helpers and public API functions."""  # Document the module purpose.

from __future__ import annotations  # Postpone annotation evaluation for forward references.

import os  # Access filesystem and permission utilities.
import re  # Validate directive spelling and integer token structure with regular expressions.
from typing import List  # Type collections of lines.
from typing import Sequence  # Type immutable views over loaded line lists.
from typing import Tuple  # Type tuple-based helper results.

ValidationResult = Tuple[bool, str]  # Represent the public validator return shape.
ReadLinesResult = Tuple[bool, List[str], str]  # Represent file-read helper output.
DirectiveResult = Tuple[bool, str, str]  # Represent directive parsing success, name, and message.

_DIRECTIVE_PATTERN = re.compile(r"^\.(?P<name>[A-Za-z]+)(?:\s|$)")  # Match an LTspice dot-directive name.

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


def _parse_directive_name(code_part: str) -> DirectiveResult:  # Parse and validate a dot-directive keyword.
    directive_match = _DIRECTIVE_PATTERN.match(code_part)  # Match the directive name at the start of the code portion.
    if directive_match is None:  # Reject directives without a valid dot-command name boundary.
        return False, "", "invalid_directive"  # Signal directive parsing failure.
    directive_name = directive_match.group("name").lower()  # Normalize the matched directive name to lowercase.
    if directive_name not in _VALID_DOT_DIRECTIVES:  # Reject unsupported or merged directive spellings.
        return False, "", "unknown_directive"  # Signal directive validation failure.
    return True, directive_name, ""  # Return the validated directive name.


def _is_integer_token(token: str) -> bool:  # Decide whether one token is a valid integer field for ASC coordinate-style records.
    return re.match(r"^-?\d+$", token) is not None  # Accept optional leading minus signs followed by one or more digits.


def _format_line_message(prefix: str, line_number: int) -> str:  # Build the required public error message with a line number suffix.
    return f"{prefix} Line {line_number}"  # Return the final user-facing message.
