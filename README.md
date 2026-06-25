# electronics_design

`electronics_design` is a small Python API library for validating, comparing, and plotting LTspice simulation netlists.

It currently exposes six public functions:

- `is_valid_ltspice_netlist_format(filepath)`
- `is_valid_ltspice_netlist_footer(filepath)`
- `is_ltspice_netlist_structure_connected(filepath)`
- `is_valid_ltspice_netlist_file(filepath)`
- `ltspice_netlist_plot_networkx(netlist_filepath, networkx_png_filepath)`
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

### `ltspice_netlist_plot_networkx(netlist_filepath, networkx_png_filepath)`

Checks that:

- The source LTspice netlist passes `is_valid_ltspice_netlist_file(filepath)`
- The function builds a `networkx` component-to-net graph
- The graph is rendered to a PNG file at `networkx_png_filepath`

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

Install the runtime dependency used by the plotting and comparison APIs:

```bash
.venv/bin/python -m pip install "networkx>=3.6.1"
```

## Example Usage

```python
from electronics_design import is_valid_ltspice_netlist_format
from electronics_design import is_valid_ltspice_netlist_footer
from electronics_design import is_ltspice_netlist_structure_connected
from electronics_design import is_valid_ltspice_netlist_file
from electronics_design import ltspice_netlist_plot_networkx
from electronics_design import ltspice_netlist_structure_cmp

format_ok, format_message = is_valid_ltspice_netlist_format("example.net")
footer_ok, footer_message = is_valid_ltspice_netlist_footer("example.net")
connected_ok, connected_message = is_ltspice_netlist_structure_connected("example.net")
file_ok, file_message = is_valid_ltspice_netlist_file("example.net")
plot_ok, plot_message = ltspice_netlist_plot_networkx("example.net", "example.png")
same_structure = ltspice_netlist_structure_cmp("example_a.net", "example_b.net")
```

## Test Layout

- `tests/unit/` contains focused unit tests
- `tests/integration/` contains integration tests against repository netlists
- `test_files/netlist_format/` contains 10 valid and 10 invalid format fixtures
- `test_files/netlist_footer/` contains 10 valid and 10 invalid footer fixtures
- `test_files/netlist_connected/` contains 10 valid and 10 invalid connectivity fixtures
- `test_files/netlist_validation/` contains 10 valid and 10 invalid whole-file validation fixtures
- `test_files/netlist_cmp/` contains 20 valid and 20 invalid structural comparison pairs
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
