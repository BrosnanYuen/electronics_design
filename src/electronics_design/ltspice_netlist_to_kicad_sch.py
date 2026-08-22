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
from .evolutionary_schematic_placement import EvolutionaryPlacementConfig  # Configure the vendored evolutionary placement search.
from .evolutionary_schematic_placement import EvolutionarySchematicPlacer  # Seed physics placement with a global genetic search.
from .flow_placement import apply_flow_placement  # Place symbols with the deterministic signal-flow layout engine.
from .flow_placement import classify_flow_roles  # Reuse the flow role classification for the restricted orientation refinement.
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
from .schematic_trace_optimizer import optimize_routed_traces  # Consolidate routed traces without changing their copper topology.
from .schematic_trace_optimizer import trace_cost  # Compare complete routing candidates deterministically.

ConversionResult = Tuple[bool, str, int]  # Represent the public conversion return shape.
BuildResult = Tuple[bool, object, str, int]  # Represent internal build successes with payloads and failures with codes.

_GROUND_NODE_NAMES = frozenset({"0", "GND"})  # Treat these netlist node names as the global ground net.

_NC_NODE_PREFIXES = ("NC", "NC_", "NC-")  # Mirror the netlist validator's exempt no-connect prefixes.


def _is_nc_net(name: str) -> bool:  # Decide whether one node name is an exempt no-connect stub.
    return name.startswith(_NC_NODE_PREFIXES)  # Match the validator's no-connect conventions.

_GENERATED_NETLIST_MARKER = "* Generated by electronics_design from a KiCad schematic"  # Recognize decks produced by the inverse converter.

_KICAD_SYMBOL_EXTENSION = ".kicad_sym"  # Recognize KiCad symbol library files by extension.
_ASY_EXTENSION = ".asy"  # Recognize LTspice symbol files by extension.

_LINE_SUFFIX_PATTERN = re.compile(r"Line (\d+)\s*$")  # Extract trailing line numbers from validator messages.

_KICAD_SCH_GRID = 1.27  # Default placement and routing grid in mm.
_KICAD_SCH_PAGE_WIDTH = 297.0  # Default A4 landscape page width in mm.
_KICAD_SCH_PAGE_HEIGHT = 210.0  # Default A4 landscape page height in mm.
_PLACEMENT_ITERATIONS = 250  # Default force-directed placement iteration budget.
_PLACEMENT_STRATEGY = "flow"  # Use the deterministic signal-flow layout by default.
_EVOLUTIONARY_POPULATION = 10  # Keep the default global search bounded for API latency.
_EVOLUTIONARY_GENERATIONS = 6  # Default number of genetic placement generations.
_ROUTING_TRIALS = 3  # Try complementary net orders and retain the best complete route.
_TRACE_OPTIMIZATION_PASSES = 8  # Bound topology-preserving trace consolidation work.
_SYMBOL_BODY_PADDING = 1.27  # Extra body padding added around symbol graphics.
_PLACEMENT_START_X = 25.4  # Initial placement row starts at this X coordinate in mm.
_PLACEMENT_STEP_X = 25.4  # Initial placement row column spacing in mm.
_PLACEMENT_Y = 100.0  # Initial placement row Y coordinate in mm.
_PIN_EXIT_STEP_X = 1.27  # Candidate horizontal side-exit spacing for fallback trunk routing.
_POWER_STUB_LENGTH = 3.81  # Default stub length in mm for power-only nets.
_KI_CAD_CONTACT_TOLERANCE = 1e-4  # KiCad treats features this close as electrically touching.

_PROPERTY_STEP = 2.54  # Vertical offset between stacked instance properties.
_TEXT_FONT_SIZE = 1.27  # Visible schematic text height in mm.
_NET_LABEL_FONT_SIZE = 0.01  # Preserve node identities without visible text-on-wire overlap; KiCad 10 ignores local-label hide.
_TEXT_BOUND_HEIGHT = 1.905  # Conservative rendered glyph/baseline envelope in mm used for net-label avoidance boxes.
_TEXT_CLEARANCE = 1.27  # Minimum visible-text clearance from symbols, wires, and other text.
_TEXT_SEARCH_RINGS = 96  # Bound deterministic field-position searches around a symbol.

# Per-character glyph advance widths of the KiCad 10 stroke font, measured from
# rendered schematics and normalized as fractions of the font size. KiCad sums
# these advances plus a constant inter-character gap to form its own text
# bounding boxes, so matching the values here makes collision boxes agree with
# what KiCad actually draws.
_GLYPH_ADVANCES = {
    " ": 0.5564, "!": 0.3421, '"': 0.5564, "#": 0.735, "$": 0.6993, "%": 0.8422, "&": 0.9136,
    "'": 0.3421, "(": 0.485, ")": 0.485, "*": 0.5564, "+": 0.9136, ",": 0.3421, "-": 0.9136,
    ".": 0.3421, "/": 0.7707, ":": 0.3421, ";": 0.3421, "<": 0.9136, "=": 0.9136, ">": 0.9136,
    "?": 0.6279, "@": 0.9493, "[": 0.485, "\\": 0.485, "]": 0.485, "^": 0.4136, "_": 0.5564,
    "{": 0.485, "|": 0.6993, "}": 0.485, "~": 0.5207, "µ": 0.7707, "Ω": 0.8422, "§": 0.6279,
    "0": 0.6993, "1": 0.6993, "2": 0.6993, "3": 0.6993, "4": 0.6993, "5": 0.6993,
    "6": 0.6993, "7": 0.6993, "8": 0.6993, "9": 0.6993,
    "A": 0.6279, "B": 0.735, "C": 0.735, "D": 0.735, "E": 0.6636, "F": 0.6279, "G": 0.735,
    "H": 0.7707, "I": 0.3421, "J": 0.5564, "K": 0.735, "L": 0.5922, "M": 0.8422, "N": 0.7707,
    "O": 0.7707, "P": 0.735, "Q": 0.7707, "R": 0.735, "S": 0.6993, "T": 0.5564, "U": 0.7707,
    "V": 0.6279, "W": 0.8422, "X": 0.6993, "Y": 0.6279, "Z": 0.6993,
    "a": 0.6636, "b": 0.6636, "c": 0.6279, "d": 0.6636, "e": 0.6279, "f": 0.4136, "g": 0.6636,
    "h": 0.6636, "i": 0.3421, "j": 0.3421, "k": 0.5922, "l": 0.3779, "m": 0.985, "n": 0.6636,
    "o": 0.6636, "p": 0.6636, "q": 0.6636, "r": 0.4493, "s": 0.5922, "t": 0.4136, "u": 0.6636,
    "v": 0.5564, "w": 0.7707, "x": 0.5922, "y": 0.5564, "z": 0.5922,
}  # Finish the measured KiCad stroke-font advance table.
_DEFAULT_GLYPH_ADVANCE = 0.70  # Fallback advance fraction for characters missing from the measured table.
_TEXT_INTER_CHARACTER_GAP = 0.0149  # Constant KiCad stroke-font gap between adjacent glyphs, as a fraction of font size.
_TEXT_BOX_HEIGHT_FRACTION = 1.27  # Full stroke-font box height (cap height plus descender) as a fraction of font size.

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
    voltage sources remain explicit two-pin simulation symbols,
    and the global ground net receives a ``GND`` power symbol. Wires are routed
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
        generated_by_converter = any(line.strip() == _GENERATED_NETLIST_MARKER for line in lines)  # Trust generic subcircuit reconstruction only when the inverse converter marked the deck.
        records_result = _build_component_records(elements, model_types, settings, temp_directory, generated_by_converter)  # Resolve symbols and build component records.
        if not records_result[0]:  # Stop when symbol resolution reports a failure.
            return records_result  # Return the resolution error unchanged.
        records, embedded_symbols = records_result[1]  # Read the resolved component records and embedded symbols.
        routing_result = _route_and_build(root_uuid=_root_uuid(input_path), records=records, settings=settings)  # Route nets and assemble the schematic nodes.
        if not routing_result[0]:  # Stop when routing reports a failure.
            return routing_result  # Return the routing error unchanged.
        schematic_nodes = routing_result[1]  # Read the assembled schematic body nodes.
        simulation_text_nodes = _build_simulation_text_nodes(lines, _root_uuid(input_path))  # Preserve the source deck's simulator directives and node-free K statements.
        text = _assemble_schematic(input_path, settings, embedded_symbols, schematic_nodes, simulation_text_nodes)  # Assemble the final schematic text.
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


def _build_simulation_text_nodes(lines: Sequence[str], root_uuid: str) -> List[SExp]:  # Convert netlist simulation statements into top-level KiCad text records.
    statements: List[str] = []  # Preserve supported statements in their source order.
    for raw_line in lines:  # Walk the original physical netlist lines.
        stripped_line = raw_line.strip()  # Normalize surrounding whitespace without changing the statement payload.
        if not stripped_line:  # Ignore blank records.
            continue  # Move to the next source line.
        lowered = stripped_line.lower()  # Normalize only for footer filtering.
        if stripped_line.startswith("."):  # Preserve every validated dot directive except the converter-owned footer.
            if lowered in {".backanno", ".end"}:  # Avoid duplicating the reverse converter's terminal records.
                continue  # Skip the footer statement.
            statements.append(stripped_line)  # Keep the directive verbatim.
            continue  # Move to the next source line.
        if stripped_line[:1].upper() == "K":  # Preserve mutual-inductance statements, which have no electrical node pins.
            statements.append(stripped_line)  # Keep the complete K device card verbatim.
    text_nodes: List[SExp] = []  # Collect graphical simulation text records.
    for index, statement in enumerate(statements, start=1):  # Build one independently readable text node per statement.
        text_nodes.append(SExp(name="text", children=[  # Create a top-level text record consumed by the reverse converter.
            SExp(value=statement, _originally_quoted=True),  # Store the exact simulation statement.
            SExp(name="exclude_from_sim", children=[SExp(value="no")]),  # Keep the statement active during simulation.
            SExp(name="at", children=[SExp(value=0.0), SExp(value=-5.0 * index), SExp(value=0.0)]),  # Park directives outside the routed drawing.
            SExp(name="effects", children=[  # Give the record valid KiCad text effects.
                SExp(name="font", children=[SExp(name="size", children=[SExp(value=1.27), SExp(value=1.27)])]),
                SExp(name="justify", children=[SExp(value="left")]),
            ]),
            SExp(name="uuid", children=[SExp(value=_derive_uuid(root_uuid, f"simulation-text/{index}"))]),  # Assign a deterministic identifier.
        ]))
    return text_nodes  # Return every preserved simulator statement.


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


def _candidate_lib_ids(element: ParsedElement, model_types: Dict[str, str], generated_by_converter: bool = False) -> List[str]:  # Derive candidate KiCad library identifiers for one device.
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
        synthetic_ground_substrate = generated_by_converter and len(element.nodes) == 4 and element.nodes[-1] in _GROUND_NODE_NAMES  # The inverse converter adds ground to ordinary three-pin transistors.
        if len(element.nodes) == 4 and not synthetic_ground_substrate:  # Preserve only an authored explicit substrate with the four-pin simulation symbol.
            polarity += "_Substrate"  # Use the substrate variant of the simulation symbol.
        candidates.append(f"Simulation_SPICE:{polarity}")  # Always propose the polarity-matched simulation symbol.
        return candidates  # Return the BJT candidates.
    if prefix == "M":  # MOSFETs prefer a model-named symbol followed by the polarity-matched simulation symbol.
        model_type = model_types.get(payload_text, payload_text).upper()  # Resolve the model type from the netlist and library .model lines.
        candidates = []  # Collect MOSFET candidates.
        if payload_text and model_type not in {"NMOS", "PMOS"}:  # Propose a model-named FET symbol when it differs from the class name.
            candidates.append(f"Transistor_FET:{payload_text}")  # Append the model-named FET symbol.
        polarity = "PMOS" if model_type == "PMOS" else "NMOS"  # Resolve the MOSFET polarity class.
        synthetic_ground_substrate = generated_by_converter and len(element.nodes) == 4 and element.nodes[-1] in _GROUND_NODE_NAMES  # The inverse converter adds ground to ordinary three-pin transistors.
        if len(element.nodes) == 4 and not synthetic_ground_substrate:  # Preserve only an authored explicit substrate with the four-pin simulation symbol.
            polarity += "_Substrate"  # Use the substrate variant of the simulation symbol.
        candidates.append(f"Simulation_SPICE:{polarity}")  # Always propose the polarity-matched simulation symbol.
        return candidates  # Return the MOSFET candidates.
    if prefix == "J":  # JFETs map to the polarity-matched simulation symbol.
        model_type = model_types.get(payload_text, payload_text).upper()  # Resolve the model type from the netlist and library .model lines.
        return [f"Simulation_SPICE:{'PJFET' if model_type == 'PJF' else 'NJFET'}"]  # Return the polarity-matched simulation symbol candidate.
    if prefix == "V":  # Voltage sources normally remain explicit two-pin devices in the reconstructed schematic.
        reference = str(element.tokens[0]) if element.tokens else ""  # Read the source reference for inverse-converter power-symbol recovery.
        positive_node = element.nodes[0] if element.nodes else ""  # Read the source positive node.
        negative_node = element.nodes[1] if len(element.nodes) > 1 else ""  # Read the source negative node.
        if generated_by_converter and re.fullmatch(r"V_PWR\d+", reference, flags=re.IGNORECASE) and negative_node in _GROUND_NODE_NAMES:  # Recognize the stable card emitted for a KiCad power symbol.
            candidates = []  # Collect exact semantic power-symbol candidates before generic source fallbacks.
            if payload_text and payload_text != "0":  # Prefer the authored power-symbol value when it names a library entry.
                candidates.append(f"power:{payload_text}")  # Recover symbols such as +12V whose node name may be normalized.
            if positive_node and positive_node not in _GROUND_NODE_NAMES:  # Also try the electrical node name.
                candidates.append(f"power:{positive_node}")  # Recover ordinary VCC/VDD-style power symbols.
            candidates.extend(["power:VCC", "Simulation_SPICE:VDC"])  # Retain portable fallbacks when a project-specific power symbol is unavailable.
            return list(dict.fromkeys(candidates))  # Return deterministic unique candidates.
        source_text = " ".join(payload).upper()  # Inspect the source waveform without changing its authored payload.
        waveform_candidates = (  # Prefer the KiCad simulation symbol matching the source's waveform.
            ("PULSE", "Simulation_SPICE:VPULSE"),
            ("SINE", "Simulation_SPICE:VSIN"),
            ("EXP", "Simulation_SPICE:VEXP"),
            ("PWL", "Simulation_SPICE:VPWL"),
            ("SFFM", "Simulation_SPICE:VSFFM"),
        )
        candidates = [lib_id for keyword, lib_id in waveform_candidates if re.search(rf"(?:^|\s){keyword}\s*\(", source_text)]
        candidates.append("Simulation_SPICE:VDC")  # Use the ordinary source for DC, AC, and unsupported waveforms.
        return candidates
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
    allow_generic_subcircuits: bool = False,  # Accept generic X symbols only for converter-produced decks with complete pin metadata.
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
        if pins_result[0] and _subcircuit_round_trips(element, symbol_node):  # Require usable pin graphics and a round-trippable subcircuit identity.
            if symbol_node.find_child("power") is not None or _symbol_pin_count_matches(element, len(pins_result[1]), allow_generic_subcircuits):  # Power symbols carry one pin; converter-added substrates may reconstruct as three-pin symbols.
                return True, (lib_id, symbol_node), "", 0  # Return the resolved symbol.
    asy_names = list(_PREFIX_ASY_FALLBACKS.get(element.prefix, ()))  # Read the prefix ASY fallback names.
    if element.prefix in {"D", "J", "M", "Q", "Z"}:  # Prefer a model-specific ASY when discrete-device node counts exceed generic symbols.
        payload = element.tokens[1 + len(element.nodes):]  # Read the model and parameter tokens after the connectivity nodes.
        if payload:  # Propose a model-specific symbol only when the netlist names one.
            asy_names.insert(0, payload[0] + _ASY_EXTENSION)  # Search configured symbol roots for the named device first.
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
        if not fallback_pins_result[0] or not _symbol_pin_count_matches(element, len(fallback_pins_result[1]), allow_generic_subcircuits):  # Require a round-trippable pin-count match before embedding.
            continue  # Move to the next ASY name.
        embedded_lib_id = f"{stem}:{stem}"  # Qualify the embedded symbol so kicad_path never shadows it.
        return True, (embedded_lib_id, symbol_node), "", 0  # Return the embedded fallback symbol.
    for lib_id in bare_lib_ids:  # Fall back to a library-wide search only when no configured ASY resolves the bare name.
        symbol_node = library_cache.find(lib_id)  # Search all KiCad symbol libraries for the bare symbol name.
        if symbol_node is None:  # Skip names that no library defines.
            continue  # Move to the next bare candidate.
        short_name = _split_lib_id(lib_id)[1]  # Read the short symbol name for pin extraction.
        pins_result = _extract_symbol_pins(symbol_node, 1, 1, short_name)  # Validate the candidate pin graphics.
        if pins_result[0] and _symbol_pin_count_matches(element, len(pins_result[1]), allow_generic_subcircuits) and _subcircuit_round_trips(element, symbol_node):  # Require usable geometry, a round-trippable pin count, and a round-trippable identity.
            return True, (lib_id, symbol_node), "", 0  # Return the library-wide resolution.
    if element.prefix == "X" and allow_generic_subcircuits:  # Fall back only when the trusted generator marker proves the deck's schematic provenance.
        payload = element.tokens[1 + len(element.nodes):]  # Read the payload tokens after the connectivity nodes.
        subcircuit_name = payload[0] if payload else "SUBCKT"  # Read the subcircuit name from the payload.
        generic_result = _build_generic_subcircuit_symbol(subcircuit_name, len(element.nodes))  # Build a self-contained generic symbol.
        if generic_result[0]:  # Use the generated symbol when it passes validation.
            return True, generic_result[1], "", 0  # Return the generic subcircuit symbol.
    detail = "', '".join(lib_ids)  # Join the candidate identifiers for the error message.
    message = f"UNKNOWN_SYMBOL: Unable to resolve a KiCad symbol for device '{element.tokens[0]}' in kicad_path candidates ['{detail}'] or the configured LTspice ASY search paths"  # Explain the failed resolution.
    return False, None, message, element.line_number  # Return the unknown symbol error with the element line.


