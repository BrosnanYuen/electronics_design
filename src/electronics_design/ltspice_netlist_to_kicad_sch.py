"""LTspice netlist (`.net`) to KiCad schematic (`.kicad_sch`) conversion API."""  # Document the module purpose.

# The conversion rules implemented here reconstruct one KiCad schematic from
# one validated LTspice netlist. Component symbols are resolved from the KiCad
# symbol libraries under `convert_settings["kicad_path"]`; when a matching
# symbol does not exist there, the LTspice `.asy` fallback searches the
# configurable `custom_search_paths`, `ltspice_wine_path`, and
# `ltspice_windows_path` roots and converts the found symbol through the public
# `ltspice_asy_to_kicad_symbol` API. All pin geometry, pin names, simulation
# attributes, and library paths are looked up from the library files or the
# settings mapping; nothing is hard-coded. The generated schematic embeds every
# resolved symbol definition in its `lib_symbols` section so that the reverse
# `kicad_sch_to_ltspice_netlist` conversion resolves it without extra files.

from __future__ import annotations  # Postpone annotation evaluation for forward references.

import datetime  # Build the default schematic format version.
import math  # Compute pin lead stub geometry.
import os  # Resolve library search roots and write the output file.
import re  # Extract line numbers from validator messages.
import tempfile  # Create a scratch directory for ASY-fallback symbol conversions.
import uuid  # Generate deterministic schematic identifiers.
from typing import Any  # Type generic record payloads.
from typing import Dict  # Type property and pin mappings.
from typing import List  # Type collected line and record lists.
from typing import Mapping  # Type the convert_settings parameter.
from typing import Optional  # Type optional parse results.
from typing import Sequence  # Type immutable record sequences.
from typing import Set  # Type unique exit-lane collections.
from typing import Tuple  # Type tuple-based helper results.

from .force_directed_placement import ForceDirectedPlacer  # Place symbols with the ported kicad-tools physics model.
from .force_directed_placement import PlacementConfig  # Configure the placement physics parameters.
from .kicad_sch import is_valid_kicad_sch_file  # Validate the generated schematic file.
from .kicad_sch_to_ltspice_netlist import _collect_properties  # Reuse the shared property collector.
from .kicad_sch_to_ltspice_netlist import _extract_symbol_pins  # Reuse the shared pin-geometry extractor.
from .kicad_sch_to_ltspice_netlist import _LibraryCache  # Reuse the kicad_path library cache.
from .kicad_sch_to_ltspice_netlist import _pin_sort_key  # Reuse the shared pin-number sort key.
from .kicad_sch_to_ltspice_netlist import _ROLE_ORDER  # Reuse the shared SPICE role ordering.
from .kicad_sch_to_ltspice_netlist import _split_lib_id  # Reuse the shared library-identifier splitter.
from .kicad_sch_to_ltspice_netlist import _transform_point  # Reuse the shared pin-position transform.
from .kicad_sexp_parser import SExp  # Build schematic and symbol S-expression trees.
from .kicad_sexp_parser import parse_string  # Parse generated ASY-fallback symbol files.
from .ltspice_asy_to_kicad_symbol import ltspice_asy_to_kicad_symbol  # Convert missing symbols from LTspice ASY files.
from .ltspice_net import _parse_elements  # Reuse the shared netlist element parser.
from .ltspice_net import _read_text_file_lines  # Reuse the shared encoding-aware netlist reader.
from .ltspice_net import is_valid_ltspice_netlist_file  # Validate the input netlist file.
from .ltspice_net import ParsedElement  # Type parsed netlist elements.
from .schematic_grid_router import GridRouter  # Route net wires with the ported kicad-tools grid A*.

ConversionResult = Tuple[bool, str, int]  # Represent the public conversion return shape.
BuildResult = Tuple[bool, object, str, int]  # Represent internal build successes with payloads and failures with codes.

_GROUND_NODE_NAMES = frozenset({"0", "GND"})  # Treat these netlist node names as the global ground net.

_KICAD_SYMBOL_EXTENSION = ".kicad_sym"  # Recognize KiCad symbol library files by extension.
_ASY_EXTENSION = ".asy"  # Recognize LTspice symbol files by extension.

_LINE_SUFFIX_PATTERN = re.compile(r"Line (\d+)\s*$")  # Extract trailing line numbers from validator messages.

_KICAD_SCH_GRID = 1.27  # Default placement and routing grid in mm.
_KICAD_SCH_PAGE_WIDTH = 297.0  # Default A4 landscape page width in mm.
_KICAD_SCH_PAGE_HEIGHT = 210.0  # Default A4 landscape page height in mm.
_PLACEMENT_ITERATIONS = 250  # Default force-directed placement iteration budget.
_SYMBOL_BODY_PADDING = 1.27  # Extra body padding added around symbol graphics.
_PLACEMENT_START_X = 25.4  # Initial placement row starts at this X coordinate in mm.
_PLACEMENT_STEP_X = 25.4  # Initial placement row column spacing in mm.
_PLACEMENT_Y = 100.0  # Initial placement row Y coordinate in mm.
_PIN_EXIT_STEP_X = 1.27  # Candidate horizontal side-exit spacing for fallback trunk routing.
_POWER_STUB_LENGTH = 3.81  # Default stub length in mm for power-only nets.
_TRUNK_FALLBACK_GAP = 15.24  # Vertical gap below the page for fallback net trunks.

_PROPERTY_STEP = 2.54  # Vertical offset between stacked instance properties.

_UNSUPPORTED_PREFIXES = frozenset({"A", "@", "&"})  # Devices that cannot be represented by KiCad schematic symbols; K couplings carry no nodes and are skipped instead.

_PREFIX_ASY_FALLBACKS = {  # Map device prefixes onto candidate LTspice symbol file basenames.
    "R": ("res.asy",),  # Resistor symbol file.
    "C": ("cap.asy",),  # Capacitor symbol file.
    "L": ("ind.asy",),  # Inductor symbol file.
    "D": ("diode.asy",),  # Diode symbol file.
    "V": ("voltage.asy",),  # Voltage source symbol file.
    "I": ("current.asy",),  # Current source symbol file.
    "E": ("e.asy",),  # VCVS symbol file.
    "F": ("f.asy",),  # CCCS symbol file.
    "G": ("g.asy",),  # VCCS symbol file.
    "H": ("h.asy",),  # CCVS symbol file.
    "B": ("bv.asy", "bi.asy"),  # Behavioral source symbol files.
    "T": ("tline.asy",),  # Lossless transmission line symbol file.
    "S": ("sw.asy",),  # Voltage-controlled switch symbol file.
    "W": ("csw.asy",),  # Current-controlled switch symbol file.
    "O": ("ltline.asy",),  # Lossy transmission line symbol file.
    "Z": ("mesfet.asy",),  # MESFET symbol file.
}  # Finish the ASY fallback table.

# Quoted-string handling copied from the MIT-licensed kicad-tools project
# (`src/kicad_tools/sexp/parser.py`, Copyright (c) 2024 RJ Walters) so that the
# generated schematic uses KiCad's canonical bare-token spelling for keywords.
_UNQUOTED_KEYWORDS = frozenset({  # KiCad keywords that must serialize as bare tokens.
    "yes", "no", "true", "false",  # Boolean-like keywords.
    "hide", "show",  # Visibility keywords.
    "none", "outline", "background", "solid",  # Fill types.
    "default", "dash", "dash_dot", "dash_dot_dot", "dot",  # Stroke types.
    "left", "right", "center", "top", "bottom", "mirror", "front", "back",  # Justification and side keywords.
    "input", "output", "bidirectional", "tri_state", "passive", "free", "unspecified",  # Pin electrical types.
    "power_in", "power_out", "open_collector", "open_emitter", "no_connect",  # Pin electrical types.
    "line", "inverted", "clock", "inverted_clock", "input_low", "clock_low", "output_low", "edge_clock_high", "non_logic",  # Pin graphic shapes.
    "signal", "power", "user", "mixed", "jumper",  # Layer type keywords.
    "thru_hole", "smd", "connect", "np_thru_hole",  # Pad types.
    "rect", "oval", "circle", "roundrect", "trapezoid", "custom",  # Pad shapes.
    "top_left", "top_right", "bottom_left", "bottom_right",  # Pad chamfer corners.
    "reference", "value",  # Footprint text types.
    "thermal_reliefs", "full", "thru_hole_only",  # Zone connection types.
    "hatch", "hatched", "edge",  # Zone fill modes and hatch types.
    "blind", "micro", "through",  # Via types.
    "arc", "start", "mid", "end",  # Arc and curve keywords.
    "italic", "bold",  # Text effects.
    "through_hole", "virtual", "exclude_from_pos_files", "exclude_from_bom", "board_only", "dnp",  # Footprint attributes.
    "clearance", "trace_width", "via_dia", "via_drill", "uvia_dia", "uvia_drill",  # Net class keywords.
    "diff_pair_width", "diff_pair_gap", "diff_pair_template", "diff_pair", "positive", "negative",  # Differential pair keywords.
    "global", "local",  # Power symbol scope keywords.
    "symbols",  # Symbol library section keyword.
    "x", "y", "xy",  # Mirror and axis values.
    "allowed", "not_allowed",  # Keepout disposition keywords.
    "allow_missing_courtyard", "allow_soldermask_bridges",  # Other bare keywords.
})  # Finish the bare-token keyword set.


def ltspice_netlist_to_kicad_sch(  # Convert one LTspice netlist into one KiCad schematic file.
    ltspice_netlist_filepath: str,  # Accept the LTspice netlist input path.
    kicad_sch_filepath_out: str,  # Accept the KiCad schematic output path.
    convert_settings: Mapping,  # Accept the conversion configuration mapping.
) -> ConversionResult:  # Return the shared conversion result tuple.
    """Convert one LTspice ``.net`` netlist into one KiCad ``.kicad_sch`` schematic.

    Every device resolves to a symbol from the KiCad symbol libraries under
    ``convert_settings["kicad_path"]``. When no library symbol matches, the
    device's LTspice ``.asy`` file is searched under the configured
    ``custom_search_paths``, ``ltspice_wine_path``, and ``ltspice_windows_path``
    roots and converted with :func:`ltspice_asy_to_kicad_symbol`. Independent
    voltage sources whose negative node is ground become KiCad power symbols;
    the global ground net receives a ``GND`` power symbol. Wires are routed
    orthogonally along per-net trunks so the schematic physically connects
    every pin of every net.

    Returns ``(True, "OK", 0)`` on success or ``(False, "<error code>", <line>)``
    on failure.
    """
    settings_result = _normalize_convert_settings(convert_settings)  # Validate the conversion settings first.
    if not settings_result[0]:  # Stop when the settings are unusable.
        return False, "INVALID_CONVERT_SETTINGS", 0  # Return the required settings error code.
    settings = settings_result[1]  # Read the normalized settings dictionary.
    output_result = _coerce_output_path(kicad_sch_filepath_out)  # Coerce the output path safely.
    if not output_result[0]:  # Stop when the output path is not path-like.
        return False, "INVALID_OUTPUT_PATH", 0  # Return the required output path error code.
    output_path = output_result[1]  # Read the coerced output path string.
    input_result = _coerce_input_path(ltspice_netlist_filepath)  # Coerce and check the input path.
    if not input_result[0]:  # Stop when the input path is unusable.
        return False, "INVALID_NETLIST_FILE", 0  # Return the required netlist file error code.
    input_path = input_result[1]  # Read the coerced input path string.
    validation_result = is_valid_ltspice_netlist_file(input_path)  # Validate the netlist before conversion.
    if not validation_result[0]:  # Stop when the netlist fails validation.
        return False, "INVALID_NETLIST_FILE", _line_from_message(validation_result[1])  # Return the failing line.
    read_result = _read_text_file_lines(input_path)  # Read the netlist text with encoding detection.
    if not read_result[0]:  # Stop when the netlist cannot be read.
        return False, "NETLIST_READ_ERROR", 0  # Return the required read error code.
    build_result = _build_schematic_text(read_result[1], input_path, settings)  # Build the KiCad schematic text.
    if not build_result[0]:  # Stop when the conversion logic reports a failure.
        return False, build_result[2], build_result[3]  # Return the conversion error code and line.
    schematic_text = build_result[1]  # Read the generated schematic text.
    write_result = _write_text_file(output_path, schematic_text)  # Write the generated schematic file.
    if not write_result[0]:  # Stop when the output cannot be written.
        return False, "WRITE_ERROR", 0  # Return the required write error code.
    generated_result = is_valid_kicad_sch_file(output_path)  # Validate the freshly written schematic.
    if not generated_result[0]:  # Stop when the generated schematic fails validation.
        return False, "INVALID_GENERATED_KICAD_SCH", _line_from_message(generated_result[1])  # Return the output line.
    return True, "OK", 0  # Return success when the conversion completed.


def _build_schematic_text(lines: Sequence[str], input_path: str, settings: Dict[str, Any]) -> BuildResult:  # Build the full KiCad schematic text from netlist lines.
    elements_result = _parse_elements(lines)  # Parse the validated netlist into device elements.
    if not elements_result[0]:  # Stop when element parsing fails unexpectedly.
        return False, "", "INVALID_NETLIST_FILE", elements_result[2]  # Return the failing line.
    elements = elements_result[1]  # Read the parsed element records.
    model_types = _build_model_types(lines, settings)  # Parse netlist and library .model lines into polarity mappings.
    temp_directory = tempfile.mkdtemp(prefix="electronics_design_netlist_kicad_")  # Create a scratch directory for ASY fallback conversions.
    try:  # Run the conversion stages inside the scratch directory lifetime.
        records_result = _build_component_records(elements, model_types, settings, temp_directory)  # Resolve symbols and build component records.
        if not records_result[0]:  # Stop when symbol resolution reports a failure.
            return records_result  # Return the resolution error unchanged.
        records, embedded_symbols = records_result[1]  # Read the resolved component records and embedded symbols.
        routing_result = _route_and_build(root_uuid=_root_uuid(input_path), records=records, settings=settings)  # Route nets and assemble the schematic nodes.
        if not routing_result[0]:  # Stop when routing reports a failure.
            return routing_result  # Return the routing error unchanged.
        schematic_nodes = routing_result[1]  # Read the assembled schematic body nodes.
        text = _assemble_schematic(input_path, settings, embedded_symbols, schematic_nodes)  # Assemble the final schematic text.
        return True, text, "", 0  # Return the generated schematic text.
    finally:  # Always clean up the scratch directory.
        try:  # Attempt the recursive cleanup.
            for entry in os.listdir(temp_directory):  # Walk the scratch entries.
                os.remove(os.path.join(temp_directory, entry))  # Remove each generated scratch file.
            os.rmdir(temp_directory)  # Remove the now-empty scratch directory.
        except OSError:  # Ignore cleanup failures for already-embedded fallback symbols.
            pass  # Continue because the schematic already embeds the converted symbols.


