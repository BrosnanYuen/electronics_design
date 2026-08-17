"""Unit tests for the LTspice netlist to KiCad schematic conversion API."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

import os  # Read the optional KiCad path environment override.
from pathlib import Path  # Use pathlib for clear path handling.
import tempfile  # Use a temporary directory for round-trip netlist outputs.
import unittest  # Use the standard library test framework.

from electronics_design import is_valid_kicad_sch_file  # Import the KiCad schematic whole-file validator.
from electronics_design import is_valid_ltspice_netlist_file  # Import the LTspice netlist whole-file validator.
from electronics_design import kicad_sch_to_ltspice_netlist  # Import the KiCad schematic to LTspice netlist conversion API.
from electronics_design import ltspice_netlist_structure_cmp  # Import the LTspice netlist structural comparison helper.
from electronics_design import ltspice_netlist_to_kicad_sch  # Import the netlist-to-KiCad-schematic conversion API.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_NETLIST_DIRECTORY = _ROOT_DIRECTORY / "kicad_convert" / "netlist"  # Point at the checked-in LTspice netlist files.

_KICAD_PATH = os.environ.get("ELECTRONICS_DESIGN_KICAD_PATH", "/usr/share/kicad")  # Resolve the KiCad library path with an optional environment override.

_CONVERT_SETTINGS = {  # Pin the settings so generated files are reproducible.
    "kicad_path": _KICAD_PATH,  # Look symbols up from the configured KiCad installation path.
    "kicad_sch_version": "20260306",  # Use a fixed eight-digit KiCad format version.
    "kicad_sch_generator": "electronics_design",  # Name the generator explicitly.
    "custom_search_paths": [  # Resolve LTspice ASY fallback symbols from the repository corpus.
        str(_ROOT_DIRECTORY / "kicad_convert" / "asy"),  # Use the checked-in ASY conversion corpus first.
        str(_ROOT_DIRECTORY / "valid_asy"),  # Fall back to the standard valid ASY fixtures.
    ],  # Finish the custom search paths.
}  # Finish the conversion settings dictionary.


class TestNetlistToKicadSch(unittest.TestCase):  # Group the netlist-to-KiCad-schematic conversion tests together.
    def test_all_netlists_convert_to_valid_kicad_schematics(self) -> None:  # Verify every netlist converts to a valid KiCad schematic that round-trips structurally.
        net_files = sorted(_NETLIST_DIRECTORY.glob("*.net"))  # Collect all LTspice netlist files in the fixture directory.
        self.assertGreater(len(net_files), 0, msg="kicad_convert/netlist/ must contain LTspice netlist files.")  # Require the source files to exist.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the generated schematics and round-trip netlists.
            for net_path in net_files:  # Walk every LTspice netlist file.
                with self.subTest(netlist=net_path.name):  # Isolate failures per netlist file.
                    output_path = Path(temporary_directory) / f"{net_path.stem}.kicad_sch"  # Derive the scratch KiCad schematic path.
                    result = ltspice_netlist_to_kicad_sch(str(net_path), str(output_path), _CONVERT_SETTINGS)  # Run the public conversion API.
                    self.assertEqual(  # Require the conversion to succeed with the standard success tuple.
                        result,  # Compare the returned conversion result.
                        (True, "OK", 0),  # Expect success, the OK message, and line zero.
                        msg=f"{net_path.name} should convert but returned: {result}",  # Report the failure with the returned tuple.
                    )  # Finish the conversion assertion.
                    validation = is_valid_kicad_sch_file(str(output_path))  # Validate the freshly generated KiCad schematic.
                    self.assertEqual(  # Require the generated file to pass the whole-file schematic validator.
                        validation,  # Compare the returned validation result.
                        (True, ""),  # Expect success with an empty message.
                        msg=f"{output_path.name} should be valid but returned: {validation[1]}",  # Report the failure with the returned message.
                    )  # Finish the validation assertion.
                    round_trip_path = Path(temporary_directory) / f"{net_path.stem}.net"  # Derive the scratch round-trip netlist path.
                    round_trip_result = kicad_sch_to_ltspice_netlist(str(output_path), str(round_trip_path), _CONVERT_SETTINGS)  # Convert the schematic back into a netlist.
                    self.assertEqual(  # Require the reverse conversion to succeed.
                        round_trip_result,  # Compare the returned conversion result.
                        (True, "OK", 0),  # Expect success, the OK message, and line zero.
                        msg=f"{output_path.name} should convert back but returned: {round_trip_result}",  # Report the failure with the returned tuple.
                    )  # Finish the reverse conversion assertion.
                    round_trip_validation = is_valid_ltspice_netlist_file(str(round_trip_path))  # Validate the round-trip netlist file.
                    self.assertEqual(  # Require the round-trip netlist to pass the whole-file netlist validator.
                        round_trip_validation,  # Compare the returned validation result.
                        (True, ""),  # Expect success with an empty message.
                        msg=f"{round_trip_path.name} should be valid but returned: {round_trip_validation[1]}",  # Report the failure with the returned message.
                    )  # Finish the round-trip validation assertion.
                    structure_matches = ltspice_netlist_structure_cmp(str(net_path), str(round_trip_path))  # Compare the round-trip structure to the original netlist.
                    self.assertTrue(  # Require the round-trip netlist to be structurally equivalent to the original.
                        structure_matches,  # Check the structural comparison result.
                        msg=f"{round_trip_path.name} must match {net_path.name} structurally.",  # Report the structural mismatch.
                    )  # Finish the structural assertion.

    def test_missing_input_returns_invalid_netlist_file(self) -> None:  # Verify the missing input error contract.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the call.
            result = ltspice_netlist_to_kicad_sch(  # Call the conversion API with a nonexistent input.
                str(_NETLIST_DIRECTORY / "does_not_exist.net"),  # Use a path that cannot exist.
                str(Path(temporary_directory) / "does_not_exist.kicad_sch"),  # Use a writable output path.
                _CONVERT_SETTINGS,  # Pass the shared settings mapping.
            )  # Finish the conversion call.
            self.assertEqual(result[0], False, msg="Missing input files must fail conversion.")  # Require failure.
            self.assertEqual(result[1], "INVALID_NETLIST_FILE", msg="Missing input files must report the netlist error code.")  # Require the netlist error code.
            self.assertEqual(result[2], 0, msg="Path failures must report line zero.")  # Require the unknown line number.

    def test_invalid_settings_return_invalid_convert_settings(self) -> None:  # Verify the settings validation error contract.
        source_path = next(_NETLIST_DIRECTORY.glob("*.net"))  # Read one valid source file for the call.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the call.
            result = ltspice_netlist_to_kicad_sch(  # Call the conversion API with invalid settings.
                str(source_path),  # Pass the valid source path.
                str(Path(temporary_directory) / "ignored.kicad_sch"),  # Pass a writable output path.
                "not a mapping",  # Pass a non-mapping settings value.
            )  # Finish the conversion call.
            self.assertEqual(result, (False, "INVALID_CONVERT_SETTINGS", 0), msg="Non-mapping settings must fail with the settings error code.")  # Require the settings error tuple.

    def test_missing_kicad_path_returns_invalid_convert_settings(self) -> None:  # Verify that a missing kicad_path setting is rejected.
        source_path = next(_NETLIST_DIRECTORY.glob("*.net"))  # Read one valid source file for the call.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the call.
            result = ltspice_netlist_to_kicad_sch(  # Call the conversion API without a usable kicad_path setting.
                str(source_path),  # Pass the valid source path.
                str(Path(temporary_directory) / "ignored.kicad_sch"),  # Pass a writable output path.
                {"kicad_path": str(Path(temporary_directory) / "missing_kicad")},  # Pass a kicad_path that does not exist.
            )  # Finish the conversion call.
            self.assertEqual(result, (False, "INVALID_CONVERT_SETTINGS", 0), msg="Missing kicad_path directories must fail with the settings error code.")  # Require the settings error tuple.

    def test_invalid_layout_settings_return_invalid_convert_settings(self) -> None:  # Verify finite positive dimensions and an integral iteration budget.
        source_path = next(_NETLIST_DIRECTORY.glob("*.net"))  # Read one valid source file for each validation call.
        invalid_overrides = (  # Collect representative invalid layout values.
            {"kicad_sch_grid": 0},  # Reject a zero routing resolution.
            {"kicad_sch_page_width": float("nan")},  # Reject a non-finite page dimension.
            {"kicad_sch_page_height": "wide"},  # Reject a non-numeric page dimension.
            {"kicad_placement_iterations": -1},  # Reject a negative iteration budget.
            {"kicad_placement_iterations": 1.5},  # Reject a fractional iteration budget.
        )  # Finish the invalid settings table.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch output directory.
            for overrides in invalid_overrides:  # Exercise every invalid setting independently.
                with self.subTest(overrides=overrides):  # Isolate failures by setting value.
                    settings = dict(_CONVERT_SETTINGS)  # Start from the valid shared settings.
                    settings.update(overrides)  # Apply the invalid override.
                    result = ltspice_netlist_to_kicad_sch(str(source_path), str(Path(temporary_directory) / "ignored.kicad_sch"), settings)  # Run settings validation through the public API.
                    self.assertEqual(result, (False, "INVALID_CONVERT_SETTINGS", 0))  # Require the settings error contract.

    def test_invalid_output_path_returns_invalid_output_path(self) -> None:  # Verify the output path error contract.
        source_path = next(_NETLIST_DIRECTORY.glob("*.net"))  # Read one valid source file for the call.
        result = ltspice_netlist_to_kicad_sch(  # Call the conversion API with a non-path output.
            str(source_path),  # Pass the valid source path.
            12345,  # Pass a non-path-like output value.
            _CONVERT_SETTINGS,  # Pass the shared settings mapping.
        )  # Finish the conversion call.
        self.assertEqual(result, (False, "INVALID_OUTPUT_PATH", 0), msg="Non-path outputs must fail with the output path error code.")  # Require the output path error tuple.

    def test_invalid_netlist_returns_invalid_netlist_file(self) -> None:  # Verify that invalid netlists are rejected before conversion.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the invalid input and output.
            invalid_path = Path(temporary_directory) / "invalid.net"  # Derive the invalid netlist path.
            invalid_path.write_text("R1 a 0 1k\nY1 a b 1k\n.tran 1\n.backanno\n.end\n", encoding="utf-8")  # Write a netlist with an invalid device prefix.
            result = ltspice_netlist_to_kicad_sch(  # Call the conversion API on the invalid netlist.
                str(invalid_path),  # Pass the invalid netlist path.
                str(Path(temporary_directory) / "ignored.kicad_sch"),  # Pass a writable output path.
                _CONVERT_SETTINGS,  # Pass the shared settings mapping.
            )  # Finish the conversion call.
            self.assertEqual(result[0], False, msg="Invalid netlists must fail conversion.")  # Require failure.
            self.assertEqual(result[1], "INVALID_NETLIST_FILE", msg="Invalid netlists must report the netlist error code.")  # Require the netlist error code.
            self.assertGreater(result[2], 0, msg="Netlist failures must report the failing source line.")  # Require a real line number.

    def test_unknown_symbol_returns_unknown_symbol(self) -> None:  # Verify that unresolved devices report the unknown symbol error.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the crafted input and output.
            crafted_path = Path(temporary_directory) / "crafted.net"  # Derive the crafted netlist path.
            crafted_path.write_text(  # Write a valid netlist that references an unresolvable subcircuit.
                "R1 a 0 1k\nXU1 a b MissingSubckt\nR2 b 0 1k\n.tran 1\n.backanno\n.end\n",  # Use two resistors to keep nodes connected.
                encoding="utf-8",  # Write UTF-8 text.
            )  # Finish writing the crafted netlist.
            result = ltspice_netlist_to_kicad_sch(  # Call the conversion API on the crafted netlist.
                str(crafted_path),  # Pass the crafted netlist path.
                str(Path(temporary_directory) / "crafted.kicad_sch"),  # Pass a writable output path.
                _CONVERT_SETTINGS,  # Pass the shared settings mapping.
            )  # Finish the conversion call.
            self.assertEqual(result[0], False, msg="Unresolvable symbols must fail conversion.")  # Require failure.
            self.assertTrue(result[1].startswith("UNKNOWN_SYMBOL"), msg=f"Unresolvable symbols must report UNKNOWN_SYMBOL but returned: {result[1]}")  # Require the symbol error code.
            self.assertGreater(result[2], 0, msg="Symbol failures must report the element source line.")  # Require a real line number.


if __name__ == "__main__":  # Allow running the module directly for debugging.
    unittest.main()  # Execute the unit tests when invoked as a script.
