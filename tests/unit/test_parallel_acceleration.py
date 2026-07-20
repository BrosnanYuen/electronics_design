"""Correctness and dispatch tests for the Numba/threaded hot paths."""

from __future__ import annotations

import os
import unittest
from unittest import mock

import networkx as nx
import numpy as np

from electronics_design import autoroute
from electronics_design import pathtracing
from electronics_design._parallel import configure_parallel_workers
from electronics_design._parallel import parallel_worker_count
from electronics_design.ltspice_netlist_plot_networkx import _fill_canvas


class TestParallelAcceleration(unittest.TestCase):
    def tearDown(self) -> None:
        configure_parallel_workers({})

    def test_large_intersection_matrix_uses_parallel_numba_kernel(self) -> None:
        wires = np.asarray(
            [[0, wire_y, 128, wire_y] for wire_y in range(65)],
            dtype=np.int64,
        )
        obstacles = np.asarray(
            [[obstacle_x, -16, obstacle_x, 96] for obstacle_x in range(64)],
            dtype=np.int64,
        )
        with mock.patch.object(
            pathtracing,
            "intersection_matrix_parallel",
            wraps=pathtracing.intersection_matrix_parallel,
        ) as parallel_kernel:
            intersections = pathtracing._wire_obstacle_intersection_matrix(wires, obstacles)

        parallel_kernel.assert_called_once()
        self.assertEqual(intersections.shape, (65, 64))
        self.assertTrue(np.all(intersections))

    def test_compiled_shortest_path_preserves_deterministic_tie_break(self) -> None:
        graph = nx.Graph()
        graph.add_edge((0, 0), (0, 16), length=16)
        graph.add_edge((0, 16), (16, 16), length=16)
        graph.add_edge((0, 0), (16, 0), length=16)
        graph.add_edge((16, 0), (16, 16), length=16)

        result = autoroute._shortest_point_path_with_segment_penalty(
            graph,
            (0, 0),
            (16, 16),
        )

        self.assertEqual(result, [(0, 0), (0, 16), (16, 16)])
        self.assertIn("_orientation_route_csr", graph.graph)

    def test_worker_count_accepts_environment_and_conversion_override(self) -> None:
        with mock.patch.dict(os.environ, {"ELECTRONICS_DESIGN_PARALLEL_WORKERS": "3"}):
            self.assertTrue(configure_parallel_workers({}))
            self.assertEqual(parallel_worker_count(), min(3, os.cpu_count() or 1))

        self.assertTrue(configure_parallel_workers({"parallel_workers": 2}))
        self.assertEqual(parallel_worker_count(), min(2, os.cpu_count() or 1))
        self.assertFalse(configure_parallel_workers({"parallel_workers": 0}))
        self.assertFalse(configure_parallel_workers({"parallel_workers": True}))

    def test_parallel_canvas_fill_preserves_rgb_layout(self) -> None:
        canvas = bytearray(4 * 3 * 3)

        _fill_canvas(canvas, 4, 3, (11, 22, 33))

        pixels = np.frombuffer(canvas, dtype=np.uint8).reshape(-1, 3)
        np.testing.assert_array_equal(
            pixels,
            np.tile(np.asarray([[11, 22, 33]], dtype=np.uint8), (12, 1)),
        )


if __name__ == "__main__":
    unittest.main()
