"""Compare two KiCad schematic (.kicad_sch) files for structural, connectivity,
and relative-layout (symbol position + orientation, wire geometry) differences.

Run modes
---------
Single pair:
    compare_kicad_sch.py <file_a> <file_b> [--tolerance FLOAT] [--verbose]

Directory mode (compares files with matching names in two directories):
    compare_kicad_sch.py <dir_a> <dir_b> [--tolerance FLOAT] [--verbose]

The comparison is translation/rotation/scale tolerant: symbol positions are
compared only as *relative* geometry after finding the best rigid transform
(rotation in 90-degree steps, optional mirror, uniform scale) that aligns the
matched symbol positions.  Symbol orientations, wire geometry, electrical
connectivity, and header/property metadata are compared directly.

Exit status is 0 when every compared pair matches, otherwise 1.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import math
import os
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

os.environ.setdefault("PYTHONHASHSEED", "0")  # Fix the hash seed so spawned workers run the graph-isomorphism search deterministically.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
_SOURCE_DIRECTORY = _ROOT_DIRECTORY / "src"

if str(_SOURCE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_SOURCE_DIRECTORY))

from electronics_design.kicad_sexp_parser import SExp, parse_string

_POINT_TOLERANCE = 1e-4


def _first_atom(node: Optional[SExp]) -> str:
    if node is None:
        return ""
    for child in node.children:
        if child.is_atom:
            return str(child.value)
    return ""


def _atom_values(node: Optional[SExp]) -> List[object]:
    if node is None:
        return []
    return [child.value for child in node.children if child.is_atom]


class _UnionFind:
    def __init__(self) -> None:
        self._parent: Dict[str, str] = {}

    def add(self, key: str) -> None:
        if key not in self._parent:
            self._parent[key] = key

    def find(self, key: str) -> str:
        root = key
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[key] != key:
            nxt = self._parent[key]
            self._parent[key] = root
            key = nxt
        return root

    def union(self, first: str, second: str) -> None:
        root_a = self.find(first)
        root_b = self.find(second)
        if root_a != root_b:
            self._parent[root_b] = root_a


def _point_key(x: float, y: float) -> str:
    return f"{round(x, 4)}|{round(y, 4)}"


def _point_on_segment(px: float, py: float, segment: Tuple[float, float, float, float]) -> bool:
    start_x, start_y, end_x, end_y = segment
    if px < min(start_x, end_x) - _POINT_TOLERANCE or px > max(start_x, end_x) + _POINT_TOLERANCE:
        return False
    if py < min(start_y, end_y) - _POINT_TOLERANCE or py > max(start_y, end_y) + _POINT_TOLERANCE:
        return False
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    length_squared = delta_x * delta_x + delta_y * delta_y
    if length_squared == 0.0:
        return abs(px - start_x) <= _POINT_TOLERANCE and abs(py - start_y) <= _POINT_TOLERANCE
    projection = ((px - start_x) * delta_x + (py - start_y) * delta_y) / length_squared
    if projection < -1e-9 or projection > 1.0 + 1e-9:
        return False
    closest_x = start_x + projection * delta_x
    closest_y = start_y + projection * delta_y
    return abs(px - closest_x) <= _POINT_TOLERANCE and abs(py - closest_y) <= _POINT_TOLERANCE


def _transform_point(local_x: float, local_y: float, origin_x: float, origin_y: float, angle: float, mirror: str) -> Tuple[float, float]:
    if mirror == "x":
        local_y = -local_y
    elif mirror == "y":
        local_x = -local_x
    radians = math.radians(angle)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    rotated_x = local_x * cosine - local_y * sine
    rotated_y = local_x * sine + local_y * cosine
    return origin_x + rotated_x, origin_y - rotated_y


def _symbol_body_bounds(symbol_node: SExp) -> Optional[Tuple[float, float, float, float]]:
    """Measure the local bounding box of a library symbol's drawn graphics."""
    xs: List[float] = []
    ys: List[float] = []

    def collect(node: SExp) -> None:
        for child in node.children:
            if child.name in ("polyline", "rectangle", "bezier"):
                for xy_node in child.find_children("xy"):
                    values = _atom_values(xy_node)
                    if len(values) >= 2:
                        xs.append(float(values[0]))
                        ys.append(float(values[1]))
            elif child.name == "circle":
                center_values = _atom_values(child.find_child("center"))
                radius_values = _atom_values(child.find_child("radius"))
                if len(center_values) >= 2 and radius_values:
                    radius = float(radius_values[0])
                    xs.extend((float(center_values[0]) - radius, float(center_values[0]) + radius))
                    ys.extend((float(center_values[1]) - radius, float(center_values[1]) + radius))
            elif child.name == "arc":
                for key in ("start", "mid", "end"):
                    point_values = _atom_values(child.find_child(key))
                    if len(point_values) >= 2:
                        xs.append(float(point_values[0]))
                        ys.append(float(point_values[1]))
            elif child.name == "symbol":
                collect(child)

    collect(symbol_node)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _text_font_size(node: SExp) -> float:
    """Read the font height of a text node's effects section."""
    effects = node.find_child("effects")
    if effects is None:
        return 1.27
    font = effects.find_child("font")
    if font is None:
        return 1.27
    size_values = _atom_values(font.find_child("size"))
    if not size_values:
        return 1.27
    try:
        return float(size_values[0])
    except (TypeError, ValueError):
        return 1.27


def _text_is_visible(node: SExp) -> bool:
    """Decide whether a text node is actually rendered at a readable size."""
    effects = node.find_child("effects")
    if effects is not None and any(child.is_atom and str(child.value) == "hide" for child in effects.children):
        return False
    return _text_font_size(node) >= 0.5


def _text_rect(x: float, y: float, text: str, font_size: float, angle: float = 0.0) -> Tuple[float, float, float, float]:
    """Approximate the bounding box of one text string centered on its anchor."""
    character_count = len(text)
    width = font_size * (0.68 * character_count + 0.015 * max(0, character_count - 1))
    height = font_size * 1.27
    normalized = angle % 360.0
    if abs(normalized - 90.0) < 1e-6 or abs(normalized - 270.0) < 1e-6:
        width, height = height, width
    return x - width / 2.0, y - height / 2.0, x + width / 2.0, y + height / 2.0


def _collect_instance_text_rects(instance_node: SExp, record: SymbolRecord) -> List[Tuple[float, float, float, float]]:
    """Collect the world-space text boxes of one symbol instance's visible fields."""
    rects: List[Tuple[float, float, float, float]] = []
    for property_node in instance_node.find_children("property"):
        values = _atom_values(property_node)
        if len(values) < 2:
            continue
        at_values = _atom_values(property_node.find_child("at"))
        if len(at_values) < 2:
            continue
        if not _text_is_visible(property_node):
            continue
        anchor_x, anchor_y = _transform_point(float(at_values[0]), float(at_values[1]), record.x, record.y, record.angle, record.mirror)
        rects.append(_text_rect(anchor_x, anchor_y, str(values[1]), _text_font_size(property_node), float(at_values[2]) if len(at_values) > 2 else 0.0))
    return rects


