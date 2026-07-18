"""Unit tests for netlist/symbol/wire to ASC conversion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
import unittest

from electronics_design import is_valid_ltspice_asc_file
from electronics_design import ltspice_asc as _asc_module
from electronics_design import ltspice_netlist_symbol_wire_to_asc

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_VALID_CONVERT_DIRECTORY = _ROOT_DIRECTORY / "valid_convert"
_VALID_NETLIST_DIRECTORY = _VALID_CONVERT_DIRECTORY / "netlist"
_VALID_SYMBOL_DIRECTORY = _VALID_CONVERT_DIRECTORY / "symbol_final"
_VALID_WIRE_DIRECTORY = _VALID_CONVERT_DIRECTORY / "wires"
_VALID_ASC_GEN_DIRECTORY = _VALID_CONVERT_DIRECTORY / "asc_gen"
_CONVERT_SETTINGS = {
    "ltspice_windows_path": "C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
    "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
    "custom_search_paths": ["./valid_asy/"],
    "minimum_dist": 16,
    "wire_pin_out_dist": 16,
    "autoplace_iter": 12,
    "grid_size": 16,
    "ltspice_version": 4.1,
    "voltage_must_have_dc": False,
}
_INTERESTING_ATTR_KEYS = (
    "Value",
    "Value2",
    "SpiceLine",
    "SpiceLine2",
    "SpiceModel",
    "Type",
    "ModelFile",
)


@dataclass(frozen=True)
class _SymbolRecord:
    symbol_name: str
    x_position: int
    y_position: int
    orientation: str
    instance_name: str
    attributes: dict[str, str]


@dataclass(frozen=True)
class _AscSnapshot:
    wires: tuple[tuple[int, int, int, int], ...]
    flags: tuple[tuple[int, int, str], ...]
    symbols: tuple[_SymbolRecord, ...]
    text_payloads: tuple[str, ...]


def _read_snapshot(filepath: Path) -> _AscSnapshot:
    read_result = _asc_module._read_text_file_lines(str(filepath))
    if not read_result[0]:
        raise AssertionError(f"Unable to read ASC snapshot fixture: {filepath}")
    lines = read_result[1]
    wires: list[tuple[int, int, int, int]] = []
    flags: list[tuple[int, int, str]] = []
    symbols: list[_SymbolRecord] = []
    text_payloads: list[str] = []
    current_symbol_name = ""
    current_x_position = 0
    current_y_position = 0
    current_orientation = ""
    current_instance_name = ""
    current_attributes: dict[str, str] = {}

    def _flush_symbol() -> None:
        nonlocal current_symbol_name
        nonlocal current_x_position
        nonlocal current_y_position
        nonlocal current_orientation
        nonlocal current_instance_name
        nonlocal current_attributes
        if current_symbol_name == "":
            return
        symbols.append(
            _SymbolRecord(
                symbol_name=current_symbol_name,
                x_position=current_x_position,
                y_position=current_y_position,
                orientation=current_orientation,
                instance_name=current_instance_name,
                attributes=dict(current_attributes),
            )
        )
        current_symbol_name = ""
        current_x_position = 0
        current_y_position = 0
        current_orientation = ""
        current_instance_name = ""
        current_attributes = {}

    for raw_line in lines:
        stripped_line = raw_line.strip()
        if stripped_line == "":
            continue
        if stripped_line.startswith("SYMBOL "):
            _flush_symbol()
            tokens = stripped_line.split()
            current_symbol_name = tokens[1]
            current_x_position = int(tokens[2])
            current_y_position = int(tokens[3])
            current_orientation = tokens[4]
            continue
        if stripped_line.startswith("WINDOW "):
            continue
        if stripped_line.startswith("SYMATTR "):
            attribute_tokens = stripped_line.split(maxsplit=2)
            attribute_key = attribute_tokens[1]
            attribute_value = attribute_tokens[2] if len(attribute_tokens) > 2 else ""
            if attribute_key == "InstName":
                current_instance_name = attribute_value
            elif attribute_key in _INTERESTING_ATTR_KEYS:
                current_attributes[attribute_key] = _normalize_attribute_value(attribute_value)
            continue
        _flush_symbol()
        if stripped_line.startswith("WIRE "):
            tokens = stripped_line.split()
            wires.append((int(tokens[1]), int(tokens[2]), int(tokens[3]), int(tokens[4])))
            continue
        if stripped_line.startswith("FLAG "):
            tokens = stripped_line.split(maxsplit=3)
            flags.append((int(tokens[1]), int(tokens[2]), tokens[3]))
            continue
        if stripped_line.startswith("TEXT "):
            text_tokens = stripped_line.split(maxsplit=5)
            text_payloads.append(text_tokens[5])
            continue
    _flush_symbol()
    return _AscSnapshot(
        wires=tuple(wires),
        flags=tuple(flags),
        symbols=tuple(symbols),
        text_payloads=tuple(text_payloads),
    )


class TestNetlistSymbolWireToAsc(unittest.TestCase):
    def test_all_valid_convert_fixtures(self) -> None:
        netlist_paths = sorted(_VALID_NETLIST_DIRECTORY.glob("*.net"))
        self.assertTrue(netlist_paths, msg="Expected netlist fixtures for ASC generation tests.")
        with tempfile.TemporaryDirectory() as temporary_directory:
            for netlist_path in netlist_paths:
                with self.subTest(fixture=netlist_path.name):
                    symbol_path = _VALID_SYMBOL_DIRECTORY / f"{netlist_path.stem}.json"
                    wire_path = _VALID_WIRE_DIRECTORY / f"{netlist_path.stem}.json"
                    expected_asc_path = _VALID_ASC_GEN_DIRECTORY / f"{netlist_path.stem}.asc"
                    self.assertTrue(symbol_path.exists(), msg=f"Missing symbol fixture for {netlist_path.name}.")
                    self.assertTrue(wire_path.exists(), msg=f"Missing wire fixture for {netlist_path.name}.")
                    self.assertTrue(expected_asc_path.exists(), msg=f"Missing expected ASC fixture for {netlist_path.name}.")
                    output_path = Path(temporary_directory) / f"{netlist_path.stem}.asc"
                    result = ltspice_netlist_symbol_wire_to_asc(
                        str(netlist_path),
                        str(symbol_path),
                        str(wire_path),
                        str(output_path),
                        _CONVERT_SETTINGS,
                    )
                    self.assertEqual(result, (True, "OK", 0), msg=f"{netlist_path.name} should convert successfully.")
                    validation_result = is_valid_ltspice_asc_file(str(output_path))
                    self.assertEqual(validation_result, (True, ""), msg=f"{netlist_path.name} should generate a valid ASC file.")
                    output_bytes = output_path.read_bytes()
                    self.assertNotIn(b"\xc2\xb5", output_bytes, msg=f"{netlist_path.name} should be Latin-1 compatible, not UTF-8 micro-sign encoded.")
                    generated_snapshot = _read_snapshot(output_path)
                    expected_snapshot = _read_snapshot(expected_asc_path)
                    self.assertEqual(
                        sorted(generated_snapshot.wires),
                        sorted(expected_snapshot.wires),
                        msg=f"{netlist_path.name} should reproduce the expected WIRE records.",
                    )
                    self.assertEqual(
                        sorted(generated_snapshot.flags),
                        sorted(expected_snapshot.flags),
                        msg=f"{netlist_path.name} should reproduce the expected FLAG records.",
                    )
                    self.assertEqual(
                        [
                            (
                                symbol.instance_name,
                                _normalized_symbol_name(symbol.symbol_name),
                                symbol.x_position,
                                symbol.y_position,
                                symbol.orientation,
                            )
                            for symbol in generated_snapshot.symbols
                        ],
                        [
                            (
                                symbol.instance_name,
                                _normalized_symbol_name(symbol.symbol_name),
                                symbol.x_position,
                                symbol.y_position,
                                symbol.orientation,
                            )
                            for symbol in expected_snapshot.symbols
                        ],
                        msg=f"{netlist_path.name} should reproduce the expected symbol placement records.",
                    )
                    _assert_expected_text_payloads_present(
                        self,
                        generated_snapshot.text_payloads,
                        expected_snapshot.text_payloads,
                        netlist_path.name,
                    )
                    generated_attr_map = {symbol.instance_name: symbol.attributes for symbol in generated_snapshot.symbols}
                    for expected_symbol in expected_snapshot.symbols:
                        self.assertIn(
                            expected_symbol.instance_name,
                            generated_attr_map,
                            msg=f"{netlist_path.name} should emit symbol block {expected_symbol.instance_name}.",
                        )
                        for attribute_key, attribute_value in expected_symbol.attributes.items():
                            generated_attribute_value = generated_attr_map[expected_symbol.instance_name].get(attribute_key, "")
                            self.assertEqual(
                                generated_attribute_value,
                                attribute_value,
                                msg=f"{netlist_path.name}:{expected_symbol.instance_name} should preserve {attribute_key}.",
                            )

    def test_invalid_convert_settings_are_rejected(self) -> None:
        netlist_path = _VALID_NETLIST_DIRECTORY / "RC-lowpass.net"
        symbol_path = _VALID_SYMBOL_DIRECTORY / "RC-lowpass.json"
        wire_path = _VALID_WIRE_DIRECTORY / "RC-lowpass.json"
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "RC-lowpass.asc"
            self.assertEqual(
                ltspice_netlist_symbol_wire_to_asc(
                    str(netlist_path),
                    str(symbol_path),
                    str(wire_path),
                    str(output_path),
                    {
                        "ltspice_version": "",
                        "voltage_must_have_dc": False,
                    },
                ),
                (False, "INVALID_CONVERT_SETTINGS", 0),
            )


def _normalize_optional_default_op(text_payloads: tuple[str, ...]) -> tuple[str, ...]:
    normalized_payloads = tuple(
        normalized_part
        for payload in text_payloads
        for normalized_part in _expand_text_payload(_normalize_text_payload(payload))
    )
    directive_payloads = [payload for payload in normalized_payloads if payload.startswith("!.") and not payload.startswith("!;")]
    if directive_payloads != ["!.op"]:
        return normalized_payloads
    return tuple(payload for payload in normalized_payloads if payload != "!.op")


def _normalized_symbol_name(symbol_name: str) -> str:
    return symbol_name.replace("\\", "/").split("/")[-1].lower()


def _assert_expected_text_payloads_present(
    test_case: unittest.TestCase,
    generated_payloads: tuple[str, ...],
    expected_payloads: tuple[str, ...],
    fixture_name: str,
) -> None:
    normalized_generated = _normalize_optional_default_op(generated_payloads)
    normalized_expected = _normalize_optional_default_op(expected_payloads)
    generated_index = 0
    for expected_payload in normalized_expected:
        while generated_index < len(normalized_generated) and normalized_generated[generated_index] != expected_payload:
            generated_index += 1
        test_case.assertLess(
            generated_index,
            len(normalized_generated),
            msg=f"{fixture_name} should include expected TEXT payload {expected_payload!r}.",
        )
        generated_index += 1


def _normalize_text_payload(payload: str) -> str:
    normalized_payload = payload.strip()
    if normalized_payload.lower().startswith("!.function "):
        normalized_payload = f"!.func {normalized_payload[11:]}"
    normalized_payload = normalized_payload.replace("Â°", "°")
    return normalized_payload


def _expand_text_payload(payload: str) -> tuple[str, ...]:
    if "\\n." not in payload:
        return (payload,)
    parts = payload.split("\\n.")
    expanded_parts = [parts[0]]
    expanded_parts.extend(f"!.{part}" for part in parts[1:])
    return tuple(expanded_parts)


def _normalize_attribute_value(attribute_value: str) -> str:
    normalized_value = attribute_value.strip()
    return "" if normalized_value == '""' else normalized_value