_LIBRARY_DIRECTIVE_PATTERN = re.compile(r"^\.(?:include|lib|inc)\b", re.IGNORECASE)  # Detect library reference directives.

_MODEL_DIRECTIVE_PATTERN = re.compile(r"^\.model\b", re.IGNORECASE)  # Detect .model definition lines in library files.

_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")  # Recognize UTF-16 byte order marks when reading library files.
_UTF8_BOM = b"\xef\xbb\xbf"  # Recognize the UTF-8 byte order mark.


def _parse_model_types(lines: Sequence[str]) -> Dict[str, str]:  # Parse inline .model lines into model-name to polarity-type mappings.
    model_types: Dict[str, str] = {}  # Collect the model type mappings.
    for raw_line in lines:  # Walk every netlist line.
        stripped_line = raw_line.strip()  # Normalize leading whitespace.
        if not _MODEL_DIRECTIVE_PATTERN.match(stripped_line):  # Skip lines that are not model definitions.
            continue  # Move to the next line.
        tokens = stripped_line.split()  # Split the model line into tokens.
        if len(tokens) < 3:  # Skip malformed model lines defensively.
            continue  # Move to the next line.
        model_types[tokens[1]] = _model_polarity_type(stripped_line, tokens[2])  # Record the polarity type under the model name.
    return model_types  # Return the collected model type mapping.


def _model_polarity_type(raw_line: str, kind_token: str) -> str:  # Normalize one .model kind token into a polarity type.
    kind = kind_token.split("(")[0].upper()  # Strip the parameter section from the kind token.
    if kind == "VDMOS":  # VDMOS polarity depends on the Pchan parameter instead of the model kind.
        return "PMOS" if re.search(r"\bpchan\b", raw_line, re.IGNORECASE) is not None else "NMOS"  # Return the VDMOS polarity type.
    return kind  # Return the kind as the polarity type.


def _ltspice_search_roots(settings: Dict[str, Any]) -> List[str]:  # Collect the configured LTspice symbol search roots.
    search_roots: List[str] = []  # Collect the search roots.
    custom_paths = settings.get("custom_search_paths")  # Read the optional custom search paths.
    if isinstance(custom_paths, (list, tuple)):  # Accept list-style custom paths.
        for custom_path in custom_paths:  # Walk every custom search path.
            if isinstance(custom_path, str) and custom_path.strip():  # Keep nonempty path strings.
                search_roots.append(os.path.expanduser(custom_path.strip()))  # Expand and store the custom root.
    for setting_key in ("ltspice_wine_path", "ltspice_windows_path"):  # Walk the LTspice install root settings.
        raw_path = settings.get(setting_key)  # Read the configured install root.
        if isinstance(raw_path, str) and raw_path.strip():  # Keep nonempty path strings.
            normalized_path = os.path.expanduser(raw_path.strip().replace("\\", "/"))  # Normalize separators and expand the root.
            search_roots.append(normalized_path)  # Store the install root.
    return search_roots  # Return the collected search roots.


def _find_library_file(library_name: str, search_roots: Sequence[str]) -> Optional[str]:  # Locate one referenced library file under the configured roots.
    normalized = os.path.expanduser(library_name.strip()).replace("\\", "/")  # Normalize the referenced path.
    if os.path.isfile(normalized):  # Accept a directly usable path first.
        return normalized  # Return the direct path.
    basename = os.path.basename(normalized)  # Extract the library basename for root-based lookup.
    relative = normalized.lstrip("./")  # Drop a relative path prefix for root-based lookup.
    for search_root in search_roots:  # Walk every search root.
        candidates = [  # Build the candidate paths for this root.
            os.path.join(search_root, relative),  # The referenced relative path below the root.
            os.path.join(search_root, basename),  # The root itself may hold the library file.
            os.path.join(search_root, "lib", basename),  # The conventional library subdirectory.
            os.path.join(search_root, "lib", "cmp", basename),  # The standard component library layout.
            os.path.join(search_root, "lib", "sub", basename),  # The standard subcircuit library layout.
        ]  # Finish the candidate path list.
        for candidate in candidates:  # Walk the candidate paths.
            if os.path.isfile(candidate):  # Stop at the first existing file.
                return candidate  # Return the resolved library path.
    return None  # Return None when no root contains the library file.


def _read_encoded_text_file(filepath: str) -> Tuple[bool, str]:  # Read one LTspice library file with encoding detection.
    try:  # Attempt to read the raw file bytes.
        with open(filepath, "rb") as file_handle:  # Open the file in binary mode for BOM inspection.
            raw_bytes = file_handle.read()  # Read the entire file as bytes.
    except OSError:  # Catch unreadable files.
        return False, ""  # Signal the read failure.
    if raw_bytes.startswith(_UTF16_BOMS):  # Prefer UTF-16 when a byte order mark is present.
        encodings = ("utf-16",)  # Use the BOM-aware UTF-16 codec.
    elif raw_bytes.startswith(_UTF8_BOM):  # Prefer BOM-aware UTF-8 when marked.
        encodings = ("utf-8-sig", "utf-8", "latin-1")  # Fall back through simpler encodings.
    elif b"\x00" in raw_bytes[:4096]:  # Detect BOM-less UTF-16 through interleaved null bytes.
        encodings = ("utf-16", "utf-8", "latin-1")  # Try UTF-16 first for null-byte content.
    else:  # Default to plain text encodings.
        encodings = ("utf-8", "latin-1")  # Try UTF-8 with a Latin-1 fallback.
    for encoding in encodings:  # Walk the candidate encodings.
        try:  # Attempt to decode the raw bytes.
            return True, raw_bytes.decode(encoding)  # Return the decoded text.
        except UnicodeDecodeError:  # Skip encodings that cannot decode the content.
            continue  # Move to the next encoding.
    return False, ""  # Signal that no encoding could decode the file.


def _collect_library_model_types(lines: Sequence[str], settings: Dict[str, Any]) -> Dict[str, str]:  # Parse model polarities from referenced library files.
    library_names: List[str] = []  # Collect the referenced library filenames.
    for raw_line in lines:  # Walk every netlist line.
        stripped_line = raw_line.strip()  # Normalize leading whitespace.
        if not _LIBRARY_DIRECTIVE_PATTERN.match(stripped_line):  # Skip lines that do not reference a library.
            continue  # Move to the next line.
        tokens = stripped_line.split()  # Split the library line into tokens.
        if len(tokens) < 2:  # Skip malformed library lines defensively.
            continue  # Move to the next line.
        reference = tokens[1].strip().strip("\"'")  # Read the filename token without surrounding quotes.
        if reference:  # Keep nonempty references.
            library_names.append(reference)  # Store the referenced filename.
    model_types: Dict[str, str] = {}  # Collect the library model mappings.
    search_roots = _ltspice_search_roots(settings)  # Collect the configured search roots once.
    for library_name in library_names:  # Walk every referenced library.
        library_path = _find_library_file(library_name, search_roots)  # Locate the library file.
        if library_path is None:  # Skip references that cannot be located.
            continue  # Move to the next reference.
        read_result = _read_encoded_text_file(library_path)  # Read the library text with encoding detection.
        if not read_result[0]:  # Skip unreadable libraries.
            continue  # Move to the next reference.
        for raw_line in read_result[1].splitlines():  # Walk every library line.
            stripped_line = raw_line.strip()  # Normalize leading whitespace.
            if not _MODEL_DIRECTIVE_PATTERN.match(stripped_line):  # Skip non-model lines.
                continue  # Move to the next line.
            tokens = stripped_line.split()  # Split the model line into tokens.
            if len(tokens) < 3:  # Skip malformed model lines defensively.
                continue  # Move to the next line.
            model_types[tokens[1]] = _model_polarity_type(stripped_line, tokens[2])  # Record the polarity type under the model name.
    return model_types  # Return the collected library model mapping.


def _build_model_types(lines: Sequence[str], settings: Dict[str, Any]) -> Dict[str, str]:  # Merge library and inline model types.
    model_types = _collect_library_model_types(lines, settings)  # Start with the referenced library model types.
    model_types.update(_parse_model_types(lines))  # Inline netlist .model definitions override the libraries.
    return model_types  # Return the merged model type mapping.


def _candidate_lib_ids(element: ParsedElement, model_types: Dict[str, str]) -> List[str]:  # Derive candidate KiCad library identifiers for one device.
    prefix = element.prefix  # Read the device prefix.
    payload = element.tokens[1 + len(element.nodes):]  # Read the value/model payload tokens.
    payload_text = payload[0] if payload else ""  # Read the primary model or value token.
    if prefix == "R":  # Resistors map to the standard Device library resistor.
        return ["Device:R"]  # Return the resistor candidate.
    if prefix == "C":  # Capacitors map to the standard Device library capacitor.
        return ["Device:C"]  # Return the capacitor candidate.
    if prefix == "L":  # Inductors map to the standard Device library inductor.
        return ["Device:L"]  # Return the inductor candidate.
    if prefix == "D":  # Diodes prefer a model-named library symbol before generic fallbacks.
        candidates: List[str] = []  # Collect diode candidates.
        if payload_text and payload_text.upper() not in {"D", "DIODE"}:  # Only propose a model-named symbol for real model names.
            candidates.append(f"Diode:{payload_text}")  # Prefer the model-named diode symbol.
        candidates.extend(["Simulation_SPICE:D", "Device:D"])  # Append the generic diode symbols.
        return candidates  # Return the diode candidates.
    if prefix == "Q":  # BJTs prefer a model-named symbol followed by the polarity-matched simulation symbol.
        model_type = model_types.get(payload_text, payload_text).upper()  # Resolve the model type from the netlist and library .model lines.
        candidates = []  # Collect BJT candidates.
        if payload_text and model_type not in {"NPN", "PNP"}:  # Propose a model-named transistor symbol when it differs from the class name.
            candidates.append(f"Transistor_BJT:{payload_text}")  # Append the model-named transistor symbol.
        polarity = "PNP" if model_type == "PNP" else "NPN"  # Resolve the BJT polarity class.
        if len(element.nodes) == 4:  # Preserve an explicit substrate node with the four-pin simulation symbol.
            polarity += "_Substrate"  # Use the substrate variant of the simulation symbol.
        candidates.append(f"Simulation_SPICE:{polarity}")  # Always propose the polarity-matched simulation symbol.
        return candidates  # Return the BJT candidates.
    if prefix == "M":  # MOSFETs prefer a model-named symbol followed by the polarity-matched simulation symbol.
        model_type = model_types.get(payload_text, payload_text).upper()  # Resolve the model type from the netlist and library .model lines.
        candidates = []  # Collect MOSFET candidates.
        if payload_text and model_type not in {"NMOS", "PMOS"}:  # Propose a model-named FET symbol when it differs from the class name.
            candidates.append(f"Transistor_FET:{payload_text}")  # Append the model-named FET symbol.
        polarity = "PMOS" if model_type == "PMOS" else "NMOS"  # Resolve the MOSFET polarity class.
        if len(element.nodes) == 4:  # Preserve an explicit substrate node with the four-pin simulation symbol.
            polarity += "_Substrate"  # Use the substrate variant of the simulation symbol.
        candidates.append(f"Simulation_SPICE:{polarity}")  # Always propose the polarity-matched simulation symbol.
        return candidates  # Return the MOSFET candidates.
    if prefix == "J":  # JFETs map to the polarity-matched simulation symbol.
        model_type = model_types.get(payload_text, payload_text).upper()  # Resolve the model type from the netlist and library .model lines.
        return [f"Simulation_SPICE:{'PJFET' if model_type == 'PJF' else 'NJFET'}"]  # Return the polarity-matched simulation symbol candidate.
    if prefix == "V":  # Voltage sources prefer power symbols named after their positive node when ground-referenced.
        positive_node = element.nodes[0] if element.nodes else ""  # Read the source positive node.
        negative_node = element.nodes[1] if len(element.nodes) > 1 else ""  # Read the source negative node.
        if negative_node not in _GROUND_NODE_NAMES or positive_node in _GROUND_NODE_NAMES:  # Use a two-pin source for floating or inverted supplies.
            return ["Simulation_SPICE:VDC"]  # Return the two-pin simulation voltage source.
        if payload_text == "0":  # A zero-volt source is a sensing source, not a supply; keep it as a two-pin device.
            return ["Simulation_SPICE:VDC"]  # Return the two-pin simulation voltage source.
        candidates = []  # Collect voltage source candidates.
        candidates.append(f"power:{positive_node}")  # Prefer a power symbol named after the node.
        candidates.append("power:VCC")  # Append the generic supply power symbol.
        candidates.append("Simulation_SPICE:VDC")  # Append the two-pin simulation voltage source as a fallback.
        return candidates  # Return the voltage source candidates.
    if prefix == "I":  # Current sources map to the standard simulation current source.
        return ["Simulation_SPICE:IDC"]  # Return the current source candidate.
    if prefix == "X":  # Subcircuit calls prefer a symbol named after the subcircuit name.
        return [payload_text]  # Return the bare subcircuit name for library-wide scanning.
    if prefix == "E":  # VCVS devices map to the simulation controlled source.
        return ["Simulation_SPICE:ESOURCE"]  # Return the VCVS candidate.
    if prefix == "F":  # CCCS devices have no standard simulation symbol; rely on the ASY fallback.
        return []  # Return no library candidates.
    if prefix == "G":  # VCCS devices map to the simulation controlled source.
        return ["Simulation_SPICE:GSOURCE"]  # Return the VCCS candidate.
    if prefix == "H":  # CCVS devices have no standard simulation symbol; rely on the ASY fallback.
        return []  # Return no library candidates.
    if prefix == "B":  # Behavioral sources map to the simulation behavioral source.
        return ["Simulation_SPICE:BSOURCE"]  # Return the behavioral source candidate.
    if prefix == "T":  # Lossless transmission lines map to the simulation transmission line.
        return ["Simulation_SPICE:TLINE"]  # Return the transmission line candidate.
    if prefix == "S":  # Voltage-controlled switches map to the simulation switch.
        return ["Simulation_SPICE:SWITCH"]  # Return the switch candidate.
    return []  # Return no candidates for prefixes covered only by the ASY fallback.


