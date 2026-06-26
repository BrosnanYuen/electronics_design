"""LTspice ASC schematic validation helpers and public API functions."""  # Document the module purpose.

from __future__ import annotations  # Postpone annotation evaluation for forward references.

from dataclasses import dataclass  # Use small records for parsed schematic content.
import os  # Access filesystem and permission utilities.
from pathlib import Path  # Normalize output paths and local cache directories.
import re  # Validate directive spelling and integer token structure with regular expressions.
from typing import Dict  # Type symbol-attribute mappings cleanly.
from typing import List  # Type collections of lines.
from typing import Optional  # Type optional parsed symbol state.
from typing import Sequence  # Type immutable views over loaded line lists.
from typing import Tuple  # Type tuple-based helper results.

ValidationResult = Tuple[bool, str]  # Represent the public validator return shape.
ReadLinesResult = Tuple[bool, List[str], str]  # Represent file-read helper output.
DirectiveResult = Tuple[bool, str, str]  # Represent directive parsing success, name, and message.
Point = Tuple[int, int]  # Represent one LTspice schematic coordinate pair.

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

_SUPPORTED_SCHEMDRAW_EXTENSIONS = {".png", ".svg", ".jpg", ".jpeg"}  # Define the supported schematic-export image formats.
_SCHEMDRAW_POINT_SCALE = 64.0  # Map LTspice drawing coordinates into manageable SchemDraw units.
_SCHEMDRAW_MARGIN_UNITS = 1.0  # Leave a small border around the rendered schematic drawing.
_SCHEMDRAW_DPI = 100.0  # Use a stable raster DPI before final format-specific resizing.
_SCHEMDRAW_NEARBY_POINT_RADIUS = 192  # Search this many LTspice units around a symbol for nearby connection points.


@dataclass(frozen=True)  # Freeze wire records so helpers can reuse them safely.
class AscWire:  # Represent one LTspice WIRE segment.
    start: Point  # Store the wire start coordinate.
    end: Point  # Store the wire end coordinate.


@dataclass(frozen=True)  # Freeze flag records so helpers can reuse them safely.
class AscFlag:  # Represent one LTspice FLAG record.
    point: Point  # Store the flag coordinate.
    name: str  # Store the net or ground name carried by the flag.


@dataclass  # Keep symbol records mutable while SYMATTR lines are still being attached.
class AscSymbol:  # Represent one LTspice SYMBOL plus its following attributes.
    symbol_name: str  # Store the LTspice symbol library name.
    origin: Point  # Store the LTspice symbol origin coordinate.
    orientation: str  # Store the LTspice orientation token.
    attributes: Dict[str, str]  # Store parsed SYMATTR values keyed by attribute name.


@dataclass(frozen=True)  # Freeze schematic records once parsing completes.
class AscSchematic:  # Represent the electrical parts of one LTspice ASC schematic.
    wires: List[AscWire]  # Store every electrical wire segment.
    flags: List[AscFlag]  # Store every net or ground flag.
    symbols: List[AscSymbol]  # Store every component symbol and its attributes.
    bounds: Tuple[int, int, int, int]  # Store min x, min y, max x, and max y across the schematic.


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


def ltspice_asc_plot_schemdraw(asc_filepath: str, schemdraw_imagepath_out: str, width: int = 1920, height: int = 1080) -> ValidationResult:  # Render one validated LTspice ASC schematic through schemdraw.
    validation_result = is_valid_ltspice_asc_file(asc_filepath)  # Validate the input ASC file through the required public wrapper first.
    if not validation_result[0]:  # Stop immediately when the ASC file is not fully valid.
        return validation_result  # Return the exact validation failure tuple unchanged.
    output_path_result = _coerce_path(schemdraw_imagepath_out)  # Convert the caller-supplied output path into a usable filesystem string.
    if not output_path_result[0]:  # Stop when the output path cannot be converted safely.
        return False, "Unable to write image file!"  # Return a stable write-path failure message.
    if isinstance(width, bool) or not isinstance(width, int):  # Reject non-integer widths before invoking the renderer.
        return False, "Unable to plot schematic drawing!"  # Return a stable plotting failure message for invalid dimensions.
    if isinstance(height, bool) or not isinstance(height, int):  # Reject non-integer heights before invoking the renderer.
        return False, "Unable to plot schematic drawing!"  # Return a stable plotting failure message for invalid dimensions.
    if width <= 0 or height <= 0:  # Reject zero or negative image dimensions before invoking the renderer.
        return False, "Unable to plot schematic drawing!"  # Return a stable plotting failure message for invalid dimensions.
    extension = Path(output_path_result[1]).suffix.lower()  # Read the requested output extension so it can be validated early.
    if extension not in _SUPPORTED_SCHEMDRAW_EXTENSIONS:  # Reject unsupported output extensions explicitly.
        return False, "Unable to plot schematic drawing!"  # Return a stable plotting failure message for unsupported formats.
    read_result = _read_text_file_lines(asc_filepath)  # Load the ASC file lines through the shared safe reader.
    if not read_result[0]:  # Stop when the file cannot be re-read safely after validation.
        return False, read_result[2]  # Propagate the same stable file-access error message.
    parse_result = _parse_asc_schematic(read_result[1])  # Parse the validated ASC drawing records into schematic structures.
    if not parse_result[0]:  # Stop when internal parsing unexpectedly fails after validation.
        return False, "Unable to plot schematic drawing!"  # Return a stable plotting failure message.
    try:  # Attempt to render and write the schemdraw output file.
        _render_asc_schematic_with_schemdraw(parse_result[1], output_path_result[1], width, height)  # Draw the schematic using the selected schemdraw backend.
    except OSError:  # Catch filesystem write failures such as missing permissions or invalid parent directories.
        return False, "Unable to write image file!"  # Return a stable write failure message.
    except (ImportError, RuntimeError, ValueError):  # Catch renderer setup failures such as missing optional dependencies or malformed SVG output.
        return False, "Unable to plot schematic drawing!"  # Return a stable plotting failure message.
    return True, ""  # Return success when the schematic image file is written successfully.


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


