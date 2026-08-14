"""LTspice ASY symbol to KiCad symbol library conversion API."""  # Describe the module purpose.

# The KiCad symbol shape emitted by this module mirrors the symbol library
# format produced by the kicad-tools project's `kicad_tools.schema.library`
# module (MIT licensed, Copyright (c) 2024 RJ Walters) and the f-string
# symbol assembly pattern used by the KiCAD-MCP-Server project's
# `SymbolCreator` (MIT licensed). The quoted-string escaping helper is copied
# from the KiCAD-MCP-Server project's `utils/sexpr_format.py` (MIT licensed).
# No third-party packages are imported; the generator code below is a local
# re-implementation written against the vendored KiCad S-expression format
# used by this repository.

from __future__ import annotations  # Postpone annotation evaluation for forward references.

import datetime  # Derive the default KiCad format version from the current date.
import math  # Compute arc geometry for KiCad arc records.
import os  # Resolve and create filesystem paths for the output file.
import re  # Parse line numbers out of validator messages.
from numbers import Real  # Validate numeric settings values.
from typing import Any  # Type generic record tuples.
from typing import Dict  # Type the collected SYMATTR attribute map.
from typing import List  # Type collected record lists.
from typing import Mapping  # Type the convert_settings parameter.
from typing import Optional  # Type optional parse results.
from typing import Sequence  # Type the parsed source line sequence.
from typing import Tuple  # Type tuple-shaped helper results.

from .kicad_symbol import is_valid_kicad_symbol_file  # Validate the generated KiCad symbol file.
from .ltspice_asy import _read_text_file_lines  # Reuse the encoding-aware ASY line reader.
from .ltspice_asy import is_valid_ltspice_asy  # Validate the LTspice ASY input file.

ConversionResult = Tuple[bool, str, int]  # Define the public conversion return shape.

_MM_PER_LTSPICE_UNIT = 1.27 / 16.0  # Map 16 LTspice units to 1.27 mm, per the KiCad LTspice importer.

_KICAD_GRID = 1.27  # Use the standard KiCad symbol grid for centering snap.

_DEFAULT_PIN_LENGTH = 2.54  # Use KiCad's standard pin length when the ASY carries no length.

_NORMAL_STROKE_WIDTH = 0.254  # Map LTspice Normal drawing width to KiCad millimeters.
_WIDE_STROKE_WIDTH = 0.508  # Map LTspice Wide drawing width to KiCad millimeters.

_VERSION_PATTERN = re.compile(r"^\d{8}$")  # Match KiCad version tokens in YYYYMMDD date format.

_LINE_SUFFIX_PATTERN = re.compile(r"Line (\d+)\s*$")  # Extract trailing line numbers from validator messages.

_PREFIX_TO_REFERENCE = {  # Map LTspice SYMATTR Prefix values onto KiCad reference designator prefixes.
    "X": "U",  # Subcircuit symbols become U-prefixed parts in KiCad.
    "A": "U",  # Special-function devices become U-prefixed parts.
    "@": "U",  # FRA analyzer devices become U-prefixed parts.
    "&": "U",  # FRA probe devices become U-prefixed parts.
    "M": "Q",  # Generic MOSFET prefixes map onto Q.
    "MN": "Q",  # N-channel MOSFET prefixes map onto Q.
    "MP": "Q",  # P-channel MOSFET prefixes map onto Q.
    "NMOS": "Q",  # Named NMOS prefixes map onto Q.
    "PMOS": "Q",  # Named PMOS prefixes map onto Q.
    "R": "R",  # Resistors keep their R prefix.
    "C": "C",  # Capacitors keep their C prefix.
    "L": "L",  # Inductors keep their L prefix.
    "D": "D",  # Diodes keep their D prefix.
    "Q": "Q",  # BJTs keep their Q prefix.
    "J": "Q",  # JFETs map onto the Q prefix.
    "Z": "Q",  # MESFETs and IGBTs map onto the Q prefix.
    "T": "T",  # Lossless transmission lines keep their T prefix.
    "O": "T",  # Lossy transmission lines map onto the T prefix.
    "V": "V",  # Voltage sources keep their V prefix.
    "I": "I",  # Current sources keep their I prefix.
    "E": "E",  # Voltage-controlled voltage sources keep their E prefix.
    "F": "F",  # Current-controlled current sources keep their F prefix.
    "G": "G",  # Voltage-controlled current sources keep their G prefix.
    "H": "H",  # Current-controlled voltage sources keep their H prefix.
    "S": "S",  # Voltage-controlled switches keep their S prefix.
    "W": "S",  # Current-controlled switches map onto the S prefix.
    "B": "B",  # Behavioral sources keep their B prefix.
    "K": "K",  # Coupling symbols keep their K prefix.
    "U": "U",  # Uniform RC lines keep their U prefix.
}  # Finish the LTspice prefix mapping table.

_POWER_PIN_NAMES = frozenset(  # Collect pin names treated as power inputs.
    {
        "VCC",  # Positive supply name.
        "VDD",  # Positive digital supply name.
        "VSS",  # Negative digital supply name.
        "VEE",  # Negative supply name.
        "V+",  # Positive supply symbol.
        "V-",  # Negative supply symbol.
        "+",  # Positive battery terminal.
        "-",  # Negative battery terminal.
        "GND",  # Ground reference name.
        "VREF",  # Reference voltage name.
        "VIN",  # Power input name.
        "VIN1",  # First power input name.
        "VIN2",  # Second power input name.
        "COM",  # Common return name.
    }
)  # Finish the power pin name set.

_OUTPUT_PIN_NAMES = frozenset({"OUT", "OUTPUT"})  # Collect pin names treated as outputs.

_INPUT_PIN_NAMES = frozenset(  # Collect pin names treated as inputs.
    {
        "G",  # Gate pin name.
        "B",  # Base pin name.
        "EN",  # Enable pin name.
        "ENABLE",  # Enable pin name.
        "SD",  # Shutdown pin name.
        "SHDN",  # Shutdown pin name.
        "CTRL",  # Control pin name.
        "IN",  # Input pin name.
        "IN+",  # Non-inverting input pin name.
        "IN-",  # Inverting input pin name.
    }
)  # Finish the input pin name set.

