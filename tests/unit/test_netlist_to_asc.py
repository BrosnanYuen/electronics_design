"""Unit tests for end-to-end LTspice netlist-to-ASC conversion."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from electronics_design import ltspice_asc_structure_cmp
from electronics_design import is_valid_ltspice_asc_file
from electronics_design import ltspice_netlist_to_asc

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_VALID_CONVERT_DIRECTORY = _ROOT_DIRECTORY / "valid_convert"
_VALID_NETLIST_DIRECTORY = _VALID_CONVERT_DIRECTORY / "netlist"
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
}
_SELECTED_FIXTURES = (
    "RC-lowpass.net",
    "Astable-multivibrator.net",
)


class TestNetlistToAsc(unittest.TestCase):
    def test_selected_valid_convert_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            for fixture_name in _SELECTED_FIXTURES:
                with self.subTest(fixture=fixture_name):
                    netlist_path = _VALID_NETLIST_DIRECTORY / fixture_name
                    expected_asc_path = _VALID_ASC_GEN_DIRECTORY / f"{netlist_path.stem}.asc"
                    self.assertTrue(netlist_path.exists(), msg=f"Missing netlist fixture {fixture_name}.")
                    self.assertTrue(expected_asc_path.exists(), msg=f"Missing ASC fixture for {fixture_name}.")
                    output_path = Path(temporary_directory) / f"{netlist_path.stem}.asc"
                    result = ltspice_netlist_to_asc(
                        str(netlist_path),
                        str(output_path),
                        _CONVERT_SETTINGS,
                    )
                    self.assertEqual(result, (True, "OK", 0), msg=f"{fixture_name} should convert successfully.")
                    self.assertEqual(
                        is_valid_ltspice_asc_file(str(output_path)),
                        (True, ""),
                        msg=f"{fixture_name} should generate a valid ASC file.",
                    )
                    self.assertEqual(
                        ltspice_asc_structure_cmp(
                            str(output_path),
                            str(expected_asc_path),
                            _CONVERT_SETTINGS,
                        ),
                        (True, "", 0),
                        msg=f"{fixture_name} should be structurally equivalent to the paired ASC fixture.",
                    )

    def test_invalid_convert_settings_are_rejected(self) -> None:
        netlist_path = _VALID_NETLIST_DIRECTORY / "RC-lowpass.net"
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "RC-lowpass.asc"
            self.assertEqual(
                ltspice_netlist_to_asc(
                    str(netlist_path),
                    str(output_path),
                    [],
                ),
                (False, "INVALID_CONVERT_SETTINGS", 0),
            )
