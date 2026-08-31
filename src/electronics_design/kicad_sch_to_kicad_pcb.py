"""KiCad schematic (`.kicad_sch`) to KiCad PCB (`.kicad_pcb`) conversion API."""  # Document the module purpose.

# The conversion rules implemented here turn one validated KiCad schematic into
# one KiCad board file by reusing the MIT-licensed `kicad-tools` project for the
# PCB data model, footprint generation, and grid A* autorouting. The schematic
# is parsed with this package's own validators and vendored S-expression
# parser; connectivity is traced from wires, junctions, labels, no-connect
# markers, and power symbols; every placed component is resolved to a footprint
# from the KiCad footprint libraries under `convert_settings["kicad_path"]`, an
# explicit per-instance `Footprint` property, the configured override mapping,
# a prefix default table, or a dynamically generated fallback footprint. All
# filesystem paths arrive through `convert_settings`; nothing is hard-coded.

from __future__ import annotations  # Postpone annotation evaluation for forward references.

import dataclasses  # Clone and modify kicad-tools net-class routing records.
import importlib  # Import the kicad-tools submodules after sys.path setup.
import math  # Compute placement scaling and overlap legalization geometry.
import os  # Resolve search roots, create parents, and probe filesystem entries.
import sys  # Insert the configured kicad-tools checkout into the import path.
import tempfile  # Host dynamically generated fallback footprint files.
from typing import Any  # Type generic record payloads.
from typing import Dict  # Type settings, net, and pad mappings.
from typing import List  # Type component, segment, and route collections.
from typing import Mapping  # Type the convert_settings parameter.
from typing import Optional  # Type optional parse and lookup results.
from typing import Sequence  # Type immutable component sequences.
from typing import Set  # Type unique reference and net-name collections.
from typing import Tuple  # Type tuple-based helper results.

from .kicad_sch import _parse_sch_text  # Reuse the shared schematic parser wrapper.
from .kicad_sch import _read_text_file_lines  # Reuse the shared encoding-aware file reader.
from .kicad_sch import is_valid_kicad_sch_file  # Validate the schematic before conversion.
from .kicad_sch_to_ltspice_netlist import _LibraryCache  # Reuse the kicad_path symbol-library cache.
from .kicad_sch_to_ltspice_netlist import _UnionFind  # Reuse the shared point-merging structure.
from .kicad_sch_to_ltspice_netlist import _attach_point  # Reuse the shared position-to-net helper.
from .kicad_sch_to_ltspice_netlist import _build_embedded_symbol_index  # Reuse the embedded lib_symbols indexer.
from .kicad_sch_to_ltspice_netlist import _coerce_input_path  # Reuse the shared input-path checker.
from .kicad_sch_to_ltspice_netlist import _coerce_output_path  # Reuse the shared output-path coercer.
from .kicad_sch_to_ltspice_netlist import _collect_junction_positions  # Reuse the shared junction collector.
from .kicad_sch_to_ltspice_netlist import _collect_label_entries  # Reuse the shared label collector.
from .kicad_sch_to_ltspice_netlist import _collect_no_connect_positions  # Reuse the shared no-connect collector.
from .kicad_sch_to_ltspice_netlist import _collect_properties  # Reuse the shared property collector.
from .kicad_sch_to_ltspice_netlist import _collect_wire_segments  # Reuse the shared wire-segment collector.
from .kicad_sch_to_ltspice_netlist import _extract_symbol_pins  # Reuse the shared pin-geometry extractor.
from .kicad_sch_to_ltspice_netlist import _line_from_message  # Reuse the shared line-number extractor.
from .kicad_sch_to_ltspice_netlist import _normalize_convert_settings  # Reuse the shared settings validator.
from .kicad_sch_to_ltspice_netlist import _parse_instance  # Reuse the shared instance parser.
from .kicad_sch_to_ltspice_netlist import _point_key  # Reuse the shared position-key builder.
from .kicad_sch_to_ltspice_netlist import _point_on_segment  # Reuse the shared point-on-wire helper.
from .kicad_sch_to_ltspice_netlist import _split_lib_id  # Reuse the shared library-identifier splitter.
from .kicad_sch_to_ltspice_netlist import _symbol_has_any_pins  # Reuse the shared pin-presence detector.
from .kicad_sch_to_ltspice_netlist import _transform_point  # Reuse the shared pin-position transform.

ConversionResult = Tuple[bool, str, int]  # Represent the public conversion return shape.

_DEFAULT_BOARD_MARGIN = 5.0  # Default content-to-edge margin in mm.
_MIN_BOARD_SIZE = 20.0  # Smallest useful board outline side in mm.
_MAX_PLACEMENT_SCALE = 4.0  # Cap schematic-to-board upscaling for tiny drawings.
_PLACEMENT_SNAP = 0.1  # Snap placed component origins to this mm grid.
_OVERLAP_LEGALIZE_ITERATIONS = 400  # Bounded overlap legalization sweeps.
_DEFAULT_TRACK_WIDTH = 0.25  # Default routed trace width in mm.
_DEFAULT_CLEARANCE = 0.2  # Default trace-to-trace clearance in mm.
_DEFAULT_GRID_RESOLUTION = 0.1  # Default routing grid resolution in mm.
_DEFAULT_VIA_DIAMETER = 0.7  # Default routed via diameter in mm.
_DEFAULT_VIA_DRILL = 0.35  # Default routed via drill in mm.
_DEFAULT_ROUTING_TIMEOUT = 300.0  # Default wall-clock routing budget in seconds.
_DEFAULT_PLACEMENT_STRATEGY = "schematic"  # Mirror the schematic signal-flow layout by default.
_PLACEMENT_STRATEGIES = ("schematic", "rows")  # Supported placement strategy names.
_FOOTPRINT_BODY_PADDING = 0.6  # Conservative body allowance added around pad extents in mm.
_FOOTPRINT_LIBRARY_DIRECTORY = "footprints"  # KiCad install footprint-library directory name.
_FOOTPRINT_LIBRARY_EXTENSION = ".pretty"  # KiCad footprint library directory suffix.
_FOOTPRINT_FILE_EXTENSION = ".kicad_mod"  # KiCad footprint file extension.
_GENERATED_FOOTPRINT_SIZE = "0603"  # Chip size used by the two-pin generated fallback footprint.

_DEFAULT_FOOTPRINT_BY_PREFIX = {  # Built-in reference-prefix to footprint-identifier defaults.
    "R": "Resistor_SMD:R_0603_1608Metric",  # Resistors.
    "C": "Capacitor_SMD:C_0603_1608Metric",  # Capacitors.
    "L": "Inductor_SMD:L_0603_1608Metric",  # Inductors.
    "D": "Diode_SMD:D_SOD-123",  # Diodes.
    "LED": "LED_SMD:LED_0603_1608Metric",  # Light-emitting diodes.
    "Q": "Package_TO_SOT_SMD:SOT-23",  # Transistors.
    "M": "Package_TO_SOT_SMD:SOT-23",  # MOSFETs.
    "F": "Fuse:Fuse_1206_3216Metric",  # Fuses and resettable protectors.
    "FB": "Inductor_SMD:L_0603_1608Metric",  # Ferrite beads.
    "J": "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",  # Generic connectors.
    "SW": "Button_Switch_SMD:SW_SPST_SKQG_WithStem",  # Generic switches.
    "Y": "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",  # Crystals and oscillators.
}  # Finish the default footprint table.

_ROUTABLE_CHIP_PIN_RANGE = (2, 2)  # Pin-count window mapped onto generated chip footprints.
_ROUTABLE_SOT_PIN_RANGE = (3, 6)  # Pin-count window mapped onto generated SOT footprints.
_ROUTABLE_SOIC_PIN_RANGE = (8, 32)  # Pin-count window mapped onto generated SOIC footprints.


