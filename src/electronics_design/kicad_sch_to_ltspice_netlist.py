"""KiCad schematic (`.kicad_sch`) to LTspice netlist (`.net`) conversion API."""  # Describe the module purpose.

# The conversion rules implemented here mirror the behavior of LTspice's own
# netlist generator so that the emitted deck is structurally equivalent to
# what LTspice would produce for the same circuit. Symbol data (pins, prefix,
# simulation attributes) is always looked up from the KiCad symbol libraries
# under `convert_settings["kicad_path"]`, falling back to the schematic's
# embedded `lib_symbols` definitions only when the library file is missing.
# No symbol names, pin positions, or library paths are hard-coded.

from __future__ import annotations  # Postpone annotation evaluation for forward references.

import math  # Compute pin rotation transforms for symbol instances.
import os  # Resolve library search roots and write the output file.
import re  # Extract line numbers from validator messages.
from functools import lru_cache  # Reuse parsed, read-only KiCad library trees across conversions.
from typing import Dict  # Type net-name and property mappings.
from typing import List  # Type collected line and record lists.
from typing import Mapping  # Type the convert_settings parameter.
from typing import Optional  # Type optional parse results.
from typing import Sequence  # Type immutable record sequences.
from typing import Set  # Type unique position sets.
from typing import Tuple  # Type tuple-based helper results.

from .kicad_sch import _first_atom_value  # Reuse the shared first-atom extraction helper.
from .kicad_sch import _node_line_or  # Reuse the shared node-line reporting helper.
from .kicad_sch import _parse_sch_text  # Reuse the shared schematic parser wrapper.
from .kicad_sch import _read_text_file_lines  # Reuse the shared encoding-aware file reader.
from .kicad_sch import is_valid_kicad_sch_file  # Validate the schematic before conversion.
from .kicad_sexp_parser import ParseError  # Catch library-file parse failures.
from .kicad_sexp_parser import SExp  # Type parsed schematic and symbol nodes.
from .kicad_sexp_parser import parse_string  # Parse KiCad symbol library files.
from .ltspice_net import _VALID_DEVICE_PREFIXES  # Validate derived LTspice device prefixes.
from .ltspice_net import is_valid_ltspice_netlist_file  # Validate the generated netlist file.

ConversionResult = Tuple[bool, str, int]  # Represent the public conversion return shape.

_GROUND_VALUES = frozenset({"GND", "0"})  # Treat these power-symbol values as LTspice ground node 0.

_POINT_TOLERANCE = 1e-6  # Compare KiCad coordinates with millimeter file precision.

_LINE_SUFFIX_PATTERN = re.compile(r"Line (\d+)\s*$")  # Extract trailing line numbers from validator messages.

_DEFAULT_ANALYSIS_DIRECTIVE = ".tran 1"  # Emit a minimal transient analysis so the footer validator passes.

_KICAD_SYMBOL_EXTENSION = ".kicad_sym"  # Recognize KiCad symbol library files by extension.

_ROLE_ORDER = {  # Define the SPICE node ordering for each known simulation device class.
    "NPN": ("C", "B", "E", "S"),  # BJT collector, base, emitter, and substrate nodes.
    "PNP": ("C", "B", "E", "S"),  # BJT collector, base, emitter, and substrate nodes.
    "NMOS": ("D", "G", "S", "B"),  # MOSFET drain, gate, source, and bulk nodes.
    "PMOS": ("D", "G", "S", "B"),  # MOSFET drain, gate, source, and bulk nodes.
    "NJF": ("D", "G", "S"),  # JFET drain, gate, and source nodes.
    "PJF": ("D", "G", "S"),  # JFET drain, gate, and source nodes.
    "D": ("A", "K"),  # Diode anode and cathode nodes.
    "V": ("+", "-"),  # Voltage source positive and negative nodes.
    "I": ("+", "-"),  # Current source positive and negative nodes.
}  # Finish the role ordering table.

_SUBCKT_SIM_DEVICES = frozenset({"SPICE", "SUBCKT"})  # Simulation devices emitted as LTspice subcircuit calls.

_SUBSTRATE_DEFAULT_PREFIXES = frozenset({"Q", "M"})  # Three-pin transistor symbols get LTspice's substrate node 0.

_NO_CONNECT_PREFIXES = ("NC", "NC_", "NC-")  # Mirror the netlist validator's exempt no-connect prefixes.


class _UnionFind:  # Track merged electrical points with a lightweight disjoint-set structure.
    def __init__(self) -> None:  # Initialize the disjoint set.
        self._parent: Dict[str, str] = {}  # Map each point key to its current representative.

    def add(self, key: str) -> None:  # Register a point key when it is not already present.
        if key not in self._parent:  # Check whether the key is new.
            self._parent[key] = key  # Start the point as its own representative.

    def find(self, key: str) -> str:  # Resolve the representative of one point key.
        root = key  # Walk upward from the requested key.
        while self._parent.get(root, root) != root:  # Follow parent links until the root is reached.
            root = self._parent[root]  # Move to the parent representative.
        self._parent[key] = root  # Compress the path for the requested key.
        return root  # Return the resolved representative.

    def union(self, first: str, second: str) -> None:  # Merge the sets containing two point keys.
        first_root = self.find(first)  # Resolve the representative of the first key.
        second_root = self.find(second)  # Resolve the representative of the second key.
        if first_root != second_root:  # Only merge when the sets are distinct.
            self._parent[second_root] = first_root  # Attach the second root under the first.


