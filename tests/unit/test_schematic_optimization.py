"""Tests for the optimized schematic placement and physical grid router."""

from __future__ import annotations

import math
import unittest

from electronics_design.force_directed_placement import ForceDirectedPlacer
from electronics_design.force_directed_placement import PlacementConfig
from electronics_design.schematic_grid_router import GridRouter


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


if __name__ == "__main__":
    unittest.main()
