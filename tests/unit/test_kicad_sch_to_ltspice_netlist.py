"""Unit tests for the KiCad schematic to LTspice netlist conversion API."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

import os  # Read the optional KiCad path environment override.
from pathlib import Path  # Use pathlib for clear path handling.
import tempfile  # Use a temporary directory so tests never modify checked-in netlist files.
import unittest  # Use the standard library test framework.

from electronics_design import is_valid_ltspice_netlist_file  # Import the LTspice netlist whole-file validator.
from electronics_design import kicad_sch_to_ltspice_netlist  # Import the KiCad schematic to LTspice netlist conversion API.
from electronics_design import ltspice_netlist_structure_cmp  # Import the LTspice netlist structural comparison helper.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_KICAD_SCH_DIRECTORY = _ROOT_DIRECTORY / "kicad_convert" / "kicad_sch"  # Point at the checked-in KiCad schematic files.
_NETLIST_DIRECTORY = _ROOT_DIRECTORY / "kicad_convert" / "netlist"  # Point at the checked-in ground-truth netlist files.

_KICAD_PATH = os.environ.get("ELECTRONICS_DESIGN_KICAD_PATH", "/usr/share/kicad")  # Resolve the KiCad library path with an optional environment override.

_CONVERT_SETTINGS = {  # Pin the settings so generated files are reproducible.
    "kicad_path": _KICAD_PATH,  # Look symbols up from the configured KiCad installation path.
}  # Finish the conversion settings dictionary.


class TestKicadSchToLtspiceNetlist(unittest.TestCase):  # Group the KiCad schematic to LTspice netlist conversion tests together.
    def test_all_kicad_schematics_convert_and_match_ground_truth(self) -> None:  # Verify every schematic converts to a valid netlist matching the ground truth.
        sch_files = sorted(_KICAD_SCH_DIRECTORY.glob("*.kicad_sch"))  # Collect all KiCad schematic files in the fixture directory.
        self.assertGreater(len(sch_files), 0, msg="kicad_convert/kicad_sch/ must contain KiCad schematic files.")  # Require the source files to exist.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the generated files.
            for sch_path in sch_files:  # Walk every KiCad schematic file.
                with self.subTest(schematic=sch_path.name):  # Isolate failures per schematic file.
                    output_path = Path(temporary_directory) / f"{sch_path.stem}.net"  # Derive the scratch LTspice netlist path.
                    result = kicad_sch_to_ltspice_netlist(str(sch_path), str(output_path), _CONVERT_SETTINGS)  # Run the public conversion API.
                    self.assertEqual(  # Require the conversion to succeed with the standard success tuple.
                        result,  # Compare the returned conversion result.
                        (True, "OK", 0),  # Expect success, the OK message, and line zero.
                        msg=f"{sch_path.name} should convert but returned: {result}",  # Report the failure with the returned tuple.
                    )  # Finish the conversion assertion.
                    validation = is_valid_ltspice_netlist_file(str(output_path))  # Validate the freshly generated netlist file.
                    self.assertEqual(  # Require the generated file to pass the whole-file netlist validator.
                        validation,  # Compare the returned validation result.
                        (True, ""),  # Expect success with an empty message.
                        msg=f"{output_path.name} should be valid but returned: {validation[1]}",  # Report the failure with the returned message.
                    )  # Finish the validation assertion.
                    ground_truth_path = _NETLIST_DIRECTORY / f"{sch_path.stem}.net"  # Resolve the checked-in ground-truth netlist file.
                    self.assertTrue(ground_truth_path.is_file(), msg=f"Missing ground truth {ground_truth_path.name}.")  # Require the ground-truth file to exist.
                    structure_matches = ltspice_netlist_structure_cmp(str(output_path), str(ground_truth_path))  # Compare the generated structure to the ground truth.
                    self.assertTrue(  # Require the generated netlist to be structurally equivalent to the ground truth.
                        structure_matches,  # Check the structural comparison result.
                        msg=f"{output_path.name} must match {ground_truth_path.name} structurally.",  # Report the structural mismatch.
                    )  # Finish the structural assertion.

    def test_missing_input_returns_invalid_kicad_sch_file(self) -> None:  # Verify the missing input error contract.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the call.
            result = kicad_sch_to_ltspice_netlist(  # Call the conversion API with a nonexistent input.
                str(_KICAD_SCH_DIRECTORY / "does_not_exist.kicad_sch"),  # Use a path that cannot exist.
                str(Path(temporary_directory) / "does_not_exist.net"),  # Use a writable output path.
                _CONVERT_SETTINGS,  # Pass the shared settings mapping.
            )  # Finish the conversion call.
            self.assertEqual(result[0], False, msg="Missing input files must fail conversion.")  # Require failure.
            self.assertEqual(result[1], "INVALID_KICAD_SCH_FILE", msg="Missing input files must report the schematic error code.")  # Require the schematic error code.
            self.assertEqual(result[2], 0, msg="Path failures must report line zero.")  # Require the unknown line number.

    def test_invalid_settings_return_invalid_convert_settings(self) -> None:  # Verify the settings validation error contract.
        source_path = next(_KICAD_SCH_DIRECTORY.glob("*.kicad_sch"))  # Read one valid source file for the call.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the call.
            result = kicad_sch_to_ltspice_netlist(  # Call the conversion API with invalid settings.
                str(source_path),  # Pass the valid source path.
                str(Path(temporary_directory) / "ignored.net"),  # Pass a writable output path.
                "not a mapping",  # Pass a non-mapping settings value.
            )  # Finish the conversion call.
            self.assertEqual(result, (False, "INVALID_CONVERT_SETTINGS", 0), msg="Non-mapping settings must fail with the settings error code.")  # Require the settings error tuple.

    def test_missing_kicad_path_returns_invalid_convert_settings(self) -> None:  # Verify that a missing kicad_path setting is rejected.
        source_path = next(_KICAD_SCH_DIRECTORY.glob("*.kicad_sch"))  # Read one valid source file for the call.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the call.
            result = kicad_sch_to_ltspice_netlist(  # Call the conversion API without the kicad_path setting.
                str(source_path),  # Pass the valid source path.
                str(Path(temporary_directory) / "ignored.net"),  # Pass a writable output path.
                {"kicad_path": str(Path(temporary_directory) / "missing_kicad")},  # Pass a kicad_path that does not exist.
            )  # Finish the conversion call.
            self.assertEqual(result, (False, "INVALID_CONVERT_SETTINGS", 0), msg="Missing kicad_path directories must fail with the settings error code.")  # Require the settings error tuple.

    def test_invalid_output_path_returns_invalid_output_path(self) -> None:  # Verify the output path error contract.
        source_path = next(_KICAD_SCH_DIRECTORY.glob("*.kicad_sch"))  # Read one valid source file for the call.
        result = kicad_sch_to_ltspice_netlist(  # Call the conversion API with a non-path output.
            str(source_path),  # Pass the valid source path.
            12345,  # Pass a non-path-like output value.
            _CONVERT_SETTINGS,  # Pass the shared settings mapping.
        )  # Finish the conversion call.
        self.assertEqual(result, (False, "INVALID_OUTPUT_PATH", 0), msg="Non-path outputs must fail with the output path error code.")  # Require the output path error tuple.

    def test_unknown_symbol_returns_unknown_kicad_symbol(self) -> None:  # Verify that unresolved symbols report the unknown symbol error.
        source_path = next(_KICAD_SCH_DIRECTORY.glob("*.kicad_sch"))  # Read one valid source file for the call.
        source_text = source_path.read_text(encoding="utf-8")  # Read the schematic text.
        tampered_text = source_text.replace('(lib_id "Device:R")', '(lib_id "NonexistentLibrary:R")')  # Break every resistor instance library reference.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the tampered input and output.
            tampered_path = Path(temporary_directory) / "tampered.kicad_sch"  # Derive the tampered schematic path.
            tampered_path.write_text(tampered_text, encoding="utf-8")  # Write the tampered schematic.
            result = kicad_sch_to_ltspice_netlist(  # Call the conversion API on the tampered schematic.
                str(tampered_path),  # Pass the tampered schematic path.
                str(Path(temporary_directory) / "tampered.net"),  # Pass a writable output path.
                _CONVERT_SETTINGS,  # Pass the shared settings mapping.
            )  # Finish the conversion call.
            self.assertEqual(result[0], False, msg="Unresolvable symbols must fail conversion.")  # Require failure.
            self.assertTrue(result[1].startswith("UNKNOWN_KICAD_SYMBOL"), msg=f"Unresolvable symbols must report UNKNOWN_KICAD_SYMBOL but returned: {result[1]}")  # Require the symbol error code.
            self.assertGreater(result[2], 0, msg="Symbol failures must report the instance source line.")  # Require a real line number.


if __name__ == "__main__":  # Allow running the module directly for debugging.
    unittest.main()  # Execute the unit tests when invoked as a script.
