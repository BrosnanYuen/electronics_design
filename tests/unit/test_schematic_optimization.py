"""Tests for the optimized schematic placement and physical grid router."""

from __future__ import annotations

import math
import unittest

from electronics_design.force_directed_placement import ForceDirectedPlacer
from electronics_design.force_directed_placement import PlacementConfig
from electronics_design.evolutionary_schematic_placement import EvolutionaryPlacementConfig
from electronics_design.evolutionary_schematic_placement import EvolutionarySchematicPlacer
from electronics_design.schematic_grid_router import GridRouter
from electronics_design.schematic_trace_optimizer import optimize_routed_traces
from electronics_design.ltspice_netlist_to_kicad_sch import _layout_visible_text
from electronics_design.ltspice_netlist_to_kicad_sch import _attach_symbol_on_net
from electronics_design.ltspice_netlist_to_kicad_sch import _measure_text_bounds
from electronics_design.ltspice_netlist_to_kicad_sch import _property_node
from electronics_design.ltspice_netlist_to_kicad_sch import _record_body_rect
from electronics_design.ltspice_netlist_to_kicad_sch import _symbol_body_bounds
from electronics_design.ltspice_netlist_to_kicad_sch import _TEXT_BOUND_HEIGHT
from electronics_design.ltspice_netlist_to_kicad_sch import _TEXT_CLEARANCE
from electronics_design.ltspice_netlist_to_kicad_sch import _text_rect_is_clear
from electronics_design.ltspice_netlist_to_kicad_sch import _text_width
from electronics_design.kicad_sexp_parser import parse_string


class TestGridRouter(unittest.TestCase):
    """Verify physical multi-terminal routing and foreign-net ownership."""

    def test_multi_terminal_route_physically_reaches_every_terminal(self) -> None:
        router = GridRouter(1.0, 0.0, 0.0, 12.0, 12.0)
        router.block_rectangle(4.0, 0.0, 6.0, 3.0)
        terminals = [(1.0, 1.0), (10.0, 1.0), (10.0, 10.0)]

        segments = router.route(terminals, net_id=1)

        self.assertIsNotNone(segments)
        assert segments is not None
        segment_points = {point for segment in segments for point in segment}
        self.assertTrue(set(terminals).issubset(segment_points))
        self.assertGreaterEqual(len(router.last_routed_sub_paths or []), 2)

    def test_soft_route_preserves_foreign_ownership_at_safe_crossing(self) -> None:
        router = GridRouter(1.0, 0.0, 0.0, 10.0, 10.0)
        vertical = router.route([(5.0, 0.0), (5.0, 10.0)], net_id=1)
        self.assertIsNotNone(vertical)

        self.assertIsNone(router.route([(0.0, 5.0), (10.0, 5.0)], net_id=2))
        horizontal = router.route([(0.0, 5.0), (10.0, 5.0)], net_id=2, soft=True)

        self.assertIsNotNone(horizontal)
        self.assertIn((5, 5), router.foreign_shared_cells(router.last_routed_cells or [], 2))
        self.assertEqual(router.owner_net[(5, 5)], 1)


class TestForceDirectedPlacer(unittest.TestCase):
    """Verify the compiled placement kernel and discrete final poses."""

    def test_compiled_forces_move_and_snap_components_inside_page(self) -> None:
        config = PlacementConfig(position_grid=1.0, edge_samples=2)
        placer = ForceDirectedPlacer(40.0, 30.0, config)
        placer.add_component("R1", 8.0, 15.0, 4.0, 2.0, [("1", -2.0, 0.0)])
        placer.add_component("R2", 30.0, 15.0, 4.0, 2.0, [("1", 2.0, 0.0)])
        placer.create_springs_from_nets({"signal": [("R1", "1"), ("R2", "1")]})

        forces, torques = placer.compute_forces_and_torques()
        self.assertTrue(all(math.isfinite(force.x) and math.isfinite(force.y) for force in forces.values()))
        self.assertTrue(all(math.isfinite(torque) for torque in torques.values()))
        placer.run(iterations=5)
        placer.snap_to_grid(1.0, 90.0)

        for component in placer.components:
            self.assertEqual(component.x, round(component.x))
            self.assertEqual(component.y, round(component.y))
            self.assertGreaterEqual(component.x, component.width / 2 + config.boundary_margin)
            self.assertLessEqual(component.x, 40.0 - component.width / 2 - config.boundary_margin)
            self.assertGreaterEqual(component.y, component.height / 2 + config.boundary_margin)
            self.assertLessEqual(component.y, 30.0 - component.height / 2 - config.boundary_margin)