def kicad_sch_to_kicad_pcb(  # Convert one KiCad schematic into one KiCad PCB file.
    kicad_sch_filepath: str,  # Accept the KiCad schematic input path.
    kicad_pcb_filepath_out: str,  # Accept the KiCad PCB output path.
    convert_settings: Mapping,  # Accept the conversion configuration mapping.
) -> ConversionResult:  # Return the shared conversion result tuple.
    """Convert one KiCad ``.kicad_sch`` schematic into one KiCad ``.kicad_pcb`` board.

    The conversion parses the schematic with this package's validators, traces
    electrical connectivity from wires, junctions, labels, no-connect markers,
    and power symbols, resolves one footprint per placed component, mirrors the
    schematic placement onto the board (or packs rows), assigns every pad to
    its traced net, and autoroutes every ordinary net with the kicad-tools grid
    A* router. The kicad-tools project is imported normally when installed;
    otherwise the configurable ``convert_settings["kicad_tools_path"]`` checkout
    is placed on the import path.

    Returns ``(True, "OK", 0)`` on success or ``(False, "<error code>", <line>)``
    on failure.
    """
    settings_result = _normalize_pcb_settings(convert_settings)  # Validate the conversion settings first.
    if not settings_result[0]:  # Stop when the settings are unusable.
        return False, settings_result[2], 0  # Return the settings error code with its detail.
    settings = settings_result[1]  # Read the validated and normalized settings.
    kicad_path = settings_result[3]  # Read the validated KiCad library path.
    output_result = _coerce_output_path(kicad_pcb_filepath_out)  # Coerce the output path safely.
    if not output_result[0]:  # Stop when the output path is not path-like.
        return False, "INVALID_OUTPUT_PATH", 0  # Return the required output path error code.
    output_path = output_result[1]  # Read the coerced output path string.
    tools_result = _load_kicad_tools_module(settings)  # Import the kicad-tools project modules.
    if not tools_result[0]:  # Stop when the kicad-tools dependency is unusable.
        return False, tools_result[1], 0  # Return the dependency error code with its detail.
    tool_modules = tools_result[1]  # Read the loaded kicad-tools module bundle.
    input_result = _coerce_input_path(kicad_sch_filepath)  # Coerce and check the input path.
    if not input_result[0]:  # Stop when the input path is unusable.
        return False, "INVALID_KICAD_SCH_FILE", 0  # Return the required schematic file error code.
    input_path = input_result[1]  # Read the coerced input path string.
    validation_result = is_valid_kicad_sch_file(input_path)  # Validate the schematic before conversion.
    if not validation_result[0]:  # Stop when the schematic fails validation.
        return False, "INVALID_KICAD_SCH_FILE", _line_from_message(validation_result[1])  # Return the failing line.
    read_result = _read_text_file_lines(input_path)  # Read the schematic text with encoding detection.
    if not read_result[0]:  # Stop when the schematic cannot be read.
        return False, "KICAD_SCH_READ_ERROR", 0  # Return the required read error code.
    parse_result = _parse_sch_text("\n".join(read_result[1]))  # Parse the schematic into an S-expression tree.
    if not parse_result[0]:  # Stop when the schematic text cannot be parsed.
        return False, "KICAD_SCH_PARSE_ERROR", parse_result[2]  # Return the failing source line.
    root = parse_result[1]  # Read the parsed schematic root node.
    components_result = _collect_components(root, kicad_path)  # Parse instances and resolve symbol definitions.
    if not components_result[0]:  # Stop when instance parsing or symbol resolution fails.
        return False, components_result[2], components_result[3]  # Return the component error code and line.
    components = components_result[1]  # Read the resolved component records.
    nets_result = _trace_nets(root, components)  # Trace connectivity and name every net.
    if not nets_result[0]:  # Stop when connectivity tracing fails.
        return False, nets_result[2], nets_result[3]  # Return the tracing error code and line.
    net_names = nets_result[1]  # Read the pin-root to net-name mapping.
    footprints_result = _resolve_footprints(components, settings, tool_modules)  # Resolve one footprint per component.
    if not footprints_result[0]:  # Stop when a footprint cannot be resolved.
        return False, footprints_result[2], footprints_result[3]  # Return the footprint error code and line.
    placement_result = _place_components(components, settings)  # Compute board-relative component origins.
    if not placement_result[0]:  # Stop when placement fails.
        return False, "PCB_PLACEMENT_FAILED", 0  # Return the placement error code.
    board_width, board_height = placement_result[1]  # Read the resolved board outline size.
    build_result = _build_pcb_file(  # Assemble nets, footprints, and net assignments into one PCB.
        components,  # Pass the placed component records.
        net_names,  # Pass the traced net-name mapping.
        board_width,  # Pass the resolved board width.
        board_height,  # Pass the resolved board height.
        input_path,  # Pass the input path for the title block.
        output_path,  # Pass the intermediate output path.
        settings,  # Pass the validated settings.
        tool_modules,  # Pass the loaded kicad-tools modules.
    )  # Finish the assembly call.
    if not build_result[0]:  # Stop when the board assembly fails.
        return False, build_result[2], build_result[3]  # Return the assembly error code and line.
    if settings["route_traces"]:  # Route copper only when the caller kept routing enabled.
        route_result = _route_board(  # Load the saved board into the kicad-tools autorouter.
            output_path,  # Pass the saved intermediate board path.
            components,  # Pass the placed component records for the pad-net table.
            output_path,  # Rewrite the same board file with routed copper.
            settings,  # Pass the validated settings.
            tool_modules,  # Pass the loaded kicad-tools modules.
        )  # Finish the routing call.
        if not route_result[0]:  # Stop when routing reports a failure.
            return False, route_result[1], 0  # Return the routing error code with its detail.
    final_result = _validate_generated_pcb(output_path, components, tool_modules)  # Validate the finished board.
    if not final_result[0]:  # Stop when the generated board fails validation.
        return False, "INVALID_GENERATED_KICAD_PCB", 0  # Return the generated-board error code.
    return True, "OK", 0  # Return success when the conversion completed.


def _normalize_pcb_settings(convert_settings: Mapping) -> Tuple[bool, Optional[Dict[str, Any]], str, str]:  # Validate the PCB settings and resolve kicad_path.
    base_result = _normalize_convert_settings(convert_settings)  # Reuse the shared kicad_path validation.
    if not base_result[0]:  # Stop when the base settings are unusable.
        return False, None, "INVALID_CONVERT_SETTINGS", ""  # Return the shared settings error.
    settings: Dict[str, Any] = {}  # Collect the normalized PCB settings.
    layers_value = convert_settings.get("kicad_pcb_layers", 2)  # Read the requested copper-layer count.
    if layers_value not in (2, 4):  # Require a supported copper-layer count.
        return False, None, "INVALID_CONVERT_SETTINGS: kicad_pcb_layers must be 2 or 4", ""  # Return the layers error.
    settings["layers"] = int(layers_value)  # Store the validated layer count.
    paper_value = convert_settings.get("kicad_pcb_paper", "A4")  # Read the requested drawing-sheet size.
    if not isinstance(paper_value, str) or paper_value.strip() == "":  # Require a nonempty paper name.
        return False, None, "INVALID_CONVERT_SETTINGS: kicad_pcb_paper must be a nonempty string", ""  # Return the paper error.
    settings["paper"] = paper_value.strip()  # Store the normalized paper name.
    for width_key in ("kicad_pcb_width", "kicad_pcb_height"):  # Validate both explicit outline sizes.
        if width_key not in convert_settings or convert_settings[width_key] is None:  # Allow absent or None sizes.
            settings[width_key] = None  # Store the auto-size marker.
            continue  # Move to the next size key.
        size_result = _positive_float(convert_settings[width_key])  # Validate the numeric size.
        if not size_result[0]:  # Reject non-positive or non-numeric sizes.
            return False, None, f"INVALID_CONVERT_SETTINGS: {width_key} must be a positive number", ""  # Return the size error.
        settings[width_key] = size_result[1]  # Store the validated size.
    margin_result = _positive_float(convert_settings.get("kicad_pcb_margin", _DEFAULT_BOARD_MARGIN))  # Validate the margin.
    if not margin_result[0]:  # Reject an unusable margin.
        return False, None, "INVALID_CONVERT_SETTINGS: kicad_pcb_margin must be a positive number", ""  # Return the margin error.
    settings["margin"] = margin_result[1]  # Store the validated margin.
    title_value = convert_settings.get("kicad_pcb_title", "")  # Read the optional board title.
    if title_value is not None and not isinstance(title_value, str):  # Reject non-string titles.
        return False, None, "INVALID_CONVERT_SETTINGS: kicad_pcb_title must be a string", ""  # Return the title error.
    settings["title"] = title_value  # Store the optional title text.
    strategy_value = convert_settings.get("kicad_pcb_placement_strategy", _DEFAULT_PLACEMENT_STRATEGY)  # Read the placement strategy.
    if not isinstance(strategy_value, str) or strategy_value not in _PLACEMENT_STRATEGIES:  # Reject unknown strategies.
        return False, None, "INVALID_CONVERT_SETTINGS: kicad_pcb_placement_strategy must be one of " + ", ".join(_PLACEMENT_STRATEGIES), ""  # Return the strategy error.
    settings["placement_strategy"] = strategy_value  # Store the validated strategy.
    map_result = _string_mapping(convert_settings.get("kicad_pcb_footprint_map", {}), "kicad_pcb_footprint_map")  # Validate the footprint override mapping.
    if not map_result[0]:  # Reject unusable override mappings.
        return False, None, map_result[1], ""  # Return the mapping error.
    settings["footprint_map"] = map_result[1]  # Store the validated override mapping.
    defaults_result = _string_mapping(convert_settings.get("kicad_pcb_default_footprints", {}), "kicad_pcb_default_footprints")  # Validate the default footprint table.
    if not defaults_result[0]:  # Reject unusable default mappings.
        return False, None, defaults_result[1], ""  # Return the mapping error.
    settings["default_footprints"] = defaults_result[1]  # Store the validated default mapping.
    search_paths_value = convert_settings.get("kicad_pcb_footprint_search_paths", [])  # Read the optional footprint search roots.
    if isinstance(search_paths_value, str):  # Accept one path as a single-entry list.
        search_paths_value = [search_paths_value]  # Normalize the scalar form.
    if not isinstance(search_paths_value, Sequence) or isinstance(search_paths_value, str):  # Require a sequence of paths.
        return False, None, "INVALID_CONVERT_SETTINGS: kicad_pcb_footprint_search_paths must be a sequence of strings", ""  # Return the paths error.
    settings["footprint_search_paths"] = [str(entry) for entry in search_paths_value]  # Store the validated search roots.
    tools_path = convert_settings.get("kicad_tools_path", None)  # Read the optional kicad-tools checkout path.
    if tools_path is not None and not isinstance(tools_path, (str, bytes)):  # Require a path-like kicad-tools path.
        return False, None, "INVALID_CONVERT_SETTINGS: kicad_tools_path must be a path-like string", ""  # Return the tools-path error.
    if isinstance(tools_path, bytes):  # Decode bytes paths through the filesystem encoding.
        tools_path = os.fsdecode(tools_path)  # Convert the bytes path to text.
    settings["kicad_tools_path"] = os.path.expanduser(str(tools_path)) if tools_path else ""  # Store the expanded tools path.
    route_value = convert_settings.get("kicad_pcb_route_traces", True)  # Read the routing toggle.
    if not isinstance(route_value, bool):  # Require a boolean routing toggle.
        return False, None, "INVALID_CONVERT_SETTINGS: kicad_pcb_route_traces must be a boolean", ""  # Return the toggle error.
    settings["route_traces"] = route_value  # Store the validated routing toggle.
    for float_key, default_value in (  # Walk every numeric routing setting.
        ("kicad_pcb_track_width", _DEFAULT_TRACK_WIDTH),  # Trace width.
        ("kicad_pcb_clearance", _DEFAULT_CLEARANCE),  # Trace clearance.
        ("kicad_pcb_grid_resolution", _DEFAULT_GRID_RESOLUTION),  # Routing grid pitch.
        ("kicad_pcb_via_diameter", _DEFAULT_VIA_DIAMETER),  # Via diameter.
        ("kicad_pcb_via_drill", _DEFAULT_VIA_DRILL),  # Via drill.
        ("kicad_pcb_routing_timeout", _DEFAULT_ROUTING_TIMEOUT),  # Wall-clock budget.
    ):  # Finish the numeric setting walk.
        numeric_result = _positive_float(convert_settings.get(float_key, default_value))  # Validate the numeric value.
        if not numeric_result[0]:  # Reject unusable numeric settings.
            return False, None, f"INVALID_CONVERT_SETTINGS: {float_key} must be a positive number", ""  # Return the numeric error.
        settings[float_key] = numeric_result[1]  # Store the validated value.
    skip_value = convert_settings.get("kicad_pcb_skip_route_nets", [])  # Read the plane-net skip list.
    if isinstance(skip_value, str):  # Accept one name as a single-entry list.
        skip_value = [skip_value]  # Normalize the scalar form.
    if not isinstance(skip_value, Sequence) or isinstance(skip_value, str):  # Require a sequence of names.
        return False, None, "INVALID_CONVERT_SETTINGS: kicad_pcb_skip_route_nets must be a sequence of strings", ""  # Return the list error.
    settings["skip_route_nets"] = [str(entry) for entry in skip_value]  # Store the validated skip list.
    complete_value = convert_settings.get("kicad_pcb_require_complete_routing", False)  # Read the complete-routing gate.
    if not isinstance(complete_value, bool):  # Require a boolean gate.
        return False, None, "INVALID_CONVERT_SETTINGS: kicad_pcb_require_complete_routing must be a boolean", ""  # Return the gate error.
    settings["require_complete_routing"] = complete_value  # Store the validated gate.
    settings["_kicad_path"] = base_result[1]  # Store the validated KiCad install path for the footprint search.
    return True, settings, "", base_result[1]  # Return the validated settings bundle.


