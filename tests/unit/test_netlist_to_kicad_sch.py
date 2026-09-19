"""Unit tests for the LTspice netlist to KiCad schematic conversion API."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

import importlib  # Import the netlist-to-KiCad module internals for the sparse-coverage and nested-lookup tests.
import os  # Read the optional KiCad path environment override.
from pathlib import Path  # Use pathlib for clear path handling.
import tempfile  # Use a temporary directory for round-trip netlist outputs.
import unittest  # Use the standard library test framework.
from unittest import mock  # Patch the wiring stage to exercise the retry ladder deterministically.

from electronics_design import is_valid_kicad_sch_file  # Import the KiCad schematic whole-file validator.
from electronics_design import is_valid_ltspice_netlist_file  # Import the LTspice netlist whole-file validator.
from electronics_design import kicad_sch_to_ltspice_netlist  # Import the KiCad schematic to LTspice netlist conversion API.
from electronics_design import ltspice_netlist_footer_cmp  # Import the directive and model-footer comparison helper.
from electronics_design import ltspice_netlist_structure_cmp  # Import the LTspice netlist structural comparison helper.
from electronics_design import ltspice_netlist_to_kicad_sch  # Import the netlist-to-KiCad-schematic conversion API.
from electronics_design.kicad_sexp_parser import parse_string  # Inspect generated annotation visibility and labels.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_NETLIST_DIRECTORY = _ROOT_DIRECTORY / "kicad_convert" / "netlist"  # Point at the checked-in LTspice netlist files.

_KICAD_PATH = os.environ.get("ELECTRONICS_DESIGN_KICAD_PATH", "/usr/share/kicad")  # Resolve the KiCad library path with an optional environment override.

_SCH_MODULE = importlib.import_module("electronics_design.ltspice_netlist_to_kicad_sch")  # Access the module internals, since the package re-exports the public function under the same name.

_CONVERT_SETTINGS = {  # Pin the settings so generated files are reproducible.
    "kicad_path": _KICAD_PATH,  # Look symbols up from the configured KiCad installation path.
    "kicad_sch_version": "20260306",  # Use a fixed eight-digit KiCad format version.
    "kicad_sch_generator": "electronics_design",  # Name the generator explicitly.
    "custom_search_paths": [  # Resolve LTspice ASY fallback symbols from the repository corpus.
        str(_ROOT_DIRECTORY / "kicad_convert" / "asy"),  # Use the checked-in ASY conversion corpus first.
        str(_ROOT_DIRECTORY / "valid_asy"),  # Fall back to the standard valid ASY fixtures.
    ],  # Finish the custom search paths.
}  # Finish the conversion settings dictionary.


def _collect_generated_wire_segments(schematic_root) -> list:  # Collect every two-point wire segment from one parsed schematic.
    segments = []  # Collect the segment endpoint pairs.
    for wire_node in schematic_root.find_children("wire"):  # Walk every wire record.
        points_node = wire_node.find_child("pts")  # Locate the polyline point list.
        assert points_node is not None  # Generated wires always carry a point list.
        points = []  # Collect the wire's coordinate pairs.
        for xy_node in points_node.find_children("xy"):  # Walk every coordinate pair.
            values = [child.value for child in xy_node.children if child.value is not None]  # Read the numeric atoms.
            points.append((float(values[0]), float(values[1])))  # Store the coordinate pair.
        assert len(points) == 2, "Generated wires must be two-point segments."  # Require the routed segment shape.
        segments.append((points[0], points[1]))  # Store the segment.
    return segments  # Return the generated wire segments.


def _collect_generated_junction_points(schematic_root) -> list:  # Collect every junction position and identifier from one parsed schematic.
    junctions = []  # Collect the junction records.
    for junction_node in schematic_root.find_children("junction"):  # Walk every junction record.
        at_node = junction_node.find_child("at")  # Locate the position record.
        assert at_node is not None  # Generated junctions always carry a position.
        values = [child.value for child in at_node.children if child.value is not None]  # Read the coordinate atoms.
        uuid_node = junction_node.find_child("uuid")  # Locate the identifier record.
        assert uuid_node is not None  # Generated junctions always carry an identifier.
        junction_uuid = str([child.value for child in uuid_node.children if child.value is not None][0])  # Read the identifier value.
        junctions.append(((round(float(values[0]), 6), round(float(values[1]), 6)), junction_uuid))  # Store the normalized point and identifier.
    return junctions  # Return the junction records.


def _test_point_on_segment(px: float, py: float, segment: tuple, tolerance: float = 1e-4) -> bool:  # Decide whether a point lies on one segment.
    (start_x, start_y), (end_x, end_y) = segment  # Unpack the segment endpoints.
    if px < min(start_x, end_x) - tolerance or px > max(start_x, end_x) + tolerance:  # Reject points outside the X span.
        return False  # Return False for non-overlapping X coordinates.
    if py < min(start_y, end_y) - tolerance or py > max(start_y, end_y) + tolerance:  # Reject points outside the Y span.
        return False  # Return False for non-overlapping Y coordinates.
    delta_x, delta_y = end_x - start_x, end_y - start_y  # Compute the segment extent.
    length_squared = delta_x * delta_x + delta_y * delta_y  # Compute the squared segment length.
    if length_squared == 0.0:  # Handle degenerate zero-length segments.
        return abs(px - start_x) <= tolerance and abs(py - start_y) <= tolerance  # Return the point-equality check.
    projection = ((px - start_x) * delta_x + (py - start_y) * delta_y) / length_squared  # Project the point onto the segment.
    if projection < -1e-9 or projection > 1.0 + 1e-9:  # Reject projections beyond the segment endpoints.
        return False  # Return False for out-of-range projections.
    closest_x = start_x + projection * delta_x  # Compute the closest X coordinate on the segment.
    closest_y = start_y + projection * delta_y  # Compute the closest Y coordinate on the segment.
    return abs(px - closest_x) <= tolerance and abs(py - closest_y) <= tolerance  # Return the distance check.


def _test_point_strictly_inside_segment(point: tuple, segment: tuple, tolerance: float = 1e-4) -> bool:  # Decide whether a point sits on a segment away from both endpoints.
    if not _test_point_on_segment(point[0], point[1], segment, tolerance):  # Require the point to lie on the segment.
        return False  # Reject points that are not on the segment.
    (start_x, start_y), (end_x, end_y) = segment  # Unpack the segment endpoints.
    clear_of_start = abs(point[0] - start_x) > tolerance or abs(point[1] - start_y) > tolerance  # Require clearance from the start endpoint.
    clear_of_end = abs(point[0] - end_x) > tolerance or abs(point[1] - end_y) > tolerance  # Require clearance from the end endpoint.
    return clear_of_start and clear_of_end  # Return True only for strict interior contacts, which KiCad cannot connect without a junction.


class TestNetlistToKicadSch(unittest.TestCase):  # Group the netlist-to-KiCad-schematic conversion tests together.
    def test_all_generated_netlists_are_valid(self) -> None:  # Verify every artifact generated from the authoritative KiCad schematics is a valid LTspice netlist.
        net_files = sorted(_NETLIST_DIRECTORY.glob("*.net"))  # Collect all generated LTspice netlist files.
        self.assertGreater(len(net_files), 0, msg="kicad_convert/netlist/ must contain LTspice netlist files.")  # Require the source files to exist.
        for net_path in net_files:  # Walk every generated artifact.
            with self.subTest(netlist=net_path.name):  # Isolate failures per netlist file.
                validation = is_valid_ltspice_netlist_file(str(net_path))  # Validate the generated netlist directly.
                self.assertEqual(validation, (True, ""), msg=f"{net_path.name} should be valid but returned: {validation[1]}")  # Require a valid generated artifact.

    def test_reference_netlist_converts_to_valid_kicad_schematic(self) -> None:  # Exercise the inverse converter with the supported reference deck without treating generated artifacts as ground truth.
        net_files = [_NETLIST_DIRECTORY / "NPN1.net"]  # Use the compact reference deck for inverse-conversion and structural round-trip coverage.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the generated schematics and round-trip netlists.
            for net_path in net_files:  # Walk every LTspice netlist file.
                with self.subTest(netlist=net_path.name):  # Isolate failures per netlist file.
                    output_path = Path(temporary_directory) / f"{net_path.stem}.kicad_sch"  # Derive the scratch KiCad schematic path.
                    result = ltspice_netlist_to_kicad_sch(str(net_path), str(output_path), _CONVERT_SETTINGS)  # Run the public conversion API.
                    self.assertEqual(  # Require the conversion to succeed with the standard success tuple.
                        result,  # Compare the returned conversion result.
                        (True, "OK", 0),  # Expect success, the OK message, and line zero.
                        msg=f"{net_path.name} should convert but returned: {result}",  # Report the failure with the returned tuple.
                    )  # Finish the conversion assertion.
                    validation = is_valid_kicad_sch_file(str(output_path))  # Validate the freshly generated KiCad schematic.
                    self.assertEqual(  # Require the generated file to pass the whole-file schematic validator.
                        validation,  # Compare the returned validation result.
                        (True, ""),  # Expect success with an empty message.
                        msg=f"{output_path.name} should be valid but returned: {validation[1]}",  # Report the failure with the returned message.
                    )  # Finish the validation assertion.
                    generated_text = output_path.read_text(encoding="utf-8")
                    generated_root = parse_string(generated_text)
                    lib_symbols = generated_root.find_child("lib_symbols")
                    self.assertIsNotNone(lib_symbols)
                    assert lib_symbols is not None
                    for embedded_symbol in lib_symbols.find_children("symbol"):
                        for annotation_name in ("pin_names", "pin_numbers"):
                            annotation = embedded_symbol.find_child(annotation_name)
                            self.assertIsNotNone(annotation, msg=f"{annotation_name} visibility must be explicit.")
                            assert annotation is not None
                            hide = annotation.find_child("hide")
                            self.assertIsNotNone(hide, msg=f"{annotation_name} must be hidden to avoid symbol overlap.")
                    for symbol_instance in generated_root.find_children("symbol"):
                        symbol_at = symbol_instance.find_child("at")
                        self.assertIsNotNone(symbol_at)
                        assert symbol_at is not None
                        symbol_position = [child.value for child in symbol_at.children if child.value is not None]
                        symbol_angle = float(symbol_position[2]) if len(symbol_position) > 2 else 0.0
                        for property_node in symbol_instance.find_children("property"):
                            property_atoms = [child.value for child in property_node.children if child.value is not None]
                            if not property_atoms or property_atoms[0] not in {"Reference", "Value"}:
                                continue
                            placement_lock = property_node.find_child("do_not_autoplace")
                            self.assertIsNotNone(placement_lock, msg=f"{property_atoms[0]} must declare its placement lock.")
                            assert placement_lock is not None
                            lock_atoms = [child.value for child in placement_lock.children if child.value is not None]
                            self.assertEqual(lock_atoms, ["yes"], msg=f"{property_atoms[0]} must retain its collision-free generated position.")
                            if property_node.find_child("hide") is None:
                                property_at = property_node.find_child("at")
                                self.assertIsNotNone(property_at)
                                assert property_at is not None
                                property_position = [child.value for child in property_at.children if child.value is not None]
                                property_angle = float(property_position[2]) if len(property_position) > 2 else 0.0
                                self.assertAlmostEqual((symbol_angle + property_angle) % 180.0, 0.0, msg=f"{property_atoms[0]} must render horizontally so its collision bounds remain valid.")
                    round_trip_path = Path(temporary_directory) / f"{net_path.stem}.net"  # Derive the scratch round-trip netlist path.
                    round_trip_result = kicad_sch_to_ltspice_netlist(str(output_path), str(round_trip_path), _CONVERT_SETTINGS)  # Convert the schematic back into a netlist.
                    self.assertEqual(  # Require the reverse conversion to succeed.
                        round_trip_result,  # Compare the returned conversion result.
                        (True, "OK", 0),  # Expect success, the OK message, and line zero.
                        msg=f"{output_path.name} should convert back but returned: {round_trip_result}",  # Report the failure with the returned tuple.
                    )  # Finish the reverse conversion assertion.
                    round_trip_validation = is_valid_ltspice_netlist_file(str(round_trip_path))  # Validate the round-trip netlist file.
                    self.assertEqual(  # Require the round-trip netlist to pass the whole-file netlist validator.
                        round_trip_validation,  # Compare the returned validation result.
                        (True, ""),  # Expect success with an empty message.
                        msg=f"{round_trip_path.name} should be valid but returned: {round_trip_validation[1]}",  # Report the failure with the returned message.
                    )  # Finish the round-trip validation assertion.
                    structure_matches = ltspice_netlist_structure_cmp(str(net_path), str(round_trip_path))  # Compare the round-trip structure to the original netlist.
                    self.assertTrue(  # Require the round-trip netlist to be structurally equivalent to the original.
                        structure_matches,  # Check the structural comparison result.
                        msg=f"{round_trip_path.name} must match {net_path.name} structurally.",  # Report the structural mismatch.
                    )  # Finish the structural assertion.

    def test_known_bug_decks_preserve_structure_and_footer(self) -> None:  # Prevent regressions in every conversion-loss category recorded in BUGS.md.
        representative_stems = (  # Cover parameters/directives, singleton labels, ground, transmission lines, and thermal MOSFET symbols.
            "Class-D",  # Exercise subcircuit parameters, options, and library directives.
            "741_subckt",  # Exercise singleton net labels and included model libraries.
            "ICL8038subckt",  # Exercise many ground connections on a large schematic.
            "ibis2",  # Exercise four-node transmission lines and their true Td parameter.
            "royer1",  # Exercise preservation of unresolved model includes.
            "F5TurboV2thermal-short",  # Exercise model-specific five-pin thermal MOSFET ASY lookup.
        )  # Finish the representative regression corpus.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Isolate all generated round-trip artifacts.
            for stem in representative_stems:  # Convert and compare every representative deck.
                with self.subTest(netlist=stem):  # Report failures by source deck.
                    net_path = _NETLIST_DIRECTORY / f"{stem}.net"  # Resolve the authoritative source netlist.
                    schematic_path = Path(temporary_directory) / f"{stem}.kicad_sch"  # Derive the generated schematic path.
                    round_trip_path = Path(temporary_directory) / f"{stem}.roundtrip.net"  # Derive the reverse-converted netlist path.
                    forward_result = ltspice_netlist_to_kicad_sch(str(net_path), str(schematic_path), _CONVERT_SETTINGS)  # Generate the KiCad schematic.
                    self.assertEqual(forward_result, (True, "OK", 0), msg=f"{stem} forward conversion failed: {forward_result}")  # Require successful forward conversion.
                    reverse_result = kicad_sch_to_ltspice_netlist(str(schematic_path), str(round_trip_path), _CONVERT_SETTINGS)  # Convert the generated schematic back.
                    self.assertEqual(reverse_result, (True, "OK", 0), msg=f"{stem} reverse conversion failed: {reverse_result}")  # Require successful reverse conversion.
                    self.assertTrue(ltspice_netlist_structure_cmp(str(net_path), str(round_trip_path)), msg=f"{stem} lost or rewired an element or net.")  # Require identical circuit structure.
                    self.assertTrue(ltspice_netlist_footer_cmp(str(net_path), str(round_trip_path)), msg=f"{stem} lost a directive, include, model, or instance parameter.")  # Require identical simulation metadata.

    def test_junction_dots_cover_every_endpoint_on_wire_contact(self) -> None:  # Require KiCad junction dots at every endpoint-on-wire contact the router creates.
        fixture_stems = ("NPN1", "rc-filter", "sallen-key-highpass")  # Cover compact, filter, and opamp decks that route endpoint-on-wire contacts.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Isolate the generated schematics.
            for stem in fixture_stems:  # Convert and inspect every fixture.
                with self.subTest(netlist=stem):  # Isolate failures per fixture.
                    net_path = _NETLIST_DIRECTORY / f"{stem}.net"  # Resolve the source netlist.
                    schematic_path = Path(temporary_directory) / f"{stem}.kicad_sch"  # Derive the generated schematic path.
                    result = ltspice_netlist_to_kicad_sch(str(net_path), str(schematic_path), _CONVERT_SETTINGS)  # Run the public conversion API.
                    self.assertEqual(result, (True, "OK", 0), msg=f"{stem} should convert but returned: {result}")  # Require successful conversion.
                    generated_root = parse_string(schematic_path.read_text(encoding="utf-8"))  # Parse the generated schematic.
                    segments = _collect_generated_wire_segments(generated_root)  # Read every routed wire segment.
                    junctions = _collect_generated_junction_points(generated_root)  # Read every junction record.
                    expected_points = set()  # Collect the endpoint-on-interior positions KiCad cannot connect without a junction.
                    for index, segment in enumerate(segments):  # Walk every segment endpoint.
                        for endpoint in segment:  # Test both endpoints of the segment.
                            for other_index, other_segment in enumerate(segments):  # Walk the remaining copper.
                                if other_index == index:  # Skip the segment against itself.
                                    continue  # Move to the next candidate segment.
                                if _test_point_strictly_inside_segment(endpoint, other_segment):  # Detect a strict endpoint-on-interior contact.
                                    expected_points.add((round(endpoint[0], 6), round(endpoint[1], 6)))  # Record the required junction position.
                    actual_points = {point for point, _uuid in junctions}  # Read the emitted junction positions.
                    self.assertGreater(len(expected_points), 0, msg=f"{stem} must route endpoint-on-wire contacts to exercise the junction fix.")  # Require the fixture to exercise the fix.
                    self.assertEqual(actual_points, expected_points, msg=f"{stem} junction dots must cover exactly the endpoint-on-wire contacts.")  # Require exact junction coverage.
                    junction_uuids = [junction_uuid for _point, junction_uuid in junctions]  # Read the emitted junction identifiers.
                    self.assertEqual(len(junction_uuids), len(set(junction_uuids)), msg=f"{stem} junction identifiers must be unique.")  # Require unique junction identifiers.
                    for junction_node in generated_root.find_children("junction"):  # Verify the emitted junction payloads.
                        self.assertIsNotNone(junction_node.find_child("diameter"), msg="Generated junctions must carry a diameter record.")  # Require the diameter field.
                        self.assertIsNotNone(junction_node.find_child("color"), msg="Generated junctions must carry a color record.")  # Require the color field.

    def test_junction_bearing_schematic_round_trips_to_the_same_netlist(self) -> None:  # Require junction-rich schematics to trace back to the same circuit.
        net_path = _NETLIST_DIRECTORY / "sallen-key-highpass.net"  # Use the filter deck that routes many endpoint-on-wire contacts.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Isolate the generated artifacts.
            schematic_path = Path(temporary_directory) / "sallen-key-highpass.kicad_sch"  # Derive the generated schematic path.
            round_trip_path = Path(temporary_directory) / "sallen-key-highpass.roundtrip.net"  # Derive the reverse-converted netlist path.
            forward_result = ltspice_netlist_to_kicad_sch(str(net_path), str(schematic_path), _CONVERT_SETTINGS)  # Generate the KiCad schematic.
            self.assertEqual(forward_result, (True, "OK", 0), msg=f"Forward conversion failed: {forward_result}")  # Require successful forward conversion.
            generated_root = parse_string(schematic_path.read_text(encoding="utf-8"))  # Parse the generated schematic.
            self.assertGreater(len(generated_root.find_children("junction")), 0, msg="The regression fixture must generate junction dots.")  # Require junction coverage.
            reverse_result = kicad_sch_to_ltspice_netlist(str(schematic_path), str(round_trip_path), _CONVERT_SETTINGS)  # Convert the schematic back to a netlist.
            self.assertEqual(reverse_result, (True, "OK", 0), msg=f"Reverse conversion failed: {reverse_result}")  # Require successful reverse conversion.
            self.assertTrue(ltspice_netlist_structure_cmp(str(net_path), str(round_trip_path)), msg="Junction dots must not alter the traced net structure.")  # Require identical circuit structure.

    def test_missing_input_returns_invalid_netlist_file(self) -> None:  # Verify the missing input error contract.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the call.
            result = ltspice_netlist_to_kicad_sch(  # Call the conversion API with a nonexistent input.
                str(_NETLIST_DIRECTORY / "does_not_exist.net"),  # Use a path that cannot exist.
                str(Path(temporary_directory) / "does_not_exist.kicad_sch"),  # Use a writable output path.
                _CONVERT_SETTINGS,  # Pass the shared settings mapping.
            )  # Finish the conversion call.
            self.assertEqual(result[0], False, msg="Missing input files must fail conversion.")  # Require failure.
            self.assertEqual(result[1], "INVALID_NETLIST_FILE", msg="Missing input files must report the netlist error code.")  # Require the netlist error code.
            self.assertEqual(result[2], 0, msg="Path failures must report line zero.")  # Require the unknown line number.

    def test_invalid_settings_return_invalid_convert_settings(self) -> None:  # Verify the settings validation error contract.
        source_path = next(_NETLIST_DIRECTORY.glob("*.net"))  # Read one valid source file for the call.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the call.
            result = ltspice_netlist_to_kicad_sch(  # Call the conversion API with invalid settings.
                str(source_path),  # Pass the valid source path.
                str(Path(temporary_directory) / "ignored.kicad_sch"),  # Pass a writable output path.
                "not a mapping",  # Pass a non-mapping settings value.
            )  # Finish the conversion call.
            self.assertEqual(result, (False, "INVALID_CONVERT_SETTINGS", 0), msg="Non-mapping settings must fail with the settings error code.")  # Require the settings error tuple.

    def test_missing_kicad_path_returns_invalid_convert_settings(self) -> None:  # Verify that a missing kicad_path setting is rejected.
        source_path = next(_NETLIST_DIRECTORY.glob("*.net"))  # Read one valid source file for the call.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the call.
            result = ltspice_netlist_to_kicad_sch(  # Call the conversion API without a usable kicad_path setting.
                str(source_path),  # Pass the valid source path.
                str(Path(temporary_directory) / "ignored.kicad_sch"),  # Pass a writable output path.
                {"kicad_path": str(Path(temporary_directory) / "missing_kicad")},  # Pass a kicad_path that does not exist.
            )  # Finish the conversion call.
            self.assertEqual(result, (False, "INVALID_CONVERT_SETTINGS", 0), msg="Missing kicad_path directories must fail with the settings error code.")  # Require the settings error tuple.

    def test_invalid_layout_settings_return_invalid_convert_settings(self) -> None:  # Verify finite positive dimensions and an integral iteration budget.
        source_path = next(_NETLIST_DIRECTORY.glob("*.net"))  # Read one valid source file for each validation call.
        invalid_overrides = (  # Collect representative invalid layout values.
            {"kicad_sch_grid": 0},  # Reject a zero routing resolution.
            {"kicad_sch_page_width": float("nan")},  # Reject a non-finite page dimension.
            {"kicad_sch_page_height": "wide"},  # Reject a non-numeric page dimension.
            {"kicad_placement_iterations": -1},  # Reject a negative iteration budget.
            {"kicad_placement_iterations": 1.5},  # Reject a fractional iteration budget.
            {"kicad_placement_strategy": "random"},  # Reject unknown placement engines.
            {"kicad_evolutionary_population": 1},  # Require at least two chromosomes.
            {"kicad_evolutionary_generations": 0},  # Require at least one genetic generation.
            {"kicad_placement_seed": -1},  # Require a non-negative deterministic seed.
            {"kicad_routing_trials": 0},  # Require at least one complete route trial.
            {"kicad_routing_trials": 4},  # Reject unavailable route-order trials.
            {"kicad_trace_optimization_passes": -1},  # Reject negative cleanup budgets.
        )  # Finish the invalid settings table.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch output directory.
            for overrides in invalid_overrides:  # Exercise every invalid setting independently.
                with self.subTest(overrides=overrides):  # Isolate failures by setting value.
                    settings = dict(_CONVERT_SETTINGS)  # Start from the valid shared settings.
                    settings.update(overrides)  # Apply the invalid override.
                    result = ltspice_netlist_to_kicad_sch(str(source_path), str(Path(temporary_directory) / "ignored.kicad_sch"), settings)  # Run settings validation through the public API.
                    self.assertEqual(result, (False, "INVALID_CONVERT_SETTINGS", 0))  # Require the settings error contract.

    def test_invalid_output_path_returns_invalid_output_path(self) -> None:  # Verify the output path error contract.
        source_path = next(_NETLIST_DIRECTORY.glob("*.net"))  # Read one valid source file for the call.
        result = ltspice_netlist_to_kicad_sch(  # Call the conversion API with a non-path output.
            str(source_path),  # Pass the valid source path.
            12345,  # Pass a non-path-like output value.
            _CONVERT_SETTINGS,  # Pass the shared settings mapping.
        )  # Finish the conversion call.
        self.assertEqual(result, (False, "INVALID_OUTPUT_PATH", 0), msg="Non-path outputs must fail with the output path error code.")  # Require the output path error tuple.

    def test_invalid_netlist_returns_invalid_netlist_file(self) -> None:  # Verify that invalid netlists are rejected before conversion.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the invalid input and output.
            invalid_path = Path(temporary_directory) / "invalid.net"  # Derive the invalid netlist path.
            invalid_path.write_text("R1 a 0 1k\nY1 a b 1k\n.tran 1\n.backanno\n.end\n", encoding="utf-8")  # Write a netlist with an invalid device prefix.
            result = ltspice_netlist_to_kicad_sch(  # Call the conversion API on the invalid netlist.
                str(invalid_path),  # Pass the invalid netlist path.
                str(Path(temporary_directory) / "ignored.kicad_sch"),  # Pass a writable output path.
                _CONVERT_SETTINGS,  # Pass the shared settings mapping.
            )  # Finish the conversion call.
            self.assertEqual(result[0], False, msg="Invalid netlists must fail conversion.")  # Require failure.
            self.assertEqual(result[1], "INVALID_NETLIST_FILE", msg="Invalid netlists must report the netlist error code.")  # Require the netlist error code.
            self.assertGreater(result[2], 0, msg="Netlist failures must report the failing source line.")  # Require a real line number.

    def test_unknown_symbol_returns_unknown_symbol(self) -> None:  # Verify that unresolved devices report the unknown symbol error.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the crafted input and output.
            crafted_path = Path(temporary_directory) / "crafted.net"  # Derive the crafted netlist path.
            crafted_path.write_text(  # Write a valid netlist that references an unresolvable subcircuit.
                "R1 a 0 1k\nXU1 a b MissingSubckt\nR2 b 0 1k\n.tran 1\n.backanno\n.end\n",  # Use two resistors to keep nodes connected.
                encoding="utf-8",  # Write UTF-8 text.
            )  # Finish writing the crafted netlist.
            result = ltspice_netlist_to_kicad_sch(  # Call the conversion API on the crafted netlist.
                str(crafted_path),  # Pass the crafted netlist path.
                str(Path(temporary_directory) / "crafted.kicad_sch"),  # Pass a writable output path.
                _CONVERT_SETTINGS,  # Pass the shared settings mapping.
            )  # Finish the conversion call.
            self.assertEqual(result[0], False, msg="Unresolvable symbols must fail conversion.")  # Require failure.
            self.assertTrue(result[1].startswith("UNKNOWN_SYMBOL"), msg=f"Unresolvable symbols must report UNKNOWN_SYMBOL but returned: {result[1]}")  # Require the symbol error code.
            self.assertGreater(result[2], 0, msg="Symbol failures must report the element source line.")  # Require a real line number.

    def test_unknown_symbol_diagnostics_are_actionable(self) -> None:  # Require the error payload to name the ASY search surface and a close match.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the crafted input, output, and nested symbol.
            symbol_root = Path(temporary_directory)  # Use the scratch directory as the only configured search root.
            nested_directory = symbol_root / "lib" / "sym" / "MyParts"  # Build a nested LTspice-style category directory.
            nested_directory.mkdir(parents=True)  # Create the nested directory tree.
            close_symbol = _ROOT_DIRECTORY / "test_files" / "netlist_to_asc" / "symbols" / "LTC3895.asy"  # Reuse a real symbol as a close-stem decoy.
            (nested_directory / "MissingSubcktX.asy").write_bytes(close_symbol.read_bytes())  # Plant a close-stem symbol under the nested directory.
            crafted_path = symbol_root / "crafted.net"  # Derive the crafted netlist path.
            crafted_path.write_text(  # Write a valid netlist that references an unresolvable subcircuit.
                "R1 a 0 1k\nXU1 a b MissingSubckt\nR2 b 0 1k\n.tran 1\n.backanno\n.end\n",  # Use two resistors to keep nodes connected.
                encoding="utf-8",  # Write UTF-8 text.
            )  # Finish writing the crafted netlist.
            settings = dict(_CONVERT_SETTINGS)  # Copy the shared settings before overriding the symbol roots.
            settings["custom_search_paths"] = [str(symbol_root)]  # Search only the scratch root.
            result = ltspice_netlist_to_kicad_sch(str(crafted_path), str(symbol_root / "crafted.kicad_sch"), settings)  # Convert the crafted netlist.
            self.assertFalse(result[0], msg="Unresolvable symbols must fail conversion.")  # Require failure.
            self.assertIn("Tried ASY names: MissingSubckt.asy", result[1], msg="The error must name every candidate ASY basename.")  # Require the tried basenames.
            self.assertIn(f"Search roots: {symbol_root}", result[1], msg="The error must name every resolved root.")  # Require the resolved root.
            self.assertIn("Checked paths:", result[1], msg="The error must name the concrete paths attempted.")  # Require the attempted paths.
            self.assertIn("lib/sym/<category>/", result[1], msg="The error must explain the common nested layout.")  # Require the nested-layout note.
            self.assertIn(str(nested_directory), result[1], msg="The error must suggest the directory holding the closest match.")  # Require the close-match suggestion.

    def test_sparse_spice_order_x_line_resolves(self) -> None:  # Accept 39-node X lines against the sparse 28-pin LTC3895 symbol.
        settings = dict(_CONVERT_SETTINGS)  # Copy the shared settings before overriding the symbol roots.
        settings["custom_search_paths"] = [str(_ROOT_DIRECTORY / "test_files" / "netlist_to_asc" / "symbols")]  # Point at the sparse fixture symbols.
        normalized_ok, normalized = _SCH_MODULE._normalize_convert_settings(settings)  # Normalize the settings exactly like the public API.
        self.assertTrue(normalized_ok, msg="The fixture settings must normalize successfully.")  # Require usable settings.
        netlist_path = _ROOT_DIRECTORY / "test_files" / "netlist_to_asc" / "large_power_supply.net"  # Use the real 39-node fixture deck.
        lines = netlist_path.read_text(encoding="utf-8").splitlines()  # Read the fixture netlist lines.
        elements = _SCH_MODULE._parse_elements(lines)[1]  # Parse the netlist elements.
        model_types = _SCH_MODULE._build_model_types(lines, normalized)  # Parse the model polarity mapping.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for ASY conversions.
            result = _SCH_MODULE._build_component_records(elements, model_types, normalized, temporary_directory)  # Resolve every device.
            self.assertTrue(result[0], msg=f"Sparse SpiceOrder X lines must resolve but returned: {result[2]}")  # Require successful resolution.
            records = result[1][0]  # Read the resolved component records.
            buck = next(record for record in records if record["reference"] == "BUCKP")  # Select one LTC3895 instance.
            self.assertEqual(buck["lib_id"], "LTC3895:LTC3895", msg="The fixture LTC3895 must resolve through the ASY fallback.")  # Require the embedded ASY symbol.
            self.assertEqual(len(buck["pin_map"]), 28, msg="Only the 28 real SpiceOrder pins may map onto the 39-node X line.")  # Require the sparse mapping.
            self.assertNotIn(8, buck["pin_map"], msg="The unfilled SpiceOrder 9 position must stay unmapped.")  # Require the gap to stay unmapped.
            self.assertEqual(buck["pin_map"].get(9), "10", msg="Node index 9 must map onto SpiceOrder 10.")  # Require exact SpiceOrder mapping.
            self.assertEqual(buck["pin_map"].get(38), "39", msg="Node index 38 must map onto SpiceOrder 39.")  # Require the last SpiceOrder mapping.
            strict_settings = dict(normalized)  # Copy the normalized settings for the strict path.
            strict_settings["kicad_sch_allow_spice_order_gaps"] = False  # Disable the sparse SpiceOrder acceptance.
            with tempfile.TemporaryDirectory() as strict_directory:  # Create a second scratch directory for the strict attempt.
                strict_result = _SCH_MODULE._build_component_records(elements, model_types, strict_settings, strict_directory)  # Resolve every device strictly.
            self.assertFalse(strict_result[0], msg="Disabling sparse SpiceOrder gaps must reject the 39-node X line.")  # Require failure.
            self.assertTrue(str(strict_result[2]).startswith("UNKNOWN_SYMBOL"), msg=f"Expected UNKNOWN_SYMBOL but got: {strict_result[2]}")  # Require the resolution error.

    def test_recursive_asy_lookup_finds_nested_symbols(self) -> None:  # Resolve symbols placed in lib/sym/<category> directories.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch LTspice-style tree.
            symbol_root = Path(temporary_directory)  # Use the scratch directory as the only configured search root.
            fixture_symbols = _ROOT_DIRECTORY / "test_files" / "netlist_to_asc" / "symbols"  # Read the sparse fixture symbols.
            for category, symbol_name in (("PowerProducts", "LTC3895.asy"), ("SpecialFunctions", "LT4320-1.asy")):  # Place each symbol in its own nested category.
                nested_directory = symbol_root / "lib" / "sym" / category  # Build the nested category directory.
                nested_directory.mkdir(parents=True, exist_ok=True)  # Create the nested directory tree.
                (nested_directory / symbol_name).write_bytes((fixture_symbols / symbol_name).read_bytes())  # Copy the fixture symbol.
            settings = dict(_CONVERT_SETTINGS)  # Copy the shared settings before overriding the symbol roots.
            settings["custom_search_paths"] = [str(symbol_root)]  # Search only the nested scratch tree.
            normalized_ok, normalized = _SCH_MODULE._normalize_convert_settings(settings)  # Normalize the settings exactly like the public API.
            self.assertTrue(normalized_ok, msg="The nested fixture settings must normalize successfully.")  # Require usable settings.
            netlist_path = _ROOT_DIRECTORY / "test_files" / "netlist_to_asc" / "large_power_supply.net"  # Use the real multi-controller fixture deck.
            lines = netlist_path.read_text(encoding="utf-8").splitlines()  # Read the fixture netlist lines.
            elements = _SCH_MODULE._parse_elements(lines)[1]  # Parse the netlist elements.
            model_types = _SCH_MODULE._build_model_types(lines, normalized)  # Parse the model polarity mapping.
            with tempfile.TemporaryDirectory() as scratch_directory:  # Create a scratch directory for ASY conversions.
                result = _SCH_MODULE._build_component_records(elements, model_types, normalized, scratch_directory)  # Resolve every device.
            self.assertTrue(result[0], msg=f"Nested .asy symbols must resolve but returned: {result[2]}")  # Require successful nested resolution.
            records = result[1][0]  # Read the resolved component records.
            resolved_ids = {record["lib_id"] for record in records if record["prefix"] == "X"}  # Collect the X-device symbol identifiers.
            self.assertEqual(resolved_ids, {"LTC3895:LTC3895", "LT4320-1:LT4320-1"}, msg="The nested symbols must resolve through the ASY fallback.")  # Require the nested symbols.

    def test_sparse_spice_order_gap_round_trips(self) -> None:  # Preserve X-line node positions across a full round trip.
        sparse_asy = (  # Define a minimal symbol whose pins skip SpiceOrder 3.
            "Version 4.1\n"  # Use a supported ASY version header.
            "SymbolType BLOCK\n"  # Use the block symbol type.
            "RECTANGLE Normal 48 0 -48 -64\n"  # Draw a small body rectangle.
            "WINDOW 0 0 -32 Center 2\n"  # Place the value window.
            "SYMATTR Value SparsePart\n"  # Name the symbol value.
            "SYMATTR Prefix X\n"  # Use the subcircuit reference prefix.
            "SYMATTR Description Sparse SpiceOrder fixture\n"  # Describe the fixture.
            "PIN 48 -16 RIGHT 8\nPINATTR PinName P1\nPINATTR SpiceOrder 1\n"  # Define the first port.
            "PIN 48 -32 RIGHT 8\nPINATTR PinName P2\nPINATTR SpiceOrder 2\n"  # Define the second port.
            "PIN 48 -48 RIGHT 8\nPINATTR PinName P4\nPINATTR SpiceOrder 4\n"  # Define the fourth port, skipping SpiceOrder 3.
        )  # Finish the sparse symbol text.
        netlist_text = "R1 a 0 1k\nR2 b 0 1k\nR3 c 0 1k\nXU1 a b NC_gap c SparsePart\n.tran 1\n.backanno\n.end\n"  # Keep every real node connected while position 3 stays an exempt filler.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the symbol, netlist, and outputs.
            symbol_root = Path(temporary_directory)  # Use the scratch directory as the only configured search root.
            (symbol_root / "SparsePart.asy").write_text(sparse_asy, encoding="utf-8")  # Write the sparse symbol fixture.
            netlist_path = symbol_root / "sparse.net"  # Derive the crafted netlist path.
            netlist_path.write_text(netlist_text, encoding="utf-8")  # Write the crafted netlist.
            settings = dict(_CONVERT_SETTINGS)  # Copy the shared settings before overriding the symbol roots.
            settings["custom_search_paths"] = [str(symbol_root)]  # Search only the scratch root.
            schematic_path = symbol_root / "sparse.kicad_sch"  # Derive the generated schematic path.
            forward_result = ltspice_netlist_to_kicad_sch(str(netlist_path), str(schematic_path), settings)  # Generate the KiCad schematic.
            self.assertEqual(forward_result, (True, "OK", 0), msg=f"sparse SpiceOrder decks must convert: {forward_result}")  # Require successful forward conversion.
            round_trip_path = symbol_root / "sparse.rt.net"  # Derive the round-trip netlist path.
            reverse_result = kicad_sch_to_ltspice_netlist(str(schematic_path), str(round_trip_path), settings)  # Convert the schematic back.
            self.assertEqual(reverse_result, (True, "OK", 0), msg=f"sparse SpiceOrder schematics must convert back: {reverse_result}")  # Require successful reverse conversion.
            round_trip_lines = round_trip_path.read_text(encoding="utf-8").splitlines()  # Read the emitted netlist lines.
            x_node_tokens = []  # Collect the emitted X-line nodes.
            resistor_nodes = set()  # Collect the real resistor nodes.
            for raw_line in round_trip_lines:  # Walk every emitted device line.
                tokens = raw_line.split()  # Split the line into tokens.
                if not tokens:  # Skip blank lines.
                    continue  # Move to the next line.
                if tokens[0].upper().startswith("X"):  # Capture the X subcircuit call.
                    x_node_tokens = tokens[1:]  # Read the nodes and the trailing subcircuit name.
                elif tokens[0].upper().startswith("R"):  # Capture the resistor nodes.
                    resistor_nodes.update(node for node in tokens[1:3] if node not in {"0", "GND"})  # Record the non-ground nodes.
            self.assertEqual(len(x_node_tokens), 5, msg="The reverse conversion must emit four nodes plus the subcircuit name.")  # Require the gap-preserving node list.
            x_nodes = x_node_tokens[:-1]  # Drop the trailing subcircuit name.
            self.assertTrue(x_nodes[2].upper().startswith("NC"), msg="The uncovered SpiceOrder position must become an NC filler.")  # Require the filler.
            self.assertEqual({x_nodes[0], x_nodes[1], x_nodes[3]}, resistor_nodes, msg="Real nets must land on their SpiceOrder positions.")  # Require positionally correct connectivity.

    def test_wiring_retry_ladder_is_bounded_and_deterministic(self) -> None:  # Verify the attempt ladder order, seeds, and paper growth.
        attempts = _SCH_MODULE._wiring_attempt_ladder({"kicad_placement_seed": 3}, 10, 2)  # Build the default two-retry ladder.
        self.assertEqual([attempt["strategy"] for attempt in attempts], [None, "hybrid", "hybrid"], msg="The first attempt must keep the caller's strategy and retries must use the hybrid engine.")  # Require the strategy ladder.
        self.assertEqual([attempt["seed"] for attempt in attempts], [3, 4, 5], msg="Retry seeds must bump deterministically from the caller's seed.")  # Require the seed ladder.
        self.assertEqual([attempt["page"] for attempt in attempts], [None, "A3", "A2"], msg="Retries must grow A4 to A3 to A2.")  # Require the paper ladder.
        explicit = _SCH_MODULE._wiring_attempt_ladder({"kicad_sch_page_width": 297.0}, 10, 2)  # Keep the caller's explicit page.
        self.assertEqual([attempt["page"] for attempt in explicit], [None, None, None], msg="Explicit page sizes must never be overridden.")  # Require fixed-paper retries.
        self.assertEqual([attempt["seed"] for attempt in explicit], [0, 1, 2], msg="Fixed-paper retries must still bump the seed.")  # Require the seed ladder.
        self.assertEqual(len(_SCH_MODULE._wiring_attempt_ladder({}, 10, 0)), 1, msg="A zero retry budget must keep the single historical attempt.")  # Require the disabled retry path.

    def test_wiring_retries_reset_records_and_fall_back_to_hybrid(self) -> None:  # Verify retries restore record state and switch engines.
        records = [{"x": 1.0, "y": 2.0, "angle": 90.0, "routing_bounds": (0, 0, 0, 0), "pin_positions": {1: (0.0, 0.0)}, "property_layout": {}}]  # Seed transient routing state.
        success_body = ([], [], [], [], {}, [])  # Use an empty assembled schematic body for the retry success.
        with mock.patch.object(_SCH_MODULE, "_route_and_build", side_effect=[(False, None, "WIRING_GENERATION_ERROR: boom", 0), (True, success_body, "", 0)]) as routed:  # Fail once, then succeed.
            result = _SCH_MODULE._route_and_build_with_retries("uuid", records, {"kicad_placement_seed": 0})  # Run the retry ladder.
        self.assertTrue(result[0], msg="The retry ladder must return the first successful attempt.")  # Require success.
        self.assertEqual(routed.call_count, 2, msg="The ladder must stop at the first success.")  # Require two attempts.
        self.assertIsNone(routed.call_args_list[0].kwargs["forced_strategy"], msg="The first attempt must keep the caller's placement strategy.")  # Require the base strategy.
        self.assertEqual(routed.call_args_list[1].kwargs["forced_strategy"], "hybrid", msg="The retry must use the hybrid engine.")  # Require the fallback engine.
        self.assertEqual((records[0]["x"], records[0]["y"], records[0]["angle"]), (1.0, 2.0, 90.0), msg="Retries must restore the pre-placement record state.")  # Require the placement reset.
        for transient_key in ("routing_bounds", "pin_positions", "property_layout"):  # Walk every transient routing key.
            self.assertNotIn(transient_key, records[0], msg=f"Retries must clear the transient {transient_key} state.")  # Require the transient cleanup.

    def test_wiring_retries_stop_on_non_retryable_failure(self) -> None:  # Verify non-wiring failures never retry.
        records = [{"x": 0.0, "y": 0.0, "angle": 0.0}]  # Use a minimal record.
        with mock.patch.object(_SCH_MODULE, "_route_and_build", return_value=(False, None, "UNKNOWN_SYMBOL: nope", 5)) as routed:  # Always return a resolution failure.
            result = _SCH_MODULE._route_and_build_with_retries("uuid", records, {})  # Run the retry ladder.
        self.assertEqual(result, (False, None, "UNKNOWN_SYMBOL: nope", 5), msg="Non-wiring failures must pass through unchanged.")  # Require the original failure.
        self.assertEqual(routed.call_count, 1, msg="Non-wiring failures must not consume the retry budget.")  # Require a single attempt.

    def test_wiring_retries_enrich_exhausted_failure(self) -> None:  # Verify the exhausted ladder reports the attempt count.
        records = [{"x": 0.0, "y": 0.0, "angle": 0.0}]  # Use a minimal record.
        with mock.patch.object(_SCH_MODULE, "_route_and_build", side_effect=lambda *args, **kwargs: (False, None, "WIRING_GENERATION_ERROR: boom", 0)):  # Always fail.
            result = _SCH_MODULE._route_and_build_with_retries("uuid", records, {"kicad_sch_wiring_retries": 2})  # Run the full ladder.
        self.assertFalse(result[0], msg="The exhausted ladder must report failure.")  # Require failure.
        self.assertIn("all 3 deterministic placement/routing attempts failed", result[2], msg="The final error must name the bounded attempt count.")  # Require the attempt report.

    def test_retry_and_cache_settings_are_validated(self) -> None:  # Verify the new retry and cache settings reject malformed values.
        netlist_path = _ROOT_DIRECTORY / "kicad_convert" / "netlist" / "NPN1.net"  # Reuse a known-good reference deck.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the rejected outputs.
            output_path = Path(temporary_directory) / "settings.kicad_sch"  # Derive the scratch output path.
            for key, value in (("kicad_sch_wiring_retries", -1), ("kicad_sch_wiring_retries", 99), ("kicad_sch_wiring_retries", 1.5), ("kicad_symbol_cache", "yes")):  # Walk malformed settings.
                with self.subTest(setting=key, value=value):  # Isolate failures per setting.
                    result = ltspice_netlist_to_kicad_sch(str(netlist_path), str(output_path), dict(_CONVERT_SETTINGS, **{key: value}))  # Convert with the malformed setting.
                    self.assertEqual(result, (False, "INVALID_CONVERT_SETTINGS", 0), msg=f"{key}={value!r} must fail with the settings error code.")  # Require the settings error tuple.

    def test_power_overlap_description_reports_pin_and_coordinates(self) -> None:  # Verify the overlap diagnostic names the symbol, pin, and coordinates.
        origin_description = _SCH_MODULE._power_overlap_description({"reference": "#PWR26", "x": 12.7, "y": -3.81})  # Describe a power record without an attachment point.
        self.assertIn("'#PWR26'", origin_description, msg="The overlap diagnostic must name the power symbol.")  # Require the reference.
        self.assertIn("(12.7, -3.81)", origin_description, msg="The overlap diagnostic must report the symbol coordinates.")  # Require the coordinates.
        pin_description = _SCH_MODULE._power_overlap_description({"reference": "#PWR26", "x": 0.0, "y": 0.0, "pin_positions": {1: (25.4, 38.1)}})  # Describe a power record with a recorded attachment.
        self.assertIn("pin at (25.4, 38.1)", pin_description, msg="The overlap diagnostic must prefer the attachment pin position.")  # Require the pin position.


if __name__ == "__main__":  # Allow running the module directly for debugging.
    unittest.main()  # Execute the unit tests when invoked as a script.
