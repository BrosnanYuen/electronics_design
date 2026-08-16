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

ConversionResult = Tuple[bool, str, int]  # Represent the public conversion return shape.
BuildResult = Tuple[bool, object, str, int]  # Represent internal build successes with payloads and failures with codes.

_GROUND_NODE_NAMES = frozenset({"0", "GND"})  # Treat these netlist node names as the global ground net.

_KICAD_SYMBOL_EXTENSION = ".kicad_sym"  # Recognize KiCad symbol library files by extension.
_ASY_EXTENSION = ".asy"  # Recognize LTspice symbol files by extension.

_LINE_SUFFIX_PATTERN = re.compile(r"Line (\d+)\s*$")  # Extract trailing line numbers from validator messages.

_PLACEMENT_START_X = 50.8  # Place the first component on this X coordinate in mm.
_PLACEMENT_STEP_X = 38.1  # Separate component columns by this X distance in mm.
_PLACEMENT_Y = 88.9  # Place every component row on this Y coordinate in mm.
_TRUNK_CLEARANCE = 15.24  # Distance below the lowest pin where net trunks begin.
_TRUNK_STEP_Y = 15.24  # Vertical separation between successive net trunks.
_POWER_PIN_STANDOFF = 15.24  # Standoff distance for power-symbol pins left of a net's leftmost stub.
_PIN_EXIT_STEP_X = 1.27  # Candidate horizontal side-exit spacing for routing pins onto their trunks.

_PROPERTY_STEP = 2.54  # Vertical offset between stacked instance properties.

_UNSUPPORTED_PREFIXES = frozenset({"K", "A", "@", "&"})  # Devices that cannot be represented by KiCad schematic symbols.

_SIM_DEVICE_LIB_NAMES = {  # Map simulation device classes onto the standard KiCad simulation library symbol names.
    "NPN": "NPN",  # BJT NPN device class.
    "PNP": "PNP",  # BJT PNP device class.
    "NMOS": "NMOS",  # MOSFET N-channel device class.
    "PMOS": "PMOS",  # MOSFET P-channel device class.
    "NJF": "NJFET",  # JFET N-channel device class.
    "PJF": "PJFET",  # JFET P-channel device class.
}  # Finish the simulation device class mapping.

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
    model_types = _parse_model_types(lines)  # Parse .model lines into name-to-type mappings.
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


