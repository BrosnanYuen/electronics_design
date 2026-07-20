"""Render validated LTspice netlists as PNG, SVG, or JPEG network graphs."""

from __future__ import annotations

from html import escape
import math
import os
import struct
from typing import Dict
from typing import List
from typing import Sequence
from typing import Tuple
import zlib

import networkx as nx
import numpy as np

from . import ltspice_net as _net
from ._numba_kernels import fill_rgb_buffer_parallel

ValidationResult = _net.ValidationResult

_PNG_BACKGROUND = (248, 250, 252)
_PNG_EDGE_COLOR = (148, 163, 184)
_PNG_COMPONENT_BORDER = (30, 41, 59)
_PNG_GROUND_COLOR = (51, 65, 85)
_PNG_TEXT_COLOR = (15, 23, 42)
_PNG_TEXT_MUTED = (71, 85, 105)
_PNG_COMPONENT_COLORS = [
    (251, 191, 36),
    (52, 211, 153),
    (96, 165, 250),
    (248, 113, 113),
    (196, 181, 253),
    (244, 114, 182),
]
_COMPONENT_BOX_HALF_WIDTH = 70
_COMPONENT_BOX_HALF_HEIGHT = 22
_GROUND_SYMBOL_HALF_WIDTH = 18
_GROUND_SYMBOL_HEIGHT = 22
_BITMAP_FONT_GLYPHS = {
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    "?": ("01110", "10001", "00001", "00010", "00100", "00000", "00100"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    ",": ("00000", "00000", "00000", "00000", "01100", "01100", "01000"),
    ":": ("00000", "01100", "01100", "00000", "01100", "01100", "00000"),
    ";": ("00000", "01100", "01100", "00000", "01100", "01100", "01000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "_": ("00000", "00000", "00000", "00000", "00000", "00000", "11111"),
    "/": ("00001", "00010", "00100", "01000", "10000", "00000", "00000"),
    "\\": ("10000", "01000", "00100", "00010", "00001", "00000", "00000"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    "=": ("00000", "11111", "00000", "11111", "00000", "00000", "00000"),
    "(": ("00010", "00100", "01000", "01000", "01000", "00100", "00010"),
    ")": ("01000", "00100", "00010", "00010", "00010", "00100", "01000"),
    "[": ("01110", "01000", "01000", "01000", "01000", "01000", "01110"),
    "]": ("01110", "00010", "00010", "00010", "00010", "00010", "01110"),
    "*": ("00000", "10101", "01110", "11111", "01110", "10101", "00000"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11100", "10010", "10001", "10001", "10001", "10010", "11100"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01110"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "J": ("00001", "00001", "00001", "00001", "10001", "10001", "01110"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
}


def ltspice_netlist_plot_networkx(
    netlist_filepath: str,
    networkx_imagepath_out: str,
    width: int = 1920,
    height: int = 1080,
) -> ValidationResult:
    validation_result = _net.is_valid_ltspice_netlist_file(netlist_filepath)
    if not validation_result[0]:
        return validation_result
    parse_result = _net._load_parsed_elements(netlist_filepath)
    if not parse_result[0]:
        return False, "Unable to plot network graph!"
    output_path_result = _net._coerce_path(networkx_imagepath_out)
    if not output_path_result[0]:
        return False, "Unable to write image file!"
    if not isinstance(width, int) or not isinstance(height, int):
        return False, "Unable to plot network graph!"
    if width <= 0 or height <= 0:
        return False, "Unable to plot network graph!"
    graph = _build_networkx_component_plot_graph(parse_result[1])
    try:
        _write_networkx_graph_image(graph, output_path_result[1], width, height)
    except OSError:
        return False, "Unable to write image file!"
    except (ImportError, ValueError):
        return False, "Unable to plot network graph!"
    return True, ""


def _build_networkx_component_plot_graph(elements: Sequence[_net.ParsedElement]) -> nx.MultiGraph:
    graph = nx.MultiGraph()
    node_to_component_ids: Dict[str, List[str]] = {}
    ground_component_ids: List[str] = []
    for element in elements:
        component_node_id = _net._component_node_id(element)
        graph.add_node(
            component_node_id,
            kind="component",
            prefix=element.prefix,
            label=element.tokens[0],
            value_label=_net._component_visual_value(element),
        )
        for node_name in element.nodes:
            if _is_ground_node(node_name):
                if component_node_id not in ground_component_ids:
                    ground_component_ids.append(component_node_id)
                continue
            if _net._is_exempt_node(node_name):
                continue
            component_ids = node_to_component_ids.setdefault(node_name, [])
            if component_node_id not in component_ids:
                component_ids.append(component_node_id)
    for node_name, component_ids in node_to_component_ids.items():
        if len(component_ids) < 2:
            continue
        sorted_component_ids = sorted(component_ids)
        for first_index, first_component_id in enumerate(sorted_component_ids):
            for second_component_id in sorted_component_ids[first_index + 1 :]:
                graph.add_edge(first_component_id, second_component_id, net=node_name)
    if ground_component_ids:
        ground_node_id = "ground:GND"
        graph.add_node(ground_node_id, kind="ground", label="GND")
        for component_node_id in sorted(ground_component_ids):
            graph.add_edge(component_node_id, ground_node_id, net="GND")
    return graph


def _write_networkx_graph_image(graph: nx.MultiGraph, output_path: str, width: int, height: int) -> None:
    extension = os.path.splitext(output_path)[1].lower()
    if extension not in {".png", ".svg", ".jpg", ".jpeg"}:
        raise ValueError("unsupported_image_extension")
    component_nodes = sorted(
        node_id
        for node_id, attributes in graph.nodes(data=True)
        if attributes.get("kind") == "component"
    )
    ground_nodes = sorted(
        node_id
        for node_id, attributes in graph.nodes(data=True)
        if attributes.get("kind") == "ground"
    )
    positions = _assign_component_plot_positions(graph, component_nodes + ground_nodes, width, height)
    if extension == ".svg":
        _write_svg_graph(output_path, graph, positions, width, height)
        return
    canvas = bytearray(width * height * 3)
    _fill_canvas(canvas, width, height, _PNG_BACKGROUND)
    _draw_raster_graph(graph, positions, component_nodes, ground_nodes, canvas, width, height)
    if extension == ".png":
        _write_png_rgb(output_path, width, height, canvas)
        return
    _write_jpeg_rgb(output_path, width, height, canvas)


def _draw_raster_graph(
    graph: nx.MultiGraph,
    positions: Dict[str, Tuple[int, int]],
    component_nodes: Sequence[str],
    ground_nodes: Sequence[str],
    canvas: bytearray,
    width: int,
    height: int,
) -> None:
    for first_node, second_node, edge_key, edge_attributes in graph.edges(keys=True, data=True):
        _draw_graph_edge(
            canvas,
            width,
            height,
            positions[first_node],
            positions[second_node],
            str(graph.nodes[first_node].get("kind", "")),
            str(graph.nodes[second_node].get("kind", "")),
            edge_attributes.get("port", 0),
            edge_key,
        )
    for component_node_id in component_nodes:
        center_x, center_y = positions[component_node_id]
        fill_color = _component_fill_color(str(graph.nodes[component_node_id].get("prefix", "?")))
        _draw_rectangle(
            canvas,
            width,
            height,
            center_x - _COMPONENT_BOX_HALF_WIDTH,
            center_y - _COMPONENT_BOX_HALF_HEIGHT,
            center_x + _COMPONENT_BOX_HALF_WIDTH,
            center_y + _COMPONENT_BOX_HALF_HEIGHT,
            fill_color,
            _PNG_COMPONENT_BORDER,
        )
        _draw_centered_text(
            canvas,
            width,
            height,
            center_x,
            center_y - 4,
            str(graph.nodes[component_node_id].get("label", "")),
            _PNG_TEXT_COLOR,
            2,
            16,
        )
        value_label = str(graph.nodes[component_node_id].get("value_label", ""))
        if value_label != "":
            _draw_centered_text(
                canvas,
                width,
                height,
                center_x,
                center_y + 28,
                value_label,
                _PNG_TEXT_MUTED,
                2,
                22,
            )
    for ground_node_id in ground_nodes:
        center_x, center_y = positions[ground_node_id]
        _draw_ground_symbol(canvas, width, height, center_x, center_y, _PNG_GROUND_COLOR)
        _draw_centered_text(
            canvas,
            width,
            height,
            center_x,
            center_y + 24,
            str(graph.nodes[ground_node_id].get("label", "GND")),
            _PNG_TEXT_MUTED,
            1,
            8,
        )


def _write_svg_graph(
    output_path: str,
    graph: nx.MultiGraph,
    positions: Dict[str, Tuple[int, int]],
    width: int,
    height: int,
) -> None:
    parent_directory = os.path.dirname(output_path)
    if parent_directory != "":
        os.makedirs(parent_directory, exist_ok=True)
    component_nodes = sorted(
        node_id
        for node_id, attributes in graph.nodes(data=True)
        if attributes.get("kind") == "component"
    )
    ground_nodes = sorted(
        node_id
        for node_id, attributes in graph.nodes(data=True)
        if attributes.get("kind") == "ground"
    )
    background_color = _rgb_hex(_PNG_BACKGROUND)
    edge_color = _rgb_hex(_PNG_EDGE_COLOR)
    border_color = _rgb_hex(_PNG_COMPONENT_BORDER)
    text_color = _rgb_hex(_PNG_TEXT_COLOR)
    muted_text_color = _rgb_hex(_PNG_TEXT_MUTED)
    svg_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="{background_color}"/>',
    ]
    for first_node, second_node, edge_key, edge_attributes in graph.edges(keys=True, data=True):
        port_index = int(edge_attributes.get("port", 0)) if isinstance(edge_attributes.get("port", 0), int) else 0
        first_kind = str(graph.nodes[first_node].get("kind", ""))
        second_kind = str(graph.nodes[second_node].get("kind", ""))
        offset = (port_index * 3) + (edge_key * 2)
        first_anchor = _plot_node_edge_anchor(positions[first_node], positions[second_node], first_kind, offset)
        second_anchor = _plot_node_edge_anchor(positions[second_node], positions[first_node], second_kind, offset)
        svg_lines.append(
            f'<line x1="{first_anchor[0]}" y1="{first_anchor[1]}" x2="{second_anchor[0]}" y2="{second_anchor[1]}" stroke="{edge_color}" stroke-width="2"/>'
        )
    for component_node_id in component_nodes:
        center_x, center_y = positions[component_node_id]
        fill_color = _rgb_hex(_component_fill_color(str(graph.nodes[component_node_id].get("prefix", "?"))))
        label = escape(_normalize_svg_text(str(graph.nodes[component_node_id].get("label", "")), 16))
        value_label = escape(_normalize_svg_text(str(graph.nodes[component_node_id].get("value_label", "")), 22))
        svg_lines.append(
            f'<rect x="{center_x - _COMPONENT_BOX_HALF_WIDTH}" y="{center_y - _COMPONENT_BOX_HALF_HEIGHT}" width="{_COMPONENT_BOX_HALF_WIDTH * 2}" height="{_COMPONENT_BOX_HALF_HEIGHT * 2}" rx="6" ry="6" fill="{fill_color}" stroke="{border_color}" stroke-width="2"/>'
        )
        if label != "":
            svg_lines.append(
                f'<text x="{center_x}" y="{center_y + 2}" text-anchor="middle" font-family="monospace" font-size="20" fill="{text_color}">{label}</text>'
            )
        if value_label != "":
            svg_lines.append(
                f'<text x="{center_x}" y="{center_y + 38}" text-anchor="middle" font-family="monospace" font-size="16" fill="{muted_text_color}">{value_label}</text>'
            )
    for ground_node_id in ground_nodes:
        center_x, center_y = positions[ground_node_id]
        label = escape(_normalize_svg_text(str(graph.nodes[ground_node_id].get("label", "GND")), 8))
        svg_lines.extend(_ground_symbol_svg_lines(center_x, center_y, _rgb_hex(_PNG_GROUND_COLOR)))
        if label != "":
            svg_lines.append(
                f'<text x="{center_x}" y="{center_y + 36}" text-anchor="middle" font-family="monospace" font-size="14" fill="{muted_text_color}">{label}</text>'
            )
    svg_lines.append("</svg>")
    with open(output_path, "w", encoding="utf-8") as file_handle:
        file_handle.write("\n".join(svg_lines))


def _ground_symbol_svg_lines(center_x: int, center_y: int, color: str) -> List[str]:
    stem_top_y = center_y - _GROUND_SYMBOL_HEIGHT
    stem_bottom_y = center_y - 4
    return [
        f'<line x1="{center_x}" y1="{stem_top_y}" x2="{center_x}" y2="{stem_bottom_y}" stroke="{color}" stroke-width="2"/>',
        f'<line x1="{center_x - 18}" y1="{center_y}" x2="{center_x + 18}" y2="{center_y}" stroke="{color}" stroke-width="2"/>',
        f'<line x1="{center_x - 12}" y1="{center_y + 6}" x2="{center_x + 12}" y2="{center_y + 6}" stroke="{color}" stroke-width="2"/>',
        f'<line x1="{center_x - 6}" y1="{center_y + 12}" x2="{center_x + 6}" y2="{center_y + 12}" stroke="{color}" stroke-width="2"/>',
    ]


def _write_jpeg_rgb(output_path: str, width: int, height: int, canvas: bytearray) -> None:
    try:
        from PIL import Image  # type: ignore
    except ImportError as import_error:
        raise ImportError("pillow_not_installed") from import_error
    parent_directory = os.path.dirname(output_path)
    if parent_directory != "":
        os.makedirs(parent_directory, exist_ok=True)
    image = Image.frombytes("RGB", (width, height), bytes(canvas))
    image.save(output_path, format="JPEG", quality=95)


def _rgb_hex(color: Tuple[int, int, int]) -> str:
    return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"


def _normalize_svg_text(text: str, max_characters: int) -> str:
    return _normalize_bitmap_text(text, max_characters)


def _assign_component_plot_positions(
    graph: nx.MultiGraph,
    plot_node_ids: Sequence[str],
    width: int,
    height: int,
) -> Dict[str, Tuple[int, int]]:
    if not plot_node_ids:
        return {}
    left_margin = 180
    right_margin = width - 180
    top_margin = 160
    bottom_margin = height - 160
    if bottom_margin <= top_margin or right_margin <= left_margin:
        raise ValueError("image_dimensions_too_small")
    if len(plot_node_ids) == 1:
        only_node_id = plot_node_ids[0]
        return {only_node_id: ((left_margin + right_margin) // 2, (top_margin + bottom_margin) // 2)}
    spring_positions = nx.spring_layout(graph, seed=7, k=1.35 / math.sqrt(len(plot_node_ids)), iterations=300)
    x_values = [spring_positions[node_id][0] for node_id in plot_node_ids]
    y_values = [spring_positions[node_id][1] for node_id in plot_node_ids]
    minimum_x = min(x_values)
    maximum_x = max(x_values)
    minimum_y = min(y_values)
    maximum_y = max(y_values)
    x_span = maximum_x - minimum_x
    y_span = maximum_y - minimum_y
    positions: Dict[str, Tuple[int, int]] = {}
    for node_id in plot_node_ids:
        raw_x, raw_y = spring_positions[node_id]
        normalized_x = 0.5 if x_span == 0 else (raw_x - minimum_x) / x_span
        normalized_y = 0.5 if y_span == 0 else (raw_y - minimum_y) / y_span
        center_x = int(round(left_margin + normalized_x * (right_margin - left_margin)))
        center_y = int(round(top_margin + normalized_y * (bottom_margin - top_margin)))
        positions[node_id] = (center_x, center_y)
    return positions


def _draw_graph_edge(
    canvas: bytearray,
    width: int,
    height: int,
    first_point: Tuple[int, int],
    second_point: Tuple[int, int],
    first_kind: str,
    second_kind: str,
    port_index: object,
    edge_key: int,
) -> None:
    normalized_port_index = port_index if isinstance(port_index, int) else 0
    offset = (normalized_port_index * 3) + (edge_key * 2)
    first_anchor = _plot_node_edge_anchor(first_point, second_point, first_kind, offset)
    second_anchor = _plot_node_edge_anchor(second_point, first_point, second_kind, offset)
    _draw_line(canvas, width, height, first_anchor[0], first_anchor[1], second_anchor[0], second_anchor[1], _PNG_EDGE_COLOR)


def _plot_node_edge_anchor(
    origin: Tuple[int, int],
    target: Tuple[int, int],
    node_kind: str,
    offset: int,
) -> Tuple[int, int]:
    origin_x, origin_y = origin
    target_x, _target_y = target
    if node_kind == "ground":
        horizontal_offset = max(-(_GROUND_SYMBOL_HALF_WIDTH - 2), min(_GROUND_SYMBOL_HALF_WIDTH - 2, offset))
        return origin_x + horizontal_offset, origin_y - _GROUND_SYMBOL_HEIGHT
    vertical_offset = max(-(_COMPONENT_BOX_HALF_HEIGHT - 2), min(_COMPONENT_BOX_HALF_HEIGHT - 2, offset))
    horizontal_anchor = origin_x + _COMPONENT_BOX_HALF_WIDTH if target_x >= origin_x else origin_x - _COMPONENT_BOX_HALF_WIDTH
    return horizontal_anchor, origin_y + vertical_offset


def _component_fill_color(prefix: str) -> Tuple[int, int, int]:
    palette_index = ord(prefix[0]) % len(_PNG_COMPONENT_COLORS)
    return _PNG_COMPONENT_COLORS[palette_index]


def _is_ground_node(node_name: str) -> bool:
    return node_name.upper() in {"0", "GND"}


def _normalize_bitmap_text(text: str, max_characters: int) -> str:
    normalized_characters: List[str] = []
    for raw_character in text:
        if raw_character == "µ" or raw_character == "μ":
            candidate_character = "U"
        elif raw_character.isalpha():
            candidate_character = raw_character.upper()
        else:
            candidate_character = raw_character
        normalized_characters.append(candidate_character if candidate_character in _BITMAP_FONT_GLYPHS else "?")
    normalized_text = "".join(normalized_characters).strip()
    if normalized_text == "":
        return ""
    if len(normalized_text) <= max_characters:
        return normalized_text
    if max_characters <= 3:
        return normalized_text[:max_characters]
    return normalized_text[: max_characters - 3] + "..."


def _draw_centered_text(
    canvas: bytearray,
    width: int,
    height: int,
    center_x: int,
    top_y: int,
    text: str,
    color: Tuple[int, int, int],
    scale: int,
    max_characters: int,
) -> None:
    normalized_text = _normalize_bitmap_text(text, max_characters)
    if normalized_text == "":
        return
    text_width = _bitmap_text_width(normalized_text, scale)
    _draw_text(canvas, width, height, center_x - text_width // 2, top_y, normalized_text, color, scale, max_characters)


def _draw_text(
    canvas: bytearray,
    width: int,
    height: int,
    left_x: int,
    top_y: int,
    text: str,
    color: Tuple[int, int, int],
    scale: int,
    max_characters: int,
) -> None:
    normalized_text = _normalize_bitmap_text(text, max_characters)
    if normalized_text == "":
        return
    cursor_x = left_x
    for character in normalized_text:
        glyph_rows = _BITMAP_FONT_GLYPHS.get(character, _BITMAP_FONT_GLYPHS["?"])
        for row_index, glyph_row in enumerate(glyph_rows):
            for column_index, bit in enumerate(glyph_row):
                if bit != "1":
                    continue
                for delta_y in range(scale):
                    for delta_x in range(scale):
                        _set_pixel(
                            canvas,
                            width,
                            height,
                            cursor_x + column_index * scale + delta_x,
                            top_y + row_index * scale + delta_y,
                            color,
                        )
        cursor_x += (5 * scale) + scale


def _bitmap_text_width(text: str, scale: int) -> int:
    if text == "":
        return 0
    return len(text) * (5 * scale) + (len(text) - 1) * scale


def _fill_canvas(canvas: bytearray, width: int, height: int, color: Tuple[int, int, int]) -> None:
    canvas_array = np.frombuffer(canvas, dtype=np.uint8)
    color_array = np.asarray(color, dtype=np.uint8)
    fill_rgb_buffer_parallel(canvas_array, color_array)


def _set_pixel(
    canvas: bytearray,
    width: int,
    height: int,
    x_position: int,
    y_position: int,
    color: Tuple[int, int, int],
) -> None:
    if x_position < 0 or y_position < 0 or x_position >= width or y_position >= height:
        return
    pixel_offset = (y_position * width + x_position) * 3
    canvas[pixel_offset] = color[0]
    canvas[pixel_offset + 1] = color[1]
    canvas[pixel_offset + 2] = color[2]


def _draw_line(
    canvas: bytearray,
    width: int,
    height: int,
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    color: Tuple[int, int, int],
) -> None:
    delta_x = abs(end_x - start_x)
    delta_y = -abs(end_y - start_y)
    step_x = 1 if start_x < end_x else -1
    step_y = 1 if start_y < end_y else -1
    error_term = delta_x + delta_y
    current_x = start_x
    current_y = start_y
    while True:
        _set_pixel(canvas, width, height, current_x, current_y, color)
        if current_x == end_x and current_y == end_y:
            break
        doubled_error = error_term * 2
        if doubled_error >= delta_y:
            error_term += delta_y
            current_x += step_x
        if doubled_error <= delta_x:
            error_term += delta_x
            current_y += step_y


def _draw_rectangle(
    canvas: bytearray,
    width: int,
    height: int,
    left: int,
    top: int,
    right: int,
    bottom: int,
    fill_color: Tuple[int, int, int],
    border_color: Tuple[int, int, int],
) -> None:
    for y_position in range(top, bottom + 1):
        for x_position in range(left, right + 1):
            is_border_pixel = x_position in {left, right} or y_position in {top, bottom}
            _set_pixel(canvas, width, height, x_position, y_position, border_color if is_border_pixel else fill_color)


def _draw_ground_symbol(
    canvas: bytearray,
    width: int,
    height: int,
    center_x: int,
    center_y: int,
    color: Tuple[int, int, int],
) -> None:
    stem_top_y = center_y - _GROUND_SYMBOL_HEIGHT
    stem_bottom_y = center_y - 4
    _draw_line(canvas, width, height, center_x, stem_top_y, center_x, stem_bottom_y, color)
    _draw_line(canvas, width, height, center_x - 18, center_y, center_x + 18, center_y, color)
    _draw_line(canvas, width, height, center_x - 12, center_y + 6, center_x + 12, center_y + 6, color)
    _draw_line(canvas, width, height, center_x - 6, center_y + 12, center_x + 6, center_y + 12, color)


def _write_png_rgb(output_path: str, width: int, height: int, canvas: bytearray) -> None:
    if width <= 0 or height <= 0:
        raise ValueError("invalid_image_dimensions")
    parent_directory = os.path.dirname(output_path)
    if parent_directory != "":
        os.makedirs(parent_directory, exist_ok=True)
    scanlines = bytearray()
    row_width = width * 3
    for row_index in range(height):
        scanlines.append(0)
        row_start = row_index * row_width
        row_end = row_start + row_width
        scanlines.extend(canvas[row_start:row_end])
    compressed_payload = zlib.compress(bytes(scanlines), level=9)
    png_header = struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)
    with open(output_path, "wb") as file_handle:
        file_handle.write(b"\x89PNG\r\n\x1a\n")
        file_handle.write(_png_chunk(b"IHDR", png_header))
        file_handle.write(_png_chunk(b"IDAT", compressed_payload))
        file_handle.write(_png_chunk(b"IEND", b""))


def _png_chunk(chunk_type: bytes, chunk_payload: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type + chunk_payload) & 0xFFFFFFFF
    return struct.pack("!I", len(chunk_payload)) + chunk_type + chunk_payload + struct.pack("!I", checksum)
