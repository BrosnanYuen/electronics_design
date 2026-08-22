"""Sugiyama-style signal-flow placement for the netlist-to-KiCad converter.

This module implements the "flow" placement strategy used by
``ltspice_netlist_to_kicad_sch``. Instead of optimizing only wire length and
overlap, it derives a human-readable schematic layout from the netlist
topology:

1. Device roles (source / series / shunt / active) come from the device
   prefix and its netlist nodes.
2. Nets are layered into signal-flow columns using a longest-path layering
   over a BFS-distance-directed net graph, so feedback is broken by
   construction and the resulting directed graph is acyclic.
3. Rows inside each column are ordered with a deterministic barycenter sweep.
4. Coordinates use a human column/row pitch centered on the drawing page
   (A4 by default, A3 for designs with more than 80 symbols).
5. Symbol orientations are chosen from role templates using only the symbol's
   resolved pin geometry (never hard-coded coordinates or paths).

All pin geometry and body bounds are looked up through the resolved symbol
definitions or the record payloads built by the converter; nothing is
hard-coded.
"""

from __future__ import annotations  # Postpone annotation evaluation for forward references.

import math  # Compute square roots, ceil, and pitch arithmetic.
from collections import deque  # Run deterministic breadth-first traversals.
from typing import Any  # Type record payload dictionaries.
from typing import Dict  # Type net, role, and coordinate mappings.
from typing import List  # Type collected edge and candidate lists.
from typing import Optional  # Type optional fallback results.
from typing import Sequence  # Type immutable record sequences.
from typing import Set  # Type unique node collections.
from typing import Tuple  # Type tuple-based helper results.

from .kicad_sch_to_ltspice_netlist import _transform_point  # Reuse the shared pin-position transform.

_GROUND_NODE_NAMES = frozenset({"0", "GND"})  # Treat these netlist node names as the global ground net.

_SUPPLY_TOKENS = (  # Heuristics shared with the physics net-stiffness model.
    "vcc", "vdd", "vss", "vee", "pwr", "v+", "v-",  # Common supply name fragments.
    "+3", "+5", "+12", "-12", "+15", "-15",  # Numeric rail fragments.
)  # Finish the supply-token table.

_SOURCE_PREFIXES = frozenset({"V", "I", "B"})  # Devices that drive the flow graph from a positive node.

_ACTIVE_PREFIXES = frozenset({"Q", "M", "J", "X"})  # Devices whose pins carry input/output roles.

_COLUMN_GAP_GRID_UNITS = 4  # Human column gap in grid units beyond the adjacent body sizes.
_ROW_GAP_GRID_UNITS = 2  # Human row gap in grid units beyond the adjacent body sizes.
_COMPACT_COLUMN_GAP_GRID_UNITS = 2  # Tighter column gap used when the primary plan overflows the page.
_COMPACT_ROW_GAP_GRID_UNITS = 1  # Tighter row gap used when the primary plan overflows the page.
_SHRINK_COLUMN_GAP_GRID_UNITS = 1  # Minimum column gap retried before the plan is folded or falls back.
_SHRINK_ROW_GAP_GRID_UNITS = 1  # Minimum row gap retried before the plan is folded or falls back.
_BARYCENTER_SWEEPS = 4  # Number of deterministic row-ordering sweeps.
_DEFAULT_BODY = 2.54  # Fallback body dimension for graphics-less symbols.
_MIN_BODY = 1.27  # Minimum body dimension used for pitch arithmetic.
_SMALL_PLAN_FRACTION = 0.4  # Plans below this page fraction are stretched to a human extent.
_SPREAD_PLAN_FRACTION = 0.45  # Small plans are stretched until they fill this page fraction.
_SPREAD_SCALE_CAP = 1.6  # Bound the small-plan stretch so compact decks stay in the human pitch band.
_CHAIN_STRETCH_MIN_ROWS = 8  # One-column chains at or above this length may be stretched.
_CHAIN_STRETCH_SCALE_CAP = 1.4  # Bound the one-column chain stretch.
_BODY_SYMMETRY_TOL = 0.254  # Pins must protrude this far on both sides to count as a symmetric body.
_PAGE_FIT_MARGIN_GRID_UNITS = 1  # Reserve one grid unit for grid snapping at the page edges.


def is_ground_net(name: str) -> bool:  # Decide whether one node name is the global ground net.
    return name in _GROUND_NODE_NAMES  # Return the ground membership.


def is_nc_net(name: str) -> bool:  # Decide whether one node name is a no-connect stub.
    return name.startswith("NC") or name.startswith("NC_") or name.startswith("NC-")  # Match the netlist validator's exempt NC conventions.


def is_supply_net(name: str) -> bool:  # Decide whether one node name looks like a supply rail.
    lowered = name.lower()  # Normalize the name for substring matching.
    return any(token in lowered for token in _SUPPLY_TOKENS)  # Return the supply detection.