def _positive_float(value: Any) -> Tuple[bool, Optional[float]]:  # Validate one positive finite number.
    if isinstance(value, bool) or not isinstance(value, (int, float)):  # Reject booleans and non-numbers.
        return False, None  # Signal the validation failure.
    number = float(value)  # Coerce the numeric value to float.
    if not math.isfinite(number) or number <= 0.0:  # Require finite positive magnitudes.
        return False, None  # Signal the validation failure.
    return True, number  # Return the validated float.


def _string_mapping(value: Any, setting_name: str) -> Tuple[bool, Any]:  # Validate one string-to-string mapping setting.
    if not isinstance(value, Mapping):  # Require mapping-like values.
        return False, f"INVALID_CONVERT_SETTINGS: {setting_name} must be a mapping of strings to strings"  # Return the mapping error.
    normalized: Dict[str, str] = {}  # Collect the validated pairs.
    for key, entry in value.items():  # Walk every mapping pair.
        if not isinstance(key, str) or not isinstance(entry, str):  # Require string keys and values.
            return False, f"INVALID_CONVERT_SETTINGS: {setting_name} keys and values must be strings"  # Return the mapping error.
        normalized[key] = entry  # Store the validated pair.
    return True, normalized  # Return the validated mapping.


def _load_kicad_tools_module(settings: Dict[str, Any]) -> Tuple[bool, Any]:  # Import the kicad-tools project modules.
    module = None  # Track the imported top-level module.
    try:  # Prefer an already installed kicad-tools distribution.
        module = importlib.import_module("kicad_tools")  # Attempt the normal import first.
    except ImportError:  # Fall back to the configured checkout path.
        module = None  # Clear the failed import result.
        tools_path = settings.get("kicad_tools_path", "")  # Read the configured checkout path.
        if not tools_path:  # Require a configured path when the import fails.
            return False, "KICAD_TOOLS_UNAVAILABLE: install kicad-tools or set convert_settings['kicad_tools_path']"  # Return the dependency error.
        candidates = [tools_path]  # Probe the configured path directly.
        source_candidate = os.path.join(tools_path, "src")  # Build the conventional src-layout candidate.
        if os.path.isdir(source_candidate):  # Detect the repository checkout layout.
            candidates = [source_candidate, tools_path]  # Prefer the src directory.
        else:  # Handle direct package parents.
            candidates = [tools_path]  # Search only the configured path.
        for candidate in candidates:  # Probe every candidate root.
            expanded = os.path.expanduser(candidate)  # Expand user-relative prefixes.
            if expanded not in sys.path:  # Avoid duplicate import-path entries.
                sys.path.insert(0, expanded)  # Add the candidate to the import path.
        try:  # Retry the import after path setup.
            module = importlib.import_module("kicad_tools")  # Import from the configured checkout.
        except ImportError:  # Report the unusable dependency.
            return False, f"KICAD_TOOLS_UNAVAILABLE: unable to import kicad_tools from '{settings.get('kicad_tools_path', '')}'"  # Return the dependency error.
    try:  # Load every submodule the conversion needs.
        schema_pcb = importlib.import_module("kicad_tools.schema.pcb")  # Import the PCB schema module.
        router_package = importlib.import_module("kicad_tools.router")  # Import the router package.
        router_rules = importlib.import_module("kicad_tools.router.rules")  # Import the default net-class map.
        connectivity_invariant = importlib.import_module("kicad_tools.router.connectivity_invariant")  # Import the pad census helper.
        router_observability = importlib.import_module("kicad_tools.router.observability")  # Import the connectivity validator.
        sexp_file = importlib.import_module("kicad_tools.core.sexp_file")  # Import the footprint file loader.
        generator_chip = importlib.import_module("kicad_tools.library.generators.chip")  # Import the chip generator.
        generator_sot = importlib.import_module("kicad_tools.library.generators.sot")  # Import the SOT generator.
        generator_soic = importlib.import_module("kicad_tools.library.generators.soic")  # Import the SOIC generator.
        generator_header = importlib.import_module("kicad_tools.library.generators.through_hole")  # Import the through-hole generators.
    except Exception as import_error:  # Catch any submodule import failure.
        return False, f"KICAD_TOOLS_UNAVAILABLE: {import_error}"  # Return the dependency error with detail.
    bundle = {  # Assemble the module bundle used by the conversion stages.
        "PCB": schema_pcb.PCB,  # The PCB schema class.
        "Autorouter": router_package.Autorouter,  # The high-level autorouter class.
        "DesignRules": router_package.DesignRules,  # The routing design-rules dataclass.
        "Layer": router_package.Layer,  # The copper-layer enum.
        "default_net_class_map": router_rules.DEFAULT_NET_CLASS_MAP,  # The default net-class routing table.
        "build_multi_pad_net_pads": connectivity_invariant.build_multi_pad_net_pads,  # The router pad census helper.
        "validate_net_connectivity": router_observability.validate_net_connectivity,  # The routed-copper connectivity validator.
        "load_footprint": sexp_file.load_footprint,  # The footprint file loader.
        "create_chip": generator_chip.create_chip,  # The chip footprint generator.
        "create_sot": generator_sot.create_sot,  # The SOT footprint generator.
        "create_soic": generator_soic.create_soic,  # The SOIC footprint generator.
        "create_pin_header": generator_header.create_pin_header,  # The pin-header generator.
    }  # Finish the module bundle.
    return True, bundle  # Return the loaded bundle.


def _collect_components(root: Any, kicad_path: str) -> Tuple[bool, List[Dict[str, Any]], str, int]:  # Parse instances and resolve every symbol definition.
    embedded_index = _build_embedded_symbol_index(root)  # Index the schematic's cached lib_symbols definitions.
    library_cache = _LibraryCache(kicad_path)  # Prepare the lazy kicad_path library cache.
    records: List[Dict[str, Any]] = []  # Collect parsed symbol instances in file order.
    for index, instance_node in enumerate(root.find_children("symbol")):  # Walk every schematic symbol instance.
        parse_result = _parse_instance(instance_node, index)  # Parse the instance header and properties.
        if not parse_result[0]:  # Stop when an instance record is malformed.
            return False, [], parse_result[2], parse_result[3]  # Return the parse error code and line.
        record = parse_result[1]  # Read the parsed instance record.
        symbol_node = embedded_index.get(record["lib_id"])  # Prefer the schematic's embedded lib_symbols definition.
        if symbol_node is None:  # Fall back to the kicad_path libraries when nothing is embedded.
            symbol_node = library_cache.find(record["lib_id"])  # Resolve the symbol in the kicad_path libraries.
        if symbol_node is None:  # Stop when the symbol cannot be resolved anywhere.
            message = f"UNKNOWN_KICAD_SYMBOL: Unable to locate KiCad symbol '{record['lib_id']}' in kicad_path or the schematic's lib_symbols section"  # Explain the failed lookup.
            return False, [], message, record["line"]  # Return the unknown symbol error with the instance line.
        record["power"] = symbol_node.find_child("power") is not None  # Detect power symbols from the library definition.
        record["symbol_props"] = _collect_properties(symbol_node)  # Collect the library symbol properties.
        pins_result = _extract_symbol_pins(symbol_node, record["unit"], record["body_style"], _split_lib_id(str(record["lib_id"]))[1])  # Extract pin geometry.
        if not pins_result[0] and record["power"]:  # Skip power symbols whose libraries carry no pin geometry.
            continue  # Power markers without pins never carry nets.
        if not pins_result[0]:  # Stop when the symbol carries no usable pin graphics.
            if not _symbol_has_any_pins(symbol_node) and not _symbol_has_any_pins(embedded_index.get(record["lib_id"])):  # Skip purely graphical marker symbols.
                continue  # Move to the next instance.
            message = f"UNKNOWN_KICAD_SYMBOL: symbol '{record['lib_id']}' has no pin definitions for unit {record['unit']}"  # Explain the missing graphics.
            return False, [], message, record["line"]  # Return the unknown symbol error with the instance line.
        if record["power"] and str(record["value"]).upper() == "PWR_FLAG":  # Skip power-flag markers that carry no electrical function.
            continue  # Move to the next instance.
        record["symbol_pins"] = pins_result[1]  # Store the resolved pin geometry mapping.
        if not record["pin_numbers"]:  # Fall back to every library pin when the instance lists none.
            record["pin_numbers"] = sorted(record["symbol_pins"].keys(), key=_pin_number_sort_key)  # Use all library pins in numeric order.
        records.append(record)  # Append the finished instance record.
    records = _merge_multi_unit_records(records)  # Combine separately placed units of one physical component.
    return True, records, "", 0  # Return the resolved component records.


def _pin_number_sort_key(pin_number: str) -> Tuple[int, str]:  # Build a numeric-first sort key for one pin number.
    match: Optional[Tuple[str, ...]] = None  # Track the numeric prefix match.
    digits = ""  # Collect the leading digit run.
    for character in pin_number:  # Walk the pin number characters.
        if character.isdigit():  # Extend the leading numeric run.
            digits += character  # Append the digit character.
        else:  # Stop at the first non-digit.
            break  # Stop the numeric prefix scan.
    if digits:  # Sort numeric-leading pins by their numeric value.
        return (0, f"{int(digits):08d}{pin_number}")  # Return the zero-padded numeric key.
    return (1, pin_number)  # Sort non-numeric pins after numeric ones.


