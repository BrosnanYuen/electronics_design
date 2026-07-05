# electronics_design

Python library for validating, converting, plotting, and comparing LTspice schematic (`.asc`), symbol (`.asy`), and netlist (`.net`) files.  Also supports symbol-pose resolution, automatic symbol placement, and orthogonal wire routing from netlists.

## API Reference

### ASC Validation

| Function | Returns |
|---|---|
| `is_valid_ltspice_asc_header(filepath)` | `(bool, str)` |
| `is_valid_ltspice_asc_spacing(filepath)` | `(bool, str)` |
| `is_valid_ltspice_asc_footer(filepath)` | `(bool, str)` |
| `is_valid_ltspice_asc_file(filepath)` | `(bool, str)` |

- **Header** requires first nonblank line to be `Version` / `VERSION` and second to be `SHEET`.
- **Spacing** validates keyword support and token structure of every ASC record.
- **Footer** ensures at least one simulation analysis directive (`.tran`, `.ac`, `.dc`, `.op`, `.tf`, `.noise`, `.fra`) is present in a `TEXT !...` record.
- **Whole-file** composes header, spacing, and footer validators.

Error messages: `"File not found!"`, `"No permission to read file!"`, or `"<type> information is invalid! Line <n>"`.

### Netlist Validation

| Function | Returns |
|---|---|
| `is_valid_ltspice_netlist_format(filepath)` | `(bool, str)` |
| `is_valid_ltspice_netlist_footer(filepath)` | `(bool, str)` |
| `is_ltspice_netlist_structure_connected(filepath)` | `(bool, str)` |
| `is_valid_ltspice_netlist_file(filepath)` | `(bool, str)` |

- **Format** checks line classification (device prefixes, dot directives, continuations, comments) and minimum token counts.
- **Footer** requires at least one analysis directive, final line `.end`, penultimate line `.backanno`.
- **Connected** ensures every non-ground, non-`NC*` node appears on at least two device ports.
- **Whole-file** composes the three validators above.

### ASY Validation & Info

| Function | Returns |
|---|---|
| `is_valid_ltspice_asy(filepath)` | `(bool, str)` |
| `get_ltspice_asy_size(filepath)` | `np.ndarray([[min_x, min_y], [max_x, max_y]])` |
| `get_ltspice_asy_pins(filepath)` | `[[x, y, "PinName", spice_order], ...]` |

`get_ltspice_asy_size` and `get_ltspice_asy_pins` raise `ValueError` on invalid inputs.

### Netlist Comparison

| Function | Returns |
|---|---|
| `ltspice_netlist_footer_cmp(filepath1, filepath2)` | `bool` |
| `ltspice_netlist_structure_cmp(filepath1, filepath2)` | `bool` |

- **Footer comparison** normalizes the post-device footer region and checks equivalence.
- **Structure comparison** builds isomorphic component-to-net graphs; ignores instance names, net names, and footer directives.

### Schematic Comparison

| Function | Returns |
|---|---|
| `ltspice_asc_structure_cmp(filepath1, filepath2, convert_settings)` | `(bool, str, int)` |

Converts both ASC files to netlists and compares their structure.  Returns `(True, "", 0)` on match or `(False, "ASC structures are different!", <line>)` on mismatch.

### Schematic Conversion

| Function | Returns |
|---|---|
| `ltspice_asc_to_netlist(asc_filepath, net_filepath_out, convert_settings)` | `(bool, str, int)` |
| `get_ltspice_asc_symbol_info(asc_filepath, convert_settings)` | `{instance_name: {SYMBOL, X, Y, ORIENTATION, RECTANGLE, PINS, ...}, ...}` |

- `ltspice_asc_to_netlist` resolves symbols and library files from `convert_settings`, generates a validated netlist. Error codes include `UNKNOWN_SYMBOL`, `UNCONNECTED_SYMBOL_PIN`, `INVALID_GENERATED_NETLIST`, etc.
- `get_ltspice_asc_symbol_info` returns absolute-coordinate symbol pin and rectangle data keyed by instance name. Raises `ValueError` on failure.

### Schematic Plotting

| Function | Returns |
|---|---|
| `ltspice_asc_plot_schemdraw(asc_filepath, schemdraw_imagepath_out, width=1920, height=1080, convert_settings=None)` | `(bool, str)` |
| `ltspice_netlist_plot_networkx(netlist_filepath, networkx_imagepath_out, width=1920, height=1080)` | `(bool, str)` |

Uses schemdraw (ASC) and networkx (netlist) to render images. Supports `.png`, `.svg`, `.jpg`, `.jpeg` output.

### Symbol Pose Pipeline

| Function | Returns |
|---|---|
| `ltspice_netlist_to_symbol_initial(netlist_filepath, symbol_json_filepath_out, convert_settings)` | `(bool, str, int)` |
| `ltspice_resolve_symbol_pose(symbol_json_filepath, convert_settings)` | `(bool, str, int)` |
| `ltspice_check_symbol_pose(symbol_json_filepath, convert_settings)` | `(bool, np.ndarray | None)` |
| `ltspice_netlist_to_wiring(netlist_filepath, symbol_pose_filepath, wire_filepath_out, convert_settings)` | `(bool, str, int)` |
| `ltspice_autoplace_symbol_pose(netlist_filepath, symbol_pose_filepath_out, wire_filepath_out, convert_settings)` | `(bool, str, int)` |