def _segment_clips_into_rect(segment: Tuple[float, float, float, float], rect: Tuple[float, float, float, float]) -> bool:
    """Return whether a wire segment passes strictly through a rectangle interior."""
    rect_x0, rect_y0, rect_x1, rect_y1 = rect
    start_x, start_y, end_x, end_y = segment
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    p = (-delta_x, delta_x, -delta_y, delta_y)
    q = (start_x - rect_x0, rect_x1 - start_x, start_y - rect_y0, rect_y1 - start_y)
    u1, u2 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if abs(pi) < 1e-12:
            if qi < 0:
                return False
        else:
            ratio = qi / pi
            if pi < 0:
                if ratio > u2:
                    return False
                if ratio > u1:
                    u1 = ratio
            else:
                if ratio < u1:
                    return False
                if ratio < u2:
                    u2 = ratio
    if u2 - u1 < 1e-9:  # A single boundary touch is a legal pin contact, not an intersection.
        return False
    midpoint_x = start_x + (u1 + u2) / 2.0 * delta_x
    midpoint_y = start_y + (u1 + u2) / 2.0 * delta_y
    return rect_x0 < midpoint_x < rect_x1 and rect_y0 < midpoint_y < rect_y1


def _rects_strict_overlap(first: Tuple[float, float, float, float], second: Tuple[float, float, float, float]) -> bool:
    """Return whether two rectangles overlap by more than a boundary tolerance."""
    epsilon = 1e-3
    return first[0] < second[2] - epsilon and second[0] < first[2] - epsilon and first[1] < second[3] - epsilon and second[1] < first[3] - epsilon


def _count_geometry_intersections(schematic: Schematic) -> Tuple[int, int, int]:
    """Count wire-symbol, wire-text, and symbol-symbol geometry intersections."""
    wire_symbol_intersections = 0
    wire_text_intersections = 0
    symbol_symbol_intersections = 0
    bodies = [record for record in schematic.symbols if record.body_rect is not None]
    for segment in schematic.wires:
        for record in bodies:
            if _segment_clips_into_rect(segment, record.body_rect):
                wire_symbol_intersections += 1
        for text_rect in schematic.text_rects:
            if _segment_clips_into_rect(segment, text_rect):
                wire_text_intersections += 1
    for first_index, first in enumerate(bodies):
        for second in bodies[first_index + 1:]:
            if _rects_strict_overlap(first.body_rect, second.body_rect):
                symbol_symbol_intersections += 1
    return wire_symbol_intersections, wire_text_intersections, symbol_symbol_intersections


class SymbolRecord:
    __slots__ = ("reference", "lib_id", "x", "y", "angle", "mirror", "unit", "body_style", "value", "properties", "pin_numbers", "pin_names", "power", "pins", "body_rect", "text_rects")

    def __init__(self) -> None:
        self.reference = ""
        self.lib_id = ""
        self.x = 0.0
        self.y = 0.0
        self.angle = 0.0
        self.mirror = ""
        self.unit = 1
        self.body_style = 1
        self.value = ""
        self.properties: Dict[str, str] = {}
        self.pin_numbers: List[str] = []
        self.pin_names: Dict[str, str] = {}
        self.power = False
        self.pins: Dict[str, Tuple[float, float]] = {}
        self.body_rect: Optional[Tuple[float, float, float, float]] = None
        self.text_rects: List[Tuple[float, float, float, float]] = []


