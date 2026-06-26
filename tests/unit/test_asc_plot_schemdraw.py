"""Unit tests for schemdraw-based LTspice ASC plotting."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from pathlib import Path  # Use pathlib for clear fixture-path handling.
import tempfile  # Create isolated temporary directories for generated outputs.
import unittest  # Use the standard library test framework.
import xml.etree.ElementTree as ElementTree  # Inspect generated SVG metadata safely.

from PIL import Image  # Inspect generated raster dimensions through Pillow.

from electronics_design import ltspice_asc_plot_schemdraw  # Import the public schemdraw plotting helper.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_VALID_DIRECTORY = _ROOT_DIRECTORY / "valid_asc"  # Reuse repository ASC samples as plotting inputs.


class TestAscPlotSchemdraw(unittest.TestCase):  # Group schemdraw plotting test cases together.
    def _assert_valid_png_output(self, fixture_name: str, expected_width: int = 1920, expected_height: int = 1080) -> None:  # Render one ASC fixture to PNG and verify that a readable raster image is produced.
        fixture_path = _VALID_DIRECTORY / fixture_name  # Resolve the source LTspice ASC fixture to render.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create an isolated temporary output directory for the PNG file.
            output_path = Path(temporary_directory) / f"{fixture_path.stem}.png"  # Resolve the PNG output path inside the temporary directory.
            result = ltspice_asc_plot_schemdraw(str(fixture_path), str(output_path), expected_width, expected_height)  # Execute the public schemdraw plotting helper using the requested dimensions.
            self.assertEqual(result, (True, ""), msg=f"{fixture_name} should render successfully.")  # Assert that plotting succeeds without an error message.
            self.assertTrue(output_path.exists(), msg=f"{fixture_name} should create a PNG output file.")  # Assert that the output file is created on disk.
            self.assertGreater(output_path.stat().st_size, 0, msg=f"{fixture_name} should produce a non-empty PNG file.")  # Assert that the output file contains image data.
            with Image.open(output_path) as image:  # Open the rendered PNG so its encoded dimensions and file format can be verified.
                self.assertEqual(image.format, "PNG", msg=f"{fixture_name} should be encoded as a PNG file.")  # Assert that the raster file format matches the requested extension.
                self.assertEqual(image.size, (expected_width, expected_height), msg=f"{fixture_name} should match the requested PNG dimensions.")  # Assert that the PNG size matches the caller request.

    def test_plot_fixture_uses_default_dimensions(self) -> None:  # Verify that the schemdraw plotting API defaults to the documented 1920x1080 size.
        fixture_path = _VALID_DIRECTORY / "How-to-set-initial-conditions.asc"  # Reuse one compact valid ASC sample as the plotting input.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create an isolated temporary output directory for the PNG file.
            output_path = Path(temporary_directory) / "default_dimensions.png"  # Resolve the PNG output path inside the temporary directory.
            result = ltspice_asc_plot_schemdraw(str(fixture_path), str(output_path))  # Execute the public schemdraw plotting helper with default dimensions.
            self.assertEqual(result, (True, ""), msg="The schemdraw plotting API should render successfully with default dimensions.")  # Assert that plotting succeeds with the default arguments.
            with Image.open(output_path) as image:  # Open the rendered PNG so its encoded dimensions can be verified.
                self.assertEqual(image.size, (1920, 1080), msg="The schemdraw plotting API should default to a 1920x1080 raster output.")  # Assert that the documented defaults remain stable.

    def test_plot_fixture_accepts_custom_png_dimensions(self) -> None:  # Verify that the schemdraw plotting API writes caller-specified PNG dimensions.
        fixture_path = _VALID_DIRECTORY / "DC-transfer-function-analysis.asc"  # Reuse one valid ASC sample as the plotting input.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create an isolated temporary output directory for the PNG file.
            output_path = Path(temporary_directory) / "custom_dimensions.png"  # Resolve the PNG output path inside the temporary directory.
            result = ltspice_asc_plot_schemdraw(str(fixture_path), str(output_path), 1280, 720)  # Execute the public schemdraw plotting helper using a custom raster size.
            self.assertEqual(result, (True, ""), msg="The schemdraw plotting API should render successfully to PNG.")  # Assert that PNG rendering succeeds without an error message.
            with Image.open(output_path) as image:  # Open the rendered PNG so its encoded dimensions can be verified.
                self.assertEqual(image.size, (1280, 720), msg="The generated PNG output should match the requested image dimensions.")  # Assert that the PNG size matches the caller request.

    def test_plot_fixture_accepts_svg_output(self) -> None:  # Verify that the schemdraw plotting API can render one valid fixture to SVG format.
        fixture_path = _VALID_DIRECTORY / "Instrumentation-amplifier.asc"  # Reuse one op-amp-heavy valid ASC sample as the plotting input.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create an isolated temporary output directory for the SVG file.
            output_path = Path(temporary_directory) / "schematic.svg"  # Resolve the SVG output path inside the temporary directory.
            result = ltspice_asc_plot_schemdraw(str(fixture_path), str(output_path), 900, 700)  # Execute the public schemdraw plotting helper using the SVG extension.
            self.assertEqual(result, (True, ""), msg="The schemdraw plotting API should render successfully to SVG.")  # Assert that SVG rendering succeeds without an error message.
            root = ElementTree.fromstring(output_path.read_text(encoding="utf-8"))  # Parse the generated SVG document so the root metadata can be inspected safely.
            self.assertTrue(root.tag.endswith("svg"), msg="The generated SVG output should contain an SVG root element.")  # Assert that the output document is an SVG file.
            self.assertEqual(root.attrib.get("width"), "900px", msg="The generated SVG output should encode the requested width in pixels.")  # Assert that the SVG width matches the requested output width.
            self.assertEqual(root.attrib.get("height"), "700px", msg="The generated SVG output should encode the requested height in pixels.")  # Assert that the SVG height matches the requested output height.

    def test_plot_fixture_accepts_jpg_output(self) -> None:  # Verify that the schemdraw plotting API can render one valid fixture to JPEG format.
        fixture_path = _VALID_DIRECTORY / "Half-bridge-inverter.asc"  # Reuse one switch-heavy valid ASC sample as the plotting input.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create an isolated temporary output directory for the JPEG file.
            output_path = Path(temporary_directory) / "schematic.jpg"  # Resolve the JPEG output path inside the temporary directory.
            result = ltspice_asc_plot_schemdraw(str(fixture_path), str(output_path), 640, 480)  # Execute the public schemdraw plotting helper using the JPEG extension.
            self.assertEqual(result, (True, ""), msg="The schemdraw plotting API should render successfully to JPEG.")  # Assert that JPEG rendering succeeds without an error message.
            with Image.open(output_path) as image:  # Open the rendered JPEG so its encoded dimensions and format can be verified.
                self.assertEqual(image.size, (640, 480), msg="The generated JPEG output should match the requested image dimensions.")  # Assert that the JPEG size matches the caller request.
                self.assertEqual(image.format, "JPEG", msg="The generated raster output should be encoded as a JPEG file.")  # Assert that the raster file format matches the requested extension.

    def test_plot_fixture_rejects_unsupported_extension(self) -> None:  # Verify that unsupported schemdraw output extensions fail with the stable plotting error.
        fixture_path = _VALID_DIRECTORY / "Example-of-DC-sweep.asc"  # Reuse one valid ASC sample as the plotting input.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create an isolated temporary output directory for the unsupported output file.
            output_path = Path(temporary_directory) / "schematic.bmp"  # Resolve an unsupported output path extension inside the temporary directory.
            result = ltspice_asc_plot_schemdraw(str(fixture_path), str(output_path))  # Execute the public schemdraw plotting helper using an unsupported extension.
            self.assertEqual(result, (False, "Unable to plot schematic drawing!"), msg="Unsupported output extensions should fail with the stable schemdraw plotting error.")  # Assert that unsupported extensions are rejected cleanly.


def _make_png_plot_test(fixture_name: str):  # Build one dynamic PNG plotting test method for one valid ASC fixture file.
    def _test_method(self: TestAscPlotSchemdraw) -> None:  # Execute the shared PNG assertions for the selected fixture.
        self._assert_valid_png_output(fixture_name)  # Render and validate the PNG output for the selected ASC fixture file.

    return _test_method  # Return the generated unittest method for later class attachment.


_PNG_PLOT_FIXTURES = [  # Select ten additional valid ASC fixtures to broaden schemdraw rendering coverage.
    "A-class-amplifier-bjt.asc",
    "BJT-emitter-follower-configuration.asc",
    "Common-emitter-BJT.asc",
    "DCDC-full-bridge.asc",
    "Differences-amplifier.asc",
    "Full-bridge-rectifier.asc",
    "PNP-transistor-biasing.asc",
    "Push-pull-amplifier.asc",
    "RC-lowpass.asc",
    "Three-phase-rectifier.asc",
]  # Finish the selected ASC fixture list used by the dynamic PNG rendering tests.


for _fixture_name in _PNG_PLOT_FIXTURES:  # Generate one explicit PNG plotting unit test for each selected ASC fixture.
    _test_name = f"test_plot_fixture_{Path(_fixture_name).stem.lower().replace('-', '_').replace(' ', '_')}"  # Build a stable unittest method name from the fixture filename.
    setattr(TestAscPlotSchemdraw, _test_name, _make_png_plot_test(_fixture_name))  # Attach the generated unittest method to the schemdraw plotting test class.