def _parse_model_types(lines: Sequence[str]) -> Dict[str, str]:  # Parse .model lines into model-name to model-type mappings.
    model_types: Dict[str, str] = {}  # Collect the model type mappings.
    for raw_line in lines:  # Walk every netlist line.
        stripped_line = raw_line.strip()  # Normalize leading whitespace.
        if not stripped_line.lower().startswith(".model"):  # Skip lines that are not model definitions.
            continue  # Move to the next line.
        tokens = stripped_line.split()  # Split the model line into tokens.
        if len(tokens) < 3:  # Skip malformed model lines defensively.
            continue  # Move to the next line.
        model_types[tokens[1]] = tokens[2].upper()  # Record the model type under the model name.
    return model_types  # Return the collected model type mapping.


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
    if prefix == "Q":  # BJTs prefer a simulation symbol matching the declared model type.
        model_type = model_types.get(payload_text, payload_text).upper()  # Resolve the model type from .model lines.
        candidates = []  # Collect BJT candidates.
        if model_type in _SIM_DEVICE_LIB_NAMES:  # Use the simulation symbol for known BJT classes.
            candidates.append(f"Simulation_SPICE:{_SIM_DEVICE_LIB_NAMES[model_type]}")  # Prefer the simulation symbol.
        if payload_text and model_type not in {"NPN", "PNP"}:  # Propose a model-named transistor symbol when it differs from the class name.
            candidates.append(f"Transistor_BJT:{payload_text}")  # Append the model-named transistor symbol.
        if not candidates:  # Fall back when no candidate was proposed.
            candidates.append("Simulation_SPICE:NPN")  # Use the generic NPN simulation symbol.
        return candidates  # Return the BJT candidates.
    if prefix == "M":  # MOSFETs prefer a simulation symbol matching the declared model type.
        model_type = model_types.get(payload_text, payload_text).upper()  # Resolve the model type from .model lines.
        candidates = []  # Collect MOSFET candidates.
        if model_type in _SIM_DEVICE_LIB_NAMES:  # Use the simulation symbol for known MOSFET classes.
            candidates.append(f"Simulation_SPICE:{_SIM_DEVICE_LIB_NAMES[model_type]}")  # Prefer the simulation symbol.
        if payload_text and model_type not in {"NMOS", "PMOS"}:  # Propose a model-named FET symbol when it differs from the class name.
            candidates.append(f"Transistor_FET:{payload_text}")  # Append the model-named FET symbol.
        if not candidates:  # Fall back when no candidate was proposed.
            candidates.append("Simulation_SPICE:NMOS")  # Use the generic NMOS simulation symbol.
        return candidates  # Return the MOSFET candidates.
    if prefix == "J":  # JFETs prefer a simulation symbol matching the declared model type.
        model_type = model_types.get(payload_text, payload_text).upper()  # Resolve the model type from .model lines.
        if model_type in _SIM_DEVICE_LIB_NAMES:  # Use the simulation symbol for known JFET classes.
            return [f"Simulation_SPICE:{_SIM_DEVICE_LIB_NAMES[model_type]}"]  # Return the simulation symbol candidate.
        return ["Simulation_SPICE:NJFET"]  # Fall back to the N-channel JFET simulation symbol.
    if prefix == "V":  # Voltage sources prefer power symbols named after their positive node when ground-referenced.
        positive_node = element.nodes[0] if element.nodes else ""  # Read the source positive node.
        negative_node = element.nodes[1] if len(element.nodes) > 1 else ""  # Read the source negative node.
        if negative_node not in _GROUND_NODE_NAMES or positive_node in _GROUND_NODE_NAMES:  # Use a two-pin source for floating or inverted supplies.
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
) -> BuildResult:  # Return the resolution success with the lib_id and symbol node.
    for lib_id in lib_ids:  # Walk the candidate library identifiers in order.
        if lib_id == "":  # Skip empty candidates.
            continue  # Move to the next candidate.
        symbol_node = library_cache.find(lib_id)  # Search the kicad_path libraries.
        if symbol_node is not None:  # Stop at the first resolved library symbol.
            return True, (lib_id, symbol_node), "", 0  # Return the resolved symbol.
    asy_names = list(_PREFIX_ASY_FALLBACKS.get(element.prefix, ()))  # Read the prefix ASY fallback names.
    if element.prefix == "X":  # Subcircuit fallbacks use the subcircuit name as the ASY basename.
        subcircuit_name = element.tokens[-1] if element.tokens else ""  # Read the trailing subcircuit name token.
        if subcircuit_name:  # Only propose a fallback when a name exists.
            asy_names = [subcircuit_name + _ASY_EXTENSION]  # Build the subcircuit ASY filename.
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
        embedded_lib_id = f"{stem}:{stem}"  # Qualify the embedded symbol so kicad_path never shadows it.
        return True, (embedded_lib_id, symbol_node), "", 0  # Return the embedded fallback symbol.
    detail = "', '".join(lib_ids)  # Join the candidate identifiers for the error message.
    message = f"UNKNOWN_SYMBOL: Unable to resolve a KiCad symbol for device '{element.tokens[0]}' in kicad_path candidates ['{detail}'] or the configured LTspice ASY search paths"  # Explain the failed resolution.
    return False, None, message, element.line_number  # Return the unknown symbol error with the element line.