def _merge_multi_unit_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:  # Combine units of one physical component into one record.
    units_by_key: Dict[Tuple[str, str], Set[int]] = {}  # Collect unit ordinals for each physical-reference candidate.
    for record in records:  # Inspect every parsed record before merging.
        if record["power"]:  # Power symbols are never multi-unit device calls.
            continue  # Keep these records independent.
        key = (str(record["reference"]).upper(), str(record["lib_id"]))  # Identify one physical part.
        units_by_key.setdefault(key, set()).add(int(record["unit"]))  # Record the unit ordinal used by this placement.
    mergeable_keys = {key for key, units in units_by_key.items() if len(units) > 1}  # Mark references represented by distinct units.
    merged_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}  # Store the combined record for each multi-unit component.
    result: List[Dict[str, Any]] = []  # Preserve original first-occurrence ordering.
    for record in records:  # Walk records in schematic order.
        key = (str(record["reference"]).upper(), str(record["lib_id"]))  # Rebuild the physical-reference key.
        if key not in mergeable_keys:  # Keep single-unit records unchanged.
            result.append(record)  # Append the independent record.
            continue  # Move to the next record.
        if key not in merged_by_key:  # Start the combined record from the first unit.
            merged_by_key[key] = record  # Store the first unit as the combined base.
            result.append(record)  # Append the combined record once.
            continue  # Move to the next record.
        combined = merged_by_key[key]  # Read the existing combined record.
        for pin_number, pin_data in record["symbol_pins"].items():  # Merge every unit pin geometry.
            combined["symbol_pins"].setdefault(pin_number, pin_data)  # Keep the first geometry per pin number.
        for pin_number in record["pin_numbers"]:  # Merge every instance pin number.
            if pin_number not in combined["pin_numbers"]:  # Skip already collected pin numbers.
                combined["pin_numbers"].append(pin_number)  # Append the new pin number.
    return result  # Return the merged component records.


def _trace_nets(root: Any, components: List[Dict[str, Any]]) -> Tuple[bool, Dict[str, str], str, int]:  # Trace connectivity and name every net.
    union_find = _UnionFind()  # Create the point-merging structure for the schematic.
    segments = _collect_wire_segments(root, union_find)  # Collect wire polylines as point-merged segments.
    for junction_x, junction_y in _collect_junction_positions(root):  # Walk every junction record.
        junction_key = _point_key(junction_x, junction_y)  # Register the junction position as a point.
        union_find.add(junction_key)  # Ensure the junction point exists.
        for segment in segments:  # Search for a segment passing through the junction.
            if _point_on_segment(junction_x, junction_y, segment):  # Detect the pass-through segment.
                union_find.union(junction_key, segment[4])  # Join the junction to the segment net.
                break  # Stop after the first passing segment.
    for first_segment in segments:  # Walk every segment as a candidate endpoint owner.
        for second_segment in segments:  # Walk every other segment as a candidate carrier.
            if first_segment is second_segment:  # Skip self comparisons.
                continue  # Move to the next pair.
            if _point_on_segment(first_segment[0], first_segment[1], second_segment):  # Detect a start point resting on another wire.
                union_find.union(first_segment[4], second_segment[4])  # Merge the start point into the carrier net.
            if _point_on_segment(first_segment[2], first_segment[3], second_segment):  # Detect an end point resting on another wire.
                union_find.union(first_segment[5], second_segment[4])  # Merge the end point into the carrier net.
    net_names: Dict[str, str] = {}  # Map net representatives to their assigned names.
    for label_x, label_y, label_text in _collect_label_entries(root):  # Walk every schematic label.
        label_key = _attach_point(union_find, segments, label_x, label_y)  # Attach the label position to its net.
        label_root = union_find.find(label_key)  # Resolve the label net representative.
        if label_text != "" and label_root not in net_names:  # Assign the first label name to each net.
            net_names[label_root] = label_text  # Record the label text as the net name.
    no_connect_keys = {_point_key(x, y) for x, y in _collect_no_connect_positions(root)}  # Index no-connect marker positions.
    for record in components:  # Walk every parsed component including power symbols.
        record["pin_nets"] = {}  # Prepare the pin-to-net mapping for this component.
        for pin_number in record["pin_numbers"]:  # Walk the instance pin numbers.
            pin_data = record["symbol_pins"].get(pin_number)  # Look up the library pin geometry.
            if pin_data is None:  # Skip instance pins that carry no library geometry.
                continue  # Ignore inert pin stubs that are never placed on the schematic.
            pin_x, pin_y, _pin_name = pin_data  # Read the local pin coordinates.
            absolute_x, absolute_y = _transform_point(pin_x, pin_y, float(record["x"]), float(record["y"]), float(record["angle"]), str(record["mirror"]))  # Compute the schematic-space pin position.
            pin_key = _attach_point(union_find, segments, absolute_x, absolute_y)  # Attach the pin to its electrical net.
            if pin_key in no_connect_keys:  # Detect pins marked with a no-connect flag.
                record["pin_nets"][pin_number] = None  # Leave no-connect pins without any PCB net.
                continue  # Move to the next pin.
            pin_root = union_find.find(pin_key)  # Resolve the pin net representative.
            record["pin_nets"][pin_number] = pin_root  # Store the pin net representative.
            if record["power"]:  # Power symbols name their net after their value.
                power_value = record["value"]  # Read the power symbol value.
                if power_value != "" and pin_root not in net_names:  # Assign the first power value as the net name.
                    net_names[pin_root] = power_value  # Record the power net name.
    normalized_net_names: Dict[str, str] = {}  # Re-key names after later attachments may have changed representatives.
    for net_root, net_name in net_names.items():  # Walk every label and power-derived name.
        normalized_net_names.setdefault(union_find.find(net_root), net_name)  # Preserve the first name assigned to each final representative.
    net_names = normalized_net_names  # Use only final union-find representatives from this point onward.
    member_order: Dict[str, Tuple[int, Tuple[int, str]]] = {}  # Track the earliest component/pin member per net for naming.
    for record in components:  # Walk every component to seed the naming order.
        if record["power"]:  # Skip power symbols from the automatic naming pass.
            continue  # Move to the next record.
        for pin_number, pin_root in record["pin_nets"].items():  # Walk every pin-to-net association.
            if pin_root is None:  # Skip no-connect pins.
                continue  # Move to the next pin.
            member_key = (record["index"], _pin_number_sort_key(pin_number))  # Build a deterministic member ordering key.
            if pin_root not in member_order or member_key < member_order[pin_root]:  # Keep the earliest member key.
                member_order[pin_root] = member_key  # Record the earliest member key.
    for root_key in sorted(member_order):  # Walk every traced net in deterministic order.
        if root_key in net_names:  # Keep explicitly named nets unchanged.
            continue  # Move to the next net.
        member_index, _pin_key_value = member_order[root_key]  # Read the earliest member identity.
        member_record = next(record for record in components if record["index"] == member_index and root_key in record["pin_nets"].values())  # Locate the earliest member record.
        first_pin = min(  # Choose the smallest pin number on this net for the member.
            (pin_number for pin_number, pin_root in member_record["pin_nets"].items() if pin_root == root_key),  # Collect the member's pins on this net.
            key=_pin_number_sort_key,  # Order pins numerically.
        )  # Finish the pin selection.
        net_names[root_key] = f"Net-({member_record['reference']}-Pad{first_pin})"  # Assign the KiCad-style automatic net name.
    for record in components:  # Normalize every stored pin root after all attachments.
        for pin_number, pin_root in list(record["pin_nets"].items()):  # Walk a stable copy of the pin mapping.
            if pin_root is None:  # Keep no-connect markers unset.
                continue  # Move to the next pin.
            record["pin_nets"][pin_number] = union_find.find(pin_root)  # Replace the stale representative.
    return True, net_names, "", 0  # Return the completed net-name mapping.


def _resolve_footprints(components: List[Dict[str, Any]], settings: Dict[str, Any], tool_modules: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]], str, int]:  # Resolve one footprint per placed component.
    scratch_directory = tempfile.mkdtemp(prefix="electronics_design_pcb_footprints_")  # Host dynamically generated fallback footprints.
    override_map = settings["footprint_map"]  # Read the caller's explicit footprint overrides.
    default_map = dict(_DEFAULT_FOOTPRINT_BY_PREFIX)  # Start from the built-in prefix defaults.
    default_map.update(settings["default_footprints"])  # Apply the caller's prefix overrides.
    search_roots = _footprint_search_roots(settings)  # Resolve the configured footprint search roots.
    for record in components:  # Walk every component record.
        if record["power"]:  # Power symbols place no footprint.
            continue  # Move to the next record.
        pin_count = len(record["symbol_pins"])  # Count the electrical pins of this component.
        identifier, from_defaults = _footprint_identifier_for(record, override_map, default_map)  # Resolve the footprint identifier and its source.
        footprint_path: Optional[str] = None  # Track the resolved footprint file path.
        if identifier != "":  # Try the explicit or default identifier first.
            footprint_path = _find_footprint_file(identifier, search_roots)  # Locate the footprint file.
            if footprint_path is None:  # Fail loudly for explicit identifiers that cannot be found.
                message = f"FOOTPRINT_NOT_FOUND: Unable to locate footprint '{identifier}' for component '{record['reference']}' under the configured footprint search paths"  # Explain the failed lookup.
                return False, [], message, record["line"]  # Return the footprint error with the instance line.
            parse_result = _parse_footprint_file(footprint_path, tool_modules)  # Parse the footprint pads and extents.
            if not parse_result[0]:  # Stop when the footprint file cannot be parsed.
                message = f"FOOTPRINT_NOT_FOUND: Unable to parse footprint file '{footprint_path}' for component '{record['reference']}': {parse_result[1]}"  # Explain the parse failure.
                return False, [], message, record["line"]  # Return the footprint error with the instance line.
            if from_defaults and len(parse_result[2]) != pin_count:  # Regenerate mismatched prefix-default footprints.
                footprint_path = None  # Clear the mismatched footprint for the fallback path.
        if footprint_path is None:  # Generate a fallback footprint matched to the pin count.
            generated = _generate_fallback_footprint(record, pin_count, tool_modules)  # Build the parametric fallback footprint.
            if generated is None:  # Stop when no generator can represent the pin count.
                message = f"FOOTPRINT_NOT_FOUND: No footprint property, prefix default, or generated fallback is available for component '{record['reference']}' with {pin_count} pins"  # Explain the failed resolution.
                return False, [], message, record["line"]  # Return the footprint error with the instance line.
            footprint_path = generated  # Use the generated footprint path.
        parse_result = _parse_footprint_file(footprint_path, tool_modules)  # Parse the footprint pads and extents.
        if not parse_result[0]:  # Stop when the footprint file cannot be parsed.
            message = f"FOOTPRINT_NOT_FOUND: Unable to parse footprint file '{footprint_path}' for component '{record['reference']}': {parse_result[1]}"  # Explain the parse failure.
            return False, [], message, record["line"]  # Return the footprint error with the instance line.
        record["footprint_path"] = footprint_path  # Store the resolved footprint file path.
        record["footprint_id"] = identifier or os.path.splitext(os.path.basename(footprint_path))[0]  # Store the footprint identifier for diagnostics.
        record["footprint_pads"] = parse_result[2]  # Store the parsed pad table.
        record["footprint_extents"] = parse_result[3]  # Store the local bounding half-extents.
    return True, components, "", 0  # Return the resolved components.


