"""Unit tests for LTspice symbol-pose resolution."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

import json  # Load generated and expected symbol JSON payloads for exact comparison.
from pathlib import Path  # Use pathlib for robust fixture-path handling.
import tempfile  # Create isolated temporary directories for in-place fixture updates.
import unittest  # Use the standard library test framework.

from electronics_design import ltspice_resolve_symbol_pose  # Import the public symbol-pose helper under test.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_UNRESOLVED_SYMBOL_POSE_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "unresolved_symbol_pose"  # Point to the unresolved symbol-pose fixtures.
_RESOLVED_SYMBOL_POSE_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "resolved_symbol_pose"  # Point to the resolved symbol-pose fixtures.
_CONVERT_SETTINGS = {  # Define the LTspice symbol/library settings passed into the resolver for every test fixture.
    "ltspice_windows_path": "C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
    "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
    "custom_search_paths": ["./valid_asy/"],
}  # Finish the shared conversion settings dictionary.


class TestResolveSymbolPose(unittest.TestCase):  # Group symbol-pose resolution tests together.
    def test_all_symbol_pose_fixtures(self) -> None:  # Resolve every unresolved symbol JSON fixture and compare the in-place result to the paired ground truth.
        unresolved_fixtures = sorted(_UNRESOLVED_SYMBOL_POSE_DIRECTORY.glob("*.json"))  # Collect every unresolved symbol-pose fixture in deterministic order.
        resolved_fixtures = sorted(_RESOLVED_SYMBOL_POSE_DIRECTORY.glob("*.json"))  # Collect every resolved symbol-pose fixture in deterministic order.
        self.assertTrue(unresolved_fixtures, msg="The symbol-pose test suite requires at least one unresolved fixture.")  # Assert that the repository fixture set is present.
        self.assertEqual(
            [fixture.name for fixture in unresolved_fixtures],
            [fixture.name for fixture in resolved_fixtures],
            msg="The unresolved and resolved symbol-pose fixture sets must match one-to-one.",
        )  # Assert that both fixture directories contain the same files.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create an isolated temporary directory for in-place JSON updates.
            for unresolved_fixture_path in unresolved_fixtures:  # Walk every unresolved fixture in deterministic order.
                with self.subTest(fixture=unresolved_fixture_path.name):  # Isolate failures to the specific fixture being resolved.
                    working_fixture_path = Path(temporary_directory) / unresolved_fixture_path.name  # Resolve the temporary in-place working copy path.
                    working_fixture_path.write_text(unresolved_fixture_path.read_text(encoding="utf-8"), encoding="utf-8")  # Copy the unresolved fixture into the temporary directory.
                    expected_resolved_path = _RESOLVED_SYMBOL_POSE_DIRECTORY / unresolved_fixture_path.name  # Resolve the paired ground-truth JSON path.
                    unresolved_symbol_pose = json.loads(unresolved_fixture_path.read_text(encoding="utf-8"))  # Load the original unresolved JSON to verify non-pose fields remain stable.
                    result = ltspice_resolve_symbol_pose(str(working_fixture_path), _CONVERT_SETTINGS)  # Execute the public symbol-pose helper on the temporary working copy.
                    self.assertEqual(result, (True, "OK", 0), msg=f"{unresolved_fixture_path.name} should resolve successfully.")  # Assert that resolution succeeds with the stable success tuple.
                    generated_resolved_symbol_pose = json.loads(working_fixture_path.read_text(encoding="utf-8"))  # Load the in-place resolved JSON into a comparable Python structure.
                    expected_resolved_symbol_pose = json.loads(expected_resolved_path.read_text(encoding="utf-8"))  # Load the paired ground-truth resolved JSON into a comparable Python structure.
                    self.assertEqual(generated_resolved_symbol_pose, expected_resolved_symbol_pose, msg=f"{unresolved_fixture_path.name} should match the paired ground-truth resolved symbol JSON exactly.")  # Assert that the resolved JSON matches the expected payload.
                    for instance_name, unresolved_entry in unresolved_symbol_pose.items():
                        self.assertEqual(generated_resolved_symbol_pose[instance_name]["X"], unresolved_entry["X"], msg=f"{unresolved_fixture_path.name}:{instance_name} should preserve X.")
                        self.assertEqual(generated_resolved_symbol_pose[instance_name]["Y"], unresolved_entry["Y"], msg=f"{unresolved_fixture_path.name}:{instance_name} should preserve Y.")
                        self.assertEqual(generated_resolved_symbol_pose[instance_name]["ORIENTATION"], unresolved_entry["ORIENTATION"], msg=f"{unresolved_fixture_path.name}:{instance_name} should preserve ORIENTATION.")