def _resolve_symbol(  # Resolve one device to a KiCad symbol from kicad_path or the LTspice ASY fallback.
    library_cache: _LibraryCache,  # Accept the prepared kicad_path library cache.
    lib_ids: Sequence[str],  # Accept the candidate library identifiers in preference order.
    element: ParsedElement,  # Accept the device element for fallback naming.
    settings: Dict[str, Any],  # Accept the normalized settings.
    temp_directory: str,  # Accept the scratch directory for fallback conversions.
    extra_asy_names: Sequence[str] = (),  # Accept polarity-derived ASY fallback names.
) -> BuildResult:  # Return the resolution success with the lib_id and symbol node.
    bare_lib_ids: List[str] = []  # Defer expensive library-wide searches until configured ASY fallbacks have been tried.
    for lib_id in lib_ids:  # Walk the candidate library identifiers in order.
        if lib_id == "":  # Skip empty candidates.
            continue  # Move to the next candidate.
        if ":" not in lib_id:  # Bare symbol names require scanning every KiCad library.
            bare_lib_ids.append(lib_id)  # Save the candidate as a last-resort library lookup.
            continue  # Prefer the explicitly configured LTspice symbol roots first.
        symbol_node = library_cache.find(lib_id)  # Search the kicad_path libraries.
        if symbol_node is None:  # Skip candidates that no library defines.
            continue  # Move to the next candidate.
        short_name = _split_lib_id(lib_id)[1]  # Read the short symbol name for pin extraction.
        pins_result = _extract_symbol_pins(symbol_node, 1, 1, short_name)  # Check that the symbol carries usable pin graphics.
        if pins_result[0]:  # Require usable pin graphics before accepting the candidate.
            if symbol_node.find_child("power") is not None or len(pins_result[1]) == len(element.nodes):  # Power symbols carry one pin regardless of node count; others must match exactly.
                return True, (lib_id, symbol_node), "", 0  # Return the resolved symbol.
    asy_names = list(_PREFIX_ASY_FALLBACKS.get(element.prefix, ()))  # Read the prefix ASY fallback names.
    if element.prefix == "X":  # Subcircuit fallbacks use the subcircuit name as the ASY basename.
        payload = element.tokens[1 + len(element.nodes):]  # Read the payload tokens after the connectivity nodes.
        subcircuit_name = payload[0] if payload else ""  # Read the first payload token as the subcircuit name.
        if subcircuit_name:  # Only propose a fallback when a name exists.
            asy_names = [subcircuit_name + _ASY_EXTENSION]  # Build the subcircuit ASY filename.
    asy_names.extend(extra_asy_names)  # Append polarity-derived fallback names after the prefix defaults.
    for asy_name in asy_names:  # Walk the candidate ASY basenames.
        asy_path = _find_asy_file(asy_name, settings)  # Search the configured LTspice roots for the file.
        if asy_path is None:  # Skip names that do not exist anywhere.
            continue  # Move to the next ASY name.
        stem = os.path.splitext(asy_name)[0]  # Derive the symbol stem from the ASY basename.
        fallback_path = os.path.join(temp_directory, stem + _KICAD_SYMBOL_EXTENSION)  # Build the scratch symbol path.
        conversion_result = ltspice_asy_to_kicad_symbol(asy_path, fallback_path, settings)  # Convert the ASY file through the public API.
        if not conversion_result[0]:  # Skip symbols that fail the ASY conversion.
            continue  # Move to the next ASY name.
        try:  # Attempt to read the generated symbol file.
            with open(fallback_path, "r", encoding="utf-8") as file_handle:  # Open the generated symbol text.
                fallback_root = parse_string(file_handle.read())  # Parse the generated symbol library.
        except OSError:  # Treat unreadable generated files as a failed fallback.
            continue  # Move to the next ASY name.
        symbol_node = None  # Initialize the extracted symbol node.
        for candidate_node in fallback_root.find_children("symbol"):  # Walk the top-level symbol definitions.
            candidate_values = [child.value for child in candidate_node.children if child.is_atom]  # Collect the name atoms.
            if candidate_values and str(candidate_values[0]) == stem:  # Match the expected stem name.
                symbol_node = candidate_node  # Select the matching symbol node.
                break  # Stop searching.
        if symbol_node is None:  # Skip generated files without the expected symbol.
            continue  # Move to the next ASY name.
        fallback_pins_result = _extract_symbol_pins(symbol_node, 1, 1, stem)  # Check the generated symbol pin graphics.
        if not fallback_pins_result[0] or len(fallback_pins_result[1]) != len(element.nodes):  # Require a pin-count match before embedding.
            continue  # Move to the next ASY name.
        embedded_lib_id = f"{stem}:{stem}"  # Qualify the embedded symbol so kicad_path never shadows it.
        return True, (embedded_lib_id, symbol_node), "", 0  # Return the embedded fallback symbol.
    for lib_id in bare_lib_ids:  # Fall back to a library-wide search only when no configured ASY resolves the bare name.
        symbol_node = library_cache.find(lib_id)  # Search all KiCad symbol libraries for the bare symbol name.
        if symbol_node is None:  # Skip names that no library defines.
            continue  # Move to the next bare candidate.
        short_name = _split_lib_id(lib_id)[1]  # Read the short symbol name for pin extraction.
        pins_result = _extract_symbol_pins(symbol_node, 1, 1, short_name)  # Validate the candidate pin graphics.
        if pins_result[0] and len(pins_result[1]) == len(element.nodes):  # Require usable geometry and an exact pin-count match.
            return True, (lib_id, symbol_node), "", 0  # Return the library-wide resolution.
    detail = "', '".join(lib_ids)  # Join the candidate identifiers for the error message.
    message = f"UNKNOWN_SYMBOL: Unable to resolve a KiCad symbol for device '{element.tokens[0]}' in kicad_path candidates ['{detail}'] or the configured LTspice ASY search paths"  # Explain the failed resolution.
    return False, None, message, element.line_number  # Return the unknown symbol error with the element line.


def _polarity_asy_fallback_names(element: ParsedElement, model_types: Dict[str, str]) -> Tuple[str, ...]:  # Derive polarity-matched ASY fallback names for transistor devices.
    prefix = element.prefix  # Read the device prefix.
    if prefix not in {"Q", "M", "J"}:  # Only transistors carry polarity-dependent fallback symbols.
        return ()  # Return no extra fallback names.
    payload = element.tokens[1 + len(element.nodes):]  # Read the payload tokens after the nodes.
    payload_text = payload[0] if payload else ""  # Read the primary model token.
    model_type = model_types.get(payload_text, payload_text).upper()  # Resolve the polarity type.
    if prefix == "Q":  # BJTs fall back to the matching LTspice NPN or PNP symbol.
        return ("pnp.asy",) if model_type == "PNP" else ("npn.asy",)  # Return the polarity-matched BJT fallback.
    if prefix == "M":  # MOSFETs fall back to the matching LTspice NMOS or PMOS symbol.
        return ("pmos.asy",) if model_type == "PMOS" else ("nmos.asy",)  # Return the polarity-matched MOSFET fallback.
    return ("pjf.asy",) if model_type == "PJF" else ("njf.asy",)  # Return the polarity-matched JFET fallback.


def _find_asy_file(asy_name: str, settings: Dict[str, Any]) -> Optional[str]:  # Search the configured LTspice roots for one ASY file.
    search_roots = _ltspice_search_roots(settings)  # Collect the configured LTspice search roots.
    for search_root in search_roots:  # Walk every search root.
        candidates = [  # Build the candidate paths for this root.
            os.path.join(search_root, asy_name),  # The root itself may hold the symbol.
            os.path.join(search_root, "sym", asy_name),  # The conventional sym subdirectory.
            os.path.join(search_root, "lib", "sym", asy_name),  # The conventional LTspice library layout.
        ]  # Finish the candidate path list.
        for candidate in candidates:  # Walk the candidate paths.
            if os.path.isfile(candidate):  # Stop at the first existing file.
                return candidate  # Return the resolved ASY path.
    return None  # Return None when no root contains the ASY file.


def _build_component_records(  # Resolve symbols and build one component record per device element.
    elements: Sequence[ParsedElement],  # Accept the parsed netlist elements.
    model_types: Dict[str, str],  # Accept the parsed model type mapping.
    settings: Dict[str, Any],  # Accept the normalized settings.
    temp_directory: str,  # Accept the scratch directory for ASY fallbacks.
) -> BuildResult:  # Return the component records and embedded symbol definitions.
    library_cache = _LibraryCache(settings["kicad_path"])  # Prepare the kicad_path library cache.
    records: List[Dict[str, Any]] = []  # Collect the resolved component records.
    embedded_symbols: Dict[str, SExp] = {}  # Collect embedded symbol definitions keyed by lib_id.
    resolved_symbols: Dict[Tuple[Tuple[str, ...], Tuple[str, ...], str, int], Tuple[str, SExp]] = {}  # Reuse symbol resolution for repeated device shapes.
    for element in elements:  # Walk every parsed device element.
        prefix = element.prefix  # Read the device prefix.
        if prefix in _UNSUPPORTED_PREFIXES:  # Reject devices with no KiCad schematic representation.
            message = f"UNSUPPORTED_DEVICE: LTspice device prefix '{prefix}' has no KiCad schematic symbol representation"  # Explain the unsupported prefix.
            return False, None, message, element.line_number  # Return the unsupported device error with the element line.
        if not element.nodes:  # Skip node-free statements such as K mutual-inductance couplings.
            continue  # Move to the next element because these statements contribute no schematic connectivity.
        candidate_ids = _candidate_lib_ids(element, model_types)  # Derive the candidate library identifiers.
        extra_asy_names = _polarity_asy_fallback_names(element, model_types)  # Derive polarity-matched ASY fallback names.
        resolution_key = (tuple(candidate_ids), tuple(extra_asy_names), prefix, len(element.nodes))  # Key resolution by all shape-affecting inputs.
        cached_symbol = resolved_symbols.get(resolution_key)  # Reuse an earlier identical resolution.
        if cached_symbol is None:  # Resolve this device shape on first use.
            resolve_result = _resolve_symbol(library_cache, candidate_ids, element, settings, temp_directory, extra_asy_names)  # Resolve the device symbol.
            if not resolve_result[0]:  # Stop when resolution fails.
                return resolve_result  # Return the resolution error unchanged.
            lib_id, symbol_node = resolve_result[1]  # Read the resolved lib_id and symbol node.
            resolved_symbols[resolution_key] = (lib_id, symbol_node)  # Cache the successful shape resolution.
        else:  # Reuse the cached symbol definition.
            lib_id, symbol_node = cached_symbol  # Unpack the resolved library id and node.
        record_result = _build_one_record(element, lib_id, symbol_node)  # Build the component record.
        if not record_result[0]:  # Stop when the record build reports a failure.
            return record_result  # Return the record error unchanged.
        records.append(record_result[1])  # Append the finished component record.
        embedded_symbols.setdefault(lib_id, symbol_node)  # Cache the symbol definition for embedding.
    return True, (records, embedded_symbols), "", 0  # Return the resolved records and embedded symbols.


def _build_one_record(  # Build one component record from a resolved device and symbol.
    element: ParsedElement,  # Accept the parsed device element.
    lib_id: str,  # Accept the resolved library identifier.
    symbol_node: SExp,  # Accept the resolved symbol definition node.
) -> BuildResult:  # Return the built record or a failure.
    short_name = _split_lib_id(lib_id)[1]  # Read the short symbol name for sub-symbol lookup.
    symbol_props = _collect_properties(symbol_node)  # Collect the library symbol properties.
    pins_result = _extract_symbol_pins(symbol_node, 1, 1, short_name)  # Extract the symbol pin geometry.
    if not pins_result[0]:  # Stop when the symbol carries no usable pins.
        message = f"UNKNOWN_SYMBOL: symbol '{lib_id}' has no pin definitions for unit 1"  # Explain the missing pin graphics.
        return False, None, message, element.line_number  # Return the unknown symbol error with the element line.
    pins = pins_result[1]  # Read the pin geometry mapping.
    pin_map = _build_pin_map(symbol_props, pins, element.nodes)  # Map netlist nodes onto pin numbers.
    prefix = element.prefix  # Read the device prefix.
    payload = element.tokens[1 + len(element.nodes):]  # Read the payload tokens after the nodes.
    power = symbol_node.find_child("power") is not None  # Detect power symbols from the library definition.
    if prefix == "V" and power:  # Handle ground-referenced voltage sources as power symbols.
        if len(element.nodes) < 2:  # Require two source nodes.
            message = f"UNSUPPORTED_DEVICE: voltage source '{element.tokens[0]}' lacks both nodes"  # Explain the missing nodes.
            return False, None, message, element.line_number  # Return the unsupported device error.
        if element.nodes[1] not in _GROUND_NODE_NAMES:  # A power symbol can only represent a ground-referenced source.
            message = f"UNSUPPORTED_DEVICE: voltage source '{element.tokens[0]}' has a floating negative node '{element.nodes[1]}'; use a ground-referenced source"  # Explain the floating supply limitation.
            return False, None, message, element.line_number  # Return the unsupported device error.
        value = " ".join(payload)  # Join the source payload tokens into one value string.
        reference = "#" + element.tokens[0]  # Power references carry the hash prefix for the reverse conversion.
        record: Dict[str, Any] = {  # Assemble the voltage source record.
            "element": element,  # Store the parsed element.
            "prefix": prefix,  # Store the device prefix.
            "reference": reference,  # Store the schematic reference designator.
            "value": value,  # Store the value payload.
            "lib_id": lib_id,  # Store the resolved library identifier.
            "symbol_props": symbol_props,  # Store the library symbol properties.
            "pins": pins,  # Store the pin geometry.
            "pin_map": pin_map,  # Store the node-to-pin mapping.
            "power": True,  # Mark the record as a power symbol.
            "symbol_node": symbol_node,  # Store the resolved symbol node for body geometry.
            "x": 0.0,  # Initialize the placement X (set during routing).
            "y": 0.0,  # Initialize the placement Y (set during routing).
            "angle": 0.0,  # Initialize the placement angle.
        }  # Finish the voltage source record.
        return True, record, "", 0  # Return the built record.
    if power:  # Reject non-voltage power symbols because they cannot round-trip as sources.
        message = f"UNSUPPORTED_DEVICE: power symbol '{lib_id}' cannot represent device '{element.tokens[0]}'"  # Explain the power mismatch.
        return False, None, message, element.line_number  # Return the unsupported device error.
    if not payload:  # Require a value or model payload on ordinary components.
        message = f"MISSING_COMPONENT_PAYLOAD: device '{element.tokens[0]}' has no value or model payload"  # Explain the missing payload.
        return False, None, message, element.line_number  # Return the payload error.
    value = " ".join(payload)  # Preserve the full value payload so the reverse conversion restores it token for token.
    reference = element.tokens[0]  # Start with the netlist instance name.
    if prefix == "X":  # Map subcircuit references onto KiCad U references.
        if reference.startswith("X") and len(reference) > 1 and reference[1:2].isdigit():  # Strip the leading X for digit-suffixed names.
            reference = "U" + reference[1:]  # Rebuild the reference with the U prefix.
        else:  # Keep nonstandard subcircuit names intact.
            reference = reference[1:]  # Strip only the leading X.
        reference = reference.lstrip("\u00a7")  # Drop LTspice hierarchy path markers so the reverse conversion reads a valid prefix.
    record = {  # Assemble the ordinary component record.
        "element": element,  # Store the parsed element.
        "prefix": prefix,  # Store the device prefix.
        "reference": reference,  # Store the schematic reference designator.
        "value": value,  # Store the value payload.
        "lib_id": lib_id,  # Store the resolved library identifier.
        "symbol_props": symbol_props,  # Store the library symbol properties.
        "pins": pins,  # Store the pin geometry.
        "pin_map": pin_map,  # Store the node-to-pin mapping.
        "power": False,  # Mark the record as an ordinary component.
        "symbol_node": symbol_node,  # Store the resolved symbol node for body geometry.
        "x": 0.0,  # Initialize the placement X.
        "y": 0.0,  # Initialize the placement Y.
        "angle": 0.0,  # Initialize the placement angle.
    }  # Finish the ordinary component record.
    return True, record, "", 0  # Return the built record.