def _footprint_search_roots(settings: Dict[str, Any]) -> List[str]:  # Resolve the configured footprint search roots.
    roots: List[str] = []  # Collect the search roots in priority order.
    kicad_path = settings["_kicad_path"]  # Read the validated KiCad install path.
    roots.append(os.path.join(kicad_path, _FOOTPRINT_LIBRARY_DIRECTORY))  # Probe the conventional footprints subdirectory first.
    roots.append(kicad_path)  # Probe the configured path itself for direct .pretty layouts.
    for entry in settings["footprint_search_paths"]:  # Walk the caller's additional roots.
        expanded = os.path.expanduser(str(entry))  # Expand user-relative prefixes.
        roots.append(expanded)  # Append the additional root.
    return roots  # Return the ordered search roots.


def _footprint_identifier_for(record: Dict[str, Any], override_map: Dict[str, str], default_map: Dict[str, str]) -> Tuple[str, bool]:  # Resolve the footprint identifier for one component and whether it came from the prefix defaults.
    lib_id = str(record["lib_id"])  # Read the component's symbol library identifier.
    reference = str(record["reference"])  # Read the component reference designator.
    prefix = _reference_prefix(reference)  # Resolve the reference prefix.
    for key in (lib_id, reference, prefix):  # Walk the override keys in priority order.
        if key and key in override_map:  # Match the first configured override.
            return override_map[key], False  # Return the explicit override identifier.
    instance_footprint = str(record["properties"].get("Footprint", "")).strip()  # Read the instance footprint property.
    if _footprint_property_set(instance_footprint):  # Use the instance footprint when it carries a value.
        return instance_footprint, False  # Return the authored instance footprint.
    library_footprint = str(record["symbol_props"].get("Footprint", "")).strip()  # Read the library footprint property.
    if _footprint_property_set(library_footprint):  # Use the library default when present.
        return library_footprint, False  # Return the library default footprint.
    if prefix and prefix in default_map:  # Match the configured prefix default.
        return default_map[prefix], True  # Return the prefix default footprint marked as a guess.
    return "", False  # Signal the generated-fallback path.


def _footprint_property_set(value: str) -> bool:  # Decide whether one footprint property carries a usable value.
    return value != "" and value != "~"  # Treat the empty and placeholder values as unset.


def _reference_prefix(reference: str) -> str:  # Resolve the longest alphabetic reference prefix.
    prefix = ""  # Collect the leading alphabetic characters.
    for character in reference:  # Walk the reference characters.
        if character.isalpha():  # Extend the alphabetic prefix.
            prefix += character  # Append the alphabetic character.
        else:  # Stop at the first digit or separator.
            break  # Stop the prefix scan.
    return prefix  # Return the reference prefix.


def _find_footprint_file(identifier: str, search_roots: Sequence[str]) -> Optional[str]:  # Locate one footprint file under the configured roots.
    if ":" in identifier:  # Split fully qualified identifiers.
        library_name, footprint_name = identifier.split(":", 1)  # Split the library and footprint names.
    else:  # Handle bare footprint names.
        library_name, footprint_name = "", identifier  # Search every library for the bare name.
    footprint_filename = footprint_name + _FOOTPRINT_FILE_EXTENSION  # Build the footprint file name.
    if library_name:  # Search the named library first.
        for root in search_roots:  # Walk every configured root.
            candidate = os.path.join(root, f"{library_name}{_FOOTPRINT_LIBRARY_EXTENSION}", footprint_filename)  # Build the conventional candidate path.
            if os.path.isfile(candidate):  # Accept the first existing candidate.
                return candidate  # Return the located footprint path.
            candidate = os.path.join(root, library_name, footprint_filename)  # Build the plain-library candidate path.
            if os.path.isfile(candidate):  # Accept a directory-based library hit.
                return candidate  # Return the located footprint path.
    for root in search_roots:  # Fall back to scanning every library directory.
        try:  # Attempt to list the search root.
            entries = sorted(os.listdir(root))  # List the root in deterministic order.
        except OSError:  # Skip roots that cannot be listed.
            continue  # Move to the next root.
        for entry in entries:  # Walk every directory entry.
            if not entry.endswith(_FOOTPRINT_LIBRARY_EXTENSION):  # Skip non-library entries.
                continue  # Move to the next entry.
            candidate = os.path.join(root, entry, footprint_filename)  # Build the per-library candidate path.
            if os.path.isfile(candidate):  # Accept the first matching footprint file.
                return candidate  # Return the located footprint path.
    for root in search_roots:  # Finally check root-level footprint files.
        candidate = os.path.join(root, footprint_filename)  # Build the flat candidate path.
        if os.path.isfile(candidate):  # Accept a flat-layout hit.
            return candidate  # Return the located footprint path.
    return None  # Report the failed lookup.


def _generate_fallback_footprint(record: Dict[str, Any], pin_count: int, tool_modules: Dict[str, Any]) -> Optional[str]:  # Build a parametric fallback footprint for one component.
    if pin_count < min(_ROUTABLE_CHIP_PIN_RANGE):  # Reject components with too few pins to represent.
        return None  # Report the unrepresentable component.
    reference = str(record["reference"])  # Read the component reference.
    prefix = _reference_prefix(reference) or "U"  # Resolve a naming prefix for the generated footprint.
    try:  # Guard every generator behind one failure path.
        if pin_count in _ROUTABLE_CHIP_PIN_RANGE:  # Two-pin passives use the chip generator.
            footprint = tool_modules["create_chip"](_GENERATED_FOOTPRINT_SIZE, prefix=prefix)  # Generate the chip footprint.
        elif pin_count == 3:  # Three-pin parts map onto the standard SOT-23.
            footprint = tool_modules["create_sot"]("SOT-23")  # Generate the SOT-23 footprint.
        elif pin_count == 5:  # Five-pin parts map onto the standard SOT-23-5.
            footprint = tool_modules["create_sot"]("SOT-23-5")  # Generate the SOT-23-5 footprint.
        elif pin_count == 6:  # Six-pin parts map onto the standard SOT-23-6.
            footprint = tool_modules["create_sot"]("SOT-23-6")  # Generate the SOT-23-6 footprint.
        elif _ROUTABLE_SOIC_PIN_RANGE[0] <= pin_count <= _ROUTABLE_SOIC_PIN_RANGE[1] and pin_count % 2 == 0:  # Even wide parts use the SOIC generator.
            footprint = tool_modules["create_soic"](pins=pin_count)  # Generate the SOIC footprint.
        else:  # Every other pin count uses the through-hole header generator.
            footprint = tool_modules["create_pin_header"](pins=pin_count, rows=1)  # Generate the header footprint.
        scratch_directory = os.path.join(tempfile.gettempdir(), "electronics_design_generated_footprints")  # Resolve the shared scratch directory.
        os.makedirs(scratch_directory, exist_ok=True)  # Create the scratch directory once.
        footprint_path = os.path.join(scratch_directory, f"{prefix}_{pin_count}pin_{abs(hash(reference)) % 100000}.kicad_mod")  # Build a deterministic scratch file name.
        footprint.save(footprint_path)  # Write the generated footprint file.
        return footprint_path  # Return the generated footprint path.
    except Exception:  # Fall through to the caller's FOOTPRINT_NOT_FOUND error.
        return None  # Report the generator failure.


def _parse_kicad_mod_pads(footprint_root: Any) -> List[Dict[str, Any]]:  # Parse one footprint's pad table from its S-expression tree.
    pads: List[Dict[str, Any]] = []  # Collect the parsed pad records.
    for pad_node in footprint_root.find_all("pad"):  # Walk every pad record.
        pad_number = pad_node.get_value(0)  # Read the pad number token.
        pad_type = str(pad_node.get_value(1) or "smd")  # Read the pad type token.
        at_node = pad_node.find("at")  # Locate the pad position.
        if at_node is None or pad_number is None:  # Skip pads without a number or position.
            continue  # Move to the next pad.
        pad_x = at_node.get_float(0)  # Read the pad X coordinate.
        pad_y = at_node.get_float(1)  # Read the pad Y coordinate.
        if pad_x is None or pad_y is None:  # Skip pads with incomplete positions.
            continue  # Move to the next pad.
        pad_angle = at_node.get_float(2) or 0.0  # Read the optional pad rotation.
        size_node = pad_node.find("size")  # Locate the pad size.
        pad_width = size_node.get_float(0) if size_node is not None else 1.0  # Read the pad width.
        pad_height = size_node.get_float(1) if size_node is not None else pad_width  # Read the pad height.
        if pad_width is None or pad_width <= 0.0:  # Guard against unusable widths.
            pad_width = 1.0  # Apply the conservative default width.
        if pad_height is None or pad_height <= 0.0:  # Guard against unusable heights.
            pad_height = pad_width  # Apply the width as the height default.
        pad_rotation = pad_angle % 180.0  # Normalize the pad rotation for axis swaps.
        if abs(pad_rotation - 90.0) < 1e-6:  # Swap the pad axes at right angles.
            pad_width, pad_height = pad_height, pad_width  # Swap the pad dimensions.
        drill_node = pad_node.find("drill")  # Locate the optional drill section.
        drill = drill_node.get_float(0) if drill_node is not None else 0.0  # Read the drill diameter.
        if drill is None:  # Default SMD pads carry no drill.
            drill = 0.0  # Apply the SMD default.
        layers_node = pad_node.find("layers")  # Locate the pad layer list.
        layer_names = [str(child.value) for child in layers_node.children if child.is_atom] if layers_node is not None else []  # Collect the layer tokens.
        through_hole = pad_type == "thru_hole" or any(name in ("*.Cu", "B.Cu") for name in layer_names)  # Detect through-hole participation.
        pads.append({  # Store the parsed pad record.
            "number": str(pad_number),  # The pad number as text.
            "x": float(pad_x),  # The pad local X coordinate.
            "y": float(pad_y),  # The pad local Y coordinate.
            "width": float(pad_width),  # The board-frame pad width.
            "height": float(pad_height),  # The board-frame pad height.
            "through_hole": through_hole,  # The through-hole flag.
            "drill": float(drill),  # The drill diameter.
        })  # Finish the pad record.
    return pads  # Return the parsed pad table.


