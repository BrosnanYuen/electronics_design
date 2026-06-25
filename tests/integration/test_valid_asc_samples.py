"""Integration tests that run the public ASC validators on repository schematic samples."""  # Describe the integration-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from pathlib import Path  # Use pathlib for robust path handling.
import unittest  # Use the standard library test framework.

from electronics_design import is_valid_ltspice_asc_file  # Import the public ASC whole-file validator.
from electronics_design import is_valid_ltspice_asc_footer  # Import the public ASC footer validator.
from electronics_design import is_valid_ltspice_asc_header  # Import the public ASC header validator.
from electronics_design import is_valid_ltspice_asc_spacing  # Import the public ASC spacing validator.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_VALID_ASC_DIRECTORY = _ROOT_DIRECTORY / "valid_asc"  # Point to the provided repository schematic samples.


class TestValidAscSamples(unittest.TestCase):  # Group repository ASC integration tests together.
    def test_all_repository_samples_have_valid_header(self) -> None:  # Verify that every provided schematic sample has a valid header.
        for fixture_path in sorted(_VALID_ASC_DIRECTORY.glob("*.asc")):  # Walk every repository ASC sample.
            result = is_valid_ltspice_asc_header(str(fixture_path))  # Execute the header validator on the sample file.
            self.assertTrue(result[0], msg=f"{fixture_path.name} failed header validation: {result[1]}")  # Assert that every repository sample has a valid header.

    def test_all_repository_samples_have_valid_spacing(self) -> None:  # Verify that every provided schematic sample has valid line formatting.
        for fixture_path in sorted(_VALID_ASC_DIRECTORY.glob("*.asc")):  # Walk every repository ASC sample.
            result = is_valid_ltspice_asc_spacing(str(fixture_path))  # Execute the spacing validator on the sample file.
            self.assertTrue(result[0], msg=f"{fixture_path.name} failed spacing validation: {result[1]}")  # Assert that every repository sample has valid spacing.

    def test_all_repository_samples_have_valid_footer(self) -> None:  # Verify that every provided schematic sample contains a valid simulation directive.
        for fixture_path in sorted(_VALID_ASC_DIRECTORY.glob("*.asc")):  # Walk every repository ASC sample.
            result = is_valid_ltspice_asc_footer(str(fixture_path))  # Execute the footer validator on the sample file.
            self.assertTrue(result[0], msg=f"{fixture_path.name} failed footer validation: {result[1]}")  # Assert that every repository sample has valid footer-like directive content.

    def test_all_repository_samples_are_valid_files(self) -> None:  # Verify that every provided schematic sample passes the whole-file ASC validator.
        for fixture_path in sorted(_VALID_ASC_DIRECTORY.glob("*.asc")):  # Walk every repository ASC sample.
            result = is_valid_ltspice_asc_file(str(fixture_path))  # Execute the whole-file validator on the sample file.
            self.assertEqual(result, (True, ""), msg=f"{fixture_path.name} failed whole-file ASC validation.")  # Assert that every repository sample passes whole-file validation.