def _build_pin_map(  # Map netlist node positions onto symbol pin numbers.
    symbol_props: Dict[str, str],  # Accept the library symbol properties.
    pins: Dict[str, Tuple[float, float, str]],  # Accept the pin geometry mapping.
    nodes: Sequence[str],  # Accept the netlist node tokens in SPICE order.
) -> Dict[int, str]:  # Return the node-index to pin-number mapping.
    sim_device = symbol_props.get("Sim.Device", "").upper()  # Read the simulation device class.
    sim_pins_text = symbol_props.get("Sim.Pins", "")  # Read the Sim.Pins role mapping.
    role_map: Dict[str, str] = {}  # Map SPICE roles onto pin numbers.
    declaration_order: List[str] = []  # Preserve the role declaration order.
    for token in sim_pins_text.split():  # Walk the space-separated Sim.Pins tokens.
        if "=" not in token:  # Skip tokens without a pin-role assignment.
            continue  # Move to the next token.
        pin_part, role_part = token.split("=", 1)  # Split the pin number from the role.
        pin_part = pin_part.strip()  # Normalize the pin number token.
        role_part = role_part.strip()  # Normalize the role token.
        if role_part and role_part not in role_map:  # Keep the first pin declared for each role.
            role_map[role_part] = pin_part  # Record the role-to-pin mapping.
            declaration_order.append(pin_part)  # Preserve the declaration order.
    name_map: Dict[str, str] = {}  # Map uppercase pin names onto pin numbers.
    for pin_number, (_pin_x, _pin_y, pin_name) in pins.items():  # Walk the pin geometry.
        if pin_name:  # Keep only named pins.
            name_map.setdefault(pin_name.upper(), pin_number)  # Record the first pin for each name.
    role_order = _ROLE_ORDER.get(sim_device)  # Look up the SPICE node ordering for the device class.
    sorted_numbers = sorted(pins.keys(), key=_pin_sort_key)  # Sort pin numbers numerically.
    pin_map: Dict[int, str] = {}  # Collect the node-to-pin mapping.
    for index, _node in enumerate(nodes):  # Walk every netlist node position.
        role = role_order[index] if role_order is not None and index < len(role_order) else None  # Resolve the SPICE role for this position.
        pin_number: Optional[str] = None  # Initialize the resolved pin number.
        if role is not None:  # Prefer role-based pin selection.
            pin_number = role_map.get(role)  # Look up the pin assigned to the role.
            if pin_number is None:  # Fall back to pin-name matching when roles are unassigned.
                pin_number = name_map.get(role.upper())  # Match the role against pin names.
        if pin_number is None and index < len(sorted_numbers):  # Fall back to ascending pin-number order.
            pin_number = sorted_numbers[index]  # Use the positional pin number.
        if pin_number is not None and pin_number in pins:  # Keep only pins that exist in the symbol.
            pin_map[index] = pin_number  # Record the node-to-pin mapping.
    return pin_map  # Return the completed pin mapping.


def _route_and_build(root_uuid: str, records: List[Dict[str, Any]], settings: Dict[str, Any]) -> BuildResult:  # Place symbols with the ported physics model, route nets with grid A*, and assemble schematic nodes.
    layout = _layout_parameters(settings)  # Resolve the layout parameters from the settings.
    grid, iterations, page_width, page_height = layout  # Unpack the layout parameters.
    placer = _build_placer(records, page_width, page_height, grid)  # Build the force-directed placement model.
    placer.run(iterations)  # Run the physics simulation until convergence or the iteration budget.
    placer.snap_to_grid(grid, 90.0)  # Snap every component onto the discrete placement grids.
    for record in records:  # Write the optimized poses back into the records.
        if record["power"]:  # Power symbols are attached onto net copper later.
            continue  # Move to the next record.
        component = placer.get_component(record["reference"])  # Read the optimized component pose.
        if component is None:  # Skip components that never entered the placer.
            continue  # Move to the next record.
        record["x"] = component.x  # Store the optimized X position.
        record["y"] = component.y  # Store the optimized Y position.
        record["angle"] = component.rotation  # Store the snapped rotation angle.
    nets, net_order = _collect_nets(records)  # Collect net memberships and absolute pin positions.
    router = GridRouter(grid, 0.0, 0.0, page_width, page_height)  # Build the routing grid over the whole page.
    for record in records:  # Block every ordinary symbol body on the routing grid.
        if record["power"]:  # Power bodies are placed after routing.
            continue  # Move to the next record.
        short_name = _split_lib_id(record["lib_id"])[1]  # Read the short symbol name for graphics lookup.
        record["routing_bounds"] = _symbol_body_bounds(record["symbol_node"], short_name, include_pins=False)  # Measure the graphics-only body bounds.
        body_rect = _record_body_rect(record, bounds_key="routing_bounds")  # Compute the rotated body bounding box.
        router.block_rectangle(body_rect[0], body_rect[1], body_rect[2], body_rect[3])  # Block the body cells.
    routing_order = sorted([name for name in net_order if nets[name]], key=lambda name: (len(nets[name]), name))  # Route short nets first.
    net_ids = {name: index + 1 for index, name in enumerate(routing_order)}  # Assign deterministic net ids.
    for name in routing_order:  # Reserve every pin cell for its own net.
        for _record_index, _pin_number, pin_x, pin_y in nets[name]:  # Walk the net pins.
            cell = router.world_to_cell(pin_x, pin_y)  # Convert the pin position to a grid cell.
            router.block_pin_cell(cell[0], cell[1], net_ids[name])  # Hard-reserve the pin cell.
    segments_by_net: Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]] = {}  # Collect routed segments per net.
    polyline_keys_by_net: Dict[str, Set[Tuple[float, float]]] = {}  # Collect compressed corner keys per net for turn-safety checks.
    foreign_points: Set[Tuple[float, float]] = set()  # Collect every pin and corner point used by any net.
    for name in routing_order:  # Preload the foreign-point index with all pin positions.
        for _record_index, _pin_number, pin_x, pin_y in nets[name]:  # Walk the net pins.
            foreign_points.add((round(pin_x, 6), round(pin_y, 6)))  # Index the pin point.
    fallback_count = 0  # Count fallback trunks for deterministic trunk Y assignment.
    for name in routing_order:  # Route every net in the deterministic order.
        pins = nets[name]  # Read the net pin list.
        terminals = [(pin_x, pin_y) for _record_index, _pin_number, pin_x, pin_y in pins]  # Build the A* terminal points.
        segments = router.route(terminals, net_id=net_ids[name])  # Route with hard cell ownership.
        used_cells = list(router.last_routed_cells or [])  # Read the claimed cell path.
        if segments is None:  # Retry with soft foreign-cell crossing.
            segments = router.route(terminals, net_id=net_ids[name], soft=True)  # Route with foreign cells penalized instead of blocked.
            used_cells = list(router.last_routed_cells or [])  # Read the soft cell path.
            if segments is not None and _soft_route_unsafe(router, used_cells, net_ids[name], segments, segments_by_net, polyline_keys_by_net):  # Reject unsafe soft crossings.
                router.unmark_cells(used_cells, net_ids[name])  # Release the unsafe path.
                segments = None  # Force the fallback router.
        if segments is None:  # Route the net with the provably safe fallback trunk engine.
            trunk_y = -_TRUNK_FALLBACK_GAP * (fallback_count + 1)  # Assign a unique trunk below the page.
            fallback_count += 1  # Advance the fallback counter.
            segments = _route_net_trunk_fallback(pins, grid, foreign_points, trunk_y)  # Build the fallback trunk segments.
        else:  # Index the successful A* path corners for fallback avoidance.
            route_corners = router.routed_corner_points()  # Read actual per-branch corners without concatenation jumps.
            polyline_keys_by_net[name] = {(round(point[0], 6), round(point[1], 6)) for point in route_corners}  # Store the corner keys.
            foreign_points.update(polyline_keys_by_net[name])  # Index the corners as foreign points.
        segment_endpoints = {(round(point[0], 6), round(point[1], 6)) for segment in segments for point in segment}  # Index every emitted endpoint, including fallback trunks.
        foreign_points.update(segment_endpoints)  # Prevent later fallback lanes from terminating on these points.
        polyline_keys_by_net.setdefault(name, set()).update(segment_endpoints)  # Include fallback endpoints in later soft-crossing checks.
        segments_by_net[name] = segments  # Store the routed segments.
    embedded_result = _resolve_ground_symbol(settings)  # Resolve the power:GND symbol definition for embedding.
    if not embedded_result[0]:  # Stop when the ground symbol cannot be resolved.
        return embedded_result  # Return the ground symbol error.
    ground_lib_id, ground_symbol_node = embedded_result[1]  # Read the resolved ground symbol.
    ground_pins = _extract_symbol_pins(ground_symbol_node, 1, 1, "GND")[1]  # Extract the ground pin geometry.
    placed_bodies: List[Tuple[float, float, float, float]] = [  # Index placed bodies for power attachment collision checks.
        _record_body_rect(record) for record in records if not record["power"]  # Start with every ordinary body.
    ]  # Finish the initial placed-body list.
    for record in records:  # Attach every voltage-source power symbol onto its net copper.
        if not record["power"]:  # Skip ordinary components.
            continue  # Move to the next record.
        node_name = record["element"].nodes[0] if record["element"].nodes else ""  # Read the source positive node.
        _ensure_net_copper(node_name, nets, segments_by_net, router, foreign_points, grid, page_width, page_height)  # Make sure the net carries wire copper.
        _attach_symbol_on_net(record, segments_by_net.get(node_name, []), placed_bodies, grid)  # Attach the power pin onto the net copper.
    ground_records: List[Dict[str, Any]] = []  # Collect the generated GND power symbols.
    ground_counter = 0  # Count generated GND symbols for deterministic references.
    for node_name in net_order:  # Walk every net to attach GND symbols to ground nets.
        if node_name not in _GROUND_NODE_NAMES:  # Skip non-ground nets.
            continue  # Move to the next net.
        net_pins = nets.get(node_name, [])  # Read the ground net pins.
        if not net_pins:  # Skip empty ground nets defensively.
            continue  # Move to the next net.
        ground_counter += 1  # Advance the GND counter.
        ground_record: Dict[str, Any] = {  # Assemble the generated GND power symbol record.
            "element": None,  # GND symbols carry no netlist element.
            "prefix": "P",  # Use a neutral prefix marker for ground symbols.
            "reference": f"#PWR{ground_counter:02d}",  # Assign a deterministic power reference.
            "value": "GND",  # Use the ground value so the reverse conversion maps the net to node 0.
            "lib_id": ground_lib_id,  # Reference the resolved ground power symbol.
            "symbol_props": {},  # Ground symbols need no simulation properties.
            "pins": ground_pins,  # Store the resolved ground pin geometry.
            "pin_map": {0: "1"},  # Ground symbols expose a single pin.
            "power": True,  # Mark the record as a power symbol.
            "symbol_node": ground_symbol_node,  # Store the resolved symbol node for body geometry.
            "x": 0.0,  # Initialize the GND symbol X position.
            "y": 0.0,  # Initialize the GND symbol Y position.
            "angle": 0.0,  # Initialize the GND symbol angle.
            "pin_positions": {},  # Pin positions are filled by the attachment step.
        }  # Finish the ground record assembly.
        ground_record["body_bounds"] = _symbol_body_bounds(ground_symbol_node, "GND")  # Resolve the ground body bounds.
        _ensure_net_copper(node_name, nets, segments_by_net, router, foreign_points, grid, page_width, page_height)  # Make sure the ground net carries wire copper.
        _attach_symbol_on_net(ground_record, segments_by_net.get(node_name, []), placed_bodies, grid)  # Attach the GND pin onto the ground copper.
        ground_records.append(ground_record)  # Append the ground symbol record.
    all_records = records + ground_records  # Combine the component and ground records.
    lead_stubs_by_net = _build_pin_lead_stubs(nets, segments_by_net, all_records, grid)  # Build pin lead stubs so every pin owns a segment start.
    wire_nodes = _build_wire_nodes(root_uuid, net_order, segments_by_net, lead_stubs_by_net)  # Build the wire nodes for every routed segment and pin stub.
    label_nodes = _build_label_nodes(root_uuid, net_order, segments_by_net)  # Build the label nodes on every non-ground net.
    symbol_nodes = _build_symbol_instance_nodes(all_records, root_uuid)  # Build the symbol instance nodes.
    embedded_extra = {ground_lib_id: ground_symbol_node}  # Collect the ground symbol for embedding.
    return True, (wire_nodes, label_nodes, symbol_nodes, embedded_extra), "", 0  # Return the assembled schematic body.


def _layout_parameters(settings: Dict[str, Any]) -> Tuple[float, int, float, float]:  # Resolve the validated layout parameters.
    grid = float(settings.get("kicad_sch_grid", _KICAD_SCH_GRID))  # Read the placement and routing grid.
    iterations = int(settings.get("kicad_placement_iterations", _PLACEMENT_ITERATIONS))  # Read the placement iteration budget.
    page_width = float(settings.get("kicad_sch_page_width", _KICAD_SCH_PAGE_WIDTH))  # Read the page width.
    page_height = float(settings.get("kicad_sch_page_height", _KICAD_SCH_PAGE_HEIGHT))  # Read the page height.
    return grid, iterations, page_width, page_height  # Return the resolved parameters.


