"""Unit tests for missing-file and permission-error handling."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from unittest import mock  # Patch filesystem calls to exercise error paths reliably.
import unittest  # Use the standard library test framework.

from electronics_design import is_ltspice_netlist_structure_connected  # Import the public connectivity validator.
from electronics_design import is_valid_ltspice_netlist_footer  # Import the public footer validator.
from electronics_design import is_valid_ltspice_netlist_format  # Import the public format validator.


class TestApiErrors(unittest.TestCase):  # Group filesystem error-path tests together.
    def test_missing_file_returns_expected_message(self) -> None:  # Verify that all public validators map missing files consistently.
        for validator in (is_valid_ltspice_netlist_format, is_valid_ltspice_netlist_footer, is_ltspice_netlist_structure_connected):  # Walk every public validator.
            result = validator("does_not_exist.net")  # Execute the validator against a missing path.
            self.assertEqual(result, (False, "File not found!"))  # Assert that the validator returns the required missing-file response.

    @mock.patch("electronics_design.ltspice.os.access", return_value=False)  # Force a read-permission failure after existence succeeds.
    @mock.patch("electronics_design.ltspice.os.path.exists", return_value=True)  # Force the existence check to pass for the mocked path.
    def test_permission_error_returns_expected_message(self, _mock_exists: mock.Mock, _mock_access: mock.Mock) -> None:  # Verify that all public validators map permission failures consistently.
        for validator in (is_valid_ltspice_netlist_format, is_valid_ltspice_netlist_footer, is_ltspice_netlist_structure_connected):  # Walk every public validator.
            result = validator("permission_denied.net")  # Execute the validator against the mocked path.
            self.assertEqual(result, (False, "No permission to read file!"))  # Assert that the validator returns the required permission response.