def _parse_asc_schematic(lines: Sequence[str]) -> Tuple[bool, AscSchematic]:  # Parse the electrical portions of one validated LTspice ASC schematic.
    wires: List[AscWire] = []  # Collect every electrical wire segment in source order.
    flags: List[AscFlag] = []  # Collect every net or ground flag in source order.
    symbols: List[AscSymbol] = []  # Collect every component symbol in source order.
    current_symbol: Optional[AscSymbol] = None  # Track the most recent symbol while SYMATTR lines are still being attached.
    all_points: List[Point] = []  # Collect every geometry point so the final drawing bounds can be computed.
    for raw_line in lines:  # Walk every ASC source line in order.
        if raw_line.strip() == "":  # Ignore blank lines because they add no schematic geometry.
            continue  # Move to the next input line.
        tokens = raw_line.split()  # Split the current ASC record into whitespace-separated tokens.
        keyword = tokens[0].upper()  # Normalize the record keyword for stable dispatch.
        if keyword == "WIRE":  # Parse one electrical wire segment.
            start_point = (int(tokens[1]), int(tokens[2]))  # Read the wire start coordinate from the current record.
            end_point = (int(tokens[3]), int(tokens[4]))  # Read the wire end coordinate from the current record.
            wires.append(AscWire(start=start_point, end=end_point))  # Save the parsed electrical wire segment.
            all_points.extend([start_point, end_point])  # Feed the bounding-box calculation with both wire endpoints.
            current_symbol = None  # Stop attaching later SYMATTR lines because a new non-symbol record was reached.
            continue  # Move to the next input line after saving the wire.
        if keyword == "FLAG":  # Parse one net or ground flag.
            flag_point = (int(tokens[1]), int(tokens[2]))  # Read the flag coordinate from the current record.
            flags.append(AscFlag(point=flag_point, name=" ".join(tokens[3:])))  # Save the parsed flag and preserve the full net-name payload.
            all_points.append(flag_point)  # Feed the bounding-box calculation with the flag coordinate.
            current_symbol = None  # Stop attaching later SYMATTR lines because a new non-symbol record was reached.
            continue  # Move to the next input line after saving the flag.
        if keyword == "SYMBOL":  # Parse one component symbol placement record.
            current_symbol = AscSymbol(  # Start a fresh symbol record that later SYMATTR lines can enrich.
                symbol_name=tokens[1],  # Preserve the LTspice symbol-library name.
                origin=(int(tokens[2]), int(tokens[3])),  # Preserve the LTspice symbol origin coordinate.
                orientation=tokens[4],  # Preserve the LTspice orientation token verbatim.
                attributes={},  # Start with no SYMATTR metadata attached yet.
            )  # Finish constructing the new parsed symbol record.
            symbols.append(current_symbol)  # Save the symbol record in source order immediately.
            all_points.append(current_symbol.origin)  # Feed the bounding-box calculation with the symbol origin.
            continue  # Move to the next input line so following SYMATTR records can attach to this symbol.
        if keyword == "SYMATTR" and current_symbol is not None:  # Attach one symbol attribute to the most recent symbol record.
            attr_tokens = raw_line.split(maxsplit=2)  # Preserve the full attribute value text after the key token.
            if len(attr_tokens) >= 3:  # Store only attributes that include both a key and a value field.
                current_symbol.attributes[attr_tokens[1]] = attr_tokens[2]  # Save the parsed symbol attribute payload verbatim.
            continue  # Move to the next input line after processing the attached symbol attribute.
        if keyword == "WINDOW" and current_symbol is not None:  # Ignore WINDOW records while keeping the current symbol attachment active.
            continue  # Move to the next input line because window geometry is not needed for this renderer.
        current_symbol = None  # Stop attaching later SYMATTR lines when any other record type is reached.
    if not all_points:  # Reject empty geometry unexpectedly because a valid ASC file should contain at least one record.
        return False, AscSchematic(wires=[], flags=[], symbols=[], bounds=(0, 0, 0, 0))  # Return a stable empty schematic placeholder on failure.
    x_values = [point[0] for point in all_points]  # Collect every x coordinate for the drawing bounds.
    y_values = [point[1] for point in all_points]  # Collect every y coordinate for the drawing bounds.
    schematic = AscSchematic(  # Assemble the parsed schematic record returned to the renderer.
        wires=wires,  # Preserve the parsed electrical wire list.
        flags=flags,  # Preserve the parsed flag list.
        symbols=symbols,  # Preserve the parsed symbol list with attached attributes.
        bounds=(min(x_values), min(y_values), max(x_values), max(y_values)),  # Save the final schematic bounds tuple.
    )  # Finish constructing the parsed schematic record.
    return True, schematic  # Return the successfully parsed schematic data.


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