class Schematic:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.version = ""
        self.generator = ""
        self.paper = ""
        self.lib_symbols: Dict[str, SExp] = {}
        self.symbols: List[SymbolRecord] = []
        self.wires: List[Tuple[float, float, float, float]] = []
        self.labels: List[Tuple[float, float, str]] = []
        self.no_connects: List[Tuple[float, float]] = []
        self.texts: List[str] = []
        self.text_rects: List[Tuple[float, float, float, float]] = []
        self.junctions: List[Tuple[float, float]] = []
        self.nets: Dict[str, Set[Tuple[str, str]]] = {}
        self.net_wire_segments: Dict[str, int] = {}
        self.net_wire_length: Dict[str, float] = {}
        self.total_wire_length = 0.0
        self._parse()

    def _parse(self) -> None:
        text = self.path.read_text(encoding="utf-8", errors="replace")
        root = parse_string(text)
        self.version = _first_atom(root.find_child("version"))
        self.generator = _first_atom(root.find_child("generator"))
        self.paper = _first_atom(root.find_child("paper"))
        lib_symbols_node = root.find_child("lib_symbols")
        if lib_symbols_node is not None:
            for symbol_node in lib_symbols_node.find_children("symbol"):
                name = _first_atom(symbol_node)
                if name:
                    self.lib_symbols[name] = symbol_node
        union_find = _UnionFind()
        segments: List[Tuple[float, float, float, float]] = []
        for wire_node in root.find_children("wire"):
            points_node = wire_node.find_child("pts")
            if points_node is None:
                continue
            coordinates: List[Tuple[float, float]] = []
            for xy_node in points_node.find_children("xy"):
                values = _atom_values(xy_node)
                if len(values) >= 2:
                    coordinates.append((float(values[0]), float(values[1])))
            for position in range(len(coordinates) - 1):
                start_x, start_y = coordinates[position]
                end_x, end_y = coordinates[position + 1]
                start_key = _point_key(start_x, start_y)
                end_key = _point_key(end_x, end_y)
                union_find.add(start_key)
                union_find.add(end_key)
                union_find.union(start_key, end_key)
                segment = (start_x, start_y, end_x, end_y)
                segments.append(segment)
                self.wires.append(segment)
        for junction_x, junction_y in self._collect_junction_positions(root):
            self.junctions.append((junction_x, junction_y))
            key = _point_key(junction_x, junction_y)
            union_find.add(key)
            for segment in segments:
                if _point_on_segment(junction_x, junction_y, segment):
                    union_find.union(key, _point_key(segment[0], segment[1]))
                    break
        for first in segments:
            for second in segments:
                if first is second:
                    continue
                if _point_on_segment(first[0], first[1], second):
                    union_find.union(_point_key(first[0], first[1]), _point_key(second[0], second[1]))
                if _point_on_segment(first[2], first[3], second):
                    union_find.union(_point_key(first[2], first[3]), _point_key(second[0], second[1]))
        self.labels = self._collect_labels(root)
        for no_connect_node in root.find_children("no_connect"):
            values = _atom_values(no_connect_node.find_child("at"))
            if len(values) >= 2:
                self.no_connects.append((float(values[0]), float(values[1])))
        net_names: Dict[str, str] = {}
        for label_x, label_y, label_text in self.labels:
            key = self._attach_point(union_find, segments, label_x, label_y)
            net_root = union_find.find(key)
            if label_text != "" and net_root not in net_names:
                net_names[net_root] = label_text
        self.symbols = self._parse_instances(root)
        for record in self.symbols:
            if record.power:
                for pin_number in record.pins:
                    pin_x, pin_y = record.pins[pin_number]
                    key = self._attach_point(union_find, segments, pin_x, pin_y)
                    net_root = union_find.find(key)
                    value = record.value
                    if value != "" and net_root not in net_names:
                        net_names[net_root] = value
        for record in self.symbols:
            record.pin_numbers = list(record.pins.keys())
        for record in self.symbols:
            for pin_number, (pin_x, pin_y) in record.pins.items():
                key = self._attach_point(union_find, segments, pin_x, pin_y)
                net_root = union_find.find(key)
                net_name = net_names.get(net_root, "")
                if net_name == "":
                    net_name = f"__NET_{net_root}"
                self.nets.setdefault(net_name, set()).add((record.reference, pin_number))
        for segment in segments:
            key = _point_key(segment[0], segment[1])
            net_root = union_find.find(key)
            net_name = net_names.get(net_root, f"__NET_{net_root}")
            segment_length = math.hypot(segment[2] - segment[0], segment[3] - segment[1])
            self.net_wire_segments[net_name] = self.net_wire_segments.get(net_name, 0) + 1
            self.net_wire_length[net_name] = self.net_wire_length.get(net_name, 0.0) + segment_length
            self.total_wire_length += segment_length
        for text_node in root.find_children("text"):
            values = _atom_values(text_node)
            if values:
                self.texts.append(str(values[0]))
        for tag in ("text", "label", "global_label", "hierarchical_label"):
            for text_node in root.find_children(tag):
                text_values = [child.value for child in text_node.children if child.is_atom]
                if not text_values:
                    continue
                at_values = _atom_values(text_node.find_child("at"))
                if len(at_values) < 2:
                    continue
                if not _text_is_visible(text_node):
                    continue
                self.text_rects.append(_text_rect(float(at_values[0]), float(at_values[1]), str(text_values[0]), _text_font_size(text_node), float(at_values[2]) if len(at_values) > 2 else 0.0))

    def _collect_junction_positions(self, root: SExp) -> List[Tuple[float, float]]:
        positions: List[Tuple[float, float]] = []
        for junction_node in root.find_children("junction"):
            values = _atom_values(junction_node.find_child("at"))
            if len(values) >= 2:
                positions.append((float(values[0]), float(values[1])))
        return positions

    def _collect_labels(self, root: SExp) -> List[Tuple[float, float, str]]:
        entries: List[Tuple[float, float, str]] = []
        for tag in ("label", "global_label", "hierarchical_label"):
            for label_node in root.find_children(tag):
                text_values = [child.value for child in label_node.children if child.is_atom]
                label_text = str(text_values[0]) if text_values else ""
                at_values = _atom_values(label_node.find_child("at"))
                if len(at_values) >= 2:
                    entries.append((float(at_values[0]), float(at_values[1]), label_text))
        return entries

    def _attach_point(self, union_find: _UnionFind, segments: Sequence[Tuple[float, float, float, float]], x: float, y: float) -> str:
        key = _point_key(x, y)
        union_find.add(key)
        for segment in segments:
            if _point_on_segment(x, y, segment):
                union_find.union(key, _point_key(segment[0], segment[1]))
                break
        return key

    def _parse_instances(self, root: SExp) -> List[SymbolRecord]:
        records: List[SymbolRecord] = []
        for instance_node in root.find_children("symbol"):
            record = SymbolRecord()
            record.lib_id = _first_atom(instance_node.find_child("lib_id"))
            at_values = _atom_values(instance_node.find_child("at"))
            if len(at_values) >= 2:
                record.x = float(at_values[0])
                record.y = float(at_values[1])
            if len(at_values) > 2:
                record.angle = float(at_values[2])
            unit_values = _atom_values(instance_node.find_child("unit"))
            if unit_values:
                record.unit = int(unit_values[0])
            style_values = _atom_values(instance_node.find_child("body_style"))
            if style_values:
                record.body_style = int(style_values[0])
            mirror_values = _atom_values(instance_node.find_child("mirror"))
            if mirror_values:
                record.mirror = str(mirror_values[0])
            record.properties = self._collect_properties(instance_node)
            record.reference = record.properties.get("Reference", "")
            record.value = record.properties.get("Value", "")
            symbol_node = self.lib_symbols.get(record.lib_id)
            if symbol_node is None:
                continue
            record.power = symbol_node.find_child("power") is not None
            symbol_name = record.lib_id.split(":", 1)[1] if ":" in record.lib_id else record.lib_id
            pin_geometry = self._extract_symbol_pins(symbol_node, record.unit, record.body_style, symbol_name)
            for pin_number, (local_x, local_y) in pin_geometry.items():
                absolute_x, absolute_y = _transform_point(local_x, local_y, record.x, record.y, record.angle, record.mirror)
                record.pins[pin_number] = (absolute_x, absolute_y)
            record.pin_names = self._collect_symbol_pin_names(symbol_node)
            local_bounds = _symbol_body_bounds(symbol_node)  # Measure the drawn body in local coordinates.
            if local_bounds is not None:  # Transform the body corners into schematic space.
                corners = [(local_bounds[0], local_bounds[1]), (local_bounds[2], local_bounds[1]), (local_bounds[2], local_bounds[3]), (local_bounds[0], local_bounds[3])]
                world_points = [_transform_point(corner_x, corner_y, record.x, record.y, record.angle, record.mirror) for corner_x, corner_y in corners]
                record.body_rect = (min(point[0] for point in world_points), min(point[1] for point in world_points), max(point[0] for point in world_points), max(point[1] for point in world_points))
            record.text_rects = _collect_instance_text_rects(instance_node, record)  # Collect visible field boxes.
            records.append(record)
        return records

    @staticmethod
    def _collect_symbol_pin_names(symbol_node: SExp) -> Dict[str, str]:
        """Collect every pin number-to-name pair defined by a library symbol."""
        pin_names: Dict[str, str] = {}
        for sub_symbol in symbol_node.find_children("symbol"):
            for pin_node in sub_symbol.find_children("pin"):
                number_node = pin_node.find_child("number")
                name_node = pin_node.find_child("name")
                if number_node is None or name_node is None:
                    continue
                number_values = _atom_values(number_node)
                name_values = _atom_values(name_node)
                if number_values:
                    pin_names.setdefault(str(number_values[0]), str(name_values[0]) if name_values else "")
        return pin_names

    @staticmethod
    def _collect_properties(node: SExp) -> Dict[str, str]:
        properties: Dict[str, str] = {}
        for property_node in node.find_children("property"):
            values = _atom_values(property_node)
            if len(values) >= 2:
                properties[str(values[0])] = str(values[1])
        return properties

    def _extract_symbol_pins(self, symbol_node: SExp, unit: int, body_style: int, symbol_name: str) -> Dict[str, Tuple[float, float]]:
        unit_prefix = f"{symbol_name}_{unit}_"
        preferred_name = f"{symbol_name}_{unit}_{body_style}"
        fallback_name = f"{symbol_name}_{unit}_1"
        sub_symbols = symbol_node.find_children("symbol")
        candidates: List[SExp] = []
        seen: Set[int] = set()

        def queue_candidate(sub_symbol: SExp) -> None:
            if id(sub_symbol) in seen:
                return
            seen.add(id(sub_symbol))
            candidates.append(sub_symbol)

        for sub_symbol in sub_symbols:
            name = _first_atom(sub_symbol)
            if name in (preferred_name, fallback_name):
                queue_candidate(sub_symbol)
        for sub_symbol in sub_symbols:
            name = _first_atom(sub_symbol)
            if name and name.startswith(unit_prefix):
                queue_candidate(sub_symbol)
        for sub_symbol in sub_symbols:
            name = _first_atom(sub_symbol)
            if name and name.startswith(f"{symbol_name}_0_"):
                queue_candidate(sub_symbol)
        for sub_symbol in sub_symbols:
            name = _first_atom(sub_symbol)
            if name and name.endswith(f"_{unit}_{body_style}"):
                queue_candidate(sub_symbol)
        for sub_symbol in sub_symbols:
            name = _first_atom(sub_symbol)
            if name and name.endswith("_0_1"):
                queue_candidate(sub_symbol)
        for candidate in candidates:
            pins = self._collect_pin_geometry(candidate)
            if not pins:
                continue
            if unit != 0:
                for shared_sub_symbol in sub_symbols:
                    shared_name = _first_atom(shared_sub_symbol)
                    if shared_name is None:
                        continue
                    if shared_name.startswith(f"{symbol_name}_0_") or shared_name.endswith("_0_1"):
                        for number, pin in self._collect_pin_geometry(shared_sub_symbol).items():
                            pins.setdefault(number, pin)
            return pins
        return {}

    @staticmethod
    def _collect_pin_geometry(sub_symbol: SExp) -> Dict[str, Tuple[float, float]]:
        pins: Dict[str, Tuple[float, float]] = {}
        for pin_node in sub_symbol.find_children("pin"):
            at_values = _atom_values(pin_node.find_child("at"))
            number_values = _atom_values(pin_node.find_child("number"))
            if len(at_values) < 2 or not number_values:
                continue
            pins[str(number_values[0])] = (float(at_values[0]), float(at_values[1]))
        return pins


