"""Unit tests for the KiCad schematic to KiCad PCB conversion API."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

import math  # Measure routed wire bend angles.
import os  # Read the optional KiCad path environment override.
from collections import defaultdict  # Group routed segments per net.
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


def _pcb_bend_violations(pcb, min_angle: float, tolerance: float = 0.5) -> int:  # Count routed bends sharper than the configured minimum.
    pad_points = {(round(pad.position[0], 4), round(pad.position[1], 4)) for footprint in pcb.footprints for pad in footprint.pads}  # Index every pad centre.
    by_net: dict[int, list[tuple[tuple[float, float], tuple[float, float], str]]] = defaultdict(list)  # Group segments per net.
    for segment in pcb.segments:  # Walk every routed segment.
        by_net[segment.net_number].append((segment.start, segment.end, segment.layer))  # Record the segment geometry.
    violations = 0  # Count the bends below the threshold.
    for segments in by_net.values():  # Walk every net's copper.
        endpoints: dict[tuple[float, float], list[int]] = defaultdict(list)  # Group segment ends per vertex.
        for index, (start, end, _layer) in enumerate(segments):  # Walk every segment end.
            endpoints[(round(start[0], 4), round(start[1], 4))].append(index)  # Record the start.
            endpoints[(round(end[0], 4), round(end[1], 4))].append(index)  # Record the end.
        for point, incident in endpoints.items():  # Walk every copper vertex.
            if len(incident) != 2:  # Skip open ends and multi-branch junctions.
                continue  # Move to the next vertex.
            if any(abs(point[0] - pad_x) < 0.05 and abs(point[1] - pad_y) < 0.05 for pad_x, pad_y in pad_points):  # Skip pad terminations.
                continue  # Move to the next vertex.
            first_index, second_index = incident  # Read the two incident segments.
            if segments[first_index][2] != segments[second_index][2]:  # Skip via layer transitions.
                continue  # Move to the next vertex.
            directions = []  # Collect the two wire directions leaving the vertex.
            for index in incident:  # Walk both incident segments.
                start, end, _layer = segments[index]  # Read the segment geometry.
                start_key = (round(start[0], 4), round(start[1], 4))  # Resolve the start key.
                other = end if start_key == point else start  # Pick the far endpoint.
                directions.append(math.degrees(math.atan2(other[1] - point[1], other[0] - point[0])))  # Measure the away direction.
            bend = abs((directions[0] - directions[1] + 180) % 360 - 180)  # Resolve the physical angle between the wires.
            if bend < min_angle - tolerance:  # Detect a bend sharper than requested.
                violations += 1  # Count the violation.
    return violations  # Return the violation count.


def _placed_component_records(schematic_path: Path, settings: dict) -> list[dict]:  # Place one schematic's components with the internal pipeline.
    import importlib  # Import the conversion module through the package registry.

    importlib.import_module("electronics_design.kicad_sch_to_kicad_pcb")  # Ensure the conversion submodule is loaded.
    pcb_module = sys.modules["electronics_design.kicad_sch_to_kicad_pcb"]  # Read the real module despite the package-level function shadowing.
    normalized = pcb_module._normalize_pcb_settings(settings)[1]  # Validate the conversion settings.
    read_result = _read_text_file_lines(str(schematic_path))  # Read the schematic text with encoding detection.
    root = _parse_sch_text("\n".join(read_result[1]))[1]  # Parse the schematic into an S-expression tree.
    components = pcb_module._collect_components(root, normalized["_kicad_path"])[1]  # Parse instances and resolve symbols.
    pcb_module._resolve_footprints(components, normalized)  # Resolve one footprint per component.
    placed_ok, _size = pcb_module._place_components(components, normalized)  # Place the components on the board.
    if not placed_ok:  # Stop when the placement failed.
        raise AssertionError("the internal placement pipeline failed")  # Report the unexpected failure.
    return [record for record in components if not record["power"]]  # Return the placed component records.


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
            output_path = Path(temporary_directory) / "CMOS-555-4.kicad_pcb"  # Derive the scratch PCB path.
            result = kicad_sch_to_kicad_pcb(  # Convert the dense 555 fixture.
                str(_KICAD_SCH_DIRECTORY / "CMOS-555-4.kicad_sch"),  # Pass the schematic path.
                str(output_path),  # Pass the scratch output path.
                {**_CONVERT_SETTINGS, "kicad_pcb_routing_timeout": 240.0},  # Pass a bounded routing budget.
            )  # Finish the conversion call.
            self.assertEqual(result, (True, "OK", 0), msg=f"CMOS-555-4 conversion failed: {result}")  # Require the success tuple.
            from kicad_tools.schema.pcb import PCB  # Import the kicad-tools PCB model.
            pcb = PCB.load(str(output_path))  # Load the generated board.
            self.assertGreaterEqual(len(pcb.footprints), 10, msg="the dense board must place its components")  # Require the placed footprints.

    def test_wire_bends_meet_default_minimum_angle(self) -> None:  # Verify routed bends respect the default 120-degree minimum.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory.
            output_path = Path(temporary_directory) / "bip-osc.kicad_pcb"  # Derive the scratch PCB path.
            result = kicad_sch_to_kicad_pcb(  # Convert the multi-bend fixture.
                str(_KICAD_SCH_DIRECTORY / "bip-osc.kicad_sch"),  # Pass the schematic path.
                str(output_path),  # Pass the scratch output path.
                _CONVERT_SETTINGS,  # Pass the pinned settings.
            )  # Finish the conversion call.
            self.assertEqual(result, (True, "OK", 0), msg=f"bip-osc conversion failed: {result}")  # Require the success tuple.
            from kicad_tools.schema.pcb import PCB  # Import the kicad-tools PCB model.
            pcb = PCB.load(str(output_path))  # Load the generated board.
            violations = _pcb_bend_violations(pcb, 120.0)  # Count bends sharper than 120 degrees.
            self.assertEqual(violations, 0, msg=f"every routed bend must be at least 120 degrees, found {violations} violations")  # Require the minimum angle.

    def test_wire_bends_support_flexible_minimum_angles(self) -> None:  # Verify the minimum bend angle is configurable across many values.
        for minimum_angle in (110.0, 135.0, 150.0):  # Walk the supported flexible thresholds.
            settings = dict(_CONVERT_SETTINGS)  # Copy the pinned settings.
            settings["kicad_pcb_min_wire_angle"] = minimum_angle  # Request the flexible threshold.
            with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory.
                output_path = Path(temporary_directory) / "rc-filter.kicad_pcb"  # Derive the scratch PCB path.
                result = kicad_sch_to_kicad_pcb(  # Convert the small fixture.
                    str(_KICAD_SCH_DIRECTORY / "rc-filter.kicad_sch"),  # Pass the schematic path.
                    str(output_path),  # Pass the scratch output path.
                    settings,  # Pass the flexible-angle settings.
                )  # Finish the conversion call.
                self.assertEqual(result, (True, "OK", 0), msg=f"min angle {minimum_angle} conversion failed: {result}")  # Require the success tuple.
                from kicad_tools.schema.pcb import PCB  # Import the kicad-tools PCB model.
                pcb = PCB.load(str(output_path))  # Load the generated board.
                violations = _pcb_bend_violations(pcb, minimum_angle, tolerance=0.5)  # Count bends sharper than the requested threshold.
                self.assertEqual(violations, 0, msg=f"min angle {minimum_angle} left {violations} sharp bends")  # Require the flexible threshold.

    def test_compact_placement_shrinks_board_and_keeps_spacing(self) -> None:  # Verify compaction shrinks the outline while every footprint pair keeps its gap.
        import importlib  # Import the conversion module through the package registry.

        importlib.import_module("electronics_design.kicad_sch_to_kicad_pcb")  # Ensure the conversion submodule is loaded.
        pcb_module = sys.modules["electronics_design.kicad_sch_to_kicad_pcb"]  # Read the real module despite the package-level function shadowing.
        schematic_path = _KICAD_SCH_DIRECTORY / "bip-osc.kicad_sch"  # Use the multi-component fixture.
        compact_records = _placed_component_records(schematic_path, dict(_CONVERT_SETTINGS))  # Place with compaction enabled.
        loose_records = _placed_component_records(schematic_path, {**_CONVERT_SETTINGS, "kicad_pcb_compact_placement": False})  # Place without compaction.
        compact_width, compact_height = pcb_module._placed_extents(compact_records)  # Measure the compacted content.
        loose_width, loose_height = pcb_module._placed_extents(loose_records)  # Measure the uncompacted content.
        self.assertLess(compact_width * compact_height, loose_width * loose_height, msg="compaction must shrink the placed content area")  # Require a dense board.
        spacing = float(_CONVERT_SETTINGS.get("kicad_pcb_component_spacing", 0.5))  # Read the default minimum gap.
        for first_index, first_record in enumerate(compact_records):  # Walk every component pair.
            first_rect = pcb_module._component_rect(first_record, first_record["board_x"], first_record["board_y"])  # Build the first rectangle.
            for second_record in compact_records[first_index + 1:]:  # Walk every later component.
                second_rect = pcb_module._component_rect(second_record, second_record["board_x"], second_record["board_y"])  # Build the second rectangle.
                self.assertFalse(pcb_module._rects_too_close(first_rect, second_rect, spacing - 1e-6), msg="compacted footprints must keep their minimum gap")  # Require the spacing contract.

    def test_new_settings_validation_errors(self) -> None:  # Verify the new PCB settings reject unusable values.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for attempted outputs.
            output_path = Path(temporary_directory) / "out.kicad_pcb"  # Derive the scratch output path.
            schematic_path = str(_KICAD_SCH_DIRECTORY / "rc-filter.kicad_sch")  # Resolve the fixture path.
            for key, value in (  # Walk every invalid new setting.
                ("kicad_pcb_min_wire_angle", 0.0),  # The minimum angle must be positive.
                ("kicad_pcb_min_wire_angle", 180.0),  # The minimum angle must stay below 180.
                ("kicad_pcb_min_wire_angle", "wide"),  # The minimum angle must be numeric.
                ("kicad_pcb_wire_bend_chamfer", 0.0),  # The bend chamfer must be positive.
                ("kicad_pcb_component_spacing", -0.1),  # The footprint spacing must be nonnegative.
                ("kicad_pcb_compact_placement", "yes"),  # The compaction toggle must be boolean.
            ):  # Finish the invalid setting table.
                bad_settings = {**_CONVERT_SETTINGS, key: value}  # Build the invalid settings.
                result = kicad_sch_to_kicad_pcb(schematic_path, str(output_path), bad_settings)  # Run the conversion with the invalid setting.
                self.assertEqual(result[0], False, msg=f"{key}={value!r} must fail")  # Require the failure flag.
                self.assertEqual(result[1].split(":", 1)[0], "INVALID_CONVERT_SETTINGS", msg=f"unexpected error for {key}={value!r}: {result[1]}")  # Require the settings error code.