def _render_asc_schematic_with_schemdraw(schematic: AscSchematic, output_path: str, width: int, height: int) -> None:  # Render one parsed ASC schematic into a schemdraw-managed image file.
    _configure_matplotlib_cache_directory()  # Ensure matplotlib-backed exports can initialize a writable local cache directory.
    import schemdraw  # Import schemdraw lazily so the package remains importable without plotting dependencies.
    import schemdraw.elements as elm  # Import the shared schemdraw element catalog lazily for the same reason.

    extension = Path(output_path).suffix.lower()  # Read the requested output extension so the renderer backend can be selected deterministically.
    backend = "svg" if extension == ".svg" else "matplotlib"  # Route SVG output through the SVG backend and raster outputs through matplotlib.
    transform = _make_schemdraw_point_transform(schematic.bounds)  # Build the LTspice-to-schemdraw coordinate transform for this schematic.
    drawing_width_units = transform(schematic.bounds[2], schematic.bounds[1])[0] + _SCHEMDRAW_MARGIN_UNITS  # Measure the transformed drawing width for sizing.
    drawing_height_units = transform(schematic.bounds[0], schematic.bounds[3])[1] + _SCHEMDRAW_MARGIN_UNITS  # Measure the transformed drawing height for sizing.
    inches_per_unit = min(  # Fit the transformed schematic into the caller-requested raster or SVG viewport.
        (width / _SCHEMDRAW_DPI) / max(drawing_width_units, 1.0),  # Fit the schematic width into the requested pixel width at the chosen DPI.
        (height / _SCHEMDRAW_DPI) / max(drawing_height_units, 1.0),  # Fit the schematic height into the requested pixel height at the chosen DPI.
    )  # Finish computing the drawing scale.
    drawing = schemdraw.Drawing(  # Create the top-level schemdraw drawing using the selected backend and neutral styling.
        show=False,  # Prevent interactive windows during test runs and scripted usage.
        canvas=backend,  # Select the appropriate schemdraw backend for the requested export format.
        unit=1.0,  # Keep direct control over absolute coordinates by using one-unit default element sizing.
        inches_per_unit=inches_per_unit,  # Scale the output to fit the requested image size cleanly.
        fontsize=10.0,  # Use a compact default label size suitable for dense schematics.
        lw=1.5,  # Use a moderate stroke width so wires remain readable after rasterization.
        margin=0.05,  # Keep backend-side margins small because the transform already reserves a visual border.
    )  # Finish constructing the schemdraw drawing object.
    electrical_points = _collect_asc_electrical_points(schematic)  # Collect wire and flag points used by the component placement heuristics.
    junction_points = _count_asc_junction_points(schematic)  # Count how many wire endpoints and flags touch each coordinate.
    for wire in schematic.wires:  # Draw every original LTspice wire segment first so the connectivity geometry is preserved directly.
        drawing.add(elm.Line().at(transform(*wire.start)).to(transform(*wire.end)))  # Render the current wire segment as a schemdraw line.
    for point, count in sorted(junction_points.items()):  # Mark multi-way wire junctions after the wire geometry has been drawn.
        if count < 3:  # Skip simple two-point line segments because they do not need explicit junction dots.
            continue  # Move to the next counted point.
        drawing.add(elm.Dot().at(transform(*point)))  # Render the visible wire junction dot at the counted coordinate.
    for flag in schematic.flags:  # Render every net flag and ground symbol after the wires so labels remain visible.
        _draw_asc_flag(drawing, elm, flag, transform)  # Draw the current flag using the appropriate ground or labeled-dot element.
    for symbol in schematic.symbols:  # Render every placed LTspice component symbol after the wires and flags.
        _draw_asc_symbol_schemdraw(drawing, elm, symbol, electrical_points, transform)  # Draw the current component using the best available schemdraw symbol mapping.
    drawing.save(output_path, dpi=_SCHEMDRAW_DPI)  # Save the raw schemdraw drawing through the backend selected for the requested extension.
    if extension == ".svg":  # Normalize the SVG viewport size when the SVG backend was selected.
        _rewrite_svg_dimensions(output_path, width, height)  # Replace the emitted SVG width and height attributes with the requested pixel dimensions.
        return  # Stop after the SVG file has been normalized.
    _resize_raster_image(output_path, extension, width, height)  # Resize raster outputs so they match the requested pixel dimensions exactly.


