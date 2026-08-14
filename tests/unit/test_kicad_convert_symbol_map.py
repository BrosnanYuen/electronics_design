"""Unit tests for the generated LTspice-to-KiCad symbol map files."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from pathlib import Path  # Use pathlib for clear path handling.
import unittest  # Use the standard library test framework.

from electronics_design import is_valid_kicad_symbol_file  # Import the public KiCad symbol library whole-file validator.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_ASY_DIRECTORY = _ROOT_DIRECTORY / "kicad_convert" / "asy"  # Point at the copied LTspice symbol files.
_KICAD_SYMBOL_DIRECTORY = _ROOT_DIRECTORY / "kicad_convert" / "kicad_symbol"  # Point at the split KiCad symbol files.


class TestKicadConvertSymbolMap(unittest.TestCase):  # Group the generated symbol-map file tests together.
    def test_kicad_symbol_files_valid(self) -> None:  # Verify every split KiCad symbol file passes the public validator.
        symbol_files = sorted(_KICAD_SYMBOL_DIRECTORY.glob("*.kicad_sym"))  # Collect all split symbol library files.
        self.assertGreater(len(symbol_files), 0, msg="kicad_convert/kicad_symbol/ must contain generated symbol files.")  # Require the generated files to exist.
        for symbol_path in symbol_files:  # Walk every generated symbol library file.
            result = is_valid_kicad_symbol_file(str(symbol_path))  # Execute the whole-file validator on the generated file.
            self.assertTrue(result[0], msg=f"{symbol_path.name} should be valid but returned: {result[1]}")  # Assert that the file validates successfully.
            self.assertEqual(result[1], "", msg=f"{symbol_path.name} should not produce an error message.")  # Assert that success returns an empty message.

    def test_symbol_map_is_one_to_one(self) -> None:  # Verify that every component name maps one LTspice file to one KiCad file.
        asy_stems = {path.stem for path in _ASY_DIRECTORY.glob("*.asy")}  # Collect the LTspice symbol file stems.
        kicad_stems = {path.stem for path in _KICAD_SYMBOL_DIRECTORY.glob("*.kicad_sym")}  # Collect the KiCad symbol file stems.
        self.assertGreater(len(asy_stems), 0, msg="kicad_convert/asy/ must contain generated symbol files.")  # Require the copied LTspice files to exist.
        self.assertEqual(asy_stems, kicad_stems, msg="Every .asy file must have exactly one matching .kicad_sym file and vice versa.")  # Assert a strict one-to-one name mapping.


if __name__ == "__main__":  # Allow running the module directly for debugging.
    unittest.main()  # Execute the unit tests when invoked as a script.