def _parse_kicad_mod_extents(footprint_root: Any, pads: Sequence[Dict[str, Any]]) -> Tuple[float, float, float, float]:  # Compute one footprint's local bounding box.
    min_x = math.inf  # Track the minimum local X.
    min_y = math.inf  # Track the minimum local Y.
    max_x = -math.inf  # Track the maximum local X.
    max_y = -math.inf  # Track the maximum local Y.
    for pad in pads:  # Include every pad in the extents.
        half_width = pad["width"] / 2.0  # Compute the pad half-width.
        half_height = pad["height"] / 2.0  # Compute the pad half-height.
        min_x = min(min_x, pad["x"] - half_width)  # Extend the minimum X.
        max_x = max(max_x, pad["x"] + half_width)  # Extend the maximum X.
        min_y = min(min_y, pad["y"] - half_height)  # Extend the minimum Y.
        max_y = max(max_y, pad["y"] + half_height)  # Extend the maximum Y.
    for graphic_node in footprint_root.find_all("fp_rect") + footprint_root.find_all("fp_line"):  # Walk the footprint graphic records.
        start_node = graphic_node.find("start")  # Locate the graphic start point.
        end_node = graphic_node.find("end")  # Locate the graphic end point.
        if start_node is None or end_node is None:  # Skip incomplete graphics.
            continue  # Move to the next graphic.
        layer_node = graphic_node.find("layer")  # Locate the graphic layer.
        layer_name = str(layer_node.get_value(0) or "") if layer_node is not None else ""  # Read the graphic layer name.
        if layer_name not in ("F.CrtYd", "F.Fab", "F.SilkS"):  # Only courtyard, fabrication, and silkscreen graphics bound the body.
            continue  # Move to the next graphic.
        start_x = start_node.get_float(0)  # Read the start X.
        start_y = start_node.get_float(1)  # Read the start Y.
        end_x = end_node.get_float(0)  # Read the end X.
        end_y = end_node.get_float(1)  # Read the end Y.
        if None in (start_x, start_y, end_x, end_y):  # Skip graphics with missing coordinates.
            continue  # Move to the next graphic.
        min_x = min(min_x, start_x, end_x)  # Extend the minimum X.
        max_x = max(max_x, start_x, end_x)  # Extend the maximum X.
        min_y = min(min_y, start_y, end_y)  # Extend the minimum Y.
        max_y = max(max_y, start_y, end_y)  # Extend the maximum Y.
    if not math.isfinite(min_x):  # Handle footprints with no pads or graphics.
        return (-1.0, -1.0, 1.0, 1.0)  # Apply a minimal 2x2 mm default extent.
    return (float(min_x), float(min_y), float(max_x), float(max_y))  # Return the local bounding box.


def _parse_footprint_file(footprint_path: str, tool_modules: Dict[str, Any]) -> Tuple[bool, Any, List[Dict[str, Any]], Tuple[float, float, float, float]]:  # Load and parse one footprint file.
    try:  # Guard the kicad-tools loader call.
        footprint_root = tool_modules["load_footprint"](footprint_path)  # Parse the footprint S-expression.
    except Exception as load_error:  # Report the loader failure with detail.
        return False, str(load_error), [], (0.0, 0.0, 0.0, 0.0)  # Return the parse failure.
    pads = _parse_kicad_mod_pads(footprint_root)  # Parse the pad table.
    if not pads:  # Reject footprints without any pads.
        return False, "footprint contains no pads", [], (0.0, 0.0, 0.0, 0.0)  # Return the empty-footprint failure.
    extents = _parse_kicad_mod_extents(footprint_root, pads)  # Compute the body extents.
    return True, footprint_root, pads, extents  # Return the parsed footprint payload.


def _place_components(components: List[Dict[str, Any]], settings: Dict[str, Any]) -> Tuple[bool, Tuple[float, float]]:  # Compute board-relative component origins and board size.
    placed = [record for record in components if not record["power"]]  # Exclude power symbols from board placement.
    if not placed:  # Reject schematics with nothing to place.
        return False, (0.0, 0.0)  # Return the empty-placement failure.
    strategy = settings["placement_strategy"]  # Read the validated placement strategy.
    margin = settings["margin"]  # Read the validated board margin.
    explicit_width = settings["kicad_pcb_width"]  # Read the optional explicit board width.
    explicit_height = settings["kicad_pcb_height"]  # Read the optional explicit board height.
    if strategy == "rows":  # Pack components into deterministic rows when requested.
        row_layout = _rows_placement(placed, margin)  # Compute the row-packed origins.
    else:  # Mirror the schematic signal-flow placement by default.
        row_layout = None  # Clear the unused row layout.
        schematic_positions = [(float(record["x"]), float(record["y"])) for record in placed]  # Collect the schematic origins.
        min_schematic_x = min(position[0] for position in schematic_positions)  # Resolve the schematic minimum X.
        min_schematic_y = min(position[1] for position in schematic_positions)  # Resolve the schematic minimum Y.
        max_schematic_x = max(position[0] for position in schematic_positions)  # Resolve the schematic maximum X.
        max_schematic_y = max(position[1] for position in schematic_positions)  # Resolve the schematic maximum Y.
        schematic_width = max(max_schematic_x - min_schematic_x, 1e-6)  # Resolve the schematic content width.
        schematic_height = max(max_schematic_y - min_schematic_y, 1e-6)  # Resolve the schematic content height.
        if explicit_width is not None and explicit_height is not None:  # Scale the drawing into the explicit board.
            scale = min((explicit_width - 2.0 * margin) / schematic_width, (explicit_height - 2.0 * margin) / schematic_height)  # Fit the drawing inside the outline.
        else:  # Keep the schematic millimeter geometry at one-to-one scale.
            scale = 1.0  # Preserve the schematic spacing.
        scale = max(min(scale, _MAX_PLACEMENT_SCALE), 1e-6)  # Bound the placement scale.
        for record in placed:  # Walk every placed component.
            record_x, record_y = float(record["x"]), float(record["y"])  # Read the schematic origin.
            board_x = (record_x - min_schematic_x) * scale + margin  # Map the schematic X onto the board.
            board_y = (record_y - min_schematic_y) * scale + margin  # Map the schematic Y onto the board.
            record["board_x"], record["board_y"] = _snap_position(board_x, board_y)  # Store the snapped board origin.
    if row_layout is not None:  # Apply the precomputed row-packed origins.
        for record, (row_x, row_y) in zip(placed, row_layout):  # Walk the paired placements.
            record["board_x"], record["board_y"] = _snap_position(row_x, row_y)  # Store the snapped origin.
    _legalize_overlaps(placed)  # Push apart component bodies that overlap on the board.
    content_width, content_height = _placed_extents(placed)  # Measure the placed content extents.
    board_width = explicit_width  # Start from the explicit width when provided.
    board_height = explicit_height  # Start from the explicit height when provided.
    needed_width = content_width + 2.0 * margin  # Compute the outline width the content requires.
    needed_height = content_height + 2.0 * margin  # Compute the outline height the content requires.
    board_width = max(board_width or 0.0, needed_width, _MIN_BOARD_SIZE)  # Grow the width to fit the content.
    board_height = max(board_height or 0.0, needed_height, _MIN_BOARD_SIZE)  # Grow the height to fit the content.
    if explicit_width is None or explicit_height is None:  # Center the content inside a freshly grown outline.
        _center_placed_content(placed, board_width, board_height)  # Re-center the content on the final board.
    return True, (board_width, board_height)  # Return the resolved board outline size.


def _snap_position(x: float, y: float) -> Tuple[float, float]:  # Snap one position onto the placement grid.
    snapped_x = round(x / _PLACEMENT_SNAP) * _PLACEMENT_SNAP  # Snap the X coordinate.
    snapped_y = round(y / _PLACEMENT_SNAP) * _PLACEMENT_SNAP  # Snap the Y coordinate.
    return (round(snapped_x, 6), round(snapped_y, 6))  # Return the snapped position.


def _rows_placement(placed: Sequence[Dict[str, Any]], margin: float) -> List[Tuple[float, float]]:  # Pack components into deterministic rows.
    ordered = sorted(placed, key=lambda record: (float(record["y"]), float(record["x"]), str(record["reference"])))  # Order components by schematic row then column.
    total_area = 0.0  # Sum the component body areas.
    for record in ordered:  # Walk the ordered components.
        min_x, min_y, max_x, max_y = record["footprint_extents"]  # Read the local extents.
        total_area += max(max_x - min_x, 1.0) * max(max_y - min_y, 1.0)  # Accumulate the bounding area.
    target_width = max(math.sqrt(total_area) * 1.6, 30.0)  # Resolve the row-packing target width.
    positions: List[Tuple[float, float]] = []  # Collect the packed origins.
    cursor_x = margin  # Start the first row at the left margin.
    cursor_y = margin  # Start the first row at the top margin.
    row_height = 0.0  # Track the tallest component in the current row.
    for record in ordered:  # Walk the ordered components.
        min_x, min_y, max_x, max_y = record["footprint_extents"]  # Read the local extents.
        width = max(max_x - min_x, 1.0)  # Resolve the component width.
        height = max(max_y - min_y, 1.0)  # Resolve the component height.
        gap = 2.0  # Keep a fixed inter-component gap.
        if cursor_x > margin and cursor_x - margin + width > target_width:  # Wrap to the next row when the row overflows.
            cursor_x = margin  # Reset the row cursor.
            cursor_y += row_height + gap  # Advance to the next row.
            row_height = 0.0  # Reset the row height.
        offset_x = -min_x + gap / 2.0  # Center the extents on the cursor.
        offset_y = -min_y + gap / 2.0  # Center the extents on the cursor.
        positions.append((cursor_x + offset_x, cursor_y + offset_y))  # Store the component origin.
        cursor_x += width + gap  # Advance the row cursor.
        row_height = max(row_height, height)  # Track the row height.
    return positions  # Return the packed origins.


def _placed_extents(placed: Sequence[Dict[str, Any]]) -> Tuple[float, float]:  # Measure the placed content extents.
    rects = [_component_rect(record, record["board_x"], record["board_y"]) for record in placed]  # Build every component rectangle.
    if not rects:  # Handle empty placements.
        return (0.0, 0.0)  # Return the empty extent.
    overall_min_x = min(rect[0] for rect in rects)  # Resolve the content minimum X.
    overall_min_y = min(rect[1] for rect in rects)  # Resolve the content minimum Y.
    overall_max_x = max(rect[2] for rect in rects)  # Resolve the content maximum X.
    overall_max_y = max(rect[3] for rect in rects)  # Resolve the content maximum Y.
    return (overall_max_x - overall_min_x, overall_max_y - overall_min_y)  # Return the placed content size.


