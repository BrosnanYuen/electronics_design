# LTspice Error Codes

This document describes the error codes and public error messages returned by the `electronics_design` package.

## Return shapes

Conversion functions normally return:

```python
(success: bool, message: str, line_number: int)
```

- `success` is `True` only when the requested operation completed.
- `message` is `"OK"` on success, or an uppercase error code on failure.
- Some newer diagnostics append details after the code, for example `UNKNOWN_SYMBOL: ...` or `AUTOPLACE_FAILED: ...`.
- `line_number` is one-based when a source line is known. `0` means that the failure is not associated with one source line or the line could not be determined.

Validation and plotting functions normally return:

```python
(success: bool, message: str)
```

Some lower-level helpers return a conversion result together with an empty payload. The embedded conversion result uses the same codes described here.

## Successful result

| Code | Meaning | Action |
|---|---|---|
| `OK` | The operation completed successfully. | Use the output. |

## Common conversion and file errors

| Code | Meaning | Recommended advice |
|---|---|---|
| `INVALID_CONVERT_SETTINGS` | `convert_settings` is not a mapping, or one of its numeric, boolean, or path-related settings is invalid. | Pass a dictionary-like mapping. Check `minimum_dist`, `wire_pin_out_dist`, `grid_size`, `autoplace_iter`, `parallel_workers`, `ltspice_version`, `voltage_must_have_dc`, and the LTspice search-path values. |
| `INVALID_OUTPUT_PATH` | The requested output path is not path-like or cannot be accepted by the API. | Pass a writable file path and create or permit its parent directory. |
| `WRITE_ERROR` | An output file could not be written. | Check the parent directory, permissions, available space, and whether another process has locked the file. |
| `NETLIST_READ_ERROR` | The netlist could not be read after path validation. | Check that the file still exists, is readable, and uses a supported text encoding. |
| `INVALID_NETLIST_FILE` | The netlist failed the project’s format validator. | Inspect the reported line for a bad leading keyword, merged tokens, invalid pin count, or malformed continuation. Run `is_valid_ltspice_netlist_format()` first. |
| `INVALID_ASC_FILE` | The ASC file failed the required header, spacing, or footer checks before conversion. | Run the three ASC validators separately to identify the failing section. |
| `ASC_READ_ERROR` | The ASC file could not be read after validation. | Check the path, permissions, and file encoding. |
| `ASC_PARSE_ERROR` | ASC records or symbol pin data could not be parsed. | Inspect the reported line and verify record token counts, coordinates, orientations, and pin metadata. |
| `INVALID_GENERATED_NETLIST` | ASC-to-netlist or KiCad-schematic-to-netlist conversion produced a netlist that failed validation. | Inspect the generated-netlist line reported by the result; check symbol pin orders, payloads, and generated directives. |
| `INVALID_GENERATED_ASC` | Netlist/symbol/wire-to-ASC conversion produced an ASC file that failed validation. | Inspect the generated ASC line reported by the result and verify symbol poses, wires, flags, and analysis text. |
| `INVALID_ASY_FILE` | An ASY file is missing, unreadable, or failed `is_valid_ltspice_asy()` during ASY-to-KiCad-symbol conversion. | Check the path and permissions, then run `is_valid_ltspice_asy()` separately to locate the failing line. |
| `ASY_PARSE_ERROR` | An ASY pin record is incomplete (for example a `PIN` without a `SpiceOrder` `PINATTR`) during ASY-to-KiCad-symbol conversion. | Inspect the reported ASY line and verify every `PIN` is followed by its `PinName`/`SpiceOrder` attributes. |
| `INVALID_GENERATED_KICAD_SYMBOL` | ASY-to-KiCad-symbol conversion produced a `.kicad_sym` file that failed `is_valid_kicad_symbol_file()`. | Inspect the generated symbol line reported by the result and verify the symbol, property, and pin structure. |
| `INVALID_GENERATED_KICAD_SCH` | Netlist-to-KiCad-schematic conversion produced a `.kicad_sch` file that failed `is_valid_kicad_sch_file()`. | Inspect the generated schematic line reported by the result and verify the header, spacing, and sheet-instance footer structure. |
| `INVALID_NETLIST_FILE` | The LTspice netlist input path is unusable, or the netlist failed the project's netlist validators before netlist-to-KiCad-schematic conversion. | Check the path and permissions, then run `is_valid_ltspice_netlist_file()` separately to locate the failing line. |
| `NETLIST_READ_ERROR` | The LTspice netlist could not be read after validation. | Check the path, permissions, and file encoding. |
| `UNSUPPORTED_DEVICE` | A netlist device has no KiCad schematic representation (for example `A`, `@`, or `&` prefixes), or its shape cannot round-trip through `kicad_sch_to_ltspice_netlist` (for example a voltage source with a floating negative node represented by a power symbol). Node-free `K` mutual-inductance statements are skipped during schematic generation and ignored by structural round-trip comparison. | Rework the netlist to use supported device shapes, or resolve the device to an `.asy`/library symbol that the reverse converter can emit. |
| `INVALID_KICAD_SCH_FILE` | The KiCad schematic input path is unusable or the schematic failed `is_valid_kicad_sch_file()` before conversion. | Check the path and permissions, then run the three KiCad schematic validators separately to locate the failing section. |
| `KICAD_SCH_READ_ERROR` | The KiCad schematic could not be read after validation. | Check the path, permissions, and file encoding. |
| `KICAD_SCH_PARSE_ERROR` | A schematic symbol instance record is malformed (missing `lib_id`, `at` position, or similar) and could not be parsed. | Inspect the reported schematic line and verify the instance's `lib_id`, `at`, `unit`, and pin sections. |
| `UNKNOWN_KICAD_SYMBOL` | A schematic instance's `lib_id` cannot be resolved in the `kicad_path` symbol libraries or the schematic's embedded `lib_symbols` definitions. | Verify the library identifier, add the missing library file under `convert_settings['kicad_path']`, or embed the symbol definition in the schematic. |