class _LibraryCache:  # Lazily parse KiCad symbol library files found under the configured kicad_path.
    def __init__(self, kicad_path: str) -> None:  # Initialize the cache with the configured root.
        self._search_roots = [kicad_path]  # Search the configured path itself first.
        symbols_directory = os.path.join(kicad_path, "symbols")  # Probe the conventional symbols subdirectory.
        if os.path.isdir(symbols_directory):  # Include the subdirectory when the install layout provides it.
            self._search_roots.append(symbols_directory)  # Add the subdirectory as a secondary search root.
        self._parsed: Dict[str, Optional[SExp]] = {}  # Cache parsed library roots by library nickname.

    def find(self, lib_id: str) -> Optional[SExp]:  # Resolve one library identifier to its symbol node.
        nickname, name = _split_lib_id(lib_id)  # Split the identifier into nickname and symbol name.
        if nickname:  # Fast path: load only the library named by the nickname.
            library_root = self._load_library(nickname)  # Parse the nickname library file.
            symbol_node = _find_symbol_in_root(library_root, name)  # Search the library for the symbol.
            if symbol_node is not None:  # Stop when the named library contains the symbol.
                return symbol_node  # Return the resolved symbol node.
        if nickname != "":  # Stop when a named library was requested and did not contain the symbol.
            return None  # Return None so the caller can fall back to embedded definitions.
        for search_root in self._search_roots:  # Slow path: scan every library file for colon-less identifiers.
            try:  # Attempt to list the search directory.
                entries = sorted(os.listdir(search_root))  # List entries in deterministic order.
            except OSError:  # Skip directories that cannot be listed.
                continue  # Move to the next search root.
            for entry in entries:  # Walk every directory entry.
                if not entry.endswith(_KICAD_SYMBOL_EXTENSION):  # Skip non-library entries.
                    continue  # Move to the next entry.
                candidate_path = os.path.join(search_root, entry)  # Build the concrete library path for the text prefilter.
                try:  # Read metadata used to invalidate the prefilter cache.
                    file_stat = os.stat(candidate_path)  # Stat the candidate file.
                    if not _library_file_contains_symbol(candidate_path, file_stat.st_mtime_ns, file_stat.st_size, name):  # Avoid parsing libraries that cannot define the requested symbol.
                        continue  # Move to the next library file.
                except (OSError, UnicodeDecodeError):  # Skip unreadable candidate files.
                    continue  # Move to the next entry.
                library_root = self._load_library(entry[: -len(_KICAD_SYMBOL_EXTENSION)])  # Parse the library file.
                symbol_node = _find_symbol_in_root(library_root, name)  # Search for the symbol name.
                if symbol_node is not None:  # Stop at the first library that defines the symbol.
                    return symbol_node  # Return the resolved symbol node.
        return None  # Return None when no library defines the requested symbol.

    def _load_library(self, nickname: str) -> Optional[SExp]:  # Parse and cache one library file root.
        if nickname in self._parsed:  # Reuse a previously parsed library.
            return self._parsed[nickname]  # Return the cached root node.
        library_root: Optional[SExp] = None  # Default to a missing library.
        for search_root in self._search_roots:  # Walk every search root in order.
            candidate_path = os.path.join(search_root, nickname + _KICAD_SYMBOL_EXTENSION)  # Build the library path.
            if not os.path.isfile(candidate_path):  # Skip roots that do not contain the library file.
                continue  # Move to the next search root.
            try:  # Attempt to read and parse the library file.
                file_stat = os.stat(candidate_path)  # Read metadata used to invalidate the shared parse cache.
                library_root = _load_library_file(candidate_path, file_stat.st_mtime_ns, file_stat.st_size)  # Reuse the parsed read-only tree when unchanged.
                break  # Stop after the first readable library file.
            except (OSError, UnicodeDecodeError, ParseError):  # Treat unreadable libraries as missing.
                library_root = None  # Keep the missing-library default.
        self._parsed[nickname] = library_root  # Cache the parsed root (or None).
        return library_root  # Return the cached library root.


@lru_cache(maxsize=64)
def _load_library_file(candidate_path: str, _mtime_ns: int, _size: int) -> SExp:  # Parse one unchanged library file once per process.
    with open(candidate_path, "r", encoding="utf-8") as file_handle:  # Open the configured library path.
        return parse_string(file_handle.read())  # Parse and cache the read-only S-expression tree.


@lru_cache(maxsize=4096)
def _library_file_contains_symbol(candidate_path: str, _mtime_ns: int, _size: int, symbol_name: str) -> bool:  # Cheaply prefilter a library before full S-expression parsing.
    with open(candidate_path, "r", encoding="utf-8") as file_handle:  # Read the configured library text.
        library_text = file_handle.read()  # Load the text for an exact symbol declaration search.
    pattern = rf'\(\s*symbol\s+"{re.escape(symbol_name)}"(?=\s|\))'  # Match an exact quoted symbol name with flexible formatting.
    return re.search(pattern, library_text) is not None  # Report whether full parsing could find the requested symbol.


def kicad_sch_to_ltspice_netlist(  # Convert one KiCad schematic into one LTspice netlist file.
    kicad_sch_filepath: str,  # Accept the KiCad schematic input path.
    ltspice_netlist_filepath_out: str,  # Accept the LTspice netlist output path.
    convert_settings: Mapping,  # Accept the conversion configuration mapping.
) -> ConversionResult:  # Return the shared conversion result tuple.
    """Convert one KiCad ``.kicad_sch`` schematic into one LTspice ``.net`` netlist.

    Symbol definitions are resolved from the KiCad symbol libraries under
    ``convert_settings["kicad_path"]``. Power symbols become LTspice voltage
    sources named after their reference designator (without any leading ``#``)
    with the symbol value as the DC payload; ``GND``/``0`` power symbols become
    node ``0``. Inductors receive LTspice's standard ``Rser=1m`` default and
    three-pin BJT/MOSFET symbols receive the substrate node ``0``.

    Returns ``(True, "OK", 0)`` on success or ``(False, "<error code>", <line>)``
    on failure.
    """
    settings_result = _normalize_convert_settings(convert_settings)  # Validate the conversion settings first.
    if not settings_result[0]:  # Stop when the settings are unusable.
        return False, "INVALID_CONVERT_SETTINGS", 0  # Return the required settings error code.
    kicad_path = settings_result[1]  # Read the validated KiCad library path.
    output_result = _coerce_output_path(ltspice_netlist_filepath_out)  # Coerce the output path safely.
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
    build_result = _build_netlist_lines(parse_result[1], kicad_path)  # Build the LTspice netlist line list.
    if not build_result[0]:  # Stop when the conversion logic reports a failure.
        return False, build_result[2], build_result[3]  # Return the conversion error code and line.
    netlist_text = "\n".join(build_result[1]) + "\n"  # Join the generated lines into one netlist text.
    write_result = _write_text_file(output_path, netlist_text)  # Write the generated netlist file.
    if not write_result[0]:  # Stop when the output cannot be written.
        return False, "WRITE_ERROR", 0  # Return the required write error code.
    generated_result = is_valid_ltspice_netlist_file(output_path)  # Validate the freshly written netlist.
    if not generated_result[0]:  # Stop when the generated netlist fails validation.
        return False, "INVALID_GENERATED_NETLIST", _line_from_message(generated_result[1])  # Return the output line.
    return True, "OK", 0  # Return success when the conversion completed.