_JUSTIFICATION_TO_ANGLE = {  # Map LTspice PIN justification onto the KiCad outward pin angle.
    # KiCad pin angles: 0 extends west, 90 extends south, 180 extends east,
    # and 270 extends north. LTspice PIN justification names the side of the
    # symbol the pin leaves, which is the same outward direction.
    "LEFT": 0,  # Left-side pins extend west.
    "RIGHT": 180,  # Right-side pins extend east.
    "TOP": 270,  # Top-side pins extend north.
    "BOTTOM": 90,  # Bottom-side pins extend south.
}  # Finish the justification angle mapping table.

_SIDE_ANGLE_ORDER = (  # Define the tie-break order used for geometric side detection.
    ("left", 0),  # Prefer the left side on exact corner ties.
    ("right", 180),  # Then the right side.
    ("top", 270),  # Then the top side.
    ("bottom", 90),  # Then the bottom side.
)  # Finish the geometric tie-break order.

_SIDE_TO_ANGLE = dict(_SIDE_ANGLE_ORDER)  # Index the geometric side names onto their outward angles.


def ltspice_asy_to_kicad_symbol(  # Convert one LTspice ASY symbol file into one KiCad symbol library file.
    ltspice_asy_filepath: str,  # Accept the LTspice symbol source path.
    kicad_symbol_filepath_out: str,  # Accept the KiCad symbol output path.
    convert_settings: Mapping,  # Accept the conversion configuration mapping.
) -> ConversionResult:  # Return the shared conversion result tuple.
    """Convert one LTspice ``.asy`` symbol into one KiCad ``.kicad_sym`` library.

    The generated file defines a single top-level symbol named after the ASY
    file stem. Body graphics (LINE, RECTANGLE, CIRCLE, ARC) are carried by the
    ``<NAME>_0_1`` sub-symbol and pins by the ``<NAME>_1_1`` sub-symbol,
    mirroring the symbol shape emitted by kicad-tools and KiCAD-MCP-Server.
    Coordinates are scaled by 16 LTspice units per 1.27 mm with the Y axis
    flipped, and the finished symbol is centered on the 1.27 mm grid.

    Optional ``convert_settings`` keys:

    - ``kicad_symbol_version``: eight-digit YYYYMMDD version (default today).
    - ``kicad_symbol_generator``: generator string (default ``electronics_design``).
    - ``kicad_symbol_default_footprint``: footprint property (default ``""``).
    - ``kicad_symbol_default_datasheet``: datasheet property (default ``"~"``).
    - ``kicad_symbol_pin_length``: pin length in mm (default ``2.54``).

    Returns ``(True, "OK", 0)`` on success or ``(False, "<error code>", <line>)``
    on failure.
    """
    settings_result = _normalize_convert_settings(convert_settings)  # Validate the conversion settings first.
    if not settings_result[0]:  # Stop when the settings are unusable.
        return False, "INVALID_CONVERT_SETTINGS", 0  # Return the required settings error code.
    settings = settings_result[1]  # Read the normalized settings dictionary.
    output_result = _coerce_output_path(kicad_symbol_filepath_out)  # Coerce the output path safely.
    if not output_result[0]:  # Stop when the output path is not path-like.
        return False, "INVALID_OUTPUT_PATH", 0  # Return the required output path error code.
    output_path = output_result[1]  # Read the coerced output path string.
    input_result = _coerce_input_path(ltspice_asy_filepath)  # Coerce and check the input path.
    if not input_result[0]:  # Stop when the input path is unusable.
        return False, "INVALID_ASY_FILE", 0  # Return the required ASY file error code.
    input_path = input_result[1]  # Read the coerced input path string.
    validation_result = is_valid_ltspice_asy(input_path)  # Validate the ASY structure before conversion.
    if not validation_result[0]:  # Stop when the ASY file fails validation.
        return False, "INVALID_ASY_FILE", _line_from_message(validation_result[1])  # Return the failing source line.
    read_result = _read_text_file_lines(input_path)  # Read the ASY lines with encoding detection.
    if not read_result[0]:  # Stop when the ASY lines cannot be read.
        return False, "INVALID_ASY_FILE", 0  # Return the required ASY file error code.
    parse_result = _parse_asy_records(read_result[1])  # Extract geometry, pins, and attributes.
    if not parse_result[0]:  # Stop when a pin record is incomplete.
        return False, "ASY_PARSE_ERROR", parse_result[2]  # Return the failing pin line.
    records = parse_result[1]  # Read the parsed record collection.
    symbol_name = _input_stem(input_path)  # Name the KiCad symbol after the ASY file stem.
    symbol_text = _build_kicad_symbol_text(symbol_name, records, settings)  # Assemble the KiCad symbol text.
    write_result = _write_text_file(output_path, symbol_text)  # Write the generated symbol file.
    if not write_result[0]:  # Stop when the output cannot be written.
        return False, "WRITE_ERROR", 0  # Return the required write error code.
    generated_result = is_valid_kicad_symbol_file(output_path)  # Validate the freshly written symbol file.
    if not generated_result[0]:  # Stop when the generated file fails the symbol validator.
        return False, "INVALID_GENERATED_KICAD_SYMBOL", _line_from_message(generated_result[1])  # Return the failing output line.
    return True, "OK", 0  # Return success when the conversion completed.