def _build_placer(records: Sequence[Dict[str, Any]], page_width: float, page_height: float, grid: float) -> ForceDirectedPlacer:  # Build the force-directed placement model from the component records.
    config = PlacementConfig(position_grid=grid)  # Configure the placement physics with the schematic grid.
    placer = ForceDirectedPlacer(page_width, page_height, config)  # Build the placer over the schematic page.
    net_pins: Dict[str, List[Tuple[str, str]]] = {}  # Collect spring memberships per net.
    index = 0  # Track the deterministic initial layout index.
    for record in records:  # Walk every component record.
        if record["power"]:  # Power symbols are attached after routing.
            continue  # Move to the next record.
        short_name = _split_lib_id(record["lib_id"])[1]  # Read the short symbol name for graphics lookup.
        bounds = _symbol_body_bounds(record["symbol_node"], short_name)  # Look the body bounds up from the symbol graphics.
        record["body_bounds"] = bounds  # Store the body bounds on the record.
        if bounds is None:  # Fall back to a small default body for graphics-less symbols.
            width = height = 2 * _SYMBOL_BODY_PADDING + 1.27  # Use a minimal default body.
        else:  # Size the body from the looked-up graphics bounds.
            width = max(bounds[2] - bounds[0], 1.27) + 2 * _SYMBOL_BODY_PADDING  # Add padding to the measured width.
            height = max(bounds[3] - bounds[1], 1.27) + 2 * _SYMBOL_BODY_PADDING  # Add padding to the measured height.
        x = _PLACEMENT_START_X + (index % 10) * _PLACEMENT_STEP_X  # Initial column position.
        y = _PLACEMENT_Y + (index // 10) * 15.24  # Initial row position.
        pins = [(str(pin_number), local_x, -local_y) for pin_number, (local_x, local_y, _name) in record["pins"].items()]  # Convert pins into screen-space offsets.
        placer.add_component(record["reference"], x, y, width, height, pins)  # Register the component with the placer.
        for node_index, pin_number in record["pin_map"].items():  # Walk the mapped pins to build springs.
            node_name = record["element"].nodes[node_index]  # Read the netlist node name.
            net_pins.setdefault(node_name, []).append((record["reference"], str(pin_number)))  # Register the spring member.
        index += 1  # Advance the layout index.
    placer.create_springs_from_nets(net_pins)  # Create the star-topology net springs.
    return placer  # Return the prepared placer.


def _collect_nets(records: Sequence[Dict[str, Any]]) -> Tuple[Dict[str, List[Tuple[int, str, float, float]]], List[str]]:  # Collect net memberships and absolute pin positions.
    nets: Dict[str, List[Tuple[int, str, float, float]]] = {}  # Collect net pins keyed by node name.
    net_order: List[str] = []  # Preserve the first-appearance order of node names.
    for record_index, record in enumerate(records):  # Walk every component record.
        if record["power"]:  # Register power-only nets without pin positions.
            node_name = record["element"].nodes[0] if record["element"].nodes else ""  # Read the source positive node.
            if node_name and node_name not in nets:  # Register the node on first appearance.
                nets[node_name] = []  # Start the empty net pin list.
                net_order.append(node_name)  # Preserve the first-appearance order.
            continue  # Move to the next record.
        record["pin_positions"] = {}  # Prepare the absolute pin position mapping.
        for node_index, pin_number in record["pin_map"].items():  # Walk the mapped pins.
            local_x, local_y, _pin_name = record["pins"][pin_number]  # Read the local pin coordinates.
            absolute_x, absolute_y = _transform_point(local_x, local_y, record["x"], record["y"], record["angle"], "")  # Transform the pin into schematic coordinates.
            record["pin_positions"][pin_number] = (absolute_x, absolute_y)  # Store the absolute pin position.
            node_name = record["element"].nodes[node_index]  # Read the netlist node name.
            if node_name not in nets:  # Register the node on first appearance.
                nets[node_name] = []  # Start the net pin list.
                net_order.append(node_name)  # Preserve the first-appearance order.
            nets[node_name].append((record_index, str(pin_number), absolute_x, absolute_y))  # Append the pin to its net.
    return nets, net_order  # Return the collected nets and ordering.


def _record_body_rect(record: Dict[str, Any], bounds_key: str = "body_bounds") -> Tuple[float, float, float, float]:  # Compute the world bounding box of one record's body.
    bounds = record.get(bounds_key)  # Read the local body bounds.
    if bounds is None:  # Fall back to a small default box.
        return record["x"] - 2.54, record["y"] - 2.54, record["x"] + 2.54, record["y"] + 2.54  # Return the default box.
    corners = [(bounds[0], bounds[1]), (bounds[2], bounds[1]), (bounds[2], bounds[3]), (bounds[0], bounds[3])]  # Build the local corner list.
    world_points = [_transform_point(local_x, local_y, record["x"], record["y"], record["angle"], "") for local_x, local_y in corners]  # Transform every corner.
    xs = [point[0] for point in world_points]  # Collect the corner X coordinates.
    ys = [point[1] for point in world_points]  # Collect the corner Y coordinates.
    return min(xs), min(ys), max(xs), max(ys)  # Return the world bounding box.


def _soft_route_unsafe(  # Decide whether a soft A* path crosses foreign wires at unsafe turning points.
    router: GridRouter,  # Accept the routing grid.
    cells: Sequence[Tuple[int, int]],  # Accept the soft path cells.
    net_id: int,  # Accept the current net id.
    current_segments: Sequence[Tuple[Tuple[float, float], Tuple[float, float]]],  # Accept the current emitted route segments.
    segments_by_net: Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]],  # Accept previously routed net geometry.
    polyline_keys_by_net: Dict[str, Set[Tuple[float, float]]],  # Accept the previously routed corner keys.
) -> bool:  # Return True when the soft path must be rejected.
    shared_cells = router.foreign_shared_cells(cells, net_id)  # Find the cells shared with foreign nets.
    if not shared_cells:  # Paths without shared cells are always safe.
        return False  # Accept the soft path.
    route_corners = router.routed_corner_points()  # Read actual branch-local corners without phantom concatenation jumps.
    my_corner_keys = {(round(point[0], 6), round(point[1], 6)) for point in route_corners}  # Index every current route corner and endpoint.
    for cell in shared_cells:  # Walk the shared cells.
        world_x, world_y = router.cell_to_world(cell[0], cell[1])  # Convert the cell to its world center.
        key = (round(world_x, 6), round(world_y, 6))  # Round the shared point key.
        if key in my_corner_keys:  # Reject when my own path turns or terminates on a foreign cell.
            return True  # Report the unsafe crossing.
        for foreign_keys in polyline_keys_by_net.values():  # Walk the previously routed nets.
            if key in foreign_keys:  # Reject when a foreign wire turns on this cell.
                return True  # Report the unsafe crossing.
        current_directions = {_segment_direction_at_point(segment, world_x, world_y) for segment in current_segments}  # Collect current segment directions through the point.
        current_directions.discard(None)  # Drop segments that do not contain the shared point.
        foreign_directions = {_segment_direction_at_point(segment, world_x, world_y) for foreign_segments in segments_by_net.values() for segment in foreign_segments}  # Collect prior segment directions through the point.
        foreign_directions.discard(None)  # Drop segments that do not contain the shared point.
        if len(current_directions) != 1 or len(foreign_directions) != 1:  # Reject corners, overlaps involving multiple segments, and unexplained ownership.
            return True  # Report an ambiguous crossing.
        if next(iter(current_directions)) == next(iter(foreign_directions)):  # Collinear cell sharing electrically overlaps wires.
            return True  # Reject the overlap and use isolated fallback routing.
    return False  # Report a safe straight-through crossing.


def _segment_direction_at_point(  # Resolve one axis-aligned segment's direction when it contains a point.
    segment: Tuple[Tuple[float, float], Tuple[float, float]],  # Accept the segment endpoints.
    point_x: float,  # Accept the test X coordinate.
    point_y: float,  # Accept the test Y coordinate.
) -> Optional[str]:  # Return H/V or None when the point is not on the segment.
    (start_x, start_y), (end_x, end_y) = segment  # Unpack the segment.
    if abs(start_y - end_y) < 1e-9 and abs(point_y - start_y) < 1e-9 and min(start_x, end_x) - 1e-9 <= point_x <= max(start_x, end_x) + 1e-9:  # Detect a horizontal carrier.
        return "H"  # Report horizontal direction.
    if abs(start_x - end_x) < 1e-9 and abs(point_x - start_x) < 1e-9 and min(start_y, end_y) - 1e-9 <= point_y <= max(start_y, end_y) + 1e-9:  # Detect a vertical carrier.
        return "V"  # Report vertical direction.
    return None  # Report that the segment does not contain the point.


def _route_net_trunk_fallback(  # Route one net with the provably safe fallback trunk engine.
    pins: Sequence[Tuple[int, str, float, float]],  # Accept the net pin list.
    grid: float,  # Accept the routing grid.
    foreign_points: Set[Tuple[float, float]],  # Accept every foreign pin and corner point.
    trunk_y: float,  # Accept the exclusive trunk Y below the page.
) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:  # Return the fallback wire segments.
    segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []  # Collect the generated segments.
    avoid_xs = {point[0] for point in foreign_points}  # Index the X coordinates occupied by foreign points.
    used_exit_xs: Set[float] = set()  # Track exit lanes already claimed by this net.
    exit_xs: List[float] = []  # Collect the resolved exit lanes.
    for pin_index, (_record_index, _pin_number, pin_x, pin_y) in enumerate(pins):  # Walk every net pin.
        chosen: Optional[float] = None  # Initialize the chosen lane.
        max_steps = max(4, len(avoid_xs) + len(used_exit_xs) + 2)  # Bound each spacing search by the finite occupied-lane count.
        for subdivision in range(17):  # Progressively search between occupied grid lanes when both sides are bracketed.
            spacing = grid / (2**subdivision)  # Refine the candidate spacing without disconnecting the physical wire.
            for step in range(1, max_steps + 1):  # Search outward at this finite resolution.
                for candidate in (pin_x - step * spacing, pin_x + step * spacing):  # Try both sides at this distance.
                    key = round(candidate, 6)  # Round the candidate X.
                    if key in avoid_xs or key in used_exit_xs:  # Skip lanes occupied by foreign points or prior exits.
                        continue  # Move to the next candidate.
                    low, high = min(pin_x, candidate), max(pin_x, candidate)  # Compute the side-exit span.
                    conflict = any(abs(point[1] - pin_y) < 1e-9 and low < point[0] < high for point in foreign_points)  # Detect foreign points inside the span.
                    if not conflict:  # Accept the clean lane.
                        chosen = candidate  # Store the chosen lane.
                        break  # Stop searching candidates.
                if chosen is not None:  # Stop widening after finding a clean lane.
                    break  # Leave the step loop.
            if chosen is not None:  # Stop refining after finding a clean lane.
                break  # Leave the subdivision loop.
        if chosen is None:  # Retain a deterministic finite fallback for pathologically dense floating-point inputs.
            chosen = pin_x + (pin_index + 1) * grid / (2**18)  # Use a unique microscopic lane beside the pin.
        used_exit_xs.add(round(chosen, 6))  # Claim the lane.
        exit_xs.append(chosen)  # Record the exit lane.
        if abs(chosen - pin_x) > 1e-9:  # Emit the horizontal side-exit stub.
            segments.append(((pin_x, pin_y), (chosen, pin_y)))  # Append the side-exit stub.
        if abs(pin_y - trunk_y) > 1e-9:  # Emit the vertical drop onto the trunk.
            segments.append(((chosen, pin_y), (chosen, trunk_y)))  # Append the vertical drop.
    if len(set(exit_xs)) > 1:  # Emit the horizontal trunk when pins span multiple lanes.
        segments.append(((min(exit_xs), trunk_y), (max(exit_xs), trunk_y)))  # Append the trunk segment.
    return segments  # Return the fallback segments.


def _ensure_net_copper(  # Guarantee that one net carries at least one wire segment.
    node_name: str,  # Accept the net name.
    nets: Dict[str, List[Tuple[int, str, float, float]]],  # Accept the net membership mapping.
    segments_by_net: Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]],  # Accept the routed segment mapping.
    router: GridRouter,  # Accept the routing grid for occupancy checks.
    foreign_points: Set[Tuple[float, float]],  # Accept the foreign point index.
    grid: float,  # Accept the routing grid.
    page_width: float,  # Accept the page width.
    page_height: float,  # Accept the page height.
) -> None:  # Return nothing.
    if segments_by_net.get(node_name):  # Nets that already carry copper need nothing.
        return  # Leave the mapping unchanged.
    pins = nets.get(node_name, [])  # Read the net pins.
    segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []  # Collect the generated stub segments.
    foreign_segments = [segment for foreign_name, routed_segments in segments_by_net.items() if foreign_name != node_name for segment in routed_segments]  # Collect complete foreign-wire geometry, including segment interiors.
    if pins:  # Prefer a stub that starts exactly at the first pin.
        pin_x, pin_y = pins[0][2], pins[0][3]  # Read the first pin position.
        for delta_x, delta_y in ((grid, 0.0), (-grid, 0.0), (0.0, grid), (0.0, -grid)):  # Try both horizontal and vertical directions.
            candidate_segments = [  # Build three explicit wire pieces so every emitted endpoint is checked.
                ((pin_x + (step - 1) * delta_x, pin_y + (step - 1) * delta_y), (pin_x + step * delta_x, pin_y + step * delta_y))
                for step in range(1, 4)
            ]  # Finish the candidate stub.
            if not any(_segments_create_junction(candidate, foreign_segment) for candidate in candidate_segments for foreign_segment in foreign_segments):  # Require every emitted piece to remain electrically isolated from foreign wires.
                for step in range(1, 4):  # Emit three grid steps of wire.
                    segments.append(candidate_segments[step - 1])  # Append the already-validated stub segment.
                break  # Stop after the first clear direction.
    if not segments:  # Fall back to a free-floating stub spot.
        spot = _find_free_stub_spot(router, foreign_points, grid, page_width, page_height)  # Search for a clear spot.
        for step in range(1, 4):  # Emit three grid steps of wire from the spot.
            start_x = spot[0] + (step - 1) * grid  # Compute the segment start X.
            end_x = spot[0] + step * grid  # Compute the segment end X.
            segments.append(((start_x, spot[1]), (end_x, spot[1])))  # Append the stub segment.
        if pins:  # Wire the first pin onto the free-floating stub when one exists.
            pin_x, pin_y = pins[0][2], pins[0][3]  # Read the first pin position.
            if (round(pin_x, 6), round(pin_y, 6)) != (round(spot[0], 6), round(spot[1], 6)):  # Connect only distinct points.
                segments.append(((pin_x, pin_y), (spot[0], spot[1])))  # Append the direct connection segment.
    for start_point, end_point in segments:  # Index the stub points as foreign points.
        foreign_points.add((round(start_point[0], 6), round(start_point[1], 6)))  # Index the segment start.
        foreign_points.add((round(end_point[0], 6), round(end_point[1], 6)))  # Index the segment end.
    segments_by_net[node_name] = segments  # Store the stub segments.