def _normalize_lib_id(lib_id: str) -> str:
    nickname, separator, name = lib_id.rpartition(":")
    if nickname in ("Device", "power", "Simulation_SPICE"):
        return name
    return name if separator else lib_id


def _signature_lib_id(lib_id: str) -> str:
    return _normalize_lib_id(lib_id)


_OFFICIAL_SYMBOL_CACHE: Dict[str, Set[str]] = {}
_OFFICIAL_SYMBOL_LOCK = threading.Lock()


def _official_symbol_names(kicad_path: str) -> Set[str]:
    """Return the set of 'nickname:symbol' lib_ids present in the official KiCad libraries.

    Symbols resolved through the LTspice .asy fallback converter are not part of
    any official library, so their lib_ids are absent from the returned set.
    An empty set also means the official symbol directory is unavailable.
    """
    if not kicad_path:
        return set()
    with _OFFICIAL_SYMBOL_LOCK:
        cached = _OFFICIAL_SYMBOL_CACHE.get(kicad_path)
        if cached is not None:
            return cached
    names: Set[str] = set()
    symbols_directory = Path(kicad_path) / "symbols"
    if symbols_directory.is_dir():
        for library_path in sorted(symbols_directory.glob("*.kicad_sym")):
            try:
                root = parse_string(library_path.read_text(encoding="utf-8", errors="replace"))
            except Exception:  # noqa: BLE001 - skip unreadable or malformed official libraries.
                continue
            nickname = library_path.stem
            for symbol_node in root.find_children("symbol"):
                symbol_name = _first_atom(symbol_node)
                if symbol_name:
                    names.add(f"{nickname}:{symbol_name}")
    with _OFFICIAL_SYMBOL_LOCK:
        _OFFICIAL_SYMBOL_CACHE[kicad_path] = names
    return names


def _report_official_library_usage(
    symbols_a: Dict[str, SymbolRecord],
    symbols_b: Dict[str, SymbolRecord],
    common: List[str],
    kicad_path: str,
) -> Tuple[List[str], List[str]]:
    """Flag matched symbols where ground truth uses an official KiCad library symbol
    but the generated schematic resolved the same reference via a non-official
    (fallback-converted) symbol instead."""
    lines: List[str] = []
    differences: List[str] = []
    if not kicad_path:
        return lines, differences
    official_names = _official_symbol_names(kicad_path)
    if not official_names:
        return lines, differences
    fallback_references: List[str] = []
    for reference in common:
        record_a = symbols_a[reference]
        record_b = symbols_b[reference]
        if record_a.lib_id in official_names and record_b.lib_id not in official_names:
            fallback_references.append(reference)
    if fallback_references:
        lines.append(
            f"  Official library usage: {len(common) - len(fallback_references)}/{len(common)} generated symbols from official KiCad libraries; "
            f"fallback-converted: {', '.join(sorted(fallback_references))}"
        )
        for reference in sorted(fallback_references):
            record_a = symbols_a[reference]
            record_b = symbols_b[reference]
            differences.append(
                f"symbol '{reference}' uses official KiCad symbol '{record_a.lib_id}' in A but non-official '{record_b.lib_id}' in B (fallback-converted symbol)"
            )
    else:
        lines.append(f"  Official library usage: {len(common)}/{len(common)} generated symbols from official KiCad libraries")
    return lines, differences


def _best_rigid_transform(gt_positions: List[Tuple[float, float]], gen_positions: List[Tuple[float, float]]) -> Tuple[float, float, float]:
    n = len(gt_positions)
    if n == 0:
        return 0.0, 1.0, 0.0
    gt_centroid_x = sum(p[0] for p in gt_positions) / n
    gt_centroid_y = sum(p[1] for p in gt_positions) / n
    gen_centroid_x = sum(p[0] for p in gen_positions) / n
    gen_centroid_y = sum(p[1] for p in gen_positions) / n
    best_score = float("inf")
    best_angle = 0.0
    best_scale = 1.0
    best_mirror = 1.0
    for mirror_x in (1.0, -1.0):
        for angle in (0.0, 90.0, 180.0, 270.0):
            radians = math.radians(angle)
            cosine = math.cos(radians)
            sine = math.sin(radians)
            numerator = 0.0
            denominator = 0.0
            for (gx, gy), (ox, oy) in zip(gt_positions, gen_positions):
                dx = ox - gen_centroid_x
                dy = (oy - gen_centroid_y) * mirror_x
                rx = dx * cosine - dy * sine
                ry = dx * sine + dy * cosine
                target_x = gx - gt_centroid_x
                target_y = gy - gt_centroid_y
                numerator += rx * target_x + ry * target_y
                denominator += rx * rx + ry * ry
            if denominator > 0 and numerator > 0:
                scale = numerator / denominator
            elif denominator > 0:
                target_norm = sum((gx - gt_centroid_x) ** 2 + (gy - gt_centroid_y) ** 2 for gx, gy in gt_positions)
                scale = math.sqrt(target_norm / denominator) if target_norm > 0 else 1.0
            else:
                scale = 1.0
            error = 0.0
            for (gx, gy), (ox, oy) in zip(gt_positions, gen_positions):
                dx = ox - gen_centroid_x
                dy = (oy - gen_centroid_y) * mirror_x
                rx = dx * cosine - dy * sine
                ry = dx * sine + dy * cosine
                error += (gt_centroid_x + scale * rx - gx) ** 2 + (gt_centroid_y + scale * ry - gy) ** 2
            if error < best_score:
                best_score = error
                best_angle = angle
                best_scale = scale
                best_mirror = mirror_x
    return best_angle, best_scale, best_mirror