def _normalize_convert_settings(convert_settings: Mapping) -> Tuple[bool, Optional[Dict[str, Any]]]:  # Validate and fill the conversion settings.
    if not isinstance(convert_settings, Mapping):  # Require a mapping-like settings object.
        return False, None  # Signal the settings failure.
    version_value = convert_settings.get("kicad_symbol_version")  # Read the optional version override.
    if version_value is None:  # Fall back to the current date when unset.
        version_value = datetime.date.today().strftime("%Y%m%d")  # Build the default eight-digit date version.
    if not _VERSION_PATTERN.match(str(version_value)):  # Require the YYYYMMDD version shape.
        return False, None  # Signal the settings failure.
    generator_value = convert_settings.get("kicad_symbol_generator", "electronics_design")  # Read the generator override.
    if not isinstance(generator_value, str) or generator_value == "":  # Require a nonempty generator string.
        return False, None  # Signal the settings failure.
    footprint_value = convert_settings.get("kicad_symbol_default_footprint", "")  # Read the default footprint.
    datasheet_value = convert_settings.get("kicad_symbol_default_datasheet", "~")  # Read the default datasheet.
    pin_length_value = convert_settings.get("kicad_symbol_pin_length", _DEFAULT_PIN_LENGTH)  # Read the pin length override.
    if isinstance(pin_length_value, bool) or not isinstance(pin_length_value, Real) or pin_length_value <= 0:  # Require a positive numeric length.
        return False, None  # Signal the settings failure.
    settings = {  # Assemble the normalized settings dictionary.
        "version": str(version_value),  # Store the checked version string.
        "generator": generator_value,  # Store the generator string.
        "footprint": str(footprint_value),  # Store the footprint property string.
        "datasheet": str(datasheet_value),  # Store the datasheet property string.
        "pin_length": float(pin_length_value),  # Store the numeric pin length.
    }  # Finish the settings assembly.
    return True, settings  # Return the normalized settings dictionary.


def _coerce_output_path(filepath: str) -> Tuple[bool, Optional[str]]:  # Convert the output path input into a filesystem string.
    try:  # Attempt path coercion through the standard library.
        path_string = os.fsdecode(os.fspath(filepath))  # Convert string, bytes, or path-like input.
    except TypeError:  # Catch non-path-like output values.
        return False, None  # Signal the output path failure.
    return True, os.path.expanduser(path_string)  # Return the expanded output path string.


def _coerce_input_path(filepath: str) -> Tuple[bool, Optional[str]]:  # Convert and check the input path.
    try:  # Attempt path coercion through the standard library.
        path_string = os.fsdecode(os.fspath(filepath))  # Convert string, bytes, or path-like input.
    except TypeError:  # Catch non-path-like input values.
        return False, None  # Signal the input path failure.
    expanded_path = os.path.expanduser(path_string)  # Expand any configurable user-relative prefix.
    if not os.path.exists(expanded_path):  # Require the input file to exist.
        return False, None  # Signal the input path failure.
    if not os.access(expanded_path, os.R_OK):  # Require read permission on the input file.
        return False, None  # Signal the input path failure.
    return True, expanded_path  # Return the checked input path string.


def _input_stem(input_path: str) -> str:  # Derive the KiCad symbol name from the input file stem.
    base_name = os.path.basename(input_path)  # Strip any parent directory from the path.
    stem, _extension = os.path.splitext(base_name)  # Remove the .asy extension.
    return stem  # Return the file stem as the symbol name.


def _line_from_message(message: str) -> int:  # Extract a trailing line number from a validator message.
    match = _LINE_SUFFIX_PATTERN.search(message or "")  # Search the message for a trailing line suffix.
    if match is None:  # Return zero when no line suffix is present.
        return 0  # Report an unknown line.
    return int(match.group(1))  # Return the extracted one-based line number.


def _write_text_file(filepath: str, text: str) -> Tuple[bool, None]:  # Write the generated text to disk safely.
    parent_directory = os.path.dirname(filepath)  # Read the output parent directory.
    if parent_directory:  # Create the parent directory only when one is needed.
        try:  # Attempt to create any missing parent directories.
            os.makedirs(parent_directory, exist_ok=True)  # Create the directory tree idempotently.
        except OSError:  # Catch directory creation failures.
            return False, None  # Signal the write failure.
    try:  # Attempt the file write.
        with open(filepath, "w", encoding="utf-8", newline="\n") as file_handle:  # Open the output in UTF-8 text mode.
            file_handle.write(text)  # Write the assembled symbol text.
    except OSError:  # Catch permission, disk, and path failures.
        return False, None  # Signal the write failure.
    return True, None  # Return success after the write completes.