def _segments_create_junction(  # Decide whether two wire segments make an electrical endpoint-on-wire contact.
    first: Tuple[Tuple[float, float], Tuple[float, float]],  # Accept the first segment.
    second: Tuple[Tuple[float, float], Tuple[float, float]],  # Accept the second segment.
) -> bool:  # Return True for a KiCad electrical junction and False for a safe interior crossing.
    return any(_point_on_segment_local(point[0], point[1], second) for point in first) or any(_point_on_segment_local(point[0], point[1], first) for point in second)  # Endpoint contact on either segment creates connectivity.


def _find_free_stub_spot(  # Find a spot whose three-cell horizontal stub avoids every foreign point.
    router: GridRouter,  # Accept the routing grid.
    foreign_points: Set[Tuple[float, float]],  # Accept the foreign point index.
    grid: float,  # Accept the routing grid.
    page_width: float,  # Accept the page width.
    page_height: float,  # Accept the page height.
) -> Tuple[float, float]:  # Return the free spot coordinates.
    for row in range(int(page_height / grid) + 1):  # Scan rows from the top of the page.
        y = page_height - row * grid - grid  # Compute the world Y coordinate.
        for column in range(int(page_width / grid) + 1):  # Scan columns from the left edge.
            x = column * grid  # Compute the world X coordinate.
            clear = True  # Assume the spot is clear.
            for step in range(4):  # Check the spot plus three following cells.
                point_key = (round(x + step * grid, 6), round(y, 6))  # Build the candidate point key.
                if point_key in foreign_points:  # Reject spots crossing foreign points.
                    clear = False  # Mark the spot as occupied.
                    break  # Stop checking this spot.
            if clear:  # Accept the first clear spot.
                return x, y  # Return the free spot.
    return 25.4, -20.0  # Return a deterministic far-away fallback spot.


def _attach_symbol_on_net(  # Attach one power or ground symbol onto its net copper.
    record: Dict[str, Any],  # Accept the power or ground record.
    segments: Sequence[Tuple[Tuple[float, float], Tuple[float, float]]],  # Accept the net wire segments.
    placed_bodies: List[Tuple[float, float, float, float]],  # Accept the placed body rectangles.
    grid: float,  # Accept the routing grid.
) -> None:  # Return nothing.
    pin_number = sorted(record["pin_map"].values(), key=_pin_sort_key)[0]  # Read the single pin number.
    local_x, local_y, _pin_name = record["pins"][pin_number]  # Read the pin local coordinates.
    for point in _segment_attachment_candidates(segments, grid):  # Walk the candidate attachment points.
        origin_x = point[0] - local_x  # Compute the symbol origin X.
        origin_y = point[1] + local_y  # Compute the symbol origin Y.
        rect = _body_rect_at(record.get("body_bounds"), origin_x, origin_y)  # Compute the placed body rectangle.
        if not _rect_overlaps_any(rect, placed_bodies):  # Accept collision-free attachment points.
            record["x"] = origin_x  # Store the symbol X position.
            record["y"] = origin_y  # Store the symbol Y position.
            record["angle"] = 0.0  # Store the upright angle.
            record["pin_positions"] = {pin_number: point}  # Store the attached pin position.
            placed_bodies.append(rect)  # Index the placed body.
            return  # Finish the attachment.
    fallback_point = _segment_attachment_candidates(segments, grid)[0]  # Reuse the first candidate when nothing is collision-free.
    record["x"] = fallback_point[0] - local_x  # Store the fallback X position.
    record["y"] = fallback_point[1] + local_y  # Store the fallback Y position.
    record["angle"] = 0.0  # Store the upright angle.
    record["pin_positions"] = {pin_number: fallback_point}  # Store the attached pin position.


def _segment_attachment_candidates(  # Build ordered candidate attachment points on one net's segments.
    segments: Sequence[Tuple[Tuple[float, float], Tuple[float, float]]],  # Accept the net wire segments.
    grid: float,  # Accept the routing grid.
) -> List[Tuple[float, float]]:  # Return the ordered candidate points.
    horizontal: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []  # Collect horizontal segments.
    vertical: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []  # Collect vertical segments.
    for segment in segments:  # Split the segments by orientation.
        if abs(segment[0][1] - segment[1][1]) < 1e-9:  # Detect horizontal segments.
            horizontal.append(segment)  # Collect the horizontal segment.
        elif abs(segment[0][0] - segment[1][0]) < 1e-9:  # Detect vertical segments.
            vertical.append(segment)  # Collect the vertical segment.
    horizontal.sort(key=lambda segment: abs(segment[1][0] - segment[0][0]), reverse=True)  # Prefer longer horizontal runs.
    vertical.sort(key=lambda segment: abs(segment[1][1] - segment[0][1]), reverse=True)  # Prefer longer vertical runs.
    candidates: List[Tuple[float, float]] = []  # Collect the candidate points.
    for segment in horizontal + vertical:  # Walk the sorted segments.
        if abs(segment[0][1] - segment[1][1]) < 1e-9:  # Handle horizontal segments.
            y = segment[0][1]  # Read the fixed Y coordinate.
            low, high = min(segment[0][0], segment[1][0]), max(segment[0][0], segment[1][0])  # Read the X span.
            x = low + grid  # Start from the first interior grid point.
            while x < high - 1e-9:  # Walk interior grid points.
                candidates.append((x, y))  # Append the interior candidate.
                x += grid  # Advance to the next grid point.
            candidates.append((low, y))  # Append the span start as a fallback.
            candidates.append((high, y))  # Append the span end as a fallback.
        else:  # Handle vertical segments.
            x = segment[0][0]  # Read the fixed X coordinate.
            low, high = min(segment[0][1], segment[1][1]), max(segment[0][1], segment[1][1])  # Read the Y span.
            y = low + grid  # Start from the first interior grid point.
            while y < high - 1e-9:  # Walk interior grid points.
                candidates.append((x, y))  # Append the interior candidate.
                y += grid  # Advance to the next grid point.
            candidates.append((x, low))  # Append the span start as a fallback.
            candidates.append((x, high))  # Append the span end as a fallback.
    return candidates  # Return the ordered candidate points.


def _body_rect_at(bounds: Optional[Tuple[float, float, float, float]], origin_x: float, origin_y: float) -> Tuple[float, float, float, float]:  # Translate local body bounds to a world rectangle.
    if bounds is None:  # Fall back to a small default body.
        return origin_x - 2.54, origin_y - 2.54, origin_x + 2.54, origin_y + 2.54  # Return the default rectangle.
    return origin_x + bounds[0], origin_y - bounds[3], origin_x + bounds[2], origin_y - bounds[1]  # Flip and translate the bounds.


def _rect_overlaps_any(rect: Tuple[float, float, float, float], placed_bodies: Sequence[Tuple[float, float, float, float]]) -> bool:  # Detect overlap between one rectangle and any placed body.
    margin = _KICAD_SCH_GRID / 2  # Keep a small visual standoff between bodies.
    for body in placed_bodies:  # Walk the placed body rectangles.
        if rect[0] - margin < body[2] and rect[2] + margin > body[0] and rect[1] - margin < body[3] and rect[3] + margin > body[1]:  # Detect rectangle overlap with margin.
            return True  # Report the overlap.
    return False  # Report a clear placement.


def _resolve_ground_symbol(settings: Dict[str, Any]) -> BuildResult:  # Resolve the power:GND symbol from kicad_path or the ASY fallback.
    library_cache = _LibraryCache(settings["kicad_path"])  # Prepare a fresh library cache.
    ground_symbol = library_cache.find("power:GND")  # Search the kicad_path libraries first.
    if ground_symbol is not None:  # Use the standard library symbol when available.
        return True, ("power:GND", ground_symbol), "", 0  # Return the resolved ground symbol.
    return False, None, "UNKNOWN_SYMBOL: Unable to locate the power:GND symbol in kicad_path", 0  # Return the ground symbol error.


def _symbol_body_bounds(symbol_node: SExp, short_name: str, include_pins: bool = True) -> Optional[Tuple[float, float, float, float]]:  # Look one symbol's body bounds up from its graphics.
    preferred_name = f"{short_name}_1_1"  # Build the preferred sub-symbol name.
    chosen: Optional[SExp] = None  # Initialize the chosen sub-symbol.
    for sub_symbol in symbol_node.find_children("symbol"):  # Walk the nested sub-symbols.
        if _first_atom_value(sub_symbol) == preferred_name:  # Match the preferred name.
            chosen = sub_symbol  # Select the preferred sub-symbol.
            break  # Stop searching.
    if chosen is None:  # Second pass accepts any sub-symbol of the first unit.
        unit_prefix = f"{short_name}_1_"  # Build the unit prefix.
        for sub_symbol in symbol_node.find_children("symbol"):  # Walk the nested sub-symbols again.
            name_value = _first_atom_value(sub_symbol)  # Read the sub-symbol name.
            if name_value is not None and str(name_value).startswith(unit_prefix):  # Match the unit prefix.
                chosen = sub_symbol  # Select the first unit sub-symbol.
                break  # Stop searching.
    graphics_node = chosen if chosen is not None else symbol_node  # Fall back to the whole symbol node.
    min_x: Optional[float] = None  # Initialize the minimum X bound.
    min_y: Optional[float] = None  # Initialize the minimum Y bound.
    max_x: Optional[float] = None  # Initialize the maximum X bound.
    max_y: Optional[float] = None  # Initialize the maximum Y bound.

    def include_point(point_x: float, point_y: float) -> None:  # Grow the bounding box around one point.
        nonlocal min_x, min_y, max_x, max_y  # Mutate the enclosing bounds.
        if min_x is None:  # Seed the first bound.
            min_x = max_x = point_x  # Seed the X bounds.
            min_y = max_y = point_y  # Seed the Y bounds.
            return  # Finish seeding.
        min_x = min(min_x, point_x)  # Grow the minimum X.
        min_y = min(min_y, point_y)  # Grow the minimum Y.
        max_x = max(max_x, point_x)  # Grow the maximum X.
        max_y = max(max_y, point_y)  # Grow the maximum Y.

    for polyline in graphics_node.find_children("polyline"):  # Walk every polyline graphic.
        pts_node = polyline.find_child("pts")  # Locate the point list.
        if pts_node is None:  # Skip polylines without points.
            continue  # Move to the next polyline.
        for xy_node in pts_node.find_children("xy"):  # Walk the coordinate pairs.
            values = [child.value for child in xy_node.children if child.is_atom]  # Collect the coordinate atoms.
            if len(values) >= 2:  # Keep complete coordinate pairs.
                include_point(float(values[0]), float(values[1]))  # Grow the bounds.
    for rectangle in graphics_node.find_children("rectangle"):  # Walk every rectangle graphic.
        for tag in ("start", "end"):  # Walk the corner sections.
            corner = rectangle.find_child(tag)  # Locate the corner section.
            if corner is not None:  # Read present corners.
                values = [child.value for child in corner.children if child.is_atom]  # Collect corner atoms.
                if len(values) >= 2:  # Keep complete corners.
                    include_point(float(values[0]), float(values[1]))  # Grow the bounds.
    for circle in graphics_node.find_children("circle"):  # Walk every circle graphic.
        center_node = circle.find_child("center")  # Locate the circle center.
        radius_node = circle.find_child("radius")  # Locate the circle radius.
        if center_node is None or radius_node is None:  # Skip circles without geometry.
            continue  # Move to the next circle.
        center_values = [child.value for child in center_node.children if child.is_atom]  # Collect center atoms.
        radius_values = [child.value for child in radius_node.children if child.is_atom]  # Collect radius atoms.
        if len(center_values) >= 2 and radius_values:  # Keep complete circles.
            center_x, center_y = float(center_values[0]), float(center_values[1])  # Read the center.
            radius = float(radius_values[0])  # Read the radius.
            include_point(center_x - radius, center_y - radius)  # Grow the lower corner.
            include_point(center_x + radius, center_y + radius)  # Grow the upper corner.
    for arc in graphics_node.find_children("arc"):  # Walk every arc graphic.
        for tag in ("start", "mid", "end"):  # Walk the arc point sections.
            point_node = arc.find_child(tag)  # Locate the point section.
            if point_node is not None:  # Read present points.
                values = [child.value for child in point_node.children if child.is_atom]  # Collect point atoms.
                if len(values) >= 2:  # Keep complete points.
                    include_point(float(values[0]), float(values[1]))  # Grow the bounds.
    if include_pins:  # Pin positions are included only when requested.
        for pin in graphics_node.find_children("pin"):  # Walk every pin definition.
            at_node = pin.find_child("at")  # Locate the pin position section.
            if at_node is not None:  # Read present pin positions.
                values = [child.value for child in at_node.children if child.is_atom]  # Collect position atoms.
                if len(values) >= 2:  # Keep complete positions.
                    include_point(float(values[0]), float(values[1]))  # Grow the bounds.
    if min_x is None:  # Report graphics-less symbols.
        return None  # Return None when no bounds could be measured.
    return min_x, min_y, max_x, max_y  # Return the measured bounds.


def _first_atom_value(node: SExp) -> Optional[object]:  # Read the first atom value of one node.
    for child in node.children:  # Walk the node children.
        if child.is_atom:  # Find the first atom child.
            return child.value  # Return the atom value.
    return None  # Return None when the node carries no atoms.


def _build_pin_lead_stubs(  # Build short lead stubs so every pin is the start of at least one wire segment.
    nets: Dict[str, List[Tuple[int, str, float, float]]],  # Accept the net membership mapping.
    segments_by_net: Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]],  # Accept the routed segments.
    records: Sequence[Dict[str, Any]],  # Accept every component record including power and ground symbols.
    grid: float,  # Accept the routing grid.
) -> Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]]:  # Return the lead stubs keyed by net.
    stubs_by_net: Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]] = {}  # Collect stubs per net.
    for node_name, net_pins in nets.items():  # Walk every net.
        segments = segments_by_net.get(node_name, [])  # Read the net wire segments.
        foreign_segments = [segment for foreign_name, routed_segments in segments_by_net.items() if foreign_name != node_name for segment in routed_segments]  # Collect geometry owned by other nets.
        for _record_index, _pin_number, pin_x, pin_y in net_pins:  # Walk the ordinary net pins.
            stub = _pin_lead_stub(pin_x, pin_y, segments, grid, foreign_segments)  # Build a pin lead whose endpoint avoids foreign wires.
            if stub is not None:  # Keep generated stubs.
                stubs_by_net.setdefault(node_name, []).append(stub)  # Append the stub.
    for record in records:  # Walk the power and ground records.
        if not record["power"]:  # Skip ordinary components whose pins were handled above.
            continue  # Move to the next record.
        node_name = record["element"].nodes[0] if record["element"] is not None and record["element"].nodes else None  # Resolve the net name when an element exists.
        if node_name is None:  # Ground symbols map onto ground nets by scanning the net names.
            for candidate in nets:  # Walk every net name.
                if candidate in _GROUND_NODE_NAMES:  # Pick the first ground net.
                    node_name = candidate  # Use the ground net name.
                    break  # Stop scanning.
        if node_name is None:  # Skip symbols without any resolvable net.
            continue  # Move to the next record.
        segments = segments_by_net.get(node_name, [])  # Read the net wire segments.
        foreign_segments = [segment for foreign_name, routed_segments in segments_by_net.items() if foreign_name != node_name for segment in routed_segments]  # Collect geometry owned by other nets.
        for pin_number, (pin_x, pin_y) in record.get("pin_positions", {}).items():  # Walk the attached power pins.
            stub = _pin_lead_stub(pin_x, pin_y, segments, grid, foreign_segments)  # Build a pin lead whose endpoint avoids foreign wires.
            if stub is not None:  # Keep generated stubs.
                stubs_by_net.setdefault(node_name, []).append(stub)  # Append the stub.
    return stubs_by_net  # Return the lead stubs.


