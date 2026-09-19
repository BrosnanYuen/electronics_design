"""Unit tests for the public netlist symbol-pin introspection helpers."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from pathlib import Path  # Use pathlib for robust fixture-path handling.
import tempfile  # Create isolated temporary directories for crafted netlists.
import unittest  # Use the standard library test framework.

from electronics_design import get_ltspice_asy_pin_count  # Import the ASY pin count helper.
from electronics_design import get_ltspice_asy_spice_orders  # Import the ASY SpiceOrder extraction helper.
from electronics_design import get_ltspice_netlist_device_pins  # Import the netlist device pin introspection helper.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_SPARSE_SYMBOL_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "netlist_to_asc" / "symbols"  # Point at the sparse LTspice fixture symbols.
_LARGE_DECK_PATH = _ROOT_DIRECTORY / "test_files" / "netlist_to_asc" / "large_power_supply.net"  # Use the real 39-node fixture deck.
_CONVERT_SETTINGS = {  # Define the settings passed into the introspection helper.
    "custom_search_paths": [str(_SPARSE_SYMBOL_DIRECTORY), str(_ROOT_DIRECTORY / "valid_asy")],  # Search the sparse symbols first, then the standard corpus.
    "voltage_must_have_dc": False,  # Preserve the historical source normalization behavior.
}  # Finish the shared settings dictionary.
_EXPECTED_SPARSE_ORDERS = [1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 13, 14, 17, 18, 19, 20, 21, 22, 24, 26, 28, 30, 32, 34, 36, 37, 38, 39]  # Match the checked-in 28-pin LTC3895 fixture.


class TestNetlistIntrospection(unittest.TestCase):  # Group the introspection tests together.
    def test_asy_spice_orders_and_pin_count(self) -> None:  # Verify the ASY helpers report the declared SpiceOrders.
        symbol_path = _SPARSE_SYMBOL_DIRECTORY / "LTC3895.asy"  # Use the sparse 28-pin fixture symbol.
        self.assertEqual(get_ltspice_asy_spice_orders(str(symbol_path)), _EXPECTED_SPARSE_ORDERS, msg="The ASY helper must return the ascending sparse SpiceOrders.")  # Require the exact order list.
        self.assertEqual(get_ltspice_asy_pin_count(str(symbol_path)), 28, msg="The ASY helper must count every declared pin.")  # Require the pin count.

    def test_asy_helpers_raise_for_invalid_input(self) -> None:  # Verify the ASY helpers raise on unusable inputs.
        with self.assertRaises(ValueError):  # Require the documented exception shape.
            get_ltspice_asy_spice_orders(str(_SPARSE_SYMBOL_DIRECTORY / "does_not_exist.asy"))  # Read a missing symbol.
        with self.assertRaises(ValueError):  # Require the documented exception shape.
            get_ltspice_asy_pin_count(str(_SPARSE_SYMBOL_DIRECTORY / "does_not_exist.asy"))  # Count a missing symbol.

    def test_device_pins_report_sparse_x_coverage(self) -> None:  # Verify the per-device report for the real 39-node deck.
        report = get_ltspice_netlist_device_pins(str(_LARGE_DECK_PATH), _CONVERT_SETTINGS)  # Introspect the fixture deck.
        self.assertIn("XBUCKP", report, msg="The controller instance must appear in the report.")  # Require the instance.
        buck = report["XBUCKP"]  # Read the controller entry.
        self.assertEqual(buck["SYMBOL"], "LTC3895", msg="The report must name the resolved symbol.")  # Require the symbol name.
        self.assertEqual(buck["ASY_PIN_COUNT"], 28, msg="The report must expose the sparse .asy pin count.")  # Require the pin count.
        self.assertEqual(buck["DECK_NODE_COUNT"], 39, msg="The report must expose the real deck node count.")  # Require the node count.
        self.assertEqual(buck["SPICE_ORDERS"], _EXPECTED_SPARSE_ORDERS, msg="The report must expose the declared SpiceOrders.")  # Require the order list.
        self.assertTrue(buck["VALID"], msg=f"The sparse coverage must be valid but reported: {buck['DETAIL']}")  # Require the sparse acceptance.
        self.assertEqual(buck["DETAIL"], "", msg="Valid mappings must not carry a detail message.")  # Require an empty detail.
        self.assertEqual(buck["UNCOVERED_NODES"], [f"NC_P_{index:02d}" for index in (9, 12, 15, 16, 23, 25, 27, 29, 31, 33, 35)], msg="The uncovered positions must name the NC fillers.")  # Require the filler list.
        bridge = report["XBRIDGEP"]  # Read the active-bridge entry.
        self.assertEqual(bridge["SYMBOL"], "LT4320-1", msg="The bridge must resolve its own fixture symbol.")  # Require the symbol name.
        self.assertEqual(bridge["DECK_NODE_COUNT"], bridge["ASY_PIN_COUNT"], msg="The bridge deck and symbol counts must agree.")  # Require the exact match.
        self.assertTrue(bridge["VALID"], msg="The exact bridge mapping must be valid.")  # Require validity.

    def test_device_pins_flag_short_x_line(self) -> None:  # Verify mismatched X lines are reported as invalid.
        settings = dict(_CONVERT_SETTINGS)  # Copy the shared settings before crafting the deck.
        short_netlist = "R1 a 0 1k\nXU1 a b LTC3895\nR2 b 0 1k\n.tran 1\n.backanno\n.end\n"  # List far fewer nodes than the symbol pins.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the crafted deck.
            netlist_path = Path(temporary_directory) / "short_x.net"  # Derive the crafted netlist path.
            netlist_path.write_text(short_netlist, encoding="utf-8")  # Write the crafted netlist.
            report = get_ltspice_netlist_device_pins(str(netlist_path), settings)  # Introspect the crafted deck.
        entry = report["XU1"]  # Read the subcircuit entry.
        self.assertFalse(entry["VALID"], msg="Short X lines must be reported as invalid.")  # Require the invalid flag.
        self.assertTrue(entry["DETAIL"].startswith("X_PIN_COUNT_MISMATCH"), msg=f"Expected X_PIN_COUNT_MISMATCH but got: {entry['DETAIL']}")  # Require the dedicated diagnostic.
        self.assertEqual(entry["DECK_NODE_COUNT"], 2, msg="The report must expose the short deck node count.")  # Require the node count.
        self.assertEqual(entry["ASY_PIN_COUNT"], 28, msg="The report must still expose the symbol pin count.")  # Require the pin count.

    def test_device_pins_report_unresolved_symbols(self) -> None:  # Verify devices without a resolved symbol stay reportable.
        netlist_text = "R1 a 0 1k\nXU1 a b MissingSubckt\nR2 b 0 1k\n.tran 1\n.backanno\n.end\n"  # Reference an unresolvable subcircuit.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the crafted deck.
            netlist_path = Path(temporary_directory) / "missing.net"  # Derive the crafted netlist path.
            netlist_path.write_text(netlist_text, encoding="utf-8")  # Write the crafted netlist.
            report = get_ltspice_netlist_device_pins(str(netlist_path), _CONVERT_SETTINGS)  # Introspect the crafted deck.
        entry = report["XU1"]  # Read the unresolved subcircuit entry.
        self.assertIsNone(entry["ASY"], msg="Unresolved symbols must report no .asy path.")  # Require the empty path.
        self.assertEqual(entry["ASY_PIN_COUNT"], 0, msg="Unresolved symbols must report zero pins.")  # Require the zero count.
        self.assertTrue(entry["VALID"], msg="Unresolved symbols cannot contradict the mapping and must report valid.")  # Require the permissive flag.
        self.assertEqual(entry["DETAIL"], "no .asy symbol resolved", msg="Unresolved symbols must explain the missing lookup.")  # Require the explanatory detail.

    def test_device_pins_raise_for_invalid_inputs(self) -> None:  # Verify the introspection error contract.
        with self.assertRaises(ValueError):  # Require the documented exception shape.
            get_ltspice_netlist_device_pins(str(_LARGE_DECK_PATH), "not a mapping")  # Pass non-mapping settings.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the invalid deck.
            invalid_path = Path(temporary_directory) / "invalid.net"  # Derive the invalid netlist path.
            invalid_path.write_text("R1 a 0 1k\nY1 a b 1k\n.tran 1\n.backanno\n.end\n", encoding="utf-8")  # Write a netlist with an invalid device prefix.
            with self.assertRaises(ValueError):  # Require the documented exception shape.
                get_ltspice_netlist_device_pins(str(invalid_path), _CONVERT_SETTINGS)  # Introspect the invalid deck.


if __name__ == "__main__":  # Allow running the module directly for debugging.
    unittest.main()  # Execute the unit tests when invoked as a script.
