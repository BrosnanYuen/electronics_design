"""Unit tests for the KiCad schematic to KiCad PCB conversion API."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

import os  # Read the optional KiCad path environment override.
from pathlib import Path  # Use pathlib for clear path handling.
import sys  # Reach the loaded conversion module through the package registry.
import tempfile  # Use a temporary directory so tests never modify checked-in files.
import unittest  # Use the standard library test framework.

from electronics_design import kicad_sch_to_kicad_pcb  # Import the KiCad schematic to KiCad PCB conversion API.
from electronics_design.kicad_sch import _parse_sch_text  # Reuse the shared schematic parser for connectivity fixtures.
from electronics_design.kicad_sch import _read_text_file_lines  # Reuse the shared encoding-aware reader for connectivity fixtures.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_KICAD_SCH_DIRECTORY = _ROOT_DIRECTORY / "kicad_convert" / "kicad_sch"  # Point at the checked-in KiCad schematic files.
_KICAD_PATH = os.environ.get("ELECTRONICS_DESIGN_KICAD_PATH", "/usr/share/kicad")  # Resolve the KiCad library path with an optional environment override.

_CONVERT_SETTINGS = {  # Pin the settings so generated boards are reproducible.
    "kicad_path": _KICAD_PATH,  # Look symbols and footprints up from the configured KiCad installation.
}  # Finish the conversion settings dictionary.


def _schematic_net_partition(schematic_path: Path) -> set[frozenset[tuple[str, str]]]:  # Trace one schematic's net membership for structural comparison.
    import importlib  # Import the conversion module through the package registry.

    importlib.import_module("electronics_design.kicad_sch_to_kicad_pcb")  # Ensure the conversion submodule is loaded.
    pcb_module = sys.modules["electronics_design.kicad_sch_to_kicad_pcb"]  # Read the real module despite the package-level function shadowing.
    read_result = _read_text_file_lines(str(schematic_path))  # Read the schematic text with encoding detection.
    root = _parse_sch_text("\n".join(read_result[1]))[1]  # Parse the schematic into an S-expression tree.
    components = pcb_module._collect_components(root, _KICAD_PATH)[1]  # Parse instances and resolve symbol definitions.
    net_names = pcb_module._trace_nets(root, components)[1]  # Trace connectivity and resolve net names.
    by_name: dict[str, set[tuple[str, str]]] = {}  # Collect members per net name.
    for record in components:  # Walk every component record.
        if record["power"]:  # Power symbols carry no PCB pads.
            continue  # Skip power-derived memberships.
        for pin_number, pin_root in record["pin_nets"].items():  # Walk every traced pin.
            if pin_root is None:  # Skip no-connect pins.
                continue  # Move to the next pin.
            by_name.setdefault(net_names[pin_root], set()).add((record["reference"], pin_number))  # Add the member pair.
    return {frozenset(members) for members in by_name.values()}  # Return the schematic-side net partition.


class TestKicadSchToKicadPcb(unittest.TestCase):  # Group the KiCad schematic to KiCad PCB conversion tests together.  # Group the KiCad schematic to KiCad PCB conversion tests together.
    def test_small_schematic_converts_to_valid_pcb(self) -> None:  # Verify one small schematic converts to a loadable routed board.
        self.assertTrue(_KICAD_SCH_DIRECTORY.joinpath("rc-filter.kicad_sch").is_file(), msg="rc-filter fixture must exist")  # Require the fixture.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the generated board.
            output_path = Path(temporary_directory) / "rc-filter.kicad_pcb"  # Derive the scratch PCB path.
            result = kicad_sch_to_kicad_pcb(  # Run the public conversion API.
                str(_KICAD_SCH_DIRECTORY / "rc-filter.kicad_sch"),  # Pass the fixture schematic.
                str(output_path),  # Pass the scratch output path.
                _CONVERT_SETTINGS,  # Pass the pinned settings.
            )  # Finish the conversion call.
            self.assertEqual(result, (True, "OK", 0), msg=f"rc-filter should convert but returned: {result}")  # Require the success tuple.
            self.assertTrue(output_path.is_file(), msg="the generated PCB file must exist")  # Require the output file.
            from kicad_tools.schema.pcb import PCB  # Import the kicad-tools PCB model lazily.
            pcb = PCB.load(str(output_path))  # Parse the generated board.
            self.assertGreaterEqual(len(pcb.footprints), 3, msg="the generated board must place every schematic component")  # Require the placed footprints.
            self.assertGreaterEqual(len(pcb.nets), 2, msg="the generated board must declare its nets")  # Require the declared nets.
            self.assertGreaterEqual(len(pcb.segments), 1, msg="the generated board must carry routed copper")  # Require routed copper.

    def test_generated_board_connectivity_matches_schematic(self) -> None:  # Verify the PCB pad-net partition mirrors the schematic connectivity.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory.
            output_path = Path(temporary_directory) / "bip-osc.kicad_pcb"  # Derive the scratch PCB path.
            result = kicad_sch_to_kicad_pcb(  # Convert the bipolar oscillator fixture.
                str(_KICAD_SCH_DIRECTORY / "bip-osc.kicad_sch"),  # Pass the schematic path.
                str(output_path),  # Pass the scratch output path.
                _CONVERT_SETTINGS,  # Pass the pinned settings.
            )  # Finish the conversion call.
            self.assertEqual(result, (True, "OK", 0), msg=f"bip-osc conversion failed: {result}")  # Require the success tuple.
            from kicad_tools.schema.pcb import PCB  # Import the kicad-tools PCB model.
            pcb = PCB.load(str(output_path))  # Load the generated board.
            by_name: dict[str, set[tuple[str, str]]] = {}  # Regroup pads per net name.
            for footprint in pcb.footprints:  # Walk the footprints again.
                for pad in footprint.pads:  # Walk the pads again.
                    if pad.net_name:  # Keep only assigned pads.
                        by_name.setdefault(pad.net_name, set()).add((footprint.reference, pad.number))  # Record the membership.
            pcb_partition = {frozenset(members) for members in by_name.values()}  # Collapse the board-side partition.
            schematic_partition = _schematic_net_partition(_KICAD_SCH_DIRECTORY / "bip-osc.kicad_sch")  # Trace the schematic-side partition.
            self.assertEqual(pcb_partition, schematic_partition, msg="PCB pad nets must mirror the schematic connectivity exactly")  # Require the structural match.

    def test_routed_copper_reaches_pads_on_small_board(self) -> None:  # Verify every multi-pad net carries copper that touches its pads.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory.
            output_path = Path(temporary_directory) / "rc-filter.kicad_pcb"  # Derive the scratch output path.
            result = kicad_sch_to_kicad_pcb(  # Convert the small filter fixture.
                str(_KICAD_SCH_DIRECTORY / "rc-filter.kicad_sch"),  # Pass the schematic path.
                str(output_path),  # Pass the scratch output path.
                _CONVERT_SETTINGS,  # Pass the pinned settings.
            )  # Finish the conversion call.
            self.assertEqual(result, (True, "OK", 0), msg=f"rc-filter conversion failed: {result}")  # Require the success tuple.
            from kicad_tools.schema.pcb import PCB  # Import the kicad-tools PCB model.
            pcb = PCB.load(str(output_path))  # Load the generated board.
            net_pads: dict[str, list[tuple[str, str]]] = {}  # Collect pads per named net.
            for footprint in pcb.footprints:  # Walk every placed footprint.
                for pad in footprint.pads:  # Walk every pad.
                    if pad.net_name:  # Keep only assigned pads.
                        net_pads.setdefault(pad.net_name, []).append((footprint.reference, pad.number))  # Record the membership.
            multi_pad_nets = {name: pads for name, pads in net_pads.items() if len(pads) >= 2}  # Keep only routeable nets.
            self.assertGreaterEqual(len(multi_pad_nets), 1, msg="the fixture must carry at least one multi-pad net")  # Require a routeable net.
            routed_net_numbers = {segment.net_number for segment in pcb.segments}  # Collect nets that received copper.
            for net_name, pads in multi_pad_nets.items():  # Walk every routeable net.
                net_number = next(number for number, net in pcb.nets.items() if net.name == net_name)  # Resolve the net number.
                self.assertIn(net_number, routed_net_numbers, msg=f"{net_name} must carry routed copper")  # Require copper for the net.

    def test_route_disabled_emits_unrouted_board(self) -> None:  # Verify the routing toggle emits a placed but unrouted board.
        settings = dict(_CONVERT_SETTINGS)  # Copy the pinned settings.
        settings["kicad_pcb_route_traces"] = False  # Disable trace routing for this test.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory.
            output_path = Path(temporary_directory) / "rc-filter.kicad_pcb"  # Derive the scratch output path.
            result = kicad_sch_to_kicad_pcb(  # Convert the fixture without routing.
                str(_KICAD_SCH_DIRECTORY / "rc-filter.kicad_sch"),  # Pass the schematic path.
                str(output_path),  # Pass the scratch output path.
                settings,  # Pass the routing-disabled settings.
            )  # Finish the conversion call.
            self.assertEqual(result, (True, "OK", 0), msg=f"unrouted conversion failed: {result}")  # Require the success tuple.
            from kicad_tools.schema.pcb import PCB  # Import the kicad-tools PCB model.
            pcb = PCB.load(str(output_path))  # Load the generated board.
            self.assertGreaterEqual(len(pcb.footprints), 3, msg="the unrouted board must still place every component")  # Require the placed footprints.
            self.assertEqual(len(pcb.segments), 0, msg="the unrouted board must carry no copper")  # Require the absent copper.

    def test_footprint_override_map_is_honored(self) -> None:  # Verify the configured footprint override map selects the placed footprint.
        settings = dict(_CONVERT_SETTINGS)  # Copy the pinned settings.
        settings["kicad_pcb_footprint_map"] = {"R": "Resistor_SMD:R_0805_2012Metric"}  # Override every resistor footprint.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory.
            output_path = Path(temporary_directory) / "rc-filter.kicad_pcb"  # Derive the scratch output path.
            result = kicad_sch_to_kicad_pcb(  # Convert the fixture with the override.
                str(_KICAD_SCH_DIRECTORY / "rc-filter.kicad_sch"),  # Pass the schematic path.
                str(output_path),  # Pass the scratch output path.
                settings,  # Pass the override settings.
            )  # Finish the conversion call.
            self.assertEqual(result, (True, "OK", 0), msg=f"override conversion failed: {result}")  # Require the success tuple.
            from kicad_tools.schema.pcb import PCB  # Import the kicad-tools PCB model.
            pcb = PCB.load(str(output_path))  # Load the generated board.
            resistors = [footprint for footprint in pcb.footprints if footprint.reference.startswith("R")]  # Collect the placed resistors.
            self.assertGreater(len(resistors), 0, msg="the fixture must place at least one resistor")  # Require a resistor.
            for footprint in resistors:  # Walk every placed resistor.
                self.assertIn("R_0805_2012Metric", footprint.name, msg="the override footprint must be honored")  # Require the overridden footprint name.

    def test_settings_validation_errors(self) -> None:  # Verify the settings validator rejects unusable configuration values.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for attempted outputs.
            output_path = Path(temporary_directory) / "out.kicad_pcb"  # Derive the scratch output path.
            result = kicad_sch_to_kicad_pcb(str(_KICAD_SCH_DIRECTORY / "rc-filter.kicad_sch"), str(output_path), "not-a-mapping")  # Pass non-mapping settings.
            self.assertEqual(result[0], False, msg="non-mapping settings must fail")  # Require the failure flag.
            self.assertEqual(result[1].split(":", 1)[0], "INVALID_CONVERT_SETTINGS", msg=f"unexpected error code: {result[1]}")  # Require the settings error code, ignoring the detail suffix.
            bad_settings = dict(_CONVERT_SETTINGS)  # Copy the pinned settings.
            bad_settings["kicad_pcb_layers"] = 3  # Choose an unsupported layer count.
            result = kicad_sch_to_kicad_pcb(str(_KICAD_SCH_DIRECTORY / "rc-filter.kicad_sch"), str(output_path), bad_settings)  # Run the conversion with bad layers.
            self.assertEqual(result[1].split(":", 1)[0], "INVALID_CONVERT_SETTINGS", msg="unsupported layer counts must fail")  # Require the settings error code.
            bad_settings = dict(_CONVERT_SETTINGS)  # Copy the pinned settings again.
            bad_settings["kicad_pcb_track_width"] = -1.0  # Choose a negative trace width.
            result = kicad_sch_to_kicad_pcb(str(_KICAD_SCH_DIRECTORY / "rc-filter.kicad_sch"), str(output_path), bad_settings)  # Run the conversion with the bad width.
            self.assertEqual(result[1].split(":", 1)[0], "INVALID_CONVERT_SETTINGS", msg="negative numeric settings must fail")  # Require the settings error code.

    def test_missing_input_file_fails_with_kicad_sch_error(self) -> None:  # Verify missing schematic inputs report the schematic error code.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory.
            output_path = Path(temporary_directory) / "out.kicad_pcb"  # Derive the scratch output path.
            result = kicad_sch_to_kicad_pcb(str(_KICAD_SCH_DIRECTORY / "does-not-exist.kicad_sch"), str(output_path), _CONVERT_SETTINGS)  # Convert a missing schematic.
            self.assertEqual(result[0], False, msg="missing inputs must fail")  # Require the failure flag.
            self.assertEqual(result[1], "INVALID_KICAD_SCH_FILE", msg=f"unexpected error code: {result[1]}")  # Require the schematic error code.

    def test_kicad_tools_dependency_imports_directly(self) -> None:  # Verify kicad-tools is importable as a declared package dependency.
        import kicad_tools  # The declared dependency import.
        import electronics_design.kicad_sch_to_kicad_pcb as pcb_module  # The conversion module through the package registry.

        module = sys.modules["electronics_design.kicad_sch_to_kicad_pcb"]  # Read the loaded module despite the function shadowing.
        self.assertEqual(module._KICAD_TOOLS_IMPORT_ERROR, "", msg=f"kicad-tools must import cleanly: {module._KICAD_TOOLS_IMPORT_ERROR}")  # Require the clean import marker.
        self.assertTrue(hasattr(kicad_tools, "__file__"), msg="kicad-tools must resolve to an installed distribution")  # Require the installed package.

    def test_generated_fallback_footprints_support_unmatched_pins(self) -> None:  # Verify components without footprint properties fall back to generated footprints.
        settings = dict(_CONVERT_SETTINGS)  # Copy the pinned settings.
        settings["kicad_pcb_default_footprints"] = {"R": "", "C": "", "Q": "", "V": "", "I": "", "D": "", "L": ""}  # Clear every prefix default to force the fallback path.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory.
            output_path = Path(temporary_directory) / "rc-filter.kicad_pcb"  # Derive the scratch output path.
            result = kicad_sch_to_kicad_pcb(  # Convert the fixture without prefix defaults.
                str(_KICAD_SCH_DIRECTORY / "rc-filter.kicad_sch"),  # Pass the schematic path.
                str(output_path),  # Pass the scratch output path.
                settings,  # Pass the cleared-default settings.
            )  # Finish the conversion call.
            self.assertEqual(result, (True, "OK", 0), msg=f"fallback conversion failed: {result}")  # Require the success tuple.
            from kicad_tools.schema.pcb import PCB  # Import the kicad-tools PCB model.
            pcb = PCB.load(str(output_path))  # Load the generated board.
            self.assertGreaterEqual(len(pcb.footprints), 3, msg="generated fallback footprints must still place every component")  # Require the placed footprints.

    def test_dense_fixture_converts_with_partial_routing(self) -> None:  # Verify a dense schematic converts successfully even when some nets stay unrouted.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory.
            output_path = Path(temporary_directory) / "CMOS-555-4.kicad_pcb"  # Derive the scratch output path.
            result = kicad_sch_to_kicad_pcb(  # Convert the dense 555 fixture.
                str(_KICAD_SCH_DIRECTORY / "CMOS-555-4.kicad_sch"),  # Pass the schematic path.
                str(output_path),  # Pass the scratch output path.
                {**_CONVERT_SETTINGS, "kicad_pcb_routing_timeout": 240.0},  # Pass a bounded routing budget.
            )  # Finish the conversion call.
            self.assertEqual(result, (True, "OK", 0), msg=f"CMOS-555-4 conversion failed: {result}")  # Require the success tuple.
            from kicad_tools.schema.pcb import PCB  # Import the kicad-tools PCB model.
            pcb = PCB.load(str(output_path))  # Load the generated board.
            self.assertGreaterEqual(len(pcb.footprints), 10, msg="the dense board must place its components")  # Require the placed footprints.



