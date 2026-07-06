"""Automatically place LTspice symbol poses and route wires from a netlist."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import tempfile
from typing import Dict
from typing import Iterable
from typing import List
from typing import Mapping
from typing import MutableMapping
from typing import Optional
from typing import Sequence
from typing import Tuple

import networkx as nx

from . import ltspice_asc as _asc
from . import ltspice_net as _net
from .ltspice_netlist_to_symbol_initial import ltspice_netlist_to_symbol_initial
from .ltspice_netlist_to_wiring import ltspice_netlist_to_wiring
from .ltspice_resolve_symbol_pose import ltspice_check_symbol_pose
from .ltspice_resolve_symbol_pose import ltspice_resolve_symbol_pose

ConversionResult = Tuple[bool, str, int]
Point = Tuple[int, int]
Rectangle = Tuple[int, int, int, int]

_OK_RESULT: ConversionResult = (True, "OK", 0)
_AUTOPLACE_ERROR: ConversionResult = (False, "AUTOPLACE_FAILED", 0)
_DEFAULT_AUTOPLACE_ITERATIONS = 12
_NO_CONNECT_PREFIXES = ("NC", "NC_", "NC-")
_GROUND_NETS = {"0", "GND"}
_SYMMETRIC_SYMBOL_NAMES = {
    "npn",
    "pnp",
    "njf",
    "pjf",
    "nmos",
    "pmos",
    "sw",
}
_GLOBAL_GEOMETRY_CACHE: Dict[Tuple[str, str], "OrientationGeometry"] = {}


@dataclass(frozen=True)
class PinGeometry:
    point: Point
    pin_name: str
    spice_order: int


@dataclass(frozen=True)
class OrientationGeometry:
    orientation: str
    rectangle: Rectangle
    pins: Tuple[PinGeometry, ...]
    width: int
    height: int
    center_offset: Tuple[float, float]


@dataclass(frozen=True)
class ComponentRecord:
    instance_name: str
    prefix: str
    line_number: int
    node_names: Tuple[str, ...]


@dataclass(frozen=True)
class PinConnection:
    instance_name: str
    line_number: int
    net_name: str
    pin_name: str
    spice_order: int


def ltspice_autoplace_symbol_pose(
    netlist_filepath: str,
    symbol_pose_filepath_out: str,
    wire_filepath_out: str,
    convert_settings: Mapping[str, object],
) -> ConversionResult:
    """Predict symbol positions/orientations, resolve poses, and route wires."""

    if not isinstance(convert_settings, Mapping):
        return False, "INVALID_CONVERT_SETTINGS", 0
    if not _coerce_path_success(symbol_pose_filepath_out) or not _coerce_path_success(wire_filepath_out):
        return False, "INVALID_OUTPUT_PATH", 0
    autoplace_iter = _resolve_autoplace_iterations(convert_settings)
    if autoplace_iter is None:
        return False, "INVALID_CONVERT_SETTINGS", 0
    format_validation_result = _net.is_valid_ltspice_netlist_format(netlist_filepath)
    if not format_validation_result[0]:
        return False, "INVALID_NETLIST_FILE", _line_number_from_message(format_validation_result[1], 0)
    with tempfile.TemporaryDirectory() as temporary_directory:
        working_symbol_pose_path = Path(temporary_directory) / "symbol_pose.json"
        initial_symbol_json_result = _prepare_working_symbol_pose_file(
            netlist_filepath,
            symbol_pose_filepath_out,
            str(working_symbol_pose_path),
            convert_settings,
        )
        if not initial_symbol_json_result[0]:
            return initial_symbol_json_result
        original_symbol_data = _read_symbol_json_mapping(str(working_symbol_pose_path))
        if original_symbol_data is None:
            return False, "SYMBOL_JSON_PARSE_ERROR", 0
        read_result = _net._read_text_file_lines(netlist_filepath)
        if not read_result[0]:
            return False, "NETLIST_READ_ERROR", 0
        components = _collect_component_records(read_result[1])
        if not components:
            return _AUTOPLACE_ERROR
        missing_instances = sorted(instance_name for instance_name in components if instance_name not in original_symbol_data)
        if missing_instances:
            return False, "SYMBOL_JSON_PARSE_ERROR", 0
        geometry_cache = _GLOBAL_GEOMETRY_CACHE
        try:
            candidate_orientations = {
                instance_name: _candidate_orientations_for_entry(original_symbol_data[instance_name])
                for instance_name in components
            }
            default_geometries = {
                instance_name: _resolve_default_geometry(
                    instance_name,
                    original_symbol_data[instance_name],
                    candidate_orientations[instance_name],
                    geometry_cache,
                    convert_settings,
                )
                for instance_name in components
            }
        except ValueError:
            return _AUTOPLACE_ERROR
        pin_connections_by_instance = _build_pin_connections_by_instance(components, default_geometries)
        component_graph = _build_component_graph(pin_connections_by_instance)
        routing_grid = _infer_layout_grid(default_geometries.values(), convert_settings)
        minimum_dist = _resolve_non_negative_integer(convert_settings.get("minimum_dist", 0))
        if minimum_dist is None:
            return False, "INVALID_CONVERT_SETTINGS", 0
        base_positions = _build_initial_positions(
            component_graph,
            default_geometries,
            minimum_dist,
            routing_grid,
        )
        current_orientations = {
            instance_name: default_geometries[instance_name].orientation
            for instance_name in components
        }
        current_positions = dict(base_positions)
        should_attempt_routing = True
        ordered_instance_names = tuple(instance_name for instance_name in original_symbol_data if instance_name in components)
        best_attempt_payload: Optional[dict[str, dict[str, object]]] = None
        best_attempt_wires: Optional[str] = None
        for iteration_index in range(autoplace_iter):
            try:
                current_orientations = _choose_orientations(
                    current_positions,
                    current_orientations,
                    original_symbol_data,
                    candidate_orientations,
                    geometry_cache,
                    pin_connections_by_instance,
                    convert_settings,
                )
                current_geometries = {
                    instance_name: _geometry_for_orientation(
                        original_symbol_data[instance_name],
                        current_orientations[instance_name],
                        geometry_cache,
                        convert_settings,
                    )
                    for instance_name in components
                }
            except ValueError:
                return _AUTOPLACE_ERROR
            current_positions = _relax_positions(
                current_positions,
                current_geometries,
                pin_connections_by_instance,
                minimum_dist,
                routing_grid,
            )
            current_positions = _resolve_collisions(
                current_positions,
                current_geometries,
                minimum_dist,
                routing_grid,
            )
            current_positions = _expand_layout_for_iteration(
                current_positions,
                iteration_index,
                routing_grid,
            )
            current_positions = _resolve_collisions(
                current_positions,
                current_geometries,
                minimum_dist,
                routing_grid,
            )
            candidate_payload = _build_symbol_pose_payload(
                original_symbol_data,
                current_positions,
                current_orientations,
            )
            working_symbol_pose_path.write_text(
                json.dumps(candidate_payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            resolve_result = ltspice_resolve_symbol_pose(str(working_symbol_pose_path), convert_settings)
            if not resolve_result[0]:
                return resolve_result
            collision_result = ltspice_check_symbol_pose(str(working_symbol_pose_path), convert_settings)
            if collision_result[0]:
                resolved_symbol_data = _read_symbol_json_mapping(str(working_symbol_pose_path))
                if resolved_symbol_data is not None:
                    current_positions = _spread_colliding_symbols(
                        current_positions,
                        current_geometries,
                        collision_result[1],
                        ordered_instance_names,
                        routing_grid,
                    )
                continue
            best_attempt_payload = _read_symbol_json_mapping(str(working_symbol_pose_path))
            if best_attempt_payload is None:
                return False, "SYMBOL_JSON_PARSE_ERROR", 0
            if not should_attempt_routing:
                best_attempt_wires = "{}\n"
                break
            working_wire_path = Path(temporary_directory) / "wires.json"
            wiring_result = ltspice_netlist_to_wiring(
                netlist_filepath,
                str(working_symbol_pose_path),
                str(working_wire_path),
                convert_settings,
            )
            if wiring_result[0]:
                best_attempt_wires = working_wire_path.read_text(encoding="utf-8")
                break
            current_positions = _expand_layout_for_routing_retry(
                current_positions,
                current_geometries,
                routing_grid,
                iteration_index,
            )
        if best_attempt_payload is None or best_attempt_wires is None:
            return _AUTOPLACE_ERROR
        output_symbol_path = Path(_asc._coerce_path(symbol_pose_filepath_out)[1])
        output_wire_path = Path(_asc._coerce_path(wire_filepath_out)[1])
        try:
            output_symbol_path.parent.mkdir(parents=True, exist_ok=True)
            output_wire_path.parent.mkdir(parents=True, exist_ok=True)
            output_symbol_path.write_text(json.dumps(best_attempt_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            output_wire_path.write_text(best_attempt_wires, encoding="utf-8")
        except OSError:
            return False, "WRITE_ERROR", 0
    return _OK_RESULT


def _prepare_working_symbol_pose_file(
    netlist_filepath: str,
    symbol_pose_filepath: str,
    working_symbol_pose_filepath: str,
    convert_settings: Mapping[str, object],
) -> ConversionResult:
    symbol_pose_path_result = _asc._coerce_path(symbol_pose_filepath)
    if not symbol_pose_path_result[0]:
        return False, "INVALID_OUTPUT_PATH", 0
    symbol_pose_path = Path(symbol_pose_path_result[1])
    working_path = Path(working_symbol_pose_filepath)
    if symbol_pose_path.exists():
        try:
            working_path.write_text(symbol_pose_path.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            return False, "SYMBOL_JSON_READ_ERROR", 0
        return _OK_RESULT
    initial_result = ltspice_netlist_to_symbol_initial(
        netlist_filepath,
        str(working_path),
        convert_settings,
    )
    if not initial_result[0]:
        return initial_result
    return _OK_RESULT


def _collect_component_records(lines: Sequence[str]) -> Dict[str, ComponentRecord]:
    logical_lines = _collect_logical_device_lines(lines)
    components: Dict[str, ComponentRecord] = {}
    for line_number, code_text in logical_lines:
        tokens = code_text.split()
        if not tokens or tokens[0][0].upper() == "K":
            continue
        instance_name = _normalize_instance_name(tokens[0])
        node_result = _net._extract_nodes(tokens)
        if instance_name == "" or not node_result[0]:
            continue
        components[instance_name] = ComponentRecord(
            instance_name=instance_name,
            prefix=tokens[0][0].upper(),
            line_number=line_number,
            node_names=tuple(str(node_name).strip() for node_name in node_result[1]),
        )
    return components


def _collect_logical_device_lines(lines: Sequence[str]) -> Tuple[Tuple[int, str], ...]:
    logical_lines: List[Tuple[int, str]] = []
    current_line_number = 0
    current_parts: List[str] = []
    for line_number, raw_line in enumerate(lines, start=1):
        classification_result = _net._classify_line(raw_line)
        if not classification_result[0]:
            continue
        kind = classification_result[1]
        if kind in {"blank", "comment"}:
            if current_parts:
                logical_lines.append((current_line_number, " ".join(current_parts).strip()))
                current_line_number = 0
                current_parts = []
            continue
        if kind == "continuation":
            continuation_text = _net._strip_semicolon_comment(raw_line).lstrip()[1:].strip()
            if current_parts and continuation_text != "":
                current_parts.append(continuation_text)
            continue
        if kind != "device":
            if current_parts:
                logical_lines.append((current_line_number, " ".join(current_parts).strip()))
                current_line_number = 0
                current_parts = []
            continue
        code_text = _net._strip_semicolon_comment(raw_line).strip()
        if code_text == "":
            continue
        if current_parts:
            logical_lines.append((current_line_number, " ".join(current_parts).strip()))
        current_line_number = line_number
        current_parts = [code_text]
    if current_parts:
        logical_lines.append((current_line_number, " ".join(current_parts).strip()))
    return tuple(logical_lines)


def _build_pin_connections_by_instance(
    components: Mapping[str, ComponentRecord],
    geometries: Mapping[str, OrientationGeometry],
) -> Dict[str, Tuple[PinConnection, ...]]:
    connections_by_instance: Dict[str, Tuple[PinConnection, ...]] = {}
    for instance_name, component in components.items():
        if instance_name not in geometries:
            continue
        geometry = geometries[instance_name]
        pin_limit = min(len(component.node_names), len(geometry.pins))
        connections: List[PinConnection] = []
        for net_name, pin in zip(component.node_names[:pin_limit], geometry.pins[:pin_limit]):
            if _is_no_connect_net(net_name):
                continue
            connections.append(
                PinConnection(
                    instance_name=instance_name,
                    line_number=component.line_number,
                    net_name=net_name,
                    pin_name=pin.pin_name,
                    spice_order=pin.spice_order,
                )
            )
        connections_by_instance[instance_name] = tuple(connections)
    return connections_by_instance


def _build_component_graph(
    pin_connections_by_instance: Mapping[str, Sequence[PinConnection]],
) -> nx.Graph:
    graph = nx.Graph()
    for instance_name in pin_connections_by_instance:
        graph.add_node(instance_name)
    net_groups = _group_connections_by_net(pin_connections_by_instance)
    for net_name, connections in net_groups.items():
        if len(connections) < 2:
            continue
        net_weight = _net_weight(net_name)
        for first_index, first_connection in enumerate(connections):
            for second_connection in connections[first_index + 1 :]:
                if first_connection.instance_name == second_connection.instance_name:
                    continue
                if graph.has_edge(first_connection.instance_name, second_connection.instance_name):
                    graph[first_connection.instance_name][second_connection.instance_name]["weight"] += net_weight
                else:
                    graph.add_edge(first_connection.instance_name, second_connection.instance_name, weight=net_weight)
    return graph


def _group_connections_by_net(
    pin_connections_by_instance: Mapping[str, Sequence[PinConnection]],
) -> Dict[str, List[PinConnection]]:
    grouped_connections: Dict[str, List[PinConnection]] = {}
    for connections in pin_connections_by_instance.values():
        for connection in connections:
            grouped_connections.setdefault(connection.net_name, []).append(connection)
    return grouped_connections


def _build_initial_positions(
    component_graph: nx.Graph,
    geometries: Mapping[str, OrientationGeometry],
    minimum_dist: int,
    routing_grid: int,
) -> Dict[str, Point]:
    padding = max(routing_grid * 4, minimum_dist * 2, 64)
    component_gap = max(padding * 2, 192)
    positions: Dict[str, Point] = {}
    current_x_offset = 0.0
    for component_nodes in sorted(nx.connected_components(component_graph), key=lambda nodes: (-len(nodes), sorted(nodes)[0])):
        subgraph = component_graph.subgraph(component_nodes).copy()
        if len(subgraph.nodes) == 1:
            node_name = next(iter(subgraph.nodes))
            geometry = geometries[node_name]
            positions[node_name] = _origin_from_center(
                (current_x_offset + geometry.width / 2.0, 0.0),
                geometry,
                routing_grid,
            )
            current_x_offset += geometry.width + component_gap
            continue
        root_node = _choose_root_component(subgraph)
        layer_map = nx.single_source_shortest_path_length(subgraph, root_node)
        layers: Dict[int, List[str]] = {}
        for node_name, layer_index in layer_map.items():
            layers.setdefault(layer_index, []).append(node_name)
        ordered_layers = []
        previous_layer_order: Dict[str, int] = {}
        for layer_index in sorted(layers):
            layer_nodes = list(layers[layer_index])
            layer_nodes.sort(
                key=lambda node_name: (
                    _neighbor_barycenter(node_name, previous_layer_order, subgraph),
                    -subgraph.degree(node_name, weight="weight"),
                    node_name,
                )
            )
            previous_layer_order = {node_name: order_index for order_index, node_name in enumerate(layer_nodes)}
            ordered_layers.append((layer_index, layer_nodes))
        layer_widths = {
            layer_index: max(geometries[node_name].width for node_name in layer_nodes)
            for layer_index, layer_nodes in ordered_layers
        }
        layer_x_centers: Dict[int, float] = {}
        layer_left = current_x_offset
        for layer_index, _layer_nodes in ordered_layers:
            layer_x_centers[layer_index] = layer_left + (layer_widths[layer_index] / 2.0)
            layer_left += layer_widths[layer_index] + padding
        for layer_index, layer_nodes in ordered_layers:
            layer_height = sum(geometries[node_name].height for node_name in layer_nodes)
            layer_height += padding * max(len(layer_nodes) - 1, 0)
            current_y = -(layer_height / 2.0)
            for node_name in layer_nodes:
                geometry = geometries[node_name]
                center_y = current_y + (geometry.height / 2.0)
                positions[node_name] = _origin_from_center(
                    (layer_x_centers[layer_index], center_y),
                    geometry,
                    routing_grid,
                )
                current_y = center_y + (geometry.height / 2.0) + padding
        current_x_offset = layer_left + component_gap
    return positions


def _choose_root_component(subgraph: nx.Graph) -> str:
    source_nodes = [
        node_name
        for node_name in subgraph.nodes
        if node_name[:1].upper() in {"V", "I"}
    ]
    candidate_nodes = source_nodes if source_nodes else list(subgraph.nodes)
    return max(
        candidate_nodes,
        key=lambda node_name: (
            subgraph.degree(node_name, weight="weight"),
            -len(node_name),
            node_name,
        ),
    )


def _neighbor_barycenter(node_name: str, previous_layer_order: Mapping[str, int], subgraph: nx.Graph) -> float:
    neighbor_orders = [
        previous_layer_order[neighbor_name]
        for neighbor_name in subgraph.neighbors(node_name)
        if neighbor_name in previous_layer_order
    ]
    if not neighbor_orders:
        return float("inf")
    return sum(neighbor_orders) / len(neighbor_orders)


def _choose_orientations(
    positions: Mapping[str, Point],
    current_orientations: Mapping[str, str],
    original_symbol_data: Mapping[str, Mapping[str, object]],
    candidate_orientations: Mapping[str, Sequence[str]],
    geometry_cache: MutableMapping[Tuple[str, str], OrientationGeometry],
    pin_connections_by_instance: Mapping[str, Sequence[PinConnection]],
    convert_settings: Mapping[str, object],
) -> Dict[str, str]:
    net_groups = _group_connections_by_net(pin_connections_by_instance)
    current_geometries = {
        instance_name: _geometry_for_orientation(
            original_symbol_data[instance_name],
            current_orientations[instance_name],
            geometry_cache,
            convert_settings,
        )
        for instance_name in positions
    }
    absolute_pin_points = _absolute_pin_points(positions, current_geometries)
    chosen_orientations = dict(current_orientations)
    for instance_name in sorted(positions):
        current_orientation = chosen_orientations[instance_name]
        best_orientation = current_orientation
        best_score = math.inf
        for orientation in candidate_orientations.get(instance_name, (current_orientation,)):
            geometry = _geometry_for_orientation(
                original_symbol_data[instance_name],
                orientation,
                geometry_cache,
                convert_settings,
            )
            score = _orientation_score(
                instance_name,
                positions[instance_name],
                geometry,
                absolute_pin_points,
                net_groups,
                pin_connections_by_instance,
            )
            if orientation == current_orientation:
                score -= 0.5
            if score < best_score:
                best_score = score
                best_orientation = orientation
        chosen_orientations[instance_name] = best_orientation
        current_geometries[instance_name] = _geometry_for_orientation(
            original_symbol_data[instance_name],
            best_orientation,
            geometry_cache,
            convert_settings,
        )
        absolute_pin_points = _absolute_pin_points(positions, current_geometries)
    return chosen_orientations


def _orientation_score(
    instance_name: str,
    origin: Point,
    geometry: OrientationGeometry,
    absolute_pin_points: Mapping[Tuple[str, int], Point],
    net_groups: Mapping[str, Sequence[PinConnection]],
    pin_connections_by_instance: Mapping[str, Sequence[PinConnection]],
) -> float:
    score = 0.0
    local_pin_points = {
        pin.spice_order: (origin[0] + pin.point[0], origin[1] + pin.point[1])
        for pin in geometry.pins
    }
    for connection in pin_connections_by_instance.get(instance_name, ()):
        if connection.spice_order not in local_pin_points:
            continue
        if _is_no_connect_net(connection.net_name):
            continue
        other_points = [
            absolute_pin_points[(other_connection.instance_name, other_connection.spice_order)]
            for other_connection in net_groups.get(connection.net_name, ())
            if other_connection.instance_name != instance_name
            and (other_connection.instance_name, other_connection.spice_order) in absolute_pin_points
        ]
        if not other_points:
            continue
        target_x = sum(point[0] for point in other_points) / len(other_points)
        target_y = sum(point[1] for point in other_points) / len(other_points)
        pin_point = local_pin_points[connection.spice_order]
        score += _net_weight(connection.net_name) * (abs(pin_point[0] - target_x) + abs(pin_point[1] - target_y))
    return score


def _absolute_pin_points(
    positions: Mapping[str, Point],
    geometries: Mapping[str, OrientationGeometry],
) -> Dict[Tuple[str, int], Point]:
    absolute_points: Dict[Tuple[str, int], Point] = {}
    for instance_name, origin in positions.items():
        geometry = geometries[instance_name]
        for pin in geometry.pins:
            absolute_points[(instance_name, pin.spice_order)] = (
                origin[0] + pin.point[0],
                origin[1] + pin.point[1],
            )
    return absolute_points


def _relax_positions(
    current_positions: Mapping[str, Point],
    geometries: Mapping[str, OrientationGeometry],
    pin_connections_by_instance: Mapping[str, Sequence[PinConnection]],
    minimum_dist: int,
    routing_grid: int,
) -> Dict[str, Point]:
    net_groups = _group_connections_by_net(pin_connections_by_instance)
    positions = dict(current_positions)
    for _ in range(2):
        absolute_pin_points = _absolute_pin_points(positions, geometries)
        updated_positions = dict(positions)
        for instance_name in sorted(positions):
            suggestions: List[Tuple[float, float, float]] = []
            geometry = geometries[instance_name]
            for connection in pin_connections_by_instance.get(instance_name, ()):
                pin_geometry = _pin_geometry_by_order(geometry, connection.spice_order)
                if pin_geometry is None:
                    continue
                other_points = [
                    absolute_pin_points[(other_connection.instance_name, other_connection.spice_order)]
                    for other_connection in net_groups.get(connection.net_name, ())
                    if other_connection.instance_name != instance_name
                    and (other_connection.instance_name, other_connection.spice_order) in absolute_pin_points
                ]
                if not other_points:
                    continue
                target_x = sum(point[0] for point in other_points) / len(other_points)
                target_y = sum(point[1] for point in other_points) / len(other_points)
                weight = _net_weight(connection.net_name)
                suggestions.append((target_x - pin_geometry.point[0], target_y - pin_geometry.point[1], weight))
            if not suggestions:
                continue
            total_weight = sum(weight for _target_x, _target_y, weight in suggestions)
            suggested_origin_x = sum(target_x * weight for target_x, _target_y, weight in suggestions) / total_weight
            suggested_origin_y = sum(target_y * weight for _target_x, target_y, weight in suggestions) / total_weight
            blended_origin = (
                (positions[instance_name][0] * 0.35) + (suggested_origin_x * 0.65),
                (positions[instance_name][1] * 0.35) + (suggested_origin_y * 0.65),
            )
            updated_positions[instance_name] = (
                _snap_coordinate_to_grid(int(round(blended_origin[0])), routing_grid),
                _snap_coordinate_to_grid(int(round(blended_origin[1])), routing_grid),
            )
        positions = _resolve_collisions(updated_positions, geometries, minimum_dist, routing_grid)
    return positions


def _resolve_collisions(
    positions: Mapping[str, Point],
    geometries: Mapping[str, OrientationGeometry],
    minimum_dist: int,
    routing_grid: int,
) -> Dict[str, Point]:
    resolved_positions = dict(positions)
    for _ in range(32):
        moved_any_symbol = False
        instance_names = sorted(resolved_positions)
        for first_index, first_name in enumerate(instance_names):
            for second_name in instance_names[first_index + 1 :]:
                first_buffered_rectangle = _buffered_absolute_rectangle(
                    resolved_positions[first_name],
                    geometries[first_name],
                    minimum_dist,
                )
                second_buffered_rectangle = _buffered_absolute_rectangle(
                    resolved_positions[second_name],
                    geometries[second_name],
                    minimum_dist,
                )
                overlap = _rectangle_overlap(first_buffered_rectangle, second_buffered_rectangle)
                if overlap is None:
                    continue
                moved_any_symbol = True
                overlap_x, overlap_y = overlap
                first_center = _rectangle_center(first_buffered_rectangle)
                second_center = _rectangle_center(second_buffered_rectangle)
                if overlap_x <= overlap_y:
                    direction = -1 if second_center[0] < first_center[0] else 1
                    shift_x = _snap_shift(overlap_x + routing_grid, routing_grid) * direction
                    resolved_positions[second_name] = (
                        resolved_positions[second_name][0] + shift_x,
                        resolved_positions[second_name][1],
                    )
                else:
                    direction = -1 if second_center[1] < first_center[1] else 1
                    shift_y = _snap_shift(overlap_y + routing_grid, routing_grid) * direction
                    resolved_positions[second_name] = (
                        resolved_positions[second_name][0],
                        resolved_positions[second_name][1] + shift_y,
                    )
        if not moved_any_symbol:
            break
    return {
        instance_name: (
            _snap_coordinate_to_grid(position[0], routing_grid),
            _snap_coordinate_to_grid(position[1], routing_grid),
        )
        for instance_name, position in resolved_positions.items()
    }


def _spread_colliding_symbols(
    positions: Mapping[str, Point],
    geometries: Mapping[str, OrientationGeometry],
    collision_pairs: object,
    ordered_instance_names: Sequence[str],
    routing_grid: int,
) -> Dict[str, Point]:
    if collision_pairs is None:
        return dict(positions)
    updated_positions = dict(positions)
    try:
        collision_rows = list(collision_pairs.tolist())
    except AttributeError:
        return updated_positions
    for first_index, second_index in collision_rows:
        if not isinstance(first_index, int) or not isinstance(second_index, int):
            continue
        if first_index < 0 or second_index < 0:
            continue
        if first_index >= len(ordered_instance_names) or second_index >= len(ordered_instance_names):
            continue
        first_name = ordered_instance_names[first_index]
        second_name = ordered_instance_names[second_index]
        first_center = _rectangle_center(
            _absolute_rectangle(updated_positions[first_name], geometries[first_name])
        )
        second_center = _rectangle_center(
            _absolute_rectangle(updated_positions[second_name], geometries[second_name])
        )
        delta_x = second_center[0] - first_center[0]
        delta_y = second_center[1] - first_center[1]
        if abs(delta_x) >= abs(delta_y):
            direction = -1 if delta_x < 0 else 1
            updated_positions[second_name] = (
                updated_positions[second_name][0] + direction * max(routing_grid * 4, 64),
                updated_positions[second_name][1],
            )
        else:
            direction = -1 if delta_y < 0 else 1
            updated_positions[second_name] = (
                updated_positions[second_name][0],
                updated_positions[second_name][1] + direction * max(routing_grid * 4, 64),
            )
    return updated_positions


def _expand_layout_for_iteration(
    positions: Mapping[str, Point],
    iteration_index: int,
    routing_grid: int,
) -> Dict[str, Point]:
    if iteration_index == 0:
        return dict(positions)
    scale = 1.0 + (0.12 * iteration_index)
    center_x = sum(position[0] for position in positions.values()) / max(len(positions), 1)
    center_y = sum(position[1] for position in positions.values()) / max(len(positions), 1)
    expanded_positions: Dict[str, Point] = {}
    for instance_name, position in positions.items():
        expanded_positions[instance_name] = (
            _snap_coordinate_to_grid(int(round(center_x + ((position[0] - center_x) * scale))), routing_grid),
            _snap_coordinate_to_grid(int(round(center_y + ((position[1] - center_y) * scale))), routing_grid),
        )
    return expanded_positions


def _expand_layout_for_routing_retry(
    positions: Mapping[str, Point],
    geometries: Mapping[str, OrientationGeometry],
    routing_grid: int,
    iteration_index: int,
) -> Dict[str, Point]:
    scale = 1.15 + (0.08 * iteration_index)
    center_x = sum(_rectangle_center(_absolute_rectangle(position, geometries[instance_name]))[0] for instance_name, position in positions.items()) / max(len(positions), 1)
    center_y = sum(_rectangle_center(_absolute_rectangle(position, geometries[instance_name]))[1] for instance_name, position in positions.items()) / max(len(positions), 1)
    expanded_positions: Dict[str, Point] = {}
    for instance_name, position in positions.items():
        rectangle_center = _rectangle_center(_absolute_rectangle(position, geometries[instance_name]))
        shifted_center = (
            center_x + ((rectangle_center[0] - center_x) * scale),
            center_y + ((rectangle_center[1] - center_y) * scale),
        )
        expanded_positions[instance_name] = _origin_from_center(shifted_center, geometries[instance_name], routing_grid)
    return expanded_positions


def _build_symbol_pose_payload(
    original_symbol_data: Mapping[str, Mapping[str, object]],
    positions: Mapping[str, Point],
    orientations: Mapping[str, str],
) -> Dict[str, Dict[str, object]]:
    symbol_payload: Dict[str, Dict[str, object]] = {}
    for instance_name, symbol_entry in original_symbol_data.items():
        new_entry = dict(symbol_entry)
        if instance_name in positions:
            new_entry["X"] = int(positions[instance_name][0])
            new_entry["Y"] = int(positions[instance_name][1])
            new_entry["ORIENTATION"] = orientations[instance_name]
            new_entry["PINS"] = []
            new_entry["RECTANGLE"] = []
        symbol_payload[instance_name] = new_entry
    return symbol_payload


def _resolve_default_geometry(
    instance_name: str,
    symbol_entry: Mapping[str, object],
    candidate_orientations: Sequence[str],
    geometry_cache: MutableMapping[Tuple[str, str], OrientationGeometry],
    convert_settings: Mapping[str, object],
) -> OrientationGeometry:
    for preferred_orientation in (_clean_orientation(symbol_entry.get("ORIENTATION", "")), *candidate_orientations):
        if preferred_orientation == "":
            continue
        return _geometry_for_orientation(symbol_entry, preferred_orientation, geometry_cache, convert_settings)
    raise ValueError(f"Unable to resolve default geometry for {instance_name}")


def _geometry_for_orientation(
    symbol_entry: Mapping[str, object],
    orientation: str,
    geometry_cache: MutableMapping[Tuple[str, str], OrientationGeometry],
    convert_settings: Mapping[str, object],
) -> OrientationGeometry:
    symbol_name = str(symbol_entry.get("SYMBOL", "")).strip()
    cache_key = (symbol_name, orientation)
    if cache_key in geometry_cache:
        return geometry_cache[cache_key]
    working_entry = dict(symbol_entry)
    working_entry["X"] = 0
    working_entry["Y"] = 0
    working_entry["ORIENTATION"] = orientation
    working_entry["PINS"] = []
    working_entry["RECTANGLE"] = []
    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_json_path = Path(temporary_directory) / "geometry.json"
        temporary_json_path.write_text(json.dumps({"U1": working_entry}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        resolve_result = ltspice_resolve_symbol_pose(str(temporary_json_path), convert_settings)
        if not resolve_result[0]:
            raise ValueError(resolve_result[1])
        resolved_symbol_json = json.loads(temporary_json_path.read_text(encoding="utf-8"))
    resolved_entry = resolved_symbol_json["U1"]
    rectangle = _parse_rectangle(resolved_entry["RECTANGLE"])
    pins = tuple(
        sorted(
            (
                PinGeometry(
                    point=(int(pin_row[0]), int(pin_row[1])),
                    pin_name=str(pin_row[2]),
                    spice_order=int(pin_row[3]),
                )
                for pin_row in resolved_entry.get("PINS", [])
            ),
            key=lambda pin: pin.spice_order,
        )
    )
    center_offset = (
        (rectangle[0] + rectangle[2]) / 2.0,
        (rectangle[1] + rectangle[3]) / 2.0,
    )
    geometry = OrientationGeometry(
        orientation=orientation,
        rectangle=rectangle,
        pins=pins,
        width=rectangle[2] - rectangle[0],
        height=rectangle[3] - rectangle[1],
        center_offset=center_offset,
    )
    geometry_cache[cache_key] = geometry
    return geometry


def _candidate_orientations_for_entry(symbol_entry: Mapping[str, object]) -> Tuple[str, ...]:
    symbol_name = str(symbol_entry.get("SYMBOL", "")).strip().lower()
    if symbol_name in _SYMMETRIC_SYMBOL_NAMES:
        return ("R0", "M0", "R180", "M180", "R90", "M90", "R270", "M270")
    return ("R0", "R90", "R180", "R270")


def _infer_layout_grid(
    geometries: Iterable[OrientationGeometry],
    convert_settings: Mapping[str, object],
) -> int:
    explicit_grid_size = _resolve_positive_integer(convert_settings.get("grid_size", 0))
    if explicit_grid_size is not None:
        return explicit_grid_size
    coordinate_values: List[int] = []
    for geometry in geometries:
        coordinate_values.extend(
            [
                abs(geometry.rectangle[0]),
                abs(geometry.rectangle[1]),
                abs(geometry.rectangle[2]),
                abs(geometry.rectangle[3]),
                abs(geometry.width),
                abs(geometry.height),
            ]
        )
        for pin in geometry.pins:
            coordinate_values.extend([abs(pin.point[0]), abs(pin.point[1])])
    minimum_dist = _resolve_non_negative_integer(convert_settings.get("minimum_dist", 0))
    wire_pin_out_dist = _resolve_non_negative_integer(convert_settings.get("wire_pin_out_dist", 0))
    if minimum_dist is not None:
        coordinate_values.append(abs(minimum_dist))
    if wire_pin_out_dist is not None:
        coordinate_values.append(abs(wire_pin_out_dist))
    grid = 0
    for value in coordinate_values:
        if value == 0:
            continue
        grid = value if grid == 0 else math.gcd(grid, value)
    return max(grid, 16)


def _origin_from_center(center_point: Tuple[float, float], geometry: OrientationGeometry, routing_grid: int) -> Point:
    return (
        _snap_coordinate_to_grid(int(round(center_point[0] - geometry.center_offset[0])), routing_grid),
        _snap_coordinate_to_grid(int(round(center_point[1] - geometry.center_offset[1])), routing_grid),
    )


def _buffered_absolute_rectangle(origin: Point, geometry: OrientationGeometry, minimum_dist: int) -> Rectangle:
    absolute_rectangle = _absolute_rectangle(origin, geometry)
    return (
        absolute_rectangle[0] - minimum_dist,
        absolute_rectangle[1] - minimum_dist,
        absolute_rectangle[2] + minimum_dist,
        absolute_rectangle[3] + minimum_dist,
    )


def _absolute_rectangle(origin: Point, geometry: OrientationGeometry) -> Rectangle:
    return (
        origin[0] + geometry.rectangle[0],
        origin[1] + geometry.rectangle[1],
        origin[0] + geometry.rectangle[2],
        origin[1] + geometry.rectangle[3],
    )


def _rectangle_overlap(first_rectangle: Rectangle, second_rectangle: Rectangle) -> Optional[Tuple[int, int]]:
    overlap_left = max(first_rectangle[0], second_rectangle[0])
    overlap_top = max(first_rectangle[1], second_rectangle[1])
    overlap_right = min(first_rectangle[2], second_rectangle[2])
    overlap_bottom = min(first_rectangle[3], second_rectangle[3])
    if overlap_left >= overlap_right or overlap_top >= overlap_bottom:
        return None
    return overlap_right - overlap_left, overlap_bottom - overlap_top


def _rectangle_center(rectangle: Rectangle) -> Tuple[float, float]:
    return (
        (rectangle[0] + rectangle[2]) / 2.0,
        (rectangle[1] + rectangle[3]) / 2.0,
    )


def _pin_geometry_by_order(geometry: OrientationGeometry, spice_order: int) -> Optional[PinGeometry]:
    for pin in geometry.pins:
        if pin.spice_order == spice_order:
            return pin
    return None


def _parse_rectangle(raw_rectangle: object) -> Rectangle:
    first_point, second_point = raw_rectangle
    minimum_x = min(int(first_point[0]), int(second_point[0]))
    minimum_y = min(int(first_point[1]), int(second_point[1]))
    maximum_x = max(int(first_point[0]), int(second_point[0]))
    maximum_y = max(int(first_point[1]), int(second_point[1]))
    return minimum_x, minimum_y, maximum_x, maximum_y


def _read_symbol_json_mapping(filepath: str) -> Optional[Dict[str, Dict[str, object]]]:
    try:
        symbol_json = json.loads(Path(filepath).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(symbol_json, dict):
        return None
    normalized_mapping: Dict[str, Dict[str, object]] = {}
    for instance_name, symbol_entry in symbol_json.items():
        if not isinstance(symbol_entry, dict):
            return None
        normalized_mapping[str(instance_name)] = dict(symbol_entry)
    return normalized_mapping


def _resolve_autoplace_iterations(convert_settings: Mapping[str, object]) -> Optional[int]:
    raw_iterations = convert_settings.get("autoplace_iter", _DEFAULT_AUTOPLACE_ITERATIONS)
    if isinstance(raw_iterations, bool):
        return None
    try:
        iterations = int(raw_iterations)
    except (TypeError, ValueError):
        return None
    if iterations <= 0:
        return None
    return iterations


def _resolve_non_negative_integer(value: object) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        integer_value = int(value)
    except (TypeError, ValueError):
        return None
    if integer_value < 0:
        return None
    return integer_value


def _resolve_positive_integer(value: object) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        integer_value = int(value)
    except (TypeError, ValueError):
        return None
    if integer_value <= 0:
        return None
    return integer_value


def _normalize_instance_name(instance_token: str) -> str:
    clean_token = instance_token.strip()
    if clean_token == "":
        return ""
    if "§" in clean_token:
        return clean_token.split("§", 1)[1].strip()
    return clean_token


def _clean_orientation(value: object) -> str:
    return str(value).strip().upper()


def _is_no_connect_net(net_name: str) -> bool:
    return net_name.upper().startswith(_NO_CONNECT_PREFIXES)


def _net_weight(net_name: str) -> float:
    uppercase_name = net_name.upper()
    if uppercase_name in _GROUND_NETS:
        return 0.35
    if _is_no_connect_net(net_name):
        return 0.0
    return 1.0


def _snap_coordinate_to_grid(value: int, routing_grid: int) -> int:
    if routing_grid <= 0:
        return int(value)
    normalized_value = int(value)
    remainder = normalized_value % routing_grid
    if remainder == 0:
        return normalized_value
    lower_value = normalized_value - remainder
    upper_value = lower_value + routing_grid
    if abs(normalized_value - lower_value) <= abs(upper_value - normalized_value):
        return lower_value
    return upper_value


def _snap_shift(value: int, routing_grid: int) -> int:
    if routing_grid <= 0:
        return int(value)
    if value % routing_grid == 0:
        return value
    return ((value // routing_grid) + 1) * routing_grid


def _line_number_from_message(message: str, default_line: int) -> int:
    try:
        return int(str(message).rsplit("Line ", 1)[1])
    except (IndexError, ValueError):
        return default_line


def _coerce_path_success(filepath: str) -> bool:
    path_result = _asc._coerce_path(filepath)
    return bool(path_result[0])
