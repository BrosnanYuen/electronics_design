"""Render validated LTspice ASC schematics as PNG, SVG, or JPEG images."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Dict
from typing import List
from typing import Mapping
from typing import Optional
from typing import Sequence
from typing import Tuple

import numpy as np

from . import ltspice_asc as _asc
from . import ltspice_asc_to_netlist as _asc_to_netlist
from . import ltspice_asy as _asy
from .ltspice_asc_to_netlist import get_ltspice_asc_symbol_info
from .pathtracing import find_wire_group_index
from .pathtracing import place_wires_into_groups

ValidationResult = _asc.ValidationResult
Point = _asc.Point
AscFlag = _asc.AscFlag
AscSchematic = _asc.AscSchematic
AscSymbol = _asc.AscSymbol
AscWire = _asc.AscWire
ConnectionKey = Tuple[str, object]

_SUPPORTED_SCHEMDRAW_EXTENSIONS = {".png", ".svg", ".jpg", ".jpeg"}
_SCHEMDRAW_POINT_SCALE = 64.0
_SCHEMDRAW_MARGIN_UNITS = 1.0
_SCHEMDRAW_DPI = 100.0


@dataclass(frozen=True)
class AscRenderPin:
    point: Point
    pin_name: str
    spice_order: int
    wire_group_index: int
    connection_key: ConnectionKey


@dataclass(frozen=True)
class AscRenderSymbol:
    symbol: AscSymbol
    instance_name: str
    rectangle: Tuple[int, int, int, int]
    pins: Tuple[AscRenderPin, ...]


@dataclass(frozen=True)
class AscConnection:
    instance_name: str
    pin_name: str
    spice_order: int
    point: Point


@dataclass(frozen=True)
class AscRenderableSchematic:
    wires: Tuple[AscWire, ...]
    flags: Tuple[AscFlag, ...]
    symbols: Tuple[AscRenderSymbol, ...]
    bounds: Tuple[int, int, int, int]
    wire_groups: Tuple[np.ndarray, ...]
    connections_by_key: Dict[ConnectionKey, Tuple[AscConnection, ...]]
    flags_by_key: Dict[ConnectionKey, Tuple[str, ...]]


def ltspice_asc_plot_schemdraw(
    asc_filepath: str,
    schemdraw_imagepath_out: str,
    width: int = 1920,
    height: int = 1080,
    convert_settings: Optional[Mapping[str, object]] = None,
) -> ValidationResult:
    validation_result = _asc.is_valid_ltspice_asc_file(asc_filepath)
    if not validation_result[0]:
        return validation_result
    output_path_result = _asc._coerce_path(schemdraw_imagepath_out)
    if not output_path_result[0]:
        return False, "Unable to write image file!"
    if isinstance(width, bool) or not isinstance(width, int):
        return False, "Unable to plot schematic drawing!"
    if isinstance(height, bool) or not isinstance(height, int):
        return False, "Unable to plot schematic drawing!"
    if width <= 0 or height <= 0:
        return False, "Unable to plot schematic drawing!"
    extension = Path(output_path_result[1]).suffix.lower()
    if extension not in _SUPPORTED_SCHEMDRAW_EXTENSIONS:
        return False, "Unable to plot schematic drawing!"
    read_result = _asc._read_text_file_lines(asc_filepath)
    if not read_result[0]:
        return False, read_result[2]
    parse_result = _parse_asc_schematic(read_result[1])
    if not parse_result[0]:
        return False, "Unable to plot schematic drawing!"
    try:
        renderable_schematic = _build_renderable_schematic(
            asc_filepath,
            parse_result[1],
            {} if convert_settings is None else convert_settings,
        )
        _render_asc_schematic_with_schemdraw(renderable_schematic, output_path_result[1], width, height)
    except OSError:
        return False, "Unable to write image file!"
    except (ImportError, RuntimeError, TypeError, ValueError):
        return False, "Unable to plot schematic drawing!"
    return True, ""


def _parse_asc_schematic(lines: Sequence[str]) -> Tuple[bool, AscSchematic]:
    wires: List[AscWire] = []
    flags: List[AscFlag] = []
    symbols: List[AscSymbol] = []
    current_symbol: Optional[AscSymbol] = None
    all_points: List[Point] = []
    for raw_line in lines:
        if raw_line.strip() == "":
            continue
        tokens = raw_line.split()
        keyword = tokens[0].upper()
        if keyword == "WIRE":
            start_point = (int(tokens[1]), int(tokens[2]))
            end_point = (int(tokens[3]), int(tokens[4]))
            wires.append(AscWire(start=start_point, end=end_point))
            all_points.extend([start_point, end_point])
            current_symbol = None
            continue
        if keyword == "FLAG":
            flag_point = (int(tokens[1]), int(tokens[2]))
            flags.append(AscFlag(point=flag_point, name=" ".join(tokens[3:])))
            all_points.append(flag_point)
            current_symbol = None
            continue
        if keyword == "SYMBOL":
            current_symbol = AscSymbol(
                symbol_name=tokens[1],
                origin=(int(tokens[2]), int(tokens[3])),
                orientation=tokens[4],
                attributes={},
            )
            symbols.append(current_symbol)
            all_points.append(current_symbol.origin)
            continue
        if keyword == "SYMATTR" and current_symbol is not None:
            attr_tokens = raw_line.split(maxsplit=2)
            if len(attr_tokens) >= 3:
                current_symbol.attributes[attr_tokens[1]] = attr_tokens[2]
            continue
        if keyword == "WINDOW" and current_symbol is not None:
            continue
        current_symbol = None
    if not all_points:
        return False, AscSchematic(wires=[], flags=[], symbols=[], bounds=(0, 0, 0, 0))
    x_values = [point[0] for point in all_points]
    y_values = [point[1] for point in all_points]
    schematic = AscSchematic(
        wires=wires,
        flags=flags,
        symbols=symbols,
        bounds=(min(x_values), min(y_values), max(x_values), max(y_values)),
    )
    return True, schematic


def _build_renderable_schematic(
    asc_filepath: str,
    schematic: AscSchematic,
    convert_settings: Mapping[str, object],
) -> AscRenderableSchematic:
    symbol_info = _load_symbol_info_for_plotting(asc_filepath, schematic, convert_settings)
    wire_groups = _wire_groups_from_schematic(schematic)
    connections_by_key: Dict[ConnectionKey, List[AscConnection]] = {}
    render_symbols: List[AscRenderSymbol] = []
    for symbol in schematic.symbols:
        instance_name = symbol.attributes.get("InstName", "").strip()
        if instance_name == "":
            instance_name = _normalize_asc_symbol_name(symbol.symbol_name)
        info = symbol_info.get(instance_name)
        if info is None:
            rectangle = (symbol.origin[0], symbol.origin[1], symbol.origin[0], symbol.origin[1])
            pins = ()
        else:
            rectangle = _extract_symbol_rectangle(info.get("RECTANGLE"))
            pins = tuple(
                sorted(
                    (_build_render_pin(pin_row, wire_groups) for pin_row in info.get("PINS", ())),
                    key=lambda pin: pin.spice_order,
                )
            )
        for pin in pins:
            connections_by_key.setdefault(pin.connection_key, []).append(
                AscConnection(
                    instance_name=instance_name,
                    pin_name=pin.pin_name,
                    spice_order=pin.spice_order,
                    point=pin.point,
                )
            )
        render_symbols.append(
            AscRenderSymbol(
                symbol=symbol,
                instance_name=instance_name,
                rectangle=rectangle,
                pins=pins,
            )
        )
    flags_by_key: Dict[ConnectionKey, List[str]] = {}
    for flag in schematic.flags:
        connection_key = _connection_key_for_point(flag.point, wire_groups)
        flag_name = flag.name.strip()
        if flag_name == "":
            continue
        flags_by_key.setdefault(connection_key, [])
        if flag_name not in flags_by_key[connection_key]:
            flags_by_key[connection_key].append(flag_name)
    return AscRenderableSchematic(
        wires=tuple(schematic.wires),
        flags=tuple(schematic.flags),
        symbols=tuple(render_symbols),
        bounds=_build_render_bounds(schematic, render_symbols),
        wire_groups=wire_groups,
        connections_by_key={key: tuple(value) for key, value in connections_by_key.items()},
        flags_by_key={key: tuple(value) for key, value in flags_by_key.items()},
    )


def _load_symbol_info_for_plotting(
    asc_filepath: str,
    schematic: AscSchematic,
    convert_settings: Mapping[str, object],
) -> Dict[str, Dict[str, object]]:
    try:
        return get_ltspice_asc_symbol_info(asc_filepath, convert_settings)
    except ValueError:
        return _load_partial_symbol_info(asc_filepath, schematic, convert_settings)


def _load_partial_symbol_info(
    asc_filepath: str,
    schematic: AscSchematic,
    convert_settings: Mapping[str, object],
) -> Dict[str, Dict[str, object]]:
    search_roots = _asc_to_netlist._resolve_search_roots_for_asc(asc_filepath, convert_settings)
    symbol_paths = _asc_to_netlist._build_symbol_filepath_lookup(search_roots)
    symbol_info: Dict[str, Dict[str, object]] = {}
    for symbol in schematic.symbols:
        instance_name = symbol.attributes.get("InstName", "").strip()
        if instance_name == "":
            continue
        symbol_filepath = _asc_to_netlist._resolve_symbol_filepath(symbol.symbol_name, symbol_paths)
        if symbol_filepath is None:
            continue
        try:
            pins = _asy.get_ltspice_asy_pins(symbol_filepath)
            bounds = _asy.get_ltspice_asy_size(symbol_filepath)
        except ValueError:
            continue
        transformed_pins = [
            [
                transformed_point[0],
                transformed_point[1],
                pin_name,
                spice_order,
            ]
            for pin_x, pin_y, pin_name, spice_order in pins
            for transformed_point in [
                _asc_to_netlist._transform_pin_point(
                    (int(pin_x), int(pin_y)),
                    symbol.origin,
                    symbol.orientation,
                )
            ]
        ]
        symbol_entry: Dict[str, object] = {
            "SYMBOL": _asc_to_netlist._display_symbol_name(symbol.symbol_name),
            "X": symbol.origin[0],
            "Y": symbol.origin[1],
            "ROTATION": _asc_to_netlist._orientation_angle(symbol.orientation),
            "RECTANGLE": _asc_to_netlist._transform_symbol_rectangle(bounds, symbol.origin, symbol.orientation),
            "PINS": transformed_pins,
        }
        _asc_to_netlist._add_symbol_info_text_field(symbol_entry, "VALUE", symbol.attributes.get("Value", ""))
        _asc_to_netlist._add_symbol_info_text_field(symbol_entry, "SPICELINE", symbol.attributes.get("SpiceLine", ""))
        _asc_to_netlist._add_symbol_info_text_field(symbol_entry, "TYPE", symbol.attributes.get("Type", ""))
        symbol_info[instance_name] = symbol_entry
    return symbol_info


def _extract_symbol_rectangle(raw_rectangle: object) -> Tuple[int, int, int, int]:
    try:
        first_point, second_point = raw_rectangle
        min_x = int(first_point[0])
        min_y = int(first_point[1])
        max_x = int(second_point[0])
        max_y = int(second_point[1])
    except (TypeError, ValueError, IndexError) as error:
        raise ValueError("Invalid symbol rectangle metadata.") from error
    return min(min_x, max_x), min(min_y, max_y), max(min_x, max_x), max(min_y, max_y)


def _build_render_pin(pin_row: object, wire_groups: Sequence[np.ndarray]) -> AscRenderPin:
    try:
        pin_x, pin_y, pin_name, spice_order = pin_row
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid symbol pin metadata.") from error
    pin_point = (int(pin_x), int(pin_y))
    wire_group_index = find_wire_group_index(np.array([pin_point[0], pin_point[1]], dtype=int), list(wire_groups))
    connection_key = ("wire_group", wire_group_index) if wire_group_index >= 0 else ("point", pin_point)
    return AscRenderPin(
        point=pin_point,
        pin_name=str(pin_name),
        spice_order=int(spice_order),
        wire_group_index=wire_group_index,
        connection_key=connection_key,
    )


def _connection_key_for_point(point: Point, wire_groups: Sequence[np.ndarray]) -> ConnectionKey:
    wire_group_index = find_wire_group_index(np.array([point[0], point[1]], dtype=int), list(wire_groups))
    if wire_group_index >= 0:
        return "wire_group", wire_group_index
    return "point", point


def _wire_groups_from_schematic(schematic: AscSchematic) -> Tuple[np.ndarray, ...]:
    if not schematic.wires:
        return ()
    wire_rows = np.array(
        [[wire.start[0], wire.start[1], wire.end[0], wire.end[1]] for wire in schematic.wires],
        dtype=int,
    )
    return tuple(place_wires_into_groups(wire_rows))


def _build_render_bounds(
    schematic: AscSchematic,
    symbols: Sequence[AscRenderSymbol],
) -> Tuple[int, int, int, int]:
    all_points: List[Point] = []
    for wire in schematic.wires:
        all_points.extend([wire.start, wire.end])
    for flag in schematic.flags:
        all_points.append(flag.point)
    for symbol in symbols:
        all_points.extend(
            [
                (symbol.rectangle[0], symbol.rectangle[1]),
                (symbol.rectangle[2], symbol.rectangle[3]),
            ]
        )
        all_points.extend(pin.point for pin in symbol.pins)
    if not all_points:
        return schematic.bounds
    x_values = [point[0] for point in all_points]
    y_values = [point[1] for point in all_points]
    return min(x_values), min(y_values), max(x_values), max(y_values)


def _render_asc_schematic_with_schemdraw(
    schematic: AscRenderableSchematic,
    output_path: str,
    width: int,
    height: int,
) -> None:
    _configure_matplotlib_cache_directory()
    import schemdraw
    import schemdraw.elements as elm

    extension = Path(output_path).suffix.lower()
    backend = "svg" if extension == ".svg" else "matplotlib"
    transform = _make_schemdraw_point_transform(schematic.bounds)
    drawing_width_units = transform(schematic.bounds[2], schematic.bounds[1])[0] + _SCHEMDRAW_MARGIN_UNITS
    drawing_height_units = transform(schematic.bounds[0], schematic.bounds[3])[1] + _SCHEMDRAW_MARGIN_UNITS
    inches_per_unit = min(
        (width / _SCHEMDRAW_DPI) / max(drawing_width_units, 1.0),
        (height / _SCHEMDRAW_DPI) / max(drawing_height_units, 1.0),
    )
    drawing = schemdraw.Drawing(
        show=False,
        canvas=backend,
        unit=1.0,
        inches_per_unit=inches_per_unit,
        fontsize=10.0,
        lw=1.5,
        margin=0.05,
    )
    junction_points = _count_asc_junction_points(schematic)
    for wire in schematic.wires:
        drawing.add(elm.Line().at(transform(*wire.start)).to(transform(*wire.end)))
    for point, count in sorted(junction_points.items()):
        if count < 3:
            continue
        drawing.add(elm.Dot().at(transform(*point)))
    for flag in schematic.flags:
        _draw_asc_flag(drawing, elm, flag, transform)
    for symbol in schematic.symbols:
        _draw_asc_symbol_schemdraw(drawing, elm, schematic, symbol, transform)
    drawing.save(output_path, dpi=_SCHEMDRAW_DPI)
    if extension == ".svg":
        _rewrite_svg_dimensions(output_path, width, height)
        return
    _resize_raster_image(output_path, extension, width, height)


def _configure_matplotlib_cache_directory() -> None:
    if "MPLCONFIGDIR" in os.environ and os.environ["MPLCONFIGDIR"] != "":
        return
    cache_directory = Path("/tmp") / "electronics_design_mplconfig"
    cache_directory.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(cache_directory)


def _make_schemdraw_point_transform(bounds: Tuple[int, int, int, int]):
    min_x, _min_y, _max_x, max_y = bounds

    def _transform(x_position: int, y_position: int) -> Tuple[float, float]:
        x_value = ((x_position - min_x) / _SCHEMDRAW_POINT_SCALE) + _SCHEMDRAW_MARGIN_UNITS
        y_value = ((max_y - y_position) / _SCHEMDRAW_POINT_SCALE) + _SCHEMDRAW_MARGIN_UNITS
        return x_value, y_value

    return _transform


def _count_asc_junction_points(schematic: AscRenderableSchematic) -> Dict[Point, int]:
    counts: Dict[Point, int] = {}
    for wire in schematic.wires:
        counts[wire.start] = counts.get(wire.start, 0) + 1
        counts[wire.end] = counts.get(wire.end, 0) + 1
    for flag in schematic.flags:
        counts[flag.point] = counts.get(flag.point, 0) + 1
    return counts


def _draw_asc_flag(drawing, elm, flag: AscFlag, transform) -> None:
    transformed_point = transform(*flag.point)
    normalized_name = flag.name.strip()
    if normalized_name.upper() in {"0", "GND"}:
        drawing.add(elm.Ground().at(transformed_point))
        return
    drawing.add(elm.Dot().at(transformed_point).label(normalized_name, loc="right"))


def _draw_asc_symbol_schemdraw(
    drawing,
    elm,
    schematic: AscRenderableSchematic,
    symbol: AscRenderSymbol,
    transform,
) -> None:
    normalized_name = _normalize_asc_symbol_name(symbol.symbol.symbol_name)
    if normalized_name in {"res", "cap", "ind", "diode", "voltage", "current", "sw", "f"} and len(symbol.pins) >= 2:
        _draw_asc_two_pin_symbol(drawing, elm, symbol, transform)
        return
    _draw_asc_block_symbol(drawing, elm, schematic, symbol, transform)


def _draw_asc_two_pin_symbol(drawing, elm, symbol: AscRenderSymbol, transform) -> None:
    ordered_pins = tuple(sorted(symbol.pins, key=lambda pin: pin.spice_order))
    start_point = ordered_pins[0].point
    end_point = ordered_pins[1].point
    element = _make_two_pin_schemdraw_element(elm, symbol.symbol)
    element = element.at(transform(*start_point)).to(transform(*end_point))
    element = _apply_symbol_labels(element, symbol.symbol)
    drawing.add(element)


def _draw_asc_block_symbol(
    drawing,
    elm,
    schematic: AscRenderableSchematic,
    symbol: AscRenderSymbol,
    transform,
) -> None:
    if symbol.rectangle[0] == symbol.rectangle[2] and symbol.rectangle[1] == symbol.rectangle[3] and not symbol.pins:
        label = elm.Label(symbol.instance_name).at(transform(*symbol.symbol.origin))
        value_text = _clean_symbol_value(symbol.symbol)
        if value_text != "":
            label = label.label(value_text, loc="bottom")
        drawing.add(label)
        return
    left, bottom, right, top = _transform_rectangle_bounds(symbol.rectangle, transform)
    rectangle = elm.Rect(corner1=(left, bottom), corner2=(right, top))
    rectangle = _apply_symbol_labels(rectangle, symbol.symbol)
    drawing.add(rectangle)
    for pin in symbol.pins:
        _draw_symbol_pin(drawing, elm, schematic, pin, left, bottom, right, top, transform)


def _transform_rectangle_bounds(rectangle: Tuple[int, int, int, int], transform) -> Tuple[float, float, float, float]:
    first_corner = transform(rectangle[0], rectangle[1])
    second_corner = transform(rectangle[2], rectangle[3])
    left = min(first_corner[0], second_corner[0])
    right = max(first_corner[0], second_corner[0])
    bottom = min(first_corner[1], second_corner[1])
    top = max(first_corner[1], second_corner[1])
    return left, bottom, right, top


def _draw_symbol_pin(
    drawing,
    elm,
    schematic: AscRenderableSchematic,
    pin: AscRenderPin,
    left: float,
    bottom: float,
    right: float,
    top: float,
    transform,
) -> None:
    pin_point = transform(*pin.point)
    anchor_point = _nearest_rectangle_edge_point(pin_point, left, bottom, right, top)
    if abs(anchor_point[0] - pin_point[0]) > 1e-9 or abs(anchor_point[1] - pin_point[1]) > 1e-9:
        drawing.add(elm.Line().at(anchor_point).to(pin_point))
    if _pin_has_connection(schematic, pin):
        drawing.add(elm.Dot().at(pin_point))


def _nearest_rectangle_edge_point(
    point: Tuple[float, float],
    left: float,
    bottom: float,
    right: float,
    top: float,
) -> Tuple[float, float]:
    point_x, point_y = point
    if left <= point_x <= right and bottom <= point_y <= top:
        return point
    clamped_x = min(max(point_x, left), right)
    clamped_y = min(max(point_y, bottom), top)
    distances = {
        (left, clamped_y): abs(point_x - left),
        (right, clamped_y): abs(point_x - right),
        (clamped_x, bottom): abs(point_y - bottom),
        (clamped_x, top): abs(point_y - top),
    }
    return min(distances.items(), key=lambda item: item[1])[0]


def _pin_has_connection(schematic: AscRenderableSchematic, pin: AscRenderPin) -> bool:
    connection_count = len(schematic.connections_by_key.get(pin.connection_key, ()))
    flag_count = len(schematic.flags_by_key.get(pin.connection_key, ()))
    return pin.wire_group_index >= 0 or connection_count > 1 or flag_count > 0


def _make_two_pin_schemdraw_element(elm, symbol: AscSymbol):
    normalized_name = _normalize_asc_symbol_name(symbol.symbol_name)
    if normalized_name == "res":
        return elm.Resistor()
    if normalized_name == "cap":
        return elm.Capacitor()
    if normalized_name == "ind":
        return elm.Inductor()
    if normalized_name == "diode":
        return elm.Diode()
    if normalized_name == "voltage":
        return elm.SourceV()
    if normalized_name == "current":
        return elm.SourceI()
    if normalized_name == "f":
        return elm.SourceControlledI()
    return elm.Switch()


def _apply_symbol_labels(element, symbol: AscSymbol):
    instance_name = symbol.attributes.get("InstName", "").strip()
    if instance_name != "":
        element = element.label(instance_name, loc="top")
    value_text = _clean_symbol_value(symbol)
    if value_text != "":
        element = element.label(value_text, loc="bottom")
    return element


def _clean_symbol_value(symbol: AscSymbol) -> str:
    raw_value = symbol.attributes.get("Value", "").strip()
    if raw_value in {"", '""'}:
        raw_value = symbol.attributes.get("SpiceLine", "").strip()
    return raw_value


def _normalize_asc_symbol_name(symbol_name: str) -> str:
    return symbol_name.replace("\\", "/").split("/")[-1].lower()


def _rewrite_svg_dimensions(output_path: str, width: int, height: int) -> None:
    svg_text = Path(output_path).read_text(encoding="utf-8")
    svg_text = re.sub(r'width="[^"]+"', f'width="{width}px"', svg_text, count=1)
    svg_text = re.sub(r'height="[^"]+"', f'height="{height}px"', svg_text, count=1)
    Path(output_path).write_text(svg_text, encoding="utf-8")


def _resize_raster_image(output_path: str, extension: str, width: int, height: int) -> None:
    from PIL import Image

    with Image.open(output_path) as image:
        if image.size == (width, height):
            return
        resized_image = image.resize((width, height), Image.Resampling.LANCZOS)
        if extension in {".jpg", ".jpeg"} and resized_image.mode not in {"RGB", "L"}:
            resized_image = resized_image.convert("RGB")
        save_format = "JPEG" if extension in {".jpg", ".jpeg"} else "PNG"
        resized_image.save(output_path, format=save_format)
