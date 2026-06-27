"""Render validated LTspice ASC schematics as PNG, SVG, or JPEG images."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple

from . import ltspice_asc as _asc

ValidationResult = _asc.ValidationResult
Point = _asc.Point
AscFlag = _asc.AscFlag
AscSchematic = _asc.AscSchematic
AscSymbol = _asc.AscSymbol
AscWire = _asc.AscWire

_SUPPORTED_SCHEMDRAW_EXTENSIONS = {".png", ".svg", ".jpg", ".jpeg"}
_SCHEMDRAW_POINT_SCALE = 64.0
_SCHEMDRAW_MARGIN_UNITS = 1.0
_SCHEMDRAW_DPI = 100.0
_SCHEMDRAW_NEARBY_POINT_RADIUS = 192


def ltspice_asc_plot_schemdraw(
    asc_filepath: str,
    schemdraw_imagepath_out: str,
    width: int = 1920,
    height: int = 1080,
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
        _render_asc_schematic_with_schemdraw(parse_result[1], output_path_result[1], width, height)
    except OSError:
        return False, "Unable to write image file!"
    except (ImportError, RuntimeError, ValueError):
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


def _render_asc_schematic_with_schemdraw(schematic: AscSchematic, output_path: str, width: int, height: int) -> None:
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
    electrical_points = _collect_asc_electrical_points(schematic)
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
        _draw_asc_symbol_schemdraw(drawing, elm, symbol, electrical_points, transform)
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


def _collect_asc_electrical_points(schematic: AscSchematic) -> List[Point]:
    points = {flag.point for flag in schematic.flags}
    for wire in schematic.wires:
        points.add(wire.start)
        points.add(wire.end)
    return sorted(points)


def _count_asc_junction_points(schematic: AscSchematic) -> Dict[Point, int]:
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


def _draw_asc_symbol_schemdraw(drawing, elm, symbol: AscSymbol, electrical_points: Sequence[Point], transform) -> None:
    normalized_name = _normalize_asc_symbol_name(symbol.symbol_name)
    if normalized_name in {"res", "cap", "ind", "diode", "voltage", "current", "sw", "f"}:
        _draw_asc_two_pin_symbol(drawing, elm, symbol, electrical_points, transform)
        return
    if normalized_name in {"npn", "pnp", "nmos", "pmos", "gain", "opamp", "lt1007", "lt1721"}:
        _draw_asc_active_symbol(drawing, elm, symbol, electrical_points, transform)
        return
    _draw_asc_generic_symbol(drawing, elm, symbol, electrical_points, transform)


def _draw_asc_two_pin_symbol(drawing, elm, symbol: AscSymbol, electrical_points: Sequence[Point], transform) -> None:
    pin_pair = _find_two_pin_connection_points(symbol, electrical_points)
    if pin_pair is None:
        center_point = _estimate_symbol_center(symbol, electrical_points)
        _draw_asc_generic_symbol(drawing, elm, symbol, electrical_points, transform, center_override=center_point)
        return
    start_point, end_point = _order_two_pin_points_for_orientation(pin_pair[0], pin_pair[1], symbol.orientation)
    element = _make_two_pin_schemdraw_element(elm, symbol)
    element = element.at(transform(*start_point)).to(transform(*end_point))
    element = _apply_symbol_labels(element, symbol)
    drawing.add(element)


def _draw_asc_active_symbol(drawing, elm, symbol: AscSymbol, electrical_points: Sequence[Point], transform) -> None:
    normalized_name = _normalize_asc_symbol_name(symbol.symbol_name)
    center_point = transform(*_estimate_symbol_center(symbol, electrical_points))
    if normalized_name == "npn":
        element = elm.BjtNpn().at(center_point)
    elif normalized_name == "pnp":
        element = elm.BjtPnp().at(center_point)
    elif normalized_name == "nmos":
        element = elm.NFet().at(center_point)
    elif normalized_name == "pmos":
        element = elm.PFet().at(center_point)
    else:
        element = elm.Opamp().at(center_point)
    element = _apply_orientation_to_schemdraw_element(element, symbol.orientation)
    element = _apply_symbol_labels(element, symbol)
    drawing.add(element)


def _draw_asc_generic_symbol(
    drawing,
    elm,
    symbol: AscSymbol,
    electrical_points: Sequence[Point],
    transform,
    center_override: Optional[Point] = None,
) -> None:
    center_source = center_override if center_override is not None else _estimate_symbol_center(symbol, electrical_points)
    element = elm.Ic(size=(1.6, 1.0)).at(transform(*center_source))
    generic_label = symbol.attributes.get("InstName", symbol.symbol_name)
    element = element.label(generic_label, loc="top")
    value_text = _clean_symbol_value(symbol)
    if value_text != "":
        element = element.label(value_text, loc="bottom")
    drawing.add(element)


def _find_two_pin_connection_points(symbol: AscSymbol, electrical_points: Sequence[Point]) -> Optional[Tuple[Point, Point]]:
    origin_x, origin_y = symbol.origin
    horizontal = _orientation_is_horizontal(symbol.orientation)
    nearby_points = [
        point
        for point in electrical_points
        if abs(point[0] - origin_x) <= _SCHEMDRAW_NEARBY_POINT_RADIUS and abs(point[1] - origin_y) <= _SCHEMDRAW_NEARBY_POINT_RADIUS
    ]
    if len(nearby_points) < 2:
        return None
    best_pair: Optional[Tuple[Point, Point]] = None
    best_score: Optional[Tuple[int, int, int, int]] = None
    for first_index, first_point in enumerate(nearby_points):
        for second_point in nearby_points[first_index + 1 :]:
            if horizontal:
                alignment_penalty = abs(first_point[1] - second_point[1])
                midpoint_penalty = abs(((first_point[1] + second_point[1]) // 2) - origin_y)
                axis_distance = abs(first_point[0] - second_point[0])
                straddle_penalty = 0 if min(first_point[0], second_point[0]) <= origin_x <= max(first_point[0], second_point[0]) else 1
            else:
                alignment_penalty = abs(first_point[0] - second_point[0])
                midpoint_penalty = abs(((first_point[0] + second_point[0]) // 2) - origin_x)
                axis_distance = abs(first_point[1] - second_point[1])
                straddle_penalty = 0 if min(first_point[1], second_point[1]) <= origin_y <= max(first_point[1], second_point[1]) else 1
            total_distance = _point_manhattan_distance(first_point, symbol.origin) + _point_manhattan_distance(second_point, symbol.origin)
            score = (alignment_penalty, straddle_penalty, midpoint_penalty, total_distance - axis_distance)
            if best_score is None or score < best_score:
                best_score = score
                best_pair = (first_point, second_point)
    return best_pair


def _estimate_symbol_center(symbol: AscSymbol, electrical_points: Sequence[Point]) -> Point:
    nearby_points = [
        point
        for point in electrical_points
        if abs(point[0] - symbol.origin[0]) <= _SCHEMDRAW_NEARBY_POINT_RADIUS and abs(point[1] - symbol.origin[1]) <= _SCHEMDRAW_NEARBY_POINT_RADIUS
    ]
    if not nearby_points:
        return symbol.origin
    x_total = sum(point[0] for point in nearby_points)
    y_total = sum(point[1] for point in nearby_points)
    return round(x_total / len(nearby_points)), round(y_total / len(nearby_points))


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


def _orientation_is_horizontal(orientation: str) -> bool:
    return _orientation_angle(orientation) in {90, 270}


def _orientation_angle(orientation: str) -> int:
    angle_match = re.search(r"(\d+)$", orientation)
    if angle_match is None:
        return 0
    return int(angle_match.group(1)) % 360


def _apply_orientation_to_schemdraw_element(element, orientation: str):
    if orientation.upper().startswith("M"):
        element = element.flip()
    angle = _orientation_angle(orientation)
    if angle != 0:
        element = element.theta(angle)
    return element


def _order_two_pin_points_for_orientation(first_point: Point, second_point: Point, orientation: str) -> Tuple[Point, Point]:
    angle = _orientation_angle(orientation)
    if angle == 90:
        return (first_point, second_point) if first_point[0] <= second_point[0] else (second_point, first_point)
    if angle == 270:
        return (first_point, second_point) if first_point[0] >= second_point[0] else (second_point, first_point)
    if angle == 180:
        return (first_point, second_point) if first_point[1] >= second_point[1] else (second_point, first_point)
    return (first_point, second_point) if first_point[1] <= second_point[1] else (second_point, first_point)


def _normalize_asc_symbol_name(symbol_name: str) -> str:
    return symbol_name.split("\\")[-1].lower()


def _point_manhattan_distance(first_point: Point, second_point: Point) -> int:
    return abs(first_point[0] - second_point[0]) + abs(first_point[1] - second_point[1])


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
