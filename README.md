# electronics_design

`electronics_design` is a small Python API library for validating LTspice simulation netlists, LTspice schematic files, and LTspice symbol files, converting LTspice schematics to netlists, and for comparing and plotting validated netlists.

It currently exposes twenty-three public functions:

- `is_valid_ltspice_asc_header(filepath)`
- `is_valid_ltspice_asc_spacing(filepath)`
- `is_valid_ltspice_asc_footer(filepath)`
- `is_valid_ltspice_asc_file(filepath)`
- `is_valid_ltspice_asy(filepath)`
- `get_ltspice_asy_size(filepath)`
- `get_ltspice_asy_pins(filepath)`
- `rectangle_points_to_lines(points)`
- `ltspice_asc_plot_schemdraw(asc_filepath, schemdraw_imagepath_out, width=1920, height=1080)`
- `ltspice_asc_to_netlist(asc_filepath, net_filepath_out, convert_settings)`
- `ltspice_asc_structure_cmp(filepath1, filepath2)`
- `get_ltspice_asc_symbol_info(asc_filepath, convert_settings)`
- `are_wires_connected(wires)`
- `are_wires_horizontal_or_vertical(wires)`
- `are_wires_intersecting_obstacles_fast(wires, obstacles)`
- `are_wires_intersecting_obstacles_detailed(wires, obstacles)`
- `get_wires_startpos_endpos(wires)`

- `is_valid_ltspice_netlist_format(filepath)`
- `is_valid_ltspice_netlist_footer(filepath)`
- `is_ltspice_netlist_structure_connected(filepath)`
- `is_valid_ltspice_netlist_file(filepath)`
- `ltspice_netlist_footer_cmp(filepath1, filepath2)`
- `ltspice_netlist_plot_networkx(netlist_filepath, networkx_imagepath_out, width=1920, height=1080)`
- `ltspice_netlist_structure_cmp(filepath1, filepath2)`

Most validation and plotting functions return a tuple:

```python
(True, "")
```

or:

```python
(False, "<error message>")
```

`ltspice_netlist_footer_cmp(filepath1, filepath2)`, `ltspice_netlist_structure_cmp(filepath1, filepath2)`, `are_wires_connected(wires)`, and `are_wires_intersecting_obstacles_fast(wires, obstacles)` return `True` or `False`.

`get_wires_startpos_endpos(wires)` returns a pair of numpy arrays:

```python
startpos, endpos = np.array([x1, y1]), np.array([x2, y2])
```

It raises `ValueError` when the wires do not form a single continuous path with exactly two endpoints.

`ltspice_asc_to_netlist(asc_filepath, net_filepath_out, convert_settings)` returns a conversion tuple:

```python
(True, "OK", 0)
```

or:

```python
(False, "<error code>", <line number>)
```

`ltspice_asc_structure_cmp(filepath1, filepath2)` returns a structure-comparison tuple:

```python
(True, "", 0)
```

or:

```python
(False, "<error message>", <line number>)
```

`get_ltspice_asy_size(filepath)` returns a numpy array containing the bounding rectangle of the drawable symbol geometry:

```python
np.array([
    [x1, y1],
    [x2, y2],
])
```

It raises `ValueError` when the input `.asy` file is invalid or when the file contains no drawable `LINE`, `RECTANGLE`, `CIRCLE`, or `ARC` geometry.

`get_ltspice_asy_pins(filepath)` returns a Python list of pin rows:

```python
[
    [x, y, "PinName", spice_order],
]
```

It raises `ValueError` when the input `.asy` file is invalid or when a declared pin is missing a `PinName` or `SpiceOrder`.

`rectangle_points_to_lines(points)` returns a numpy array containing the four rectangle edges implied by two opposite corner points:

```python
np.array([
    [x1, y1, x2, y1],
    [x2, y1, x2, y2],
    [x1, y1, x1, y2],
    [x1, y2, x2, y2],
])
```

## What The Library Checks

### `is_valid_ltspice_asc_header(filepath)`

Checks that:

- The file exists and is readable
- The first nonblank structural line is `Version` or `VERSION`
- The second nonblank structural line is `SHEET`
- Both header lines have the required whitespace token structure

Possible returns:

- `False, "File not found!"`
- `False, "No permission to read file!"`
- `False, "Header information is invalid! Line <n>"`
- `True, ""`

### `is_valid_ltspice_asc_spacing(filepath)`

Checks that:

- The file exists and is readable
- Each nonblank line starts with a supported LTspice `.asc` keyword
- Supported records such as `WIRE`, `FLAG`, `SYMBOL`, `WINDOW`, `SYMATTR`, `TEXT`, `LINE`, `RECTANGLE`, `CIRCLE`, `ARC`, `IOPIN`, `BUSTAP`, and `DATAFLAG` have valid token structure
- Spacing mistakes such as merged keywords or malformed `TEXT`/`SYMBOL`/`WIRE` records are rejected

Possible returns:

- `False, "File not found!"`
- `False, "No permission to read file!"`
- `False, "Line format/spacing is invalid! Line <n>"`
- `True, ""`

### `is_valid_ltspice_asc_footer(filepath)`

Checks that:

- The file exists and is readable
- The file already passes `.asc` spacing validation
- The schematic contains at least one valid simulation directive carried by `TEXT ... !.<directive>`
- Analysis directives such as `.tran`, `.ac`, `.dc`, `.op`, `.tf`, `.noise`, or `.fra` are accepted
- Disabled directive text such as `!;tran ...` is treated as annotation, not as an active directive

Possible returns:

- `False, "File not found!"`
- `False, "No permission to read file!"`
- `False, "Footer information is invalid! Line <n>"`
- `True, ""`

### `is_valid_ltspice_asc_file(filepath)`

Checks that:

- The file passes `is_valid_ltspice_asc_header(filepath)`
- The file passes `is_valid_ltspice_asc_spacing(filepath)`
- The file passes `is_valid_ltspice_asc_footer(filepath)`

Possible returns:

- `False, "File not found!"`
- `False, "No permission to read file!"`
- `False, "<propagated validator message>"`
- `True, ""`

### `is_valid_ltspice_asy(filepath)`

Checks that:

- The file exists and is readable
- The first nonblank structural line is `Version`
- The second nonblank structural line is `SymbolType`
- Each nonblank line starts with a supported LTspice `.asy` keyword
- Supported records such as `LINE`, `RECTANGLE`, `CIRCLE`, `ARC`, `WINDOW`, `SYMATTR`, `TEXT`, `PIN`, and `PINATTR` have valid token structure
- `PINATTR` records only appear immediately after a `PIN` record
- UTF-8, Latin-1, and UTF-16 encoded `.asy` files are accepted

Possible returns:

- `False, "File not found!"`
- `False, "No permission to read file!"`
- `False, "LTspice ASY file is invalid! Line <n>"`
- `True, ""`

### `get_ltspice_asy_size(filepath)`

Checks that:

- The source LTspice symbol passes `is_valid_ltspice_asy(filepath)`
- Only the `LINE`, `RECTANGLE`, `CIRCLE`, and `ARC` records are used to determine the drawable bounds
- The minimum `x`, minimum `y`, maximum `x`, and maximum `y` across those records are returned as the symbol bounding rectangle
- All non-geometry records such as `WINDOW`, `SYMATTR`, `PIN`, `PINATTR`, and `TEXT` are ignored for sizing

Returns:

- `np.array([[min_x, min_y], [max_x, max_y]])` for a valid symbol with drawable geometry

Raises:

- `ValueError` when the `.asy` file is invalid
- `ValueError` when the `.asy` file contains no drawable `LINE`, `RECTANGLE`, `CIRCLE`, or `ARC` geometry

### `get_ltspice_asy_pins(filepath)`

Checks that:

- The source LTspice symbol passes `is_valid_ltspice_asy(filepath)`
- Every declared `PIN` block includes both a `PINATTR PinName ...` and a `PINATTR SpiceOrder ...`
- Returned pins are sorted by ascending `SpiceOrder`

