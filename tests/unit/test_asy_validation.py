"""Unit tests for LTspice ASY validation."""

from __future__ import annotations

from pathlib import Path
import unittest

from electronics_design import is_valid_ltspice_asy

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_VALID_DIRECTORY = _ROOT_DIRECTORY / "valid_asy"


class TestAsyValidation(unittest.TestCase):
    def test_all_repository_valid_asy_files(self) -> None:
        fixture_paths = sorted(_VALID_DIRECTORY.glob("*.asy"))
        self.assertTrue(fixture_paths, msg="The ASY validation tests require at least one fixture.")
        for fixture_path in fixture_paths:
            with self.subTest(fixture=fixture_path.name):
                result = is_valid_ltspice_asy(str(fixture_path))
                self.assertEqual(result, (True, ""), msg=f"{fixture_path.name} should be a valid LTspice ASY file.")