def classify_flow_roles(records: Sequence[Dict[str, Any]]) -> Dict[int, str]:  # Classify every device by its netlist role.
    roles: Dict[int, str] = {}  # Collect the role assignments keyed by unique placement id.
    for record in records:  # Walk every component record.
        if record["power"]:  # Power symbols are attached after routing.
            continue  # Move to the next record.
        uid = record["uid"]  # Read the unique placement key.
        prefix = record["prefix"]  # Read the device prefix.
        used = [record["element"].nodes[node_index] for node_index in record["pin_map"]]  # Collect the used node names.
        if prefix in _SOURCE_PREFIXES and len(used) >= 2 and not is_ground_net(used[0]):  # Sources drive the graph from a non-ground positive node.
            roles[uid] = "source"  # Classify the device as a signal source.
        elif len(used) >= 3 or prefix in _ACTIVE_PREFIXES:  # Multi-pin and transistor devices carry directed flow.
            roles[uid] = "active"  # Classify the device as an active stage.
        elif len(used) == 2:  # Two-pin devices split by their second net.
            ground_side = sum(1 for name in used if is_ground_net(name))  # Count ground-side nets.
            supply_side = sum(1 for name in used if is_supply_net(name))  # Count supply-side nets.
            if ground_side >= 1:  # Devices with a ground terminal are ground shunts.
                roles[uid] = "shunt_gnd"  # Classify the device as a ground shunt.
            elif supply_side >= 1:  # Devices with a supply terminal are supply shunts.
                roles[uid] = "shunt_pwr"  # Classify the device as a supply shunt.
            else:  # Two non-power nets pass signal straight through.
                roles[uid] = "series"  # Classify the device as a series element.
        else:  # Degenerate or fully-unmapped devices stay neutral.
            roles[uid] = "passive"  # Classify the device as passive.
    return roles  # Return the role assignments.


def active_pin_roles(record: Dict[str, Any]) -> Tuple[Set[str], Set[str]]:  # Resolve input and output pin numbers for one active device.
    prefix = record["prefix"]  # Read the device prefix.
    role_map: Dict[str, str] = {}  # Map pin numbers onto Sim.Pins roles.
    for token in record["symbol_props"].get("Sim.Pins", "").split():  # Walk the Sim.Pins role tokens.
        if "=" not in token:  # Skip tokens without a pin assignment.
            continue  # Move to the next token.
        pin_part, role_part = token.split("=", 1)  # Split the pin number from its role.
        role_map[pin_part.strip()] = role_part.strip().upper()  # Record the pin role.
    input_pins: Set[str] = set()  # Collect input pin numbers.
    output_pins: Set[str] = set()  # Collect output pin numbers.
    for node_index, pin_number in record["pin_map"].items():  # Walk every used pin.
        role = role_map.get(str(pin_number), "")  # Read the pin's Sim.Pins role.
        pin_name = str(record["pins"][pin_number][2]).upper() if pin_number in record["pins"] else ""  # Read the pin name.
        if prefix == "Q":  # BJT flow enters the base and exits collector/emitter.
            if role == "B" or pin_name in {"B", "BASE"}:  # Detect the base terminal.
                input_pins.add(pin_number)  # Record the base as an input.
            elif role in {"C", "E"} or pin_name in {"C", "E", "COLLECTOR", "EMITTER"}:  # Detect collector/emitter terminals.
                output_pins.add(pin_number)  # Record the output terminals.
        elif prefix == "M":  # MOSFET flow enters the gate and exits drain/source.
            if role == "G" or pin_name in {"G", "GATE"}:  # Detect the gate terminal.
                input_pins.add(pin_number)  # Record the gate as an input.
            elif role in {"D", "S"} or pin_name in {"D", "S", "DRAIN", "SOURCE"}:  # Detect drain/source terminals.
                output_pins.add(pin_number)  # Record the output terminals.
        elif prefix == "J":  # JFET flow enters the gate and exits drain/source.
            if role == "G" or pin_name in {"G", "GATE"}:  # Detect the gate terminal.
                input_pins.add(pin_number)  # Record the gate as an input.
            elif role in {"D", "S"} or pin_name in {"D", "S"}:  # Detect drain/source terminals.
                output_pins.add(pin_number)  # Record the output terminals.
        else:  # Generic subcircuits and controlled devices use role or name conventions.
            if role and ("IN" in role or role in {"+", "-"}):  # Detect explicit input roles.
                input_pins.add(pin_number)  # Record the input pin.
            elif role and "OUT" in role:  # Detect explicit output roles.
                output_pins.add(pin_number)  # Record the output pin.
            elif not role:  # Fall back to pin-name conventions for un-rolled symbols.
                if pin_name.startswith("IN") or pin_name in {"+", "-", "G", "B", "EN"}:  # Detect conventional input names.
                    input_pins.add(pin_number)  # Record the input pin.
                elif pin_name.startswith("OUT"):  # Detect conventional output names.
                    output_pins.add(pin_number)  # Record the output pin.
    return input_pins, output_pins  # Return the resolved pin role sets.