def _configure_matplotlib_cache_directory() -> None:  # Point matplotlib at a writable cache directory before schemdraw imports it.
    if "MPLCONFIGDIR" in os.environ and os.environ["MPLCONFIGDIR"] != "":  # Respect an existing explicit matplotlib cache directory.
        return  # Leave the user-supplied cache directory unchanged.
    cache_directory = Path("/tmp") / "electronics_design_mplconfig"  # Use a writable temporary directory for matplotlib's cache files.
    cache_directory.mkdir(parents=True, exist_ok=True)  # Ensure the fallback cache directory exists before matplotlib uses it.
    os.environ["MPLCONFIGDIR"] = str(cache_directory)  # Export the fallback cache directory path for later matplotlib imports.


def _make_schemdraw_point_transform(bounds: Tuple[int, int, int, int]):  # Build the LTspice-to-schemdraw coordinate transform for one schematic bounds tuple.
    min_x, _min_y, _max_x, max_y = bounds  # Read the schematic bounds needed by the coordinate transform.

    def _transform(x_position: int, y_position: int) -> Tuple[float, float]:  # Transform one LTspice coordinate pair into schemdraw coordinates.
        x_value = ((x_position - min_x) / _SCHEMDRAW_POINT_SCALE) + _SCHEMDRAW_MARGIN_UNITS  # Normalize x into the positive schemdraw coordinate space.
        y_value = ((max_y - y_position) / _SCHEMDRAW_POINT_SCALE) + _SCHEMDRAW_MARGIN_UNITS  # Flip y so LTspice's downward axis becomes schemdraw's upward axis.
        return x_value, y_value  # Return the transformed schemdraw coordinate pair.

    return _transform  # Return the reusable point-transform closure.


def _collect_asc_electrical_points(schematic: AscSchematic) -> List[Point]:  # Collect unique wire-endpoint and flag coordinates used by symbol-placement heuristics.
    points = {flag.point for flag in schematic.flags}  # Start with every flag coordinate because flags attach directly to electrical nets.
    for wire in schematic.wires:  # Walk every stored wire segment.
        points.add(wire.start)  # Record the wire start coordinate as an electrical point.
        points.add(wire.end)  # Record the wire end coordinate as an electrical point.
    return sorted(points)  # Return the deterministic sorted electrical-point list.


def _count_asc_junction_points(schematic: AscSchematic) -> Dict[Point, int]:  # Count how many endpoints or flags touch each schematic coordinate.
    counts: Dict[Point, int] = {}  # Collect per-point incidence counts for explicit junction-dot rendering.
    for wire in schematic.wires:  # Walk every stored wire segment.
        counts[wire.start] = counts.get(wire.start, 0) + 1  # Increment the incidence count for the wire start.
        counts[wire.end] = counts.get(wire.end, 0) + 1  # Increment the incidence count for the wire end.
    for flag in schematic.flags:  # Treat flags as additional visible touches on the connected node.
        counts[flag.point] = counts.get(flag.point, 0) + 1  # Increment the incidence count for the flag coordinate.
    return counts  # Return the completed junction-incidence mapping.