def _build_netlist_lines(root: SExp, kicad_path: str) -> Tuple[bool, List[str], str, int]:  # Build LTspice netlist lines from a parsed schematic.
    embedded_index = _build_embedded_symbol_index(root)  # Index the schematic's cached lib_symbols definitions.
    library_cache = _LibraryCache(kicad_path)  # Prepare the lazy kicad_path library cache.
    components: List[Dict[str, object]] = []  # Collect parsed symbol instances in file order.
    for index, instance_node in enumerate(root.find_children("symbol")):  # Walk every schematic symbol instance.
        parse_result = _parse_instance(instance_node, index)  # Parse the instance header and properties.
        if not parse_result[0]:  # Stop when an instance record is malformed.
            return False, [], parse_result[2], parse_result[3]  # Return the parse error code and line.
        record = parse_result[1]  # Read the parsed instance record.
        symbol_node = library_cache.find(record["lib_id"])  # Resolve the symbol in the kicad_path libraries.
        if symbol_node is None:  # Fall back to the schematic's embedded lib_symbols definition.
            symbol_node = embedded_index.get(record["lib_id"])  # Look up the cached definition.
        if symbol_node is None:  # Stop when the symbol cannot be resolved anywhere.
            message = f"UNKNOWN_KICAD_SYMBOL: Unable to locate KiCad symbol '{record['lib_id']}' in kicad_path or the schematic's lib_symbols section"  # Explain the failed lookup.
            return False, [], message, record["line"]  # Return the unknown symbol error with the instance line.
        record["power"] = symbol_node.find_child("power") is not None  # Detect power symbols from the library definition.
        record["symbol_props"] = _collect_properties(symbol_node)  # Collect the library symbol properties.
        exclude_result = _symbol_excluded_from_sim(symbol_node)  # Check the library-level simulation exclusion.
        if exclude_result:  # Respect the library-level exclusion flag.
            record["exclude"] = True  # Mark the instance as excluded from simulation.
        pins_result = _extract_symbol_pins(symbol_node, record["unit"], record["body_style"], _split_lib_id(str(record["lib_id"]))[1])  # Extract pin geometry.
        if not pins_result[0]:  # Stop when the symbol carries no usable pin graphics.
            message = f"UNKNOWN_KICAD_SYMBOL: symbol '{record['lib_id']}' has no pin definitions for unit {record['unit']}"  # Explain the missing graphics.
            return False, [], message, record["line"]  # Return the unknown symbol error with the instance line.
        record["symbol_pins"] = pins_result[1]  # Store the resolved pin geometry mapping.
        components.append(record)  # Append the finished instance record.
    netlist_result = _wire_and_emit(components, root)  # Trace connectivity and emit the device lines.
    if not netlist_result[0]:  # Stop when wiring or emission reports a failure.
        return netlist_result  # Return the wiring or emission error unchanged.
    return True, netlist_result[1], "", 0  # Return the generated netlist lines on success.


def _wire_and_emit(components: List[Dict[str, object]], root: SExp) -> Tuple[bool, List[str], str, int]:  # Trace nets and emit LTspice device lines.
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
    net_member_counts: Dict[str, int] = {}  # Count device-pin memberships per net.
    for record in components:  # Walk every parsed component.
        record["pin_nets"] = {}  # Prepare the pin-to-net mapping for this component.
        for pin_number in record["pin_numbers"]:  # Walk the instance pin numbers.
            pin_data = record["symbol_pins"].get(pin_number)  # Look up the library pin geometry.
            if pin_data is None:  # Stop when the library symbol lacks this pin.
                message = f"UNCONNECTED_SYMBOL_PIN: pin {pin_number} of '{record['reference']}' has no library pin definition"  # Explain the missing pin.
                return False, [], message, record["line"]  # Return the unconnected pin error.
            pin_x, pin_y, _pin_name = pin_data  # Read the local pin coordinates.
            absolute_x, absolute_y = _transform_point(pin_x, pin_y, float(record["x"]), float(record["y"]), float(record["angle"]), str(record["mirror"]))  # Compute the schematic-space pin position.
            pin_key = _attach_point(union_find, segments, absolute_x, absolute_y)  # Attach the pin to its electrical net.
            pin_root = union_find.find(pin_key)  # Resolve the pin net representative.
            if pin_key in no_connect_keys:  # Detect pins marked with a no-connect flag.
                no_connect_name = f"NC_{record['reference']}_{pin_number}"  # Build an exempt no-connect net name.
                if pin_root not in net_names:  # Assign the no-connect name when the net is unnamed.
                    net_names[pin_root] = no_connect_name  # Record the no-connect name.
            record["pin_nets"][pin_number] = pin_root  # Store the pin net representative.
            net_member_counts[pin_root] = net_member_counts.get(pin_root, 0) + 1  # Count the pin membership.
            if record["power"]:  # Power symbols name their net after their value.
                power_value = record["value"]  # Read the power symbol value.
                if power_value != "" and pin_root not in net_names:  # Assign the first power value as the net name.
                    net_names[pin_root] = power_value  # Record the power net name.
    member_order: Dict[str, Tuple[int, int]] = {}  # Track the earliest component/pin member per net for naming.
    for record in components:  # Walk every component to seed the naming order.
        for pin_number, pin_root in record["pin_nets"].items():  # Walk every pin-to-net association.
            member_key = (record["index"], _pin_sort_key(pin_number))  # Build a deterministic member ordering key.
            if pin_root not in member_order or member_key < member_order[pin_root]:  # Keep the earliest member key.
                member_order[pin_root] = member_key  # Record the earliest member key.
    unnamed_roots = sorted(root_key for root_key in member_order if root_key not in net_names)  # Order unnamed nets deterministically.
    for counter, root_key in enumerate(unnamed_roots, start=1):  # Name each unnamed net in order.
        net_names[root_key] = f"N{counter:03d}"  # Assign the sequential LTspice-style net name.
    for record in components:  # Walk every component again to reject lone floating pins.
        for pin_number, pin_root in record["pin_nets"].items():  # Walk every pin net.
            net_name = net_names.get(pin_root, "")  # Read the resolved net name.
            if net_name.upper() in _GROUND_VALUES:  # Skip ground nets.
                continue  # Move to the next pin.
            if net_name.upper().startswith(_NO_CONNECT_PREFIXES):  # Skip explicitly marked no-connect pins.
                continue  # Move to the next pin.
            if record["power"]:  # Power pins may sit on nets referenced only by behavioral expressions.
                continue  # Move to the next pin.
            if str(record["reference"])[:1].upper() == "B":  # Behavioral source pins may sit on probe nets referenced only by expressions.
                continue  # Move to the next pin.
            if net_member_counts.get(pin_root, 0) < 2:  # Require at least two device ports on ordinary nets.
                message = f"UNCONNECTED_SYMBOL_PIN: pin {pin_number} of '{record['reference']}' is not connected to another component"  # Explain the floating pin.
                return False, [], message, record["line"]  # Return the unconnected pin error.
    emit_result = _emit_device_lines(components, net_names)  # Emit the LTspice device lines.
    if not emit_result[0]:  # Stop when device emission reports a failure.
        return emit_result  # Return the emission error unchanged.
    lines = emit_result[1]  # Read the emitted device lines.
    lines.append(_DEFAULT_ANALYSIS_DIRECTIVE)  # Append the minimal analysis directive.
    lines.append(".backanno")  # Append the required back-annotation directive.
    lines.append(".end")  # Append the required netlist terminator.
    return True, lines, "", 0  # Return the completed netlist lines.


