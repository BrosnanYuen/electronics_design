# Agent Instructions

## Do not hard-code paths in `src/`

Any filesystem path that refers to a user's home directory, an OS-specific location, or a WINE prefix must be configurable — never hard-coded.

Prohibited examples:
- `C:\users\brosnan\...`
- `~/.wine/drive_c/...`
- `/home/$USER/.wine/...`

Use `os.path.expanduser` with a configurable default or accept the path via function parameter or settings dict.

## Netlist-to-ASC wiring must be physical

Netlist-to-ASC conversion must physically route component-to-component nets,
regardless of circuit size. Do not add a component-count routing limit or an
all-net fallback that replaces physical wires with disconnected labeled stubs.

`FLAG` records may still label physically routed nets. Disconnected net-label
routing is allowed only for nets attached to voltage sources and for the global
ground names `GND` and `0`.

## Do not hard-code any .asy pin positions or pin names in `src/`

JUST LOOK THEM UP USING convert_settings

convert_settings = {
    "ltspice_windows_path": "C:\users\brosnan\AppData\Local\LTspice\",
    "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
    "voltage_must_have_dc": False,
}
