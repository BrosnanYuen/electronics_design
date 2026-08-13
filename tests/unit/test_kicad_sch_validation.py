"""Unit tests for full KiCad schematic file validation."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from pathlib import Path  # Use pathlib for clear fixture-path handling.
import unittest  # Use the standard library test framework.

from electronics_design import is_valid_kicad_sch_file  # Import the public KiCad schematic whole-file validator.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_VALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "kicad_sch_validation" / "valid"  # Point to valid schematic whole-file fixtures.
_INVALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "kicad_sch_validation" / "invalid"  # Point to invalid schematic whole-file fixtures.
_EXPECTED_INVALID_RESULTS = {  # Map each invalid fixture file to the exact public error tuple it should produce.
    "invalid_01.kicad_sch": (False, "Header information is invalid! Line 1"),  # Expect the wrong-root fixture to fail on line one.
    "invalid_02.kicad_sch": (False, "Header information is invalid! Line 2"),  # Expect the malformed version fixture to fail on line two.
    "invalid_03.kicad_sch": (False, "Header information is invalid! Line 1"),  # Expect the missing uuid fixture to fail on the root line.
    "invalid_04.kicad_sch": (False, "Line format/spacing is invalid! Line 8"),  # Expect the unclosed root fixture to fail as a spacing problem.
    "invalid_05.kicad_sch": (False, "Line format/spacing is invalid! Line 10"),  # Expect the trailing junk fixture to fail as a spacing problem.
    "invalid_06.kicad_sch": (False, "Footer information is invalid! Line 6"),  # Expect the missing sheet_instances fixture to fail on the final nonblank line.
    "invalid_07.kicad_sch": (False, "Footer information is invalid! Line 7"),  # Expect the malformed path fixture to fail on the path line.
    "invalid_08.kicad_sch": (False, "Footer information is invalid! Line 10"),  # Expect the trailing comment fixture to fail on the final nonblank line.
}  # Finish the invalid-fixture result map.


class TestKicadSchValidation(unittest.TestCase):  # Group KiCad schematic whole-file validation test cases together.
    def test_valid_validation_fixtures(self) -> None:  # Verify that all valid schematic whole-file fixtures pass the public wrapper validator.
        for fixture_path in sorted(_VALID_DIRECTORY.glob("*.kicad_sch")):  # Walk every valid schematic whole-file fixture file.
            result = is_valid_kicad_sch_file(str(fixture_path))  # Execute the whole-file validator on the fixture path.
            self.assertTrue(result[0], msg=f"{fixture_path.name} should be valid but returned: {result[1]}")  # Assert that the fixture validates successfully.
            self.assertEqual(result[1], "", msg=f"{fixture_path.name} should not produce an error message.")  # Assert that successful validation returns an empty message.

    def test_invalid_validation_fixtures(self) -> None:  # Verify that all invalid schematic whole-file fixtures fail with the expected public error tuple.
        for fixture_path in sorted(_INVALID_DIRECTORY.glob("*.kicad_sch")):  # Walk every invalid schematic whole-file fixture file.
            expected_result = _EXPECTED_INVALID_RESULTS[fixture_path.name]  # Look up the exact public error tuple expected for the fixture.
            result = is_valid_kicad_sch_file(str(fixture_path))  # Execute the whole-file validator on the fixture path.
            self.assertEqual(result, expected_result, msg=f"{fixture_path.name} returned an unexpected validation result.")  # Assert that the wrapper returns the expected propagated error tuple.


if __name__ == "__main__":  # Allow running the module directly for debugging.
    unittest.main()  # Execute the unit tests when invoked as a script.
