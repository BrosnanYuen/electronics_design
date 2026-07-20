# Test and Function Profile

Generated: 2026-07-19

## Baseline

Command:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_all_tests.py
```

Result: **OK**

- Unit suite: 163 tests in 63.598 seconds.
- Integration suite: 11 tests in 0.578 seconds.
- Total: 174 tests.

## Method

Two additional passes were used:

1. The exact test runner was executed under Python `cProfile`. This provides
   package-function call counts, self time, and cumulative time. Raw profiler
   data was written to `/tmp/electronics_design_tests.prof` and is not part of
   the repository.
2. A timing-only `unittest` pass recorded wall-clock time between each
   test's `startTest` and `stopTest`, including that test's setup and teardown.
   It wrote intermediate data to `/tmp/electronics_design_test_timings.json`.

The profiler pass passed all tests: 163 unit tests in 237.336 profiled
seconds and 11 integration tests in 0.681 profiled seconds. Profiler times
are intentionally not comparable to the baseline because instrumentation adds
substantial overhead. The timing-only pass measured 163 unit tests in 55.786
seconds and 11 integration tests in 0.576 seconds; rankings below use that
pass.

## Post-optimization validation

After the routing, obstacle-checking, symbol-lookup, wire-grouping, and canvas
optimizations, the exact command above was run again:

- Unit suite: 163 tests in 47.808 seconds.
- Integration suite: 11 tests in 0.204 seconds.
- Total: 174 tests in 48.012 seconds.

This is 16.164 seconds, or approximately 25.2%, below the 64.176-second
baseline while preserving the complete test result.

The implementation uses bounded `ThreadPoolExecutor` batches for independent
NumPy obstacle checks, visibility-edge construction, route-candidate attempts,
and symbol-file discovery/definition loading. The default worker count is
derived from available CPUs and capped at eight; it can be overridden with
`ELECTRONICS_DESIGN_PARALLEL_WORKERS` or the `parallel_workers` conversion
setting. Results are collected in input order so routing and lookup precedence
remain deterministic. The sequential shortest-path search remains sequential
because each Dijkstra state depends on prior relaxation, but its neighbors and
edge lengths are now precomputed once.

Additional speedups replace repeated scalar scans with vectorized obstacle
checks, interval/union-find wire connectivity, endpoint-indexed wire grouping,
cached symbol path enumeration, and bulk canvas filling. Netlist-to-ASC
routing continues to create physical component-to-component wires; no
component-count or disconnected-label fallback was introduced.

## Slowest tests

Times include each test method's setup and teardown. The four dominant tests
account for most of the unit-suite runtime:

| Test | Time (s) |
|---|---:|
| `test_autoplace_symbol_pose.TestLtspiceAutoplaceSymbolPose.test_all_valid_convert_symbol_layouts` | 22.796 |
| `test_netlist_to_asc.TestNetlistToAsc.test_large_power_supply_routes_without_external_ltspice_paths` | 11.960 |
| `test_symbol_estimate.TestLtspiceSymbolEstimate.test_all_symbol_estimate_fixtures` | 6.414 |
| `test_autoplace_symbol_pose.TestLtspiceAutoplaceSymbolPose.test_routing_regressions_round_trip_structurally` | 6.332 |
| `test_netlist_to_symbol_initial.TestNetlistToSymbolInitial.test_all_valid_convert_fixtures` | 0.732 |
| `test_netlist_to_asc.TestNetlistToAsc.test_selected_valid_convert_fixtures` | 0.721 |
| `test_asc_cmp.TestAscComparison.test_invalid_comparison_pairs` | 0.720 |
| `test_asc_cmp.TestAscComparison.test_valid_comparison_pairs` | 0.664 |
| `test_asc_cmp.TestAscComparison.test_structure_comparison_accepts_drawing_without_analysis_directive` | 0.635 |
| `test_asc_to_netlist.TestAscToNetlist.test_all_valid_convert_fixtures` | 0.532 |
| `test_extended_ltspice_apis.TestExtendedLtspiceApis.test_plot_selected_repository_samples` | 0.494 |
| `test_voltage_must_have_dc.TestVoltageMustHaveDc.test_end_to_end_netlist_to_asc_uses_normalized_voltage` | 0.350 |
| `test_netlist_to_asc.TestNetlistToAsc.test_missing_x_symbol_reports_instance_and_search_advice` | 0.344 |
| `test_netlist_symbol_wire_to_asc.TestNetlistSymbolWireToAsc.test_all_valid_convert_fixtures` | 0.258 |
| `test_auto_route_wires.TestAutoRouteWires.test_valid_route_fixtures` | 0.250 |

## Slowest package functions by cumulative time

Cumulative time includes time spent in called functions, so these values are
not additive. They show which call paths dominate the profiler run.

| Function | Location | Calls | Cumulative (s) |
|---|---|---:|---:|
| `ltspice_autoplace_symbol_pose` | `src/electronics_design/ltspice_autoplace_symbol_pose.py:145` | 134 | 193.229 |
| `ltspice_netlist_to_wiring` | `src/electronics_design/ltspice_netlist_to_wiring.py:68` | 41 | 120.025 |
| `_route_all_nets` | `src/electronics_design/ltspice_netlist_to_wiring.py:516` | 41 | 119.991 |
| `_route_single_net` | `src/electronics_design/ltspice_netlist_to_wiring.py:560` | 323 | 119.988 |
| `_route_net_exit_points` | `src/electronics_design/ltspice_netlist_to_wiring.py:619` | 312 | 116.190 |
| `_route_net_exit_points_with_obstacles` | `src/electronics_design/ltspice_netlist_to_wiring.py:647` | 315 | 116.063 |
| `ltspice_netlist_to_asc` | `src/electronics_design/ltspice_netlist_to_asc.py:17` | 6 | 115.487 |
| `_build_symbol_filepath_lookup` | `src/electronics_design/ltspice_asc_to_netlist.py:480` | 784 | 95.519 |
| `get_ltspice_asc_symbol_info` | `src/electronics_design/ltspice_asc_to_netlist.py:170` | 517 | 95.147 |
| `ltspice_resolve_symbol_pose` | `src/electronics_design/ltspice_resolve_symbol_pose.py:34` | 312 | 92.147 |
| `_build_visibility_graph_for_terminals` | `src/electronics_design/autoroute.py:158` | 43 | 73.819 |
| `_point_hits_any_obstacle` | `src/electronics_design/autoroute.py:521` | 3,818,925 | 42.285 |
| `_build_visibility_graph` | `src/electronics_design/autoroute.py:291` | 43 | 30.167 |
| `_route_with_visibility_graph` | `src/electronics_design/autoroute.py:407` | 43 | 29.573 |
| `_shortest_point_path_with_segment_penalty` | `src/electronics_design/autoroute.py:442` | 43 | 29.314 |
| `_add_visible_edges` | `src/electronics_design/autoroute.py:337` | 16,645 | 27.084 |
| `_build_candidate_points_for_terminals` | `src/electronics_design/autoroute.py:134` | 63 | 24.310 |
| `_geometry_for_orientation` | `src/electronics_design/ltspice_autoplace_symbol_pose.py:1455` | 11,221 | 23.781 |
| `_wire_obstacle_intersection_matrix` | `src/electronics_design/pathtracing.py:71` | 193,214 | 21.181 |
| `ltspice_symbol_estimate` | `src/electronics_design/ltspice_symbol_estimate.py:37` | 15 | 21.055 |

## Slowest package functions by self time

Self time excludes time spent in child calls and is the better indicator of
where the function's own implementation spends CPU time.

| Function | Location | Calls | Self (s) | Cumulative (s) |
|---|---|---:|---:|---:|
| `_point_hits_any_obstacle` | `src/electronics_design/autoroute.py:521` | 3,818,925 | 36.793 | 42.285 |
| `_wire_obstacle_intersection_matrix` | `src/electronics_design/pathtracing.py:71` | 193,214 | 20.599 | 21.181 |
| `_shortest_point_path_with_segment_penalty` | `src/electronics_design/autoroute.py:442` | 43 | 11.881 | 29.314 |
| `_build_symbol_filepath_lookup` | `src/electronics_design/ltspice_asc_to_netlist.py:480` | 784 | 3.855 | 95.519 |
| `_add_visible_edges` | `src/electronics_design/autoroute.py:337` | 16,645 | 3.617 | 27.084 |
| `place_wires_into_groups` | `src/electronics_design/pathtracing.py:151` | 2,871 | 3.217 | 3.279 |
| `_fill_canvas` | `src/electronics_design/ltspice_netlist_plot_networkx.py:523` | 17 | 1.637 | 1.637 |
| `_load_symbol_definition` | `src/electronics_design/ltspice_asc_to_netlist.py:523` | 33,652 | 1.571 | 3.565 |
| `are_wires_connected` | `src/electronics_design/pathtracing.py:32` | 167,001 | 0.953 | 1.573 |
| `_build_candidate_points_for_terminals` | `src/electronics_design/autoroute.py:134` | 63 | 0.832 | 24.310 |
| `_route_simple_orthogonal` | `src/electronics_design/autoroute.py:177` | 932 | 0.740 | 11.908 |
| `_route_net_exit_points_with_obstacles` | `src/electronics_design/ltspice_netlist_to_wiring.py:647` | 315 | 0.669 | 116.063 |
| `_build_visibility_graph` | `src/electronics_design/autoroute.py:291` | 43 | 0.642 | 30.167 |
| `are_wires_intersecting_obstacles_detailed` | `src/electronics_design/pathtracing.py:131` | 30,150 | 0.608 | 0.750 |
| `_validate_generated_route` | `src/electronics_design/autoroute.py:492` | 166,962 | 0.616 | 9.815 |

## Findings

- The primary bottleneck is physical net routing invoked by autoplace and
  netlist-to-ASC conversion. `ltspice_netlist_to_wiring`, `_route_all_nets`,
  and `_route_single_net` all lead into exit-point routing and the autorouter.
- `_point_hits_any_obstacle` is the largest self-time hotspot: 36.793 seconds
  across 3.8 million calls. `_wire_obstacle_intersection_matrix` is next at
  20.599 seconds across 193,214 calls.
- The visibility-graph path search is the dominant cumulative autorouting
  path. Candidate generation, visible-edge construction, and shortest-path
  selection together are repeatedly exercised by the four slowest tests.
- Symbol lookup and pose resolution are a secondary hotspot. Repeated
  `_build_symbol_filepath_lookup`, `get_ltspice_asc_symbol_info`, and
  `ltspice_resolve_symbol_pose` calls account for large cumulative time in
  conversion and autoplace tests.

The highest-value optimization targets are therefore obstacle intersection
checks and repeated visibility-graph construction, followed by caching or
reducing repeated symbol-file lookup and pose-resolution work. Any routing
optimization must preserve the repository requirement that component-to-
component nets remain physically wired.