def _symbol_pin_count_matches(element: ParsedElement, pin_count: int, generated_by_converter: bool) -> bool:
    """Accept exact shapes and inverse-converter three-pin transistor shapes."""

    if pin_count == len(element.nodes):
        return True
    return (
        generated_by_converter
        and element.prefix in {"Q", "M"}
        and len(element.nodes) == 4
        and element.nodes[-1] in _GROUND_NODE_NAMES
        and pin_count == 3
    )


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
    allow_generic_subcircuits: bool = False,  # Accept generic X symbols only for decks emitted by the inverse converter.
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
        candidate_ids = _candidate_lib_ids(element, model_types, allow_generic_subcircuits)  # Derive the candidate library identifiers, including safe inverse-converter hints.
        extra_asy_names = _polarity_asy_fallback_names(element, model_types)  # Derive polarity-matched ASY fallback names.
        resolution_key = (tuple(candidate_ids), tuple(extra_asy_names), prefix, len(element.nodes))  # Key resolution by all shape-affecting inputs.
        cached_symbol = resolved_symbols.get(resolution_key)  # Reuse an earlier identical resolution.
        if cached_symbol is None:  # Resolve this device shape on first use.
            resolve_result = _resolve_symbol(library_cache, candidate_ids, element, settings, temp_directory, extra_asy_names, allow_generic_subcircuits)  # Resolve the device symbol.
            if not resolve_result[0]:  # Stop when resolution fails.
                return resolve_result  # Return the resolution error unchanged.
            lib_id, symbol_node = resolve_result[1]  # Read the resolved lib_id and symbol node.
            resolved_symbols[resolution_key] = (lib_id, symbol_node)  # Cache the successful shape resolution.
        else:  # Reuse the cached symbol definition.
            lib_id, symbol_node = cached_symbol  # Unpack the resolved library id and node.
        record_result = _build_one_record(element, lib_id, symbol_node)  # Build the component record.
        if not record_result[0]:  # Stop when the record build reports a failure.
            return record_result  # Return the record error unchanged.
        record = record_result[1]  # Read the finished component record.
        record["uid"] = len(records)  # Assign a unique placement key so duplicate references never collide.
        records.append(record)  # Append the finished component record.
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
        power_match = re.fullmatch(r"V_PWR(\d+)", str(element.tokens[0]), flags=re.IGNORECASE)  # Recover the reference convention used before inverse conversion.
        reference = f"#PWR{power_match.group(1)}" if power_match is not None else "#" + element.tokens[0]  # Power references carry the hash prefix for reverse conversion.
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
    value = " ".join(payload)  # Preserve the full value payload by default.
    instance_sim_name = ""  # Store an explicit model/subcircuit name when the reverse converter needs one.
    instance_sim_params = ""  # Store instance parameters separately from the displayed value.
    if prefix in {"X", "D", "J", "M", "Q", "Z"}:  # Split model-bearing device payloads into KiCad simulation fields.
        instance_sim_name = payload[0]  # The first payload token is the model or subcircuit name.
        instance_sim_params = " ".join(payload[1:])  # Remaining tokens are true instance parameters.
        value = instance_sim_name  # Keep the visible value free of duplicated instance parameters.
    elif prefix == "L" and len(payload) > 1:  # Keep LTspice's default series resistance out of the visible component value.
        value = payload[0]  # Display the authored inductance itself.
        instance_sim_params = " ".join(payload[1:])  # Preserve Rser and other authored parameters for simulation and round-trip fidelity.
    elif prefix == "T":  # Transmission-line defaults in the library must not override authored Zo/Td values.
        instance_sim_params = " ".join(payload)  # Store the complete line parameter payload as an instance override.
    elif prefix in {"V", "I"}:  # Source-library defaults must not replace the authored LTspice waveform or AC clause.
        source_phrase = " ".join(payload)
        escaped_source = source_phrase.replace("\\", "\\\\").replace('"', '\\"')
        instance_sim_params = f'model="{escaped_source}"'  # Preserve the complete source phrase as one generic model assignment.
        if prefix == "V" and re.search(r"(?:^|\s)(?:PULSE|SINE|EXP|PWL|SFFM)\s*\(", source_phrase, flags=re.IGNORECASE):
            value = short_name  # Show the waveform symbol type while retaining the authored source clause in Sim.Params.
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
        "instance_sim_name": instance_sim_name,  # Preserve the explicit simulation model/subcircuit name.
        "instance_sim_params": instance_sim_params,  # Preserve true per-instance parameters.
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
    positional_numbers = [pin_number for pin_number in declaration_order if pin_number in pins]  # Start with the Sim.Pins declaration order used by reverse conversion.
    for pin_number in sorted_numbers:  # Append pins omitted from Sim.Pins deterministically.
        if pin_number not in positional_numbers:  # Avoid assigning any symbol pin twice.
            positional_numbers.append(pin_number)  # Preserve the remaining numeric pin order.
    pin_map: Dict[int, str] = {}  # Collect the node-to-pin mapping.
    for index, _node in enumerate(nodes):  # Walk every netlist node position.
        role = role_order[index] if role_order is not None and index < len(role_order) else None  # Resolve the SPICE role for this position.
        pin_number: Optional[str] = None  # Initialize the resolved pin number.
        if role is not None:  # Prefer role-based pin selection.
            pin_number = role_map.get(role)  # Look up the pin assigned to the role.
            if pin_number is None:  # Fall back to pin-name matching when roles are unassigned.
                pin_number = name_map.get(role.upper())  # Match the role against pin names.
        if pin_number is None and index < len(positional_numbers):  # Fall back to the same declaration order used during reverse emission.
            pin_number = positional_numbers[index]  # Use the inverse positional pin mapping.
        if pin_number is not None and pin_number in pins:  # Keep only pins that exist in the symbol.
            pin_map[index] = pin_number  # Record the node-to-pin mapping.
    return pin_map  # Return the completed pin mapping.


def _make_routing_orders(
    nets: Mapping[str, Sequence[Tuple[int, str, float, float]]],
    net_order: Sequence[str],
    net_columns: Optional[Mapping[str, int]] = None,
) -> List[List[str]]:
    """Build complementary deterministic orders for negotiated route trials."""

    names = [name for name in net_order if nets[name] and name not in _GROUND_NODE_NAMES]  # Global ground may use disconnected physical stubs and GND symbols.

    def span(name: str) -> float:
        xs = [pin[2] for pin in nets[name]]
        ys = [pin[3] for pin in nets[name]]
        return (max(xs) - min(xs)) + (max(ys) - min(ys))

    candidates = [
        sorted(names, key=lambda name: (len(nets[name]), span(name), name)),
        sorted(names, key=lambda name: (-len(nets[name]), -span(name), name)),
        sorted(names, key=lambda name: (-span(name), -len(nets[name]), name)),
    ]
    if net_columns:  # Route short local nets first when flow columns are known.
        candidates.insert(  # Order by the leftmost flow column with fewest pins first.
            0,
            sorted(names, key=lambda name: (net_columns.get(name, 10**9), len(nets[name]), name)),
        )
        candidates.insert(  # Order by the leftmost flow column with most pins first.
            1,
            sorted(names, key=lambda name: (net_columns.get(name, 10**9), -len(nets[name]), name)),
        )
    unique: List[List[str]] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def _new_routing_grid(
    records: Sequence[Dict[str, Any]],
    nets: Mapping[str, Sequence[Tuple[int, str, float, float]]],
    net_ids: Mapping[str, int],
    grid: float,
    page_width: float,
    page_height: float,
    blocked_points: Sequence[Tuple[float, float]] = (),
) -> GridRouter:
    router = GridRouter(grid, 0.0, 0.0, page_width, page_height)
    for record in records:
        if record["power"]:
            continue
        body_rect = _record_body_rect(record, bounds_key="routing_bounds")
        router.block_rectangle(body_rect[0], body_rect[1], body_rect[2], body_rect[3])
    for blocked_x, blocked_y in blocked_points:  # Block exempt NC pin cells so copper never passes through them.
        cell_x, cell_y = router.world_to_cell(blocked_x, blocked_y)  # Snap the blocked point onto the routing grid.
        router.block_cell(cell_x, cell_y)  # Reserve the NC pin cell.
    for name, pins in nets.items():
        if name not in net_ids:
            continue
        for _record_index, _pin_number, pin_x, pin_y in pins:
            cell_x, cell_y = router.world_to_cell(pin_x, pin_y)
            router.block_pin_cell(cell_x, cell_y, net_ids[name])
    return router


def _route_trial(
    records: Sequence[Dict[str, Any]],
    nets: Mapping[str, Sequence[Tuple[int, str, float, float]]],
    routing_order: Sequence[str],
    net_ids: Mapping[str, int],
    grid: float,
    page_width: float,
    page_height: float,
    central_seed: bool = False,
    blocked_points: Sequence[Tuple[float, float]] = (),
) -> Tuple[GridRouter, Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]], Set[Tuple[float, float]], int]:
    """Route every net physically for one order and return the complete trial."""

    router = _new_routing_grid(records, nets, net_ids, grid, page_width, page_height, blocked_points)
    segments_by_net: Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]] = {}
    polyline_keys_by_net: Dict[str, Set[Tuple[float, float]]] = {}
    foreign_points = {
        (round(pin_x, 6), round(pin_y, 6))
        for pins in nets.values()
        for _record_index, _pin_number, pin_x, pin_y in pins
    }
    fallback_bodies = [_record_body_rect(record, "routing_bounds") for record in records if not record["power"]]  # Exit lanes must never cross symbol bodies.
    fallback_count = 0
    for name in routing_order:
        pins = nets[name]
        terminals = [(pin_x, pin_y) for _record_index, _pin_number, pin_x, pin_y in pins]
        if central_seed:
            terminals = _order_terminals_for_routing(terminals)  # Also evaluate a tree seeded at its Manhattan medoid.
        terminal_keys = {(round(pin_x, 6), round(pin_y, 6)) for pin_x, pin_y in terminals}  # Exempt this net's own terminals from the foreign-point audit.
        foreign_segments = [segment for routed_segments in segments_by_net.values() for segment in routed_segments]  # Collect all previously emitted foreign copper.
        segments = router.route(terminals, net_id=net_ids[name])
        used_cells = list(router.last_routed_cells or [])
        if segments is None:
            segments = router.route(terminals, net_id=net_ids[name], soft=True)
            used_cells = list(router.last_routed_cells or [])
            if segments is not None and _soft_route_unsafe(router, used_cells, net_ids[name], segments, segments_by_net, polyline_keys_by_net):
                router.unmark_cells(used_cells, net_ids[name])
                segments = None
        if segments is not None and any(  # Reject hard or soft routes whose exact off-grid stubs create an electrical junction with foreign copper.
            _segments_create_junction(candidate_segment, foreign_segment)
            for candidate_segment in segments
            for foreign_segment in foreign_segments
        ):
            router.unmark_cells(used_cells, net_ids[name])  # Release the rejected A* occupancy before falling back.
            segments = None  # Force the isolated physical trunk engine.
        if segments is not None and any(  # Reject a wire passing through another net's pin even when the crossing is interior to both wire segments.
            point not in terminal_keys and _point_on_segment_local(point[0], point[1], candidate_segment)
            for candidate_segment in segments
            for point in foreign_points
        ):
            router.unmark_cells(used_cells, net_ids[name])  # Release the rejected A* occupancy before falling back.
            segments = None  # Force an isolated route around every foreign terminal.
        if segments is not None and not _segments_connect_terminals(segments, terminals):  # Reject partial router results that leave same-net pins isolated.
            router.unmark_cells(used_cells, net_ids[name])  # Release the incomplete route's occupancy.
            segments = None  # Force the complete physical trunk implementation.
        if segments is None:
            trunk_y = -grid * (fallback_count + 1)  # Keep emergency trunks on unique adjacent grid lanes near the sheet.
            fallback_count += 1
            segments = _route_net_trunk_fallback(pins, grid, foreign_points, trunk_y, foreign_segments, fallback_bodies)
            router.mark_cells(_grid_cells_for_segments(router, segments), net_ids[name])  # Reserve in-page fallback copper against later hard routes.
        else:
            route_corners = router.routed_corner_points()
            polyline_keys_by_net[name] = {(round(point[0], 6), round(point[1], 6)) for point in route_corners}
            foreign_points.update(polyline_keys_by_net[name])
        endpoints = {(round(point[0], 6), round(point[1], 6)) for segment in segments for point in segment}
        foreign_points.update(endpoints)
        polyline_keys_by_net.setdefault(name, set()).update(endpoints)
        segments_by_net[name] = segments
    return router, segments_by_net, foreign_points, fallback_count