Returns:

- `[[x, y, "PinName", spice_order], ...]` for a valid symbol

Raises:

- `ValueError` when the `.asy` file is invalid
- `ValueError` when a declared pin is missing a `PinName` or `SpiceOrder`

### `rectangle_points_to_lines(points)`

Checks that:

- `points` is a numpy array of shape `(2, 2)` containing integer coordinates
- The two rows describe opposite rectangle corners
- The returned line order is top, right, left, bottom

Returns:

- `np.array([[x1, y1, x2, y1], [x2, y1, x2, y2], [x1, y1, x1, y2], [x1, y2, x2, y2]])`

Raises:

- `ValueError` when `points` is not shape `(2, 2)` or contains non-integer coordinates

### `ltspice_asc_plot_schemdraw(asc_filepath, schemdraw_imagepath_out, width=1920, height=1080)`

Checks that:

- The source LTspice schematic passes `is_valid_ltspice_asc_file(filepath)`
- The function builds a `schemdraw` rendering from the schematic symbols, flags, and wire geometry
- The image is written to `schemdraw_imagepath_out`
- Supported output extensions are `.png`, `.svg`, `.jpg`, and `.jpeg`
- `width` optionally sets the output width in pixels and defaults to `1920`
- `height` optionally sets the output height in pixels and defaults to `1080`

Possible returns:

- `False, "File not found!"`
- `False, "No permission to read file!"`
- `False, "Unable to plot schematic drawing!"`
- `False, "Unable to write image file!"`
- `True, ""`

### `ltspice_asc_to_netlist(asc_filepath, net_filepath_out, convert_settings)`

Checks that:

- The source LTspice schematic is acceptable for conversion and is first validated with `is_valid_ltspice_asc_file(filepath)`
- The converter resolves LTspice symbols and library files by browsing the LTspice root supplied in `convert_settings`
- The generated netlist is written to `net_filepath_out`
- The generated netlist is validated with `is_valid_ltspice_netlist_file(filepath)`
- ASC comments are ignored during conversion and no comments are emitted into the generated netlist
- `convert_settings` is a mapping so additional conversion options can be added later without changing the API shape

Example `convert_settings`:

```python
convert_settings = {
    "ltspice_windows_path": "C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
    "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
}
```

Possible returns:

- `False, "INVALID_CONVERT_SETTINGS", 0`
- `False, "INVALID_OUTPUT_PATH", 0`
- `False, "INVALID_ASC_FILE", <line>`
- `False, "ASC_READ_ERROR", 0`
- `False, "ASC_PARSE_ERROR", <line>`
- `False, "UNKNOWN_SYMBOL", <line>`
- `False, "UNCONNECTED_SYMBOL_PIN", <line>`
- `False, "MISSING_COMPONENT_PAYLOAD", <line>`
- `False, "WRITE_ERROR", 0`
- `False, "INVALID_GENERATED_NETLIST", <line>`
- `True, "OK", 0`

### `ltspice_asc_structure_cmp(filepath1, filepath2)`

Checks that:

- Both input ASC files pass `is_valid_ltspice_asc_file(filepath)`
- Both ASC files can be converted to temporary LTspice netlists through `ltspice_asc_to_netlist(...)`
- ASC comments are ignored because comparison is performed on the converted netlist structure
- The converted netlists compare equal through `ltspice_netlist_structure_cmp(filepath1, filepath2)`

Possible returns:

- `False, "File not found!", 0`
- `False, "No permission to read file!", 0`
- `False, "<validator message>", <line>`
- `False, "<conversion error code>", <line>`
- `False, "ASC structures are different!", <line>`
- `True, "", 0`

### `get_ltspice_asc_symbol_info(asc_filepath, convert_settings)`

Checks that:

- The source LTspice schematic can be read and parsed for `SYMBOL` and `SYMATTR InstName` records
- The LTspice symbol library root is resolved from `convert_settings`
- Each ASC symbol is matched to its corresponding `.asy` file by searching the configured LTspice library
- `get_ltspice_asy_pins(filepath)` is used to read the symbol pin names, local pin coordinates, and `SpiceOrder`
- `get_ltspice_asy_size(filepath)` is used to read the symbol drawable bounding rectangle
- Local `.asy` pin and rectangle coordinates are transformed into absolute ASC coordinates using the symbol origin and orientation