def _find_asy_file(asy_name: str, settings: Dict[str, Any]) -> Optional[str]:  # Search the configured LTspice roots for one ASY file.
    search_roots: List[str] = []  # Collect the ASY search roots from the settings.
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
    for element in elements:  # Walk every parsed device element.
        prefix = element.prefix  # Read the device prefix.
        if prefix in _UNSUPPORTED_PREFIXES:  # Reject devices with no KiCad schematic representation.
            message = f"UNSUPPORTED_DEVICE: LTspice device prefix '{prefix}' has no KiCad schematic symbol representation"  # Explain the unsupported prefix.
            return False, None, message, element.line_number  # Return the unsupported device error with the element line.
        candidate_ids = _candidate_lib_ids(element, model_types)  # Derive the candidate library identifiers.
        resolve_result = _resolve_symbol(library_cache, candidate_ids, element, settings, temp_directory)  # Resolve the device symbol.
        if not resolve_result[0]:  # Stop when resolution fails.
            return resolve_result  # Return the resolution error unchanged.
        lib_id, symbol_node = resolve_result[1]  # Read the resolved lib_id and symbol node.
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
            "x": 0.0,  # Initialize the placement X (set during routing).
            "y": 0.0,  # Initialize the placement Y (set during routing).
        }  # Finish the voltage source record.
        return True, record, "", 0  # Return the built record.
    if power:  # Reject non-voltage power symbols because they cannot round-trip as sources.
        message = f"UNSUPPORTED_DEVICE: power symbol '{lib_id}' cannot represent device '{element.tokens[0]}'"  # Explain the power mismatch.
        return False, None, message, element.line_number  # Return the unsupported device error.
    if not payload:  # Require a value or model payload on ordinary components.
        message = f"MISSING_COMPONENT_PAYLOAD: device '{element.tokens[0]}' has no value or model payload"  # Explain the missing payload.
        return False, None, message, element.line_number  # Return the payload error.
    if prefix == "L":  # Inductors carry only the inductance value; the reverse conversion restores Rser=1m.
        value = payload[0]  # Use the first payload token as the inductance value.
    elif prefix in {"V", "I"}:  # Source values may carry SPICE waveform phrases.
        value = " ".join(payload)  # Join the source payload into one value string.
    else:  # All other devices take their model or value token directly.
        value = payload[0]  # Use the first payload token as the value.
    reference = element.tokens[0]  # Start with the netlist instance name.
    if prefix == "X":  # Map subcircuit references onto KiCad U references.
        if reference.startswith("X") and len(reference) > 1 and reference[1:2].isdigit():  # Strip the leading X for digit-suffixed names.
            reference = "U" + reference[1:]  # Rebuild the reference with the U prefix.
        else:  # Keep nonstandard subcircuit names intact.
            reference = reference[1:]  # Strip only the leading X.
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
        "x": 0.0,  # Initialize the placement X.
        "y": 0.0,  # Initialize the placement Y.
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