Typical pipeline:

1. **netlist → symbol_initial** — generates JSON with `SYMBOL`, `X=0`, `Y=0`, `ORIENTATION=""`, empty `RECTANGLE` and `PINS`.
2. **resolve_symbol_pose** — populates `RECTANGLE` and `PINS` from `.asy` files using `X`, `Y`, and `ORIENTATION`.
3. **check_symbol_pose** — detects symbol-rectangle collisions after buffering by `minimum_dist`. Returns `(False, None)` or `(True, collisions_array)`.
4. **netlist_to_wiring** — routes axis-aligned wires between symbol pins while avoiding obstacles.
5. **autoplace_symbol_pose** — automatically places symbols using a spring-layout-like algorithm, resolves poses, avoids collisions, and generates wiring.

### Wire / Path Utilities

| Function | Returns |
|---|---|
| `are_wires_connected(wires)` | `bool` |
| `are_wires_horizontal_or_vertical(wires)` | `bool` |
| `are_wires_intersecting_obstacles_fast(wires, obstacles)` | `bool` |
| `are_wires_intersecting_obstacles_detailed(wires, obstacles)` | `(bool, np.ndarray \| None)` |
| `place_wires_into_groups(wires)` | `list[np.ndarray]` |
| `get_wire_pos(wires)` | `np.ndarray shape (2N, 2)` |
| `find_wire_group_index(point, wire_groups)` | `int` |
| `rectangle_points_to_lines(points)` | `np.ndarray shape (4, 4)` |

All wire/obstacle arrays are numpy arrays of shape `(N, 4)` with rows `[X1, Y1, X2, Y2]`.  Many raise `ValueError` on invalid input shapes.

- `place_wires_into_groups` groups wires that share an exact endpoint.
- `find_wire_group_index` returns the group index containing a point, or -1 if not found.
- `rectangle_points_to_lines` converts two opposite corner points into four edge segments: top, right, left, bottom.

### Autorouting

| Function | Returns |
|---|---|
| `auto_route_wires(start_x, start_y, end_x, end_y, obstacles, grid_x, grid_y)` | `np.ndarray shape (M, 4)` |

Routes an orthogonal, connected wire path between two points on a grid while avoiding obstacle lines. Raises `ValueError` if no valid route exists.

### GUI Debug

| Function | Returns |
|---|---|
| `gui_debug()` | `None` |

Launches a Tkinter path-tracing GUI for interactive wire, obstacle, and flag placement with autorouting preview.

## Return Conventions

Validation and plotting functions return `(True, "")` or `(False, "<error message>")`.

Conversion functions return `(True, "OK", 0)` or `(False, "<error code>", <line number>)`.

Comparison functions return `True` / `False` (netlist) or `(bool, str, int)` (ASC).

## `convert_settings`

A `Mapping` of configuration values used by conversion and pose functions.  Common keys:

```python
convert_settings = {
    # LTspice library search paths (required for ASC/netlist conversion)
    "ltspice_windows_path": "C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
    "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
    "custom_search_paths": ["./valid_asy/"],

    # Wiring and pose layout parameters
    "minimum_dist": 32,
    "wire_pin_out_dist": 16,
    "grid_size": 16,
    "autoplace_iter": 12,
}
```

No hard-coded paths are permitted in `src/`; all search paths must be supplied through this mapping.

## Install For Local Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install "networkx>=3.6.1" "schemdraw>=0.23" "matplotlib>=3.11.0"
```

Run tests:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

Or the sequential runner:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_all_tests.py
```

## CLI Usage

```bash
# Render an ASC schematic to an image
PYTHONPATH=src .venv/bin/python scripts/ltspice_asc_plot_schemdraw.py input.asc output.svg --width 1600 --height 900

# Render a netlist to a network graph
PYTHONPATH=src .venv/bin/python scripts/ltspice_net_to_networkxpng.py input.net output.svg --width 1600 --height 900

# Convert ASC to netlist
PYTHONPATH=src .venv/bin/python scripts/ltspice_asc_to_netlist.py input.asc

# Extract symbol info from ASC
PYTHONPATH=src .venv/bin/python scripts/ltspice_asc_symbol_info.py input.asc
```

## Example Usage