Returns:

- A dictionary keyed by `InstName`
- Each entry contains `SYMBOL`, `X`, `Y`, `ROTATION`, `RECTANGLE`, and `PINS`

Raises:

- `ValueError` when the ASC file cannot be read
- `ValueError` when a symbol is missing `InstName`
- `ValueError` when a symbol `.asy` file cannot be found through `convert_settings`

### `are_wires_connected(wires)`

Checks that:

- `wires` is a numpy array of shape `(N, 4)` where each row is `[X1, Y1, X2, Y2]`
- Each wire is an axis-aligned line segment
- Two wires are connected if they share an endpoint, or if they are collinear and their ranges overlap
- Orthogonal wires that cross at a non-endpoint are not counted as connected

Returns:

- `True` when all wires belong to a single connected component
- `False` when at least one wire is disconnected from the rest

### `are_wires_horizontal_or_vertical(wires)`

Checks that:

- `wires` is a numpy array of shape `(N, 4)` where each row is `[X1, Y1, X2, Y2]`
- Each wire is checked for axis alignment: horizontal means `Y1 == Y2`, vertical means `X1 == X2`

Returns:

- `True` when every wire in the array is either horizontal or vertical
- `False` when at least one wire moves diagonally (both `X1 != X2` and `Y1 != Y2`)

### `are_wires_intersecting_obstacles_fast(wires, obstacles)`

Checks that:

- `wires` is a numpy array of shape `(N, 4)` where each row is `[X1, Y1, X2, Y2]`
- `obstacles` is a numpy array of shape `(M, 4)` where each row is `[X1, Y1, X2, Y2]`
- Each wire and obstacle is an axis-aligned line segment
- Two lines intersect if they cross at a shared interior point or touch at a shared endpoint
- Collinear lines intersect if their ranges overlap

Returns:

- `True` when at least one wire line intersects at least one obstacle line
- `False` when no wire line intersects any obstacle line

### `are_wires_intersecting_obstacles_detailed(wires, obstacles)`

Checks that:

- `wires` is a numpy array of shape `(N, 4)` where each row is `[X1, Y1, X2, Y2]`
- `obstacles` is a numpy array of shape `(M, 4)` where each row is `[X1, Y1, X2, Y2]`
- Each wire and obstacle is an axis-aligned line segment
- Two lines intersect if they cross at a shared interior point or touch at a shared endpoint
- Collinear lines intersect if their ranges overlap

Returns:

- `True, intersections` when at least one wire line intersects at least one obstacle line, where `intersections` is a numpy array of shape `(K, 2)` listing all `[wire_index, obstacle_index]` pairs
- `False, None` when no wire line intersects any obstacle line

### `get_wires_startpos_endpos(wires)`

Checks that:

- `wires` is a numpy array of shape `(N, 4)` where each row is `[X1, Y1, X2, Y2]`
- Each wire is an axis-aligned line segment
- The wires form a single continuous path with exactly two endpoints

Returns:

- `startpos, endpos` as two numpy arrays `[x, y]` identifying the path endpoints, ordered by ascending `x` then `y`

Raises:

- `ValueError` when `wires` is not shape `(N, 4)`, is not a single continuous path, or does not have exactly two endpoints

### `is_valid_ltspice_netlist_format(filepath)`

Checks that:

- The file exists and is readable
- Each line starts with a valid LTspice line class
- Dot directives are spelled correctly and separated correctly
- Device lines have the required whitespace token structure
- Spacing mistakes like `R1Vcc N001 1` or `.stepPARAM ...` are rejected

Possible returns:

- `False, "File not found!"`
- `False, "No permission to read file!"`
- `False, "Line format/spacing is invalid! Line <n>"`
- `True, ""`

### `is_valid_ltspice_netlist_footer(filepath)`

