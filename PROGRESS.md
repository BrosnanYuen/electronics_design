# PROGRESS

Status snapshot: **implementation complete and verified** on 2026-08-16.

## Goal

Refactor `ltspice_netlist_to_kicad_sch` to use self-contained kicad-tools-style force-directed placement and physical grid routing while preserving structural round trips for the complete netlist corpus.

## Completed work

### Netlist compatibility fixes

- Added the missing `.tran 1` directive to `Sawtooth-oscillator.net` and `Variable-duty-cycle-square-wave.net`.
- Allowed single-port probe nodes owned only by `B` behavioral sources in the connectivity validator.
- Allowed the reverse KiCad converter to emit behavioral-source probe pins without treating them as ordinary disconnected pins.
- Configured the tests to resolve CCCS, CCVS, and op-amp `.asy` fallback symbols from repository search paths.
- Skip node-free `K` mutual-inductance statements during schematic generation and exclude zero-node elements from structural round-trip comparison.

### Force-directed placement

- Added `src/electronics_design/force_directed_placement.py`, adapted from the MIT-licensed kicad-tools placement model (Copyright (c) 2024 RJ Walters).
- Component outlines repel each other, net pins attract through Hooke-law springs, page edges repel and clamp bodies, and torsion biases rotations to 90-degree poses.
- Body and boundary force hot loops use a cached Numba kernel.
- Positions and rotations snap to the configured schematic grid after simulation.
- Fixed components correctly repel movable components while remaining stationary.

### Physical grid routing

- Added `src/electronics_design/schematic_grid_router.py`, adapted from the MIT-licensed kicad-tools grid/pathfinder approach.
- Multi-terminal nets grow one connected tree using multi-source/multi-goal A* rather than repeatedly searching from a fixed root.
- The A* cell search uses array-backed ownership and a cached Numba kernel with direction-aware turn costs.
- Component graphics block routing cells; pin cells are reserved for their own nets.
- Hard routing prevents foreign ownership. Soft routing is accepted only for unambiguous perpendicular interior crossings; turns, endpoints, overlaps, and foreign pin cells remain unsafe.
- If A* cannot route a net, the bounded fallback emits physically connected pin-to-trunk wires below the page. It never substitutes disconnected net-label stubs.
- Per-branch path metadata prevents phantom segments between independent tree branches.
- Exact pin lead stubs preserve reverse-converter union semantics.
- Late copper for single-pin and power-only nets checks complete foreign segment geometry, preventing endpoint-on-wire shorts.

### Symbol lookup and performance

- KiCad library files are cached process-wide by path and file metadata.
- Bare symbol names defer broad KiCad-library scanning until configured `.asy` fallbacks have been tried.
- Repeated symbol-shape resolution is cached while component records are built.
- Dense representative placement and routing now complete in seconds rather than stalling.

### Configuration and documentation

The following optional `convert_settings` keys are validated and documented:

- `kicad_sch_grid` (default `1.27` mm)
- `kicad_placement_iterations` (default `250`)
- `kicad_sch_page_width` (default `297.0` mm)
- `kicad_sch_page_height` (default `210.0` mm)

README and LTspice behavior/error documentation now describe the physical routing model, Numba acceleration, kicad-tools attribution, behavioral probe exemption, and `K` handling.

## Verification

- Six representative circuits, including both dense common-emitter and three-phase designs: forward conversion, KiCad validation, reverse conversion, LTspice validation, and structural comparison all passed in 2.59 seconds.
- Complete `tests.unit.test_netlist_to_kicad_sch` corpus test, including layout-setting validation: **8 tests passed**.
- Added focused tests for multi-terminal physical routing, safe soft crossings with preserved ownership, and compiled placement/snap behavior.
- Complete suite: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` → **210 tests passed** in 60.49 seconds.

## Files added

- `src/electronics_design/force_directed_placement.py`
- `src/electronics_design/schematic_grid_router.py`
- `tests/unit/test_schematic_optimization.py`

## Remaining optional work

- Review selected generated schematics visually in KiCad and tune placement constants if a different aesthetic is desired.
- Decide whether the generated `kicad_convert/kicad_sch/*.kicad_sch` corpus artifacts should be checked in.
- Commit only when explicitly requested.