class TestEvolutionaryPlacement(unittest.TestCase):
    """Verify deterministic evolutionary seeding before physics refinement."""

    @staticmethod
    def _placer() -> ForceDirectedPlacer:
        placer = ForceDirectedPlacer(80.0, 60.0, PlacementConfig(position_grid=1.0))
        placer.add_component("R1", 10.0, 20.0, 6.0, 3.0, [("1", -3.0, 0.0), ("2", 3.0, 0.0)])
        placer.add_component("R2", 70.0, 40.0, 6.0, 3.0, [("1", -3.0, 0.0), ("2", 3.0, 0.0)])
        placer.create_springs_from_nets({"signal": [("R1", "2"), ("R2", "1")]})
        return placer

    def test_seeded_search_is_deterministic_and_applies_grid_poses(self) -> None:
        config = EvolutionaryPlacementConfig(population_size=6, generations=3, random_seed=17)
        first, second = self._placer(), self._placer()

        first_cost = EvolutionarySchematicPlacer(first, 1.0, config).optimize()
        second_cost = EvolutionarySchematicPlacer(second, 1.0, config).optimize()

        self.assertTrue(math.isfinite(first_cost))
        self.assertEqual(first_cost, second_cost)
        self.assertEqual(
            [(component.x, component.y, component.rotation) for component in first.components],
            [(component.x, component.y, component.rotation) for component in second.components],
        )
        self.assertTrue(all(component.x == round(component.x) and component.y == round(component.y) for component in first.components))


class TestTraceOptimizer(unittest.TestCase):
    """Verify cleanup preserves terminals, corners, and branch junctions."""

    def test_unprotected_collinear_chain_is_consolidated(self) -> None:
        optimized = optimize_routed_traces(
            {"n": [((0.0, 0.0), (1.0, 0.0)), ((1.0, 0.0), (2.0, 0.0))]}
        )

        self.assertEqual(optimized["n"], [((0.0, 0.0), (2.0, 0.0))])

    def test_collinear_degree_two_nodes_merge_but_terminals_remain(self) -> None:
        traces = {
            "n": [
                ((0.0, 0.0), (1.0, 0.0)),
                ((1.0, 0.0), (2.0, 0.0)),
                ((2.0, 0.0), (3.0, 0.0)),
                ((2.0, 0.0), (2.0, 1.0)),
            ]
        }

        optimized = optimize_routed_traces(traces, protected_points_by_net={"n": [(1.0, 0.0)]})

        self.assertIn(((0.0, 0.0), (1.0, 0.0)), optimized["n"])
        self.assertIn(((1.0, 0.0), (2.0, 0.0)), optimized["n"])
        self.assertEqual(len(optimized["n"]), 4, msg="Protected terminals and degree-three branch points must not be removed.")