Checks that:

- The file format is already valid
- The final nonblank line is `.end`
- The penultimate nonblank line is `.backanno`
- The file contains at least one LTspice analysis directive such as `.tran`, `.ac`, `.dc`, `.op`, `.tf`, `.noise`, or `.fra`
- Footer directives are structurally valid

Possible returns:

- `False, "File not found!"`
- `False, "No permission to read file!"`
- `False, "Footer information is invalid! Line <n>"`
- `True, ""`

### `is_ltspice_netlist_structure_connected(filepath)`

Checks that:

- The file exists and is readable
- The line format is parseable
- Every non-ground, non-`NC_*` node appears on at least two device ports

Possible returns:

- `False, "File not found!"`
- `False, "No permission to read file!"`
- `False, "Node is not connected correctly! Line <n>"`
- `True, ""`

### `is_valid_ltspice_netlist_file(filepath)`

Checks that:

- The file passes `is_valid_ltspice_netlist_format(filepath)`
- The file passes `is_valid_ltspice_netlist_footer(filepath)`
- The file passes `is_ltspice_netlist_structure_connected(filepath)`

Possible returns:

- `False, "File not found!"`
- `False, "No permission to read file!"`
- `False, "<propagated validator message>"`
- `True, ""`

### `ltspice_netlist_footer_cmp(filepath1, filepath2)`

Checks that:

- Both input files pass `is_valid_ltspice_netlist_file(filepath)`
- The normalized footer regions of both netlists match
- Directive order and content in the footer remain equivalent after normalization

Possible returns:

- `True`
- `False`

### `ltspice_netlist_plot_networkx(netlist_filepath, networkx_imagepath_out, width=1920, height=1080)`

Checks that:

- The source LTspice netlist passes `is_valid_ltspice_netlist_file(filepath)`
- The function builds a `networkx` component-to-net graph
- The graph is rendered to an image file at `networkx_imagepath_out`
- Supported output extensions are `.png`, `.svg`, `.jpg`, and `.jpeg`
- `width` optionally sets the PNG width in pixels and defaults to `1920`
- `height` optionally sets the PNG height in pixels and defaults to `1080`

Possible returns:

- `False, "File not found!"`
- `False, "No permission to read file!"`
- `False, "Unable to plot network graph!"`
- `False, "Unable to write PNG file!"`
- `True, ""`

### `ltspice_netlist_structure_cmp(filepath1, filepath2)`

Checks that:

- Both input files can be parsed as LTspice netlists
- The electrical structure matches even if device order differs
- Component instance names may differ
- Ordinary net names may differ
- Footer directives are ignored
- Component values, device types, and pin-to-net structure must still match

Possible returns:

- `False` when either file cannot be parsed or when the structures differ
- `True` when the two netlists are structurally equivalent

## Install For Local Development

Create the virtual environment:

```bash
python3 -m venv .venv
```

Run tests with the project environment:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