def _pin_lead_stub(  # Build a short lead stub starting exactly at one pin when no segment already starts there.
    pin_x: float,  # Accept the pin X coordinate.
    pin_y: float,  # Accept the pin Y coordinate.
    segments: Sequence[Tuple[Tuple[float, float], Tuple[float, float]]],  # Accept the net wire segments.
    grid: float,  # Accept the routing grid.
    foreign_segments: Sequence[Tuple[Tuple[float, float], Tuple[float, float]]] = (),  # Accept other-net geometry that the stub endpoint must avoid.
) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:  # Return the stub segment or None.
    for segment in segments:  # Walk the net segments.
        if abs(segment[0][0] - pin_x) < 1e-9 and abs(segment[0][1] - pin_y) < 1e-9:  # A segment already starts at the pin.
            return None  # No stub is required.
    for segment in segments:  # Walk the net segments again to find the carrying segment.
        if _point_on_segment_local(pin_x, pin_y, segment):  # Find the segment carrying the pin.
            other_x, other_y = segment[1]  # Read the far endpoint.
            delta_x, delta_y = other_x - pin_x, other_y - pin_y  # Compute the direction vector.
            length = math.hypot(delta_x, delta_y)  # Compute the segment length.
            if length < 1e-9:  # Skip degenerate segments.
                continue  # Move to the next segment.
            step = min(grid, length)  # Start one grid unit along the wire without overshooting.
            for _attempt in range(32):  # Shorten until the new endpoint is not a foreign-wire junction.
                neighbor = (pin_x + delta_x / length * step, pin_y + delta_y / length * step)  # Compute the candidate endpoint on the wire.
                if not any(_point_on_segment_local(neighbor[0], neighbor[1], foreign_segment) for foreign_segment in foreign_segments):  # Require a foreign-clear endpoint.
                    if abs(neighbor[0] - pin_x) < 1e-9 and abs(neighbor[1] - pin_y) < 1e-9:  # Reject a numerically zero-length stub.
                        break  # Stop refining this carrier.
                    return (pin_x, pin_y), neighbor  # Return the safe pin lead stub.
                step *= 0.5  # Move the endpoint closer to the pin before retrying.
    return None  # Return None when no carrying segment exists.


def _point_on_segment_local(px: float, py: float, segment: Tuple[Tuple[float, float], Tuple[float, float]]) -> bool:  # Decide whether a point lies on one segment.
    (start_x, start_y), (end_x, end_y) = segment  # Unpack the segment endpoints.
    if px < min(start_x, end_x) - 1e-6 or px > max(start_x, end_x) + 1e-6:  # Reject points outside the X span.
        return False  # Return False for non-overlapping X coordinates.
    if py < min(start_y, end_y) - 1e-6 or py > max(start_y, end_y) + 1e-6:  # Reject points outside the Y span.
        return False  # Return False for non-overlapping Y coordinates.
    delta_x, delta_y = end_x - start_x, end_y - start_y  # Compute the segment extent.
    length_squared = delta_x * delta_x + delta_y * delta_y  # Compute the squared segment length.
    if length_squared == 0.0:  # Handle degenerate zero-length segments.
        return abs(px - start_x) <= 1e-6 and abs(py - start_y) <= 1e-6  # Return the point-equality check.
    projection = ((px - start_x) * delta_x + (py - start_y) * delta_y) / length_squared  # Project the point onto the segment.
    if projection < -1e-9 or projection > 1.0 + 1e-9:  # Reject projections beyond the segment endpoints.
        return False  # Return False for out-of-range projections.
    closest_x = start_x + projection * delta_x  # Compute the closest X coordinate on the segment.
    closest_y = start_y + projection * delta_y  # Compute the closest Y coordinate on the segment.
    return abs(px - closest_x) <= 1e-6 and abs(py - closest_y) <= 1e-6  # Return the distance check.


def _build_wire_nodes(  # Build one wire node per routed segment and pin lead stub.
    root_uuid: str,  # Accept the schematic root UUID for deterministic identifiers.
    net_order: Sequence[str],  # Accept the net ordering.
    segments_by_net: Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]],  # Accept the routed segments.
    lead_stubs_by_net: Optional[Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]]] = None,  # Accept the pin lead stubs.
) -> List[SExp]:  # Return the generated wire nodes.
    wire_nodes: List[SExp] = []  # Collect the generated wire nodes.
    wire_counter = 0  # Count wires for deterministic identifiers.
    for node_name in net_order:  # Walk every net in order.
        for start_point, end_point in (lead_stubs_by_net or {}).get(node_name, []):  # Emit pin lead stubs first.
            wire_counter += 1  # Advance the wire counter.
            wire_nodes.append(_wire_node(root_uuid, wire_counter, start_point, end_point))  # Append the stub wire node.
        for start_point, end_point in segments_by_net.get(node_name, []):  # Walk the routed segments.
            wire_counter += 1  # Advance the wire counter.
            wire_nodes.append(_wire_node(root_uuid, wire_counter, start_point, end_point))  # Append the segment wire node.
    return wire_nodes  # Return the generated wire nodes.


def _wire_node(root_uuid: str, wire_counter: int, start_point: Tuple[float, float], end_point: Tuple[float, float]) -> SExp:  # Build one wire S-expression node.
    return SExp(name="wire", children=[  # Build the wire list node.
        SExp(name="pts", children=[  # Build the polyline point list.
            SExp(name="xy", children=[SExp(value=start_point[0]), SExp(value=start_point[1])]),  # Start coordinate pair.
            SExp(name="xy", children=[SExp(value=end_point[0]), SExp(value=end_point[1])]),  # End coordinate pair.
        ]),  # Finish the point list.
        SExp(name="stroke", children=[SExp(name="width", children=[SExp(value=0)]), SExp(name="type", children=[SExp(value="default")])]),  # Stroke definition.
        SExp(name="uuid", children=[SExp(value=_derive_uuid(root_uuid, f"wire/{wire_counter}"))]),  # Wire identifier.
    ])  # Finish the wire node.


def _build_label_nodes(  # Build label nodes on every non-ground net's copper.
    root_uuid: str,  # Accept the schematic root UUID for deterministic identifiers.
    net_order: Sequence[str],  # Accept the net ordering.
    segments_by_net: Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]],  # Accept the routed segments.
) -> List[SExp]:  # Return the generated label nodes.
    label_nodes: List[SExp] = []  # Collect the generated label nodes.
    label_counter = 0  # Count labels for deterministic identifiers.
    for node_name in net_order:  # Walk every net in order.
        if node_name in _GROUND_NODE_NAMES:  # Ground nets carry no labels.
            continue  # Move to the next net.
        segments = segments_by_net.get(node_name, [])  # Read the net wire segments.
        label_point = _label_point_on_segments(segments)  # Resolve the label position on the copper.
        if label_point is None:  # Skip nets without any copper.
            continue  # Move to the next net.
        label_counter += 1  # Advance the label counter.
        label_nodes.append(  # Append the generated label node.
            SExp(name="label", children=[  # Build the label list node.
                SExp(value=node_name, _originally_quoted=True),  # Label text carries the original node name; KiCad requires a quoted string here.
                SExp(name="at", children=[SExp(value=label_point[0]), SExp(value=label_point[1]), SExp(value=0)]),  # Label position on the wire.
                SExp(name="effects", children=[SExp(name="font", children=[SExp(name="size", children=[SExp(value=1.27), SExp(value=1.27)])])]),  # Label text effects.
                SExp(name="uuid", children=[SExp(value=_derive_uuid(root_uuid, f"label/{label_counter}"))]),  # Label identifier.
            ])  # Finish the label node.
        )  # Append the label node to the list.
    return label_nodes  # Return the generated label nodes.


def _label_point_on_segments(  # Pick a point that lies exactly on one net's copper.
    segments: Sequence[Tuple[Tuple[float, float], Tuple[float, float]]],  # Accept the net wire segments.
) -> Optional[Tuple[float, float]]:  # Return the label point or None.
    best: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None  # Track the longest horizontal segment.
    for segment in segments:  # Walk the net segments.
        if abs(segment[0][1] - segment[1][1]) < 1e-9:  # Detect horizontal segments.
            if best is None or abs(segment[1][0] - segment[0][0]) > abs(best[1][0] - best[0][0]):  # Keep the longest horizontal run.
                best = segment  # Store the longest segment.
    if best is not None:  # Prefer the midpoint of the longest horizontal run.
        return (best[0][0] + best[1][0]) / 2, best[0][1]  # Return the horizontal midpoint.
    for segment in segments:  # Walk the net segments again.
        if abs(segment[0][0] - segment[1][0]) < 1e-9:  # Detect vertical segments.
            return segment[0][0], (segment[0][1] + segment[1][1]) / 2  # Return the vertical midpoint.
    if segments:  # Fall back to the midpoint of the first (possibly diagonal) segment.
        return (segments[0][0][0] + segments[0][1][0]) / 2, (segments[0][0][1] + segments[0][1][1]) / 2  # Return the segment midpoint.
    return None  # Return None when the net carries no copper.


def _build_symbol_instance_nodes(records: Sequence[Dict[str, Any]], root_uuid: str) -> List[SExp]:  # Build KiCad symbol instance nodes for every record.
    symbol_nodes: List[SExp] = []  # Collect the generated symbol instance nodes.
    for record in records:  # Walk every component record.
        children: List[SExp] = [  # Start the instance children.
            SExp(name="lib_id", children=[SExp(value=record["lib_id"])]),  # Library identifier.
            SExp(name="at", children=[SExp(value=record["x"]), SExp(value=record["y"]), SExp(value=record.get("angle", 0.0))]),  # Placement position and rotation.
            SExp(name="unit", children=[SExp(value=1)]),  # Symbol unit ordinal.
            SExp(name="body_style", children=[SExp(value=1)]),  # Symbol body style ordinal.
            SExp(name="exclude_from_sim", children=[SExp(value="no")]),  # Simulation inclusion flag.
            SExp(name="in_bom", children=[SExp(value="yes")]),  # Bill-of-materials flag.
            SExp(name="on_board", children=[SExp(value="yes")]),  # Board export flag.
            SExp(name="in_pos_files", children=[SExp(value="yes")]),  # Position file flag.
            SExp(name="dnp", children=[SExp(value="no")]),  # Do-not-populate flag.
            SExp(name="fields_autoplaced", children=[SExp(value="yes")]),  # Autoplaced fields flag.
            SExp(name="uuid", children=[SExp(value=_derive_uuid(root_uuid, f"symbol/{record['reference']}"))]),  # Instance identifier.
        ]  # Finish the base instance children.
        children.extend(_build_instance_properties(record))  # Append the instance property nodes.
        pin_numbers = sorted(record["pin_map"].values(), key=_pin_sort_key)  # Sort the used pin numbers.
        for pin_number in pin_numbers:  # Walk the used pins.
            children.append(  # Append the pin declaration.
                SExp(name="pin", children=[  # Build the pin declaration node.
                    SExp(value=str(pin_number), _originally_quoted=True),  # Pin number atom; KiCad requires a quoted string here.
                    SExp(name="uuid", children=[SExp(value=_derive_uuid(root_uuid, f"symbol/{record['reference']}/pin/{pin_number}"))]),  # Pin identifier.
                ])  # Finish the pin declaration node.
            )  # Append the pin declaration to the children.
        children.append(  # Append the instance reference block.
            SExp(name="instances", children=[  # Build the instances block.
                SExp(name="project", children=[  # Build the project block.
                    SExp(value="electronics_design"),  # Project name atom.
                    SExp(name="path", children=[  # Build the sheet path block.
                        SExp(value=f"/{root_uuid}"),  # Root sheet path atom.
                        SExp(name="reference", children=[SExp(value=record["reference"])]),  # Reference designator.
                        SExp(name="unit", children=[SExp(value=1)]),  # Unit ordinal.
                    ]),  # Finish the sheet path block.
                ])  # Finish the project block.
            ])  # Finish the instances block.
        )  # Append the instances block to the children.
        symbol_nodes.append(SExp(name="symbol", children=children))  # Append the completed instance node.
    return symbol_nodes  # Return the generated instance nodes.


def _build_instance_properties(record: Dict[str, Any]) -> List[SExp]:  # Build the property nodes for one symbol instance.
    properties: List[SExp] = []  # Collect the generated property nodes.
    properties.append(  # Append the Reference property.
        _property_node(record["reference"], "Reference", record["reference"], record, visible=not record["power"])  # Reference property with power symbols hidden.
    )  # Append the Reference property to the list.
    properties.append(  # Append the Value property.
        _property_node(record["reference"], "Value", record["value"], record, visible=True)  # Value property always visible.
    )  # Append the Value property to the list.
    footprint_value = record["symbol_props"].get("Footprint", "")  # Read the library footprint default.
    datasheet_value = record["symbol_props"].get("Datasheet", "~")  # Read the library datasheet default.
    description_value = record["symbol_props"].get("Description", "")  # Read the library description default.
    properties.append(  # Append the Footprint property.
        _property_node(record["reference"], "Footprint", footprint_value, record, visible=False)  # Footprint property hidden.
    )  # Append the Footprint property to the list.
    properties.append(  # Append the Datasheet property.
        _property_node(record["reference"], "Datasheet", datasheet_value, record, visible=False)  # Datasheet property hidden.
    )  # Append the Datasheet property to the list.
    properties.append(  # Append the Description property.
        _property_node(record["reference"], "Description", description_value, record, visible=False)  # Description property hidden.
    )  # Append the Description property to the list.
    return properties  # Return the generated property nodes.


