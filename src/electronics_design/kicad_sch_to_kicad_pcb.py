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
import math  # Compute placement scaling and overlap legalization geometry.
import os  # Resolve search roots, create parents, and probe filesystem entries.
import tempfile  # Host dynamically generated fallback footprint files.
import warnings  # Suppress the intentional off-45-grid warning for smooth bends.
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

# kicad-tools is a declared package dependency (pyproject.toml) and is
# imported directly; the guarded import only preserves the public
# KICAD_TOOLS_UNAVAILABLE error contract when the dependency is absent.
try:  # Import every kicad-tools symbol the conversion stages use.
    from kicad_tools.core.sexp_file import load_footprint  # The footprint file loader.
    from kicad_tools.library.generators.chip import create_chip  # The chip footprint generator.
    from kicad_tools.library.generators.soic import create_soic  # The SOIC footprint generator.
    from kicad_tools.library.generators.sot import create_sot  # The SOT footprint generator.
    from kicad_tools.library.generators.through_hole import create_pin_header  # The pin-header generator.
    from kicad_tools.router import Autorouter  # The high-level autorouter class.
    from kicad_tools.router import DesignRules  # The routing design-rules dataclass.
    from kicad_tools.router import Layer  # The copper-layer enum.
    from kicad_tools.router.connectivity_invariant import build_multi_pad_net_pads  # The router pad census helper.
    from kicad_tools.router.observability import validate_net_connectivity  # The routed-copper connectivity validator.
    from kicad_tools.router.rules import DEFAULT_NET_CLASS_MAP  # The default net-class routing table.
    from kicad_tools.schema.pcb import PCB  # The PCB schema class.
    _KICAD_TOOLS_IMPORT_ERROR = ""  # Clear the dependency error marker.