## KiCad PCB conversion errors

These codes are returned by `kicad_sch_to_kicad_pcb()`.

| Code | Meaning | Recommended advice |
|---|---|---|
| `KICAD_TOOLS_UNAVAILABLE: ...` | The declared `kicad-tools` dependency could not be imported. | Install the package with `pip install "kicad-tools[all]"` and verify the environment. |
| `FOOTPRINT_NOT_FOUND: ...` | A component's footprint cannot be resolved: an explicit identifier was not found, a footprint file failed to parse, or no generator can represent the pin count. | Check the `Footprint` property, add the missing library under `kicad_path` or `kicad_pcb_footprint_search_paths`, supply a `kicad_pcb_footprint_map` override, or raise the pin count coverage with `kicad_pcb_default_footprints`. |
| `PCB_BUILD_FAILED: ...` | Board assembly failed while creating the board, declaring nets, or placing a footprint. | Check the `kicad_pcb_layers`, `kicad_pcb_paper`, width/height, and margin settings; verify the resolved footprint files. |
| `PCB_PLACEMENT_FAILED` | The schematic carries no placeable component (only power symbols or graphical markers). | Verify the schematic contains real components with pins. |
| `ROUTING_FAILED: ...` | The kicad-tools autorouter crashed, exceeded its budget, or (with `kicad_pcb_require_complete_routing`) left nets unrouted or partially connected. | Increase `kicad_pcb_routing_timeout`, enlarge the board, reduce the grid resolution, skip plane nets with `kicad_pcb_skip_route_nets`, or inspect the appended exception detail. |
| `INVALID_GENERATED_KICAD_PCB` | The finished board failed the final reload-and-reference validation. | Retry the conversion and report the failure if it persists; the message names the mismatch. |

## Symbol and symbol-pose errors

| Code | Meaning | Recommended advice |
|---|---|---|
| `UNKNOWN_SYMBOL` | An ASC symbol cannot be found or cannot be matched to a loaded symbol definition. The message may include the symbol name, instance, expected `.asy` filename, and searched roots. | Add the directory containing the `.asy` file to `convert_settings['custom_search_paths']`, or correct the symbol name. For `X...` devices, preserve an LTspice `ModelFile` hint when the `.subckt` name differs from the `.asy` filename. Also returned by netlist-to-KiCad-schematic conversion when no symbol in `convert_settings["kicad_path"]` and no LTspice `.asy` fallback file resolves the device. |
| `UNCONNECTED_SYMBOL_PIN` | A symbol has no usable pin-to-net mapping during ASC-to-netlist or KiCad-schematic-to-netlist conversion. | Connect the pin with a `WIRE`/`FLAG`, verify the symbol's `PINATTR SpiceOrder`, and check that the symbol is not floating unintentionally. In KiCad schematics, verify the pin geometry of the library symbol under `kicad_path` and that the pin position touches a wire or another pin. |
| `MISSING_COMPONENT_PAYLOAD` | A component requires a value, model, or other SPICE payload, but none was available. | Add the required `SYMATTR Value`/model data or ensure the symbol definition supplies a valid default. In KiCad schematics, verify the instance `Value` property and that the reference designator has a supported LTspice device prefix. |
| `INVALID_SYMBOL_JSON_PATH` | The symbol-pose JSON path is not path-like. | Pass a valid path-like value. |
| `SYMBOL_JSON_READ_ERROR` | The symbol-pose JSON file could not be opened or read. | Check that the file exists and is readable. |
| `SYMBOL_JSON_PARSE_ERROR` | The symbol-pose JSON is malformed or does not have the expected dictionary/entry structure. | Parse it with `json.loads()`, ensure every instance has `SYMBOL`, `X`, `Y`, `ORIENTATION`, `RECTANGLE`, and `PINS` fields where required. |
| `SYMBOL_POSE_READ_ERROR` | A symbol-pose JSON file could not be read by the wiring or ASC reconstruction stage. | Check the path and permissions. |
| `SYMBOL_POSE_PARSE_ERROR` | A symbol-pose JSON entry is malformed, or its rectangle/pin arrays have invalid shapes or values. | Validate each entry’s rectangle as two points and each pin as `[x, y, pin_name, spice_order]`. |
| `SYMBOL_POSE_RESOLUTION_ERROR` | A symbol pose could not be resolved to `.asy` geometry and pins. The message includes the underlying symbol lookup error when available. | Verify the `SYMBOL` value, configured search roots, `.asy` validity, orientation, and pin metadata. |