def _emit_device_lines(components: List[Dict[str, object]], net_names: Dict[str, str]) -> Tuple[bool, List[str], str, int]:  # Emit LTspice device lines from parsed components.
    lines: List[str] = []  # Collect the emitted device lines in schematic order.
    for record in components:  # Walk every parsed component in file order.
        if record["exclude"]:  # Skip components excluded from simulation.
            continue  # Move to the next component.
        reference = record["reference"]  # Read the instance reference designator.
        value = record["value"]  # Read the instance value.
        if record["power"]:  # Handle power symbols specially.
            if value.upper() in _GROUND_VALUES:  # Skip ground power symbols; their net already maps to node 0.
                continue  # Move to the next component.
            if reference == "" or value == "":  # Require a usable reference and value on power symbols.
                return False, [], "MISSING_COMPONENT_PAYLOAD: power symbol is missing its Reference or Value property", record["line"]  # Return the payload error.
            source_name = reference.lstrip("#")  # Strip the leading hash from power references.
            if not record["pin_numbers"]:  # Require at least one pin on the power symbol.
                return False, [], "UNCONNECTED_SYMBOL_PIN: power symbol has no pins", record["line"]  # Return the pin error.
            pin_root = record["pin_nets"][record["pin_numbers"][0]]  # Resolve the power pin net.
            node_name = _node_name_for_net(pin_root, net_names)  # Convert the net into an LTspice node token.
            lines.append(f"{source_name} {node_name} 0 {value}")  # Emit the power-derived voltage source.
            continue  # Move to the next component.
        if reference == "":  # Require a reference designator on ordinary components.
            return False, [], "MISSING_COMPONENT_PAYLOAD: component is missing its Reference property", record["line"]  # Return the payload error.
        if value == "":  # Require a value or model payload on ordinary components.
            return False, [], "MISSING_COMPONENT_PAYLOAD: component is missing its Value property", record["line"]  # Return the payload error.
        prefix = reference[0].upper()  # Read the LTspice device prefix from the reference.
        if prefix == "U":  # Map KiCad U references onto LTspice subcircuit calls.
            prefix = "X"  # Use the subcircuit prefix.
        sim_device = str(record["properties"].get("Sim.Device") or record["symbol_props"].get("Sim.Device") or "").upper()  # Read the simulation device class.
        if sim_device in _SUBCKT_SIM_DEVICES:  # Force subcircuit emission for SPICE/SUBCKT devices.
            prefix = "X"  # Use the subcircuit prefix.
        if prefix not in _VALID_DEVICE_PREFIXES:  # Reject references whose prefix has no LTspice device class.
            return False, [], f"MISSING_COMPONENT_PAYLOAD: reference '{reference}' has no supported LTspice device prefix", record["line"]  # Return the prefix error.
        ordered_pins = _ordered_pin_numbers(record)  # Order the pin numbers by SPICE node order.
        node_tokens: List[str] = []  # Collect the ordered node tokens.
        for pin_number in ordered_pins:  # Walk the ordered pin numbers.
            pin_root = record["pin_nets"].get(pin_number)  # Resolve each pin net.
            if pin_root is None:  # Stop when a pin has no resolved net.
                return False, [], f"UNCONNECTED_SYMBOL_PIN: pin {pin_number} of '{reference}' has no resolved net", record["line"]  # Return the pin error.
            node_tokens.append(_node_name_for_net(pin_root, net_names))  # Append the node token in order.
        if prefix in _SUBSTRATE_DEFAULT_PREFIXES and len(node_tokens) == 3:  # Emulate LTspice's substrate default.
            node_tokens.append("0")  # Append the substrate node 0 for three-pin transistors.
        payload_tokens = _payload_tokens(prefix, value)  # Build the value/model payload tokens.
        instance_name = f"X{reference}" if prefix == "X" and reference.upper().startswith("U") else reference  # Prefix remapped U references for subcircuits.
        lines.append(" ".join([instance_name] + node_tokens + payload_tokens))  # Emit the completed device line.
    return True, lines, "", 0  # Return the emitted device lines.