def _parse_asy_records(lines: Sequence[str]) -> Tuple[bool, Optional[Dict[str, Any]], int]:  # Extract geometry, pins, and attributes from ASY lines.
    geometry: List[Tuple[Any, ...]] = []  # Collect drawing record tuples.
    pins: List[Tuple[int, int, str, int, str]] = []  # Collect pin tuples as (x, y, name, spice_order, justification).
    attributes: Dict[str, str] = {}  # Collect uppercase SYMATTR keys onto their values.
    current_pin_x = 0  # Track the active pin X coordinate.
    current_pin_y = 0  # Track the active pin Y coordinate.
    current_pin_name = ""  # Track the active pin name.
    current_pin_order: Optional[int] = None  # Track the active pin spice order.
    current_pin_justification = "NONE"  # Track the active pin justification.
    current_pin_line_number = 0  # Track the active pin source line.
    for line_number, raw_line in enumerate(lines, start=1):  # Walk every source line with a one-based number.
        tokens = raw_line.split()  # Tokenize the current line.
        if not tokens:  # Skip blank lines.
            continue  # Move to the next line.
        keyword = tokens[0].upper()  # Normalize the line keyword.
        if keyword == "PIN":  # Start a new pin record.
            finalized = _finalize_pin(  # Finalize the previous pin record first.
                pins,  # Pass the accumulating pin list.
                current_pin_x,  # Pass the previous pin X.
                current_pin_y,  # Pass the previous pin Y.
                current_pin_name,  # Pass the previous pin name.
                current_pin_order,  # Pass the previous pin spice order.
                current_pin_justification,  # Pass the previous pin justification.
                current_pin_line_number,  # Pass the previous pin source line.
            )  # Finalize the previous pin.
            if not finalized[0]:  # Stop when the previous pin lacks a spice order.
                return False, None, finalized[1]  # Return the failing pin line.
            current_pin_x = int(tokens[1])  # Record the new pin X coordinate.
            current_pin_y = int(tokens[2])  # Record the new pin Y coordinate.
            current_pin_name = ""  # Reset the pin name for the new pin.
            current_pin_order = None  # Reset the spice order for the new pin.
            current_pin_justification = tokens[3].upper() if len(tokens) > 3 else "NONE"  # Record the pin justification.
            current_pin_line_number = line_number  # Record the pin source line.
            continue  # Move to the next line.
        if keyword == "PINATTR" and current_pin_line_number != 0:  # Attach an attribute to the active pin.
            attribute_tokens = raw_line.split(maxsplit=2)  # Split key and value while preserving the value text.
            if len(attribute_tokens) < 3:  # Skip malformed attribute lines defensively.
                continue  # Move to the next line.
            attribute_name = attribute_tokens[1].upper()  # Normalize the attribute key.
            attribute_value = attribute_tokens[2]  # Read the attribute value text.
            if attribute_name == "PINNAME":  # Record the pin name attribute.
                current_pin_name = attribute_value  # Store the pin name text.
            elif attribute_name == "SPICEORDER":  # Record the spice order attribute.
                current_pin_order = int(attribute_value)  # Store the numeric spice order.
            continue  # Move to the next line.
        finalized = _finalize_pin(  # Any other keyword ends the active pin record.
            pins,  # Pass the accumulating pin list.
            current_pin_x,  # Pass the active pin X.
            current_pin_y,  # Pass the active pin Y.
            current_pin_name,  # Pass the active pin name.
            current_pin_order,  # Pass the active pin spice order.
            current_pin_justification,  # Pass the active pin justification.
            current_pin_line_number,  # Pass the active pin source line.
        )  # Finalize the active pin.
        if not finalized[0]:  # Stop when the active pin lacks a spice order.
            return False, None, finalized[1]  # Return the failing pin line.
        current_pin_line_number = 0  # Reset the active pin marker.
        if keyword == "SYMATTR":  # Record symbol attribute overrides.
            attribute_tokens = raw_line.split(maxsplit=2)  # Split key and value while preserving the value text.
            if len(attribute_tokens) >= 3:  # Guard against malformed attribute lines.
                attributes[attribute_tokens[1].upper()] = attribute_tokens[2]  # Store the uppercase attribute key.
            continue  # Move to the next line.
        geometry_record = _geometry_record(raw_line, keyword)  # Try to parse a drawing record.
        if geometry_record is not None:  # Append recognized drawing records.
            geometry.append(geometry_record)  # Store the parsed drawing record.
    finalized = _finalize_pin(  # Finalize the trailing pin after the last line.
        pins,  # Pass the accumulating pin list.
        current_pin_x,  # Pass the trailing pin X.
        current_pin_y,  # Pass the trailing pin Y.
        current_pin_name,  # Pass the trailing pin name.
        current_pin_order,  # Pass the trailing pin spice order.
        current_pin_justification,  # Pass the trailing pin justification.
        current_pin_line_number,  # Pass the trailing pin source line.
    )  # Finalize the trailing pin.
    if not finalized[0]:  # Stop when the trailing pin lacks a spice order.
        return False, None, finalized[1]  # Return the failing pin line.
    pins.sort(key=lambda pin: pin[3])  # Order pins by spice order like the original symbol.
    records = {  # Assemble the parsed record collection.
        "geometry": geometry,  # Store the drawing records.
        "pins": pins,  # Store the sorted pin records.
        "attributes": attributes,  # Store the SYMATTR attribute map.
    }  # Finish the record collection.
    return True, records, 0  # Return the parsed records.


def _finalize_pin(  # Commit one parsed pin record when it is complete.
    pins: List[Tuple[int, int, str, int, str]],  # Accept the accumulating pin list.
    pin_x: int,  # Accept the pin X coordinate.
    pin_y: int,  # Accept the pin Y coordinate.
    pin_name: str,  # Accept the pin name.
    pin_order: Optional[int],  # Accept the pin spice order.
    pin_justification: str,  # Accept the pin justification.
    pin_line_number: int,  # Accept the pin source line.
) -> Tuple[bool, int]:  # Return success or the failing line.
    if pin_line_number == 0:  # Skip when no pin is active.
        return True, 0  # Return success with no work.
    if pin_order is None:  # Require a spice order on every pin.
        return False, pin_line_number  # Return the failing pin line.
    pins.append((pin_x, pin_y, pin_name, pin_order, pin_justification))  # Commit the complete pin record.
    return True, 0  # Return success.


def _geometry_record(raw_line: str, keyword: str) -> Optional[Tuple[Any, ...]]:  # Parse one ASY drawing record into a tuple.
    tokens = raw_line.split()  # Tokenize the drawing line.
    if keyword in {"LINE", "RECTANGLE", "CIRCLE"}:  # Handle the three four-coordinate primitives.
        if len(tokens) < 6:  # Guard against short drawing lines.
            return None  # Skip unparseable drawing lines.
        return (keyword, tokens[1].upper(), int(tokens[2]), int(tokens[3]), int(tokens[4]), int(tokens[5]))  # Return the primitive tuple.
    if keyword == "ARC":  # Handle the eight-coordinate arc primitive.
        if len(tokens) < 10:  # Guard against short arc lines.
            return None  # Skip unparseable arc lines.
        return (  # Return the arc tuple with bounding box and endpoints.
            keyword,  # Store the arc keyword.
            tokens[1].upper(),  # Store the arc width class.
            int(tokens[2]),  # Store the bounding box X1.
            int(tokens[3]),  # Store the bounding box Y1.
            int(tokens[4]),  # Store the bounding box X2.
            int(tokens[5]),  # Store the bounding box Y2.
            int(tokens[6]),  # Store the arc start X.
            int(tokens[7]),  # Store the arc start Y.
            int(tokens[8]),  # Store the arc end X.
            int(tokens[9]),  # Store the arc end Y.
        )  # Finish the arc tuple.
    return None  # Ignore WINDOW, TEXT, and other non-drawing records.