Run the sequential test runner:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_all_tests.py
```

Install the runtime dependencies used by the plotting and comparison APIs:

```bash
.venv/bin/python -m pip install "networkx>=3.6.1" "schemdraw>=0.23" "matplotlib>=3.11.0"
```

## CLI Usage

Render a validated LTspice schematic directly to an image file:

```bash
PYTHONPATH=src .venv/bin/python scripts/ltspice_asc_plot_schemdraw.py input.asc output.svg --width 1600 --height 900
```

This script only calls the public `ltspice_asc_plot_schemdraw(asc_filepath, schemdraw_imagepath_out, width=1920, height=1080)` API and exits with a non-zero status if validation or image generation fails.

Render a validated LTspice netlist directly to an image file:

```bash
PYTHONPATH=src .venv/bin/python scripts/ltspice_net_to_networkxpng.py input.net output.svg --width 1600 --height 900
```

This script only calls the public `ltspice_netlist_plot_networkx(netlist_filepath, networkx_imagepath_out, width=1920, height=1080)` API and exits with a non-zero status if validation or image generation fails.

## Example Usage

```python
import numpy as np
from electronics_design import is_valid_ltspice_asc_header
from electronics_design import is_valid_ltspice_asc_spacing
from electronics_design import is_valid_ltspice_asc_footer
from electronics_design import is_valid_ltspice_asc_file
from electronics_design import is_valid_ltspice_asy
from electronics_design import get_ltspice_asy_size
from electronics_design import get_ltspice_asy_pins
from electronics_design import rectangle_points_to_lines
from electronics_design import ltspice_asc_plot_schemdraw
from electronics_design import ltspice_asc_to_netlist
from electronics_design import ltspice_asc_structure_cmp
from electronics_design import get_ltspice_asc_symbol_info
from electronics_design.pathtracing import are_wires_connected
from electronics_design.pathtracing import are_wires_horizontal_or_vertical
from electronics_design.pathtracing import are_wires_intersecting_obstacles_fast
from electronics_design.pathtracing import are_wires_intersecting_obstacles_detailed
from electronics_design.pathtracing import get_wires_startpos_endpos
from electronics_design import is_valid_ltspice_netlist_format
from electronics_design import is_valid_ltspice_netlist_footer
from electronics_design import is_ltspice_netlist_structure_connected
from electronics_design import is_valid_ltspice_netlist_file
from electronics_design import ltspice_netlist_footer_cmp
from electronics_design import ltspice_netlist_plot_networkx
from electronics_design import ltspice_netlist_structure_cmp

