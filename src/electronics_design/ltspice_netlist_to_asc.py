"""Convert LTspice netlists directly into LTspice ASC schematics."""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Mapping
from typing import Tuple

from .ltspice_autoplace_symbol_pose import ltspice_autoplace_symbol_pose
from .ltspice_netlist_symbol_wire_to_asc import ltspice_netlist_symbol_wire_to_asc
from .ltspice_netlist_to_symbol_initial import ltspice_netlist_to_symbol_initial

ConversionResult = Tuple[bool, str, int]


def ltspice_netlist_to_asc(
    netlist_filepath: str,
    asc_filepath_out: str,
    convert_settings: Mapping[str, object],
) -> ConversionResult:
    """Convert one LTspice netlist into an LTspice ASC file via the public pipeline."""

    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_directory_path = Path(temporary_directory)
        symbol_json_path = temporary_directory_path / "symbol_pose.json"
        wire_json_path = temporary_directory_path / "wires.json"

        symbol_initial_result = ltspice_netlist_to_symbol_initial(
            netlist_filepath,
            str(symbol_json_path),
            convert_settings,
        )
        if not symbol_initial_result[0]:
            return symbol_initial_result

        autoplace_result = ltspice_autoplace_symbol_pose(
            netlist_filepath,
            str(symbol_json_path),
            str(wire_json_path),
            convert_settings,
        )
        if not autoplace_result[0]:
            return autoplace_result

        return ltspice_netlist_symbol_wire_to_asc(
            netlist_filepath,
            str(symbol_json_path),
            str(wire_json_path),
            asc_filepath_out,
            convert_settings,
        )
