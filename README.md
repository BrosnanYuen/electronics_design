# electronics_design

`electronics_design` is a small Python API library for validating LTspice simulation netlists and LTspice schematic files, and for comparing and plotting validated netlists.

It currently exposes eleven public functions:

- `is_valid_ltspice_asc_header(filepath)`
- `is_valid_ltspice_asc_spacing(filepath)`
- `is_valid_ltspice_asc_footer(filepath)`
- `is_valid_ltspice_asc_file(filepath)`
- `ltspice_asc_plot_schemdraw(asc_filepath, schemdraw_imagepath_out, width=1920, height=1080)`

- `is_valid_ltspice_netlist_format(filepath)`
- `is_valid_ltspice_netlist_footer(filepath)`
- `is_ltspice_netlist_structure_connected(filepath)`
- `is_valid_ltspice_netlist_file(filepath)`
- `ltspice_netlist_plot_networkx(netlist_filepath, networkx_imagepath_out, width=1920, height=1080)`
- `ltspice_netlist_structure_cmp(filepath1, filepath2)`

Each function returns a tuple:

```python
(True, "")
```

or:

```python
(False, "<error message>")
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

- Both input files pass `is_valid_ltspice_netlist_file(filepath)`
- The electrical structure matches even if device order differs
- Component instance names may differ
- Ordinary net names may differ
- Footer directives are ignored
- Component values, device types, and pin-to-net structure must still match

Possible returns:

- `False` when either file is invalid or when the structures differ
- `True` when the two validated netlists are structurally equivalent

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

Render a validated LTspice netlist directly to an image file:

```bash
PYTHONPATH=src .venv/bin/python scripts/ltspice_net_to_networkxpng.py input.net output.svg --width 1600 --height 900
```

This script only calls the public `ltspice_netlist_plot_networkx(netlist_filepath, networkx_imagepath_out, width=1920, height=1080)` API and exits with a non-zero status if validation or image generation fails.

## Example Usage

```python
from electronics_design import is_valid_ltspice_asc_header
from electronics_design import is_valid_ltspice_asc_spacing
from electronics_design import is_valid_ltspice_asc_footer
from electronics_design import is_valid_ltspice_asc_file
from electronics_design import ltspice_asc_plot_schemdraw
from electronics_design import is_valid_ltspice_netlist_format
from electronics_design import is_valid_ltspice_netlist_footer
from electronics_design import is_ltspice_netlist_structure_connected
from electronics_design import is_valid_ltspice_netlist_file
from electronics_design import ltspice_netlist_plot_networkx
from electronics_design import ltspice_netlist_structure_cmp

asc_header_ok, asc_header_message = is_valid_ltspice_asc_header("example.asc")
asc_spacing_ok, asc_spacing_message = is_valid_ltspice_asc_spacing("example.asc")
asc_footer_ok, asc_footer_message = is_valid_ltspice_asc_footer("example.asc")
asc_file_ok, asc_file_message = is_valid_ltspice_asc_file("example.asc")
schemdraw_ok, schemdraw_message = ltspice_asc_plot_schemdraw("example.asc", "example.svg")
format_ok, format_message = is_valid_ltspice_netlist_format("example.net")
footer_ok, footer_message = is_valid_ltspice_netlist_footer("example.net")
connected_ok, connected_message = is_ltspice_netlist_structure_connected("example.net")
file_ok, file_message = is_valid_ltspice_netlist_file("example.net")
plot_ok, plot_message = ltspice_netlist_plot_networkx("example.net", "example.png")
plot_svg_ok, plot_svg_message = ltspice_netlist_plot_networkx("example.net", "example.svg", 1280, 720)
plot_jpg_ok, plot_jpg_message = ltspice_netlist_plot_networkx("example.net", "example.jpg", 1280, 720)
same_structure = ltspice_netlist_structure_cmp("example_a.net", "example_b.net")
```

## Test Layout

- `tests/unit/` contains focused unit tests
- `tests/integration/` contains integration tests against repository netlists and schematic samples
- `test_files/asc_header/` contains valid and invalid ASC header fixtures
- `test_files/asc_spacing/` contains valid and invalid ASC spacing fixtures
- `test_files/asc_footer/` contains valid and invalid ASC footer fixtures
- `test_files/asc_validation/` contains valid and invalid whole-file ASC validation fixtures
- `tests/unit/test_asc_plot_schemdraw.py` covers schemdraw-based ASC plotting outputs
- `test_files/netlist_format/` contains 10 valid and 10 invalid format fixtures
- `test_files/netlist_footer/` contains 10 valid and 10 invalid footer fixtures
- `test_files/netlist_connected/` contains 10 valid and 10 invalid connectivity fixtures
- `test_files/netlist_validation/` contains 10 valid and 10 invalid whole-file validation fixtures
- `test_files/netlist_cmp/` contains 20 valid and 20 invalid structural comparison pairs
- `scripts/ltspice_net_to_networkxpng.py` renders one validated LTspice netlist to a `.png`, `.svg`, or `.jpg` image file
- `scripts/run_all_tests.py` runs unit tests first and integration tests second

## Package Layout

```text
src/electronics_design/
    __init__.py
    ltspice.py
tests/
test_files/
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
