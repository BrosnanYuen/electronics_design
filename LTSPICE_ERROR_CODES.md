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
| `INVALID_CONVERT_SETTINGS` | `convert_settings` is not a mapping, or one of its numeric/path-related settings is invalid. | Pass a dictionary-like mapping. Check `minimum_dist`, `wire_pin_out_dist`, `grid_size`, `autoplace_iter`, `ltspice_version`, and the LTspice search-path values. |
| `INVALID_OUTPUT_PATH` | The requested output path is not path-like or cannot be accepted by the API. | Pass a writable file path and create or permit its parent directory. |
| `WRITE_ERROR` | An output file could not be written. | Check the parent directory, permissions, available space, and whether another process has locked the file. |
| `NETLIST_READ_ERROR` | The netlist could not be read after path validation. | Check that the file still exists, is readable, and uses a supported text encoding. |
| `INVALID_NETLIST_FILE` | The netlist failed the project’s format validator. | Inspect the reported line for a bad leading keyword, merged tokens, invalid pin count, or malformed continuation. Run `is_valid_ltspice_netlist_format()` first. |
| `INVALID_ASC_FILE` | The ASC file failed the required header, spacing, or footer checks before conversion. | Run the three ASC validators separately to identify the failing section. |
| `ASC_READ_ERROR` | The ASC file could not be read after validation. | Check the path, permissions, and file encoding. |
| `ASC_PARSE_ERROR` | ASC records or symbol pin data could not be parsed. | Inspect the reported line and verify record token counts, coordinates, orientations, and pin metadata. |
| `INVALID_GENERATED_NETLIST` | ASC-to-netlist conversion produced a netlist that failed validation. | Inspect the generated-netlist line reported by the result; check symbol pin orders, payloads, and generated directives. |
| `INVALID_GENERATED_ASC` | Netlist/symbol/wire-to-ASC conversion produced an ASC file that failed validation. | Inspect the generated ASC line reported by the result and verify symbol poses, wires, flags, and analysis text. |

## Symbol and symbol-pose errors

| Code | Meaning | Recommended advice |
|---|---|---|
| `UNKNOWN_SYMBOL` | An ASC symbol cannot be found or cannot be matched to a loaded symbol definition. The message may include the symbol name, instance, expected `.asy` filename, and searched roots. | Add the directory containing the `.asy` file to `convert_settings['custom_search_paths']`, or correct the symbol name. For `X...` devices, preserve an LTspice `ModelFile` hint when the `.subckt` name differs from the `.asy` filename. |
| `UNCONNECTED_SYMBOL_PIN` | A symbol has no usable pin-to-net mapping during ASC-to-netlist conversion. | Connect the pin with a `WIRE`/`FLAG`, verify the symbol’s `PINATTR SpiceOrder`, and check that the symbol is not floating unintentionally. |
| `MISSING_COMPONENT_PAYLOAD` | A component requires a value, model, or other SPICE payload, but none was available. | Add the required `SYMATTR Value`/model data or ensure the symbol definition supplies a valid default. |
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