def _payload_tokens(prefix: str, value: str) -> List[str]:  # Build the value payload tokens for one device class.
    if prefix == "L":  # Inductors carry LTspice's standard series resistance default.
        tokens = value.split()  # Split the inductor value payload into tokens.
        if any(token.lower().startswith("rser=") for token in tokens):  # Keep an explicitly stored series resistance.
            return tokens  # Return the stored payload unchanged.
        return tokens + ["Rser=1m"]  # Append the LTspice inductor default when the payload omits it.
    if prefix in {"V", "I"}:  # Source values may carry SPICE waveform phrases.
        return value.split()  # Split the source payload into individual tokens.
    return [value]  # Return the plain value token for all other devices.


def _ordered_pin_numbers(record: Dict[str, object]) -> List[str]:  # Order instance pin numbers by SPICE node order.
    pin_numbers = record["pin_numbers"]  # Read the instance pin number list.
    sim_pins_text = str(record["properties"].get("Sim.Pins") or record["symbol_props"].get("Sim.Pins") or "")  # Read the Sim.Pins role mapping.
    if sim_pins_text == "":  # Fall back to ascending pin-number order without roles.
        return sorted(pin_numbers, key=_pin_sort_key)  # Return the numerically ordered pins.
    role_map: Dict[str, str] = {}  # Map pin numbers onto their SPICE role names.
    token_order: List[str] = []  # Preserve the role declaration order.
    for token in sim_pins_text.split():  # Walk the space-separated Sim.Pins tokens.
        if "=" not in token:  # Skip tokens without a pin-role assignment.
            continue  # Move to the next token.
        pin_part, role_part = token.split("=", 1)  # Split the pin number from the role.
        pin_part = pin_part.strip()  # Normalize the pin number token.
        role_part = role_part.strip()  # Normalize the role token.
        if pin_part not in role_map:  # Keep the first role declared for each pin.
            role_map[pin_part] = role_part  # Record the pin-to-role mapping.
            token_order.append(pin_part)  # Preserve the declaration order.
    sim_device = str(record["properties"].get("Sim.Device") or record["symbol_props"].get("Sim.Device") or "").upper()  # Read the device class.
    role_order = _ROLE_ORDER.get(sim_device)  # Look up the SPICE node ordering for the device class.
    if role_order is not None:  # Reorder pins by the known role sequence.
        role_rank = {role: rank for rank, role in enumerate(role_order)}  # Index the role sequence.
        def role_key(pin_number: str) -> Tuple[int, int]:  # Build the sort key for one pin number.
            role = role_map.get(pin_number)  # Read the assigned role.
            if role is not None and role in role_rank:  # Rank known roles by their SPICE position.
                return (0, role_rank[role])  # Return the role rank key.
            if pin_number in token_order:  # Rank unknown roles by declaration position.
                return (1, token_order.index(pin_number))  # Return the declaration position key.
            return (2, _pin_sort_key(pin_number))  # Rank unmapped pins after all role pins.
        return sorted(pin_numbers, key=role_key)  # Return the role-ordered pins.
    ordered = [pin for pin in token_order if pin in pin_numbers]  # Keep declared pins in declaration order.
    for pin_number in sorted(pin_numbers, key=_pin_sort_key):  # Append remaining pins numerically.
        if pin_number not in ordered:  # Skip pins already included by the declaration order.
            ordered.append(pin_number)  # Append the remaining pin.
    return ordered  # Return the declaration-ordered pins.


def _pin_sort_key(pin_number: str) -> Tuple[int, str]:  # Build a numeric-first sort key for one pin number.
    if str(pin_number).isdigit():  # Numeric pin numbers sort before symbolic ones.
        return (0, int(str(pin_number)))  # Return the integer key for numeric pins.
    return (1, str(pin_number))  # Return the string key for symbolic pins.


def _node_name_for_net(net_root: str, net_names: Dict[str, str]) -> str:  # Convert a net representative into an LTspice node token.
    name = net_names.get(net_root, "")  # Read the assigned net name.
    if name.upper() in _GROUND_VALUES:  # Ground-named nets always map to node 0.
        return "0"  # Return the LTspice ground node.
    sanitized = "".join("_" if char.isspace() else char for char in name)  # Replace whitespace inside node names.
    return sanitized if sanitized != "" else net_root  # Return the sanitized name or the raw representative.


