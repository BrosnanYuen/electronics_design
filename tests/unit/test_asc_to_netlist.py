"""Unit tests for LTspice ASC-to-netlist conversion."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from pathlib import Path  # Use pathlib for robust fixture-path handling.
import tempfile  # Create isolated temporary directories for generated netlist outputs.
import unittest  # Use the standard library test framework.

from electronics_design import is_valid_ltspice_netlist_file  # Import the public generated-netlist validator.
from electronics_design import ltspice_asc_to_netlist  # Import the public ASC-to-netlist conversion helper.
from electronics_design import ltspice_netlist_footer_cmp  # Import the footer comparison helper used for footer ground-truth checks.
from electronics_design import ltspice_netlist_structure_cmp  # Import the structural comparison helper used for ground-truth checks.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_VALID_ASC_DIRECTORY = _ROOT_DIRECTORY / "valid_convert" / "asc"  # Point to the repository ASC fixtures used for conversion tests.
_VALID_NETLIST_DIRECTORY = _ROOT_DIRECTORY / "valid_convert" / "netlist"  # Point to the ground-truth LTspice netlists for structural comparison.
_CONVERT_SETTINGS = {  # Define the LTspice library settings passed into the converter for every test fixture.
    "ltspice_lib_cmp_path": r"C:\users\brosnan\AppData\Local\LTspice\lib\cmp\\",
    "ltspice_lib_sym_path": r"C:\users\brosnan\AppData\Local\LTspice\lib\sym\\",
}  # Finish the shared conversion settings dictionary.


class TestAscToNetlist(unittest.TestCase):  # Group ASC-to-netlist conversion tests together.
    def test_all_valid_convert_fixtures(self) -> None:  # Convert every repository ASC fixture and compare the result to the paired ground-truth netlist.
        asc_fixtures = sorted(_VALID_ASC_DIRECTORY.glob("*.asc"))  # Collect every ASC conversion fixture in deterministic order.
        self.assertTrue(asc_fixtures, msg="The conversion test suite requires at least one ASC fixture.")  # Assert that the repository fixture set is present.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create an isolated temporary directory for generated netlist outputs.
            for asc_fixture_path in asc_fixtures:  # Walk every ASC conversion fixture in deterministic order.
                with self.subTest(fixture=asc_fixture_path.name):  # Isolate failures to the specific fixture being converted.
                    expected_netlist_path = _VALID_NETLIST_DIRECTORY / f"{asc_fixture_path.stem}.net"  # Resolve the paired ground-truth netlist path.
                    self.assertTrue(expected_netlist_path.exists(), msg=f"Missing paired netlist fixture for {asc_fixture_path.name}.")  # Assert that every ASC fixture has a paired ground-truth netlist.
                    generated_netlist_path = Path(temporary_directory) / f"{asc_fixture_path.stem}.net"  # Resolve the temporary output path for the generated netlist.
                    result = ltspice_asc_to_netlist(str(asc_fixture_path), str(generated_netlist_path), _CONVERT_SETTINGS)  # Execute the public conversion helper on the current ASC fixture.
                    self.assertEqual(result, (True, "OK", 0), msg=f"{asc_fixture_path.name} should convert successfully.")  # Assert that conversion succeeds with the stable success tuple.
                    validation_result = is_valid_ltspice_netlist_file(str(generated_netlist_path))  # Validate the generated netlist through the public whole-file validator.
                    self.assertEqual(validation_result, (True, ""), msg=f"{asc_fixture_path.name} should generate a validator-approved netlist.")  # Assert that the generated netlist passes the public validator.
                    footer_comparison_result = ltspice_netlist_footer_cmp(str(generated_netlist_path), str(expected_netlist_path))  # Compare the generated netlist footer against the repository ground truth.
                    self.assertTrue(footer_comparison_result, msg=f"{asc_fixture_path.name} should match the paired ground-truth netlist footer.")  # Assert that the generated netlist footer matches the expected footer.
                    comparison_result = ltspice_netlist_structure_cmp(str(generated_netlist_path), str(expected_netlist_path))  # Compare the generated netlist against the repository ground truth structurally.
                    self.assertTrue(comparison_result, msg=f"{asc_fixture_path.name} should match the paired ground-truth netlist structurally.")  # Assert that the generated netlist matches the expected structure.