def _transform_position(x: float, y: float, centroid: Tuple[float, float], angle: float, scale: float, mirror: float) -> Tuple[float, float]:
    radians = math.radians(angle)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    dx = x - centroid[0]
    dy = (y - centroid[1]) * mirror
    rx = dx * cosine - dy * sine
    ry = dx * sine + dy * cosine
    return centroid[0] + scale * rx, centroid[1] + scale * ry


_PWR_FLAG_LIB = "power:PWR_FLAG"

_SIM_PROPERTY_KEYS = ("Sim.Device", "Sim.Name", "Sim.Library", "Sim.Params", "Sim.Pins", "Sim.Type")  # Simulation metadata that must survive conversion round trips.


def _is_graphical_marker(record: SymbolRecord) -> bool:
    return record.lib_id == _PWR_FLAG_LIB or record.lib_id.startswith("power:")


def _electrical_equivalent(first: Schematic, second: Schematic, kicad_path: str) -> Tuple[bool, str]:
    import tempfile

    from electronics_design import kicad_sch_to_ltspice_netlist
    from electronics_design import ltspice_netlist_structure_cmp

    settings = {"kicad_path": kicad_path}
    try:
        with tempfile.TemporaryDirectory() as temporary_directory:
            net_a = str(Path(temporary_directory) / "a.net")
            net_b = str(Path(temporary_directory) / "b.net")
            ok_a, message_a, _ = kicad_sch_to_ltspice_netlist(str(first.path), net_a, settings)
            if not ok_a:
                return False, f"file A netlist conversion failed: {message_a}"
            ok_b, message_b, _ = kicad_sch_to_ltspice_netlist(str(second.path), net_b, settings)
            if not ok_b:
                return False, f"file B netlist conversion failed: {message_b}"
            equal = ltspice_netlist_structure_cmp(net_a, net_b)
            return bool(equal), ""
    except ImportError as exc:  # The optional netlist back-end is unavailable.
        return False, f"netlist back-end unavailable: {exc}"


def _angular_difference(first: float, second: float) -> float:
    difference = (first - second) % 360.0
    return min(difference, 360.0 - difference)


def _connection_label(members: Set[Tuple[str, str]]) -> str:
    return "{" + ", ".join(f"{reference}:{pin}" for reference, pin in sorted(members)) + "}"


def _report_wire_length_scores(first: Schematic, second: Schematic, relative_tolerance: float) -> Tuple[float, List[str]]:
    lines: List[str] = []
    second_by_members: Dict[frozenset, List[str]] = {}
    for net_name, members in second.nets.items():
        second_by_members.setdefault(frozenset(members), []).append(net_name)
    used_second: Set[str] = set()
    pairs: List[Tuple[str, float, float, Set[Tuple[str, str]]]] = []
    unmatched_first: List[Tuple[str, Set[Tuple[str, str]]]] = []
    for net_name, members in first.nets.items():
        key = frozenset(members)
        candidates = [candidate for candidate in second_by_members.get(key, []) if candidate not in used_second]
        if candidates:
            second_net = candidates[0]
            used_second.add(second_net)
            pairs.append((net_name, first.net_wire_length.get(net_name, 0.0), second.net_wire_length.get(second_net, 0.0), members))
        else:
            unmatched_first.append((net_name, members))
    matched_second = set(second.nets) - used_second
    within = 0
    graded = 0.0
    for _net_name, first_length, second_length, members in pairs:
        larger = max(first_length, second_length)
        relative_difference = abs(first_length - second_length) / larger if larger > 0 else 0.0
        if relative_difference <= relative_tolerance:
            within += 1
        graded += max(0.0, 1.0 - relative_difference / relative_tolerance)
        lines.append(
            f"    wire length for {_connection_label(members)}: A={first_length:7.2f}mm B={second_length:7.2f}mm "
            f"rel-diff={relative_difference*100:5.1f}%"
        )
    total = len(pairs)
    score = 100.0 * graded / total if total else 100.0
    lines.append(f"  Score wire length per connection: {score:.1f}% ({within}/{total} connections within {relative_tolerance*100:.0f}% relative difference, graded)")
    if unmatched_first or matched_second:
        lines.append(f"  Connections without an exact member match: {len(unmatched_first)} only-A, {len(matched_second)} only-B")
    return score, lines


def _count_unconnected_wires(schematic: Schematic) -> Tuple[int, int]:  # Count wire segments with a free endpoint plus the total free endpoints.
    connection_points: List[Tuple[float, float]] = []  # Collect symbol pins, NC markers, and net labels.
    for record in schematic.symbols:  # Walk every symbol instance.
        for pin_x, pin_y in record.pins.values():  # Walk the absolute pin positions.
            connection_points.append((pin_x, pin_y))  # Register the pin position.
    for no_x, no_y in schematic.no_connects:  # Walk the no-connect markers.
        connection_points.append((no_x, no_y))  # Register the marker position.
    for label_x, label_y, _label_text in schematic.labels:  # Walk the net labels.
        connection_points.append((label_x, label_y))  # Register the label position.
    wires = schematic.wires  # Read the wire segments.
    unconnected = 0  # Count wires with at least one free endpoint.
    free_endpoints = 0  # Count the free endpoints themselves.
    for index, segment in enumerate(wires):  # Walk every wire segment.
        endpoints = ((segment[0], segment[1]), (segment[2], segment[3]))  # Read the two endpoints.
        free_ends = 0  # Count the free endpoints of this wire.
        for end_x, end_y in endpoints:  # Walk the endpoints.
            connected = False  # Assume the endpoint is free.
            for other_index, other in enumerate(wires):  # Walk the other wire segments.
                if other_index == index:  # Skip the wire itself.
                    continue  # Move to the next segment.
                if _point_on_segment(end_x, end_y, other):  # The endpoint touches another wire.
                    connected = True  # The endpoint is connected.
                    break  # Stop searching for this endpoint.
            if not connected:  # No wire contact at this endpoint.
                for point_x, point_y in connection_points:  # Walk the symbol/NC/label positions.
                    if abs(end_x - point_x) <= _POINT_TOLERANCE and abs(end_y - point_y) <= _POINT_TOLERANCE:  # The endpoint coincides with a connection point.
                        connected = True  # The endpoint is connected.
                        break  # Stop searching for this endpoint.
            if not connected:  # The endpoint contacts nothing.
                free_ends += 1  # Count the free endpoint.
        if free_ends:  # At least one endpoint of this wire is free.
            unconnected += 1  # Count the wire as unconnected.
        free_endpoints += free_ends  # Accumulate the free endpoints.
    return unconnected, free_endpoints  # Return the wire and endpoint counts.


