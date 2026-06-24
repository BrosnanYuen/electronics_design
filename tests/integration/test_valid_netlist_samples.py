"""Integration tests that run the public validators on repository netlists."""  # Describe the integration-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from pathlib import Path  # Use pathlib for robust path handling.
import unittest  # Use the standard library test framework.

from electronics_design import is_ltspice_netlist_structure_connected  # Import the public connectivity validator.
from electronics_design import is_valid_ltspice_netlist_footer  # Import the public footer validator.
from electronics_design import is_valid_ltspice_netlist_format  # Import the public format validator.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_VALID_NETLIST_DIRECTORY = _ROOT_DIRECTORY / "valid_netlist"  # Point to the provided repository sample netlists.

_CONNECTED_SAMPLE_FILES = [  # Select sample netlists that should pass the connectivity rule implemented by this package.
    "AM-modulator-bjt.net",  # Use the prompt-provided connected AM modulator sample.
    "Astable-multivibrator.net",  # Use a connected two-transistor oscillator sample.
    "DC-transfer-function-analysis.net",  # Use a simple resistor-divider transfer-function sample.
    "Example-of-DC-sweep.net",  # Use a simple diode DC sweep sample.
    "How-to-set-initial-conditions.net",  # Use a simple RC initial-condition sample.
    "PNP-transistor-biasing.net",  # Use a simple transistor-bias sample.
    "Transistor-beta.net",  # Use a simple transistor-beta measurement sample.
]  # Finish the selected connectivity sample list.

_FOOTER_SAMPLE_FILES = [  # Select repository netlists that include explicit simulation directives required by the footer API.
    "AM-modulator-bjt.net",  # Use a sample with a valid transient analysis footer.
    "AM-modulator-jfet.net",  # Use a sample with a valid transient analysis footer.
    "Astable-multivibrator.net",  # Use a sample with a valid transient analysis footer.
    "Current-mirrors.net",  # Use a sample with a valid DC sweep footer.
    "DC-transfer-function-analysis.net",  # Use a sample with a valid transfer-function footer.
    "Example-of-DC-sweep.net",  # Use a sample with a valid DC sweep footer.
    "How-to-set-initial-conditions.net",  # Use a sample with a valid transient analysis footer.
    "Royer-zvs.net",  # Use a sample with a valid transient analysis footer.
    "Transistor-beta.net",  # Use a sample with a valid operating-point footer.
    "current-limiting-npn.net",  # Use a sample with a valid stepped transient footer.
]  # Finish the selected footer sample list.


class TestValidNetlistSamples(unittest.TestCase):  # Group repository integration tests together.
    def test_all_repository_samples_have_valid_format(self) -> None:  # Verify that every provided sample netlist has valid line formatting.
        for fixture_path in sorted(_VALID_NETLIST_DIRECTORY.glob("*.net")):  # Walk every repository sample netlist.
            result = is_valid_ltspice_netlist_format(str(fixture_path))  # Execute the format validator on the sample file.
            self.assertTrue(result[0], msg=f"{fixture_path.name} failed format validation: {result[1]}")  # Assert that every repository sample has valid formatting.

    def test_selected_repository_samples_have_valid_footer(self) -> None:  # Verify that repository samples with simulation directives have valid footers.
        for filename in _FOOTER_SAMPLE_FILES:  # Walk the curated list of repository netlists with explicit simulation directives.
            fixture_path = _VALID_NETLIST_DIRECTORY / filename  # Build the full path to the sample file.
            result = is_valid_ltspice_netlist_footer(str(fixture_path))  # Execute the footer validator on the sample file.
            self.assertTrue(result[0], msg=f"{fixture_path.name} failed footer validation: {result[1]}")  # Assert that each selected repository sample has a valid footer.

    def test_selected_repository_samples_are_connected(self) -> None:  # Verify that selected provided sample netlists pass the connectivity rule.
        for filename in _CONNECTED_SAMPLE_FILES:  # Walk the curated list of connected repository netlists.
            fixture_path = _VALID_NETLIST_DIRECTORY / filename  # Build the full path to the sample file.
            result = is_ltspice_netlist_structure_connected(str(fixture_path))  # Execute the connectivity validator on the sample file.
            self.assertTrue(result[0], msg=f"{fixture_path.name} failed connectivity validation: {result[1]}")  # Assert that the curated sample passes connectivity validation.