def _route_and_build(root_uuid: str, records: List[Dict[str, Any]], settings: Dict[str, Any]) -> BuildResult:  # Place power symbols, route nets, and assemble schematic nodes.
    non_power_index = 0  # Track the column index for ordinary components.
    for record in records:  # Walk every component record.
        if record["power"]:  # Power symbols are placed later during net routing.
            continue  # Move to the next record.
        record["x"] = _PLACEMENT_START_X + _PLACEMENT_STEP_X * non_power_index  # Assign the column X position.
        record["y"] = _PLACEMENT_Y  # Assign the row Y position.
        non_power_index += 1  # Advance the column index.
    nets: Dict[str, List[Tuple[int, str, float, float, float]]] = {}  # Collect net pins keyed by node name.
    net_order: List[str] = []  # Preserve the first-appearance order of node names.
    for record_index, record in enumerate(records):  # First pass: compute every absolute pin position.
        if record["power"]:  # Power pin positions are computed after trunk Y assignment.
            continue  # Move to the next record.
        record["pin_positions"] = {}  # Prepare the absolute pin position mapping.
        for node_index, pin_number in record["pin_map"].items():  # Walk the mapped pins.
            pin_x, pin_y, _pin_name = record["pins"][pin_number]  # Read the local pin coordinates.
            absolute_x, absolute_y = _transform_point(pin_x, pin_y, record["x"], record["y"], 0.0, "")  # Transform the pin into schematic coordinates.
            record["pin_positions"][pin_number] = (absolute_x, absolute_y)  # Store the absolute pin position.
    global_pin_xs = {  # Index every pin X so side-exit stubs never run through a foreign pin.
        pin_x  # Collect the pin X coordinate.
        for record in records  # Walk every ordinary record.
        if not record["power"]  # Skip power records whose positions are not yet assigned.
        for pin_x, _pin_y in record["pin_positions"].values()  # Walk every pin position.
    }  # Finish the global pin X index.
    for record_index, record in enumerate(records):  # Second pass: assign side-exit lanes and register net pins.
        if record["power"]:  # Power pin positions are computed after trunk Y assignment.
            continue  # Move to the next record.
        record["pin_exits"] = {}  # Prepare the per-pin side-exit mapping.
        used_exits: Set[str] = set()  # Track exits already claimed by this component.
        for pin_number in sorted(record["pin_map"].values(), key=_pin_sort_key):  # Assign exits in pin-number order.
            pin_x, _pin_y = record["pin_positions"][pin_number]  # Read the absolute pin position.
            exit_step = 1  # Start with the first candidate lane.
            while True:  # Search for the first lane that collides with neither a pin nor an existing exit.
                candidate_x = pin_x + exit_step * _PIN_EXIT_STEP_X  # Compute the candidate lane X.
                if candidate_x not in global_pin_xs and candidate_x not in used_exits:  # Accept the lane when it is clear.
                    break  # Stop searching.
                exit_step += 1  # Try the next lane.
            record["pin_exits"][pin_number] = candidate_x  # Store the resolved side-exit X.
            used_exits.add(candidate_x)  # Claim the lane for this component.
        for node_index, pin_number in record["pin_map"].items():  # Walk the mapped pins again to register nets.
            absolute_x, absolute_y = record["pin_positions"][pin_number]  # Read the absolute pin position.
            node_name = record["element"].nodes[node_index]  # Read the netlist node name.
            if node_name not in nets:  # Register the node on first appearance.
                nets[node_name] = []  # Start the net pin list.
                net_order.append(node_name)  # Preserve the first-appearance order.
            nets[node_name].append((record_index, pin_number, absolute_x, absolute_y, record["pin_exits"][pin_number]))  # Append the pin to its net.
    min_pin_y = _PLACEMENT_Y  # Initialize the lowest pin Y bound.
    for net_pins in nets.values():  # Walk every net to find the lowest pin.
        for _record_index, _pin_number, _pin_x, pin_y, _exit_x in net_pins:  # Walk the net pins.
            min_pin_y = min(min_pin_y, pin_y)  # Track the lowest pin Y.
    trunk_ys: Dict[str, float] = {}  # Map node names onto their trunk Y coordinates.
    for net_index, node_name in enumerate(net_order):  # Assign a unique trunk Y per net.
        trunk_ys[node_name] = min_pin_y - _TRUNK_CLEARANCE - _TRUNK_STEP_Y * net_index  # Compute the trunk Y below all pins.
    ground_records: List[Dict[str, Any]] = []  # Collect the generated GND power symbols.
    ground_counter = 0  # Count generated GND symbols for deterministic references.
    for record_index, record in enumerate(records):  # Place every power symbol onto its net.
        if not record["power"]:  # Skip ordinary components here.
            continue  # Move to the next record.
        node_name = record["element"].nodes[0] if record["element"].nodes else ""  # Read the source positive node.
        trunk_y = trunk_ys.get(node_name, min_pin_y - _TRUNK_CLEARANCE)  # Resolve the net trunk Y.
        net_pins = nets.setdefault(node_name, [])  # Resolve the net pin list.
        component_pins = [entry for entry in net_pins if entry[0] != record_index]  # Exclude the power pin itself from the leftmost scan.
        leftmost_exit = min(entry[4] for entry in component_pins) if component_pins else _PLACEMENT_START_X  # Read the leftmost component stub X.
        power_x = leftmost_exit - _POWER_PIN_STANDOFF  # Compute the power pin standoff X.
        record["x"] = power_x  # Assign the power symbol X position.
        record["y"] = trunk_y  # Assign the power symbol Y position.
        record["pin_positions"] = {"1": (power_x, trunk_y)}  # Attach the single power pin at the trunk point.
        nets[node_name].append((record_index, "1", power_x, trunk_y, power_x))  # Add the power pin to the net.
    for node_name in net_order:  # Walk every net to attach GND symbols to ground nets.
        if node_name not in _GROUND_NODE_NAMES:  # Skip non-ground nets.
            continue  # Move to the next net.
        trunk_y = trunk_ys[node_name]  # Read the ground trunk Y.
        net_pins = nets[node_name]  # Read the ground net pins.
        if not net_pins:  # Skip empty ground nets defensively.
            continue  # Move to the next net.
        leftmost_exit = min(entry[4] for entry in net_pins)  # Read the leftmost ground stub X.
        ground_x = leftmost_exit - _POWER_PIN_STANDOFF  # Compute the GND pin standoff X.
        ground_counter += 1  # Advance the GND counter.
        ground_record = {  # Assemble the generated GND power symbol record.
            "element": None,  # GND symbols carry no netlist element.
            "prefix": "P",  # Use a neutral prefix marker for ground symbols.
            "reference": f"#PWR{ground_counter:02d}",  # Assign a deterministic power reference.
            "value": "GND",  # Use the ground value so the reverse conversion maps the net to node 0.
            "lib_id": "power:GND",  # Reference the standard KiCad ground power symbol.
            "symbol_props": {},  # Ground symbols need no simulation properties.
            "pins": {},  # Pin geometry is filled after resolution below.
            "pin_map": {0: "1"},  # Ground symbols expose a single pin.
            "power": True,  # Mark the record as a power symbol.
            "x": ground_x,  # Store the GND symbol X position.
            "y": trunk_y,  # Store the GND symbol Y position.
            "pin_positions": {"1": (ground_x, trunk_y)},  # Attach the GND pin at the trunk point.
        }  # Finish the ground record assembly.
        ground_records.append(ground_record)  # Append the ground symbol record.
        nets[node_name].append((len(records) + len(ground_records) - 1, "1", ground_x, trunk_y, ground_x))  # Add the GND pin to the ground net.
    embedded_result = _resolve_ground_symbol(settings)  # Resolve the power:GND symbol definition for embedding.
    if not embedded_result[0]:  # Stop when the ground symbol cannot be resolved.
        return embedded_result  # Return the ground symbol error.
    ground_lib_id, ground_symbol_node = embedded_result[1]  # Read the resolved ground symbol.
    for ground_record in ground_records:  # Attach the resolved ground symbol geometry to each GND record.
        ground_record["lib_id"] = ground_lib_id  # Store the resolved ground lib_id.
        ground_record["pins"] = _extract_symbol_pins(ground_symbol_node, 1, 1, "GND")[1]  # Store the ground pin geometry.
    all_records = records + ground_records  # Combine the component and ground records.
    wire_nodes, label_nodes = _route_all_nets(nets, net_order, trunk_ys, root_uuid)  # Route wires and labels for every net.
    symbol_nodes = _build_symbol_instance_nodes(all_records, root_uuid)  # Build the symbol instance nodes.
    embedded_extra = {ground_lib_id: ground_symbol_node}  # Collect the ground symbol for embedding.
    return True, (wire_nodes, label_nodes, symbol_nodes, embedded_extra), "", 0  # Return the assembled schematic body.