def _report_symbol_layout(schematic_a: Schematic, schematic_b: Schematic, matched: List[Tuple[SymbolRecord, SymbolRecord]]) -> Tuple[bool, List[str]]:
    lines: List[str] = []
    problems: List[str] = []
    if not matched:
        lines.append("  No matched symbols for relative-layout comparison.")
        return True, lines
    count = len(matched)
    gt_positions = [(record_a.x, record_a.y) for record_a, _ in matched]
    gen_positions = [(record_b.x, record_b.y) for _, record_b in matched]
    angle, scale, mirror = _best_rigid_transform(gt_positions, gen_positions)
    gt_centroid = (sum(p[0] for p in gt_positions) / count, sum(p[1] for p in gt_positions) / count)
    gen_centroid = (sum(p[0] for p in gen_positions) / count, sum(p[1] for p in gen_positions) / count)
    gt_x_span = max(record_a.x for record_a, _ in matched) - min(record_a.x for record_a, _ in matched)
    gt_y_span = max(record_a.y for record_a, _ in matched) - min(record_a.y for record_a, _ in matched)
    characteristic = max(1.0, gt_x_span, gt_y_span)
    position_tolerance = 0.05 * characteristic
    total = 0.0
    squared = 0.0
    worst = 0.0
    worst_pair = ""
    position_within = 0
    for record_a, record_b in matched:
        px, py = _transform_position(record_b.x, record_b.y, gen_centroid, angle, scale, mirror)
        distance = math.hypot(px - record_a.x, py - record_a.y)
        total += distance
        squared += distance * distance
        if distance <= position_tolerance:
            position_within += 1
        if distance > worst:
            worst = distance
            worst_pair = record_a.reference
    mean_error = total / count
    rms_error = math.sqrt(squared / count)

    distance_pairs = 0
    distance_total = 0.0
    distance_worst = 0.0
    distance_within = 0
    for first_index in range(count):
        for second_index in range(first_index + 1, count):
            gt_distance = math.hypot(
                gt_positions[first_index][0] - gt_positions[second_index][0],
                gt_positions[first_index][1] - gt_positions[second_index][1],
            )
            gen_distance = math.hypot(
                gen_positions[first_index][0] - gen_positions[second_index][0],
                gen_positions[first_index][1] - gen_positions[second_index][1],
            )
            distance_pairs += 1
            if gt_distance <= 1e-6:
                residual = gen_distance
            else:
                residual = abs(gen_distance / scale - gt_distance) if scale > 0 else gen_distance
            distance_total += residual
            if residual > distance_worst:
                distance_worst = residual
            if residual <= position_tolerance:
                distance_within += 1
    mean_pairwise_error = distance_total / distance_pairs if distance_pairs else 0.0

    orientation_within = 0
    for record_a, record_b in matched:
        expected_b_angle = record_b.angle
        if mirror < 0:
            expected_b_angle = -expected_b_angle
        expected_b_angle = (expected_b_angle + angle) % 360.0
        if _angular_difference(record_a.angle, expected_b_angle) <= 0.5:
            orientation_within += 1
    orientation_ratio = 100.0 * orientation_within / count

    def _relative(value: float) -> str:  # Format one measurement against the GT characteristic span.
        return f"{value:.3f}mm ({100.0 * value / characteristic:.1f}% of {characteristic:.2f}mm GT span)"

    lines.append(f"  Best rigid transform: rotation={angle:g}deg mirror={'-' if mirror < 0 else '+'} scale={scale:.4f}")
    lines.append(f"  Relative position: mean {_relative(mean_error)}, rms {_relative(rms_error)}, worst {_relative(worst)} (at '{worst_pair}')")
    lines.append(f"  Position within tolerance: {position_within}/{count} symbols (tolerance {position_tolerance:.2f}mm = 5% of GT span)")
    lines.append(f"  Pairwise distance error: mean {_relative(mean_pairwise_error)}, worst {_relative(distance_worst)}, {distance_within}/{distance_pairs} pairs within tolerance")
    lines.append(f"  Orientation match: {orientation_within}/{count} symbols ({orientation_ratio:.1f}%, global rotation {angle:g}deg accounted)")
    lines.append(f"  Combined relative layout: mean residual {_relative(mean_error)}, orientation {orientation_ratio:.1f}%")
    lines.append(f"  Relative layout match: {'YES' if worst <= position_tolerance else 'NO'} (worst tolerance {position_tolerance:.3f}mm)")
    if worst > position_tolerance:
        problems.append(f"relative symbol layout mismatch (worst residual {worst:.3f}mm)")
    return not problems, lines


def _orientation_equivalent(first: SymbolRecord, second: SymbolRecord) -> bool:
    return abs(first.angle - second.angle) < 1e-6 and first.mirror == second.mirror