def _net_devices(records: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:  # Map every non-ground net onto its device records.
    net_devices: Dict[str, List[Dict[str, Any]]] = {}  # Collect the net-to-device lists.
    for record in records:  # Walk every component record.
        if record["power"]:  # Power symbols carry no flow nets.
            continue  # Move to the next record.
        for node_index in record["pin_map"]:  # Walk the used node positions.
            name = record["element"].nodes[node_index]  # Read the node name.
            if is_ground_net(name) or is_nc_net(name):  # Ground and no-connect stubs never propagate signal flow.
                continue  # Move to the next node.
            net_devices.setdefault(name, []).append(record)  # Register the device on the net.
    return net_devices  # Return the net membership mapping.


def _directed_flow_edges(  # Build deterministic directed flow edges from the current distance layers.
    records: Sequence[Dict[str, Any]],  # Accept the component records.
    roles: Dict[int, str],  # Accept the device role map.
    all_nets: Set[str],  # Accept every flow net name.
    distances: Dict[str, int],  # Accept the current net distances.
) -> List[Tuple[str, str]]:  # Return the directed edge list.

    def _append_ordered(first: str, second: str) -> None:  # Append one pair directed from the nearer net.
        if distances[first] < distances[second]:  # Direct from the smaller distance.
            edges.append((first, second))  # Append the forward edge.
        elif distances[second] < distances[first]:  # Direct from the smaller distance.
            edges.append((second, first))  # Append the forward edge.
        else:  # Break same-distance ties deterministically by name.
            if first < second:  # Order by net name.
                edges.append((first, second))  # Append the forward edge.
            else:  # Order by net name.
                edges.append((second, first))  # Append the forward edge.

    edges: List[Tuple[str, str]] = []  # Collect directed flow edges from smaller to larger distance.
    for record in records:  # Walk every component record.
        if record["power"]:  # Power symbols carry no flow edges.
            continue  # Move to the next record.
        uid = record["uid"]  # Read the unique placement id.
        role = roles.get(uid, "passive")  # Read the device role.
        flow_nets = [  # Collect the record's flow nets.
            record["element"].nodes[node_index] for node_index in record["pin_map"]
            if record["element"].nodes[node_index] in all_nets
        ]  # Finish the flow-net list.
        if role in ("series", "shunt_pwr") and len(flow_nets) >= 2:  # Series and rail-to-signal shunts connect their flow nets monotonically.
            for first_index, first in enumerate(flow_nets):  # Walk the flow-net pairs.
                for second in flow_nets[first_index + 1:]:  # Walk the remaining flow nets.
                    _append_ordered(first, second)  # Append the ordered edge pair.
        elif role == "active":  # Active devices add input-to-output edges.
            input_pins, output_pins = active_pin_roles(record)  # Resolve the pin roles.
            input_nets = [record["element"].nodes[i] for i in record["pin_map"] if record["pin_map"][i] in input_pins]  # Collect input nets.
            output_nets = [record["element"].nodes[i] for i in record["pin_map"] if record["pin_map"][i] in output_pins]  # Collect output nets.
            input_nets = [name for name in input_nets if name in all_nets]  # Keep known flow nets.
            output_nets = [name for name in output_nets if name in all_nets]  # Keep known flow nets.
            if not input_nets and not output_nets and len(flow_nets) >= 2:  # Ambiguous subcircuits flow through all pins bidirectionally.
                for first_index, first in enumerate(flow_nets):  # Walk the flow-net pairs.
                    for second in flow_nets[first_index + 1:]:  # Walk the remaining flow nets.
                        _append_ordered(first, second)  # Append the ordered edge pair.
                continue  # Move to the next record.
            for input_net in input_nets:  # Walk the input nets.
                for output_net in output_nets:  # Walk the output nets.
                    if input_net == output_net:  # Skip self-loops.
                        continue  # Move to the next pair.
                    if distances[input_net] < distances[output_net]:  # Preserve downhill direction.
                        edges.append((input_net, output_net))  # Append the role edge.
                    elif distances[output_net] < distances[input_net]:  # Flip feedback edges downhill.
                        edges.append((output_net, input_net))  # Append the reversed edge.
                    else:  # Same-distance inputs flow toward outputs by role.
                        edges.append((input_net, output_net))  # Append the role edge.
    return edges  # Return the directed edge list.


def _net_layers(records: Sequence[Dict[str, Any]], roles: Dict[int, str]) -> Dict[str, int]:  # Assign a signal-flow column index to every flow net.
    net_devices = _net_devices(records)  # Read the net membership mapping.
    all_nets = set(net_devices)  # Collect every flow net name.
    adjacency: Dict[str, Set[str]] = {name: set() for name in all_nets}  # Build the undirected net adjacency.
    for record in records:  # Walk every component record.
        if record["power"]:  # Power symbols contribute no flow edges.
            continue  # Move to the next record.
        flow_nets = [  # Collect the record's non-ground nets.
            record["element"].nodes[node_index] for node_index in record["pin_map"]
            if record["element"].nodes[node_index] in all_nets
        ]  # Finish the flow-net list.
        for first in flow_nets:  # Walk the record's flow nets pairwise.
            for second in flow_nets:  # Walk the remaining flow nets.
                if first != second:  # Connect distinct nets.
                    adjacency[first].add(second)  # Add the undirected edge.
                    adjacency[second].add(first)  # Add the reverse edge.
    distances: Dict[str, int] = {}  # Store BFS distances from the sources.
    pending = deque()  # Prepare the BFS queue.
    for record in records:  # Seed the traversal from every source output net.
        if record["power"] or roles.get(record["uid"]) != "source":  # Skip non-source devices.
            continue  # Move to the next record.
        nodes = record["element"].nodes  # Read the source nodes.
        positive = nodes[0] if nodes else ""  # Read the positive node.
        if positive in all_nets:  # Seed only known flow nets.
            if positive not in distances:  # Avoid duplicate seeds.
                distances[positive] = 0  # Place the source output at distance zero.
                pending.append(positive)  # Queue the seed.

    def _flood() -> None:  # Expand the BFS until the queue empties.
        while pending:  # Process every queued net.
            current = pending.popleft()  # Read the next net.
            for neighbor in sorted(adjacency[current]):  # Walk its neighbors deterministically.
                if neighbor not in distances:  # Assign first-visit distances only.
                    distances[neighbor] = distances[current] + 1  # Record the BFS distance.
                    pending.append(neighbor)  # Queue the neighbor.
    _flood()  # Flood from the source seeds.
    if not distances:  # Source-less decks seed from one end of the net-diameter pseudo-source.
        first_distances: Dict[str, int] = {}  # Store the first BFS sweep distances.
        first_pending = deque([min(sorted(all_nets))])  # Start the sweep from the first sorted net.
        first_distances[min(sorted(all_nets))] = 0  # Place the sweep start at distance zero.
        while first_pending:  # Expand the first sweep until the queue empties.
            current = first_pending.popleft()  # Read the next net.
            for neighbor in sorted(adjacency[current]):  # Walk its neighbors deterministically.
                if neighbor not in first_distances:  # Assign first-visit distances only.
                    first_distances[neighbor] = first_distances[current] + 1  # Record the BFS distance.
                    first_pending.append(neighbor)  # Queue the neighbor.
        seed = max(sorted(all_nets), key=lambda name: (first_distances.get(name, -1), name))  # Pick the farthest deterministic net as the pseudo-source.
        distances[seed] = 0  # Place the pseudo-source at distance zero.
        pending.append(seed)  # Queue the pseudo-source.
        _flood()  # Flood from the pseudo-source.
    for name in sorted(all_nets):  # Cover components unreachable from any source.
        if name in distances:  # Skip already-reached nets.
            continue  # Move to the next net.
        distances[name] = 0  # Treat the isolated component as a local source.
        pending.append(name)  # Queue the local seed.
        _flood()  # Flood the remaining component.

    edges = _directed_flow_edges(records, roles, all_nets, distances)  # Direct the first edge set.
    for _iteration in range(len(all_nets) + 1):  # Iteratively deepen the layers until the direction map stabilizes.
        refined = _longest_path_layers(all_nets, edges)  # Recompute the longest-path layers over the directed edges.
        if refined == distances:  # The layering converged.
            return refined  # Return the stable layers.
        distances = refined  # Adopt the deepened layers.
        edges = _directed_flow_edges(records, roles, all_nets, distances)  # Re-direct the edges by the new layers.
    return _longest_path_layers(all_nets, edges)  # Return the last computed layers at the iteration cap.


def _longest_path_layers(nets: Set[str], edges: Sequence[Tuple[str, str]]) -> Dict[str, int]:  # Compute longest-path net layers over the directed edges.
    predecessors: Dict[str, List[str]] = {}  # Index every predecessor of each net.
    for source, target in edges:  # Walk the directed edges.
        predecessors.setdefault(target, []).append(source)  # Record the predecessor.
    memo: Dict[str, int] = {}  # Cache computed layers.
    visiting: Set[str] = set()  # Track the DFS stack for cycle safety.

    def _layer(name: str) -> int:  # Compute one net's longest-path layer.
        if name in memo:  # Reuse the cached layer.
            return memo[name]  # Return the cached value.
        if name in visiting:  # Ignore back edges on feedback paths.
            return 0  # Break the cycle deterministically.
        visiting.add(name)  # Mark the net as in-progress.
        best = 0  # Seed the longest path.
        for predecessor in predecessors.get(name, ()):  # Walk the predecessors.
            best = max(best, _layer(predecessor) + 1)  # Extend the longest path.
        visiting.discard(name)  # Unmark the net.
        memo[name] = best  # Cache the computed layer.
        return best  # Return the longest-path layer.
    for name in sorted(nets):  # Compute every net layer deterministically.
        _layer(name)  # Evaluate the longest path.
    return memo  # Return the layer mapping.


def _component_columns(records: Sequence[Dict[str, Any]], roles: Dict[int, str], layers: Dict[str, int]) -> Dict[int, int]:  # Assign one column index to every device.
    columns: Dict[int, int] = {}  # Collect the column assignments.
    for record in records:  # Walk every component record.
        if record["power"]:  # Power symbols attach after routing.
            continue  # Move to the next record.
        uid = record["uid"]  # Read the unique placement id.
        role = roles.get(uid, "passive")  # Read the device role.
        flow_nets = [record["element"].nodes[i] for i in record["pin_map"] if record["element"].nodes[i] in layers]  # Collect the device flow nets.
        if role == "source":  # Sources sit in the leftmost column.
            columns[uid] = 0  # Place the source at column zero.
        elif flow_nets:  # Ordinary devices sit at their downstream net layer.
            column = max(layers[name] for name in flow_nets)  # Use the deepest flow net.
            if role == "shunt_gnd":  # Ground shunts get their own column past the driven net.
                column += 1  # Place the leaf just beyond its signal net.
            columns[uid] = column  # Store the resolved column.
        else:  # All-ground devices inherit their consumer's column.
            columns[uid] = None  # Resolve all-ground columns below.
    for record in records:  # Resolve all-ground device columns from their shared-net consumers.
        if record["power"]:  # Skip power symbols.
            continue  # Move to the next record.
        uid = record["uid"]  # Read the unique placement id.
        if columns[uid] is not None:  # Skip already-assigned devices.
            continue  # Move to the next record.
        used_nets = {record["element"].nodes[i] for i in record["pin_map"]}  # Collect every node of the device.
        best = 0  # Seed the inherited column.
        for other in records:  # Walk every candidate consumer.
            if other["power"] or other["uid"] == uid:  # Skip self and power records.
                continue  # Move to the next candidate.
            other_nets = {other["element"].nodes[i] for i in other["pin_map"]}  # Collect the consumer's nodes.
            if used_nets & other_nets:  # Detect a shared net.
                other_column = columns.get(other["uid"])  # Read the consumer's column.
                if other_column is not None:  # Keep only resolved consumers.
                    best = max(best, other_column)  # Inherit the consumer's column.
        columns[uid] = best  # Store the inherited column.
    return columns  # Return the column assignments.


def _barycenter_rows(records: Sequence[Dict[str, Any]], columns: Dict[int, int]) -> Dict[int, int]:  # Order devices inside each column with a barycenter sweep.
    grouped: Dict[int, List[Dict[str, Any]]] = {}  # Group devices by column.
    for record in records:  # Walk every component record.
        if record["power"]:  # Power symbols attach after routing.
            continue  # Move to the next record.
        grouped.setdefault(columns[record["uid"]], []).append(record)  # Append the device to its column.
    for column in grouped:  # Deterministically order the initial rows.
        grouped[column].sort(key=lambda record: (str(record["reference"]), record["uid"]))  # Sort by reference then id.
    rows: Dict[int, int] = {}  # Store the current row index per device.
    for column in sorted(grouped):  # Assign the initial row indices.
        for row_index, record in enumerate(grouped[column]):  # Walk the sorted group.
            rows[record["uid"]] = row_index  # Store the row index.
    adjacency = _device_adjacency(records, columns)  # Build the device neighbor graph.
    for sweep in range(_BARYCENTER_SWEEPS):  # Alternate the sweep direction.
        column_order = sorted(grouped)  # Process columns left to right.
        if sweep % 2 == 1:  # Reverse on alternating sweeps.
            column_order = column_order[::-1]  # Process columns right to left.
        for column in column_order:  # Walk the current column order.
            def _barycenter_key(record: Dict[str, Any]) -> Tuple[float, str, int]:  # Compute one device's ordering key.
                total = 0.0  # Accumulate the neighbor row sum.
                count = 0  # Count the contributing neighbors.
                for other_uid in adjacency.get(record["uid"], ()):  # Walk the device neighbors.
                    if other_uid in rows and columns.get(other_uid) != column:  # Use resolved neighbors in other columns.
                        total += rows[other_uid]  # Accumulate the neighbor row.
                        count += 1  # Count the neighbor.
                if count:  # Prefer the mean neighbor row.
                    return total / count, str(record["reference"]), record["uid"]  # Return the barycenter key.
                return float("inf"), str(record["reference"]), record["uid"]  # Keep isolated devices stable.
            grouped[column].sort(key=_barycenter_key)  # Reorder the column by barycenter.
            for row_index, record in enumerate(grouped[column]):  # Write the new row indices.
                rows[record["uid"]] = row_index  # Store the updated row index.
    return rows  # Return the row assignments.


def _device_adjacency(records: Sequence[Dict[str, Any]], columns: Dict[int, int]) -> Dict[int, Set[int]]:  # Build the device neighbor graph from shared flow nets.
    adjacency: Dict[int, Set[int]] = {record["uid"]: set() for record in records if not record["power"]}  # Seed the adjacency.
    net_members: Dict[str, List[int]] = {}  # Collect device ids per flow net.
    for record in records:  # Walk every component record.
        if record["power"]:  # Power symbols carry no flow membership.
            continue  # Move to the next record.
        for node_index in record["pin_map"]:  # Walk the used node positions.
            name = record["element"].nodes[node_index]  # Read the node name.
            if is_ground_net(name):  # Ground never propagates signal flow.
                continue  # Move to the next node.
            net_members.setdefault(name, []).append(record["uid"])  # Register the device on the net.
    for members in net_members.values():  # Connect every pair sharing a net.
        for first_index, first_uid in enumerate(members):  # Walk the member pairs.
            for second_uid in members[first_index + 1:]:  # Walk the remaining members.
                adjacency.setdefault(first_uid, set()).add(second_uid)  # Add the neighbor edge.
                adjacency.setdefault(second_uid, set()).add(first_uid)  # Add the reverse edge.
    return adjacency  # Return the neighbor graph.


def _snap(value: float, grid: float) -> float:  # Snap one value onto the placement grid.
    return round(value / grid) * grid  # Return the snapped value.


def _pin_world(record: Dict[str, Any], pin_number: str, angle: float) -> Tuple[float, float]:  # Transform one pin to schematic coordinates at a candidate angle.
    local_x, local_y, _pin_name = record["pins"][pin_number]  # Read the local pin geometry.
    return _transform_point(local_x, local_y, 0.0, 0.0, angle, "")  # Return the transformed pin position.


def _angle_for_pin_facing(record: Dict[str, Any], pin_number: str, side: str) -> float:  # Choose the angle placing one pin on the requested side.
    candidates = (0.0, 90.0, 180.0, 270.0)  # Evaluate every quarter turn.
    if side == "left":  # Face the pin toward the left edge.
        return min(candidates, key=lambda angle: _pin_world(record, pin_number, angle)[0])  # Minimize the pin X.
    if side == "right":  # Face the pin toward the right edge.
        return max(candidates, key=lambda angle: _pin_world(record, pin_number, angle)[0])  # Maximize the pin X.
    if side == "top":  # Face the pin toward the top edge.
        return min(candidates, key=lambda angle: _pin_world(record, pin_number, angle)[1])  # Minimize the pin Y.
    if side == "bottom":  # Face the pin toward the bottom edge.
        return max(candidates, key=lambda angle: _pin_world(record, pin_number, angle)[1])  # Maximize the pin Y.
    return 0.0  # Return the upright angle for unknown sides.


def _flow_orientation(record: Dict[str, Any], roles: Dict[int, str], layers: Dict[str, int]) -> float:  # Choose one device's angle from its role and resolved pin geometry.
    role = roles.get(record["uid"], "passive")  # Read the device role.
    if role == "source":  # Sources stay upright in the leftmost column.
        return 0.0  # Return the upright angle.
    if role == "series":  # Series devices lie horizontal with the upstream pin facing left.
        flow_pairs = [(record["element"].nodes[i], i) for i in record["pin_map"] if record["element"].nodes[i] in layers]  # Collect the flow net pairs.
        if len(flow_pairs) == 2:  # Require two flow nets for a series element.
            upstream_node = min(flow_pairs, key=lambda pair: layers[pair[0]])[0]  # Find the upstream net.
            upstream_index = next(index for name, index in flow_pairs if name == upstream_node)  # Find its node index.
            upstream_pin = record["pin_map"][upstream_index]  # Resolve the upstream pin.
            if upstream_pin in record["pins"]:  # Require resolved pin geometry.
                upstream_angle = _angle_for_pin_facing(record, upstream_pin, "left")  # Face the upstream pin left.
                if upstream_angle in (0.0, 180.0):  # Break symmetric-body parity deterministically by pin name.
                    if abs(_pin_world(record, upstream_pin, 0.0)[0] - _pin_world(record, upstream_pin, 180.0)[0]) < 1e-9:  # Both angles place the pin identically.
                        other_pins = [pin for pin in record["pin_map"].values() if pin != upstream_pin]  # Collect the remaining pins.
                        if other_pins:  # Require a tie-break partner.
                            other_name = str(record["pins"][other_pins[0]][2])  # Read the partner pin name.
                            upstream_name = str(record["pins"][upstream_pin][2])  # Read the upstream pin name.
                            if other_name < upstream_name:  # Order the parity by pin-name order.
                                return 180.0  # Return the flipped parity.
                return upstream_angle  # Return the resolved series angle.
        return 0.0  # Fall back to the upright angle.
    if role == "shunt_gnd":  # Ground shunts stand vertical with the ground pin down.
        for node_index in record["pin_map"]:  # Walk the used node positions.
            if is_ground_net(record["element"].nodes[node_index]):  # Detect the ground terminal.
                ground_pin = record["pin_map"][node_index]  # Resolve the ground pin.
                if ground_pin in record["pins"]:  # Require resolved pin geometry.
                    return _angle_for_pin_facing(record, ground_pin, "bottom")  # Face the ground pin down.
        return 0.0  # Fall back to the upright angle.
    if role == "shunt_pwr":  # Supply shunts stand vertical with the supply pin up.
        for node_index in record["pin_map"]:  # Walk the used node positions.
            if is_supply_net(record["element"].nodes[node_index]):  # Detect the supply terminal.
                supply_pin = record["pin_map"][node_index]  # Resolve the supply pin.
                if supply_pin in record["pins"]:  # Require resolved pin geometry.
                    return _angle_for_pin_facing(record, supply_pin, "top")  # Face the supply pin up.
        return 0.0  # Fall back to the upright angle.
    if role == "active":  # Active devices stay upright so inputs always read from the left.
        return 0.0  # Return the upright angle.
    return 0.0  # Return the upright angle for passive devices.


def _pins_both_sides(record: Dict[str, Any]) -> bool:  # Decide whether a device's pins protrude symmetrically on both body sides.
    xs = [record["pins"][pin_number][0] for pin_number in record["pin_map"].values() if pin_number in record["pins"]]  # Collect the local pin X offsets.
    if len(xs) < 2:  # Require at least two pins to judge the symmetry.
        return False  # Report the body as asymmetric.
    return min(xs) < -_BODY_SYMMETRY_TOL and max(xs) > _BODY_SYMMETRY_TOL  # Report pins on both sides of the origin.


def apply_differential_pair_symmetry(  # Mirror one member of every same-symbol input-net pair vertically.
    records: Sequence[Dict[str, Any]],  # Accept the placed component records.
) -> None:  # Update paired record angles in place.
    roles = classify_flow_roles(records)  # Reuse the flow role classification for pair detection.
    members_by_key: Dict[Tuple[float, str, str], List[Dict[str, Any]]] = {}  # Group active devices by column, symbol, and input net.
    for record in records:  # Walk every component record.
        if record["power"] or roles.get(record["uid"]) != "active":  # Only active devices form differential pairs.
            continue  # Move to the next record.
        input_pins, _output_pins = active_pin_roles(record)  # Resolve the device input pins.
        if not input_pins:  # Require at least one input pin for pair detection.
            continue  # Move to the next record.
        input_nets = {  # Collect the input nets attached to this device.
            record["element"].nodes[node_index] for node_index in record["pin_map"] if record["pin_map"][node_index] in input_pins
        }  # Finish the input-net set.
        for net_name in sorted(input_nets):  # Register the device on every input net.
            members_by_key.setdefault((round(float(record["x"]), 6), str(record["lib_id"]), net_name), []).append(record)  # Group by column, symbol, and input net.
    for _key in sorted(members_by_key):  # Process every pair group deterministically.
        members = members_by_key[_key]  # Read the group members.
        members.sort(key=lambda member: (float(member["y"]), int(member["uid"])))  # Order the members by row and id.
        for upper, lower in zip(members[0::2], members[1::2]):  # Pair consecutive members of the group.
            upper_angle = float(upper["angle"]) % 360.0  # Read the upper member angle.
            lower_angle = float(lower["angle"]) % 360.0  # Read the lower member angle.
            if not (_pins_both_sides(upper) and _pins_both_sides(lower)):  # Mirror only geometrically symmetric bodies.
                continue  # Keep asymmetric devices upright.
            if upper_angle == lower_angle and upper_angle in (0.0, 180.0):  # Mirror only already-parallel upright pairs.
                lower["angle"] = 180.0 - upper_angle  # Flip the lower member vertically for symmetric reading.


def apply_flow_placement(  # Place every ordinary device using the signal-flow layout.
    records: Sequence[Dict[str, Any]],  # Accept the component records.
    grid: float,  # Accept the placement grid.
    page_width: float,  # Accept the page width.
    page_height: float,  # Accept the page height.
) -> Optional[Dict[str, int]]:  # Return the net-column mapping or None when the plan must fall back.
    ordinary = [record for record in records if not record["power"]]  # Collect the placeable devices.
    count = len(ordinary)  # Count the placeable devices.
    if count == 0:  # Nothing to place.
        return {}  # Return an empty mapping.
    roles = classify_flow_roles(records)  # Classify every device role.
    layers = _net_layers(records, roles)  # Assign the flow layers.
    columns = _component_columns(records, roles, layers)  # Assign the column indices.
    ordered_columns = sorted({value for value in columns.values() if value is not None})  # Collect the occupied columns.
    column_remap = {value: index for index, value in enumerate(ordered_columns)}  # Build the empty-column collapse map.
    for uid in columns:  # Renumber every occupied column.
        columns[uid] = column_remap[columns[uid]]  # Collapse the gaps so no empty column widens the plan.
    rows = _barycenter_rows(records, columns)  # Assign the row indices.
    widths: Dict[int, float] = {}  # Collect rotated body widths.
    heights: Dict[int, float] = {}  # Collect rotated body heights.
    angles: Dict[int, float] = {}  # Collect the role orientations.
    for record in ordinary:  # Measure every device body.
        uid = record["uid"]  # Read the unique placement id.
        angles[uid] = _flow_orientation(record, roles, layers)  # Resolve the role orientation first.
        bounds = record.get("body_bounds")  # Read the looked-up local body bounds.
        if bounds is not None:  # Rotate the local extents onto the world axes.
            cosine = abs(math.cos(math.radians(angles[uid])))  # Read the rotation cosine magnitude.
            sine = abs(math.sin(math.radians(angles[uid])))  # Read the rotation sine magnitude.
            local_width = max(bounds[2] - bounds[0], _MIN_BODY)  # Measure the local width.
            local_height = max(bounds[3] - bounds[1], _MIN_BODY)  # Measure the local height.
            width = local_width * cosine + local_height * sine  # Rotate the width onto the world X axis.
            height = local_width * sine + local_height * cosine  # Rotate the height onto the world Y axis.
        else:  # Graphics-less symbols keep the default body.
            width = _DEFAULT_BODY  # Store the fallback width.
            height = _DEFAULT_BODY  # Store the fallback height.
        widths[uid] = max(width, _MIN_BODY)  # Store the floor width.
        heights[uid] = max(height, _MIN_BODY)  # Store the floor height.
    column_gap = _COLUMN_GAP_GRID_UNITS * grid  # Derive the human column gap from the placement grid.
    row_gap = _ROW_GAP_GRID_UNITS * grid  # Derive the tighter row gap from the placement grid.
    column_count = max(columns.values()) + 1  # Count the columns.
    row_count = max(rows.values()) + 1  # Count the rows.

    def _grid_extents(  # Measure per-column widths and per-row heights for one column/row mapping.
        column_map: Dict[int, int],  # Accept the device-to-column mapping.
        row_map: Dict[int, int],  # Accept the device-to-row mapping.
    ) -> Tuple[List[float], List[float]]:  # Return the column-width and row-height arrays.
        resolved_widths: List[float] = [0.0] * (max(column_map.values()) + 1)  # Collect each column's widest body.
        resolved_heights: List[float] = [0.0] * (max(row_map.values()) + 1)  # Collect each row's tallest body.
        for record in ordinary:  # Accumulate per-column widths and per-row heights.
            resolved_widths[column_map[record["uid"]]] = max(resolved_widths[column_map[record["uid"]]], widths[record["uid"]])  # Widen the column.
            resolved_heights[row_map[record["uid"]]] = max(resolved_heights[row_map[record["uid"]]], heights[record["uid"]])  # Raise the row.
        return resolved_widths, resolved_heights  # Return the measured arrays.

    def _fit_plan(  # Build a plan from the given grid and gaps, expanding small plans and rejecting overflows.
        resolved_widths: List[float],  # Accept the per-column widths.
        resolved_heights: List[float],  # Accept the per-row heights.
        gaps: Sequence[float],  # Accept the column gap sequence.
        gap_row: float,  # Accept the row gap.
        allow_spread: bool,  # Accept whether small plans may be stretched.
    ) -> Optional[Tuple[List[float], List[float], float, float]]:  # Return the centers and extents or None.
        resolved_column_count = len(resolved_widths)  # Count the columns.
        resolved_row_count = len(resolved_heights)  # Count the rows.
        column_centers: List[float] = [resolved_widths[0] / 2.0]  # Place the first column center.
        for index in range(1, resolved_column_count):  # Step through the remaining columns.
            column_centers.append(column_centers[-1] + (resolved_widths[index - 1] + resolved_widths[index]) / 2.0 + gaps[index - 1])  # Space centers by the adjacent half-widths plus the gap.
        row_centers: List[float] = [resolved_heights[0] / 2.0]  # Place the first row center.
        for index in range(1, resolved_row_count):  # Step through the remaining rows.
            row_centers.append(row_centers[-1] + (resolved_heights[index - 1] + resolved_heights[index]) / 2.0 + gap_row)  # Space centers by the adjacent half-heights plus the gap.
        total_width = column_centers[-1] + resolved_widths[-1] / 2.0  # Measure the plan width.
        total_height = row_centers[-1] + resolved_heights[-1] / 2.0  # Measure the plan height.
        fit_width = page_width - _PAGE_FIT_MARGIN_GRID_UNITS * grid  # Reserve snap margin at the right edge.
        fit_height = page_height - _PAGE_FIT_MARGIN_GRID_UNITS * grid  # Reserve snap margin at the bottom edge.
        if total_width > fit_width or total_height > fit_height:  # Reject plans that overflow the page.
            return None  # Signal the fallback to the hybrid engine.
        two_dimensional = resolved_column_count > 1 and resolved_row_count > 1  # Distinguish grids from chains.
        chain_plan = resolved_column_count == 1 and resolved_row_count >= _CHAIN_STRETCH_MIN_ROWS  # Long one-column chains may also be stretched.
        spread_cap = _SPREAD_SCALE_CAP if two_dimensional else _CHAIN_STRETCH_SCALE_CAP  # Bound the stretch by the plan shape.
        spread = min(  # Compute the small-plan stretch factor.
            _SPREAD_PLAN_FRACTION * page_width / total_width,  # Stretch the width toward the target fraction.
            _SPREAD_PLAN_FRACTION * page_height / total_height,  # Stretch the height toward the target fraction.
            spread_cap,  # Bound the stretch factor.
        )  # Finish the spread computation.
        if allow_spread and (two_dimensional or chain_plan) and spread > 1.0 and (total_width < _SMALL_PLAN_FRACTION * page_width or total_height < _SMALL_PLAN_FRACTION * page_height):  # Spread small plans so they do not bunch in a corner.
            scaled_gaps = [gap * spread for gap in gaps]  # Stretch the column gaps uniformly.
            scaled_row_gap = gap_row * spread  # Stretch the row gap uniformly.
            return _fit_plan(resolved_widths, resolved_heights, scaled_gaps, scaled_row_gap, False)  # Re-fit the stretched plan without recursing again.
        return column_centers, row_centers, total_width, total_height  # Return the fitted plan geometry.

    column_widths, row_heights = _grid_extents(columns, rows)  # Measure the primary grid.

    def _try_fold(  # Split the rows of a too-tall plan into appended sub-columns before falling back.
        fold_rows: int,  # Accept the rows kept per sub-column.
        gaps: Sequence[float],  # Accept the column gap sequence.
        gap_row: float,  # Accept the row gap.
    ) -> Optional[Tuple[Dict[int, int], Dict[int, int], Tuple[List[float], List[float], float, float]]]:  # Return the folded mappings and fit or None.
        if fold_rows < 2:  # A single row cannot be folded.
            return None  # Report no folded fit.
        folded_columns: Dict[int, int] = {}  # Collect the folded device columns.
        folded_rows: Dict[int, int] = {}  # Collect the folded device rows.
        for record in ordinary:  # Walk every placed device.
            uid = record["uid"]  # Read the unique placement id.
            chunk = rows[uid] // fold_rows  # Read the row chunk index.
            folded_columns[uid] = columns[uid] + chunk * column_count  # Append the chunk as new columns to the right.
            folded_rows[uid] = rows[uid] % fold_rows  # Keep the local row inside the chunk.
        folded_widths, folded_heights = _grid_extents(folded_columns, folded_rows)  # Measure the folded grid.
        folded_gaps = list(gaps) + [_COMPACT_COLUMN_GAP_GRID_UNITS * grid] * (len(folded_widths) - len(gaps))  # Extend the gap sequence for the appended columns.
        fitted = _fit_plan(folded_widths, folded_heights, folded_gaps, gap_row, False)  # Fit the folded plan without spreading.
        if fitted is None:  # The folded plan still overflows.
            return None  # Report no folded fit.
        return folded_columns, folded_rows, fitted  # Return the folded mappings and geometry.

    default_gaps: List[float] = []  # Collect the width-aware gaps between adjacent columns.
    for index in range(column_count - 1):  # Walk the column boundaries.
        default_gaps.append(column_gap)  # Use the standard human gap.
    fitted = _fit_plan(column_widths, row_heights, default_gaps, row_gap, True)  # Try the primary human pitch first.
    adopted_columns, adopted_rows = columns, rows  # Track the mapping used by the accepted fit.
    if fitted is None:  # Oversized plans retry with a minimum pitch before falling back.
        shrink_gaps = [_SHRINK_COLUMN_GAP_GRID_UNITS * grid] * (column_count - 1)  # Build the minimum column gap sequence.
        shrink_row_gap = _SHRINK_ROW_GAP_GRID_UNITS * grid  # Build the minimum row gap.
        fitted = _fit_plan(column_widths, row_heights, shrink_gaps, shrink_row_gap, False)  # Retry the plan with the minimum gaps.
    if fitted is None:  # The minimum plan cannot fit the page height.
        row_pitch = max(row_heights) + _SHRINK_ROW_GAP_GRID_UNITS * grid  # Estimate the row pitch at the minimum gap.
        fit_rows = max(2, int((page_height - _PAGE_FIT_MARGIN_GRID_UNITS * grid) / max(row_pitch, 1e-9)))  # Count rows that fit the page height.
        folded = None  # Try folding the tall plan into appended sub-columns.
        for fold_rows in range(fit_rows, 1, -1):  # Step the fold depth down from the fitted height until one succeeds.
            folded = _try_fold(fold_rows, shrink_gaps, shrink_row_gap)  # Try the current fold depth.
            if folded is not None:  # The folded plan fits the page.
                break  # Accept the shallowest successful fold.
        if folded is not None:  # A fold succeeded before the hybrid engine is needed.
            adopted_columns, adopted_rows, fitted = folded  # Unpack the folded mappings and geometry.
    if fitted is None:  # Neither the primary, minimum, nor folded plan fits the page.
        return None  # Signal the fallback to the hybrid engine.
    column_centers, row_centers, total_width, total_height = fitted  # Unpack the fitted plan geometry.
    origin_x = _snap((page_width - total_width) / 2.0, grid)  # Center the plan horizontally.
    origin_y = _snap((page_height - total_height) / 2.0, grid)  # Center the plan vertically.
    for record in ordinary:  # Write the final poses back into the records.
        uid = record["uid"]  # Read the unique placement id.
        record["x"] = _snap(origin_x + column_centers[adopted_columns[uid]], grid)  # Assign the column coordinate.
        record["y"] = _snap(origin_y + row_centers[adopted_rows[uid]], grid)  # Assign the row coordinate.
        record["angle"] = angles[uid]  # Assign the role orientation.
    apply_differential_pair_symmetry(records)  # Mirror one member of every differential pair after the base angles are set.
    net_columns: Dict[str, int] = {}  # Collect the leftmost device column per net.
    for record in ordinary:  # Walk every placed device.
        column = adopted_columns[record["uid"]]  # Read the device column.
        for node_index in record["pin_map"]:  # Walk the used node positions.
            name = record["element"].nodes[node_index]  # Read the node name.
            if name in layers:  # Keep only flow nets.
                net_columns[name] = min(net_columns.get(name, column), column)  # Record the leftmost column.
    return net_columns  # Return the net-column mapping for routing order.