def _build_kicad_symbol_text(symbol_name: str, records: Dict[str, Any], settings: Dict[str, Any]) -> str:  # Assemble the full KiCad symbol library text.
    geometry = records["geometry"]  # Read the drawing records.
    pins = records["pins"]  # Read the pin records.
    attributes = records["attributes"]  # Read the SYMATTR attributes.
    body_bounds = _geometry_bounds(geometry)  # Compute the body bounds in LTspice units.
    transformed_geometry = _transform_geometry(geometry, body_bounds)  # Scale and flip every drawing record.
    transformed_pins = []  # Collect the transformed pin records.
    for pin in pins:  # Walk every parsed pin record.
        scaled_x, scaled_y = _scale_point(pin[0], pin[1])  # Scale the current pin coordinates.
        transformed_pins.append(  # Append the transformed pin tuple.
            (scaled_x, scaled_y, pin[2], pin[3], _pin_angle(pin[0], pin[1], pin[4], body_bounds))  # Carry name, order, and the derived angle.
        )  # Finish the transformed pin tuple.
    symbol_bounds = _symbol_bounds(transformed_geometry, transformed_pins)  # Compute the total bounds in millimeters.
    offset_x, offset_y = _centering_offset(symbol_bounds)  # Compute the grid-snapped centering offset.
    centered_geometry = [  # Apply the centering offset to every geometry record.
        _offset_geometry(record, offset_x, offset_y)  # Offset the current drawing record.
        for record in transformed_geometry  # Walk every transformed drawing record.
    ]  # Finish the centered geometry list.
    centered_pins = [  # Apply the centering offset to every pin.
        (round(pin[0] - offset_x, 6), round(pin[1] - offset_y, 6), pin[2], pin[3], pin[4])  # Offset the current pin coordinates.
        for pin in transformed_pins  # Walk every transformed pin.
    ]  # Finish the centered pin list.
    reference_prefix = _reference_prefix(attributes.get("PREFIX", ""))  # Map the LTspice prefix onto a KiCad reference prefix.
    value_text = attributes.get("VALUE", "") or symbol_name  # Fall back to the file stem for the value property.
    description_text = attributes.get("DESCRIPTION", "")  # Read the optional description attribute.
    reference_y = symbol_bounds[3] - offset_y + 2.54  # Place the reference property above the centered body.
    value_y = reference_y - 1.27  # Stack the value property below the reference property.
    lines: List[str] = [  # Begin assembling the symbol library text.
        "(kicad_symbol_lib",  # Open the root library expression.
        f"\t(version {settings['version']})",  # Emit the KiCad format version.
        f'\t(generator "{_esc(settings["generator"])}")',  # Emit the generator name.
        f'\t(symbol "{_esc(symbol_name)}"',  # Open the top-level symbol entry.
        "\t\t(exclude_from_sim no)",  # Keep the symbol in simulation.
        "\t\t(in_bom yes)",  # Include the symbol in bills of materials.
        "\t\t(on_board yes)",  # Export the symbol footprint to the board.
    ]  # Finish the header lines.
    lines.extend(_property_lines("Reference", reference_prefix, 0.0, reference_y, hidden=False))  # Emit the reference property.
    lines.extend(_property_lines("Value", value_text, 0.0, value_y, hidden=False))  # Emit the value property.
    lines.extend(_property_lines("Footprint", settings["footprint"], 0.0, 0.0, hidden=True))  # Emit the hidden footprint property.
    lines.extend(_property_lines("Datasheet", settings["datasheet"], 0.0, 0.0, hidden=True))  # Emit the hidden datasheet property.
    if description_text:  # Emit the description property only when the ASY carries one.
        lines.extend(_property_lines("Description", description_text, 0.0, 0.0, hidden=True))  # Emit the hidden description property.
    if centered_geometry:  # Emit the body sub-symbol only when drawing records exist.
        lines.append(f'\t\t(symbol "{_esc(symbol_name)}_0_1"')  # Open the body graphics sub-symbol.
        for record in centered_geometry:  # Walk every centered drawing record.
            lines.extend(_geometry_lines(record))  # Emit the current drawing record.
        lines.append("\t\t)")  # Close the body sub-symbol.
    if centered_pins:  # Emit the pin sub-symbol only when pins exist.
        lines.append(f'\t\t(symbol "{_esc(symbol_name)}_1_1"')  # Open the pin sub-symbol.
        for pin in centered_pins:  # Walk every centered pin record.
            lines.extend(_pin_lines(pin, settings["pin_length"]))  # Emit the current pin record.
        lines.append("\t\t)")  # Close the pin sub-symbol.
    lines.append("\t)")  # Close the top-level symbol entry.
    lines.append(")")  # Close the root library expression.
    return "\n".join(lines) + "\n"  # Join the lines into the final file text.


def _geometry_bounds(geometry: Sequence[Tuple[Any, ...]]) -> Tuple[int, int, int, int]:  # Compute the drawing bounds in LTspice units.
    all_x: List[int] = []  # Collect every drawing X coordinate.
    all_y: List[int] = []  # Collect every drawing Y coordinate.
    for record in geometry:  # Walk every drawing record.
        kind = record[0]  # Read the drawing kind.
        if kind in {"LINE", "RECTANGLE", "CIRCLE"}:  # Handle the four-coordinate primitives.
            all_x.extend((record[2], record[4]))  # Collect both X coordinates.
            all_y.extend((record[3], record[5]))  # Collect both Y coordinates.
        elif kind == "ARC":  # Handle the arc primitive.
            all_x.extend((record[2], record[4]))  # Collect the bounding box X coordinates.
            all_y.extend((record[3], record[5]))  # Collect the bounding box Y coordinates.
    if not all_x:  # Fall back to a degenerate bound when no drawing exists.
        return 0, 0, 0, 0  # Return the degenerate bounds.
    return min(all_x), min(all_y), max(all_x), max(all_y)  # Return the minimum and maximum bounds.


def _scale_point(x: float, y: float) -> Tuple[float, float]:  # Scale one LTspice point into KiCad millimeters.
    return round(x * _MM_PER_LTSPICE_UNIT, 6), round(-y * _MM_PER_LTSPICE_UNIT, 6)  # Scale X and flip Y into millimeters.


