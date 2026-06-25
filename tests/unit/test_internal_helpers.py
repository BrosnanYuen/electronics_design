"""Unit tests for selected internal LTspice helper functions."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

import unittest  # Use the standard library test framework.

from electronics_design import ltspice  # Import the internal helper module for focused unit coverage.


class TestInternalHelpers(unittest.TestCase):  # Group internal-helper tests together.
    def test_classify_asc_line_accepts_version_keyword(self) -> None:  # Verify ASC keyword classification accepts the Version header record.
        result = ltspice._classify_asc_line("Version 4")  # Classify a standard ASC Version header line.
        self.assertEqual(result, (True, "VERSION"))  # Assert that the Version line is classified correctly.

    def test_strip_semicolon_comment(self) -> None:  # Verify inline semicolon comments are removed cleanly.
        result = ltspice._strip_semicolon_comment("R1 in out 1k ; resistor comment")  # Strip a line with an inline semicolon comment.
        self.assertEqual(result, "R1 in out 1k ")  # Assert that only the code portion remains.

    def test_parse_directive_name_accepts_valid_keyword(self) -> None:  # Verify valid directive parsing succeeds.
        result = ltspice._parse_directive_name(".tran 10m")  # Parse a valid transient directive.
        self.assertEqual(result, (True, "tran", ""))  # Assert that the directive name is parsed correctly.

    def test_parse_directive_name_rejects_merged_keyword(self) -> None:  # Verify merged directive spellings are rejected.
        result = ltspice._parse_directive_name(".tran10m")  # Parse an invalid merged directive token.
        self.assertEqual(result[0], False)  # Assert that the directive parse fails.

    def test_extract_nodes_for_subcircuit(self) -> None:  # Verify variable-width subcircuit node extraction works.
        result = ltspice._extract_nodes(["XU1", "IN", "OUT", "0", "AMP", "GAIN=10"])  # Extract nodes from a subcircuit line with parameters.
        self.assertEqual(result, (True, ["IN", "OUT", "0"]))  # Assert that only the connectivity nodes are returned.

    def test_extract_asc_text_directive(self) -> None:  # Verify directives carried by ASC TEXT records are extracted cleanly.
        result = ltspice._extract_asc_text_directive("TEXT 0 0 Left 2 !.tran 10m")  # Extract a transient directive from a TEXT record.
        self.assertEqual(result, (True, ".tran 10m"))  # Assert that the embedded directive payload is returned.

    def test_extract_asc_text_directive_ignores_plain_comment_text(self) -> None:  # Verify plain ASC annotation text is not treated as a directive.
        result = ltspice._extract_asc_text_directive("TEXT 0 0 Left 2 ;plain comment")  # Inspect a non-directive annotation record.
        self.assertEqual(result, (True, ""))  # Assert that the annotation is ignored as expected.

    def test_is_exempt_node(self) -> None:  # Verify ground and explicit no-connect nodes are exempt.
        self.assertTrue(ltspice._is_exempt_node("0"))  # Assert that numeric ground is exempt.
        self.assertTrue(ltspice._is_exempt_node("GND"))  # Assert that textual ground is exempt.
        self.assertTrue(ltspice._is_exempt_node("NC_01"))  # Assert that explicit no-connect labels are exempt.
        self.assertFalse(ltspice._is_exempt_node("N001"))  # Assert that ordinary nodes are not exempt.