def _compare_schematic_pair(first: Schematic, second: Schematic, tolerance: float, verbose: bool, kicad_path: str, wire_length_tolerance: float) -> Tuple[bool, List[str], List[str]]:
    lines: List[str] = []
    hard_problems: List[str] = []
    differences: List[str] = []
    if first.version != second.version:
        differences.append(f"version differs ({first.version} vs {second.version})")
    if first.generator != second.generator:
        differences.append(f"generator differs ({first.generator} vs {second.generator})")
    if first.paper != second.paper:
        hard_problems.append(f"paper differs ({first.paper} vs {second.paper})")
    lines.append(f"  Header: version={first.version} vs {second.version} generator={first.generator} vs {second.generator} paper={first.paper} vs {second.paper}")

    symbols_a = {record.reference: record for record in first.symbols}
    symbols_b = {record.reference: record for record in second.symbols}
    refs_a = set(symbols_a)
    refs_b = set(symbols_b)
    common = sorted(refs_a & refs_b)
    only_a = sorted(refs_a - refs_b)
    only_b = sorted(refs_b - refs_a)
    lines.append(f"  Symbols: {len(refs_a)} in A, {len(refs_b)} in B, {len(common)} matched, {len(only_a)} only-A, {len(only_b)} only-B")
    for reference in only_a:
        record = symbols_a[reference]
        marker = " (graphical marker)" if _is_graphical_marker(record) else ""
        lines.append(f"    only in A: {reference} ({record.lib_id}){marker}")
    for reference in only_b:
        record = symbols_b[reference]
        marker = " (graphical marker)" if _is_graphical_marker(record) else ""
        lines.append(f"    only in B: {reference} ({record.lib_id}){marker}")

    matched: List[Tuple[SymbolRecord, SymbolRecord]] = []
    lib_mismatch = 0
    value_mismatch = 0
    orientation_mismatch = 0
    sim_property_mismatch = 0
    pin_set_mismatch = 0
    pin_name_mismatch = 0
    for reference in common:
        record_a = symbols_a[reference]
        record_b = symbols_b[reference]
        matched.append((record_a, record_b))
        if _signature_lib_id(record_a.lib_id) != _signature_lib_id(record_b.lib_id):
            lib_mismatch += 1
            lines.append(f"    lib_id differs for {reference}: {record_a.lib_id} vs {record_b.lib_id}")
        if record_a.value != record_b.value:
            value_mismatch += 1
            lines.append(f"    value differs for {reference}: '{record_a.value}' vs '{record_b.value}'")
        if not _orientation_equivalent(record_a, record_b):
            orientation_mismatch += 1
            lines.append(f"    orientation differs for {reference}: angle={record_a.angle:g}/{record_a.mirror} vs {record_b.angle:g}/{record_b.mirror}")
        for sim_key in _SIM_PROPERTY_KEYS:
            value_a = record_a.properties.get(sim_key, "")
            value_b = record_b.properties.get(sim_key, "")
            if value_a != value_b:
                sim_property_mismatch += 1
                lines.append(f"    {sim_key} differs for {reference}: '{value_a}' vs '{value_b}'")
        pins_a = set(record_a.pin_numbers)
        pins_b = set(record_b.pin_numbers)
        if pins_a != pins_b:
            pin_set_mismatch += 1
            lines.append(f"    pin numbers differ for {reference}: {sorted(pins_a)} vs {sorted(pins_b)}")
        names_a = sorted((number, record_a.pin_names.get(number, "")) for number in pins_a)
        names_b = sorted((number, record_b.pin_names.get(number, "")) for number in pins_b)
        if names_a != names_b:
            pin_name_mismatch += 1
            lines.append(f"    pin names differ for {reference}: {names_a} vs {names_b}")
    lines.append(f"  Matched symbol properties: lib_id {len(common) - lib_mismatch}/{len(common)} OK, value {len(common) - value_mismatch}/{len(common)} OK, orientation {len(common) - orientation_mismatch}/{len(common)} OK")
    lines.append(f"  Matched symbol simulation metadata: Sim.* {len(common) * len(_SIM_PROPERTY_KEYS) - sim_property_mismatch}/{len(common) * len(_SIM_PROPERTY_KEYS)} OK, pins {len(common) - pin_set_mismatch}/{len(common)} OK, pin names {len(common) - pin_name_mismatch}/{len(common)} OK")
    if sim_property_mismatch:
        differences.append(f"simulation metadata differs for {sim_property_mismatch} matched symbol(s)")
    if pin_set_mismatch:
        differences.append(f"pin number sets differ for {pin_set_mismatch} matched symbol(s)")
    if pin_name_mismatch:
        differences.append(f"pin names differ for {pin_name_mismatch} matched symbol(s)")

    official_lines, official_differences = _report_official_library_usage(symbols_a, symbols_b, common, kicad_path)
    lines.extend(official_lines)
    differences.extend(official_differences)

    layout_ok, layout_lines = _report_symbol_layout(first, second, matched)
    lines.extend(layout_lines)
    if not layout_ok:
        differences.append("relative symbol layout differs beyond tolerance")

    electrical_ok = True
    if kicad_path:
        electrical_ok, electrical_note = _electrical_equivalent(first, second, kicad_path)
        if electrical_ok:
            lines.append("  Electrical equivalence (netlist structure): MATCH")
        else:
            lines.append(f"  Electrical equivalence (netlist structure): DIFF - {electrical_note}")
    else:
        lines.append("  Electrical equivalence: skipped (pass --kicad-path to enable)")

    nets_a = {net: members for net, members in first.nets.items()}
    nets_b = {net: members for net, members in second.nets.items()}
    members_a = set()
    members_b = set()
    for members in nets_a.values():
        members_a.update(members)
    for members in nets_b.values():
        members_b.update(members)
    missing_members = sorted(members_a - members_b)
    extra_members = sorted(members_b - members_a)
    if missing_members:
        lines.append(f"  Connectivity members only in A: {missing_members}")
    if extra_members:
        lines.append(f"  Connectivity members only in B: {extra_members}")
    lines.append(f"  Connectivity: {len(nets_a)} nets in A, {len(nets_b)} nets in B, members {len(members_a)}/{len(members_b)}")

    electrical_symbol_problem = False
    if not electrical_ok:
        for reference in only_a:
            if not _is_graphical_marker(symbols_a[reference]):
                hard_problems.append(f"symbol '{reference}' only in file A")
                electrical_symbol_problem = True
        for reference in only_b:
            if not _is_graphical_marker(symbols_b[reference]):
                hard_problems.append(f"symbol '{reference}' only in file B")
                electrical_symbol_problem = True
        if not electrical_symbol_problem and not electrical_ok:
            hard_problems.append("electrical equivalence check failed")
        if missing_members:
            hard_problems.append("connectivity members missing in B")
        if extra_members:
            hard_problems.append("connectivity members extra in B")
        for reference in common:
            record_a = symbols_a[reference]
            record_b = symbols_b[reference]
            if _signature_lib_id(record_a.lib_id) != _signature_lib_id(record_b.lib_id):
                hard_problems.append(f"symbol '{reference}' lib_id differs ({record_a.lib_id} vs {record_b.lib_id})")
    else:
        for reference in only_a:
            if not _is_graphical_marker(symbols_a[reference]):
                differences.append(f"symbol '{reference}' present only in A (electrically matched by role)")
        for reference in only_b:
            if not _is_graphical_marker(symbols_b[reference]):
                differences.append(f"symbol '{reference}' present only in B (electrically matched by role)")

    wire_count_a = len(first.wires)
    wire_count_b = len(second.wires)
    lines.append(f"  Wires: {wire_count_a} segments/{first.total_wire_length:.2f}mm in A, {wire_count_b} segments/{second.total_wire_length:.2f}mm in B")
    if abs(wire_count_a - wire_count_b) > tolerance:
        differences.append(f"wire segment count differs ({wire_count_a} vs {wire_count_b})")
    intersections_a = _count_geometry_intersections(first)
    intersections_b = _count_geometry_intersections(second)
    lines.append(
        f"  Geometry intersections: wires x symbols {intersections_a[0]} in A / {intersections_b[0]} in B; "
        f"wires x text {intersections_a[1]} in A / {intersections_b[1]} in B; "
        f"symbols x symbols {intersections_a[2]} in A / {intersections_b[2]} in B"
    )
    if intersections_b[0] > intersections_a[0]:
        differences.append(f"wire-symbol intersections exceed ground truth ({intersections_b[0]} vs {intersections_a[0]})")
    if intersections_b[1] > intersections_a[1]:
        differences.append(f"wire-text intersections exceed ground truth ({intersections_b[1]} vs {intersections_a[1]})")
    if intersections_b[2] > intersections_a[2]:
        differences.append(f"symbol-symbol intersections exceed ground truth ({intersections_b[2]} vs {intersections_a[2]})")
    unconnected_a, free_ends_a = _count_unconnected_wires(first)
    unconnected_b, free_ends_b = _count_unconnected_wires(second)
    lines.append(f"  Unconnected wires: {unconnected_a} in A, {unconnected_b} in B ({free_ends_a}/{free_ends_b} free endpoints that contact no wire, symbol pin, NC marker, or net label)")
    if unconnected_a != unconnected_b:
        differences.append(f"unconnected wire count differs ({unconnected_a} vs {unconnected_b})")
    label_count_a = len(first.labels)
    label_count_b = len(second.labels)
    text_count_a = len(first.texts)
    text_count_b = len(second.texts)
    lines.append(f"  Labels: {label_count_a} vs {label_count_b}; texts: {text_count_a} vs {text_count_b}")
    if label_count_a != label_count_b:
        differences.append(f"label count differs ({label_count_a} vs {label_count_b})")
    if text_count_a != text_count_b:
        differences.append(f"text count differs ({text_count_a} vs {text_count_b})")
    net_wire_mismatch = False
    for net in sorted(set(nets_a) | set(nets_b)):
        count_a = first.net_wire_segments.get(net, 0)
        count_b = second.net_wire_segments.get(net, 0)
        if count_a != count_b:
            net_wire_mismatch = True
            lines.append(f"    wire segments for net '{net}': {count_a} vs {count_b}")
    if net_wire_mismatch:
        differences.append("per-net wire segment counts differ")

    wire_length_score, wire_length_lines = _report_wire_length_scores(first, second, wire_length_tolerance)
    lines.extend(wire_length_lines)
    if wire_length_score < 50.0:
        differences.append(f"per-connection wire length score {wire_length_score:.1f}%")

    if verbose:
        lines.append("  Net memberships:")
        for net in sorted(set(nets_a) | set(nets_b)):
            members_a = sorted(nets_a.get(net, set()))
            members_b = sorted(nets_b.get(net, set()))
            status = "OK" if members_a == members_b else "DIFF"
            lines.append(f"    [{status}] {net}: A={members_a} B={members_b}")
        lines.append("  Library symbols embedded:")
        libs_a = sorted(first.lib_symbols)
        libs_b = sorted(second.lib_symbols)
        if libs_a == libs_b:
            lines.append(f"    OK ({len(libs_a)} identical)")
        else:
            lines.append(f"    A only: {sorted(set(libs_a) - set(libs_b))}")
            lines.append(f"    B only: {sorted(set(libs_b) - set(libs_a))}")
            differences.append("embedded lib_symbols sets differ")

    if hard_problems:
        lines.append(f"  Result: ELECTRICAL/STRUCTURAL ERROR ({len(hard_problems)} issue(s))")
        lines.append(f"    hard: {hard_problems}")
    elif differences:
        lines.append(f"  Result: ELECTRICALLY EQUIVALENT, {len(differences)} representation/layout difference(s)")
        lines.append(f"    differences: {differences}")
    else:
        lines.append("  Result: EXACT MATCH")
    return not hard_problems, lines, differences