def _pin_angle(pin_x: int, pin_y: int, justification: str, body_bounds: Tuple[int, int, int, int]) -> int:  # Derive the outward pin angle.
    if justification in _JUSTIFICATION_TO_ANGLE:  # Prefer the explicit justification mapping.
        return _JUSTIFICATION_TO_ANGLE[justification]  # Return the justification angle.
    minimum_x, minimum_y, maximum_x, maximum_y = body_bounds  # Unpack the body bounds.
    distances = {  # Compute the signed distance from the pin to each body side.
        "left": pin_x - minimum_x,  # Distance toward the left side.
        "right": maximum_x - pin_x,  # Distance toward the right side.
        "top": pin_y - minimum_y,  # Distance toward the top side.
        "bottom": maximum_y - pin_y,  # Distance toward the bottom side.
    }  # Finish the side distance map.
    best_side, best_distance = "left", distances["left"]  # Start with the left side.
    for side, _angle in _SIDE_ANGLE_ORDER[1:]:  # Walk the remaining sides in tie-break order.
        if distances[side] < best_distance:  # Replace the best side on a strictly smaller distance.
            best_side = side  # Update the best side name.
            best_distance = distances[side]  # Update the best distance.
    return _SIDE_TO_ANGLE[best_side]  # Return the angle of the nearest body side.


def _transform_geometry(geometry: Sequence[Tuple[Any, ...]], body_bounds: Tuple[int, int, int, int]) -> List[Tuple[Any, ...]]:  # Scale and flip every drawing record.
    transformed: List[Tuple[Any, ...]] = []  # Collect the transformed drawing records.
    for record in geometry:  # Walk every drawing record.
        kind = record[0]  # Read the drawing kind.
        width_class = record[1]  # Read the drawing width class.
        width = _WIDE_STROKE_WIDTH if width_class == "WIDE" else _NORMAL_STROKE_WIDTH  # Map the width class to millimeters.
        if kind in {"LINE", "RECTANGLE", "CIRCLE"}:  # Handle the four-coordinate primitives.
            x1, y1 = _scale_point(record[2], record[3])  # Scale the first corner.
            x2, y2 = _scale_point(record[4], record[5])  # Scale the opposite corner.
            transformed.append((kind, width, x1, y1, x2, y2))  # Store the transformed primitive.
        elif kind == "ARC":  # Handle the arc primitive.
            start_x, start_y = _scale_point(record[6], record[7])  # Scale the arc start point.
            end_x, end_y = _scale_point(record[8], record[9])  # Scale the arc end point.
            mid_x, mid_y = _arc_midpoint(record[2], record[3], record[4], record[5], record[6], record[7], record[8], record[9])  # Compute the arc midpoint in LTspice units.
            mid_x, mid_y = _scale_point(mid_x, mid_y)  # Scale the computed arc midpoint.
            transformed.append((kind, width, start_x, start_y, mid_x, mid_y, end_x, end_y))  # Store the transformed arc.
    return transformed  # Return the transformed drawing records.


def _arc_midpoint(  # Compute the counterclockwise arc midpoint in LTspice units.
    box_x1: int,  # Accept the arc bounding box X1.
    box_y1: int,  # Accept the arc bounding box Y1.
    box_x2: int,  # Accept the arc bounding box X2.
    box_y2: int,  # Accept the arc bounding box Y2.
    start_x: int,  # Accept the arc start X.
    start_y: int,  # Accept the arc start Y.
    end_x: int,  # Accept the arc end X.
    end_y: int,  # Accept the arc end Y.
) -> Tuple[float, float]:  # Return the midpoint coordinates.
    center_x = (box_x1 + box_x2) / 2.0  # Compute the circle center X.
    center_y = (box_y1 + box_y2) / 2.0  # Compute the circle center Y.
    start_angle = math.atan2(start_y - center_y, start_x - center_x)  # Compute the start angle on the circle.
    end_angle = math.atan2(end_y - center_y, end_x - center_x)  # Compute the end angle on the circle.
    delta = (end_angle - start_angle) % (2.0 * math.pi)  # Compute the counterclockwise sweep from start to end.
    mid_angle = start_angle + delta / 2.0  # Bisect the sweep for the midpoint angle.
    radius = math.hypot(start_x - center_x, start_y - center_y)  # Compute the arc radius from the start point.
    return center_x + radius * math.cos(mid_angle), center_y + radius * math.sin(mid_angle)  # Return the midpoint on the arc.


def _symbol_bounds(geometry: Sequence[Tuple[Any, ...]], pins: Sequence[Tuple[Any, ...]]) -> Tuple[float, float, float, float]:  # Compute the total symbol bounds in millimeters.
    all_x: List[float] = []  # Collect every X coordinate.
    all_y: List[float] = []  # Collect every Y coordinate.
    for record in geometry:  # Walk every transformed drawing record.
        kind = record[0]  # Read the drawing kind.
        if kind in {"LINE", "RECTANGLE", "CIRCLE"}:  # Handle the four-coordinate primitives.
            all_x.extend((record[2], record[4]))  # Collect both X coordinates.
            all_y.extend((record[3], record[5]))  # Collect both Y coordinates.
        elif kind == "ARC":  # Handle the arc primitive.
            all_x.extend((record[2], record[4], record[6]))  # Collect the arc X coordinates.
            all_y.extend((record[3], record[5], record[7]))  # Collect the arc Y coordinates.
    for pin in pins:  # Walk every transformed pin record.
        all_x.append(pin[0])  # Collect the pin X coordinate.
        all_y.append(pin[1])  # Collect the pin Y coordinate.
    if not all_x:  # Fall back to a degenerate bound when the symbol is empty.
        return 0.0, 0.0, 0.0, 0.0  # Return the degenerate bounds.
    return min(all_x), min(all_y), max(all_x), max(all_y)  # Return the minimum and maximum bounds.