def _component_rect(record: Dict[str, Any], origin_x: float, origin_y: float) -> Tuple[float, float, float, float]:  # Compute one component's board rectangle.
    min_x, min_y, max_x, max_y = record["footprint_extents"]  # Read the local extents.
    return (origin_x + min_x, origin_y + min_y, origin_x + max_x, origin_y + max_y)  # Return the board rectangle.


def _rects_overlap(first: Tuple[float, float, float, float], second: Tuple[float, float, float, float]) -> bool:  # Detect one-axis overlap between two rectangles.
    return first[0] < second[2] and second[0] < first[2] and first[1] < second[3] and second[1] < first[3]  # Return the strict overlap test.


def _legalize_overlaps(placed: Sequence[Dict[str, Any]]) -> None:  # Push apart component bodies that overlap on the board.
    for _iteration in range(_OVERLAP_LEGALIZE_ITERATIONS):  # Bound the legalization sweeps.
        moved = False  # Track whether any component moved this sweep.
        for first_index in range(len(placed)):  # Walk every first component.
            for second_index in range(first_index + 1, len(placed)):  # Walk every second component.
                first_record = placed[first_index]  # Read the first component.
                second_record = placed[second_index]  # Read the second component.
                first_rect = _component_rect(first_record, first_record["board_x"], first_record["board_y"])  # Build the first rectangle.
                second_rect = _component_rect(second_record, second_record["board_x"], second_record["board_y"])  # Build the second rectangle.
                if not _rects_overlap(first_rect, second_rect):  # Skip non-overlapping pairs.
                    continue  # Move to the next pair.
                overlap_x = min(first_rect[2], second_rect[2]) - max(first_rect[0], second_rect[0])  # Compute the X overlap.
                overlap_y = min(first_rect[3], second_rect[3]) - max(first_rect[1], second_rect[1])  # Compute the Y overlap.
                push = max(overlap_x, overlap_y) / 2.0 + _PLACEMENT_SNAP  # Compute the separation push distance.
                if overlap_x >= overlap_y:  # Push along the smaller-overlap axis.
                    direction = 1.0 if first_record["board_x"] <= second_record["board_x"] else -1.0  # Choose the push direction.
                    first_record["board_x"] = round(first_record["board_x"] - direction * push, 6)  # Move the first component.
                    second_record["board_x"] = round(second_record["board_x"] + direction * push, 6)  # Move the second component.
                else:  # Push vertically when the Y overlap is smaller.
                    direction = 1.0 if first_record["board_y"] <= second_record["board_y"] else -1.0  # Choose the vertical direction.
                    first_record["board_y"] = round(first_record["board_y"] - direction * push, 6)  # Move the first component.
                    second_record["board_y"] = round(second_record["board_y"] + direction * push, 6)  # Move the second component.
                moved = True  # Record the movement.
        if not moved:  # Stop once no pair overlaps.
            break  # Exit the legalization loop.


def _center_placed_content(placed: Sequence[Dict[str, Any]], board_width: float, board_height: float) -> None:  # Center the placed content inside the final outline.
    if not placed:  # Nothing to center without content.
        return  # Return immediately.
    overall_min_x = min(_component_rect(record, record["board_x"], record["board_y"])[0] for record in placed)  # Resolve the content minimum X.
    overall_min_y = min(_component_rect(record, record["board_x"], record["board_y"])[1] for record in placed)  # Resolve the content minimum Y.
    overall_max_x = max(_component_rect(record, record["board_x"], record["board_y"])[2] for record in placed)  # Resolve the content maximum X.
    overall_max_y = max(_component_rect(record, record["board_x"], record["board_y"])[3] for record in placed)  # Resolve the content maximum Y.
    content_width = overall_max_x - overall_min_x  # Measure the content width.
    content_height = overall_max_y - overall_min_y  # Measure the content height.
    shift_x = (board_width - content_width) / 2.0 - overall_min_x  # Compute the X centering shift.
    shift_y = (board_height - content_height) / 2.0 - overall_min_y  # Compute the Y centering shift.
    for record in placed:  # Walk every placed component.
        record["board_x"] = round(record["board_x"] + shift_x, 6)  # Apply the X shift.
        record["board_y"] = round(record["board_y"] + shift_y, 6)  # Apply the Y shift.


def _build_pcb_file(  # Assemble nets, footprints, and net assignments into one PCB.
    components: List[Dict[str, Any]],  # Pass the placed component records.
    net_names: Dict[str, str],  # Pass the traced net-name mapping.
    board_width: float,  # Pass the resolved board width.
    board_height: float,  # Pass the resolved board height.
    input_path: str,  # Pass the input path for the title block.
    output_path: str,  # Pass the intermediate output path.
    settings: Dict[str, Any],  # Pass the validated settings.
    tool_modules: Dict[str, Any],  # Pass the loaded kicad-tools modules.
) -> Tuple[bool, Any, str, int]:  # Return the assembly result tuple.
    pcb_class = tool_modules["PCB"]  # Read the PCB schema class.
    title = settings["title"] or os.path.splitext(os.path.basename(input_path))[0]  # Resolve the title-block title.
    try:  # Guard the board construction calls.
        pcb = pcb_class.create(  # Create the blank board with the resolved outline.
            width=board_width,  # Pass the resolved board width.
            height=board_height,  # Pass the resolved board height.
            layers=settings["layers"],  # Pass the copper-layer count.
            title=title,  # Pass the resolved title text.
            paper=settings["paper"],  # Pass the drawing-sheet size.
            center=True,  # Center the outline on the drawing sheet.
        )  # Finish the board creation.
    except Exception as create_error:  # Report the unusable board parameters.
        return False, None, f"PCB_BUILD_FAILED: {create_error}", 0  # Return the assembly failure.
    assigned_nets: Set[str] = set()  # Collect every net name used by a pad.
    for record in components:  # Walk every placed component.
        for pin_root in record["pin_nets"].values():  # Walk every assigned pin.
            if pin_root is None:  # Skip no-connect pins.
                continue  # Move to the next pin.
            net_name = net_names.get(pin_root, "")  # Resolve the final net name.
            if net_name:  # Register only named nets.
                assigned_nets.add(net_name)  # Record the used net name.
    for net_name in sorted(assigned_nets):  # Declare nets in deterministic order.
        try:  # Guard the net declaration.
            pcb.add_net(net_name)  # Declare the net on the board.
        except Exception as net_error:  # Report the net declaration failure.
            return False, None, f"PCB_BUILD_FAILED: {net_error}", 0  # Return the assembly failure.
    unassigned_pins = 0  # Count pins left without a matching pad.
    for record in components:  # Walk every component record.
        if record["power"]:  # Power symbols place no footprint.
            record["pad_nets"] = {}  # Give power markers an empty pad-net table.
            continue  # Move to the next record.
        try:  # Guard the footprint placement call.
            pcb.add_footprint_from_file(  # Load and place the resolved footprint.
                record["footprint_path"],  # Pass the resolved footprint file path.
                reference=str(record["reference"]),  # Pass the component reference.
                x=float(record["board_x"]),  # Pass the board-relative X origin.
                y=float(record["board_y"]),  # Pass the board-relative Y origin.
                rotation=0.0,  # Keep the physical rotation at zero.
                layer="F.Cu",  # Place every footprint on the front copper layer.
                value=str(record["value"]),  # Pass the component value.
            )  # Finish the placement call.
        except Exception as place_error:  # Report the placement failure.
            return False, None, f"PCB_BUILD_FAILED: unable to place '{record['reference']}': {place_error}", record["line"]  # Return the assembly failure.
        unassigned = _assign_component_nets(pcb, record, net_names)  # Assign every traced net to its pad.
        unassigned_pins += unassigned  # Accumulate the unmatched pin count.
    try:  # Guard the intermediate board write.
        pcb.save(output_path)  # Write the assembled board to disk.
    except Exception as save_error:  # Report the write failure.
        return False, None, f"WRITE_ERROR: {save_error}", 0  # Return the write failure.
    return True, pcb, "", 0  # Return the assembled board.


def _resolve_pad_nets(record: Dict[str, Any], net_names: Dict[str, str]) -> Dict[str, str]:  # Map every footprint pad onto its final net name.
    pad_numbers = [pad["number"] for pad in record["footprint_pads"]]  # Collect the footprint pad numbers.
    traced_pins = {pin_number: pin_root for pin_number, pin_root in record["pin_nets"].items() if pin_root is not None}  # Collect the traced pin nets.
    pad_roots: Dict[str, Any] = {}  # Prepare the pad-to-net-root mapping.
    for pad_number in pad_numbers:  # Resolve each pad in pad-table order.
        if pad_number in traced_pins:  # Match the pad directly to its traced pin.
            pad_roots[pad_number] = traced_pins[pad_number]  # Use the direct pin-number match.
            continue  # Move to the next pad.
        pad_roots[pad_number] = None  # Leave unmatched pads for the positional fallback.
    unmatched_pads = [pad_number for pad_number, pad_root in pad_roots.items() if pad_root is None]  # Collect the pads without a direct net.
    unmatched_pins = [pin_number for pin_number in traced_pins if pin_number not in pad_roots]  # Collect the pins without a direct pad.
    if unmatched_pads and unmatched_pins and len(unmatched_pads) == len(unmatched_pins):  # Pair leftover pins and pads positionally on complete matches.
        ordered_pads = sorted(unmatched_pads, key=_pin_number_sort_key)  # Sort the leftover pads numerically.
        ordered_pins = sorted(unmatched_pins, key=_pin_number_sort_key)  # Sort the leftover pins numerically.
        for pad_number, pin_number in zip(ordered_pads, ordered_pins):  # Pair the leftover sequences.
            pad_roots[pad_number] = traced_pins[pin_number]  # Map the pin net onto the pad.
    pad_nets: Dict[str, str] = {}  # Collect the final pad-to-net-name mapping.
    for pad_number, pad_root in pad_roots.items():  # Resolve every pad net name.
        pad_nets[pad_number] = net_names.get(pad_root, "") if pad_root is not None else ""  # Leave unmatched and no-connect pads unnamed.
    record["pad_nets"] = pad_nets  # Store the shared pad-net mapping on the record.
    return pad_nets  # Return the mapping.