def _draw_asc_flag(drawing, elm, flag: AscFlag, transform) -> None:  # Draw one LTspice FLAG record using schemdraw primitives.
    transformed_point = transform(*flag.point)  # Transform the LTspice flag coordinate into schemdraw coordinates.
    normalized_name = flag.name.strip()  # Normalize the raw flag name before deciding how to draw it.
    if normalized_name.upper() in {"0", "GND"}:  # Render LTspice ground labels using schemdraw's dedicated ground element.
        drawing.add(elm.Ground().at(transformed_point))  # Draw the standard ground symbol anchored at the flag coordinate.
        return  # Stop after rendering the ground flag.
    drawing.add(elm.Dot().at(transformed_point).label(normalized_name, loc="right"))  # Draw other flags as labeled connection dots.


def _draw_asc_symbol_schemdraw(drawing, elm, symbol: AscSymbol, electrical_points: Sequence[Point], transform) -> None:  # Draw one LTspice symbol using the closest useful schemdraw element mapping.
    normalized_name = _normalize_asc_symbol_name(symbol.symbol_name)  # Normalize the LTspice symbol name so the mapping logic is stable.
    if normalized_name in {"res", "cap", "ind", "diode", "voltage", "current", "sw", "f"}:  # Render common two-pin components through explicit start and end coordinates.
        _draw_asc_two_pin_symbol(drawing, elm, symbol, electrical_points, transform)  # Delegate to the shared two-pin schemdraw renderer.
        return  # Stop after drawing the two-pin component.
    if normalized_name in {"npn", "pnp", "nmos", "pmos", "gain", "opamp", "lt1007", "lt1721"}:  # Render the common active-device and amplifier symbols through fixed schemdraw elements.
        _draw_asc_active_symbol(drawing, elm, symbol, electrical_points, transform)  # Delegate to the shared active-device renderer.
        return  # Stop after drawing the active or amplifier component.
    _draw_asc_generic_symbol(drawing, elm, symbol, electrical_points, transform)  # Fall back to a labeled generic IC-style block for unknown symbols.


def _draw_asc_two_pin_symbol(drawing, elm, symbol: AscSymbol, electrical_points: Sequence[Point], transform) -> None:  # Draw one LTspice two-pin symbol stretched between its nearby connection points.
    pin_pair = _find_two_pin_connection_points(symbol, electrical_points)  # Infer the two nearby electrical points that the symbol connects between.
    if pin_pair is None:  # Fall back when no credible pin pair can be inferred from the local wire geometry.
        center_point = _estimate_symbol_center(symbol, electrical_points)  # Estimate a generic placement point so the symbol is still visible.
        _draw_asc_generic_symbol(drawing, elm, symbol, electrical_points, transform, center_override=center_point)  # Render a fallback generic block instead of dropping the symbol.
        return  # Stop after the fallback generic symbol is rendered.
    start_point, end_point = _order_two_pin_points_for_orientation(pin_pair[0], pin_pair[1], symbol.orientation)  # Order the inferred pin pair to roughly follow the LTspice orientation.
    element = _make_two_pin_schemdraw_element(elm, symbol)  # Instantiate the schemdraw element that best matches the LTspice symbol name.
    element = element.at(transform(*start_point)).to(transform(*end_point))  # Stretch the symbol directly between the inferred LTspice pin coordinates.
    element = _apply_symbol_labels(element, symbol)  # Attach the instance and value labels when available.
    drawing.add(element)  # Add the fully configured two-pin component to the drawing.


def _draw_asc_active_symbol(drawing, elm, symbol: AscSymbol, electrical_points: Sequence[Point], transform) -> None:  # Draw one LTspice active or amplifier symbol at an estimated local center point.
    normalized_name = _normalize_asc_symbol_name(symbol.symbol_name)  # Normalize the LTspice symbol name so the active-device mapping is stable.
    center_point = transform(*_estimate_symbol_center(symbol, electrical_points))  # Estimate the active-device center from nearby electrical points.
    if normalized_name == "npn":  # Map LTspice NPN symbols to the dedicated schemdraw BJT symbol.
        element = elm.BjtNpn().at(center_point)  # Create the configured schemdraw NPN transistor element.
    elif normalized_name == "pnp":  # Map LTspice PNP symbols to the dedicated schemdraw BJT symbol.
        element = elm.BjtPnp().at(center_point)  # Create the configured schemdraw PNP transistor element.
    elif normalized_name == "nmos":  # Map LTspice NMOS symbols to the dedicated schemdraw FET symbol.
        element = elm.NFet().at(center_point)  # Create the configured schemdraw NMOS element.
    elif normalized_name == "pmos":  # Map LTspice PMOS symbols to the dedicated schemdraw FET symbol.
        element = elm.PFet().at(center_point)  # Create the configured schemdraw PMOS element.
    else:  # Map op-amp, comparator, and gain blocks to the shared schemdraw op-amp style.
        element = elm.Opamp().at(center_point)  # Create the configured schemdraw amplifier-style element.
    element = _apply_orientation_to_schemdraw_element(element, symbol.orientation)  # Apply the LTspice orientation token as closely as the schemdraw element API allows.
    element = _apply_symbol_labels(element, symbol)  # Attach the instance and value labels when available.
    drawing.add(element)  # Add the fully configured active-device or amplifier symbol to the drawing.


