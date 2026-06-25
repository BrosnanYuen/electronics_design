"""Unit tests for missing-file and permission-error handling."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from unittest import mock  # Patch filesystem calls to exercise error paths reliably.
import unittest  # Use the standard library test framework.

from electronics_design import is_ltspice_netlist_structure_connected  # Import the public connectivity validator.
from electronics_design import is_valid_ltspice_netlist_file  # Import the public whole-file validator.
from electronics_design import is_valid_ltspice_netlist_footer  # Import the public footer validator.
from electronics_design import is_valid_ltspice_netlist_format  # Import the public format validator.
from electronics_design import ltspice_netlist_plot_networkx  # Import the public networkx plotting helper.
from electronics_design import ltspice_netlist_structure_cmp  # Import the public structural comparison helper.


class TestApiErrors(unittest.TestCase):  # Group filesystem error-path tests together.
    def test_missing_file_returns_expected_message(self) -> None:  # Verify that all public validators map missing files consistently.
        for validator in (is_valid_ltspice_netlist_format, is_valid_ltspice_netlist_footer, is_ltspice_netlist_structure_connected, is_valid_ltspice_netlist_file):  # Walk every public validator that returns the shared tuple contract.
            result = validator("does_not_exist.net")  # Execute the validator against a missing path.
            self.assertEqual(result, (False, "File not found!"))  # Assert that the validator returns the required missing-file response.
        plot_result = ltspice_netlist_plot_networkx("does_not_exist.net", "graph.png")  # Execute the plotting helper against a missing source path.
        self.assertEqual(plot_result, (False, "File not found!"))  # Assert that the plotting helper returns the same missing-file response.
        compare_result = ltspice_netlist_structure_cmp("does_not_exist.net", "does_not_exist_too.net")  # Execute the comparison helper against missing source paths.
        self.assertFalse(compare_result)  # Assert that the comparison helper returns False when validation cannot proceed.

    @mock.patch("electronics_design.ltspice.os.access", return_value=False)  # Force a read-permission failure after existence succeeds.
    @mock.patch("electronics_design.ltspice.os.path.exists", return_value=True)  # Force the existence check to pass for the mocked path.
    def test_permission_error_returns_expected_message(self, _mock_exists: mock.Mock, _mock_access: mock.Mock) -> None:  # Verify that all public validators map permission failures consistently.
        for validator in (is_valid_ltspice_netlist_format, is_valid_ltspice_netlist_footer, is_ltspice_netlist_structure_connected, is_valid_ltspice_netlist_file):  # Walk every public validator that returns the shared tuple contract.
            result = validator("permission_denied.net")  # Execute the validator against the mocked path.
            self.assertEqual(result, (False, "No permission to read file!"))  # Assert that the validator returns the required permission response.
        plot_result = ltspice_netlist_plot_networkx("permission_denied.net", "graph.png")  # Execute the plotting helper against the mocked unreadable path.
        self.assertEqual(plot_result, (False, "No permission to read file!"))  # Assert that the plotting helper returns the same permission response.
        compare_result = ltspice_netlist_structure_cmp("permission_denied.net", "permission_denied_2.net")  # Execute the comparison helper against mocked unreadable paths.
        self.assertFalse(compare_result)  # Assert that the comparison helper returns False when validation cannot proceed.