def _parse_instance(node: SExp, index: int) -> Tuple[bool, Optional[Dict[str, object]], str, int]:  # Parse one schematic symbol instance node.
    line = _node_line_or(node, 1)  # Resolve the instance source line.
    lib_id_node = node.find_child("lib_id")  # Locate the library identifier section.
    lib_id = ""  # Default to an empty library identifier.
    if lib_id_node is not None:  # Read the identifier when present.
        lib_id_values = [child.value for child in lib_id_node.children if child.is_atom]  # Collect identifier atoms.
        lib_id = str(lib_id_values[0]) if lib_id_values else ""  # Extract the identifier text.
    if lib_id == "":  # Require a library identifier on every instance.
        return False, None, "KICAD_SCH_PARSE_ERROR", line  # Return the parse error for the missing identifier.
    at_node = node.find_child("at")  # Locate the position section.
    at_values = [child.value for child in at_node.children if child.is_atom] if at_node is not None else []  # Collect position atoms.
    if len(at_values) < 2:  # Require X and Y coordinates on every instance.
        return False, None, "KICAD_SCH_PARSE_ERROR", line  # Return the parse error for the missing position.
    instance_x = float(at_values[0])  # Read the X coordinate.
    instance_y = float(at_values[1])  # Read the Y coordinate.
    instance_angle = float(at_values[2]) if len(at_values) > 2 else 0.0  # Read the optional rotation angle.
    unit_node = node.find_child("unit")  # Locate the unit section.
    unit = 1  # Default to the first unit.
    if unit_node is not None:  # Read the unit when present.
        unit_values = [child.value for child in unit_node.children if child.is_atom]  # Collect unit atoms.
        unit = int(unit_values[0]) if unit_values else 1  # Extract the unit ordinal.
    body_style_node = node.find_child("body_style")  # Locate the body style section.
    body_style = 1  # Default to the standard body style.
    if body_style_node is not None:  # Read the body style when present.
        style_values = [child.value for child in body_style_node.children if child.is_atom]  # Collect style atoms.
        body_style = int(style_values[0]) if style_values else 1  # Extract the style ordinal.
    mirror = ""  # Default to no mirroring.
    mirror_node = node.find_child("mirror")  # Locate the optional mirror section.
    if mirror_node is not None:  # Read the mirror flag when present.
        mirror_values = [child.value for child in mirror_node.children if child.is_atom]  # Collect mirror atoms.
        mirror = str(mirror_values[0]) if mirror_values else ""  # Extract the mirror axis.
    exclude = False  # Default to simulation inclusion.
    exclude_node = node.find_child("exclude_from_sim")  # Locate the simulation exclusion flag.
    if exclude_node is not None:  # Read the flag when present.
        exclude_values = [child.value for child in exclude_node.children if child.is_atom]  # Collect flag atoms.
        exclude = str(exclude_values[0]).lower() == "yes" if exclude_values else False  # Parse the flag value.
    properties = _collect_properties(node)  # Collect the instance property overrides.
    pin_numbers: List[str] = []  # Collect the instance pin numbers in file order.
    for pin_node in node.find_children("pin"):  # Walk the instance pin sections.
        pin_values = [child.value for child in pin_node.children if child.is_atom]  # Collect pin number atoms.
        if pin_values:  # Keep pins that carry a number.
            pin_numbers.append(str(pin_values[0]))  # Store the pin number as text.
    record: Dict[str, object] = {  # Assemble the parsed instance record.
        "index": index,  # Store the schematic file order index.
        "line": line,  # Store the source line for error reporting.
        "lib_id": lib_id,  # Store the library identifier.
        "x": instance_x,  # Store the placement X coordinate.
        "y": instance_y,  # Store the placement Y coordinate.
        "angle": instance_angle,  # Store the placement rotation angle.
        "mirror": mirror,  # Store the optional mirror axis.
        "unit": unit,  # Store the symbol unit ordinal.
        "body_style": body_style,  # Store the symbol body style ordinal.
        "exclude": exclude,  # Store the simulation exclusion flag.
        "properties": properties,  # Store the instance property overrides.
        "reference": properties.get("Reference", ""),  # Store the reference designator.
        "value": properties.get("Value", ""),  # Store the value payload.
        "pin_numbers": pin_numbers,  # Store the pin number list.
        "power": False,  # Initialize the power-symbol marker.
        "symbol_props": {},  # Initialize the library property map.
        "symbol_pins": {},  # Initialize the library pin geometry map.
        "pin_nets": {},  # Initialize the pin-to-net mapping.
    }  # Finish the record assembly.
    return True, record, "", 0  # Return the parsed instance record.


def _collect_properties(node: SExp) -> Dict[str, str]:  # Collect key-value properties from one node.
    properties: Dict[str, str] = {}  # Collect the property mapping.
    for property_node in node.find_children("property"):  # Walk the property sections.
        property_values = [child.value for child in property_node.children if child.is_atom]  # Collect property atoms.
        if len(property_values) >= 2:  # Require a key and a value.
            properties[str(property_values[0])] = str(property_values[1])  # Store the property pair.
    return properties  # Return the collected property mapping.


def _symbol_excluded_from_sim(symbol_node: SExp) -> bool:  # Read the library-level simulation exclusion flag.
    exclude_node = symbol_node.find_child("exclude_from_sim")  # Locate the exclusion section.
    if exclude_node is None:  # Treat a missing flag as simulation inclusion.
        return False  # Return False when no flag exists.
    exclude_values = [child.value for child in exclude_node.children if child.is_atom]  # Collect flag atoms.
    if not exclude_values:  # Treat an empty flag as simulation inclusion.
        return False  # Return False when the flag is empty.
    return str(exclude_values[0]).lower() == "yes"  # Return the parsed flag value.


def _build_embedded_symbol_index(root: SExp) -> Dict[str, SExp]:  # Index the schematic's embedded lib_symbols definitions.
    index: Dict[str, SExp] = {}  # Collect symbols keyed by their full library identifier.
    lib_symbols_node = root.find_child("lib_symbols")  # Locate the embedded library section.
    if lib_symbols_node is None:  # Return early when the schematic caches no symbols.
        return index  # Return the empty index.
    for symbol_node in lib_symbols_node.find_children("symbol"):  # Walk every cached symbol.
        symbol_values = [child.value for child in symbol_node.children if child.is_atom]  # Collect the symbol name atoms.
        if symbol_values:  # Index symbols that carry a name.
            index[str(symbol_values[0])] = symbol_node  # Store the symbol under its full identifier.
    return index  # Return the completed embedded index.


def _split_lib_id(lib_id: str) -> Tuple[str, str]:  # Split a library identifier into nickname and symbol name.
    if ":" in lib_id:  # Split identifiers that carry a nickname.
        nickname, name = lib_id.split(":", 1)  # Split at the first colon.
        return nickname, name  # Return the nickname and symbol name.
    return "", lib_id  # Return an empty nickname for plain symbol names.


def _find_symbol_in_root(library_root: Optional[SExp], symbol_name: str) -> Optional[SExp]:  # Find one symbol inside a library root.
    if library_root is None:  # Return early for missing libraries.
        return None  # Return None when the library root is absent.
    for symbol_node in library_root.find_children("symbol"):  # Walk the top-level symbol definitions.
        symbol_values = [child.value for child in symbol_node.children if child.is_atom]  # Collect the name atoms.
        if symbol_values and str(symbol_values[0]) == symbol_name:  # Match the requested symbol name.
            return symbol_node  # Return the matching symbol node.
    return None  # Return None when the symbol is not defined in this library.