except ImportError as kicad_tools_import_error:  # Preserve the missing-dependency detail.
    _KICAD_TOOLS_IMPORT_ERROR = str(kicad_tools_import_error)  # Store the import failure detail.

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
_DEFAULT_MIN_WIRE_ANGLE = 120.0  # Default minimum bend angle between two routed wires in degrees.
_DEFAULT_WIRE_BEND_CHAMFER = 0.5  # Default corner cut length used to smooth a sharp bend in mm.
_MIN_WIRE_BEND_CUT = 0.02  # Smallest useful corner cut length in mm.
_WIRE_BEND_ANGLE_TOLERANCE = 1e-3  # Bend-angle comparison tolerance in degrees.
_MICRO_SEGMENT_LENGTH = 0.05  # Router jitter segments at or below this length are merged away in mm.
_MICRO_BEND_ANGLE = 1.0  # Near-collinear vertices within this direction change are merged away in degrees.
_WIRE_BEND_SAFETY_MARGIN = 3.0  # Extra degrees kept clear of the threshold so file rounding cannot dip below it.
_DEFAULT_COMPONENT_SPACING = 0.5  # Default minimum footprint-to-footprint gap in mm.
_COMPACT_PLACEMENT_ITERATIONS = 6  # Bounded compaction sweeps per ordering variant.
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
    A* router. The kicad-tools project is a declared package dependency and is
    imported directly.

    Returns ``(True, "OK", 0)`` on success or ``(False, "<error code>", <line>)``
    on failure.
    """
    if _KICAD_TOOLS_IMPORT_ERROR:  # Stop when the kicad-tools dependency is absent.
        return False, f"KICAD_TOOLS_UNAVAILABLE: {_KICAD_TOOLS_IMPORT_ERROR}", 0  # Return the dependency error with its detail.
    settings_result = _normalize_pcb_settings(convert_settings)  # Validate the conversion settings first.
    if not settings_result[0]:  # Stop when the settings are unusable.
        return False, settings_result[2], 0  # Return the settings error code with its detail.
    settings = settings_result[1]  # Read the validated and normalized settings.
    kicad_path = settings_result[3]  # Read the validated KiCad library path.
    output_result = _coerce_output_path(kicad_pcb_filepath_out)  # Coerce the output path safely.
    if not output_result[0]:  # Stop when the output path is not path-like.
        return False, "INVALID_OUTPUT_PATH", 0  # Return the required output path error code.
    output_path = output_result[1]  # Read the coerced output path string.
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
    footprints_result = _resolve_footprints(components, settings)  # Resolve one footprint per component.
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
    )  # Finish the assembly call.
    if not build_result[0]:  # Stop when the board assembly fails.
        return False, build_result[2], build_result[3]  # Return the assembly error code and line.
    if settings["route_traces"]:  # Route copper only when the caller kept routing enabled.
        route_result = _route_board(  # Load the saved board into the kicad-tools autorouter.
            output_path,  # Pass the saved intermediate board path.
            components,  # Pass the placed component records for the pad-net table.
            output_path,  # Rewrite the same board file with routed copper.
            settings,  # Pass the validated settings.
        )  # Finish the routing call.
        if not route_result[0]:  # Stop when routing reports a failure.
            return False, route_result[1], 0  # Return the routing error code with its detail.
    final_result = _validate_generated_pcb(output_path, components)  # Validate the finished board.
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
    angle_result = _positive_float(convert_settings.get("kicad_pcb_min_wire_angle", _DEFAULT_MIN_WIRE_ANGLE))  # Validate the minimum bend angle.
    if not angle_result[0] or angle_result[1] >= 180.0:  # Require an angle strictly inside (0, 180).
        return False, None, "INVALID_CONVERT_SETTINGS: kicad_pcb_min_wire_angle must be a number in (0, 180)", ""  # Return the angle error.
    settings["kicad_pcb_min_wire_angle"] = angle_result[1]  # Store the validated minimum bend angle.
    chamfer_result = _positive_float(convert_settings.get("kicad_pcb_wire_bend_chamfer", _DEFAULT_WIRE_BEND_CHAMFER))  # Validate the bend chamfer length.
    if not chamfer_result[0]:  # Reject unusable chamfer lengths.
        return False, None, "INVALID_CONVERT_SETTINGS: kicad_pcb_wire_bend_chamfer must be a positive number", ""  # Return the chamfer error.
    settings["kicad_pcb_wire_bend_chamfer"] = chamfer_result[1]  # Store the validated bend chamfer length.
    spacing_result = _nonnegative_float(convert_settings.get("kicad_pcb_component_spacing", _DEFAULT_COMPONENT_SPACING))  # Validate the footprint spacing.
    if not spacing_result[0]:  # Reject unusable spacing values.
        return False, None, "INVALID_CONVERT_SETTINGS: kicad_pcb_component_spacing must be a nonnegative number", ""  # Return the spacing error.
    settings["kicad_pcb_component_spacing"] = spacing_result[1]  # Store the validated footprint spacing.
    compact_value = convert_settings.get("kicad_pcb_compact_placement", True)  # Read the placement-compaction toggle.
    if not isinstance(compact_value, bool):  # Require a boolean compaction toggle.
        return False, None, "INVALID_CONVERT_SETTINGS: kicad_pcb_compact_placement must be a boolean", ""  # Return the compaction error.
    settings["kicad_pcb_compact_placement"] = compact_value  # Store the validated compaction toggle.
    settings["_kicad_path"] = base_result[1]  # Store the validated KiCad install path for the footprint search.
    return True, settings, "", base_result[1]  # Return the validated settings bundle.


def _positive_float(value: Any) -> Tuple[bool, Optional[float]]:  # Validate one positive finite number.
    if isinstance(value, bool) or not isinstance(value, (int, float)):  # Reject booleans and non-numbers.
        return False, None  # Signal the validation failure.
    number = float(value)  # Coerce the numeric value to float.
    if not math.isfinite(number) or number <= 0.0:  # Require finite positive magnitudes.
        return False, None  # Signal the validation failure.
    return True, number  # Return the validated float.


def _nonnegative_float(value: Any) -> Tuple[bool, Optional[float]]:  # Validate one nonnegative finite number.
    if isinstance(value, bool) or not isinstance(value, (int, float)):  # Reject booleans and non-numbers.
        return False, None  # Signal the validation failure.
    number = float(value)  # Coerce the numeric value to float.
    if not math.isfinite(number) or number < 0.0:  # Require finite nonnegative magnitudes.
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


def _resolve_footprints(components: List[Dict[str, Any]], settings: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]], str, int]:  # Resolve one footprint per placed component.
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
            parse_result = _parse_footprint_file(footprint_path)  # Parse the footprint pads and extents.
            if not parse_result[0]:  # Stop when the footprint file cannot be parsed.
                message = f"FOOTPRINT_NOT_FOUND: Unable to parse footprint file '{footprint_path}' for component '{record['reference']}': {parse_result[1]}"  # Explain the parse failure.
                return False, [], message, record["line"]  # Return the footprint error with the instance line.
            if from_defaults and len(parse_result[2]) != pin_count:  # Regenerate mismatched prefix-default footprints.
                footprint_path = None  # Clear the mismatched footprint for the fallback path.
        if footprint_path is None:  # Generate a fallback footprint matched to the pin count.
            generated = _generate_fallback_footprint(record, pin_count)  # Build the parametric fallback footprint.
            if generated is None:  # Stop when no generator can represent the pin count.
                message = f"FOOTPRINT_NOT_FOUND: No footprint property, prefix default, or generated fallback is available for component '{record['reference']}' with {pin_count} pins"  # Explain the failed resolution.
                return False, [], message, record["line"]  # Return the footprint error with the instance line.
            footprint_path = generated  # Use the generated footprint path.
        parse_result = _parse_footprint_file(footprint_path)  # Parse the footprint pads and extents.
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


def _generate_fallback_footprint(record: Dict[str, Any], pin_count: int) -> Optional[str]:  # Build a parametric fallback footprint for one component.
    if pin_count < min(_ROUTABLE_CHIP_PIN_RANGE):  # Reject components with too few pins to represent.
        return None  # Report the unrepresentable component.
    reference = str(record["reference"])  # Read the component reference.
    prefix = _reference_prefix(reference) or "U"  # Resolve a naming prefix for the generated footprint.
    try:  # Guard every generator behind one failure path.
        if pin_count in _ROUTABLE_CHIP_PIN_RANGE:  # Two-pin passives use the chip generator.
            footprint = create_chip(_GENERATED_FOOTPRINT_SIZE, prefix=prefix)  # Generate the chip footprint.
        elif pin_count == 3:  # Three-pin parts map onto the standard SOT-23.
            footprint = create_sot("SOT-23")  # Generate the SOT-23 footprint.
        elif pin_count == 5:  # Five-pin parts map onto the standard SOT-23-5.
            footprint = create_sot("SOT-23-5")  # Generate the SOT-23-5 footprint.
        elif pin_count == 6:  # Six-pin parts map onto the standard SOT-23-6.
            footprint = create_sot("SOT-23-6")  # Generate the SOT-23-6 footprint.
        elif _ROUTABLE_SOIC_PIN_RANGE[0] <= pin_count <= _ROUTABLE_SOIC_PIN_RANGE[1] and pin_count % 2 == 0:  # Even wide parts use the SOIC generator.
            footprint = create_soic(pins=pin_count)  # Generate the SOIC footprint.
        else:  # Every other pin count uses the through-hole header generator.
            footprint = create_pin_header(pins=pin_count, rows=1)  # Generate the header footprint.
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


def _parse_footprint_file(footprint_path: str) -> Tuple[bool, Any, List[Dict[str, Any]], Tuple[float, float, float, float]]:  # Load and parse one footprint file.
    try:  # Guard the kicad-tools loader call.
        footprint_root = load_footprint(footprint_path)  # Parse the footprint S-expression.
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
    spacing = settings["kicad_pcb_component_spacing"]  # Read the validated minimum footprint spacing.
    _legalize_overlaps(placed, spacing)  # Enforce the minimum gap between component bodies.
    if settings["kicad_pcb_compact_placement"]:  # Compact the layout unless the caller opted out.
        _compact_placement(placed, spacing)  # Pull every component toward the origin to shrink the outline.
        _snap_placed_positions(placed)  # Return the compacted origins to the placement grid.
        _legalize_overlaps(placed, spacing)  # Restore the minimum gap after grid snapping.
    if not _placement_respects_spacing(placed, spacing):  # Verify the compacted board keeps its minimum gap.
        return False, (0.0, 0.0)  # Report the placement failure.
    content_width, content_height = _placed_extents(placed)  # Measure the placed content extents.
    board_width = explicit_width  # Start from the explicit width when provided.
    board_height = explicit_height  # Start from the explicit height when provided.
    needed_width = content_width + 2.0 * margin  # Compute the outline width the content requires.
    needed_height = content_height + 2.0 * margin  # Compute the outline height the content requires.
    board_width = max(board_width or 0.0, needed_width, _MIN_BOARD_SIZE)  # Grow the width to fit the content.
    board_height = max(board_height or 0.0, needed_height, _MIN_BOARD_SIZE)  # Grow the height to fit the content.
    _center_placed_content(placed, board_width, board_height)  # Keep the content centered inside the final outline.
    return True, (board_width, board_height)  # Return the resolved board outline size.


def _snap_position(x: float, y: float) -> Tuple[float, float]:  # Snap one position onto the placement grid.
    snapped_x = round(x / _PLACEMENT_SNAP) * _PLACEMENT_SNAP  # Snap the X coordinate.
    snapped_y = round(y / _PLACEMENT_SNAP) * _PLACEMENT_SNAP  # Snap the Y coordinate.
    return (round(snapped_x, 6), round(snapped_y, 6))  # Return the snapped position.


def _placement_respects_spacing(placed: Sequence[Dict[str, Any]], spacing: float) -> bool:  # Verify every component pair keeps the minimum gap.
    for first_index in range(len(placed)):  # Walk every first component.
        first_rect = _component_rect(placed[first_index], placed[first_index]["board_x"], placed[first_index]["board_y"])  # Build the first rectangle.
        for second_index in range(first_index + 1, len(placed)):  # Walk every second component.
            second_record = placed[second_index]  # Read the second component.
            second_rect = _component_rect(second_record, second_record["board_x"], second_record["board_y"])  # Build the second rectangle.
            if _rects_too_close(first_rect, second_rect, spacing - 1e-6):  # Detect a pair that breaks the minimum gap.
                return False  # Report the spacing violation.
    return True  # Report the valid placement.


def _snap_placed_positions(placed: Sequence[Dict[str, Any]]) -> None:  # Snap every placed origin back onto the placement grid.
    for record in placed:  # Walk every component record.
        record["board_x"], record["board_y"] = _snap_position(record["board_x"], record["board_y"])  # Store the snapped origin.


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


def _rects_too_close(first: Tuple[float, float, float, float], second: Tuple[float, float, float, float], spacing: float) -> bool:  # Detect whether two rectangles violate the minimum gap.
    return first[0] - spacing < second[2] and second[0] - spacing < first[2] and first[1] - spacing < second[3] and second[1] - spacing < first[3]  # Return the spacing-aware overlap test.


def _legalize_overlaps(placed: Sequence[Dict[str, Any]], spacing: float = 0.0) -> None:  # Push apart component bodies until the minimum gap is met.
    for _iteration in range(_OVERLAP_LEGALIZE_ITERATIONS):  # Bound the legalization sweeps.
        moved = False  # Track whether any component moved this sweep.
        for first_index in range(len(placed)):  # Walk every first component.
            for second_index in range(first_index + 1, len(placed)):  # Walk every second component.
                first_record = placed[first_index]  # Read the first component.
                second_record = placed[second_index]  # Read the second component.
                first_rect = _component_rect(first_record, first_record["board_x"], first_record["board_y"])  # Build the first rectangle.
                second_rect = _component_rect(second_record, second_record["board_x"], second_record["board_y"])  # Build the second rectangle.
                if not _rects_too_close(first_rect, second_rect, spacing):  # Skip pairs that already keep the required gap.
                    continue  # Move to the next pair.
                overlap_x = min(first_rect[2], second_rect[2]) - max(first_rect[0], second_rect[0]) + spacing  # Compute the X gap shortfall.
                overlap_y = min(first_rect[3], second_rect[3]) - max(first_rect[1], second_rect[1]) + spacing  # Compute the Y gap shortfall.
                push = max(overlap_x, overlap_y) / 2.0 + _PLACEMENT_SNAP  # Compute the separation push distance.
                if overlap_x <= overlap_y:  # Push along the axis that needs the smaller correction.
                    direction = 1.0 if first_record["board_x"] <= second_record["board_x"] else -1.0  # Choose the push direction.
                    first_record["board_x"] = round(first_record["board_x"] - direction * push, 6)  # Move the first component.
                    second_record["board_x"] = round(second_record["board_x"] + direction * push, 6)  # Move the second component.
                else:  # Push vertically when the Y shortfall is larger.
                    direction = 1.0 if first_record["board_y"] <= second_record["board_y"] else -1.0  # Choose the vertical direction.
                    first_record["board_y"] = round(first_record["board_y"] - direction * push, 6)  # Move the first component.
                    second_record["board_y"] = round(second_record["board_y"] + direction * push, 6)  # Move the second component.
                moved = True  # Record the movement.
        if not moved:  # Stop once no pair overlaps.
            break  # Exit the legalization loop.


def _compact_placement(placed: Sequence[Dict[str, Any]], spacing: float) -> None:  # Pull every component toward the origin to shrink the placed area.
    original_positions = [(float(record["board_x"]), float(record["board_y"])) for record in placed]  # Snapshot the legal starting layout.
    best_positions: Optional[List[Tuple[float, float]]] = None  # Track the tightest layout found.
    best_area = math.inf  # Track the tightest layout area.
    for variant in range(2):  # Try both deterministic sweep orderings.
        for record, (start_x, start_y) in zip(placed, original_positions):  # Reset the layout before each variant.
            record["board_x"], record["board_y"] = start_x, start_y  # Restore the snapshot.
        for _iteration in range(_COMPACT_PLACEMENT_ITERATIONS):  # Bound the compaction sweeps.
            _compact_axis(placed, spacing, 0, variant)  # Pull every component toward the minimum X.
            _compact_axis(placed, spacing, 1, variant)  # Pull every component toward the minimum Y.
        content_width, content_height = _placed_extents(placed)  # Measure the compacted bounding box.
        area = content_width * content_height  # Score the layout by its bounding-box area.
        if area < best_area - 1e-9:  # Keep every strictly tighter layout.
            best_area = area  # Record the new best area.
            best_positions = [(float(record["board_x"]), float(record["board_y"])) for record in placed]  # Snapshot the layout.
    if best_positions is not None:  # Restore the winning layout.
        for record, (best_x, best_y) in zip(placed, best_positions):  # Walk every component record.
            record["board_x"], record["board_y"] = best_x, best_y  # Apply the winning origin.


def _compact_axis(placed: Sequence[Dict[str, Any]], spacing: float, axis: int, variant: int) -> None:  # Pack every component toward the origin along one axis.
    if axis == 0:  # Handle the horizontal sweep.
        primary = lambda record: (float(record["board_x"]), float(record["board_y"])) if variant == 0 else (float(record["board_y"]), float(record["board_x"]))  # Choose the horizontal ordering key.
    else:  # Handle the vertical sweep.
        primary = lambda record: (float(record["board_y"]), float(record["board_x"])) if variant == 0 else (float(record["board_x"]), float(record["board_y"]))  # Choose the vertical ordering key.
    ordered = sorted(placed, key=lambda record: (primary(record), str(record["reference"])))  # Order the components deterministically.
    axis_min_index, axis_max_index = (0, 2) if axis == 0 else (1, 3)  # Resolve the local-extent indices for this axis.
    cross_min_index, cross_max_index = (1, 3) if axis == 0 else (0, 2)  # Resolve the local-extent indices for the other axis.
    axis_coordinate = "board_x" if axis == 0 else "board_y"  # Resolve the board-coordinate key for this axis.
    cross_coordinate = "board_y" if axis == 0 else "board_x"  # Resolve the board-coordinate key for the other axis.
    packed: List[Dict[str, Any]] = []  # Track the components already fixed this sweep.
    for record in ordered:  # Walk the ordered components.
        local = record["footprint_extents"]  # Read the local bounding extents.
        cross_low = float(record[cross_coordinate]) + local[cross_min_index]  # Resolve this component's low edge on the other axis.
        cross_high = float(record[cross_coordinate]) + local[cross_max_index]  # Resolve this component's high edge on the other axis.
        limit: Optional[float] = None  # Track the nearest blocking component edge.
        for other in packed:  # Walk every component already placed this sweep.
            other_local = other["footprint_extents"]  # Read the packed component's local extents.
            other_low = float(other[cross_coordinate]) + other_local[cross_min_index]  # Resolve the packed low edge.
            other_high = float(other[cross_coordinate]) + other_local[cross_max_index]  # Resolve the packed high edge.
            if other_low - spacing < cross_high and cross_low - spacing < other_high:  # Detect cross-axis proximity within the minimum gap.
                blocking_edge = float(other[axis_coordinate]) + other_local[axis_max_index] + spacing  # Compute the blocked coordinate.
                limit = blocking_edge if limit is None else max(limit, blocking_edge)  # Keep the furthest blocking edge.
        target_min = limit if limit is not None else 0.0  # Pack against the origin when nothing blocks.
        record[axis_coordinate] = round(target_min - local[axis_min_index], 6)  # Move the component's low edge to the target.
        packed.append(record)  # Mark the component as fixed for this sweep.


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
) -> Tuple[bool, Any, str, int]:  # Return the assembly result tuple.
    pcb_class = PCB  # Read the PCB schema class.
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
) -> Tuple[bool, str]:  # Return the routing result tuple.
    pcb_class = PCB  # Read the PCB schema class.
    autorouter_class = Autorouter  # Read the autorouter class.
    design_rules_class = DesignRules  # Read the design-rules dataclass.
    layer_enum = Layer  # Read the copper-layer enum.
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
    for class_name, class_rules in dict(DEFAULT_NET_CLASS_MAP).items():  # Clone every default net class.
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
    _enforce_wire_bend_angles(routes, components, settings)  # Smooth every bend to the configured minimum angle.
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
        net_pads = build_multi_pad_net_pads(router)  # Build the router's own pad census.
        connectivity_report = validate_net_connectivity(routes, net_pads)  # Validate every routed net's copper connectivity.
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
        with warnings.catch_warnings():  # Keep the intentional smooth-bend advisory from surfacing to callers.
            warnings.filterwarnings("ignore", message=".*off-angle segment.*")  # The smoothed geometry was clearance-checked above.
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


def _enforce_wire_bend_angles(routes: List[Any], components: Sequence[Dict[str, Any]], settings: Dict[str, Any]) -> None:  # Smooth every routed bend to the configured minimum angle.
    min_angle = float(settings["kicad_pcb_min_wire_angle"])  # Read the validated minimum bend angle.
    max_change = 180.0 - min_angle  # Resolve the largest allowed direction change per vertex.
    chamfer = float(settings["kicad_pcb_wire_bend_chamfer"])  # Read the validated corner cut length.
    clearance = float(settings["kicad_pcb_clearance"])  # Read the validated copper clearance.
    foreign = _collect_foreign_copper(routes, components)  # Snapshot every foreign-net obstacle once.
    routes_by_net: Dict[Any, List[Any]] = {}  # Group the routed chains by net so cross-route joints are smoothed too.
    for route in routes:  # Walk every routed net chain.
        if route.segments:  # Register only chains that carry copper.
            routes_by_net.setdefault(route.net, []).append(route)  # Group the chain under its net.
    for net_routes in routes_by_net.values():  # Walk every net's copper.
        _smooth_net_copper(net_routes, max_change, chamfer, clearance, foreign)  # Smooth every corner along the net's paths.


def _smooth_net_copper(net_routes: List[Any], max_change: float, chamfer: float, clearance: float, foreign: Sequence[Dict[str, Any]]) -> None:  # Rebuild one net's copper with smooth bend fillets.
    segments = [segment for route in net_routes for segment in route.segments]  # Collect every segment of the net.
    if len(segments) < 2:  # Skip nets without an interior corner.
        return  # Leave the net unchanged.
    via_keys = {(round(via.x, 6), round(via.y, 6)) for route in net_routes for via in route.vias}  # Index the net's layer-transition points.
    rebuilt, changed = _rebuild_net_copper(segments, via_keys, max_change, chamfer, clearance, foreign)  # Rebuild the net with tangent fillets.
    if not changed:  # Stop when the geometry already satisfies the settings.
        return  # Leave the net unchanged.
    net_routes[0].segments = rebuilt  # Park the net's complete rebuilt geometry on its first chain.
    for route in net_routes[1:]:  # Reset the remaining chains of the net.
        route.segments = []  # Avoid writing the same copper twice.


def _rebuild_net_copper(segments: Sequence[Any], via_keys: Set[Tuple[float, float]], max_change: float, chamfer: float, clearance: float, foreign: Sequence[Dict[str, Any]]) -> Tuple[List[Any], bool]:  # Rebuild one net's segment list with smoothed paths.
    endpoints: Dict[Tuple[float, float], List[Tuple[int, int]]] = {}  # Map every segment endpoint onto its incident segment ends.
    for index, segment in enumerate(segments):  # Walk every net segment.
        endpoints.setdefault(_point_key(segment.x1, segment.y1), []).append((index, 0))  # Record the segment start.
        endpoints.setdefault(_point_key(segment.x2, segment.y2), []).append((index, 1))  # Record the segment end.
    boundary_keys: Set[Tuple[float, float]] = set()  # Collect the nodes that terminate smoothable paths.
    for key, incident in endpoints.items():  # Walk every net node.
        if len(incident) != 2 or key in via_keys:  # Detect open ends, junctions, and via transitions.
            boundary_keys.add(key)  # Stop paths at the boundary node.
            continue  # Move to the next node.
        if segments[incident[0][0]].layer != segments[incident[1][0]].layer:  # Detect layer changes.
            boundary_keys.add(key)  # Stop paths at the layer boundary.
    used = [False] * len(segments)  # Track the segments already assigned to a path.
    paths: List[List[Tuple[int, bool]]] = []  # Collect every path description.
    for seed in range(len(segments)):  # Anchor paths at every boundary-incident segment first.
        if used[seed]:  # Skip segments already consumed by another path.
            continue  # Move to the next seed.
        segment = segments[seed]  # Read the seed segment.
        if _point_key(segment.x1, segment.y1) in boundary_keys or _point_key(segment.x2, segment.y2) in boundary_keys:  # Detect a boundary-anchored chain.
            paths.append(_walk_net_path(seed, segments, endpoints, used, boundary_keys))  # Walk the anchored chain.
    for seed in range(len(segments)):  # Handle the remaining closed loops.
        if used[seed]:  # Skip segments already consumed.
            continue  # Move to the next seed.
        paths.append(_walk_net_path(seed, segments, endpoints, used, boundary_keys))  # Walk the loop chain.
    rebuilt: List[Any] = []  # Collect the replacement geometry for the whole net.
    changed = False  # Track whether this pass modified the geometry.
    for path in paths:  # Walk every path.
        points = _path_points(path, segments)  # Flatten the path into an ordered polyline.
        if len(points) < 2:  # Preserve degenerate paths verbatim.
            rebuilt.append(segments[path[0][0]])  # Keep the original segment.
            continue  # Move to the next path.
        template = segments[path[0][0]]  # Use the path's first segment for the rebuilt trace metadata.
        simplified = _simplify_path_points(points, template, clearance, foreign)  # Drop duplicate, micro, and near-collinear vertices.
        if len(simplified) != len(points):  # Detect geometry simplified by this pass.
            changed = True  # Record the modification.
        smoothed, filleted = _smooth_path_points(simplified, template, max_change, chamfer, clearance, foreign)  # Fillet the remaining sharp vertices.
        if filleted:  # Detect geometry smoothed by this pass.
            changed = True  # Record the modification.
        rebuilt.extend(smoothed)  # Append the rebuilt path geometry.
    return rebuilt, changed  # Return the rebuilt geometry and change marker.


def _walk_net_path(seed: int, segments: Sequence[Any], endpoints: Dict[Tuple[float, float], List[Tuple[int, int]]], used: List[bool], boundary_keys: Set[Tuple[float, float]]) -> List[Tuple[int, bool]]:  # Walk one smoothable path through the net graph.
    segment = segments[seed]  # Read the seed segment.
    start_key = _point_key(segment.x1, segment.y1)  # Resolve the seed start key.
    end_key = _point_key(segment.x2, segment.y2)  # Resolve the seed end key.
    start_boundary = start_key in boundary_keys  # Detect a boundary at the seed start.
    end_boundary = end_key in boundary_keys  # Detect a boundary at the seed end.
    if start_boundary and not end_boundary:  # Prefer walking away from a boundary.
        path: List[Tuple[int, bool]] = [(seed, True)]  # Start the path at the seed start.
        current_key = end_key  # Continue from the seed end.
    elif end_boundary and not start_boundary:  # Handle the opposite orientation.
        path = [(seed, False)]  # Start the path at the seed end.
        current_key = start_key  # Continue from the seed start.
    else:  # Handle loops and segments that join two boundaries.
        path = [(seed, True)]  # Walk the seed forward.
        current_key = end_key  # Continue from the seed end.
    used[seed] = True  # Mark the seed consumed.
    while current_key not in boundary_keys:  # Walk through every degree-two interior node.
        candidates = [entry for entry in endpoints[current_key] if not used[entry[0]]]  # Collect the unused continuations.
        if not candidates:  # Stop when the path dead-ends.
            break  # Exit the walk.
        index, end_flag = candidates[0]  # Continue through the first unused segment.
        used[index] = True  # Mark the continuation consumed.
        forward = end_flag == 0  # Traverse forward when entering at the segment start.
        path.append((index, forward))  # Append the continuation.
        next_segment = segments[index]  # Read the continuation segment.
        current_key = _point_key(next_segment.x2, next_segment.y2) if forward else _point_key(next_segment.x1, next_segment.y1)  # Advance to the far end.
    return path  # Return the ordered path description.


def _path_points(path: Sequence[Tuple[int, bool]], segments: Sequence[Any]) -> List[Tuple[float, float]]:  # Flatten one path into an ordered polyline.
    points: List[Tuple[float, float]] = []  # Collect the path vertices.
    for index, forward in path:  # Walk the path segments in order.
        segment = segments[index]  # Read the current segment.
        first = (segment.x1, segment.y1) if forward else (segment.x2, segment.y2)  # Resolve the entry point.
        second = (segment.x2, segment.y2) if forward else (segment.x1, segment.y1)  # Resolve the exit point.
        if not points or not _points_close(points[-1][0], points[-1][1], first[0], first[1], tolerance=1e-4):  # Detect gaps in the chain.
            points.append(first)  # Append the entry point when it starts a new run.
        points.append(second)  # Append the exit point.
    return points  # Return the ordered polyline.


def _simplify_path_points(points: Sequence[Tuple[float, float]], template: Any, clearance: float, foreign: Sequence[Dict[str, Any]]) -> List[Tuple[float, float]]:  # Drop duplicate, micro, and near-collinear polyline vertices.
    simplified = list(points)  # Copy the input polyline.
    changed = True  # Track whether the last sweep removed a vertex.
    while changed and len(simplified) > 2:  # Sweep until no removable vertex remains.
        changed = False  # Reset the change marker for this sweep.
        index = 1  # Start at the first interior vertex.
        while index < len(simplified) - 1:  # Walk every interior vertex.
            previous = simplified[index - 1]  # Read the previous vertex.
            current = simplified[index]  # Read the current vertex.
            following = simplified[index + 1]  # Read the following vertex.
            first_length = math.dist(previous, current)  # Measure the incoming segment.
            second_length = math.dist(current, following)  # Measure the outgoing segment.
            if first_length < 1e-9 or second_length < 1e-9:  # Remove duplicate vertices.
                simplified.pop(index)  # Drop the duplicate vertex.
                changed = True  # Record the removal.
                continue  # Restart at the same index.
            incoming = _unit_vector(previous[0], previous[1], current[0], current[1])  # Resolve the incoming direction.
            outgoing = _unit_vector(current[0], current[1], following[0], following[1])  # Resolve the outgoing direction.
            removable = False  # Track whether the vertex may be dropped.
            if incoming is not None and outgoing is not None:  # Guard degenerate directions.
                change = _direction_change_degrees(incoming, outgoing)  # Measure the direction change.
                removable = change <= _MICRO_BEND_ANGLE or min(first_length, second_length) <= _MICRO_SEGMENT_LENGTH  # Drop near-collinear and micro vertices.
            if removable and _straight_leg_is_clear(previous, following, template, clearance, foreign):  # Verify the replacement leg clearance.
                simplified.pop(index)  # Drop the removable vertex.
                changed = True  # Record the removal.
                continue  # Restart at the same index.
            index += 1  # Advance to the next interior vertex.
    return simplified  # Return the simplified polyline.


def _straight_leg_is_clear(first: Tuple[float, float], second: Tuple[float, float], template: Any, clearance: float, foreign: Sequence[Dict[str, Any]]) -> bool:  # Verify one straight replacement leg keeps its copper clearance.
    return _smoothed_legs_are_clear([first, second], template.net_name, template.layer, template.width, clearance, foreign)  # Reuse the fillet clearance checker.


def _smooth_path_points(points: Sequence[Tuple[float, float]], template: Any, max_change: float, chamfer: float, clearance: float, foreign: Sequence[Dict[str, Any]]) -> Tuple[List[Any], bool]:  # Replace every sharp polyline vertex with a smooth fillet.
    if len(points) < 2:  # Handle empty and single-point paths.
        return [], False  # Emit no geometry.
    if len(points) == 2:  # Handle straight two-point paths.
        return [_clone_segment(template, points[0], points[1])], False  # Emit the single straight segment.
    fillet_max_change = max(max_change - _WIRE_BEND_SAFETY_MARGIN, _WIRE_BEND_ANGLE_TOLERANCE)  # Keep the chords clear of the exact threshold.
    lengths = [math.dist(points[index], points[index + 1]) for index in range(len(points) - 1)]  # Measure every polyline segment.
    consumed_start = [0.0] * len(lengths)  # Track the length consumed at each segment start.
    consumed_end = [0.0] * len(lengths)  # Track the length consumed at each segment end.
    corners: Dict[int, Tuple[float, float, Tuple[float, float], Tuple[float, float]]] = {}  # Record the smoothed interior vertices.
    for index in range(1, len(points) - 1):  # Walk every interior vertex.
        incoming = _unit_vector(points[index - 1][0], points[index - 1][1], points[index][0], points[index][1])  # Resolve the incoming direction.
        outgoing = _unit_vector(points[index][0], points[index][1], points[index + 1][0], points[index + 1][1])  # Resolve the outgoing direction.
        if incoming is None or outgoing is None:  # Skip degenerate vertices.
            continue  # Move to the next vertex.
        change = _direction_change_degrees(incoming, outgoing)  # Measure the direction change.
        if change <= fillet_max_change + _WIRE_BEND_ANGLE_TOLERANCE:  # Keep bends that already satisfy the minimum angle.
            continue  # Move to the next vertex.
        available_in = lengths[index - 1]  # Resolve the incoming length before any corner consumes it.
        available_out = lengths[index]  # Resolve the outgoing length before any corner consumes it.
        if available_in <= 0.0 or available_out <= 0.0:  # Skip degenerate vertices.
            continue  # Move to the next vertex.
        cut = min(chamfer, 0.45 * available_in, 0.45 * available_out)  # Resolve the initial corner cut length.
        while cut >= _MIN_WIRE_BEND_CUT:  # Shrink the fillet until it is clearance-clean.
            fillet = _corner_fillet_points(points[index], incoming, outgoing, cut, change, fillet_max_change)  # Build the candidate fillet.
            if _smoothed_legs_are_clear(fillet, template.net_name, template.layer, template.width, clearance, foreign):  # Verify the fillet clearance.
                break  # Keep the clearance-clean fillet.
            cut *= 0.5  # Halve the fillet and retry.
        if cut < _MIN_WIRE_BEND_CUT:  # Skip corners that cannot be smoothed safely.
            continue  # Move to the next vertex.
        consumed_end[index - 1] += cut  # Consume the incoming segment end.
        consumed_start[index] += cut  # Consume the outgoing segment start.
        corners[index] = (change, cut, incoming, outgoing)  # Record the smoothed vertex.
    rebuilt: List[Any] = []  # Collect the replacement segments.
    for index in range(len(lengths)):  # Walk every polyline segment.
        start_point = _offset_point(points[index], points[index + 1], consumed_start[index])  # Resolve the trimmed start point.
        end_point = _offset_point(points[index + 1], points[index], consumed_end[index])  # Resolve the trimmed end point.
        if math.dist(start_point, end_point) > 1e-9:  # Keep only non-degenerate trims.
            rebuilt.append(_clone_segment(template, start_point, end_point))  # Append the trimmed segment.
        if index + 1 in corners:  # Append the fillet that follows this segment.
            change, cut, incoming, outgoing = corners[index + 1]  # Unpack the recorded corner.
            fillet = _corner_fillet_points(points[index + 1], incoming, outgoing, cut, change, fillet_max_change)  # Rebuild the fillet polyline.
            for first, second in zip(fillet, fillet[1:]):  # Walk every fillet leg.
                if math.dist(first, second) > 1e-9:  # Keep only non-degenerate legs.
                    rebuilt.append(_clone_segment(template, first, second))  # Append the fillet leg.
    return rebuilt, bool(corners)  # Return the rebuilt path geometry and the fillet marker.


def _collect_foreign_copper(routes: Sequence[Any], components: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:  # Snapshot the copper that smoothed bends must keep clear of.
    items: List[Dict[str, Any]] = []  # Collect every foreign-net obstacle record.
    for route in routes:  # Walk every routed chain.
        for segment in route.segments:  # Walk every routed trace segment.
            items.append({  # Store the segment obstacle.
                "kind": "segment",  # Mark the obstacle shape.
                "net": route.net_name,  # The owning net name.
                "layer": segment.layer,  # The copper layer.
                "geometry": (segment.x1, segment.y1, segment.x2, segment.y2),  # The segment endpoints.
                "half": float(segment.width) / 2.0,  # The trace half-width.
            })  # Finish the segment record.
        for via in route.vias:  # Walk every routed via.
            items.append({  # Store the via obstacle.
                "kind": "disc",  # Mark the obstacle shape.
                "net": route.net_name,  # The owning net name.
                "layer": None,  # Vias connect layers and block all of them.
                "geometry": (via.x, via.y, float(via.diameter) / 2.0),  # The via centre and radius.
                "half": 0.0,  # Discs carry no extra half-width.
            })  # Finish the via record.
    for record in components:  # Walk every placed component.
        if record["power"]:  # Power symbols place no pads.
            continue  # Move to the next record.
        for pad in record.get("footprint_pads", []):  # Walk every footprint pad.
            net_name = record.get("pad_nets", {}).get(pad["number"], "")  # Resolve the pad net name.
            centre_x = float(record["board_x"]) + float(pad["x"])  # Resolve the board-frame pad X.
            centre_y = float(record["board_y"]) + float(pad["y"])  # Resolve the board-frame pad Y.
            items.append({  # Store the pad obstacle as an axis-aligned rectangle.
                "kind": "rect",  # Mark the obstacle shape.
                "net": net_name,  # The owning net name.
                "layer": None,  # Pads block conservatively on every layer.
                "geometry": (centre_x, centre_y, float(pad["width"]), float(pad["height"])),  # The pad centre and size.
                "half": 0.0,  # Rectangles carry no extra half-width.
            })  # Finish the pad record.
    return items  # Return the complete obstacle snapshot.


def _unit_vector(x1: float, y1: float, x2: float, y2: float) -> Optional[Tuple[float, float]]:  # Normalize one displacement into a unit vector.
    dx = x2 - x1  # Compute the displacement X.
    dy = y2 - y1  # Compute the displacement Y.
    length = math.hypot(dx, dy)  # Measure the displacement length.
    if length < 1e-12:  # Reject degenerate displacements.
        return None  # Signal the unusable displacement.
    return (dx / length, dy / length)  # Return the normalized direction.


def _points_close(first_x: float, first_y: float, second_x: float, second_y: float, tolerance: float = 1e-6) -> bool:  # Compare two board points.
    return abs(first_x - second_x) <= tolerance and abs(first_y - second_y) <= tolerance  # Return the tolerance comparison.


def _direction_change_degrees(first: Tuple[float, float], second: Tuple[float, float]) -> float:  # Measure the angle between two travel directions.
    dot = max(-1.0, min(1.0, first[0] * second[0] + first[1] * second[1]))  # Compute the clamped direction dot product.
    return math.degrees(math.acos(dot))  # Return the direction change in degrees.


def _clone_segment(template: Any, start_point: Tuple[float, float], end_point: Tuple[float, float]) -> Any:  # Clone one router segment with new endpoints.
    return dataclasses.replace(  # Reuse the segment's width, layer, and net metadata.
        template,  # Keep the template metadata.
        x1=float(start_point[0]),  # Assign the new start X.
        y1=float(start_point[1]),  # Assign the new start Y.
        x2=float(end_point[0]),  # Assign the new end X.
        y2=float(end_point[1]),  # Assign the new end Y.
    )  # Finish the cloned segment.


def _offset_point(origin: Tuple[float, float], target: Tuple[float, float], distance: float) -> Tuple[float, float]:  # Compute a point measured from one vertex toward another.
    direction = _unit_vector(origin[0], origin[1], target[0], target[1])  # Resolve the vertex direction.
    if direction is None:  # Handle duplicate vertices.
        return origin  # Return the origin unchanged.
    return (origin[0] + direction[0] * distance, origin[1] + direction[1] * distance)  # Return the offset point.


def _corner_fillet_points(vertex: Tuple[float, float], incoming: Tuple[float, float], outgoing: Tuple[float, float], cut: float, change: float, max_change: float) -> List[Tuple[float, float]]:  # Build the fillet polyline replacing one sharp corner.
    point_in = (vertex[0] - incoming[0] * cut, vertex[1] - incoming[1] * cut)  # Resolve the incoming tangent point.
    point_out = (vertex[0] + outgoing[0] * cut, vertex[1] + outgoing[1] * cut)  # Resolve the outgoing tangent point.
    steps = max(2, int(math.ceil(change / max_change - 1e-9)))  # Resolve how many chords approximate the fillet arc.
    if steps == 2:  # Use the plain 45-degree chamfer for the common case.
        return [point_in, point_out]  # Return the single chord.
    half = math.radians(change / 2.0)  # Resolve the half direction change.
    radius = cut / math.tan(half)  # Resolve the tangent-arc radius.
    bisector = _unit_vector(incoming[0], incoming[1], outgoing[0], outgoing[1])  # Resolve the interior bisector direction.
    if bisector is None:  # Handle antiparallel directions.
        return [point_in, point_out]  # Fall back to the direct chord.
    centre_distance = cut / math.sin(half)  # Resolve the arc-centre distance from the vertex.
    centre = (vertex[0] + bisector[0] * centre_distance, vertex[1] + bisector[1] * centre_distance)  # Resolve the arc centre.
    first_radial = _unit_vector(centre[0], centre[1], point_in[0], point_in[1])  # Resolve the first radial direction.
    if first_radial is None:  # Handle a degenerate radial.
        return [point_in, point_out]  # Fall back to the direct chord.
    last_radial = (point_out[0] - centre[0], point_out[1] - centre[1])  # Resolve the last radial vector.
    cross = first_radial[0] * last_radial[1] - first_radial[1] * last_radial[0]  # Resolve the arc sweep sign.
    sign = 1.0 if cross >= 0.0 else -1.0  # Choose the short-arc rotation direction.
    points: List[Tuple[float, float]] = [point_in]  # Start the fillet at the incoming tangent point.
    for index in range(1, steps):  # Walk every intermediate chord vertex.
        angle = sign * math.radians(change) * (index / steps)  # Resolve the radial rotation for this vertex.
        cosine = math.cos(angle)  # Precompute the cosine.
        sine = math.sin(angle)  # Precompute the sine.
        points.append((  # Append the rotated point on the arc.
            centre[0] + radius * (first_radial[0] * cosine - first_radial[1] * sine),  # Compute the arc point X.
            centre[1] + radius * (first_radial[0] * sine + first_radial[1] * cosine),  # Compute the arc point Y.
        ))  # Finish the intermediate vertex.
    points.append(point_out)  # Terminate the fillet at the outgoing tangent point.
    return points  # Return the fillet polyline.


def _point_segment_distance(point_x: float, point_y: float, x1: float, y1: float, x2: float, y2: float) -> float:  # Measure the distance from one point to one segment.
    dx = x2 - x1  # Compute the segment displacement X.
    dy = y2 - y1  # Compute the segment displacement Y.
    length_squared = dx * dx + dy * dy  # Measure the squared segment length.
    if length_squared <= 1e-18:  # Handle degenerate segments.
        return math.hypot(point_x - x1, point_y - y1)  # Return the point distance.
    parameter = ((point_x - x1) * dx + (point_y - y1) * dy) / length_squared  # Project the point onto the segment.
    parameter = max(0.0, min(1.0, parameter))  # Clamp the projection to the segment.
    return math.hypot(point_x - x1 - parameter * dx, point_y - y1 - parameter * dy)  # Return the clamped distance.


def _orientation(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:  # Compute the signed area of one triangle.
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)  # Return the cross product.


def _segments_intersect(ax1: float, ay1: float, ax2: float, ay2: float, bx1: float, by1: float, bx2: float, by2: float) -> bool:  # Detect whether two segments cross.
    first = _orientation(ax1, ay1, ax2, ay2, bx1, by1)  # Orient the first endpoint.
    second = _orientation(ax1, ay1, ax2, ay2, bx2, by2)  # Orient the second endpoint.
    third = _orientation(bx1, by1, bx2, by2, ax1, ay1)  # Orient the third endpoint.
    fourth = _orientation(bx1, by1, bx2, by2, ax2, ay2)  # Orient the fourth endpoint.
    return (first * second < 0.0) and (third * fourth < 0.0)  # Return the proper-crossing test.


def _segment_segment_distance(ax1: float, ay1: float, ax2: float, ay2: float, bx1: float, by1: float, bx2: float, by2: float) -> float:  # Measure the distance between two segments.
    if _segments_intersect(ax1, ay1, ax2, ay2, bx1, by1, bx2, by2):  # Detect a crossing pair.
        return 0.0  # Return the touching distance.
    return min(  # Return the closest endpoint-to-segment distance.
        _point_segment_distance(ax1, ay1, bx1, by1, bx2, by2),  # First endpoint of the first segment.
        _point_segment_distance(ax2, ay2, bx1, by1, bx2, by2),  # Second endpoint of the first segment.
        _point_segment_distance(bx1, by1, ax1, ay1, ax2, ay2),  # First endpoint of the second segment.
        _point_segment_distance(bx2, by2, ax1, ay1, ax2, ay2),  # Second endpoint of the second segment.
    )  # Finish the distance selection.


def _segment_rect_distance(x1: float, y1: float, x2: float, y2: float, min_x: float, min_y: float, max_x: float, max_y: float) -> float:  # Measure the distance between one segment and one axis-aligned rectangle.
    if (min_x <= x1 <= max_x and min_y <= y1 <= max_y) or (min_x <= x2 <= max_x and min_y <= y2 <= max_y):  # Detect endpoints inside the rectangle.
        return 0.0  # Return the touching distance.
    corners = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]  # Collect the rectangle corners.
    best = math.inf  # Track the smallest edge distance.
    for index, (corner_x, corner_y) in enumerate(corners):  # Walk every rectangle edge.
        next_x, next_y = corners[(index + 1) % len(corners)]  # Resolve the edge end.
        best = min(best, _segment_segment_distance(x1, y1, x2, y2, corner_x, corner_y, next_x, next_y))  # Shrink the distance.
    return best  # Return the closest distance.


def _smoothed_legs_are_clear(points: Sequence[Tuple[float, float]], net_name: str, layer: Any, width: float, clearance: float, foreign: Sequence[Dict[str, Any]]) -> bool:  # Verify that a fillet keeps its copper clearance.
    half_width = float(width) / 2.0  # Resolve the smoothed trace half-width.
    for (x1, y1), (x2, y2) in zip(points, points[1:]):  # Walk every fillet leg.
        for item in foreign:  # Walk every foreign-net obstacle.
            if item["net"] == net_name:  # Skip copper on the same net.
                continue  # Move to the next obstacle.
            if item["kind"] == "segment":  # Handle foreign trace segments.
                if item["layer"] != layer:  # Skip copper on another layer.
                    continue  # Move to the next obstacle.
                distance = _segment_segment_distance(x1, y1, x2, y2, *item["geometry"])  # Measure the segment separation.
                if distance < half_width + item["half"] + clearance - 1e-6:  # Detect a clearance violation.
                    return False  # Report the blocked fillet.
            elif item["kind"] == "disc":  # Handle foreign vias.
                centre_x, centre_y, radius = item["geometry"]  # Unpack the via geometry.
                distance = _point_segment_distance(centre_x, centre_y, x1, y1, x2, y2)  # Measure the via separation.
                if distance < half_width + radius + clearance - 1e-6:  # Detect a clearance violation.
                    return False  # Report the blocked fillet.
            else:  # Handle foreign pads.
                centre_x, centre_y, pad_width, pad_height = item["geometry"]  # Unpack the pad geometry.
                distance = _segment_rect_distance(  # Measure the pad separation.
                    x1, y1, x2, y2,  # Pass the fillet leg.
                    centre_x - pad_width / 2.0, centre_y - pad_height / 2.0,  # Pass the pad minimum corner.
                    centre_x + pad_width / 2.0, centre_y + pad_height / 2.0,  # Pass the pad maximum corner.
                )  # Finish the pad distance measurement.
                if distance < half_width + clearance - 1e-6:  # Detect a clearance violation.
                    return False  # Report the blocked fillet.
    return True  # Report the clear fillet.


def _validate_generated_pcb(output_path: str, components: List[Dict[str, Any]]) -> Tuple[bool, str]:  # Validate the finished board file.
    pcb_class = PCB  # Read the PCB schema class.
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