## Placement and wiring errors

| Code | Meaning | Recommended advice |
|---|---|---|
| `AUTOPLACE_FAILED` | Automatic placement could not resolve symbol geometry, find a collision-free layout, or produce a usable placement/wiring result. The detailed message identifies the failing instance/symbol when geometry lookup is the cause. | First inspect the symbol-initial JSON. Confirm every `SYMBOL` resolves to an `.asy` file. Then check `minimum_dist`, `wire_pin_out_dist`, `grid_size`, `autoplace_iter`, and circuit connectivity. |
| `INVALID_WIRE_PATH` | The wire JSON output/input path is invalid. | Pass a valid path-like value and ensure its parent can be written. |
| `WIRE_READ_ERROR` | A wire JSON file could not be read. | Check the file path and permissions. |
| `WIRE_PARSE_ERROR` | Wire JSON is malformed or does not contain the expected mapping/rows. | Use a JSON object whose values are wire rows `[x1, y1, x2, y2]`; verify all coordinates are numeric. |
| `WIRING_GENERATION_ERROR` | Net attachments or routed wire groups failed structural checks. Typical causes are missing pin attachments, disconnected routes, non-orthogonal segments, or wire intersections with other nets. | Inspect the reported netlist line; verify pin geometry, increase available layout space, adjust routing clearance/grid settings, or use the bounded net-label fallback in autoplace. |

## Diagnostic-only and internal pipeline codes

These codes can be returned by comparison or intermediate helpers, even though they are not usually the first error seen from the top-level conversion function.

| Code | Meaning | Recommended advice |
|---|---|---|
| `ASC_COMPARE_DIAGNOSTIC_ERROR` | Structural comparison could not build a component signature from an ASC file. | Validate both ASC files, resolve all symbols, and inspect the reported symbol line. |
| `INVALID_OUTPUT_PATH` | An intermediate writer rejected its output path. | Apply the common output-path advice above. |
| `WRITE_ERROR` | An intermediate writer failed to create its JSON/netlist/ASC output. | Apply the common write-error advice above. |

## Human-readable validation messages

Validators intentionally return descriptive messages instead of uppercase codes:

| Message pattern | Used by | Meaning |
|---|---|---|
| `File not found!` | ASC, ASY, and netlist validators | The input path does not identify a file. |
| `No permission to read file!` | ASC, ASY, and netlist validators | The file exists but cannot be read. |
| `Header information is invalid! Line <n>` | ASC header validation | The `Version`/`SHEET` header is missing or malformed. |
| `Line format/spacing is invalid! Line <n>` | ASC and netlist format validation | A record has invalid keyword, spacing, token count, or value syntax. |
| `Footer information is invalid! Line <n>` | ASC and netlist footer validation | Required analysis/footer structure is missing or malformed. |
| `LTspice ASY file is invalid! Line <n>` | ASY validation | The symbol header, drawing record, pin, or attribute is malformed. |
| `Node is not connected correctly! Line <n>` | Netlist connectivity validation | A non-exempt node occurs on fewer than two device ports. |
| `Unable to plot network graph!` | Network graph plotting | The input could not be parsed/plotted or the requested image format is unsupported. |
| `Unable to write image file!` | Network graph plotting | The image output could not be created or written. |

## Reading detailed messages

Detailed messages retain the leading code so callers can branch on it while still showing actionable context to users. For example:

```text
AUTOPLACE_FAILED: Unable to resolve geometry for instance 'XU1' for symbol 'level2' at orientation 'R0': SYMBOL_POSE_RESOLUTION_ERROR: Unable to locate LTspice symbol file ... Advice: add the directory containing the .asy file to convert_settings['custom_search_paths'] ...
```

Recommended handling:

```python
success, message, line_number = ltspice_netlist_to_asc(netlist, asc_out, settings)
if not success:
    code = message.split(":", 1)[0]
    print(f"{code} at line {line_number}: {message}")
```

Do not assume that every failure has a nonzero line number. File access, settings, output, placement, and routing failures often use `0`.

## Pipeline triage order

For a failed netlist-to-ASC conversion, investigate in this order:

1. `INVALID_CONVERT_SETTINGS`, `INVALID_NETLIST_FILE`, or `NETLIST_READ_ERROR` — fix inputs and settings first.
2. `UNKNOWN_SYMBOL` or `SYMBOL_POSE_RESOLUTION_ERROR` — verify `.asy` search roots and `ModelFile` hints.
3. `AUTOPLACE_FAILED` — inspect symbol geometry, collisions, placement clearance, and iteration settings.
4. `WIRING_GENERATION_ERROR` — inspect pin attachments, orthogonality, obstacles, and route clearance.
5. `INVALID_GENERATED_ASC` — validate the final generated schematic and inspect the reported line.

This file documents the current package behavior. Add a row here whenever a new public error code is introduced.