def _extract_symbol_pins(symbol_node: SExp, unit: int, body_style: int, symbol_name: str) -> Tuple[bool, Dict[str, Tuple[float, float, str]]]:  # Extract pin geometry from a symbol definition.
    unit_prefix = f"{symbol_name}_{unit}_"  # Build the sub-symbol name prefix for this unit.
    preferred_name = f"{symbol_name}_{unit}_{body_style}"  # Build the preferred sub-symbol name.
    fallback_name = f"{symbol_name}_{unit}_1"  # Build the standard body style fallback name.
    sub_symbols = symbol_node.find_children("symbol")  # Collect the nested unit sub-symbols.
    chosen: Optional[SExp] = None  # Initialize the chosen sub-symbol.
    for sub_symbol in sub_symbols:  # First pass: match the exact preferred name.
        if _first_atom_value(sub_symbol) == preferred_name:  # Detect the preferred sub-symbol.
            chosen = sub_symbol  # Select the preferred sub-symbol.
            break  # Stop searching.
    if chosen is None:  # Second pass: match the standard body style fallback.
        for sub_symbol in sub_symbols:  # Walk the sub-symbols again.
            if _first_atom_value(sub_symbol) == fallback_name:  # Detect the fallback sub-symbol.
                chosen = sub_symbol  # Select the fallback sub-symbol.
                break  # Stop searching.
    if chosen is None:  # Third pass: accept any sub-symbol of the requested unit.
        for sub_symbol in sub_symbols:  # Walk the sub-symbols one last time.
            name_value = _first_atom_value(sub_symbol)  # Read the sub-symbol name.
            if name_value is not None and str(name_value).startswith(unit_prefix):  # Match the unit prefix.
                chosen = sub_symbol  # Select the first unit-matching sub-symbol.
                break  # Stop searching.
    if chosen is None:  # Fail when the unit carries no graphics.
        return False, {}  # Signal the missing pin graphics.
    pins: Dict[str, Tuple[float, float, str]] = {}  # Collect pins keyed by their number.
    for pin_node in chosen.find_children("pin"):  # Walk the pin definitions.
        at_node = pin_node.find_child("at")  # Locate the pin position section.
        number_node = pin_node.find_child("number")  # Locate the pin number section.
        if at_node is None or number_node is None:  # Skip pins without position or number data.
            continue  # Move to the next pin.
        at_values = [child.value for child in at_node.children if child.is_atom]  # Collect position atoms.
        number_values = [child.value for child in number_node.children if child.is_atom]  # Collect number atoms.
        if len(at_values) < 2 or not number_values:  # Skip pins with incomplete data.
            continue  # Move to the next pin.
        pin_number = str(number_values[0])  # Read the pin number text.
        pin_name = ""  # Default to an unnamed pin.
        name_node = pin_node.find_child("name")  # Locate the optional pin name section.
        if name_node is not None:  # Read the name when present.
            name_values = [child.value for child in name_node.children if child.is_atom]  # Collect name atoms.
            pin_name = str(name_values[0]) if name_values else ""  # Extract the pin name text.
        pins[pin_number] = (float(at_values[0]), float(at_values[1]), pin_name)  # Store the pin geometry.
    if not pins:  # Fail when the sub-symbol defines no usable pins.
        return False, {}  # Signal the missing pin definitions.
    return True, pins  # Return the extracted pin geometry mapping.


def _transform_point(local_x: float, local_y: float, origin_x: float, origin_y: float, angle: float, mirror: str) -> Tuple[float, float]:  # Transform a symbol-local point into schematic coordinates.
    if mirror == "x":  # Mirror across the vertical symbol axis.
        local_x = -local_x  # Negate the local X coordinate.
    elif mirror == "y":  # Mirror across the horizontal symbol axis.
        local_y = -local_y  # Negate the local Y coordinate.
    screen_x = local_x  # Start the schematic offset with the mirrored X coordinate.
    screen_y = -local_y  # Flip the Y axis from symbol space into schematic space.
    radians = math.radians(angle)  # Convert the placement angle to radians.
    cosine = math.cos(radians)  # Compute the rotation cosine.
    sine = math.sin(radians)  # Compute the rotation sine.
    rotated_x = screen_x * cosine - screen_y * sine  # Rotate the X offset clockwise.
    rotated_y = screen_x * sine + screen_y * cosine  # Rotate the Y offset clockwise.
    return origin_x + rotated_x, origin_y + rotated_y  # Return the absolute schematic position.


def _collect_wire_segments(root: SExp, union_find: _UnionFind) -> List[Tuple[float, float, float, float, str, str]]:  # Collect wire polylines as merged point segments.
    segments: List[Tuple[float, float, float, float, str, str]] = []  # Collect the segment records.
    for wire_node in root.find_children("wire"):  # Walk the wire sections.
        points_node = wire_node.find_child("pts")  # Locate the polyline point list.
        if points_node is None:  # Skip wires without a point list.
            continue  # Move to the next wire.
        coordinates: List[Tuple[float, float]] = []  # Collect the polyline coordinates.
        for xy_node in points_node.find_children("xy"):  # Walk the coordinate pairs.
            xy_values = [child.value for child in xy_node.children if child.is_atom]  # Collect coordinate atoms.
            if len(xy_values) >= 2:  # Keep complete coordinate pairs.
                coordinates.append((float(xy_values[0]), float(xy_values[1])))  # Store the coordinate pair.
        if len(coordinates) < 2:  # Skip degenerate wires with fewer than two points.
            continue  # Move to the next wire.
        for position in range(len(coordinates) - 1):  # Split the polyline into consecutive segments.
            start_x, start_y = coordinates[position]  # Read the segment start point.
            end_x, end_y = coordinates[position + 1]  # Read the segment end point.
            start_key = _point_key(start_x, start_y)  # Register the start point key.
            end_key = _point_key(end_x, end_y)  # Register the end point key.
            union_find.add(start_key)  # Ensure the start point exists.
            union_find.add(end_key)  # Ensure the end point exists.
            union_find.union(start_key, end_key)  # Join the endpoints through the segment.
            segments.append((start_x, start_y, end_x, end_y, start_key, end_key))  # Store the segment record.
    return segments  # Return the collected wire segments.