def _draw_asc_generic_symbol(drawing, elm, symbol: AscSymbol, electrical_points: Sequence[Point], transform, center_override: Optional[Point] = None) -> None:  # Draw a labeled generic block for unsupported LTspice symbols.
    center_source = center_override if center_override is not None else _estimate_symbol_center(symbol, electrical_points)  # Use the supplied fallback center when one exists.
    element = elm.Ic(size=(1.6, 1.0)).at(transform(*center_source))  # Represent unsupported symbols as compact IC-style rectangles.
    generic_label = symbol.attributes.get("InstName", symbol.symbol_name)  # Prefer the instance name on the generic block when available.
    element = element.label(generic_label, loc="top")  # Label the generic block with the most useful instance identifier.
    value_text = _clean_symbol_value(symbol)  # Extract a compact optional value text for secondary labeling.
    if value_text != "":  # Add the secondary label only when the symbol carries a non-empty displayed value.
        element = element.label(value_text, loc="bottom")  # Place the secondary value or model label below the generic block.
    drawing.add(element)  # Add the fallback generic component block to the drawing.


def _find_two_pin_connection_points(symbol: AscSymbol, electrical_points: Sequence[Point]) -> Optional[Tuple[Point, Point]]:  # Infer the two electrical points used by one LTspice two-pin symbol.
    origin_x, origin_y = symbol.origin  # Read the LTspice symbol origin so candidate points can be scored relative to it.
    horizontal = _orientation_is_horizontal(symbol.orientation)  # Decide whether the symbol is primarily horizontal or vertical.
    nearby_points = [  # Filter the global electrical-point list down to points plausibly attached to this symbol.
        point
        for point in electrical_points
        if abs(point[0] - origin_x) <= _SCHEMDRAW_NEARBY_POINT_RADIUS and abs(point[1] - origin_y) <= _SCHEMDRAW_NEARBY_POINT_RADIUS
    ]  # Finish collecting nearby candidate electrical points.
    if len(nearby_points) < 2:  # Stop when there are not enough nearby electrical points to infer a two-pin connection.
        return None  # Signal that no credible two-pin connection pair could be inferred.
    best_pair: Optional[Tuple[Point, Point]] = None  # Track the currently best-scoring pin pair candidate.
    best_score: Optional[Tuple[int, int, int, int]] = None  # Track the current best deterministic pair score.
    for first_index, first_point in enumerate(nearby_points):  # Walk each nearby candidate point as the first pin.
        for second_point in nearby_points[first_index + 1 :]:  # Walk each later nearby candidate point as the second pin.
            if horizontal:  # Score the candidate as a horizontal two-pin element.
                alignment_penalty = abs(first_point[1] - second_point[1])  # Prefer points that share the same y coordinate.
                midpoint_penalty = abs(((first_point[1] + second_point[1]) // 2) - origin_y)  # Prefer horizontal pairs close to the symbol origin y coordinate.
                axis_distance = abs(first_point[0] - second_point[0])  # Measure the horizontal separation between the candidate pins.
                straddle_penalty = 0 if min(first_point[0], second_point[0]) <= origin_x <= max(first_point[0], second_point[0]) else 1  # Prefer pairs that span the symbol origin along the main axis.
            else:  # Score the candidate as a vertical two-pin element.
                alignment_penalty = abs(first_point[0] - second_point[0])  # Prefer points that share the same x coordinate.
                midpoint_penalty = abs(((first_point[0] + second_point[0]) // 2) - origin_x)  # Prefer vertical pairs close to the symbol origin x coordinate.
                axis_distance = abs(first_point[1] - second_point[1])  # Measure the vertical separation between the candidate pins.
                straddle_penalty = 0 if min(first_point[1], second_point[1]) <= origin_y <= max(first_point[1], second_point[1]) else 1  # Prefer pairs that span the symbol origin along the main axis.
            total_distance = _point_manhattan_distance(first_point, symbol.origin) + _point_manhattan_distance(second_point, symbol.origin)  # Prefer nearby candidates when several pairs remain plausible.
            score = (alignment_penalty, straddle_penalty, midpoint_penalty, total_distance - axis_distance)  # Prefer aligned, origin-spanning, nearby, longer candidate pairs deterministically.
            if best_score is None or score < best_score:  # Update the winning pair when a better-scoring candidate is found.
                best_score = score  # Save the better deterministic pair score.
                best_pair = (first_point, second_point)  # Save the matching better-scoring pin pair.
    return best_pair  # Return the inferred two-pin connection pair when one was found.


def _estimate_symbol_center(symbol: AscSymbol, electrical_points: Sequence[Point]) -> Point:  # Estimate a useful visual center point for one LTspice symbol from nearby wire geometry.
    nearby_points = [  # Collect nearby electrical points that likely belong to the symbol's visible pins.
        point
        for point in electrical_points
        if abs(point[0] - symbol.origin[0]) <= _SCHEMDRAW_NEARBY_POINT_RADIUS and abs(point[1] - symbol.origin[1]) <= _SCHEMDRAW_NEARBY_POINT_RADIUS
    ]  # Finish collecting nearby candidate points.
    if not nearby_points:  # Fall back to the LTspice symbol origin when no nearby electrical points exist.
        return symbol.origin  # Use the raw LTspice symbol origin as the estimated center.
    x_total = sum(point[0] for point in nearby_points)  # Sum the nearby point x coordinates for centroid calculation.
    y_total = sum(point[1] for point in nearby_points)  # Sum the nearby point y coordinates for centroid calculation.
    return round(x_total / len(nearby_points)), round(y_total / len(nearby_points))  # Return the rounded centroid of the nearby electrical points.


def _make_two_pin_schemdraw_element(elm, symbol: AscSymbol):  # Create the schemdraw element that best matches one LTspice two-pin symbol name.
    normalized_name = _normalize_asc_symbol_name(symbol.symbol_name)  # Normalize the LTspice symbol name so the mapping logic is stable.
    if normalized_name == "res":  # Map LTspice resistor symbols to schemdraw resistors.
        return elm.Resistor()  # Return the configured schemdraw resistor element.
    if normalized_name == "cap":  # Map LTspice capacitor symbols to schemdraw capacitors.
        return elm.Capacitor()  # Return the configured schemdraw capacitor element.
    if normalized_name == "ind":  # Map LTspice inductor symbols to schemdraw inductors.
        return elm.Inductor()  # Return the configured schemdraw inductor element.
    if normalized_name == "diode":  # Map LTspice diode symbols to schemdraw diodes.
        return elm.Diode()  # Return the configured schemdraw diode element.
    if normalized_name == "voltage":  # Map LTspice independent voltage sources to schemdraw voltage sources.
        return elm.SourceV()  # Return the configured schemdraw voltage-source element.
    if normalized_name == "current":  # Map LTspice independent current sources to schemdraw current sources.
        return elm.SourceI()  # Return the configured schemdraw current-source element.
    if normalized_name == "f":  # Map LTspice CCCS symbols to schemdraw controlled current sources.
        return elm.SourceControlledI()  # Return the configured schemdraw controlled current-source element.
    return elm.Switch()  # Fall back to the generic switch symbol for LTspice switch elements and any other unmapped two-pin device.


def _apply_symbol_labels(element, symbol: AscSymbol):  # Attach compact instance and value labels to a schemdraw element when those attributes exist.
    instance_name = symbol.attributes.get("InstName", "").strip()  # Extract the LTspice instance name if one exists.
    if instance_name != "":  # Add the instance-name label only when the symbol carries one.
        element = element.label(instance_name, loc="top")  # Place the instance-name label above the schemdraw element.
    value_text = _clean_symbol_value(symbol)  # Extract a compact optional value or model label from the symbol attributes.
    if value_text != "":  # Add the secondary label only when a non-empty value exists.
        element = element.label(value_text, loc="bottom")  # Place the value or model label below the schemdraw element.
    return element  # Return the labeled schemdraw element for chaining.


def _clean_symbol_value(symbol: AscSymbol) -> str:  # Extract a compact user-facing value or model string from one parsed LTspice symbol.
    raw_value = symbol.attributes.get("Value", "").strip()  # Prefer the LTspice Value attribute when one exists.
    if raw_value in {"", '""'}:  # Ignore empty LTspice string values because they add no useful rendered text.
        raw_value = symbol.attributes.get("SpiceLine", "").strip()  # Fall back to SpiceLine content when Value is absent or empty.
    return raw_value  # Return the final compact displayed value string.


def _orientation_is_horizontal(orientation: str) -> bool:  # Decide whether one LTspice orientation token produces a horizontal two-pin symbol.
    return _orientation_angle(orientation) in {90, 270}  # Treat quarter-turn rotations as horizontal and everything else as vertical.


def _orientation_angle(orientation: str) -> int:  # Extract the rotation angle encoded in one LTspice orientation token.
    angle_match = re.search(r"(\d+)$", orientation)  # Read the trailing numeric rotation suffix from the orientation token.
    if angle_match is None:  # Fall back when the orientation token does not end in a numeric angle.
        return 0  # Treat malformed or missing rotations as the default zero-degree orientation.
    return int(angle_match.group(1)) % 360  # Normalize the parsed rotation angle into the canonical 0-359 range.


def _apply_orientation_to_schemdraw_element(element, orientation: str):  # Apply one LTspice orientation token to a schemdraw element as closely as possible.
    if orientation.upper().startswith("M"):  # Approximate LTspice mirrored symbols through schemdraw's vertical flip operation.
        element = element.flip()  # Mirror the current schemdraw element before applying any explicit rotation angle.
    angle = _orientation_angle(orientation)  # Extract the explicit rotation angle from the LTspice orientation token.
    if angle != 0:  # Apply only non-zero rotations because schemdraw's default orientation already covers zero degrees.
        element = element.theta(angle)  # Rotate the current schemdraw element to approximate the LTspice orientation.
    return element  # Return the oriented schemdraw element for chaining.


def _order_two_pin_points_for_orientation(first_point: Point, second_point: Point, orientation: str) -> Tuple[Point, Point]:  # Order a two-pin point pair to roughly respect the LTspice rotation token.
    angle = _orientation_angle(orientation)  # Extract the explicit LTspice rotation angle from the orientation token.
    if angle == 90:  # Order ninety-degree horizontal components from left to right.
        return (first_point, second_point) if first_point[0] <= second_point[0] else (second_point, first_point)  # Return the ordered left-to-right pair.
    if angle == 270:  # Order two-hundred-seventy-degree horizontal components from right to left.
        return (first_point, second_point) if first_point[0] >= second_point[0] else (second_point, first_point)  # Return the ordered right-to-left pair.
    if angle == 180:  # Order one-hundred-eighty-degree vertical components from bottom to top.
        return (first_point, second_point) if first_point[1] >= second_point[1] else (second_point, first_point)  # Return the ordered bottom-to-top pair.
    return (first_point, second_point) if first_point[1] <= second_point[1] else (second_point, first_point)  # Default to the LTspice zero-degree top-to-bottom ordering.


def _normalize_asc_symbol_name(symbol_name: str) -> str:  # Normalize one LTspice symbol-library path into a stable lowercase base name.
    return symbol_name.split("\\")[-1].lower()  # Keep only the final symbol name after any LTspice library path prefix.


def _point_manhattan_distance(first_point: Point, second_point: Point) -> int:  # Compute one Manhattan distance between two LTspice coordinate pairs.
    return abs(first_point[0] - second_point[0]) + abs(first_point[1] - second_point[1])  # Return the summed axis-aligned distance.


def _rewrite_svg_dimensions(output_path: str, width: int, height: int) -> None:  # Normalize one emitted schemdraw SVG file to the caller-requested pixel dimensions.
    svg_text = Path(output_path).read_text(encoding="utf-8")  # Read the emitted SVG document text from disk for in-place normalization.
    svg_text = re.sub(r'width="[^"]+"', f'width="{width}px"', svg_text, count=1)  # Replace the root SVG width attribute with the requested pixel width.
    svg_text = re.sub(r'height="[^"]+"', f'height="{height}px"', svg_text, count=1)  # Replace the root SVG height attribute with the requested pixel height.
    Path(output_path).write_text(svg_text, encoding="utf-8")  # Write the normalized SVG document back to disk.


def _resize_raster_image(output_path: str, extension: str, width: int, height: int) -> None:  # Resize one emitted schemdraw raster file to the caller-requested exact dimensions.
    from PIL import Image  # Import Pillow lazily so non-plotting callers do not require raster support at import time.

    with Image.open(output_path) as image:  # Open the emitted schemdraw raster file for exact-size normalization.
        if image.size == (width, height):  # Skip the extra raster pass when the backend already produced the requested dimensions exactly.
            return  # Leave the already-correct raster output unchanged.
        resized_image = image.resize((width, height), Image.Resampling.LANCZOS)  # Resize the emitted raster image to the exact requested dimensions.
        if extension in {".jpg", ".jpeg"} and resized_image.mode not in {"RGB", "L"}:  # Normalize JPEG outputs into a non-alpha-compatible color mode.
            resized_image = resized_image.convert("RGB")  # Drop any alpha channel before saving the JPEG output.
        save_format = "JPEG" if extension in {".jpg", ".jpeg"} else "PNG"  # Select the Pillow save format that matches the requested raster extension.
        resized_image.save(output_path, format=save_format)  # Overwrite the raster output file with the exact-size normalized image.