def _order_terminals_for_routing(terminals: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Order terminals from a central seed to nearby peers for compact route trees."""

    unique: List[Tuple[float, float]] = []
    for terminal in terminals:
        if terminal not in unique:
            unique.append(terminal)
    if len(unique) <= 2:
        return unique
    seed = min(
        unique,
        key=lambda point: (
            sum(abs(point[0] - other[0]) + abs(point[1] - other[1]) for other in unique),
            point[0],
            point[1],
        ),
    )
    remaining = [point for point in unique if point != seed]
    ordered = [seed]
    while remaining:
        candidate = min(
            remaining,
            key=lambda point: (
                min(abs(point[0] - placed[0]) + abs(point[1] - placed[1]) for placed in ordered),
                point[0],
                point[1],
            ),
        )
        ordered.append(candidate)
        remaining.remove(candidate)
    return ordered


def _segments_connect_terminals(  # Verify that one segment set forms a single electrical component containing every terminal.
    segments: Sequence[Tuple[Tuple[float, float], Tuple[float, float]]],
    terminals: Sequence[Tuple[float, float]],
    tolerance: float = 1e-6,
) -> bool:
    if len(terminals) <= 1:  # A singleton needs a copper stub later but has no peer terminal to connect here.
        return True
    if not segments:  # Multi-terminal nets cannot be connected without copper.
        return False
    adjacency: Dict[int, Set[int]] = {index: set() for index in range(len(segments))}  # Build segment connectivity by KiCad endpoint contacts.
    for first_index, first in enumerate(segments):
        for second_index in range(first_index + 1, len(segments)):
            second = segments[second_index]
            if _segments_create_junction(first, second, tolerance):
                adjacency[first_index].add(second_index)
                adjacency[second_index].add(first_index)
    terminal_segments: List[int] = []  # Map every terminal to at least one carrying segment.
    for terminal in terminals:
        carrying = next((index for index, segment in enumerate(segments) if _point_on_segment_local(terminal[0], terminal[1], segment, tolerance)), None)
        if carrying is None:
            return False
        terminal_segments.append(carrying)
    reachable = {terminal_segments[0]}  # Traverse from the first terminal's carrying segment.
    pending = [terminal_segments[0]]
    while pending:
        current = pending.pop()
        for neighbor in adjacency[current]:
            if neighbor not in reachable:
                reachable.add(neighbor)
                pending.append(neighbor)
    return all(segment_index in reachable for segment_index in terminal_segments)  # Require every terminal in the same copper component.


def _grid_cells_for_segments(  # Rasterize orthogonal world-space segments onto the routing grid.
    router: GridRouter,  # Accept the grid whose occupancy will be updated.
    segments: Sequence[Tuple[Tuple[float, float], Tuple[float, float]]],  # Accept fallback copper segments.
) -> List[Tuple[int, int]]:  # Return every in-bounds grid cell touched by the segments.
    cells: Set[Tuple[int, int]] = set()  # Deduplicate cells shared by adjacent segments.
    for start_point, end_point in segments:  # Walk every orthogonal segment.
        start_cell = router.world_to_cell(start_point[0], start_point[1])  # Snap the first endpoint onto the routing grid.
        end_cell = router.world_to_cell(end_point[0], end_point[1])  # Snap the second endpoint onto the routing grid.
        if start_cell[0] == end_cell[0]:  # Rasterize a vertical segment.
            low, high = sorted((start_cell[1], end_cell[1]))  # Normalize its row range.
            for cell_y in range(low, high + 1):  # Include both endpoints and every interior row.
                if router.cell_in_bounds(start_cell[0], cell_y):  # Ignore the exclusive trunk portion below the page.
                    cells.add((start_cell[0], cell_y))  # Reserve the touched cell.
        elif start_cell[1] == end_cell[1]:  # Rasterize a horizontal segment.
            low, high = sorted((start_cell[0], end_cell[0]))  # Normalize its column range.
            for cell_x in range(low, high + 1):  # Include both endpoints and every interior column.
                if router.cell_in_bounds(cell_x, start_cell[1]):  # Keep only cells inside the primary routing canvas.
                    cells.add((cell_x, start_cell[1]))  # Reserve the touched cell.
    return sorted(cells)  # Return a deterministic cell list for ownership marking.


def _route_and_build(root_uuid: str, records: List[Dict[str, Any]], settings: Dict[str, Any], forced_strategy: Optional[str] = None) -> BuildResult:  # Place symbols with hybrid optimization, route nets with grid A*, and assemble schematic nodes.
    layout = _layout_parameters(settings)  # Resolve the layout parameters from the settings.
    grid, iterations, page_width, page_height = layout  # Unpack the layout parameters.
    placer = _build_placer(records, page_width, page_height, grid)  # Build the force-directed placement model.
    placement_strategy = forced_strategy or settings.get("kicad_placement_strategy", _PLACEMENT_STRATEGY)
    net_columns = None  # Keep the flow net-column mapping for column-aware routing orders.
    if placement_strategy == "flow":
        net_columns = apply_flow_placement(records, grid, page_width, page_height)  # Place symbols with the deterministic signal-flow layout.
        if net_columns is None:  # Plans that cannot fit the page even after folding fall back deterministically.
            placement_strategy = "hybrid"  # Reuse the hybrid engine as the deterministic fallback.
    if placement_strategy != "flow":
        if placement_strategy in ("evolutionary", "hybrid"):
            evolution_config = EvolutionaryPlacementConfig(
                population_size=int(settings.get("kicad_evolutionary_population", _EVOLUTIONARY_POPULATION)),
                generations=int(settings.get("kicad_evolutionary_generations", _EVOLUTIONARY_GENERATIONS)),
                elitism=min(3, int(settings.get("kicad_evolutionary_population", _EVOLUTIONARY_POPULATION))),
                position_mutation_sigma=max(grid * 4.0, 2.54),
                random_seed=int(settings.get("kicad_placement_seed", 0)),
            )
            EvolutionarySchematicPlacer(placer, grid, evolution_config).optimize()
        if placement_strategy in ("physics", "hybrid"):
            placer.run(iterations)  # Run physics as the local refinement phase.
        placer.snap_to_grid(grid, 90.0)  # Snap every component onto the discrete placement grids.
        for record in records:  # Write the optimized poses back into the records.
            if record["power"]:  # Power symbols are attached onto net copper later.
                continue  # Move to the next record.
            component = placer.get_component(record["uid"])  # Read the optimized component pose under its unique placement key.
            if component is None:  # Skip components that never entered the placer.
                continue  # Move to the next record.
            record["x"] = component.x  # Store the optimized X position.
            record["y"] = component.y  # Store the optimized Y position.
            record["angle"] = component.rotation  # Store the snapped rotation angle.
        _compact_placement(records, grid, page_width, page_height)  # Remove unused whitespace while retaining collision-free, page-centered geometry.
        _legalize_body_overlaps(records, grid, page_width, page_height)  # Nudge symbols whose bodies overlap after compaction.
        _refine_symbol_orientations(records, grid, page_width, page_height)  # Turn pins toward their electrical peers before routing.
        _separate_foreign_pin_overlaps(records, grid, page_width, page_height)  # Prevent touching pin tips from silently shorting unrelated nets.
    else:  # Flow placements keep their human reading direction.
        _refine_flow_orientations(records, grid, page_width, page_height)  # Flip only role-consistent passive devices when copper shortens meaningfully.
        _legalize_body_overlaps(records, grid, page_width, page_height)  # Nudge symbols whose bodies overlap inside a flow row.
        _separate_foreign_pin_overlaps(records, grid, page_width, page_height)  # Prevent touching pin tips from silently shorting unrelated nets.
    nets, net_order = _collect_nets(records)  # Collect net memberships and absolute pin positions.
    no_connect_positions: List[Tuple[float, float]] = []  # Collect NC-marker positions for exempt singleton pins.
    nc_names = {name for name in nets if _is_nc_net(name) and len(nets[name]) <= 1}  # Singleton NC nets match KiCad no-connect markers, not copper.
    if nc_names:  # Replace routed copper with no-connect markers on exempt singleton pins.
        no_connect_positions = [  # Record the schematic-space pin position of every NC net.
            (pins[0][2], pins[0][3]) for name in sorted(nc_names) for pins in [nets[name]] if pins
        ]  # Finish the NC-marker position list.
        nets = {name: pins for name, pins in nets.items() if name not in nc_names}  # Drop NC nets from routing.
        net_order = [name for name in net_order if name not in nc_names]  # Drop NC nets from the ordering.
    power_nodes = {  # Index nets owned by power symbols that must keep copper for their attachments.
        str(record["element"].nodes[0]) for record in records if record["power"] and record["element"] is not None and record["element"].nodes
    }  # Finish the power-net index.
    singleton_label_nets = {  # Singleton label nets get their label directly on the pin, matching hand-drawn KiCad style.
        name for name in nets
        if len(nets[name]) == 1
        and name not in _GROUND_NODE_NAMES
        and name not in power_nodes
    }  # Finish the singleton-label net set.
    singleton_pins = {name: (pins[0][2], pins[0][3]) for name in singleton_label_nets for pins in [nets[name]]}  # Map each singleton net onto its pin position.
    for record in records:  # Block every ordinary symbol body on the routing grid.
        if record["power"]:  # Power bodies are placed after routing.
            continue  # Move to the next record.
        short_name = _split_lib_id(record["lib_id"])[1]  # Read the short symbol name for graphics lookup.
        routing_bounds = _symbol_body_bounds(record["symbol_node"], short_name, include_pins=False)  # Measure the graphics-only body bounds.
        if routing_bounds is not None and (routing_bounds[2] - routing_bounds[0] < 1e-9 or routing_bounds[3] - routing_bounds[1] < 1e-9):  # Degenerate graphics-free bodies stay tiny for routing.
            routing_bounds = None  # Keep the small default below.
        if routing_bounds is None:  # Pin cells carry the real constraints for graphics-less symbols.
            routing_bounds = (record["x"] - grid, record["y"] - grid, record["x"] + grid, record["y"] + grid)  # Use a one-grid routing box.
        record["routing_bounds"] = routing_bounds  # Store the routing body bounds.
    routing_orders = _make_routing_orders(nets, net_order, net_columns)
    trial_limit = min(len(routing_orders), int(settings.get("kicad_routing_trials", _ROUTING_TRIALS)))
    stable_names = [name for name in net_order if nets[name]]
    net_ids = {name: index + 1 for index, name in enumerate(stable_names)}
    trials = [
        _route_trial(records, nets, order, net_ids, grid, page_width, page_height, central_seed, no_connect_positions)
        for order in routing_orders[:trial_limit]
        for central_seed in (False, True)
    ]  # Evaluate both source-order and central-seed trees for each bounded net ordering.
    router, segments_by_net, foreign_points, fallback_count = min(
        trials,
        key=lambda trial: trace_cost(trial[1], trial[3]),
    )
    routed_segments = segments_by_net  # Preserve the complete negotiated routes in case cleanup exposes an unsafe junction.
    optimized_segments = optimize_routed_traces(
        segments_by_net,
        passes=int(settings.get("kicad_trace_optimization_passes", _TRACE_OPTIMIZATION_PASSES)),
        protected_points_by_net={name: [(pin[2], pin[3]) for pin in pins] for name, pins in nets.items()},
    )
    if _routed_nets_are_isolated(optimized_segments, nets):  # Accept cleanup only when it retains complete, isolated physical copper.
        segments_by_net = optimized_segments
    elif _routed_nets_are_isolated(routed_segments, nets):  # Roll back cleanup locally instead of replacing every net with an all-net fallback.
        segments_by_net = routed_segments
    else:  # The per-net A* router and physical fallback are required to produce a complete isolated result.
        return False, None, "WIRING_GENERATION_ERROR: routed nets are not complete and electrically isolated", 0
    straightened_segments = _straighten_aligned_nets(segments_by_net, nets, records, grid, page_width, page_height)  # Replace collinear multi-hop nets with single straight rails.
    if straightened_segments is not None and _routed_nets_are_isolated(straightened_segments, nets):  # Accept rails only when every net stays complete and isolated.
        segments_by_net = straightened_segments
    ground_attachments = _build_disconnected_ground_stubs(nets, records, segments_by_net, grid, page_width, page_height, _KI_CAD_CONTACT_TOLERANCE)  # Give every ground terminal a short local physical connection.
    for ground_name, attachments in ground_attachments.items():  # Store the disconnected ground stubs under their semantic ground net.
        segments_by_net[ground_name] = [segment for _pin, segment in attachments]  # GND symbols unify these intentionally disconnected copper islands.
    if not _routed_nets_are_isolated(segments_by_net, nets):  # Verify the local ground stubs remain isolated from ordinary nets.
        if placement_strategy == "flow" and forced_strategy is None:  # Flow's dense trunk lanes can saturate ground-pin surroundings.
            return _route_and_build(root_uuid, records, settings, forced_strategy="hybrid")  # Retry deterministically with the hybrid engine.
        ground_attachments = _build_disconnected_ground_stubs(nets, records, segments_by_net, grid, page_width, page_height)  # Relax to the fine tolerance when no coarse-clean stub exists.
        for ground_name, attachments in ground_attachments.items():  # Replace the failed coarse stubs.
            segments_by_net[ground_name] = [segment for _pin, segment in attachments]  # Store the relaxed stubs.
        if not _routed_nets_are_isolated(segments_by_net, nets):  # Require at least fine isolation from the relaxed stubs.
            return False, None, "WIRING_GENERATION_ERROR: ground stubs are not electrically isolated", 0
    if placement_strategy == "flow" and forced_strategy is None and not _routed_nets_are_isolated(segments_by_net, nets, _KI_CAD_CONTACT_TOLERANCE):  # Flow's dense trunk lanes may leave near-touching copper that KiCad reads as shorted.
        return _route_and_build(root_uuid, records, settings, forced_strategy="hybrid")  # Retry deterministically with the hybrid engine.
    ordinary_body_rects = [_record_body_rect(record) for record in records if not record["power"]]  # Block stub directions that would cross symbol bodies.
    for node_name in net_order:  # Give singleton and otherwise empty ordinary nets real copper before labels and power symbols are attached.
        if node_name in _GROUND_NODE_NAMES or _is_nc_net(node_name) or node_name in singleton_label_nets:  # Ground uses local stubs, NC pins carry no-connect markers, and singleton labels sit directly on their pin.
            continue
        _ensure_net_copper(node_name, nets, segments_by_net, router, foreign_points, grid, page_width, page_height, ordinary_body_rects)
    embedded_result = _resolve_ground_symbol(settings)  # Resolve the power:GND symbol definition for embedding.
    if not embedded_result[0]:  # Stop when the ground symbol cannot be resolved.
        return embedded_result  # Return the ground symbol error.
    ground_lib_id, ground_symbol_node = embedded_result[1]  # Read the resolved ground symbol.
    ground_pins = _extract_symbol_pins(ground_symbol_node, 1, 1, "GND")[1]  # Extract the ground pin geometry.
    placed_bodies: List[Tuple[float, float, float, float]] = [  # Index placed bodies for power attachment collision checks.
        _record_body_rect(record) for record in records if not record["power"]  # Start with every ordinary body.
    ]  # Finish the initial placed-body list.
    all_pin_points = [  # Index every settled symbol pin so power symbols never attach on top of another device.
        (pin[2], pin[3]) for node_pins in nets.values() for pin in node_pins
    ]  # Finish the pin-point list.
    for record in records:  # Attach every voltage-source power symbol onto its net copper.
        if not record["power"]:  # Skip ordinary components.
            continue  # Move to the next record.
        node_name = record["element"].nodes[0] if record["element"].nodes else ""  # Read the source positive node.
        _ensure_net_copper(node_name, nets, segments_by_net, router, foreign_points, grid, page_width, page_height, ordinary_body_rects)  # Make sure the net carries wire copper.
        foreign_segments = [segment for foreign_name, routed_segments in segments_by_net.items() if foreign_name != node_name for segment in routed_segments]  # Collect other-net copper that must not become a power-pin junction.
        _attach_symbol_on_net(record, segments_by_net.get(node_name, []), placed_bodies, grid, foreign_segments, all_pin_points)  # Attach the power pin only to electrically exclusive copper.
    ground_records: List[Dict[str, Any]] = []  # Collect the generated GND power symbols.
    ground_counter = 0  # Count generated GND symbols for deterministic references.
    used_references = {str(record["reference"]) for record in records}  # Avoid colliding with recovered power-symbol references.
    for node_name in net_order:  # Walk every net to attach GND symbols to ground-net stubs.
        if node_name not in _GROUND_NODE_NAMES:  # Skip non-ground nets.
            continue  # Move to the next net.
        attachments = ground_attachments.get(node_name, [])  # Read the independently stubbed ground terminals.
        if not attachments:  # Skip empty ground nets defensively.
            continue  # Move to the next net.
        for _ordinary_pin, ground_stub in attachments:  # Attach one power symbol to each disconnected ground island.
            ground_counter += 1  # Advance the GND counter.
            while f"#PWR{ground_counter:02d}" in used_references:  # Skip references already restored from V_PWR cards.
                ground_counter += 1  # Advance to the next free power reference.
            ground_reference = f"#PWR{ground_counter:02d}"  # Capture the unique deterministic reference.
            used_references.add(ground_reference)  # Reserve it before building later ground symbols.
            ground_record: Dict[str, Any] = {  # Assemble the generated GND power symbol record.
                "element": None, "prefix": "P", "reference": ground_reference, "value": "GND",
                "lib_id": ground_lib_id, "symbol_props": {}, "pins": ground_pins, "pin_map": {0: "1"},
                "power": True, "symbol_node": ground_symbol_node, "x": 0.0, "y": 0.0, "angle": 0.0, "pin_positions": {},
            }
            ground_record["body_bounds"] = _symbol_body_bounds(ground_symbol_node, "GND")
            ground_record["text_bounds"] = _symbol_body_bounds(ground_symbol_node, "GND", include_pins=False, combine_sections=True)
            foreign_segments = [segment for foreign_name, routed_segments in segments_by_net.items() if foreign_name != node_name for segment in routed_segments]
            _attach_symbol_on_net(ground_record, [ground_stub], placed_bodies, grid, foreign_segments, all_pin_points)
            ground_records.append(ground_record)
    all_records = records + ground_records  # Combine the component and ground records.
    lead_stubs_by_net = _build_pin_lead_stubs(nets, segments_by_net, all_records, grid)  # Build pin lead stubs so every pin owns a segment start.
    label_layout = _layout_visible_text(all_records, net_order, segments_by_net, lead_stubs_by_net, grid, page_width, page_height, singleton_pins)  # Place visible fields and net labels away from symbols, wires, and other text.
    wire_nodes = _build_wire_nodes(root_uuid, net_order, segments_by_net, lead_stubs_by_net)  # Build the wire nodes for every routed segment and pin stub.
    no_connect_nodes = _build_no_connect_nodes(root_uuid, no_connect_positions)  # Mark exempt singleton NC pins with KiCad no-connect markers.
    label_nodes = _build_label_nodes(root_uuid, net_order, segments_by_net, label_layout)  # Label authored names; physical copper carries internal and ground nets.
    symbol_nodes = _build_symbol_instance_nodes(all_records, root_uuid)  # Build the symbol instance nodes.
    embedded_extra = {ground_lib_id: ground_symbol_node}  # Collect the ground symbol for embedding.
    return True, (wire_nodes, no_connect_nodes, label_nodes, symbol_nodes, embedded_extra), "", 0  # Return the assembled schematic body.


def _routed_nets_are_isolated(
    segments_by_net: Mapping[str, Sequence[Tuple[Tuple[float, float], Tuple[float, float]]]],
    nets: Mapping[str, Sequence[Tuple[int, str, float, float]]],
    tolerance: float = 1e-6,
) -> bool:
    """Require complete per-net copper with no KiCad endpoint junctions between nets."""

    net_names = list(nets)
    for node_name, pins in nets.items():
        terminals = [(pin[2], pin[3]) for pin in pins]
        if node_name not in _GROUND_NODE_NAMES and len(terminals) > 1 and not _segments_connect_terminals(segments_by_net.get(node_name, ()), terminals, tolerance):
            return False
    for first_index, first_name in enumerate(net_names):
        first_segments = segments_by_net.get(first_name, ())
        for second_name in net_names[first_index + 1:]:
            second_segments = segments_by_net.get(second_name, ())
            if any(_segments_create_junction(first, second, tolerance) for first in first_segments for second in second_segments):
                return False
            first_terminals = [(pin[2], pin[3]) for pin in nets[first_name]]
            second_terminals = [(pin[2], pin[3]) for pin in nets[second_name]]
            if any(_point_on_segment_local(point[0], point[1], segment, tolerance) for point in first_terminals for segment in second_segments):
                return False
            if any(_point_on_segment_local(point[0], point[1], segment, tolerance) for point in second_terminals for segment in first_segments):
                return False
    return True


def _straighten_aligned_nets(  # Replace collinear multi-hop nets with single straight rails.
    segments_by_net: Mapping[str, Sequence[Tuple[Tuple[float, float], Tuple[float, float]]]],  # Accept the routed segment mapping.
    nets: Mapping[str, Sequence[Tuple[int, str, float, float]]],  # Accept the net membership mapping.
    records: Sequence[Dict[str, Any]],  # Accept the component records for body collision checks.
    grid: float,  # Accept the routing grid.
    page_width: float,  # Accept the page width.
    page_height: float,  # Accept the page height.
) -> Optional[Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]]]:  # Return the straightened mapping or None when nothing changed.
    rail_points: Dict[str, Tuple[Tuple[float, float], Tuple[float, float]]] = {}  # Collect the candidate rail per net.
    for node_name, pins in nets.items():  # Walk every routed net.
        if node_name in _GROUND_NODE_NAMES or len(pins) < 2:  # Ground stubs and singleton nets stay untouched.
            continue  # Move to the next net.
        terminals = [(pin[2], pin[3]) for pin in pins]  # Read the terminal positions.
        first_x, first_y = terminals[0]  # Read the first terminal.
        if all(abs(pin_y - first_y) < 1e-9 for pin_x, pin_y in terminals):  # Detect a shared horizontal line.
            rail = ((min(pin_x for pin_x, _pin_y in terminals), first_y), (max(pin_x for pin_x, _pin_y in terminals), first_y))  # Build the horizontal rail.
        elif all(abs(pin_x - first_x) < 1e-9 for pin_x, pin_y in terminals):  # Detect a shared vertical line.
            rail = ((first_x, min(pin_y for _pin_x, pin_y in terminals)), (first_x, max(pin_y for _pin_x, pin_y in terminals)))  # Build the vertical rail.
        else:  # Non-collinear nets cannot be straightened.
            continue  # Move to the next net.
        rail_points[node_name] = rail  # Record the candidate rail.
    if not rail_points:  # Nothing to straighten.
        return None  # Report no change.
    foreign_points = {  # Index every foreign pin position and wire corner.
        (round(point[0], 6), round(point[1], 6))
        for other_name, other_pins in nets.items()
        for pin in other_pins
        for point in [(pin[2], pin[3])]
    }  # Finish the foreign pin index.
    for other_name, routed in segments_by_net.items():  # Index every foreign segment endpoint.
        for segment in routed:  # Walk the foreign segments.
            foreign_points.add((round(segment[0][0], 6), round(segment[0][1], 6)))  # Index the start point.
            foreign_points.add((round(segment[1][0], 6), round(segment[1][1], 6)))  # Index the end point.
    straightened: Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]] = {name: list(segments) for name, segments in segments_by_net.items()}  # Copy the routed mapping.
    for node_name, rail in rail_points.items():  # Walk the candidate rails.
        terminals = {(round(pin[2], 6), round(pin[3], 6)) for pin in nets[node_name]}  # Exempt this net's own terminals.
        (low_x, low_y), (high_x, high_y) = rail  # Unpack the rail span.
        horizontal = abs(low_y - high_y) < 1e-9  # Detect a horizontal rail.
        interior = [  # Collect rail points that are not this net's terminals.
            (round(point[0], 6), round(point[1], 6))
            for point in ((low_x, low_y), (high_x, high_y))
        ]  # Finish the endpoint list.
        clear = True  # Assume the rail is safe.
        for point in foreign_points:  # Check every foreign point against the rail interior.
            if point in terminals:  # Skip this net's own terminal points.
                continue  # Move to the next point.
            if horizontal and abs(point[1] - low_y) < 1e-9 and low_x < point[0] < high_x:  # Detect a foreign point inside the horizontal span.
                clear = False  # Reject the rail.
                break  # Stop checking.
            if not horizontal and abs(point[0] - low_x) < 1e-9 and low_y < point[1] < high_y:  # Detect a foreign point inside the vertical span.
                clear = False  # Reject the rail.
                break  # Stop checking.
        if not clear:  # Foreign pins or wire corners block the rail.
            continue  # Keep the routed copper.
        foreign_segments = [segment for other_name, routed in segments_by_net.items() if other_name != node_name for segment in routed]  # Collect foreign copper.
        for foreign in foreign_segments:  # Check every foreign segment against the rail interior.
            foreign_start = (round(foreign[0][0], 6), round(foreign[0][1], 6))  # Read the foreign start key.
            foreign_end = (round(foreign[1][0], 6), round(foreign[1][1], 6))  # Read the foreign end key.
            if foreign_start in terminals or foreign_end in terminals:  # Foreign wires ending on this net's pins are normal tap points.
                continue  # Move to the next segment.
            if _segments_create_junction(rail, foreign):  # A foreign endpoint or collinear overlap would electrically merge the nets.
                clear = False  # Reject the rail.
                break  # Stop checking.
        if not clear:  # Foreign copper intersects the rail.
            continue  # Keep the routed copper.
        owner_indices = {pin[0] for pin in nets[node_name]}  # Index the records that own this net's pins.
        for record_index, record in enumerate(records):  # Check foreign symbol bodies against the rail.
            if record["power"] or record_index in owner_indices:  # Skip bodies that own this net's pins.
                continue  # Move to the next record.
            body = _record_body_rect(record)  # Read the body rectangle.
            if horizontal and body[1] < low_y < body[3] and body[0] < (low_x + high_x) / 2.0 < body[2]:  # Detect the rail crossing the body.
                clear = False  # Reject the rail.
                break  # Stop checking.
            if not horizontal and body[0] < low_x < body[2] and body[1] < (low_y + high_y) / 2.0 < body[3]:  # Detect the rail crossing the body.
                clear = False  # Reject the rail.
                break  # Stop checking.
        if not clear:  # The rail crosses a foreign symbol body.
            continue  # Keep the routed copper.
        straightened[node_name] = [rail]  # Replace the multi-hop copper with the straight rail.
    return straightened  # Return the straightened mapping.


def _build_disconnected_ground_stubs(
    nets: Mapping[str, Sequence[Tuple[int, str, float, float]]],
    records: Sequence[Dict[str, Any]],
    segments_by_net: Mapping[str, Sequence[Tuple[Tuple[float, float], Tuple[float, float]]]],
    grid: float,
    page_width: float,
    page_height: float,
    tolerance: float = 1e-6,
) -> Dict[str, List[Tuple[Tuple[int, str, float, float], Tuple[Tuple[float, float], Tuple[float, float]]]]]:
    """Build one short physical stub per ground pin for local GND symbols."""

    attachments: Dict[str, List[Tuple[Tuple[int, str, float, float], Tuple[Tuple[float, float], Tuple[float, float]]]]] = {}
    ordinary_segments = [
        segment
        for node_name, routed in segments_by_net.items()
        if node_name not in _GROUND_NODE_NAMES
        for segment in routed
    ]
    all_pins = {
        (round(pin[2], 6), round(pin[3], 6))
        for node_pins in nets.values()
        for pin in node_pins
    }
    body_rects = [_record_body_rect(record) for record in records if not record["power"]]
    graphics_owners = set()  # Index records whose body comes from real drawn graphics.
    for index, record in enumerate(records):  # Walk every component record.
        if record["power"]:  # Power symbols attach after routing.
            continue  # Move to the next record.
        short_name = _split_lib_id(record["lib_id"])[1]  # Read the short symbol name.
        if _symbol_body_bounds(record["symbol_node"], short_name, include_pins=False) is not None:  # Detect real drawn bodies.
            graphics_owners.add(index)  # Record the graphics owner.
    stub_length = max(_POWER_STUB_LENGTH, 2.0 * grid)

    for node_name in (name for name in nets if name in _GROUND_NODE_NAMES):
        used_segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        for pin in nets[node_name]:
            record_index, _pin_number, pin_x, pin_y = pin
            owner_rect = _record_body_rect(records[record_index])
            directions = [
                (abs(pin_y - owner_rect[3]), 0, 0.0, 1.0),
                (abs(pin_x - owner_rect[0]), 1, -1.0, 0.0),
                (abs(pin_x - owner_rect[2]), 2, 1.0, 0.0),
                (abs(pin_y - owner_rect[1]), 3, 0.0, -1.0),
            ]
            directions.sort(key=lambda entry: (0 if entry[2:] == (0.0, 1.0) else 1, entry[0], entry[1]))  # Prefer the downward reading direction while keeping the safety search.
            chosen: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None
            owner_graphics = record_index in graphics_owners  # Pin-derived owner boxes never block their own stub.
            for _edge_distance, _priority, direction_x, direction_y in directions:
                endpoint = (pin_x + direction_x * stub_length, pin_y + direction_y * stub_length)
                candidate = ((pin_x, pin_y), endpoint)
                if endpoint[0] < grid or endpoint[1] < grid or endpoint[0] > page_width - grid or endpoint[1] > page_height - grid:
                    continue
                if any(
                    point != (round(pin_x, 6), round(pin_y, 6)) and _point_on_segment_local(point[0], point[1], candidate, _KI_CAD_CONTACT_TOLERANCE)
                    for point in all_pins
                ):
                    continue
                if any(_segments_create_junction(candidate, foreign, _KI_CAD_CONTACT_TOLERANCE) for foreign in ordinary_segments):
                    continue
                if any(_segment_intersects_rect(candidate, body) for body in body_rects if body != owner_rect or owner_graphics):
                    continue
                chosen = candidate
                break
            if chosen is None:  # Harden the fallback with a shrinking multi-direction search before the unconditional downward stub.
                for length_factor in (0.75, 0.5, 0.25, 0.125):  # Shrink the stub length until one direction clears.
                    length = stub_length * length_factor  # Compute the shrunken length.
                    for _edge_distance, _priority, direction_x, direction_y in directions:  # Walk the directions in the biased order.
                        endpoint = (pin_x + direction_x * length, pin_y + direction_y * length)  # Compute the shrunken endpoint.
                        candidate = ((pin_x, pin_y), endpoint)  # Build the shrunken candidate.
                        if endpoint[0] < grid or endpoint[1] < grid or endpoint[0] > page_width - grid or endpoint[1] > page_height - grid:  # Keep stubs inside the page.
                            continue  # Try the next direction.
                        if any(point != (round(pin_x, 6), round(pin_y, 6)) and _point_on_segment_local(point[0], point[1], candidate, _KI_CAD_CONTACT_TOLERANCE) for point in all_pins):  # Avoid running through foreign pins.
                            continue  # Try the next direction.
                        if any(_segments_create_junction(candidate, foreign, _KI_CAD_CONTACT_TOLERANCE) for foreign in ordinary_segments):  # Avoid touching foreign copper.
                            continue  # Try the next direction.
                        if any(_segment_intersects_rect(candidate, body) for body in body_rects if body != owner_rect or owner_graphics):  # Avoid crossing real symbol bodies including the owner's graphics.
                            continue  # Try the next direction.
                        chosen = candidate  # Accept the shrunken safe stub.
                        break  # Stop checking directions.
                    if chosen is not None:  # Stop shrinking after finding a safe stub.
                        break  # Leave the length loop.
            if chosen is None:  # Last resort: keep the historical unconditional downward stub.
                endpoint_y = min(max(grid, pin_y + stub_length), page_height - grid)
                chosen = ((pin_x, pin_y), (pin_x, endpoint_y))
            used_segments.append(chosen)
            attachments.setdefault(node_name, []).append((pin, chosen))
        ordinary_segments.extend(used_segments)
    return attachments


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
        if bounds is not None and (bounds[2] - bounds[0] < 1e-9 or bounds[3] - bounds[1] < 1e-9):  # Graphics-less generic symbols carry degenerate bounds.
            bounds = None  # Fall back to a pin-derived body so collision checks stay meaningful.
        if bounds is None:  # Derive a meaningful body from the symbol's pin extents when graphics are missing.
            pin_local = [record["pins"][pin][:2] for pin in record["pins"]]  # Collect the local pin coordinates.
            if pin_local:  # Require at least one pin to measure the body.
                pin_xs = [point[0] for point in pin_local]  # Collect the pin X coordinates.
                pin_ys = [point[1] for point in pin_local]  # Collect the pin Y coordinates.
                bounds = (  # Build a body that covers every pin plus the standard padding.
                    min(pin_xs) - _SYMBOL_BODY_PADDING, min(pin_ys) - _SYMBOL_BODY_PADDING,
                    max(pin_xs) + _SYMBOL_BODY_PADDING, max(pin_ys) + _SYMBOL_BODY_PADDING,
                )  # Finish the pin-derived bounds.
        record["body_bounds"] = bounds  # Store the body bounds on the record.
        record["text_bounds"] = _symbol_body_bounds(record["symbol_node"], short_name, include_pins=False, combine_sections=True)  # Combine split graphical sections for visible-text collision checks.
        if bounds is None:  # Fall back to a small default body for graphics-less symbols.
            width = height = 2 * _SYMBOL_BODY_PADDING + 1.27  # Use a minimal default body.
        else:  # Size the body from the looked-up graphics bounds.
            width = max(bounds[2] - bounds[0], 1.27) + 2 * _SYMBOL_BODY_PADDING  # Add padding to the measured width.
            height = max(bounds[3] - bounds[1], 1.27) + 2 * _SYMBOL_BODY_PADDING  # Add padding to the measured height.
        x = _PLACEMENT_START_X + (index % 10) * _PLACEMENT_STEP_X  # Initial column position.
        y = _PLACEMENT_Y + (index // 10) * 15.24  # Initial row position.
        pins = [(str(pin_number), local_x, -local_y) for pin_number, (local_x, local_y, _name) in record["pins"].items()]  # Convert pins into screen-space offsets.
        placer.add_component(record["uid"], x, y, width, height, pins)  # Register the component with the placer under its unique placement key.
        for node_index, pin_number in record["pin_map"].items():  # Walk the mapped pins to build springs.
            node_name = record["element"].nodes[node_index]  # Read the netlist node name.
            net_pins.setdefault(node_name, []).append((record["uid"], str(pin_number)))  # Register the spring member.
        index += 1  # Advance the layout index.
    placer.create_springs_from_nets(net_pins)  # Create the star-topology net springs.
    return placer  # Return the prepared placer.


def _compact_placement(
    records: Sequence[Dict[str, Any]],
    grid: float,
    page_width: float,
    page_height: float,
) -> None:
    """Center and uniformly compact a placement as far as body clearance allows."""

    ordinary = [record for record in records if not record["power"]]
    if not ordinary:
        return
    centroid_x = sum(float(record["x"]) for record in ordinary) / len(ordinary)
    centroid_y = sum(float(record["y"]) for record in ordinary) / len(ordinary)
    target_x = round((page_width / 2.0) / grid) * grid
    target_y = round((page_height / 2.0) / grid) * grid
    original = [(float(record["x"]), float(record["y"])) for record in ordinary]
    clearance = max(grid, _SYMBOL_BODY_PADDING)

    for scale_percent in range(35, 101, 5):
        scale = scale_percent / 100.0
        for record, (original_x, original_y) in zip(ordinary, original):
            record["x"] = round((target_x + (original_x - centroid_x) * scale) / grid) * grid
            record["y"] = round((target_y + (original_y - centroid_y) * scale) / grid) * grid
        if _placement_is_clear(ordinary, clearance, page_width, page_height):
            return

    for record, (original_x, original_y) in zip(ordinary, original):
        record["x"] = round((target_x + original_x - centroid_x) / grid) * grid
        record["y"] = round((target_y + original_y - centroid_y) / grid) * grid


def _placement_is_clear(
    records: Sequence[Dict[str, Any]],
    clearance: float,
    page_width: float,
    page_height: float,
) -> bool:
    """Return whether symbol bodies fit on-page with the requested clearance."""

    rects = [_record_body_rect(record) for record in records]
    for rect in rects:
        if rect[0] < clearance or rect[1] < clearance or rect[2] > page_width - clearance or rect[3] > page_height - clearance:
            return False
    for first_index, first in enumerate(rects):
        expanded = (first[0] - clearance, first[1] - clearance, first[2] + clearance, first[3] + clearance)
        if any(_rects_overlap(expanded, second) for second in rects[first_index + 1:]):
            return False
    return True


def _refine_symbol_orientations(
    records: Sequence[Dict[str, Any]],
    grid: float,
    page_width: float,
    page_height: float,
) -> None:
    """Choose quarter-turns that shorten pin-to-peer Manhattan distances."""

    ordinary = [record for record in records if not record["power"]]
    if len(ordinary) < 2:
        return
    clearance = max(grid / 2.0, 0.635)

    def peer_positions(skip_record: Dict[str, Any]) -> Dict[str, List[Tuple[float, float]]]:
        peers: Dict[str, List[Tuple[float, float]]] = {}
        for other in ordinary:
            if other is skip_record:
                continue
            for node_index, pin_number in other["pin_map"].items():
                local_x, local_y, _pin_name = other["pins"][pin_number]
                point = _transform_point(local_x, local_y, other["x"], other["y"], other["angle"], "")
                peers.setdefault(other["element"].nodes[node_index], []).append(point)
        return peers

    for _pass in range(3):
        changed = False
        for record in ordinary:
            peers = peer_positions(record)
            original_angle = float(record["angle"]) % 360.0
            other_rects = [_record_body_rect(other) for other in ordinary if other is not record]
            best_angle = original_angle
            best_cost = float("inf")
            candidates = [original_angle] + [angle for angle in (0.0, 90.0, 180.0, 270.0) if angle != original_angle]
            for candidate_angle in candidates:
                record["angle"] = candidate_angle
                rect = _record_body_rect(record)
                expanded = (rect[0] - clearance, rect[1] - clearance, rect[2] + clearance, rect[3] + clearance)
                if rect[0] < 0.0 or rect[1] < 0.0 or rect[2] > page_width or rect[3] > page_height:
                    continue
                if any(_rects_overlap(expanded, other_rect) for other_rect in other_rects):
                    continue
                cost = 0.0
                connection_count = 0
                for node_index, pin_number in record["pin_map"].items():
                    node_name = record["element"].nodes[node_index]
                    targets = peers.get(node_name, ())
                    if not targets:
                        continue
                    local_x, local_y, _pin_name = record["pins"][pin_number]
                    pin_x, pin_y = _transform_point(local_x, local_y, record["x"], record["y"], candidate_angle, "")
                    target_x = sum(point[0] for point in targets) / len(targets)
                    target_y = sum(point[1] for point in targets) / len(targets)
                    cost += abs(pin_x - target_x) + abs(pin_y - target_y)
                    connection_count += 1
                if connection_count == 0:
                    cost = 0.0 if candidate_angle == original_angle else 1.0
                if cost < best_cost - 1e-9:
                    best_cost = cost
                    best_angle = candidate_angle
            record["angle"] = best_angle
            changed = changed or best_angle != original_angle
        if not changed:
            break


def _refine_flow_orientations(
    records: Sequence[Dict[str, Any]],
    grid: float,
    page_width: float,
    page_height: float,
) -> None:
    """Flip role-consistent passive devices only when copper shortens by 20%."""

    ordinary = [record for record in records if not record["power"]]
    if len(ordinary) < 2:
        return
    roles = classify_flow_roles(records)  # Reuse the flow role classification for angle gating.
    clearance = max(grid / 2.0, 0.635)

    def peer_positions(skip_record: Dict[str, Any]) -> Dict[str, List[Tuple[float, float]]]:
        peers: Dict[str, List[Tuple[float, float]]] = {}
        for other in ordinary:
            if other is skip_record:
                continue
            for node_index, pin_number in other["pin_map"].items():
                local_x, local_y, _pin_name = other["pins"][pin_number]
                point = _transform_point(local_x, local_y, other["x"], other["y"], other["angle"], "")
                peers.setdefault(other["element"].nodes[node_index], []).append(point)
        return peers

    for _pass in range(2):
        changed = False
        for record in ordinary:
            role = roles.get(record["uid"], "passive")
            if role == "active" or role == "source":  # Actives keep their role-template reading direction.
                continue
            allowed = (0.0, 180.0) if role == "series" else ((90.0, 270.0) if role in ("shunt_gnd", "shunt_pwr") else (0.0,))
            original_angle = float(record["angle"]) % 360.0
            candidates = [original_angle] + [angle for angle in allowed if angle != original_angle]
            peers = peer_positions(record)
            other_rects = [_record_body_rect(other) for other in ordinary if other is not record]
            best_angle = original_angle
            best_cost = float("inf")
            original_cost = None
            for candidate_angle in candidates:
                record["angle"] = candidate_angle
                rect = _record_body_rect(record)
                expanded = (rect[0] - clearance, rect[1] - clearance, rect[2] + clearance, rect[3] + clearance)
                if rect[0] < 0.0 or rect[1] < 0.0 or rect[2] > page_width or rect[3] > page_height:
                    continue
                if any(_rects_overlap(expanded, other_rect) for other_rect in other_rects):
                    continue
                cost = 0.0
                connection_count = 0
                for node_index, pin_number in record["pin_map"].items():
                    node_name = record["element"].nodes[node_index]
                    targets = peers.get(node_name, ())
                    if not targets:
                        continue
                    local_x, local_y, _pin_name = record["pins"][pin_number]
                    pin_x, pin_y = _transform_point(local_x, local_y, record["x"], record["y"], candidate_angle, "")
                    target_x = sum(point[0] for point in targets) / len(targets)
                    target_y = sum(point[1] for point in targets) / len(targets)
                    cost += abs(pin_x - target_x) + abs(pin_y - target_y)
                    connection_count += 1
                if connection_count == 0:
                    cost = 0.0 if candidate_angle == original_angle else 1.0
                if candidate_angle == original_angle:
                    original_cost = cost
                if cost < best_cost - 1e-9:
                    best_cost = cost
                    best_angle = candidate_angle
            if best_angle != original_angle and original_cost is not None and best_cost < original_cost * 0.8:
                record["angle"] = best_angle  # Flip only when copper shortens meaningfully.
                changed = True
            else:
                record["angle"] = original_angle  # Keep the deterministic role-template parity otherwise.
        if not changed:
            break


def _legalize_body_overlaps(  # Nudge symbols whose bodies overlap so no symbol sits inside another.
    records: Sequence[Dict[str, Any]],  # Accept the placed component records.
    grid: float,  # Accept the placement grid for deterministic displacement.
    page_width: float,  # Accept the page width bound.
    page_height: float,  # Accept the page height bound.
) -> None:  # Update conflicting record poses in place.
    ordinary = [record for record in records if not record["power"]]  # Power symbols attach after routing.
    placed: List[Tuple[float, float, float, float]] = []  # Track settled body rectangles.
    for record in ordinary:  # Settle records in deterministic source order.
        rect = _record_body_rect(record)  # Read the current body rectangle.
        if not any(_rects_overlap(rect, body) for body in placed):  # Keep collision-free poses.
            placed.append(rect)  # Index the settled body.
            continue  # Move to the next record.
        original_x, original_y = float(record["x"]), float(record["y"])  # Preserve the placed pose for relative search offsets.
        resolved = False  # Track whether a clean nearby pose was found.
        for ring in range(1, 40):  # Search a bounded square spiral around the placed pose.
            offsets = [  # Enumerate the current ring perimeter deterministically.
                (offset_x, offset_y)
                for offset_y in range(-ring, ring + 1)
                for offset_x in range(-ring, ring + 1)
                if max(abs(offset_x), abs(offset_y)) == ring
            ]  # Finish the ring offsets.
            for offset_x, offset_y in offsets:  # Try every candidate on this ring.
                record["x"] = original_x + offset_x * grid  # Shift horizontally on the placement grid.
                record["y"] = original_y + offset_y * grid  # Shift vertically on the placement grid.
                candidate_rect = _record_body_rect(record)  # Resolve the moved body envelope.
                if candidate_rect[0] < grid or candidate_rect[1] < grid or candidate_rect[2] > page_width - grid or candidate_rect[3] > page_height - grid:  # Keep symbols inside the page.
                    continue  # Try the next pose.
                if any(_rects_overlap(candidate_rect, body) for body in placed):  # Preserve body collision freedom.
                    continue  # Try the next pose.
                placed.append(candidate_rect)  # Index the accepted pose.
                resolved = True  # Accept the first collision-free pose.
                break  # Leave the candidate loop.
            if resolved:  # Stop after accepting one pose.
                break  # Leave the ring search.
        if not resolved:  # Preserve the placed pose if the bounded search is exhausted.
            record["x"], record["y"] = original_x, original_y  # Restore the original coordinates.
            placed.append(_record_body_rect(record))  # Index the restored body.


def _separate_foreign_pin_overlaps(  # Move symbols whose pin tips coincide with pins belonging to other nets.
    records: Sequence[Dict[str, Any]],  # Accept the placed component records.
    grid: float,  # Accept the placement grid for deterministic displacement.
    page_width: float,  # Accept the page width bound.
    page_height: float,  # Accept the page height bound.
) -> None:  # Update conflicting record poses in place.
    claimed: Dict[Tuple[float, float], str] = {}  # Map settled pin positions onto their electrical net names.
    ordinary_records = [record for record in records if not record["power"]]  # Power symbols are attached after routing and cannot conflict yet.

    def pin_entries(record: Dict[str, Any]) -> List[Tuple[Tuple[float, float], str]]:  # Resolve one record's absolute used-pin positions and net names.
        entries: List[Tuple[Tuple[float, float], str]] = []  # Collect the position/name pairs.
        for node_index, pin_number in record["pin_map"].items():  # Walk pins used by the source element.
            local_x, local_y, _pin_name = record["pins"][pin_number]  # Read the pin's library geometry.
            absolute_x, absolute_y = _transform_point(local_x, local_y, record["x"], record["y"], record["angle"], "")  # Transform it into schematic space.
            entries.append(((round(absolute_x, 6), round(absolute_y, 6)), record["element"].nodes[node_index]))  # Store serializer-stable coordinates.
        return entries  # Return the used pins.

    def has_foreign_overlap(entries: Sequence[Tuple[Tuple[float, float], str]]) -> bool:  # Detect an already claimed position belonging to another net.
        return any(position in claimed and claimed[position] != node_name for position, node_name in entries)  # Report any electrical conflict.

    for record in ordinary_records:  # Settle records in deterministic source order.
        entries = pin_entries(record)  # Resolve the current pose's pins.
        if has_foreign_overlap(entries):  # Search nearby grid poses when unrelated pin tips touch.
            original_x, original_y = record["x"], record["y"]  # Preserve the optimized pose for relative search offsets.
            other_rects = [_record_body_rect(other) for other in ordinary_records if other is not record]  # Keep the moved symbol clear of every other body.
            resolved = False  # Track whether a clean nearby pose was found.
            for ring in range(1, 65):  # Search a bounded square spiral around the optimized pose.
                offsets = [  # Enumerate the current ring perimeter deterministically.
                    (offset_x, offset_y)
                    for offset_y in range(-ring, ring + 1)
                    for offset_x in range(-ring, ring + 1)
                    if max(abs(offset_x), abs(offset_y)) == ring
                ]  # Finish the ring offsets.
                for offset_x, offset_y in offsets:  # Try every candidate on this ring.
                    record["x"] = original_x + offset_x * grid  # Shift horizontally on the placement grid.
                    record["y"] = original_y + offset_y * grid  # Shift vertically on the placement grid.
                    candidate_rect = _record_body_rect(record)  # Resolve the moved body envelope including pin extents.
                    if candidate_rect[0] < 0.0 or candidate_rect[1] < 0.0 or candidate_rect[2] > page_width or candidate_rect[3] > page_height:  # Keep symbols inside the page.
                        continue  # Try the next pose.
                    if any(_rects_overlap(candidate_rect, other_rect) for other_rect in other_rects):  # Preserve body collision freedom.
                        continue  # Try the next pose.
                    entries = pin_entries(record)  # Resolve pins at the candidate pose.
                    if has_foreign_overlap(entries):  # Reject another foreign-net pin contact.
                        continue  # Try the next pose.
                    resolved = True  # Accept the first collision-free pose.
                    break  # Leave the candidate loop.
                if resolved:  # Stop after accepting one pose.
                    break  # Leave the ring search.
            if not resolved:  # Preserve the optimized pose if the bounded search is exhausted.
                record["x"], record["y"] = original_x, original_y  # Restore the original coordinates.
                entries = pin_entries(record)  # Restore its pin entries for deterministic downstream behavior.
        for position, node_name in entries:  # Claim every settled pin position.
            claimed.setdefault(position, node_name)  # Preserve the first net owner at each point.


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
    if bounds is None and bounds_key != "body_bounds":  # Allow specialized collision bounds to fall back for synthetic or graphics-less records.
        bounds = record.get("body_bounds")  # Reuse the ordinary body measurement when no specialized bound exists.
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
    foreign_segments: Sequence[Tuple[Tuple[float, float], Tuple[float, float]]] = (),  # Accept complete foreign copper for exact junction rejection.
    body_rects: Sequence[Tuple[float, float, float, float]] = (),  # Accept symbol bodies that exit lanes must avoid.
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
                    candidate_segments = [((pin_x, pin_y), (candidate, pin_y)), ((candidate, pin_y), (candidate, trunk_y))]  # Build the exact proposed exit geometry.
                    conflict = conflict or any(  # Reject endpoint-on-wire contacts that would electrically merge the nets.
                        _segments_create_junction(candidate_segment, foreign_segment)
                        for candidate_segment in candidate_segments
                        for foreign_segment in foreign_segments
                    )
                    if not conflict and any(_segment_intersects_rect(segment, body) for segment in candidate_segments for body in body_rects):  # Never drop exit lanes through symbol bodies.
                        conflict = True  # Reject the lane.
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
    body_rects: Sequence[Tuple[float, float, float, float]] = (),  # Accept symbol bodies that stub directions must avoid.
) -> None:  # Return nothing.
    if segments_by_net.get(node_name):  # Nets that already carry copper need nothing.
        return  # Leave the mapping unchanged.
    pins = nets.get(node_name, [])  # Read the net pins.
    segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []  # Collect the generated stub segments.
    foreign_segments = [segment for foreign_name, routed_segments in segments_by_net.items() if foreign_name != node_name for segment in routed_segments]  # Collect complete foreign-wire geometry, including segment interiors.
    if pins:  # Prefer a stub that starts exactly at the first pin.
        pin_x, pin_y = pins[0][2], pins[0][3]  # Read the first pin position.
        best_direction: Optional[Tuple[float, float]] = None  # Keep the safest clear direction.
        best_clearance = -1.0  # Track the far-end clearance score.
        for delta_x, delta_y in ((grid, 0.0), (-grid, 0.0), (0.0, grid), (0.0, -grid)):  # Try both horizontal and vertical directions.
            candidate_segments = [  # Build three explicit wire pieces so every emitted endpoint is checked.
                ((pin_x + (step - 1) * delta_x, pin_y + (step - 1) * delta_y), (pin_x + step * delta_x, pin_y + step * delta_y))
                for step in range(1, 4)
            ]  # Finish the candidate stub.
            far_end = candidate_segments[-1][1]  # Read the stub's far endpoint.
            if far_end[0] < grid or far_end[1] < grid or far_end[0] > page_width - grid or far_end[1] > page_height - grid:  # Keep stubs inside the page.
                continue  # Try another direction.
            if any(_segment_intersects_rect(candidate, body) for candidate in candidate_segments for body in body_rects):  # Never draw stubs through symbol bodies.
                continue  # Try another direction.
            foreign_pin_contact = any(  # Prevent a power-net stub from running through an unrelated symbol pin before that net has copper.
                point != (round(pin_x, 6), round(pin_y, 6)) and _point_on_segment_local(point[0], point[1], candidate, _KI_CAD_CONTACT_TOLERANCE)
                for candidate in candidate_segments
                for point in foreign_points
            )
            if foreign_pin_contact or any(_segments_create_junction(candidate, foreign_segment, _KI_CAD_CONTACT_TOLERANCE) for candidate in candidate_segments for foreign_segment in foreign_segments):  # Require every emitted piece to remain electrically isolated from foreign wires and pins.
                continue  # Try another direction.
            clearance = min(  # Score the free space around the far endpoint so stubs point away from symbols.
                [math.hypot(far_end[0] - point[0], far_end[1] - point[1]) for point in foreign_points]  # Distance to foreign pins and corners.
                + [max(0.0, body[0] - far_end[0], far_end[0] - body[2], body[1] - far_end[1], far_end[1] - body[3]) for body in body_rects]  # Distance to every body edge.
                + [math.hypot(far_end[0] - page_width, far_end[1]), math.hypot(far_end[0], far_end[1]), math.hypot(far_end[0], far_end[1] - page_height), math.hypot(far_end[0] - page_width, far_end[1] - page_height)]  # Distance to the page corners.
            )  # Finish the clearance score.
            if clearance > best_clearance:  # Keep the clearest direction.
                best_clearance = clearance  # Update the best score.
                best_direction = (delta_x, delta_y)  # Remember the direction.
        if best_direction is not None:  # Emit the three validated stub steps in the clearest direction.
            for step in range(1, 4):  # Emit three grid steps of wire.
                segments.append(  # Append the already-validated stub segment.
                    ((pin_x + (step - 1) * best_direction[0], pin_y + (step - 1) * best_direction[1]), (pin_x + step * best_direction[0], pin_y + step * best_direction[1]))
                )  # Finish the stub segment append.
    if not segments:  # Fall back to a free-floating stub spot.
        spot = _find_free_stub_spot(router, foreign_points, grid, page_width, page_height, body_rects)  # Search for a clear spot.
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
    tolerance: float = 1e-6,  # Accept the contact tolerance.
) -> bool:  # Return True for a KiCad electrical junction and False for a safe interior crossing.
    return any(_point_on_segment_local(point[0], point[1], second, tolerance) for point in first) or any(_point_on_segment_local(point[0], point[1], first, tolerance) for point in second)  # Endpoint contact on either segment creates connectivity.


def _find_free_stub_spot(  # Find a spot whose three-cell horizontal stub avoids every foreign point.
    router: GridRouter,  # Accept the routing grid.
    foreign_points: Set[Tuple[float, float]],  # Accept the foreign point index.
    grid: float,  # Accept the routing grid.
    page_width: float,  # Accept the page width.
    page_height: float,  # Accept the page height.
    body_rects: Sequence[Tuple[float, float, float, float]] = (),  # Accept symbol bodies that the stub must avoid.
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
            if clear and any(_segment_intersects_rect(((x, y), (x + 3 * grid, y)), body) for body in body_rects):  # Reject stubs drawn through symbol bodies.
                clear = False  # Mark the spot as occupied.
            if clear:  # Accept the first clear spot.
                return x, y  # Return the free spot.
    return 25.4, -20.0  # Return a deterministic far-away fallback spot.


def _attach_symbol_on_net(  # Attach one power or ground symbol onto its net copper.
    record: Dict[str, Any],  # Accept the power or ground record.
    segments: Sequence[Tuple[Tuple[float, float], Tuple[float, float]]],  # Accept the net wire segments.
    placed_bodies: List[Tuple[float, float, float, float]],  # Accept the placed body rectangles.
    grid: float,  # Accept the routing grid.
    foreign_segments: Sequence[Tuple[Tuple[float, float], Tuple[float, float]]] = (),  # Accept other-net copper whose crossings must not become junctions.
    pin_points: Sequence[Tuple[float, float]] = (),  # Accept every symbol pin so attachments never land on another device's pin.
) -> None:  # Return nothing.
    pin_number = sorted(record["pin_map"].values(), key=_pin_sort_key)[0]  # Read the single pin number.
    local_x, local_y, _pin_name = record["pins"][pin_number]  # Read the pin local coordinates.
    occupied_pins = {(round(point[0], 6), round(point[1], 6)) for point in pin_points}  # Index every settled pin position.
    candidates = list(_segment_attachment_candidates(segments, grid))  # Read the ordered attachment candidates.
    if not any((round(point[0], 6), round(point[1], 6)) in occupied_pins for point in candidates) and len(candidates) > 2:  # Without a pin anchoring the wire, interior points keep the historical priority.
        candidates = candidates[2:] + candidates[:2]  # Restore the interior-first order for free-floating wires.

    def _safe_candidates() -> List[Tuple[float, float]]:  # Retain points that are electrically exclusive and pin-free.
        return [
            point for point in candidates
            if not any(_point_on_segment_local(point[0], point[1], foreign_segment) for foreign_segment in foreign_segments)
            and (round(point[0], 6), round(point[1], 6)) not in occupied_pins
        ]  # Finish the safe candidate list.

    safe_candidates = _safe_candidates()  # Precompute the electrically safe candidate points.
    for point in safe_candidates:  # Walk the candidate attachment points.
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
    fallback_point = safe_candidates[0] if safe_candidates else candidates[0]  # Prefer electrical isolation over body clearance in the fallback.
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
            candidates.append((low, y))  # Prefer the span start so symbols terminate wires like hand-drawn schematics.
            candidates.append((high, y))  # Prefer the span end so symbols terminate wires like hand-drawn schematics.
            x = low + grid  # Start from the first interior grid point.
            while x < high - 1e-9:  # Walk interior grid points.
                candidates.append((x, y))  # Append the interior candidate.
                x += grid  # Advance to the next grid point.
        else:  # Handle vertical segments.
            x = segment[0][0]  # Read the fixed X coordinate.
            low, high = min(segment[0][1], segment[1][1]), max(segment[0][1], segment[1][1])  # Read the Y span.
            candidates.append((x, low))  # Prefer the span start so symbols terminate wires like hand-drawn schematics.
            candidates.append((x, high))  # Prefer the span end so symbols terminate wires like hand-drawn schematics.
            y = low + grid  # Start from the first interior grid point.
            while y < high - 1e-9:  # Walk interior grid points.
                candidates.append((x, y))  # Append the interior candidate.
                y += grid  # Advance to the next grid point.
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


def _subcircuit_round_trips(element: ParsedElement, symbol_node: SExp) -> bool:  # Decide whether a resolved symbol will re-emit an X device as a subcircuit call.
    if element.prefix != "X":  # Non-subcircuit devices use their natural device class.
        return True  # Return True for ordinary device resolution.
    if str(element.tokens[0]).upper().startswith("XU"):  # XU-named devices become U references that the reverse converter re-emits as X.
        return True  # Accept the symbol because the reference prefix guarantees subcircuit emission.
    sim_device = str(_collect_properties(symbol_node).get("Sim.Device", "")).upper()  # Read the resolved symbol simulation class.
    return sim_device in {"SPICE", "SUBCKT"}  # Accept symbols whose simulation class forces subcircuit emission.


def _build_generic_subcircuit_symbol(subcircuit_name: str, node_count: int) -> Tuple[bool, Tuple[str, SExp]]:  # Build a self-contained generic symbol for an unresolvable subcircuit.
    sanitized = re.sub(r"[^A-Za-z0-9_]+", "_", subcircuit_name).strip("_")  # Normalize the subcircuit name into a safe identifier fragment.
    if not sanitized:  # Fall back for empty or symbol-only subcircuit names.
        sanitized = "SUBCKT"  # Use a neutral generic stem.
    symbol_name = f"SUBCKT_{sanitized}_{node_count}"  # Derive a unique symbol stem from the name and pin count.
    lib_id = f"Simulation_SPICE:{symbol_name}"  # Give every generic subcircuit its own library identifier so instances resolve their own embedded symbol.
    sub_symbol_name = f"{symbol_name}_1_1"  # Build the standard unit/body-style sub-symbol name.

    def _property_node(key: str, value: str, hide: bool) -> SExp:  # Build one generic library property node.
        effects_children: List[SExp] = [  # Start the text effects children.
            SExp(name="font", children=[SExp(name="size", children=[SExp(value=1.27), SExp(value=1.27)])]),  # Font size.
        ]  # Finish the base effects children.
        if hide:  # Hide nonessential fields.
            effects_children.append(SExp(name="hide", children=[SExp(value="yes")]))  # Mark the field hidden.
        return SExp(name="property", children=[  # Build the property node.
            SExp(value=key, _originally_quoted=True),  # Property key.
            SExp(value=value, _originally_quoted=True),  # Property value.
            SExp(name="at", children=[SExp(value=0), SExp(value=0), SExp(value=0)]),  # Default position.
            SExp(name="effects", children=effects_children),  # Text effects.
        ])  # Return the assembled property node.

    def _pin_node(pin_number: int, pin_y: float) -> SExp:  # Build one generic pin node.
        effects = SExp(name="effects", children=[SExp(name="font", children=[SExp(name="size", children=[SExp(value=1.27), SExp(value=1.27)])])])  # Font effects.
        return SExp(name="pin", children=[  # Build the pin node.
            SExp(value="passive"),  # Passive electrical type.
            SExp(value="line"),  # Line graphical style.
            SExp(name="at", children=[SExp(value=5.08), SExp(value=round(pin_y, 4)), SExp(value=180)]),  # Connection point on the symbol right edge.
            SExp(name="length", children=[SExp(value=2.54)]),  # Pin length.
            SExp(name="name", children=[SExp(value=f"P{pin_number}", _originally_quoted=True), effects]),  # Pin name.
            SExp(name="number", children=[SExp(value=str(pin_number), _originally_quoted=True), effects]),  # Pin number.
        ])  # Return the assembled pin node.

    pin_nodes: List[SExp] = []  # Collect the generated pin nodes.
    for pin_number in range(1, node_count + 1):  # Walk the required node positions.
        pin_y = (pin_number - (node_count + 1) / 2.0) * 2.54  # Stack the pins vertically around the origin.
        pin_nodes.append(_pin_node(pin_number, pin_y))  # Append the generated pin.
    symbol_children: List[SExp] = [  # Start the generic symbol children.
        SExp(value=lib_id),  # Leading library-identifier atom.
        SExp(name="pin_numbers", children=[SExp(name="hide", children=[SExp(value="yes")])]),  # Hide pin numbers.
        SExp(name="pin_names", children=[SExp(name="offset", children=[SExp(value=0)]), SExp(name="hide", children=[SExp(value="yes")])]),  # Hide pin names.
        SExp(name="exclude_from_sim", children=[SExp(value="no")]),  # Simulation inclusion flag.
        SExp(name="in_bom", children=[SExp(value="yes")]),  # Bill-of-materials flag.
        SExp(name="on_board", children=[SExp(value="yes")]),  # Board export flag.
        _property_node("Reference", "U?", False),  # Reference prefix property.
        _property_node("Value", subcircuit_name, False),  # Subcircuit name property.
        _property_node("Footprint", "", True),  # Footprint property.
        _property_node("Datasheet", "~", True),  # Datasheet property.
        _property_node("Sim.Device", "SUBCKT", True),  # Simulation device class.
        _property_node("Sim.Name", subcircuit_name, True),  # Simulation model name.
        SExp(name="symbol", children=[SExp(value=sub_symbol_name)] + pin_nodes),  # The unit sub-symbol carrying the pins.
    ]  # Finish the symbol children.
    symbol_node = SExp(name="symbol", children=symbol_children)  # Build the generic symbol node.
    return True, (lib_id, symbol_node)  # Return the generated generic symbol.


def _symbol_body_bounds(symbol_node: SExp, short_name: str, include_pins: bool = True, combine_sections: bool = False) -> Optional[Tuple[float, float, float, float]]:  # Look one symbol's body bounds up from its graphics.
    if combine_sections:  # Text avoidance must account for KiCad's separately stored common and unit graphics.
        accepted_prefixes = (f"{short_name}_0_", f"{short_name}_1_")  # Match common body sections and unit-one sections.
        graphics_sections = [sub_symbol for sub_symbol in symbol_node.find_children("symbol") if (_first_atom_value(sub_symbol) is not None and str(_first_atom_value(sub_symbol)).startswith(accepted_prefixes))]  # Collect every rendered section.
        graphics_node = SExp(name="combined_symbol_graphics", children=[child for section in graphics_sections for child in section.children]) if graphics_sections else symbol_node  # Flatten matching sections or use a flat-symbol fallback.
    else:  # Preserve the established placement and routing geometry behavior.
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
        common_prefix = f"{short_name}_0_"  # KiCad stores shared graphics in the unit-zero sections.
        unit_sections = [  # Merge the common body graphics with the chosen unit graphics.
            sub_symbol for sub_symbol in symbol_node.find_children("symbol")
            if _first_atom_value(sub_symbol) is not None and str(_first_atom_value(sub_symbol)).startswith(common_prefix)
        ]  # Finish the common-section list.
        if chosen is not None:  # Include the resolved unit graphics.
            unit_sections.append(chosen)  # Append the unit section.
        graphics_node = SExp(name="combined_symbol_graphics", children=[child for section in unit_sections for child in section.children]) if unit_sections else symbol_node  # Flatten matching sections or use a flat-symbol fallback.
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


def _point_on_segment_local(px: float, py: float, segment: Tuple[Tuple[float, float], Tuple[float, float]], tolerance: float = 1e-6) -> bool:  # Decide whether a point lies on one segment.
    (start_x, start_y), (end_x, end_y) = segment  # Unpack the segment endpoints.
    if px < min(start_x, end_x) - tolerance or px > max(start_x, end_x) + tolerance:  # Reject points outside the X span.
        return False  # Return False for non-overlapping X coordinates.
    if py < min(start_y, end_y) - tolerance or py > max(start_y, end_y) + tolerance:  # Reject points outside the Y span.
        return False  # Return False for non-overlapping Y coordinates.
    delta_x, delta_y = end_x - start_x, end_y - start_y  # Compute the segment extent.
    length_squared = delta_x * delta_x + delta_y * delta_y  # Compute the squared segment length.
    if length_squared == 0.0:  # Handle degenerate zero-length segments.
        return abs(px - start_x) <= tolerance and abs(py - start_y) <= tolerance  # Return the point-equality check.
    projection = ((px - start_x) * delta_x + (py - start_y) * delta_y) / length_squared  # Project the point onto the segment.
    if projection < -1e-9 or projection > 1.0 + 1e-9:  # Reject projections beyond the segment endpoints.
        return False  # Return False for out-of-range projections.
    closest_x = start_x + projection * delta_x  # Compute the closest X coordinate on the segment.
    closest_y = start_y + projection * delta_y  # Compute the closest Y coordinate on the segment.
    return abs(px - closest_x) <= tolerance and abs(py - closest_y) <= tolerance  # Return the distance check.


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


def _build_no_connect_nodes(  # Build one no-connect marker per exempt singleton NC pin.
    root_uuid: str,  # Accept the schematic root UUID for deterministic identifiers.
    positions: Sequence[Tuple[float, float]],  # Accept the NC pin positions in schematic space.
) -> List[SExp]:  # Return the generated no-connect nodes.
    no_connect_nodes: List[SExp] = []  # Collect the generated no-connect nodes.
    for counter, (pin_x, pin_y) in enumerate(positions, start=1):  # Walk the NC pin positions deterministically.
        no_connect_nodes.append(  # Append the generated no-connect node.
            SExp(name="no_connect", children=[  # Build the no-connect list node.
                SExp(name="at", children=[SExp(value=pin_x), SExp(value=pin_y)]),  # Marker position on the exempt pin.
                SExp(name="uuid", children=[SExp(value=_derive_uuid(root_uuid, f"no_connect/{counter}"))]),  # Marker identifier.
            ])  # Finish the no-connect node.
        )  # Append the no-connect node to the list.
    return no_connect_nodes  # Return the generated no-connect nodes.


def _measure_text_bounds(text: str, font_size: float = _TEXT_FONT_SIZE) -> Tuple[float, float]:
    """Measure the KiCad stroke-font bounding box of one text string in mm.

    The width sums the per-character glyph advances measured from the KiCad 10
    stroke font plus the constant inter-character gap, matching the bounding
    boxes KiCad itself computes for schematic text. The height covers the full
    font box: the cap height plus the descender area below the baseline.
    Returns ``(width, height)`` in millimetres.
    """

    characters = str(text)
    width_fraction = sum(_GLYPH_ADVANCES.get(character, _DEFAULT_GLYPH_ADVANCE) for character in characters)
    if characters:
        width_fraction += _TEXT_INTER_CHARACTER_GAP * (len(characters) - 1)
    return width_fraction * font_size, _TEXT_BOX_HEIGHT_FRACTION * font_size


def _text_width(text: str, font_size: float = _TEXT_FONT_SIZE) -> float:
    """Measure the KiCad stroke-font bounding width of one text string."""

    return _measure_text_bounds(text, font_size)[0]


def _expand_rect(rect: Tuple[float, float, float, float], clearance: float) -> Tuple[float, float, float, float]:
    return rect[0] - clearance, rect[1] - clearance, rect[2] + clearance, rect[3] + clearance


def _rects_overlap(first: Tuple[float, float, float, float], second: Tuple[float, float, float, float]) -> bool:
    """Return whether two rectangles have overlapping interiors."""

    return first[0] < second[2] and first[2] > second[0] and first[1] < second[3] and first[3] > second[1]


def _segment_intersects_rect(
    segment: Tuple[Tuple[float, float], Tuple[float, float]],
    rect: Tuple[float, float, float, float],
) -> bool:
    """Conservatively test a routed segment against a rectangle interior."""

    (start_x, start_y), (end_x, end_y) = segment
    low_x, high_x = min(start_x, end_x), max(start_x, end_x)
    low_y, high_y = min(start_y, end_y), max(start_y, end_y)
    epsilon = 1e-9  # Boundary touches (pins on body edges) are legal contacts, not crossings.
    if abs(start_y - end_y) < 1e-9:
        return rect[1] + epsilon < start_y < rect[3] - epsilon and low_x + epsilon < rect[2] and high_x - epsilon > rect[0]
    if abs(start_x - end_x) < 1e-9:
        return rect[0] + epsilon < start_x < rect[2] - epsilon and low_y < rect[3] - epsilon and high_y > rect[1] + epsilon
    return low_x + epsilon < rect[2] and high_x - epsilon > rect[0] and low_y < rect[3] - epsilon and high_y > rect[1] + epsilon


def _text_rect_is_clear(
    rect: Tuple[float, float, float, float],
    body_rects: Sequence[Tuple[float, float, float, float]],
    wire_segments: Sequence[Tuple[Tuple[float, float], Tuple[float, float]]],
    occupied_text: Sequence[Tuple[float, float, float, float]],
) -> bool:
    padded = _expand_rect(rect, _TEXT_CLEARANCE)
    if any(_rects_overlap(padded, body) for body in body_rects):
        return False
    if any(_segment_intersects_rect(segment, padded) for segment in wire_segments):
        return False
    return not any(_rects_overlap(padded, other) for other in occupied_text)


def _property_text_candidates(
    body: Tuple[float, float, float, float],
    width: float,
    height: float,
    grid: float,
) -> Sequence[Tuple[float, float, str, Tuple[float, float, float, float]]]:
    """Generate expanding field positions around one symbol body."""

    left, top, right, bottom = body
    center_x, center_y = (left + right) / 2.0, (top + bottom) / 2.0
    candidates: List[Tuple[float, float, str, Tuple[float, float, float, float]]] = []
    step = max(grid, height + _TEXT_CLEARANCE)
    for ring in range(_TEXT_SEARCH_RINGS):
        distance = _TEXT_CLEARANCE + height / 2.0 + ring * step
        top_y, bottom_y = top - distance, bottom + distance
        candidates.extend([
            (left, top_y, "left", (left, top_y - height / 2.0, left + width, top_y + height / 2.0)),
            (right, top_y, "right", (right - width, top_y - height / 2.0, right, top_y + height / 2.0)),
            (left, bottom_y, "left", (left, bottom_y - height / 2.0, left + width, bottom_y + height / 2.0)),
            (right, bottom_y, "right", (right - width, bottom_y - height / 2.0, right, bottom_y + height / 2.0)),
            (right + distance, center_y, "left", (right + distance, center_y - height / 2.0, right + distance + width, center_y + height / 2.0)),
            (left - distance, center_y, "right", (left - distance - width, center_y - height / 2.0, left - distance, center_y + height / 2.0)),
        ])
    return candidates


def _label_text_candidates(
    segments: Sequence[Tuple[Tuple[float, float], Tuple[float, float]]],
    width: float,
    height: float,
    pin_points: Sequence[Tuple[float, float]] = (),
) -> Sequence[Tuple[Tuple[float, float], List[str], Tuple[float, float, float, float]]]:
    """Generate label glyph boxes offset from, but anchored to, net copper."""

    candidates: List[Tuple[Tuple[float, float], List[str], Tuple[float, float, float, float]]] = []
    pin_keys = {(round(point[0], 6), round(point[1], 6)) for point in pin_points}  # Index every settled pin position.
    endpoint_usage: Dict[Tuple[float, float], int] = {}  # Count how many own segments share each endpoint.
    for (start_x, start_y), (end_x, end_y) in segments:  # Index the net's own segment endpoints.
        endpoint_usage[(round(start_x, 6), round(start_y, 6))] = endpoint_usage.get((round(start_x, 6), round(start_y, 6)), 0) + 1  # Count the start.
        endpoint_usage[(round(end_x, 6), round(end_y, 6))] = endpoint_usage.get((round(end_x, 6), round(end_y, 6)), 0) + 1  # Count the end.

    def _free_end_count(segment: Tuple[Tuple[float, float], Tuple[float, float]]) -> int:  # Count the segment ends that are neither pins nor shared joints.
        free = 0  # Count the free ends.
        for end in ((segment[0][0], segment[0][1]), (segment[1][0], segment[1][1])):  # Walk the two ends.
            key = (round(end[0], 6), round(end[1], 6))  # Build the endpoint key.
            if key not in pin_keys and endpoint_usage.get(key, 0) <= 1:  # A wire end that is neither a pin nor a shared joint.
                free += 1  # Count the free end.
        return free  # Return the free-end count.

    ordered = sorted(segments, key=lambda segment: (-_free_end_count(segment), -math.hypot(segment[1][0] - segment[0][0], segment[1][1] - segment[0][1])))
    for (start_x, start_y), (end_x, end_y) in ordered:
        start_is_pin = (round(start_x, 6), round(start_y, 6)) in pin_keys  # Detect a pin at the segment start.
        end_is_pin = (round(end_x, 6), round(end_y, 6)) in pin_keys  # Detect a pin at the segment end.
        fractions: List[float] = []  # Prefer free wire ends so labels terminate stubs like hand-drawn schematics.
        if not end_is_pin:
            fractions.append(1.0)  # Anchor at the free end first.
        if not start_is_pin:
            fractions.append(0.0)  # Anchor at the free start next.
        fractions.extend([0.5, 0.25, 0.75])  # Then the interior fractions.
        if end_is_pin:
            fractions.append(1.0)  # Keep pin ends last.
        if start_is_pin:
            fractions.append(0.0)  # Keep pin starts last.
        seen_fractions: List[float] = []  # Deduplicate fractions per segment.
        for fraction in fractions:
            if fraction in seen_fractions:
                continue
            seen_fractions.append(fraction)
            anchor_x = start_x + (end_x - start_x) * fraction
            anchor_y = start_y + (end_y - start_y) * fraction
            anchor = (anchor_x, anchor_y)
            if abs(start_y - end_y) < 1e-9:
                candidates.extend([
                    (anchor, ["left", "bottom"], (anchor_x, anchor_y - _TEXT_CLEARANCE - height, anchor_x + width, anchor_y - _TEXT_CLEARANCE)),
                    (anchor, ["right", "bottom"], (anchor_x - width, anchor_y - _TEXT_CLEARANCE - height, anchor_x, anchor_y - _TEXT_CLEARANCE)),
                    (anchor, ["left", "top"], (anchor_x, anchor_y + _TEXT_CLEARANCE, anchor_x + width, anchor_y + _TEXT_CLEARANCE + height)),
                    (anchor, ["right", "top"], (anchor_x - width, anchor_y + _TEXT_CLEARANCE, anchor_x, anchor_y + _TEXT_CLEARANCE + height)),
                ])
            elif abs(start_x - end_x) < 1e-9:
                candidates.extend([
                    (anchor, ["left"], (anchor_x + _TEXT_CLEARANCE, anchor_y - height / 2.0, anchor_x + _TEXT_CLEARANCE + width, anchor_y + height / 2.0)),
                    (anchor, ["right"], (anchor_x - _TEXT_CLEARANCE - width, anchor_y - height / 2.0, anchor_x - _TEXT_CLEARANCE, anchor_y + height / 2.0)),
                ])
    return candidates


def _layout_visible_text(
    records: Sequence[Dict[str, Any]],
    net_order: Sequence[str],
    segments_by_net: Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]],
    lead_stubs_by_net: Mapping[str, Sequence[Tuple[Tuple[float, float], Tuple[float, float]]]],
    grid: float,
    page_width: float,
    page_height: float,
    singleton_pins: Optional[Mapping[str, Tuple[float, float]]] = None,
) -> Dict[str, Tuple[Tuple[float, float], List[str], bool]]:
    """Place every visible field and label without graphical overlap."""

    text_body_rects = [_record_body_rect(record, "text_bounds") for record in records]
    wire_segments_by_net = {
        name: list(lead_stubs_by_net.get(name, ())) + list(segments_by_net.get(name, ()))
        for name in net_order
    }
    wire_segments = [segment for segments in wire_segments_by_net.values() for segment in segments]
    occupied_text: List[Tuple[float, float, float, float]] = []
    for record in records:
        record["property_layout"] = {}
        visible_fields = [("Value", str(record["value"]))]
        if not record["power"]:
            visible_fields.insert(0, ("Reference", str(record["reference"])))
        body = _record_body_rect(record, "text_bounds")
        for key, value in visible_fields:
            width, height = _measure_text_bounds(value)
            chosen = None
            for anchor_x, anchor_y, justification, rect in _property_text_candidates(body, width, height, grid):
                if rect[0] < 0.0 or rect[1] < 0.0 or rect[2] > page_width or rect[3] > page_height:
                    continue
                if _text_rect_is_clear(rect, text_body_rects, wire_segments, occupied_text):
                    chosen = (anchor_x, anchor_y, justification, rect)
                    break
            if chosen is None:
                fallback_index = 1
                while chosen is None:
                    fallback_y = page_height + fallback_index * (height + 2 * _TEXT_CLEARANCE)
                    fallback_rect = (0.0, fallback_y - height / 2.0, width, fallback_y + height / 2.0)
                    if _text_rect_is_clear(fallback_rect, text_body_rects, wire_segments, occupied_text):
                        chosen = (0.0, fallback_y, "left", fallback_rect)
                    fallback_index += 1
            record["property_layout"][key] = chosen[:3]
            occupied_text.append(chosen[3])

    label_layout: Dict[str, Tuple[Tuple[float, float], List[str], bool]] = {}
    label_pin_points = [  # Index every settled pin so labels anchor on free wire ends.
        (pin_x, pin_y) for record in records for pin_x, pin_y in record.get("pin_positions", {}).values()
    ]  # Finish the label pin-point list.
    for node_name in net_order:
        if node_name in _GROUND_NODE_NAMES or _is_nc_net(node_name):
            continue
        own_segments = wire_segments_by_net.get(node_name, [])
        if not own_segments:  # Singleton label nets anchor their label directly on the single pin.
            singleton_pin = (singleton_pins or {}).get(node_name)
            if singleton_pin is None:
                continue
            width = _text_width(node_name)
            anchor_x, anchor_y = singleton_pin  # Read the pin position.
            singleton_candidates = [  # Build the same four offset boxes around the pin anchor.
                ((anchor_x, anchor_y), ["left", "bottom"], (anchor_x, anchor_y - _TEXT_CLEARANCE - _TEXT_BOUND_HEIGHT, anchor_x + width, anchor_y - _TEXT_CLEARANCE)),
                ((anchor_x, anchor_y), ["right", "bottom"], (anchor_x - width, anchor_y - _TEXT_CLEARANCE - _TEXT_BOUND_HEIGHT, anchor_x, anchor_y - _TEXT_CLEARANCE)),
                ((anchor_x, anchor_y), ["left", "top"], (anchor_x, anchor_y + _TEXT_CLEARANCE, anchor_x + width, anchor_y + _TEXT_CLEARANCE + _TEXT_BOUND_HEIGHT)),
                ((anchor_x, anchor_y), ["right", "top"], (anchor_x - width, anchor_y + _TEXT_CLEARANCE, anchor_x, anchor_y + _TEXT_CLEARANCE + _TEXT_BOUND_HEIGHT)),
            ]  # Finish the singleton anchor candidates.
            chosen_label = None  # Track the first clear singleton anchor.
            for anchor, justification, rect in singleton_candidates:  # Walk the anchor candidates.
                if _text_rect_is_clear(rect, text_body_rects, wire_segments, occupied_text):  # Require a collision-free text box.
                    chosen_label = (anchor, justification, rect)  # Accept the clear anchor.
                    break  # Stop after the first clear candidate.
            if chosen_label is None:  # Keep the label hidden on the pin when the surroundings are crowded.
                label_layout[node_name] = (singleton_pin, [], True)
                continue
            label_layout[node_name] = (chosen_label[0], chosen_label[1], False)
            occupied_text.append(chosen_label[2])
            continue
        width = _text_width(node_name)
        chosen_label = None
        foreign_label_segments = [segment for other_name, segments in wire_segments_by_net.items() if other_name != node_name for segment in segments]
        for anchor, justification, rect in _label_text_candidates(own_segments, width, _TEXT_BOUND_HEIGHT, label_pin_points):
            if any(_point_on_segment_local(anchor[0], anchor[1], segment) for segment in foreign_label_segments):
                continue
            if _text_rect_is_clear(rect, text_body_rects, wire_segments, occupied_text):
                chosen_label = (anchor, justification, rect)
                break
        if chosen_label is None:
            hidden_point = _exclusive_label_point(wire_segments_by_net[node_name], foreign_label_segments)
            if hidden_point is not None:
                label_layout[node_name] = (hidden_point, [], True)
            continue
        label_layout[node_name] = (chosen_label[0], chosen_label[1], False)
        occupied_text.append(chosen_label[2])
    return label_layout


def _exclusive_label_point(
    own_segments: Sequence[Tuple[Tuple[float, float], Tuple[float, float]]],
    foreign_segments: Sequence[Tuple[Tuple[float, float], Tuple[float, float]]],
) -> Optional[Tuple[float, float]]:
    """Choose a point on one net's copper that is not also a foreign-net crossing."""

    ordered = sorted(own_segments, key=lambda segment: -math.hypot(segment[1][0] - segment[0][0], segment[1][1] - segment[0][1]))
    for segment in ordered:
        for fraction in (0.5, 0.25, 0.75, 0.125, 0.875, 0.0, 1.0):
            point = (
                segment[0][0] + (segment[1][0] - segment[0][0]) * fraction,
                segment[0][1] + (segment[1][1] - segment[0][1]) * fraction,
            )
            if not any(_point_on_segment_local(point[0], point[1], foreign) for foreign in foreign_segments):
                return point
    return None


def _build_label_nodes(  # Build label nodes on every non-ground net's copper.
    root_uuid: str,  # Accept the schematic root UUID for deterministic identifiers.
    net_order: Sequence[str],  # Accept the net ordering.
    segments_by_net: Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]],  # Accept the routed segments.
    label_layout: Optional[Mapping[str, Tuple[Tuple[float, float], Sequence[str], bool]]] = None,  # Accept label anchors, justification, and visibility.
) -> List[SExp]:  # Return the generated label nodes.
    label_nodes: List[SExp] = []  # Collect the generated label nodes.
    label_counter = 0  # Count labels for deterministic identifiers.
    for node_name in net_order:  # Walk every net in order.
        if node_name in _GROUND_NODE_NAMES:  # Ground nets carry no labels.
            continue  # Move to the next net.
        if re.fullmatch(r"N\d+", node_name, flags=re.IGNORECASE):  # Auto-numbered internal nets need no label because their pins are physically connected.
            continue  # Avoid clutter while preserving authored semantic net names.
        layout = (label_layout or {}).get(node_name)
        if layout is None:  # Never fall back to an unchecked midpoint that may overlap a symbol or wire.
            continue  # Move to the next net.
        label_point = layout[0]
        justification = list(layout[1])
        hidden = bool(layout[2])
        effects_children = [SExp(name="font", children=[SExp(name="size", children=[SExp(value=_NET_LABEL_FONT_SIZE), SExp(value=_NET_LABEL_FONT_SIZE)])])]
        if justification:
            effects_children.append(SExp(name="justify", children=[SExp(value=value) for value in justification]))
        if hidden:
            effects_children.append(SExp(value="hide", _originally_bare=True))
        label_counter += 1  # Advance the label counter.
        label_nodes.append(  # Append the generated label node.
            SExp(name="label", children=[  # Build the label list node.
                SExp(value=node_name, _originally_quoted=True),  # Label text carries the original node name; KiCad requires a quoted string here.
                SExp(name="at", children=[SExp(value=label_point[0]), SExp(value=label_point[1]), SExp(value=0)]),  # Label position on the wire.
                SExp(name="effects", children=effects_children),  # Label text effects.
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
    for record_index, record in enumerate(records):  # Walk every component record with a fallback identity for generated ground symbols.
        instance_key = record.get("uid", f"generated-{record_index}")  # Keep UUIDs unique for both source and synthesized records.
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
            SExp(name="uuid", children=[SExp(value=_derive_uuid(root_uuid, f"symbol/{instance_key}/{record['reference']}"))]),  # Instance identifier unique even when source references repeat.
        ]  # Finish the base instance children.
        children.extend(_build_instance_properties(record))  # Append the instance property nodes.
        pin_numbers = sorted(record["pin_map"].values(), key=_pin_sort_key)  # Sort the used pin numbers.
        for pin_number in pin_numbers:  # Walk the used pins.
            children.append(  # Append the pin declaration.
                SExp(name="pin", children=[  # Build the pin declaration node.
                    SExp(value=str(pin_number), _originally_quoted=True),  # Pin number atom; KiCad requires a quoted string here.
                    SExp(name="uuid", children=[SExp(value=_derive_uuid(root_uuid, f"symbol/{instance_key}/{record['reference']}/pin/{pin_number}"))]),  # Pin identifier unique to this instance.
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
    if record.get("instance_sim_name"):  # Preserve an explicit model or subcircuit name independently of the display value.
        properties.append(_property_node(record["reference"], "Sim.Name", str(record["instance_sim_name"]), record, visible=False))
    if record.get("instance_sim_params"):  # Preserve authored per-instance parameters over library defaults.
        properties.append(_property_node(record["reference"], "Sim.Params", str(record["instance_sim_params"]), record, visible=False))
    return properties  # Return the generated property nodes.


def _property_node(reference: str, key: str, value: str, record: Dict[str, Any], visible: bool) -> SExp:  # Build one property node for an instance.
    layout = record.get("property_layout", {}).get(key)
    property_x = layout[0] if layout is not None else record["x"]
    property_y = layout[1] if layout is not None else record["y"] + _PROPERTY_STEP
    justification = layout[2] if layout is not None else "left"
    symbol_angle = float(record.get("angle", 0.0)) % 360.0
    property_angle = (-symbol_angle) % 360.0  # KiCad composes field and parent angles, so counter-rotate every parent rotation to keep the collision-checked horizontal text box.
    children: List[SExp] = [  # Start the property children.
        SExp(value=key),  # Property key atom.
        SExp(value=value, _originally_quoted=True),  # Property value atom; KiCad requires a quoted string here.
        SExp(name="at", children=[SExp(value=property_x), SExp(value=property_y), SExp(value=property_angle)]),  # Collision-aware position with horizontal rendered text.
        SExp(name="show_name", children=[SExp(value="no")]),  # Property name visibility flag.
        SExp(name="do_not_autoplace", children=[SExp(value="yes")]),  # Preserve the collision-aware position when KiCad opens or renders the schematic.
    ]  # Finish the base property children.
    if not visible:  # Hide non-visible properties.
        children.append(SExp(name="hide", children=[SExp(value="yes")]))  # Append the hide flag.
    effects_children: List[SExp] = [  # Start the text effects children.
        SExp(name="font", children=[SExp(name="size", children=[SExp(value=1.27), SExp(value=1.27)])]),  # Font size.
    ]  # Finish the base effects children.
    if key in {"Reference", "Value"}:  # Justify the visible fields so the rendered text box equals the collision-checked box.
        effects_children.append(SExp(name="justify", children=[SExp(value=justification)]))  # KiCad names the anchored text-box edge exactly like the layout rectangles, so the justification maps directly.
    children.append(SExp(name="effects", children=effects_children))  # Append the text effects.
    return SExp(name="property", children=children)  # Return the assembled property node.


def _assemble_schematic(  # Assemble the final schematic text from its parts.
    input_path: str,  # Accept the netlist input path for the root UUID.
    settings: Dict[str, Any],  # Accept the normalized settings.
    embedded_symbols: Dict[str, SExp],  # Accept the embedded symbol definitions.
    body_parts: Tuple[List[SExp], List[SExp], List[SExp], List[SExp], Dict[str, SExp]],  # Accept the assembled body nodes.
    simulation_text_nodes: Sequence[SExp],  # Accept source simulator directives and node-free device cards.
) -> str:  # Return the final schematic text.
    root_uuid = _root_uuid(input_path)  # Derive the deterministic schematic root UUID.
    version = settings.get("kicad_sch_version") or datetime.date.today().strftime("%Y%m%d")  # Resolve the format version.
    generator = settings.get("kicad_sch_generator") or "electronics_design"  # Resolve the generator name.
    wire_nodes, no_connect_nodes, label_nodes, symbol_nodes, embedded_extra = body_parts  # Unpack the assembled body nodes.
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
    root_children.extend(no_connect_nodes)  # Append the exempt NC pin markers.
    root_children.extend(simulation_text_nodes)  # Append preserved simulator statements as active schematic text.
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
    annotation_sections: Set[str] = set()
    for child in symbol_node.children:  # Walk the symbol children.
        if not first_atom_replaced and child.is_atom:  # Replace the leading name atom only.
            renamed_children.append(SExp(value=lib_id))  # Emit the full library identifier.
            first_atom_replaced = True  # Mark the name atom as replaced.
        elif not child.is_atom and child.name in {"pin_names", "pin_numbers"}:  # Hide annotations that commonly overlap compact symbol graphics.
            annotation_sections.add(child.name)
            annotation_children = [grandchild for grandchild in child.children if grandchild.name != "hide"]
            annotation_children.append(SExp(name="hide", children=[SExp(value="yes")]))
            renamed_children.append(SExp(name=child.name, children=annotation_children))
        else:  # Keep all remaining children unchanged.
            renamed_children.append(child)  # Preserve the child node.
    insertion_index = 1 if renamed_children and renamed_children[0].is_atom else 0
    missing_annotations: List[SExp] = []
    if "pin_numbers" not in annotation_sections:
        missing_annotations.append(SExp(name="pin_numbers", children=[SExp(name="hide", children=[SExp(value="yes")])]))
    if "pin_names" not in annotation_sections:
        missing_annotations.append(SExp(name="pin_names", children=[SExp(name="offset", children=[SExp(value=0)]), SExp(name="hide", children=[SExp(value="yes")])]))
    renamed_children[insertion_index:insertion_index] = missing_annotations
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
    placement_strategy = settings.get("kicad_placement_strategy", _PLACEMENT_STRATEGY)
    if placement_strategy not in ("physics", "evolutionary", "hybrid", "flow"):
        return False, None
    integer_limits = {
        "kicad_evolutionary_population": (2, None),
        "kicad_evolutionary_generations": (1, None),
        "kicad_placement_seed": (0, None),
        "kicad_routing_trials": (1, 3),
        "kicad_trace_optimization_passes": (0, None),
    }
    for integer_key, (minimum, maximum) in integer_limits.items():
        value = settings.get(integer_key)
        if value is None:
            continue
        try:
            numeric_value = float(value)
            integer_value = int(value)
        except (OverflowError, TypeError, ValueError):
            return False, None
        if not math.isfinite(numeric_value) or numeric_value != integer_value or integer_value < minimum:
            return False, None
        if maximum is not None and integer_value > maximum:
            return False, None
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
