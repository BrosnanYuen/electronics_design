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

    def test_x_pin_count_mismatch_is_reported(self) -> None:  # Reject X lines that cannot map onto the resolved .asy SpiceOrders.
        settings = dict(_CONVERT_SETTINGS)  # Copy the shared settings before overriding the symbol roots.
        settings["custom_search_paths"] = [  # Resolve the fixture LTC3895 symbol with sparse SpiceOrders.
            str(_ROOT_DIRECTORY / "valid_asy"),  # Keep the standard symbol corpus available.
            str(_ROOT_DIRECTORY / "test_files" / "netlist_to_asc" / "symbols"),  # Provide the sparse 28-pin LTC3895.asy.
        ]  # Finish the symbol roots.
        short_x_netlist = "R1 a 0 1k\nXU1 a b LTC3895\nR2 b 0 1k\n.tran 1\n.backanno\n.end\n"  # List far fewer nodes than the symbol pins.
        with tempfile.TemporaryDirectory() as temporary_directory:
            netlist_path = Path(temporary_directory) / "short_x.net"  # Derive the crafted netlist path.
            netlist_path.write_text(short_x_netlist, encoding="utf-8")  # Write the crafted netlist.
            output_path = Path(temporary_directory) / "short_x.json"  # Derive the symbol JSON output path.
            result = ltspice_netlist_to_symbol_initial(str(netlist_path), str(output_path), settings)  # Convert the crafted deck.
            self.assertFalse(result[0], msg="Short X lines must fail the strict pin-coverage validation.")  # Require failure.
            self.assertTrue(result[1].startswith("X_PIN_COUNT_MISMATCH"), msg=f"Expected X_PIN_COUNT_MISMATCH but got: {result[1]}")  # Require the dedicated error code.
            self.assertEqual(result[2], 2, msg="The error must point at the X line.")  # Require the X line number.
            relaxed_settings = dict(settings)  # Copy the settings for the opt-out path.
            relaxed_settings["ltspice_allow_spice_order_mismatch"] = True  # Restore the historical silent-skip behavior.
            relaxed_result = ltspice_netlist_to_symbol_initial(str(netlist_path), str(output_path), relaxed_settings)  # Convert with validation disabled.
            self.assertEqual(relaxed_result, (True, "OK", 0), msg="The opt-out setting must restore silent skipping.")  # Require success.

    def test_connected_x_line_gap_is_rejected(self) -> None:  # Reject deck nodes beyond SpiceOrder coverage that carry real nets.
        settings = dict(_CONVERT_SETTINGS)  # Copy the shared settings before overriding the symbol roots.
        settings["custom_search_paths"] = [  # Resolve the fixture LTC3895 symbol with sparse SpiceOrders.
            str(_ROOT_DIRECTORY / "valid_asy"),  # Keep the standard symbol corpus available.
            str(_ROOT_DIRECTORY / "test_files" / "netlist_to_asc" / "symbols"),  # Provide the sparse 28-pin LTC3895.asy.
        ]  # Finish the symbol roots.
        node_names = [f"NC_P_{index:02d}" for index in range(1, 40)]  # Fill every SpiceOrder position with an exempt no-connect node.
        node_names[8] = "gap"  # Occupy the missing SpiceOrder 9 position with a real net.
        x_line = "XU1 " + " ".join(node_names) + " LTC3895"  # Build the 39-node X line.
        netlist_text = f"R1 gap 0 1k\n{x_line}\nR2 0 0 1k\n.tran 1\n.backanno\n.end\n"  # Connect the gap node to another device.
        with tempfile.TemporaryDirectory() as temporary_directory:
            netlist_path = Path(temporary_directory) / "connected_gap.net"  # Derive the crafted netlist path.
            netlist_path.write_text(netlist_text, encoding="utf-8")  # Write the crafted netlist.
            output_path = Path(temporary_directory) / "connected_gap.json"  # Derive the symbol JSON output path.
            result = ltspice_netlist_to_symbol_initial(str(netlist_path), str(output_path), settings)  # Convert the crafted deck.
            self.assertFalse(result[0], msg="Connected gap nodes must fail the strict pin-coverage validation.")  # Require failure.
            self.assertTrue(result[1].startswith("X_PIN_COUNT_MISMATCH"), msg=f"Expected X_PIN_COUNT_MISMATCH but got: {result[1]}")  # Require the dedicated error code.
            self.assertIn("'gap'", result[1], msg="The error must name the connected gap node.")  # Require the offending node in the message.