asc_header_ok, asc_header_message = is_valid_ltspice_asc_header("example.asc")
asc_spacing_ok, asc_spacing_message = is_valid_ltspice_asc_spacing("example.asc")
asc_footer_ok, asc_footer_message = is_valid_ltspice_asc_footer("example.asc")
asc_file_ok, asc_file_message = is_valid_ltspice_asc_file("example.asc")
asy_ok, asy_message = is_valid_ltspice_asy("example.asy")
asy_bounds = get_ltspice_asy_size("example.asy")
asy_pins = get_ltspice_asy_pins("example.asy")
rectangle_lines = rectangle_points_to_lines(np.array([[-16, -32], [48, 32]]))
schemdraw_ok, schemdraw_message = ltspice_asc_plot_schemdraw("example.asc", "example.svg")
convert_settings = {
    "ltspice_windows_path": "C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
    "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
}
convert_ok, convert_error_code, convert_line = ltspice_asc_to_netlist(
    "example.asc",
    "example.net",
    convert_settings,
)
same_asc_structure, asc_compare_message, asc_compare_line = ltspice_asc_structure_cmp(
    "example_a.asc",
    "example_b.asc",
    convert_settings,
)
symbol_info = get_ltspice_asc_symbol_info("example.asc", convert_settings)
wires_array = np.array([[16, 32, 0, 16], [0, 16, 16, 48]])
wires_connected = are_wires_connected(wires_array)
all_axis_aligned = are_wires_horizontal_or_vertical(wires_array)
obstacles_array = np.array([[48, 32, 0, 32], [0, 16, 0, 72]])
intersects_obstacles = are_wires_intersecting_obstacles_fast(wires_array, obstacles_array)
intersects_detailed, detailed_pairs = are_wires_intersecting_obstacles_detailed(wires_array, obstacles_array)
path_wires = np.array([[160, 192, 256, 192], [256, 192, 256, 384], [256, 384, 432, 384]])
startpos, endpos = get_wires_startpos_endpos(path_wires)
format_ok, format_message = is_valid_ltspice_netlist_format("example.net")
footer_ok, footer_message = is_valid_ltspice_netlist_footer("example.net")
connected_ok, connected_message = is_ltspice_netlist_structure_connected("example.net")
file_ok, file_message = is_valid_ltspice_netlist_file("example.net")
same_footer = ltspice_netlist_footer_cmp("example_a.net", "example_b.net")
plot_ok, plot_message = ltspice_netlist_plot_networkx("example.net", "example.png")
plot_svg_ok, plot_svg_message = ltspice_netlist_plot_networkx("example.net", "example.svg", 1280, 720)
plot_jpg_ok, plot_jpg_message = ltspice_netlist_plot_networkx("example.net", "example.jpg", 1280, 720)
same_structure = ltspice_netlist_structure_cmp("example_a.net", "example_b.net")
```

## Test Layout

- `tests/unit/` contains focused unit tests
- `tests/integration/` contains integration tests against repository netlists and schematic samples
- `tests/unit/test_asc_to_netlist.py` converts every fixture in `valid_convert/asc/` and compares the generated netlist against the matching ground-truth file in `valid_convert/netlist/`
- `tests/unit/test_asy_validation.py` validates every symbol file in `valid_asy/`
- `tests/unit/test_asy_size.py` covers `.asy` bounding-rectangle extraction
- `test_files/asy_size/` contains 20 `.asy` symbol-size fixtures
- `test_files/asc_header/` contains valid and invalid ASC header fixtures
- `test_files/asc_spacing/` contains valid and invalid ASC spacing fixtures
- `test_files/asc_footer/` contains valid and invalid ASC footer fixtures
- `test_files/asc_validation/` contains valid and invalid whole-file ASC validation fixtures
- `tests/unit/test_asc_plot_schemdraw.py` covers schemdraw-based ASC plotting outputs
- `tests/unit/test_wires_connected.py` covers the wire connectivity API
- `test_files/wires_connected/` contains 15 valid and 15 invalid wire connectivity fixtures
- `tests/unit/test_wires_horizontal_vertical.py` covers the wire axis-alignment API
- `test_files/wires_horizontal_vertical/` contains 10 valid and 10 invalid axis-alignment fixtures
- `tests/unit/test_wires_intersect_obstacles.py` covers the wire-obstacle intersection API
- `tests/unit/test_wires_intersect_obstacles_detailed.py` covers the detailed wire-obstacle intersection API
- `test_files/wires_intersect_obstacles/` contains 15 valid and 15 invalid wire-obstacle intersection fixtures
- `test_files/wires_intersect_obstacles_detailed/` contains 10 valid and 10 invalid detailed wire-obstacle intersection fixtures
- `tests/unit/test_wires_start_end.py` covers the wire start/end position API
- `test_files/wire_start_end/` contains 10 connected wire chain fixtures with expected start and end positions
- `test_files/netlist_format/` contains 10 valid and 10 invalid format fixtures
- `test_files/netlist_footer/` contains 10 valid and 10 invalid footer fixtures
- `test_files/netlist_connected/` contains 10 valid and 10 invalid connectivity fixtures
- `test_files/netlist_validation/` contains 10 valid and 10 invalid whole-file validation fixtures
- `test_files/netlist_cmp/` contains 20 valid and 20 invalid structural comparison pairs
- `valid_asy/` contains valid LTspice ASY symbol fixtures
- `valid_convert/asc/` contains valid LTspice ASC conversion fixtures
- `valid_convert/netlist/` contains the expected LTspice netlists for the conversion fixtures
- `scripts/ltspice_asc_plot_schemdraw.py` renders one validated LTspice ASC schematic to a `.png`, `.svg`, or `.jpg` image file
- `scripts/ltspice_net_to_networkxpng.py` renders one validated LTspice netlist to a `.png`, `.svg`, or `.jpg` image file
- `scripts/run_all_tests.py` runs unit tests first and integration tests second

## Package Layout

```text
src/electronics_design/
    __init__.py
    ltspice.py
    ltspice_asc.py
    ltspice_asc_plot_schemdraw.py
    ltspice_asc_to_netlist.py
    ltspice_asy.py
    ltspice_net.py
    ltspice_netlist_plot_networkx.py
    pathtracing.py
tests/
test_files/
valid_convert/
scripts/
pyproject.toml
README.md
SUBMIT.md
```

## Build And Publish

The project uses `setuptools` through `pyproject.toml`.

Typical release flow:

```bash
.venv/bin/python -m pip install --upgrade build twine
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
.venv/bin/python -m twine upload dist/*
```

See `SUBMIT.md` for the exact submission checklist.