def _assign_component_nets(pcb: Any, record: Dict[str, Any], net_names: Dict[str, str]) -> int:  # Assign one component's traced nets to its pads.
    pad_nets = _resolve_pad_nets(record, net_names)  # Resolve the pad-to-net mapping once.
    unmatched = 0  # Count pads left without an assignment.
    for pad_number, net_name in pad_nets.items():  # Walk every resolved pad.
        if not net_name:  # Skip unnamed and no-connect pads.
            continue  # Move to the next pad.
        try:  # Guard the net assignment call.
            assigned = pcb.assign_net_to_footprint_pad(str(record["reference"]), pad_number, net_name)  # Assign the net to the pad.
        except Exception:  # Treat assignment exceptions as unmatched pads.
            assigned = False  # Count the failed assignment.
        if not assigned:  # Detect pads whose net could not be persisted.
            unmatched += 1  # Count the unmatched pad.
    return unmatched  # Return the unmatched pad count.


def _exception_detail(error: Exception) -> str:  # Build one concise exception detail string.
    import traceback  # Import the traceback formatter lazily.
    frames = traceback.format_exception(type(error), error, error.__traceback__)  # Format the exception stack.
    return frames[-1].strip() if frames else str(error)  # Keep the final frame with the exception message.


def _route_board(  # Route the saved board with the kicad-tools autorouter.
    pcb_path: str,  # Pass the saved intermediate board path.
    components: List[Dict[str, Any]],  # Pass the placed component records.
    output_path: str,  # Pass the final board output path.
    settings: Dict[str, Any],  # Pass the validated settings.
    tool_modules: Dict[str, Any],  # Pass the loaded kicad-tools modules.
) -> Tuple[bool, str]:  # Return the routing result tuple.
    pcb_class = tool_modules["PCB"]  # Read the PCB schema class.
    autorouter_class = tool_modules["Autorouter"]  # Read the autorouter class.
    design_rules_class = tool_modules["DesignRules"]  # Read the design-rules dataclass.
    layer_enum = tool_modules["Layer"]  # Read the copper-layer enum.
    try:  # Guard the board reload used for geometry and net tables.
        pcb = pcb_class.load(pcb_path)  # Reload the saved intermediate board.
    except Exception as load_error:  # Report the reload failure.
        return False, f"ROUTING_FAILED: unable to reload the generated board: {_exception_detail(load_error)}"  # Return the routing failure with detail.
    net_numbers: Dict[str, int] = {}  # Map every net name onto a routing net number.
    for record in components:  # Walk every placed component.
        if record["power"]:  # Power symbols carry no pads.
            continue  # Move to the next record.
        for net_name in record["pad_nets"].values():  # Walk every resolved pad net.
            if net_name and net_name not in net_numbers:  # Register each named net once.
                net_numbers[net_name] = len(net_numbers) + 1  # Assign the next routing net number.
    net_class_map = {}  # Build a routing net-class map without copper-pour exclusions.
    for class_name, class_rules in dict(tool_modules["default_net_class_map"]).items():  # Clone every default net class.
        net_class_map[class_name] = dataclasses.replace(class_rules, is_pour_net=False)  # Route every net as a signal because the generated board carries no pours.
    try:  # Guard the router construction.
        rules = design_rules_class(  # Build the routing design rules.
            trace_width=settings["kicad_pcb_track_width"],  # Pass the configured trace width.
            trace_clearance=settings["kicad_pcb_clearance"],  # Pass the configured clearance.
            grid_resolution=settings["kicad_pcb_grid_resolution"],  # Pass the configured grid pitch.
            via_diameter=settings["kicad_pcb_via_diameter"],  # Pass the configured via diameter.
            via_drill=settings["kicad_pcb_via_drill"],  # Pass the configured via drill.
        )  # Finish the rules construction.
        router = autorouter_class(  # Build the standalone autorouter.
            width=pcb.board_size[0],  # Pass the board width.
            height=pcb.board_size[1],  # Pass the board height.
            origin_x=0.0,  # Use board-relative routing coordinates.
            origin_y=0.0,  # Use board-relative routing coordinates.
            rules=rules,  # Pass the routing design rules.
            net_class_map=net_class_map,  # Pass the pour-free net-class map.
            force_python=True,  # Keep routing deterministic and dependency-free.
        )  # Finish the router construction.
    except Exception as router_error:  # Report the router construction failure.
        return False, f"ROUTING_FAILED: {_exception_detail(router_error)}"  # Return the routing failure with detail.
    for record in components:  # Register every component pad with the router.
        if record["power"]:  # Power symbols carry no pads.
            continue  # Move to the next record.
        pad_entries: List[Dict[str, Any]] = []  # Collect the routing pad table.
        for pad in record["footprint_pads"]:  # Walk the parsed pad table.
            net_name = record["pad_nets"].get(pad["number"], "")  # Resolve the pad net name.
            pad_entries.append({  # Build the router pad entry.
                "number": pad["number"],  # The pad number.
                "x": float(record["board_x"]) + pad["x"],  # The board-relative pad X.
                "y": float(record["board_y"]) + pad["y"],  # The board-relative pad Y.
                "width": pad["width"],  # The pad width.
                "height": pad["height"],  # The pad height.
                "net": net_numbers.get(net_name, 0),  # The routing net number.
                "net_name": net_name,  # The net name.
                "layer": layer_enum.F_CU,  # Route every pad from the front copper layer.
                "through_hole": bool(pad["through_hole"]),  # The through-hole flag.
                "drill": pad["drill"],  # The drill diameter.
            })  # Finish the pad entry.
        try:  # Guard the component registration.
            router.add_component(str(record["reference"]), pad_entries)  # Register the component pads.
        except Exception as add_error:  # Report the registration failure.
            return False, f"ROUTING_FAILED: unable to register '{record['reference']}': {add_error}"  # Return the routing failure.
    try:  # Guard the routing run.
        routes = router.route_all(timeout=settings["kicad_pcb_routing_timeout"])  # Route every ordinary net.
    except Exception as route_error:  # Report the routing failure.
        return False, f"ROUTING_FAILED: {_exception_detail(route_error)}"  # Return the routing failure with detail.
    pad_members: Dict[str, int] = {}  # Count pads per net for the census.
    for record in components:  # Walk every placed component.
        for pad_number, net_name in record["pad_nets"].items():  # Walk every resolved pad net.
            if net_name:  # Count only named nets.
                pad_members[net_name] = pad_members.get(net_name, 0) + 1  # Count the pad membership.
    routeable_nets = {name for name, count in pad_members.items() if count >= 2}  # Nets with two or more pads can be routed.
    routed_nets = {route.net_name for route in routes if route.segments}  # Collect nets that received copper.
    if routeable_nets and not (routeable_nets & routed_nets):  # Detect a completely failed routing pass.
        return False, "ROUTING_FAILED: no routeable net received copper"  # Return the routing failure.
    try:  # Guard the connectivity audit.
        net_pads = tool_modules["build_multi_pad_net_pads"](router)  # Build the router's own pad census.
        connectivity_report = tool_modules["validate_net_connectivity"](routes, net_pads)  # Validate every routed net's copper connectivity.
        unconnected_nets = sorted(  # Collect the nets whose copper misses at least one pad.
            router.net_names.get(net_id, f"Net {net_id}")  # Resolve the net name.
            for net_id, report in connectivity_report.items()  # Walk the per-net connectivity reports.
            if not report["connected"]  # Keep only nets with stranded pads.
        )  # Finish the unconnected-net list.
        if settings["require_complete_routing"] and unconnected_nets:  # Enforce the complete-routing gate when enabled.
            return False, f"ROUTING_FAILED: copper does not connect every pad on {len(unconnected_nets)} net(s): {', '.join(unconnected_nets)}"  # Return the routing failure.
    except Exception as audit_error:  # Treat a failed audit as advisory only.
        del audit_error  # The audit never blocks the conversion by itself.
    if settings["require_complete_routing"] and not routeable_nets.issubset(routed_nets):  # Enforce the complete-routing gate when enabled.
        missing = sorted(routeable_nets - routed_nets)  # List the unrouted nets.
        return False, f"ROUTING_FAILED: {len(missing)} net(s) remain unrouted: {', '.join(missing)}"  # Return the routing failure.
    try:  # Guard the copper write-back.
        for route in routes:  # Walk every routed net.
            net_name = route.net_name  # Read the routed net name.
            if not net_name:  # Skip unnamed copper.
                continue  # Move to the next route.
            for segment in route.segments:  # Write every trace segment.
                pcb.add_trace(  # Append the segment to the board.
                    (segment.x1, segment.y1),  # Pass the segment start.
                    (segment.x2, segment.y2),  # Pass the segment end.
                    width=segment.width,  # Pass the segment width.
                    layer=segment.layer.kicad_name,  # Pass the copper layer name.
                    net=net_name,  # Pass the net name.
                )  # Finish the segment write.
            for via in route.vias:  # Write every layer-transition via.
                pcb.add_via(  # Append the via.
                    via.x,  # Pass the via X.
                    via.y,  # Pass the via Y.
                    size=via.diameter,  # Pass the via diameter.
                    drill=via.drill,  # Pass the via drill.
                    layers=(via.layers[0].kicad_name, via.layers[1].kicad_name),  # Pass the connected layers.
                    net=net_name,  # Pass the net name.
                )  # Finish the via write.
        pcb.save(output_path)  # Rewrite the board with routed copper.
    except Exception as write_error:  # Report the copper write-back failure.
        return False, f"ROUTING_FAILED: unable to write routed copper: {_exception_detail(write_error)}"  # Return the routing failure with detail.
    return True, ""  # Return the routing success.


def _validate_generated_pcb(output_path: str, components: List[Dict[str, Any]], tool_modules: Dict[str, Any]) -> Tuple[bool, str]:  # Validate the finished board file.
    pcb_class = tool_modules["PCB"]  # Read the PCB schema class.
    try:  # Guard the reload parse.
        pcb = pcb_class.load(output_path)  # Parse the finished board.
    except Exception as load_error:  # Report the reload failure.
        return False, f"generated board failed to reload: {load_error}"  # Return the validation failure.
    expected_references = {str(record["reference"]) for record in components if not record["power"]}  # Collect the placed references.
    loaded_references = {footprint.reference for footprint in pcb.footprints}  # Collect the board references.
    if expected_references != loaded_references:  # Detect missing or unexpected footprints.
        missing = sorted(expected_references - loaded_references)  # List the missing references.
        unexpected = sorted(loaded_references - expected_references)  # List the unexpected references.
        detail = f"footprint mismatch (missing: {missing}, unexpected: {unexpected})"  # Explain the mismatch.
        return False, detail  # Return the validation failure.
    return True, ""  # Return the validation success.