def _compare_files(first_path: Path, second_path: Path, tolerance: float, verbose: bool, kicad_path: str, wire_length_tolerance: float) -> Tuple[bool, List[str]]:
    lines: List[str] = []
    lines.append(f"Comparing: {first_path.name}")
    lines.append(f"  A: {first_path}")
    lines.append(f"  B: {second_path}")
    try:
        first = Schematic(first_path)
    except Exception as exc:  # noqa: BLE001 - report any parse failure directly.
        lines.append(f"  ERROR parsing file A: {exc}")
        return False, lines
    try:
        second = Schematic(second_path)
    except Exception as exc:  # noqa: BLE001 - report any parse failure directly.
        lines.append(f"  ERROR parsing file B: {exc}")
        return False, lines
    ok, detail, _differences = _compare_schematic_pair(first, second, tolerance, verbose, kicad_path, wire_length_tolerance)
    lines.extend(detail)
    return ok, lines


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare two KiCad schematic files for structural, connectivity, and relative-layout differences.")
    parser.add_argument("first", help="First .kicad_sch file or directory.")
    parser.add_argument("second", help="Second .kicad_sch file or directory.")
    parser.add_argument("--tolerance", type=float, default=1.0, help="Tolerance for wire-count differences. Default: 1.0.")
    parser.add_argument("--verbose", action="store_true", help="Print per-net and per-library detail.")
    parser.add_argument("--kicad-path", default="/usr/share/kicad/", help="Root of the KiCad symbol libraries for the electrical equivalence check. Empty disables it.")
    parser.add_argument("--wire-length-tolerance", type=float, default=0.25, help="Maximum relative wire-length difference per connection scored as a match. Default: 0.25 (25%%).")
    parser.add_argument(
        "--workers",
        type=int,
        default=os.cpu_count() or 1,
        help="Number of simultaneous directory comparisons. Default: one per CPU core.",
    )
    parser.add_argument(
        "--pair-timeout",
        type=float,
        default=600.0,
        help="Seconds allowed for one comparison pair before it is reported as timed out. Default: 600.",
    )
    return parser


def main() -> int:
    try:  # Stream live progress even when stdout is redirected to a file.
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):  # Older interpreters may not support reconfigure.
        pass
    parser = _build_argument_parser()
    arguments = parser.parse_args()
    first_path = Path(arguments.first)
    second_path = Path(arguments.second)
    kicad_path = arguments.kicad_path
    if kicad_path:
        kicad_path = str(Path(kicad_path).expanduser())
    if first_path.is_dir() and second_path.is_dir():
        names_a = {path.stem: path for path in sorted(first_path.glob("*.kicad_sch"))}
        names_b = {path.stem: path for path in sorted(second_path.glob("*.kicad_sch"))}
        names = sorted(set(names_a) | set(names_b))
        if not names:
            print("No .kicad_sch files found in either directory.", file=sys.stderr)
            return 1
        missing = sorted(name for name in names if name not in names_a or name not in names_b)
        pairs = [(name, names_a[name], names_b[name]) for name in names if name not in missing]
        workers = max(1, arguments.workers)
        print(f"Comparing {len(names)} schematics with {workers} worker(s)...")
        failures = 0
        for name in missing:
            side = "A" if name not in names_a else "B"
            print(f"  MISSING in file {side} directory: {name}")
            failures += 1
        if workers > 1 and len(pairs) > 1:
            executor = concurrent.futures.ProcessPoolExecutor(max_workers=workers)
            try:
                future_to_name = {
                    executor.submit(
                        _compare_files,
                        first_path,
                        second_path,
                        arguments.tolerance,
                        arguments.verbose,
                        kicad_path,
                        arguments.wire_length_tolerance,
                    ): name
                    for name, first_path, second_path in pairs
                }
                pending = set(future_to_name)
                deadlines = {future: time.monotonic() + arguments.pair_timeout for future in pending}
                while pending:
                    remaining = max(0.0, min(deadlines[future] - time.monotonic() for future in pending))
                    done, pending = concurrent.futures.wait(pending, timeout=remaining, return_when=concurrent.futures.FIRST_COMPLETED)
                    for future in done:
                        name = future_to_name[future]
                        try:
                            ok, lines = future.result()
                        except Exception as exc:  # noqa: BLE001 - report any worker failure directly.
                            ok, lines = False, [f"  ERROR comparing {name}: {exc}"]
                        print(f"== {name} ==")
                        print("\n".join(lines))
                        if not ok:
                            failures += 1
                    expired = [future for future in pending if time.monotonic() >= deadlines[future]]
                    for future in expired:
                        name = future_to_name[future]
                        print(f"== {name} ==")
                        print(f"  TIMEOUT comparing {name} after {arguments.pair_timeout:g}s")
                        future.cancel()
                        pending.discard(future)
                        failures += 1
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        else:
            for name, first_path, second_path in pairs:
                ok, lines = _compare_files(
                    first_path,
                    second_path,
                    arguments.tolerance,
                    arguments.verbose,
                    kicad_path,
                    arguments.wire_length_tolerance,
                )
                print(f"== {name} ==")
                print("\n".join(lines))
                if not ok:
                    failures += 1
        print(f"\nDirectory comparison: {len(names) - failures}/{len(names)} files matched.")
        return 0 if failures == 0 else 1
    if not first_path.is_file():
        print(f"{first_path}: not a file", file=sys.stderr)
        return 1
    if not second_path.is_file():
        print(f"{second_path}: not a file", file=sys.stderr)
        return 1
    ok, lines = _compare_files(first_path, second_path, arguments.tolerance, arguments.verbose, kicad_path, arguments.wire_length_tolerance)
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