def _centering_offset(bounds: Tuple[float, float, float, float]) -> Tuple[float, float]:  # Compute the grid-snapped centering offset.
    center_x = (bounds[0] + bounds[2]) / 2.0  # Compute the horizontal center.
    center_y = (bounds[1] + bounds[3]) / 2.0  # Compute the vertical center.
    offset_x = round(center_x / _KICAD_GRID) * _KICAD_GRID  # Snap the horizontal center onto the grid.
    offset_y = round(center_y / _KICAD_GRID) * _KICAD_GRID  # Snap the vertical center onto the grid.
    return offset_x, offset_y  # Return the centering offset.


def _offset_geometry(record: Tuple[Any, ...], offset_x: float, offset_y: float) -> Tuple[Any, ...]:  # Apply the centering offset to one drawing record.
    kind = record[0]  # Read the drawing kind.
    if kind in {"LINE", "RECTANGLE", "CIRCLE"}:  # Handle the four-coordinate primitives.
        return (  # Return the offset primitive tuple.
            kind,  # Preserve the drawing kind.
            record[1],  # Preserve the stroke width.
            round(record[2] - offset_x, 6),  # Offset the first X.
            round(record[3] - offset_y, 6),  # Offset the first Y.
            round(record[4] - offset_x, 6),  # Offset the second X.
            round(record[5] - offset_y, 6),  # Offset the second Y.
        )  # Finish the offset primitive tuple.
    return (  # Return the offset arc tuple.
        kind,  # Preserve the arc kind.
        record[1],  # Preserve the stroke width.
        round(record[2] - offset_x, 6),  # Offset the start X.
        round(record[3] - offset_y, 6),  # Offset the start Y.
        round(record[4] - offset_x, 6),  # Offset the mid X.
        round(record[5] - offset_y, 6),  # Offset the mid Y.
        round(record[6] - offset_x, 6),  # Offset the end X.
        round(record[7] - offset_y, 6),  # Offset the end Y.
    )  # Finish the offset arc tuple.


def _reference_prefix(prefix: str) -> str:  # Map one LTspice SYMATTR Prefix onto a KiCad reference prefix.
    normalized = prefix.strip().upper()  # Normalize the prefix text.
    if normalized in _PREFIX_TO_REFERENCE:  # Use the explicit mapping table first.
        return _PREFIX_TO_REFERENCE[normalized]  # Return the mapped KiCad prefix.
    for character in normalized:  # Walk the prefix characters for a fallback letter.
        if character.isalpha():  # Pick the first alphabetic character.
            return character  # Return the fallback letter prefix.
    return "U"  # Return the generic U prefix when no letter exists.


def _pin_electrical_type(pin_name: str) -> str:  # Guess the KiCad pin electrical type from the pin name.
    normalized = pin_name.strip().upper()  # Normalize the pin name text.
    if normalized in _POWER_PIN_NAMES:  # Match explicit power names first.
        return "power_in"  # Return the power input type.
    if normalized in _OUTPUT_PIN_NAMES or normalized.startswith("OUT"):  # Match output-style names.
        return "output"  # Return the output type.
    if normalized in _INPUT_PIN_NAMES or normalized.startswith("IN"):  # Match input-style names.
        return "input"  # Return the input type.
    return "passive"  # Return the passive default type.


def _esc(value: str) -> str:  # Escape a value for a KiCad double-quoted token.
    # Copied from the KiCAD-MCP-Server project's `escape_sexpr_string`
    # (utils/sexpr_format.py, MIT licensed). Backslash is escaped before
    # quote so embedded quote sequences survive the round trip.
    return value.replace("\\", "\\\\").replace('"', '\\"')  # Escape backslashes then quotes.


def _fmt(value: float) -> str:  # Format one millimeter coordinate compactly.
    return f"{round(value, 6):g}"  # Round away float noise and strip trailing zeros.


def _property_lines(key: str, value: str, x: float, y: float, hidden: bool) -> List[str]:  # Assemble one KiCad property block.
    lines = [  # Begin the property block.
        f'\t\t(property "{_esc(key)}" "{_esc(value)}"',  # Open the property with its key and value.
        f"\t\t\t(at {_fmt(x)} {_fmt(y)} 0)",  # Emit the property position.
        "\t\t\t(effects",  # Open the text effects section.
        "\t\t\t\t(font",  # Open the font section.
        "\t\t\t\t\t(size 1.27 1.27)",  # Emit the standard font size.
        "\t\t\t\t)",  # Close the font section.
    ]  # Finish the shared effect lines.
    if hidden:  # Append the hide flag when requested.
        lines.append("\t\t\t\t(hide yes)")  # Emit the hide flag.
    lines.extend(["\t\t\t)", "\t\t)"])  # Close the effects and property sections.
    return lines  # Return the assembled property block.


def _pin_lines(pin: Tuple[Any, ...], pin_length: float) -> List[str]:  # Assemble one KiCad pin block.
    pin_x, pin_y, pin_name, pin_order, pin_angle = pin  # Unpack the transformed pin tuple.
    pin_type = _pin_electrical_type(pin_name)  # Guess the pin electrical type.
    lines = [  # Begin the pin block.
        f"\t\t\t(pin {pin_type} line",  # Open the pin with its type and graphic style.
        f"\t\t\t\t(at {_fmt(pin_x)} {_fmt(pin_y)} {int(pin_angle)})",  # Emit the pin position and outward angle.
        f"\t\t\t\t(length {_fmt(pin_length)})",  # Emit the pin length.
        f'\t\t\t\t(name "{_esc(pin_name)}"',  # Open the pin name section.
        "\t\t\t\t\t(effects",  # Open the name effects section.
        "\t\t\t\t\t\t(font",  # Open the name font section.
        "\t\t\t\t\t\t\t(size 1.27 1.27)",  # Emit the name font size.
        "\t\t\t\t\t\t)",  # Close the name font section.
        "\t\t\t\t\t)",  # Close the name effects section.
        "\t\t\t\t)",  # Close the pin name section.
        f'\t\t\t\t(number "{_esc(str(pin_order))}"',  # Open the pin number section.
        "\t\t\t\t\t(effects",  # Open the number effects section.
        "\t\t\t\t\t\t(font",  # Open the number font section.
        "\t\t\t\t\t\t\t(size 1.27 1.27)",  # Emit the number font size.
        "\t\t\t\t\t\t)",  # Close the number font section.
        "\t\t\t\t\t)",  # Close the number effects section.
        "\t\t\t\t)",  # Close the pin number section.
        "\t\t\t)",  # Close the pin block.
    ]  # Finish the pin block lines.
    return lines  # Return the assembled pin block.


