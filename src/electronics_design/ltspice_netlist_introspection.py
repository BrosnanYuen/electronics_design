"""Public netlist symbol-pin introspection helpers."""  # Describe the module purpose.

from __future__ import annotations  # Keep annotations lazy and consistent with the package code.

from typing import Any  # Type the per-device report entries.
from typing import Dict  # Type the return mapping.
from typing import List  # Type the collected device and SpiceOrder lists.
from typing import Mapping  # Type the convert_settings parameter.
from typing import Sequence  # Type the extracted node tuples.
from typing import Tuple  # Type the intermediate device records.

from . import ltspice_asc_to_netlist as _asc_to_netlist  # Reuse the shared symbol-file resolver.
from . import ltspice_net as _net  # Reuse the netlist reader, validator, and token helpers.
from . import ltspice_netlist_to_symbol_initial as _symbol_initial  # Reuse the symbol-name resolution helpers.
from .ltspice_asy import get_ltspice_asy_pins  # Read the .asy pin rows.
from .ltspice_library import build_node_device_index  # Index every node onto its device instances.
from .ltspice_library import validate_x_pin_coverage  # Validate X-line coverage against the .asy SpiceOrders.


def get_ltspice_netlist_device_pins(
    netlist_filepath: str,
    convert_settings: Mapping,
) -> Dict[str, Dict[str, Any]]:
    """Return per-device symbol pin compatibility information for one netlist.

    Every device entry carries the resolved symbol name (``SYMBOL``), the
    resolved ``.asy`` path (``ASY``), the ``.asy`` pin count
    (``ASY_PIN_COUNT``), the deck node count (``DECK_NODE_COUNT``), the
    declared ``SpiceOrder`` values (``SPICE_ORDERS``), the deck nodes left
    uncovered by any SpiceOrder (``UNCOVERED_NODES``), the device line number
    (``LINE``), and whether the deck nodes map onto the symbol pins
    (``VALID`` with an explanatory ``DETAIL``).

    ``VALID`` is ``True`` when no ``.asy`` symbol resolves (nothing to check),
    when an X subcircuit's nodes map onto its ``.asy`` SpiceOrders, or when a
    primitive device's node count equals its symbol pin count. It is ``False``
    when a resolved symbol cannot address every connected deck node.

    Raises ``ValueError`` when the netlist or the conversion settings are
    unusable.
    """

    if not isinstance(convert_settings, Mapping):  # Require a mapping-like settings object.
        raise ValueError("convert_settings must be a mapping")
    validation_result = _net.is_valid_ltspice_netlist_file(netlist_filepath)  # Validate the whole netlist first.
    if not validation_result[0]:  # Reject unusable netlists.
        raise ValueError(validation_result[1])
    read_result = _net._read_text_file_lines(netlist_filepath)  # Read the netlist text with encoding detection.
    if not read_result[0]:  # Reject unreadable netlists.
        raise ValueError("NETLIST_READ_ERROR")
    voltage_must_have_dc = _net._resolve_voltage_must_have_dc(convert_settings)  # Read the source normalization toggle.
    if voltage_must_have_dc is None:  # Reject malformed source normalization settings.
        raise ValueError("INVALID_CONVERT_SETTINGS")
    logical_lines = _symbol_initial._collect_logical_code_lines(read_result[1])  # Fold continuation lines into logical records.
    search_roots = _symbol_initial._resolve_search_roots_for_netlist(netlist_filepath, convert_settings)  # Resolve the configurable symbol roots.
    library_context = _symbol_initial._build_library_context(netlist_filepath, logical_lines, search_roots)  # Collect model and subcircuit metadata.
    coupled_inductors = _symbol_initial._collect_coupled_inductor_names(logical_lines)  # Recognize coupled-inductor statements.
    symbol_path_lookup = _asc_to_netlist._build_symbol_filepath_lookup(search_roots)  # Index every configured .asy file.
    comment_symbol_hints = _symbol_initial._extract_comment_symbol_hints(read_result[1])  # Restore symbol hints recorded in comments.
    symbol_records = _symbol_initial._build_symbol_initial_records(  # Resolve one symbol name per device like the converter does.
        logical_lines,
        library_context,
        coupled_inductors,
        symbol_path_lookup,
        {},
        comment_symbol_hints,
        voltage_must_have_dc,
    )
    devices: List[Tuple[str, str, Sequence[str], int]] = []  # Collect (instance, prefix, nodes, line) tuples.
    for logical_line in logical_lines:  # Walk every logical source line.
        if logical_line.kind != "device":  # Keep only device records.
            continue
        tokens = _net._normalize_voltage_source_tokens(logical_line.text.split(), voltage_must_have_dc)  # Normalize source tokens consistently.
        if not tokens or tokens[0][0].upper() == "K":  # Skip empty and node-free coupling records.
            continue
        instance_name = _symbol_initial._normalize_instance_name(tokens[0])  # Normalize hierarchy markers out of the reference.
        if instance_name == "":  # Skip unnameable records.
            continue
        node_result = _net._extract_nodes(tokens)  # Extract the connectivity nodes.
        if not node_result[0]:  # Skip records without connectivity.
            continue
        devices.append((instance_name, tokens[0][0].upper(), tuple(str(node) for node in node_result[1]), logical_line.line_number))
    node_devices = build_node_device_index([(instance_name, nodes) for instance_name, _prefix, nodes, _line in devices])  # Index node connectivity.
    report: Dict[str, Dict[str, Any]] = {}  # Collect the per-device report entries.
    for instance_name, prefix, nodes, line_number in devices:  # Walk every device once.
        symbol_name = str(symbol_records.get(instance_name, {}).get("SYMBOL", ""))  # Read the resolved symbol name.
        asy_path = _asc_to_netlist._resolve_symbol_filepath(symbol_name, symbol_path_lookup) if symbol_name else None  # Resolve the .asy file.
        spice_orders: List[int] = []  # Collect the declared SpiceOrder values.
        pin_count = 0  # Count the declared pins.
        parse_detail = ""  # Record an unreadable .asy file.
        if asy_path is not None:  # Only read symbols that resolved.
            try:  # Attempt the pin parse.
                spice_orders = sorted(int(pin_row[3]) for pin_row in get_ltspice_asy_pins(asy_path))  # Read and sort every SpiceOrder.
                pin_count = len(spice_orders)  # Count the declared pins.
            except (IndexError, TypeError, ValueError) as error:  # Treat malformed symbols as a reportable mismatch.
                parse_detail = f"ASY_PARSE_ERROR: {error}"
        coverage = set(spice_orders)  # Index the covered X-line positions.
        uncovered_nodes = [node for position, node in enumerate(nodes, start=1) if position not in coverage]  # Collect positions without a pin.
        if asy_path is None:  # Devices without a resolved symbol cannot be checked.
            valid = True
            detail = "no .asy symbol resolved"
        elif parse_detail != "":  # Unreadable symbols are reported as invalid.
            valid = False
            detail = parse_detail
        elif prefix == "X":  # X subcircuits use the sparse SpiceOrder coverage rule.
            coverage_error = validate_x_pin_coverage(instance_name, nodes, spice_orders, node_devices)  # Check every pin and gap.
            valid = coverage_error is None
            detail = coverage_error or ""
        else:  # Primitives require the symbol pin count to equal the deck node count.
            valid = pin_count == len(nodes)
            detail = "" if valid else (
                f"PIN_COUNT_MISMATCH: device '{instance_name}' lists {len(nodes)} node(s) "
                f"but symbol '{symbol_name}' declares {pin_count} pin(s)"
            )
        report[instance_name] = {  # Assemble the per-device report.
            "SYMBOL": symbol_name,
            "ASY": asy_path,
            "ASY_PIN_COUNT": pin_count,
            "DECK_NODE_COUNT": len(nodes),
            "SPICE_ORDERS": spice_orders,
            "UNCOVERED_NODES": uncovered_nodes,
            "LINE": line_number,
            "VALID": valid,
            "DETAIL": detail,
        }
    return report  # Return the per-device report mapping.
