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


if __name__ == "__main__":
    unittest.main()