def _collect_junction_positions(root: SExp) -> List[Tuple[float, float]]:  # Collect schematic junction positions.
    positions: List[Tuple[float, float]] = []  # Collect the junction coordinates.
    for junction_node in root.find_children("junction"):  # Walk the junction sections.
        at_node = junction_node.find_child("at")  # Locate the junction position.
        if at_node is None:  # Skip junctions without a position.
            continue  # Move to the next junction.
        at_values = [child.value for child in at_node.children if child.is_atom]  # Collect position atoms.
        if len(at_values) >= 2:  # Keep complete junction positions.
            positions.append((float(at_values[0]), float(at_values[1])))  # Store the junction position.
    return positions  # Return the collected junction positions.


def _collect_label_entries(root: SExp) -> List[Tuple[float, float, str]]:  # Collect label, global label, and hierarchical label entries.
    entries: List[Tuple[float, float, str]] = []  # Collect the label entries.
    for tag in ("label", "global_label", "hierarchical_label"):  # Walk every supported label kind.
        for label_node in root.find_children(tag):  # Walk the labels of this kind.
            text_values = [child.value for child in label_node.children if child.is_atom]  # Collect the label text atoms.
            label_text = str(text_values[0]) if text_values else ""  # Extract the label text.
            at_node = label_node.find_child("at")  # Locate the label position.
            if at_node is None:  # Skip labels without a position.
                continue  # Move to the next label.
            at_values = [child.value for child in at_node.children if child.is_atom]  # Collect position atoms.
            if len(at_values) < 2:  # Skip labels with incomplete positions.
                continue  # Move to the next label.
            entries.append((float(at_values[0]), float(at_values[1]), label_text))  # Store the label entry.
    return entries  # Return the collected label entries.


def _collect_no_connect_positions(root: SExp) -> List[Tuple[float, float]]:  # Collect no-connect marker positions.
    positions: List[Tuple[float, float]] = []  # Collect the no-connect coordinates.
    for no_connect_node in root.find_children("no_connect"):  # Walk the no-connect sections.
        at_node = no_connect_node.find_child("at")  # Locate the marker position.
        if at_node is None:  # Skip markers without a position.
            continue  # Move to the next marker.
        at_values = [child.value for child in at_node.children if child.is_atom]  # Collect position atoms.
        if len(at_values) >= 2:  # Keep complete marker positions.
            positions.append((float(at_values[0]), float(at_values[1])))  # Store the marker position.
    return positions  # Return the collected no-connect positions.


def _attach_point(union_find: _UnionFind, segments: Sequence[Tuple[float, float, float, float, str, str]], x: float, y: float) -> str:  # Attach one schematic position to its electrical net.
    key = _point_key(x, y)  # Build the position point key.
    union_find.add(key)  # Ensure the point exists in the disjoint set.
    for segment in segments:  # Search for a segment passing through the position.
        if _point_on_segment(x, y, segment):  # Detect the carrying segment.
            union_find.union(key, segment[4])  # Join the position to the carrying net.
            break  # Stop after the first carrying segment.
    return key  # Return the attached point key.


def _point_on_segment(px: float, py: float, segment: Tuple[float, float, float, float, str, str]) -> bool:  # Decide whether a point lies on one wire segment.
    start_x, start_y, end_x, end_y = segment[0], segment[1], segment[2], segment[3]  # Read the segment endpoints.
    if px < min(start_x, end_x) - _POINT_TOLERANCE or px > max(start_x, end_x) + _POINT_TOLERANCE:  # Reject points outside the X span.
        return False  # Return False for non-overlapping X coordinates.
    if py < min(start_y, end_y) - _POINT_TOLERANCE or py > max(start_y, end_y) + _POINT_TOLERANCE:  # Reject points outside the Y span.
        return False  # Return False for non-overlapping Y coordinates.
    delta_x = end_x - start_x  # Compute the segment X extent.
    delta_y = end_y - start_y  # Compute the segment Y extent.
    length_squared = delta_x * delta_x + delta_y * delta_y  # Compute the squared segment length.
    if length_squared == 0.0:  # Handle degenerate zero-length segments.
        return abs(px - start_x) <= _POINT_TOLERANCE and abs(py - start_y) <= _POINT_TOLERANCE  # Return the point-equality check.
    projection = ((px - start_x) * delta_x + (py - start_y) * delta_y) / length_squared  # Project the point onto the segment.
    if projection < -1e-9 or projection > 1.0 + 1e-9:  # Reject projections beyond the segment endpoints.
        return False  # Return False for out-of-range projections.
    closest_x = start_x + projection * delta_x  # Compute the closest X coordinate on the segment.
    closest_y = start_y + projection * delta_y  # Compute the closest Y coordinate on the segment.
    return abs(px - closest_x) <= _POINT_TOLERANCE and abs(py - closest_y) <= _POINT_TOLERANCE  # Return the distance check.


def _point_key(x: float, y: float) -> str:  # Build a stable string key for one schematic position.
    return f"{round(x, 6)}|{round(y, 6)}"  # Round to KiCad's maximum file precision and join the coordinates.


def _normalize_convert_settings(convert_settings: Mapping) -> Tuple[bool, Optional[str]]:  # Validate the conversion settings and resolve kicad_path.
    if not isinstance(convert_settings, Mapping):  # Require a mapping-like settings object.
        return False, None  # Signal the settings failure.
    raw_path = convert_settings.get("kicad_path")  # Read the required KiCad library path.
    if not isinstance(raw_path, str) or raw_path.strip() == "":  # Require a nonempty path string.
        return False, None  # Signal the settings failure.
    expanded_path = os.path.expanduser(raw_path.strip())  # Expand any user-relative path prefix.
    if not os.path.isdir(expanded_path):  # Require the configured path to exist as a directory.
        return False, None  # Signal the settings failure.
    return True, expanded_path  # Return the resolved KiCad library path.


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


def _write_text_file(filepath: str, text: str) -> Tuple[bool, None]:  # Write the generated netlist text to disk safely.
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
