"""Unit tests for LTspice netlist-to-symbol-initial conversion."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

import json  # Load the generated and expected symbol JSON payloads for exact comparison.
from pathlib import Path  # Use pathlib for robust fixture-path handling.
import tempfile  # Create isolated temporary directories for generated JSON outputs.
import unittest  # Use the standard library test framework.

from electronics_design import ltspice_netlist_to_symbol_initial  # Import the public conversion helper under test.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_VALID_NETLIST_DIRECTORY = _ROOT_DIRECTORY / "valid_convert" / "netlist"  # Point to the repository netlist fixtures used for conversion tests.
_VALID_SYMBOL_INITIAL_DIRECTORY = _ROOT_DIRECTORY / "valid_convert" / "symbol_initial"  # Point to the ground-truth symbol-initial fixtures.
_CONVERT_SETTINGS = {  # Define the LTspice symbol/library settings passed into the converter for every test fixture.
    "ltspice_windows_path": "C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
    "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
    "custom_search_paths": ["./valid_asy/"],
    "grid_size": 16,
    "voltage_must_have_dc": False,
}  # Finish the shared conversion settings dictionary.


class TestNetlistToSymbolInitial(unittest.TestCase):  # Group netlist-to-symbol-initial conversion tests together.
    def test_all_valid_convert_fixtures(self) -> None:  # Convert every repository netlist fixture and compare the result to the paired ground-truth symbol JSON.
        netlist_fixtures = sorted(_VALID_NETLIST_DIRECTORY.glob("*.net"))  # Collect every netlist conversion fixture in deterministic order.
        self.assertTrue(netlist_fixtures, msg="The conversion test suite requires at least one netlist fixture.")  # Assert that the repository fixture set is present.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create an isolated temporary directory for generated symbol JSON outputs.
            for netlist_fixture_path in netlist_fixtures:  # Walk every netlist conversion fixture in deterministic order.
                with self.subTest(fixture=netlist_fixture_path.name):  # Isolate failures to the specific fixture being converted.
                    expected_symbol_initial_path = _VALID_SYMBOL_INITIAL_DIRECTORY / f"{netlist_fixture_path.stem}.json"  # Resolve the paired ground-truth symbol JSON path.
                    self.assertTrue(expected_symbol_initial_path.exists(), msg=f"Missing paired symbol-initial fixture for {netlist_fixture_path.name}.")  # Assert that every netlist fixture has a paired ground-truth symbol JSON file.
                    generated_symbol_initial_path = Path(temporary_directory) / f"{netlist_fixture_path.stem}.json"  # Resolve the temporary output path for the generated symbol JSON.
                    result = ltspice_netlist_to_symbol_initial(str(netlist_fixture_path), str(generated_symbol_initial_path), _CONVERT_SETTINGS)  # Execute the public conversion helper on the current netlist fixture.
                    self.assertEqual(result, (True, "OK", 0), msg=f"{netlist_fixture_path.name} should convert successfully.")  # Assert that conversion succeeds with the stable success tuple.
                    generated_symbol_initial = json.loads(generated_symbol_initial_path.read_text(encoding="utf-8"))  # Load the generated symbol JSON into a comparable Python structure.
                    expected_symbol_initial = json.loads(expected_symbol_initial_path.read_text(encoding="utf-8"))  # Load the paired ground-truth symbol JSON into a comparable Python structure.
                    self.assertEqual(generated_symbol_initial, expected_symbol_initial, msg=f"{netlist_fixture_path.name} should match the paired ground-truth symbol JSON exactly.")  # Assert that the generated JSON matches the expected symbol-initial payload.
                    for symbol_entry in generated_symbol_initial.values():
                        self.assertIn("ORIENTATION", symbol_entry, msg=f"{netlist_fixture_path.name} should expose ORIENTATION in symbol-initial JSON.")
                        self.assertEqual(symbol_entry["ORIENTATION"], "", msg=f"{netlist_fixture_path.name} should emit an empty ORIENTATION value.")
                        self.assertNotIn("ROTATION", symbol_entry, msg=f"{netlist_fixture_path.name} should no longer expose ROTATION in symbol-initial JSON.")