```python
import numpy as np
from electronics_design import auto_route_wires
from electronics_design import find_wire_group_index
from electronics_design import get_ltspice_asc_symbol_info
from electronics_design import get_ltspice_asy_pins
from electronics_design import get_ltspice_asy_size
from electronics_design import get_wire_pos
from electronics_design import gui_debug
from electronics_design import is_ltspice_netlist_structure_connected
from electronics_design import is_valid_ltspice_asc_file
from electronics_design import is_valid_ltspice_asc_footer
from electronics_design import is_valid_ltspice_asc_header
from electronics_design import is_valid_ltspice_asc_spacing
from electronics_design import is_valid_ltspice_asy
from electronics_design import is_valid_ltspice_netlist_file
from electronics_design import is_valid_ltspice_netlist_footer
from electronics_design import is_valid_ltspice_netlist_format
from electronics_design import ltspice_asc_plot_schemdraw
from electronics_design import ltspice_asc_structure_cmp
from electronics_design import ltspice_asc_to_netlist
from electronics_design import ltspice_autoplace_symbol_pose
from electronics_design import ltspice_check_symbol_pose
from electronics_design import ltspice_netlist_footer_cmp
from electronics_design import ltspice_netlist_plot_networkx
from electronics_design import ltspice_netlist_structure_cmp
from electronics_design import ltspice_netlist_to_symbol_initial
from electronics_design import ltspice_netlist_to_wiring
from electronics_design import ltspice_resolve_symbol_pose
from electronics_design import rectangle_points_to_lines
from electronics_design.pathtracing import are_wires_connected
from electronics_design.pathtracing import are_wires_horizontal_or_vertical
from electronics_design.pathtracing import are_wires_intersecting_obstacles_fast
from electronics_design.pathtracing import are_wires_intersecting_obstacles_detailed
from electronics_design.pathtracing import place_wires_into_groups

convert_settings = {
    "ltspice_windows_path": "C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
    "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
    "custom_search_paths": ["./valid_asy/"],
    "minimum_dist": 32,
    "wire_pin_out_dist": 16,
    "grid_size": 16,
    "autoplace_iter": 12,
}

# ASC validation
header_ok, _ = is_valid_ltspice_asc_header("example.asc")
spacing_ok, _ = is_valid_ltspice_asc_spacing("example.asc")
footer_ok, _ = is_valid_ltspice_asc_footer("example.asc")
asc_ok, _ = is_valid_ltspice_asc_file("example.asc")

# Netlist validation
fmt_ok, _ = is_valid_ltspice_netlist_format("example.net")
net_footer_ok, _ = is_valid_ltspice_netlist_footer("example.net")
conn_ok, _ = is_ltspice_netlist_structure_connected("example.net")
net_ok, _ = is_valid_ltspice_netlist_file("example.net")

# ASY
asy_ok, _ = is_valid_ltspice_asy("example.asy")
bounds = get_ltspice_asy_size("example.asy")
pins = get_ltspice_asy_pins("example.asy")

# Plotting
ltspice_asc_plot_schemdraw("example.asc", "schematic.svg")
ltspice_netlist_plot_networkx("example.net", "graph.png")

# Conversion
convert_ok, _, _ = ltspice_asc_to_netlist("example.asc", "example.net", convert_settings)
symbol_info = get_ltspice_asc_symbol_info("example.asc", convert_settings)

# ASP comparison
cmp_ok, _, _ = ltspice_asc_structure_cmp("a.asc", "b.asc", convert_settings)
same_structure = ltspice_netlist_structure_cmp("a.net", "b.net")
same_footer = ltspice_netlist_footer_cmp("a.net", "b.net")

# Symbol pose pipeline
ltspice_netlist_to_symbol_initial("example.net", "symbols.json", convert_settings)
ltspice_resolve_symbol_pose("symbols.json", convert_settings)
collides, pairs = ltspice_check_symbol_pose("symbols.json", convert_settings)
ltspice_netlist_to_wiring("example.net", "symbols.json", "wires.json", convert_settings)
ltspice_autoplace_symbol_pose("example.net", "symbols.json", "wires.json", convert_settings)

# Wire utilities
wires = np.array([[16, 32, 0, 16], [0, 16, 16, 48]])
connected = are_wires_connected(wires)
axis_aligned = are_wires_horizontal_or_vertical(wires)
groups = place_wires_into_groups(wires)
points = get_wire_pos(wires)

obstacles = np.array([[48, 32, 0, 32], [0, 16, 0, 72]])
hits = are_wires_intersecting_obstacles_fast(wires, obstacles)
hits_detailed, hit_pairs = are_wires_intersecting_obstacles_detailed(wires, obstacles)

rect_lines = rectangle_points_to_lines(np.array([[-16, -32], [48, 32]]))
group_idx = find_wire_group_index(np.array([16, 0]), groups)
path = auto_route_wires(0, 0, 128, 128, obstacles, 16, 16)
```

## Package Layout

```text
src/electronics_design/
    __init__.py
    autoroute.py
    ltspice.py
    ltspice_asc.py
    ltspice_asc_plot_schemdraw.py
    ltspice_asc_to_netlist.py
    ltspice_asy.py
    ltspice_autoplace_symbol_pose.py
    ltspice_net.py
    ltspice_netlist_plot_networkx.py
    ltspice_netlist_to_symbol_initial.py
    ltspice_netlist_to_wiring.py
    ltspice_resolve_symbol_pose.py
    pathtracing.py
tests/
test_files/
valid_asy/
valid_asc/
valid_netlist/
valid_convert/
scripts/
pyproject.toml
```

## Build And Publish

```bash
.venv/bin/python -m pip install --upgrade build twine
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
.venv/bin/python -m twine upload dist/*
```

See `SUBMIT.md` for the checklist.