class TestVisibleTextLayout(unittest.TestCase):
    """Verify visible properties and labels avoid schematic geometry."""

    def test_split_kicad_symbol_sections_form_one_body_bound(self) -> None:
        symbol = parse_string(
            '(symbol "R" (symbol "R_0_1" (rectangle (start -1 -2) (end 1 2))) '
            '(symbol "R_1_1" (pin passive line (at 0 3 270) (length 1))))'
        )

        self.assertEqual(_symbol_body_bounds(symbol, "R", include_pins=False, combine_sections=True), (-1.0, -2.0, 1.0, 2.0))
        self.assertEqual(_symbol_body_bounds(symbol, "R", include_pins=True, combine_sections=True), (-1.0, -2.0, 1.0, 3.0))

    def test_fields_and_label_receive_non_overlapping_positions(self) -> None:
        records = [
            {"reference": "R1", "value": "10k", "power": False, "x": 10.0, "y": 10.0, "angle": 0.0, "body_bounds": (-2.0, -1.0, 2.0, 1.0), "text_bounds": (-4.0, -3.0, 4.0, 3.0)},
            {"reference": "C1", "value": "100n", "power": False, "x": 24.0, "y": 10.0, "angle": 0.0, "body_bounds": (-2.0, -1.0, 2.0, 1.0), "text_bounds": (-4.0, -3.0, 4.0, 3.0)},
        ]
        segments = {"signal": [((5.0, 15.0), (30.0, 15.0))]}

        label_layout = _layout_visible_text(records, ["signal"], segments, {}, 1.0, 40.0, 30.0)

        bodies = [_record_body_rect(record, "text_bounds") for record in records]
        wires = segments["signal"]
        occupied = []
        for record in records:
            self.assertNotEqual(record["property_layout"]["Reference"][:2], record["property_layout"]["Value"][:2])
            for key, value in (("Reference", record["reference"]), ("Value", record["value"])):
                x, y, justification = record["property_layout"][key]
                width, height = _measure_text_bounds(value)
                rect = (x, y - height / 2.0, x + width, y + height / 2.0) if justification == "left" else (x - width, y - height / 2.0, x, y + height / 2.0)
                self.assertTrue(_text_rect_is_clear(rect, bodies, wires, occupied))
                occupied.append(rect)
        self.assertIn("signal", label_layout)
        label_anchor, label_justification, hidden = label_layout["signal"]
        self.assertFalse(hidden)
        label_width = _text_width("signal")
        label_x, label_y = label_anchor
        if "left" in label_justification:
            label_left, label_right = label_x, label_x + label_width
        else:
            label_left, label_right = label_x - label_width, label_x
        if "bottom" in label_justification:
            label_top, label_bottom = label_y - _TEXT_CLEARANCE - _TEXT_BOUND_HEIGHT, label_y - _TEXT_CLEARANCE
        elif "top" in label_justification:
            label_top, label_bottom = label_y + _TEXT_CLEARANCE, label_y + _TEXT_CLEARANCE + _TEXT_BOUND_HEIGHT
        else:
            label_top, label_bottom = label_y - _TEXT_BOUND_HEIGHT / 2.0, label_y + _TEXT_BOUND_HEIGHT / 2.0
        self.assertTrue(_text_rect_is_clear((label_left, label_top, label_right, label_bottom), bodies, wires, occupied))

    def test_quarter_turned_symbol_fields_are_counter_rotated(self) -> None:
        record = {
            "x": 10.0,
            "y": 20.0,
            "angle": 90.0,
            "power": False,
            "property_layout": {"Reference": (7.0, 8.0, "left")},
        }

        property_node = _property_node("R5", "Reference", "R5", record, visible=True)
        at_node = property_node.find_child("at")

        self.assertIsNotNone(at_node)
        assert at_node is not None
        self.assertEqual([child.value for child in at_node.children], [7.0, 8.0, 270.0])

    def test_measured_text_bounds_match_kicad_stroke_font(self) -> None:
        left_width, left_height = _measure_text_bounds("LEFT", 2.54)
        self.assertAlmostEqual(left_width, (0.5922 + 0.6636 + 0.6279 + 0.5564 + 3 * 0.0149) * 2.54, places=3)
        self.assertAlmostEqual(left_height, 1.27 * 2.54, places=3)
        self.assertAlmostEqual(_measure_text_bounds("A", 2.54)[0], 0.6279 * 2.54, places=3)
        self.assertAlmostEqual(_measure_text_bounds("i", 1.27)[0], 0.3421 * 1.27, places=3)
        empty_width, empty_height = _measure_text_bounds("", 1.27)
        self.assertEqual(empty_width, 0.0)
        self.assertGreater(empty_height, 0.0)
        self.assertGreater(_measure_text_bounds("AA", 2.54)[0], _measure_text_bounds("A", 2.54)[0])
        self.assertGreater(_measure_text_bounds("M", 2.54)[0], _measure_text_bounds("i", 2.54)[0])
        self.assertGreater(_measure_text_bounds("A A", 2.54)[0], _measure_text_bounds("AA", 2.54)[0])

    def test_property_justification_matches_collision_checked_box(self) -> None:
        for justification in ("left", "right"):
            record = {
                "x": 10.0,
                "y": 20.0,
                "angle": 0.0,
                "power": False,
                "property_layout": {"Reference": (7.0, 8.0, justification)},
            }
            property_node = _property_node("R5", "Reference", "R5", record, visible=True)
            effects_node = property_node.find_child("effects")
            self.assertIsNotNone(effects_node)
            assert effects_node is not None
            justify_node = effects_node.find_child("justify")
            self.assertIsNotNone(justify_node)
            assert justify_node is not None
            values = [child.value for child in justify_node.children if child.is_atom]
            self.assertEqual(values, [justification])

    def test_power_attachment_avoids_foreign_wire_crossing(self) -> None:
        record = {
            "pin_map": {0: "1"},
            "pins": {"1": (0.0, 0.0, "GND")},
            "body_bounds": (0.0, 0.0, 0.0, 0.0),
        }

        _attach_symbol_on_net(
            record,
            [((0.0, 0.0), (4.0, 0.0))],
            [],
            1.0,
            [((1.0, -2.0), (1.0, 2.0))],
        )

        self.assertEqual(record["pin_positions"], {"1": (2.0, 0.0)})


if __name__ == "__main__":
    unittest.main()