def _geometry_lines(record: Tuple[Any, ...]) -> List[str]:  # Assemble one KiCad drawing record block.
    kind = record[0]  # Read the drawing kind.
    if kind == "LINE":  # Emit a polyline for LTspice LINE records.
        return _polyline_lines([(record[2], record[3]), (record[4], record[5])], record[1], "none")  # Return the two-point polyline.
    if kind == "RECTANGLE":  # Emit a rectangle for LTspice RECTANGLE records.
        return _rectangle_lines(record[1], record[2], record[3], record[4], record[5])  # Return the rectangle block.
    if kind == "CIRCLE":  # Emit a circle for LTspice CIRCLE records.
        center_x = (record[2] + record[4]) / 2.0  # Compute the circle center X.
        center_y = (record[3] + record[5]) / 2.0  # Compute the circle center Y.
        radius = abs(record[4] - record[2]) / 2.0  # Compute the circle radius from the bounding box.
        return _circle_lines(center_x, center_y, radius, record[1])  # Return the circle block.
    return _arc_lines(record[1], record[2], record[3], record[4], record[5], record[6], record[7])  # Emit an arc for LTspice ARC records.


def _polyline_lines(points: Sequence[Tuple[float, float]], width: float, fill: str) -> List[str]:  # Assemble one KiCad polyline block.
    point_text = " ".join(f"(xy {_fmt(x)} {_fmt(y)})" for x, y in points)  # Serialize the point list compactly.
    return [  # Begin the polyline block.
        "\t\t\t(polyline",  # Open the polyline record.
        "\t\t\t\t(pts",  # Open the point list.
        f"\t\t\t\t\t{point_text}",  # Emit the serialized points.
        "\t\t\t\t)",  # Close the point list.
        "\t\t\t\t(stroke",  # Open the stroke section.
        f"\t\t\t\t\t(width {_fmt(width)})",  # Emit the stroke width.
        "\t\t\t\t\t(type default)",  # Emit the default stroke type.
        "\t\t\t\t)",  # Close the stroke section.
        "\t\t\t\t(fill",  # Open the fill section.
        f"\t\t\t\t\t(type {fill})",  # Emit the fill type.
        "\t\t\t\t)",  # Close the fill section.
        "\t\t\t)",  # Close the polyline block.
    ]  # Finish the polyline block.


def _rectangle_lines(width: float, x1: float, y1: float, x2: float, y2: float) -> List[str]:  # Assemble one KiCad rectangle block.
    start_x, end_x = min(x1, x2), max(x1, x2)  # Normalize the horizontal corners.
    start_y, end_y = max(y1, y2), min(y1, y2)  # Normalize the vertical corners with Y-up orientation.
    return [  # Begin the rectangle block.
        "\t\t\t(rectangle",  # Open the rectangle record.
        f"\t\t\t\t(start {_fmt(start_x)} {_fmt(start_y)})",  # Emit the upper-left corner.
        f"\t\t\t\t(end {_fmt(end_x)} {_fmt(end_y)})",  # Emit the lower-right corner.
        "\t\t\t\t(stroke",  # Open the stroke section.
        f"\t\t\t\t\t(width {_fmt(width)})",  # Emit the stroke width.
        "\t\t\t\t\t(type default)",  # Emit the default stroke type.
        "\t\t\t\t)",  # Close the stroke section.
        "\t\t\t\t(fill",  # Open the fill section.
        "\t\t\t\t\t(type background)",  # Fill the body rectangle like the LTspice source.
        "\t\t\t\t)",  # Close the fill section.
        "\t\t\t)",  # Close the rectangle block.
    ]  # Finish the rectangle block.


def _circle_lines(center_x: float, center_y: float, radius: float, width: float) -> List[str]:  # Assemble one KiCad circle block.
    return [  # Begin the circle block.
        "\t\t\t(circle",  # Open the circle record.
        f"\t\t\t\t(center {_fmt(center_x)} {_fmt(center_y)})",  # Emit the circle center.
        f"\t\t\t\t(radius {_fmt(radius)})",  # Emit the circle radius.
        "\t\t\t\t(stroke",  # Open the stroke section.
        f"\t\t\t\t\t(width {_fmt(width)})",  # Emit the stroke width.
        "\t\t\t\t\t(type default)",  # Emit the default stroke type.
        "\t\t\t\t)",  # Close the stroke section.
        "\t\t\t\t(fill",  # Open the fill section.
        "\t\t\t\t\t(type none)",  # Emit the unfilled style.
        "\t\t\t\t)",  # Close the fill section.
        "\t\t\t)",  # Close the circle block.
    ]  # Finish the circle block.


def _arc_lines(width: float, start_x: float, start_y: float, mid_x: float, mid_y: float, end_x: float, end_y: float) -> List[str]:  # Assemble one KiCad arc block.
    return [  # Begin the arc block.
        "\t\t\t(arc",  # Open the arc record.
        f"\t\t\t\t(start {_fmt(start_x)} {_fmt(start_y)})",  # Emit the arc start point.
        f"\t\t\t\t(mid {_fmt(mid_x)} {_fmt(mid_y)})",  # Emit the arc midpoint.
        f"\t\t\t\t(end {_fmt(end_x)} {_fmt(end_y)})",  # Emit the arc end point.
        "\t\t\t\t(stroke",  # Open the stroke section.
        f"\t\t\t\t\t(width {_fmt(width)})",  # Emit the stroke width.
        "\t\t\t\t\t(type default)",  # Emit the default stroke type.
        "\t\t\t\t)",  # Close the stroke section.
        "\t\t\t\t(fill",  # Open the fill section.
        "\t\t\t\t\t(type none)",  # Emit the unfilled style.
        "\t\t\t\t)",  # Close the fill section.
        "\t\t\t)",  # Close the arc block.
    ]  # Finish the arc block.