def _resolve_ground_symbol(settings: Dict[str, Any]) -> BuildResult:  # Resolve the power:GND symbol from kicad_path or the ASY fallback.
    library_cache = _LibraryCache(settings["kicad_path"])  # Prepare a fresh library cache.
    ground_symbol = library_cache.find("power:GND")  # Search the kicad_path libraries first.
    if ground_symbol is not None:  # Use the standard library symbol when available.
        return True, ("power:GND", ground_symbol), "", 0  # Return the resolved ground symbol.
    return False, None, "UNKNOWN_SYMBOL: Unable to locate the power:GND symbol in kicad_path", 0  # Return the ground symbol error.


def _route_all_nets(  # Route orthogonal wire segments and labels for every net.
    nets: Dict[str, List[Tuple[int, str, float, float, float]]],  # Accept the net pin mapping.
    net_order: Sequence[str],  # Accept the first-appearance net order.
    trunk_ys: Dict[str, float],  # Accept the per-net trunk Y coordinates.
    root_uuid: str,  # Accept the schematic root UUID for deterministic identifiers.
) -> Tuple[List[SExp], List[SExp]]:  # Return the generated wire and label nodes.
    wire_nodes: List[SExp] = []  # Collect the generated wire nodes.
    label_nodes: List[SExp] = []  # Collect the generated label nodes.
    wire_counter = 0  # Count wires for deterministic identifiers.
    label_counter = 0  # Count labels for deterministic identifiers.
    for node_name in net_order:  # Walk every net in first-appearance order.
        net_pins = nets.get(node_name, [])  # Read the net pin list.
        if not net_pins:  # Skip empty nets.
            continue  # Move to the next net.
        trunk_y = trunk_ys[node_name]  # Read the trunk Y coordinate.
        segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []  # Collect the routed segments.
        for _record_index, _pin_number, pin_x, pin_y, exit_x in net_pins:  # Walk the net pins.
            if abs(exit_x - pin_x) > 1e-9:  # Route a horizontal side-exit stub when the pin has one.
                segments.append(((pin_x, pin_y), (exit_x, pin_y)))  # Append the horizontal side-exit stub.
            if abs(pin_y - trunk_y) > 1e-9:  # Route a vertical drop stub only when the pin is not on the trunk.
                segments.append(((exit_x, pin_y), (exit_x, trunk_y)))  # Append the vertical drop stub.
        unique_exit_xs = sorted({exit_x for _record_index, _pin_number, _pin_x, _pin_y, exit_x in net_pins})  # Collect the distinct stub X coordinates.
        if len(unique_exit_xs) > 1:  # Route a horizontal trunk only when pins span multiple columns.
            segments.append(((unique_exit_xs[0], trunk_y), (unique_exit_xs[-1], trunk_y)))  # Append the horizontal trunk segment.
        for start_point, end_point in segments:  # Walk the routed segments.
            wire_counter += 1  # Advance the wire counter.
            wire_nodes.append(  # Append the generated wire node.
                SExp(name="wire", children=[  # Build the wire list node.
                    SExp(name="pts", children=[  # Build the polyline point list.
                        SExp(name="xy", children=[SExp(value=start_point[0]), SExp(value=start_point[1])]),  # Start coordinate pair.
                        SExp(name="xy", children=[SExp(value=end_point[0]), SExp(value=end_point[1])]),  # End coordinate pair.
                    ]),  # Finish the point list.
                    SExp(name="stroke", children=[SExp(name="width", children=[SExp(value=0)]), SExp(name="type", children=[SExp(value="default")])]),  # Stroke definition.
                    SExp(name="uuid", children=[SExp(value=_derive_uuid(root_uuid, f"wire/{wire_counter}"))]),  # Wire identifier.
                ])  # Finish the wire node.
            )  # Append the wire node to the list.
        if node_name not in _GROUND_NODE_NAMES:  # Label non-ground nets with their original node names.
            label_counter += 1  # Advance the label counter.
            label_x = min(exit_x for _record_index, _pin_number, _pin_x, _pin_y, exit_x in net_pins)  # Place the label at the left trunk end.
            label_nodes.append(  # Append the generated label node.
                SExp(name="label", children=[  # Build the label list node.
                    SExp(value=node_name),  # Label text carries the original node name.
                    SExp(name="at", children=[SExp(value=label_x), SExp(value=trunk_y), SExp(value=0)]),  # Label position on the trunk.
                    SExp(name="effects", children=[SExp(name="font", children=[SExp(name="size", children=[SExp(value=1.27), SExp(value=1.27)])])]),  # Label text effects.
                    SExp(name="uuid", children=[SExp(value=_derive_uuid(root_uuid, f"label/{label_counter}"))]),  # Label identifier.
                ])  # Finish the label node.
            )  # Append the label node to the list.
    return wire_nodes, label_nodes  # Return the generated wire and label nodes.


def _build_symbol_instance_nodes(records: Sequence[Dict[str, Any]], root_uuid: str) -> List[SExp]:  # Build KiCad symbol instance nodes for every record.
    symbol_nodes: List[SExp] = []  # Collect the generated symbol instance nodes.
    for record in records:  # Walk every component record.
        children: List[SExp] = [  # Start the instance children.
            SExp(name="lib_id", children=[SExp(value=record["lib_id"])]),  # Library identifier.
            SExp(name="at", children=[SExp(value=record["x"]), SExp(value=record["y"]), SExp(value=0)]),  # Placement position.
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
                    SExp(value=pin_number),  # Pin number atom.
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
        SExp(value=value),  # Property value atom.
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
                SExp(name="page", children=[SExp(value="1")]),  # Page number.
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
