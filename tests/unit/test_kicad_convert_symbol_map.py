"""Unit tests for the LTspice ASY to KiCad symbol conversion API."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from pathlib import Path  # Use pathlib for clear path handling.
import tempfile  # Use a temporary directory so tests never modify checked-in symbol files.
import unittest  # Use the standard library test framework.

from electronics_design import is_valid_kicad_symbol_file  # Import the KiCad symbol library whole-file validator.
from electronics_design import ltspice_asy_to_kicad_symbol  # Import the ASY to KiCad symbol conversion API.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_ASY_DIRECTORY = _ROOT_DIRECTORY / "kicad_convert" / "asy"  # Point at the copied LTspice symbol files.
_KICAD_SYMBOL_DIRECTORY = _ROOT_DIRECTORY / "kicad_convert" / "kicad_symbol"  # Point at the checked-in KiCad symbol files.

_CONVERT_SETTINGS = {  # Pin the settings so generated files are reproducible.
    "kicad_symbol_version": "20251024",  # Use a fixed eight-digit KiCad format version.
    "kicad_symbol_generator": "electronics_design",  # Name the generator explicitly.
}  # Finish the conversion settings dictionary.


class TestLtspiceAsyToKicadSymbol(unittest.TestCase):  # Group the ASY-to-KiCad-symbol conversion tests together.
    def test_all_asy_files_convert_to_valid_kicad_symbols(self) -> None:  # Verify every copied ASY file converts and validates.
        asy_files = sorted(_ASY_DIRECTORY.glob("*.asy"))  # Collect all LTspice symbol files in the fixture directory.
        self.assertGreater(len(asy_files), 0, msg="kicad_convert/asy/ must contain LTspice symbol files.")  # Require the source files to exist.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the generated files.
            for asy_path in asy_files:  # Walk every LTspice symbol file.
                with self.subTest(symbol=asy_path.name):  # Isolate failures per symbol file.
                    output_path = Path(temporary_directory) / f"{asy_path.stem}.kicad_sym"  # Derive the scratch KiCad symbol path.
                    result = ltspice_asy_to_kicad_symbol(str(asy_path), str(output_path), _CONVERT_SETTINGS)  # Run the public conversion API.
                    self.assertEqual(  # Require the conversion to succeed with the standard success tuple.
                        result,  # Compare the returned conversion result.
                        (True, "OK", 0),  # Expect success, the OK message, and line zero.
                        msg=f"{asy_path.name} should convert but returned: {result}",  # Report the failure with the returned tuple.
                    )  # Finish the conversion assertion.
                    validation = is_valid_kicad_symbol_file(str(output_path))  # Validate the freshly generated KiCad symbol file.
                    self.assertEqual(  # Require the generated file to pass the symbol validator.
                        validation,  # Compare the returned validation result.
                        (True, ""),  # Expect success with an empty message.
                        msg=f"{output_path.name} should be valid but returned: {validation[1]}",  # Report the failure with the returned message.
                    )  # Finish the validation assertion.

    def test_symbol_map_is_one_to_one(self) -> None:  # Verify that every component name maps one LTspice file to one KiCad file.
        asy_stems = {path.stem for path in _ASY_DIRECTORY.glob("*.asy")}  # Collect the LTspice symbol file stems.
        kicad_stems = {path.stem for path in _KICAD_SYMBOL_DIRECTORY.glob("*.kicad_sym")}  # Collect the KiCad symbol file stems.
        self.assertGreater(len(asy_stems), 0, msg="kicad_convert/asy/ must contain LTspice symbol files.")  # Require the source files to exist.
        self.assertEqual(asy_stems, kicad_stems, msg="Every .asy file must have exactly one matching .kicad_sym file and vice versa.")  # Assert a strict one-to-one name mapping.

    def test_missing_input_returns_invalid_asy_file(self) -> None:  # Verify the missing input error contract.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the call.
            result = ltspice_asy_to_kicad_symbol(  # Call the conversion API with a nonexistent input.
                str(_ASY_DIRECTORY / "does_not_exist.asy"),  # Use a path that cannot exist.
                str(Path(temporary_directory) / "does_not_exist.kicad_sym"),  # Use a writable output path.
                _CONVERT_SETTINGS,  # Pass the shared settings mapping.
            )  # Finish the conversion call.
            self.assertEqual(result[0], False, msg="Missing input files must fail conversion.")  # Require failure.
            self.assertEqual(result[1], "INVALID_ASY_FILE", msg="Missing input files must report the ASY error code.")  # Require the ASY error code.
            self.assertEqual(result[2], 0, msg="Path failures must report line zero.")  # Require the unknown line number.

    def test_invalid_settings_return_invalid_convert_settings(self) -> None:  # Verify the settings validation error contract.
        source_path = next(_ASY_DIRECTORY.glob("*.asy"))  # Read one valid source file for the call.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the call.
            result = ltspice_asy_to_kicad_symbol(  # Call the conversion API with invalid settings.
                str(source_path),  # Pass the valid source path.
                str(Path(temporary_directory) / "ignored.kicad_sym"),  # Pass a writable output path.
                "not a mapping",  # Pass a non-mapping settings value.
            )  # Finish the conversion call.
            self.assertEqual(result, (False, "INVALID_CONVERT_SETTINGS", 0), msg="Non-mapping settings must fail with the settings error code.")  # Require the settings error tuple.

    def test_invalid_output_path_returns_invalid_output_path(self) -> None:  # Verify the output path error contract.
        source_path = next(_ASY_DIRECTORY.glob("*.asy"))  # Read one valid source file for the call.
        result = ltspice_asy_to_kicad_symbol(  # Call the conversion API with a non-path output.
            str(source_path),  # Pass the valid source path.
            12345,  # Pass a non-path-like output value.
            _CONVERT_SETTINGS,  # Pass the shared settings mapping.
        )  # Finish the conversion call.
        self.assertEqual(result, (False, "INVALID_OUTPUT_PATH", 0), msg="Non-path outputs must fail with the output path error code.")  # Require the output path error tuple.


if __name__ == "__main__":  # Allow running the module directly for debugging.
    unittest.main()  # Execute the unit tests when invoked as a script.