def _property_node(reference: str, key: str, value: str, record: Dict[str, Any], visible: bool) -> SExp:  # Build one property node for an instance.
    children: List[SExp] = [  # Start the property children.
        SExp(value=key),  # Property key atom.
        SExp(value=value, _originally_quoted=True),  # Property value atom; KiCad requires a quoted string here.
        SExp(name="at", children=[SExp(value=record["x"]), SExp(value=record["y"] + _PROPERTY_STEP), SExp(value=0)]),  # Property position.
        SExp(name="show_name", children=[SExp(value="no")]),  # Property name visibility flag.
        SExp(name="do_not_autoplace", children=[SExp(value="no")]),  # Autoplace flag.
    ]  # Finish the base property children.
    if not visible:  # Hide non-visible properties.
        children.append(SExp(name="hide", children=[SExp(value="yes")]))  # Append the hide flag.
    effects_children: List[SExp] = [  # Start the text effects children.
        SExp(name="font", children=[SExp(name="size", children=[SExp(value=1.27), SExp(value=1.27)])]),  # Font size.
    ]  # Finish the base effects children.
    if key in {"Reference", "Value"}:  # Left-justify the visible fields.
        effects_children.append(SExp(name="justify", children=[SExp(value="left")]))  # Append the left justification.
    children.append(SExp(name="effects", children=effects_children))  # Append the text effects.
    return SExp(name="property", children=children)  # Return the assembled property node.


def _assemble_schematic(  # Assemble the final schematic text from its parts.
    input_path: str,  # Accept the netlist input path for the root UUID.
    settings: Dict[str, Any],  # Accept the normalized settings.
    embedded_symbols: Dict[str, SExp],  # Accept the embedded symbol definitions.
    body_parts: Tuple[List[SExp], List[SExp], List[SExp], Dict[str, SExp]],  # Accept the assembled body nodes.
) -> str:  # Return the final schematic text.
    root_uuid = _root_uuid(input_path)  # Derive the deterministic schematic root UUID.
    version = settings.get("kicad_sch_version") or datetime.date.today().strftime("%Y%m%d")  # Resolve the format version.
    generator = settings.get("kicad_sch_generator") or "electronics_design"  # Resolve the generator name.
    wire_nodes, label_nodes, symbol_nodes, embedded_extra = body_parts  # Unpack the assembled body nodes.
    all_embedded = dict(embedded_symbols)  # Copy the device symbol definitions.
    all_embedded.update(embedded_extra)  # Merge the ground power symbol definition.
    lib_symbol_nodes: List[SExp] = []  # Collect the embedded symbol nodes.
    for lib_id, symbol_node in all_embedded.items():  # Walk the embedded symbol definitions.
        renamed_node = _rename_embedded_symbol(symbol_node, lib_id)  # Qualify the symbol name with its library identifier.
        lib_symbol_nodes.append(renamed_node)  # Append the embedded symbol node.
    root_children: List[SExp] = [  # Start the schematic root children.
        SExp(name="version", children=[SExp(value=version)]),  # Format version.
        SExp(name="generator", children=[SExp(value=generator)]),  # Generator name.
        SExp(name="uuid", children=[SExp(value=root_uuid)]),  # Schematic identifier.
        SExp(name="paper", children=[SExp(value="A4")]),  # Drawing page size.
        SExp(name="lib_symbols", children=lib_symbol_nodes),  # Embedded symbol definitions.
    ]  # Finish the header children.
    root_children.extend(wire_nodes)  # Append the routed wires.
    root_children.extend(label_nodes)  # Append the net labels.
    root_children.extend(symbol_nodes)  # Append the symbol instances.
    root_children.append(  # Append the closing sheet instance section.
        SExp(name="sheet_instances", children=[  # Build the sheet instances section.
            SExp(name="path", children=[  # Build the root sheet path.
                SExp(value="/"),  # Root sheet path marker.
                SExp(name="page", children=[SExp(value="1", _originally_quoted=True)]),  # Page number; KiCad requires a quoted string here.
            ])  # Finish the root sheet path.
        ])  # Finish the sheet instances section.
    )  # Append the sheet instances section to the root.
    root = SExp(name="kicad_sch", children=root_children)  # Build the schematic root node.
    return "\n".join(_serialize_sexp(root)) + "\n"  # Serialize the schematic text with a trailing newline.


def _rename_embedded_symbol(symbol_node: SExp, lib_id: str) -> SExp:  # Rename an embedded symbol definition to its full library identifier.
    renamed_children: List[SExp] = []  # Collect the renamed children.
    first_atom_replaced = False  # Track whether the leading name atom was replaced.
    for child in symbol_node.children:  # Walk the symbol children.
        if not first_atom_replaced and child.is_atom:  # Replace the leading name atom only.
            renamed_children.append(SExp(value=lib_id))  # Emit the full library identifier.
            first_atom_replaced = True  # Mark the name atom as replaced.
        else:  # Keep all remaining children unchanged.
            renamed_children.append(child)  # Preserve the child node.
    return SExp(name="symbol", children=renamed_children)  # Return the renamed symbol node.


def _root_uuid(input_path: str) -> str:  # Derive a deterministic schematic UUID from the input path.
    stem = os.path.splitext(os.path.basename(input_path))[0]  # Read the input file stem.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://electronics-design.local/kicad_sch/{stem}"))  # Return the deterministic root UUID.


def _derive_uuid(root_uuid: str, suffix: str) -> str:  # Derive a deterministic child UUID from the root UUID.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{root_uuid}/{suffix}"))  # Return the deterministic child UUID.


def _serialize_sexp(node: SExp) -> List[str]:  # Serialize one S-expression node into KiCad-style text lines.
    if node.is_atom:  # Serialize leaf atoms.
        return [_atom_text(node)]  # Return the atom text as a single fragment.
    if not node.name and not node.children:  # Serialize empty lists.
        return ["()"]  # Return the empty list spelling.
    children_are_atoms = all(child.is_atom for child in node.children)  # Check whether every child is an atom.
    if children_are_atoms:  # Inline lists whose children are all atoms.
        parts = ["("]  # Start the inline list.
        if node.name:  # Include the list name when present.
            parts.append(node.name)  # Append the name.
        for child in node.children:  # Walk the atom children.
            parts.append(" " + _atom_text(child))  # Append each atom.
        parts.append(")")  # Close the inline list.
        return ["".join(parts)]  # Return the single inline line.
    lines = ["(" + node.name if node.name else "("]  # Start the multi-line list with its name.
    for child in node.children:  # Walk the list children.
        if child.is_atom:  # Keep leading atoms on the opening line like eeschema does.
            lines[-1] += " " + _atom_text(child)  # Append the atom to the current line.
        else:  # Serialize list children on indented lines.
            for child_line in _serialize_sexp(child):  # Serialize each child recursively.
                lines.append("\t" + child_line)  # Indent the child line.
    lines.append(")")  # Close the multi-line list.
    return lines  # Return the serialized lines.


def _atom_text(node: SExp) -> str:  # Serialize one atom value with KiCad quoting rules.
    value = node.value  # Read the atom value.
    if node._original_str is not None:  # Preserve the source spelling of parsed numeric atoms.
        return node._original_str  # Return the original numeric spelling.
    if isinstance(value, bool):  # Serialize booleans as yes/no keywords.
        return "yes" if value else "no"  # Return the boolean keyword.
    if isinstance(value, (int, float)) and not isinstance(value, bool):  # Serialize numbers with trimmed formatting.
        return _format_number(value)  # Return the formatted number.
    text = str(value)  # Convert the value to text.
    if node._originally_quoted:  # Preserve originally quoted strings.
        return _quote_string(text)  # Return the quoted string.
    if node._originally_bare and not _must_quote(text):  # Preserve originally bare tokens.
        return text  # Return the bare token.
    if _needs_quoting(text):  # Quote values that require quoting.
        return _quote_string(text)  # Return the quoted string.
    return text  # Return the bare keyword token.


def _format_number(value: Any) -> str:  # Format one numeric value without unnecessary trailing zeros.
    if isinstance(value, int):  # Integers serialize directly.
        return str(value)  # Return the integer spelling.
    if float(value) == int(value):  # Whole floats serialize as integers.
        return str(int(value))  # Return the integer spelling.
    rounded = round(float(value), 4)  # Round to the schematic file precision.
    text = f"{rounded:.4f}".rstrip("0").rstrip(".")  # Trim trailing zeros and the decimal point.
    return text if text not in ("", "-") else "0"  # Return the trimmed number or zero.


def _needs_quoting(text: str) -> bool:  # Decide whether a string value must be quoted.
    if not text:  # Empty strings always quote.
        return True  # Return True for empty text.
    if text in _UNQUOTED_KEYWORDS:  # Bare KiCad keywords stay bare.
        return False  # Return False for known keywords.
    if text.startswith("0x") or text.startswith("0X"):  # Hex numbers stay bare.
        return False  # Return False for hex spellings.
    try:  # Attempt numeric interpretation.
        float(text)  # Check whether the text is numeric.
        return False  # Numeric values stay bare.
    except ValueError:  # Non-numeric values fall through.
        return True  # Quote everything else.


def _must_quote(text: str) -> bool:  # Decide whether a string structurally requires quoting.
    if not text:  # Empty strings require quoting.
        return True  # Return True for empty text.
    return any(char in text for char in ' \t\n\r"()\\')  # Return True when unsafe characters are present.


def _quote_string(text: str) -> str:  # Escape and quote one string value.
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')  # Escape backslashes and quotes.
    escaped = escaped.replace("\n", "\\n").replace("\t", "\\t")  # Escape control characters.
    return '"' + escaped + '"'  # Return the quoted string.


def _normalize_convert_settings(convert_settings: Mapping) -> Tuple[bool, Optional[Dict[str, Any]]]:  # Validate the conversion settings and resolve kicad_path.
    if not isinstance(convert_settings, Mapping):  # Require a mapping-like settings object.
        return False, None  # Signal the settings failure.
    raw_path = convert_settings.get("kicad_path")  # Read the required KiCad library path.
    if not isinstance(raw_path, str) or raw_path.strip() == "":  # Require a nonempty path string.
        return False, None  # Signal the settings failure.
    expanded_path = os.path.expanduser(raw_path.strip())  # Expand any user-relative path prefix.
    if not os.path.isdir(expanded_path):  # Require the configured path to exist as a directory.
        return False, None  # Signal the settings failure.
    settings = dict(convert_settings)  # Copy the caller settings.
    settings["kicad_path"] = expanded_path  # Store the resolved KiCad library path.
    version_value = settings.get("kicad_sch_version")  # Read the optional version override.
    if version_value is None:  # Default to today's date.
        settings["kicad_sch_version"] = datetime.date.today().strftime("%Y%m%d")  # Build the default version.
    if not re.match(r"^\d{8}$", str(settings["kicad_sch_version"])):  # Require the YYYYMMDD version shape.
        return False, None  # Signal the settings failure.
    generator_value = settings.get("kicad_sch_generator")  # Read the optional generator override.
    if generator_value is None:  # Default to the package generator name.
        settings["kicad_sch_generator"] = "electronics_design"  # Build the default generator.
    if not isinstance(settings["kicad_sch_generator"], str) or settings["kicad_sch_generator"] == "":  # Require a nonempty generator string.
        return False, None  # Signal the settings failure.
    for number_key in ("kicad_sch_grid", "kicad_sch_page_width", "kicad_sch_page_height"):  # Validate the numeric layout settings.
        number_value = settings.get(number_key)  # Read the optional numeric setting.
        if number_value is None:  # Skip absent settings.
            continue  # Move to the next key.
        try:  # Attempt numeric conversion.
            numeric_value = float(number_value)  # Normalize the setting for finite/range checks.
            if not math.isfinite(numeric_value) or numeric_value <= 0:  # Require finite positive numbers.
                return False, None  # Signal the settings failure.
        except (TypeError, ValueError):  # Catch non-numeric values.
            return False, None  # Signal the settings failure.
    iteration_value = settings.get("kicad_placement_iterations")  # Read the optional iteration budget.
    if iteration_value is not None:  # Validate present iteration budgets.
        try:  # Attempt integer conversion.
            numeric_iterations = float(iteration_value)  # Normalize the iteration setting for exactness checks.
            integer_iterations = int(iteration_value)  # Convert an exact integer spelling or value.
            if not math.isfinite(numeric_iterations) or integer_iterations < 0 or numeric_iterations != integer_iterations:  # Require a finite non-negative integer.
                return False, None  # Signal the settings failure.
        except (OverflowError, TypeError, ValueError):  # Catch non-finite and non-integer values.
            return False, None  # Signal the settings failure.
    return True, settings  # Return the normalized settings dictionary.


def _coerce_output_path(filepath: object) -> Tuple[bool, Optional[str]]:  # Convert the output path input into a filesystem string.
    try:  # Attempt path coercion through the standard library.
        path_string = os.fsdecode(os.fspath(filepath))  # Convert string, bytes, or path-like input.
    except TypeError:  # Catch non-path-like output values.
        return False, None  # Signal the output path failure.
    return True, os.path.expanduser(path_string)  # Return the expanded output path string.


def _coerce_input_path(filepath: object) -> Tuple[bool, Optional[str]]:  # Convert and check the input path.
    try:  # Attempt path coercion through the standard library.
        path_string = os.fsdecode(os.fspath(filepath))  # Convert string, bytes, or path-like input.
    except TypeError:  # Catch non-path-like input values.
        return False, None  # Signal the input path failure.
    expanded_path = os.path.expanduser(path_string)  # Expand any user-relative path prefix.
    if not os.path.exists(expanded_path):  # Require the input file to exist.
        return False, None  # Signal the input path failure.
    if not os.access(expanded_path, os.R_OK):  # Require read permission on the input file.
        return False, None  # Signal the input path failure.
    return True, expanded_path  # Return the checked input path string.


def _write_text_file(filepath: str, text: str) -> Tuple[bool, None]:  # Write the generated schematic text to disk safely.
    parent_directory = os.path.dirname(filepath)  # Read the output parent directory.
    if parent_directory:  # Create the parent directory only when one is needed.
        try:  # Attempt to create any missing parent directories.
            os.makedirs(parent_directory, exist_ok=True)  # Create the directory tree idempotently.
        except OSError:  # Catch directory creation failures.
            return False, None  # Signal the write failure.
    try:  # Attempt to write the output file.
        with open(filepath, "w", encoding="utf-8", newline="\n") as file_handle:  # Open the output file with UTF-8 encoding.
            file_handle.write(text)  # Write the generated text.
    except OSError:  # Catch any write failure.
        return False, None  # Signal the write failure.
    return True, None  # Return success when the file was written.


def _line_from_message(message: str) -> int:  # Extract a trailing line number from a validator message.
    match = _LINE_SUFFIX_PATTERN.search(message or "")  # Search the message for a trailing line suffix.
    if match is None:  # Return zero when no line suffix is present.
        return 0  # Report an unknown line.
    return int(match.group(1))  # Return the extracted one-based line number.
