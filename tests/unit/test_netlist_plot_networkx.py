"""Unit tests for networkx-based LTspice graph plotting."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from pathlib import Path  # Use pathlib for clear fixture-path handling.
import struct  # Decode the PNG IHDR dimensions from the generated output file.
import tempfile  # Create isolated temporary directories for generated PNG outputs.
import unittest  # Use the standard library test framework.

from electronics_design import ltspice_netlist_plot_networkx  # Import the public networkx plotting helper.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_VALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "netlist_validation" / "valid"  # Reuse the valid whole-file fixtures as plotting inputs.


class TestNetlistPlotNetworkx(unittest.TestCase):  # Group networkx plotting test cases together.
    def _assert_valid_png_output(self, fixture_name: str, expected_width: int = 1920, expected_height: int = 1080) -> None:  # Generate one PNG output and verify that the renderer produced a valid PNG file.
        fixture_path = _VALID_DIRECTORY / fixture_name  # Resolve the source LTspice netlist fixture to render.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create an isolated temporary output directory for the PNG file.
            output_path = Path(temporary_directory) / f"{fixture_path.stem}.png"  # Resolve the PNG output path inside the temporary directory.
            result = ltspice_netlist_plot_networkx(str(fixture_path), str(output_path), expected_width, expected_height)  # Execute the public networkx plotting helper on the fixture using the requested dimensions.
            self.assertEqual(result, (True, ""), msg=f"{fixture_name} should render successfully.")  # Assert that plotting succeeds without an error message.
            self.assertTrue(output_path.exists(), msg=f"{fixture_name} should create a PNG output file.")  # Assert that the output file is created on disk.
            png_bytes = output_path.read_bytes()  # Read the rendered PNG file bytes for structural validation.
            self.assertGreater(len(png_bytes), 64, msg=f"{fixture_name} should produce a non-trivial PNG payload.")  # Assert that the PNG file is not suspiciously small.
            self.assertEqual(png_bytes[:8], b"\x89PNG\r\n\x1a\n", msg=f"{fixture_name} should begin with the PNG file signature.")  # Assert that the file begins with the fixed PNG signature.
            self.assertEqual(png_bytes[12:16], b"IHDR", msg=f"{fixture_name} should contain an IHDR chunk immediately after the PNG signature.")  # Assert that the first PNG chunk is the required IHDR chunk.
            width, height = struct.unpack("!II", png_bytes[16:24])  # Decode the encoded image dimensions from the IHDR payload.
            self.assertEqual(width, expected_width, msg=f"{fixture_name} should encode the requested PNG width.")  # Assert that the PNG width matches the requested output width.
            self.assertEqual(height, expected_height, msg=f"{fixture_name} should encode the requested PNG height.")  # Assert that the PNG height matches the requested output height.
            self.assertEqual(png_bytes[-8:-4], b"IEND", msg=f"{fixture_name} should terminate with the PNG IEND chunk.")  # Assert that the PNG stream ends with the required IEND chunk.

    def test_plot_fixture_uses_default_dimensions(self) -> None:  # Verify that the plotting API still defaults to the documented 1920x1080 output size.
        fixture_path = _VALID_DIRECTORY / "valid_01.net"  # Reuse one valid whole-file fixture as the plotting input.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create an isolated temporary output directory for the PNG file.
            output_path = Path(temporary_directory) / "default_dimensions.png"  # Resolve the PNG output path inside the temporary directory.
            result = ltspice_netlist_plot_networkx(str(fixture_path), str(output_path))  # Execute the public plotting helper without overriding dimensions.
            self.assertEqual(result, (True, ""), msg="The plotting API should render successfully with default dimensions.")  # Assert that plotting succeeds with the default arguments.
            png_bytes = output_path.read_bytes()  # Read the rendered PNG bytes so the encoded dimensions can be verified.
            width, height = struct.unpack("!II", png_bytes[16:24])  # Decode the encoded image dimensions from the IHDR payload.
            self.assertEqual((width, height), (1920, 1080), msg="The plotting API should default to a 1920x1080 PNG output.")  # Assert that the documented defaults remain stable.

    def test_plot_fixture_accepts_custom_dimensions(self) -> None:  # Verify that the plotting API writes caller-specified image dimensions into the PNG output.
        self._assert_valid_png_output("valid_02.net", expected_width=1280, expected_height=720)  # Render one fixture using a non-default image size.


def _make_plot_test(fixture_name: str):  # Build one dynamic plotting test method for one valid fixture file.
    def _test_method(self: TestNetlistPlotNetworkx) -> None:  # Execute the shared PNG assertions for the selected fixture.
        self._assert_valid_png_output(fixture_name)  # Render and validate the PNG output for the selected fixture file.

    return _test_method  # Return the generated unittest method for later class attachment.


for _fixture_number in range(1, 11):  # Generate one explicit plotting unit test for each of the ten valid whole-file fixtures.
    _fixture_name = f"valid_{_fixture_number:02d}.net"  # Build the fixture filename for the current dynamic plotting test.
    _test_name = f"test_plot_fixture_{_fixture_number:02d}"  # Build the unittest method name for the current fixture.
    setattr(TestNetlistPlotNetworkx, _test_name, _make_plot_test(_fixture_name))  # Attach the generated unittest method to the plotting test class.
