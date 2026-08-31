"""Convert a KiCad schematic into a KiCad PCB file."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

_ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
_SOURCE_DIRECTORY = _ROOT_DIRECTORY / "src"

if str(_SOURCE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_SOURCE_DIRECTORY))

from electronics_design import kicad_sch_to_kicad_pcb


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a KiCad schematic (.kicad_sch) file into a KiCad PCB (.kicad_pcb) file.",
    )
    parser.add_argument(
        "sch_filepath",
        help="Path to the KiCad .kicad_sch schematic file.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional output .kicad_pcb file path. Defaults to the schematic stem plus '.kicad_pcb'.",
    )
    parser.add_argument(
        "--kicad-path",
        default="/usr/share/kicad/",
        help="Root path of the KiCad symbol and footprint libraries used for symbol and footprint lookup.",
    )
    parser.add_argument(
        "--kicad-pcb-layers",
        type=int,
        default=2,
        choices=(2, 4),
        help="Number of copper layers on the generated board. Default: 2.",
    )
    parser.add_argument(
        "--kicad-pcb-width",
        type=float,
        default=None,
        help="Optional explicit board outline width in mm. Defaults to the auto-sized outline.",
    )
    parser.add_argument(
        "--kicad-pcb-height",
        type=float,
        default=None,
        help="Optional explicit board outline height in mm. Defaults to the auto-sized outline.",
    )
    parser.add_argument(
        "--kicad-pcb-margin",
        type=float,
        default=5.0,
        help="Content-to-edge margin in mm. Default: 5.0.",
    )
    parser.add_argument(
        "--kicad-pcb-placement-strategy",
        default="schematic",
        choices=("schematic", "rows"),
        help="Placement strategy: 'schematic' mirrors the schematic layout, 'rows' packs parts in rows. Default: schematic.",
    )
    parser.add_argument(
        "--kicad-pcb-track-width",
        type=float,
        default=0.25,
        help="Routed trace width in mm. Default: 0.25.",
    )
    parser.add_argument(
        "--kicad-pcb-grid-resolution",
        type=float,
        default=0.1,
        help="Routing grid resolution in mm. Default: 0.1.",
    )
    parser.add_argument(
        "--no-route",
        action="store_true",
        help="Skip trace routing and emit the placed board only.",
    )
    parser.add_argument(
        "--kicad-pcb-footprint",
        nargs="*",
        default=[],
        help="Optional 'PATTERN=Lib:Footprint' footprint overrides (PATTERN matches a reference, prefix, or lib_id).",
    )
    return parser


def main() -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args()
    footprint_map: dict[str, str] = {}
    for override in arguments.kicad_pcb_footprint:
        if "=" not in override:
            print(f"invalid --kicad-pcb-footprint override '{override}': expected PATTERN=Lib:Footprint", file=sys.stderr)
            return 1
        pattern, footprint_id = override.split("=", 1)
        footprint_map[pattern] = footprint_id
    convert_settings: dict[str, object] = {
        "kicad_path": arguments.kicad_path,
        "kicad_pcb_layers": arguments.kicad_pcb_layers,
        "kicad_pcb_margin": arguments.kicad_pcb_margin,
        "kicad_pcb_placement_strategy": arguments.kicad_pcb_placement_strategy,
        "kicad_pcb_track_width": arguments.kicad_pcb_track_width,
        "kicad_pcb_grid_resolution": arguments.kicad_pcb_grid_resolution,
        "kicad_pcb_route_traces": not arguments.no_route,
        "kicad_pcb_footprint_map": footprint_map,
    }
    if arguments.kicad_pcb_width is not None:
        convert_settings["kicad_pcb_width"] = arguments.kicad_pcb_width
    if arguments.kicad_pcb_height is not None:
        convert_settings["kicad_pcb_height"] = arguments.kicad_pcb_height
    input_path = Path(arguments.sch_filepath)
    if not input_path.is_file():
        print(f"{input_path}: not a file", file=sys.stderr)
        return 1
    output_path = (
        arguments.out
        if arguments.out is not None
        else str(input_path.with_suffix(".kicad_pcb"))
    )
    result = kicad_sch_to_kicad_pcb(
        str(input_path),
        output_path,
        convert_settings,
    )
    if not result[0]:
        print(f"{input_path.name}: {result[1]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
