* [Introduction](#_introduction)
* [Schematic Format (.asc)](#_schematic_format_asc)
  + [Keywords](#_keywords)
  + [VERSION](#_version)
  + [SHEET](#_sheet)
  + [SYMBOL](#_symbol)
  + [WIRE](#_wire)
  + [FLAG](#_flag)
  + [DATAFLAG](#_dataflag)
  + [LINE](#_line)
  + [CIRCLE](#_circle)
  + [ARC](#_arc)
  + [RECTANGLE](#_rectangle)
  + [TEXT](#_text)
  + [WINDOW](#_window)
  + [SYMATTR](#_symattr)
  + [IOPIN](#_iopin)
  + [BUSTAP](#_bustap)
* [Orientation Encoding](#orientation-encoding)
* [Justification Encoding](#justification-encoding)
* [Line Style Values](#line-style-values)
* [Line Width Values](#_line_width_values)
* [Symbol Format (.asy)](#_symbol_format_asy)
  + [Keywords](#_keywords_2)
  + [PIN](#_pin)
  + [PINATTR](#_pinattr)
  + [SYMBOLTYPE](#_symboltype)
* [Window Number Mappings](#window-number-mappings)
* [SYMATTR Keys](#symattr-keys)
* [Coordinate System](#_coordinate_system)
  + [Page Centering](#_page_centering)
  + [Font Size Mapping](#_font_size_mapping)
* [SPICE Simulation Mapping](#_spice_simulation_mapping)
* [Hierarchical Design Detection](#_hierarchical_design_detection)
* [Imported Elements](#_imported_elements)
* [Limitations](#_limitations)
* [Undocumented Areas](#_undocumented_areas)

1. [Import Formats](/en/import-formats/index.html) >
2. LTspice

# LTspice

## Introduction

LTspice (by Analog Devices, formerly Linear Technology) is a SPICE simulation tool
for analog circuit design. KiCad provides a schematic-only importer for LTspice files
(LTspice has no layout capability).

Supported file types:

* `.asc` — LTspice schematic (the import entry point)
* `.asy` — LTspice symbol definition (consumed during import to reconstruct component
  graphics and pin definitions)

Both file types are plain text, line-oriented formats. Each line begins with an
uppercase keyword followed by space-separated parameters. The parser splits lines on
spaces and reconstructs multi-word values (such as SYMATTR values containing spaces) by
concatenating all tokens from the value position onward. Files may use either LF or
CR+LF line endings; trailing carriage returns are stripped during parsing.

## Schematic Format (.asc)

An `.asc` file describes one schematic sheet. It contains a header declaring the
version and sheet dimensions, followed by an unordered sequence of element lines.

### Keywords

| Keyword | Description |
| --- | --- |
| VERSION | File format version number |
| SHEET | Sheet number and dimensions |
| SYMBOL | Component instance placement |
| WIRE | Electrical connection between two points |
| FLAG | Net label or power symbol |
| DATAFLAG | Data expression marker attached to a wire |
| LINE | Graphical line |
| CIRCLE | Graphical circle |
| ARC | Graphical arc |
| RECTANGLE | Graphical rectangle |
| TEXT | Text annotation or SPICE directive |
| WINDOW | Attribute display position override (follows a SYMBOL) |
| SYMATTR | Symbol attribute value override (follows a SYMBOL) |
| IOPIN | Hierarchical I/O pin marker |
| BUSTAP | Bus tap connection |

### VERSION

Declares the file format version.

```
VERSION <version>
```

The version may be an integer (`4`) or a dotted pair (`4.1`). When a dot is present,
the major and minor parts are parsed separately.

### SHEET

Declares the sheet number and drawing area size.

```
SHEET <sheet_number> <width> <height>
```

All three parameters are integers. The width and height define the drawing area in
LTspice coordinate units.

### SYMBOL

Places a component instance on the schematic.

```
SYMBOL <name> <x> <y> <orientation>
```

|  |  |
| --- | --- |
| name | Symbol name or library-relative path. Backslashes in the name are converted to forward slashes for cross-platform path resolution (e.g., `Opamps\UniversalOpamp2` becomes `Opamps/UniversalOpamp2`). |
| x, y | Placement position in LTspice coordinates. |
| orientation | One of the eight [orientation values](#orientation-encoding). |

After a SYMBOL line, any number of WINDOW and SYMATTR lines may follow. These modify
the most recently declared symbol.

### WIRE

Defines an electrical connection between two points.

```
WIRE <x1> <y1> <x2> <y2>
```

All four parameters are integer coordinates.

### FLAG

Places a net label at a point.

```
FLAG <x> <y> <name>
```

A FLAG with the name `0` is converted to a GND power symbol during import. All other
names become global labels. The font size defaults to 2.

### DATAFLAG

Places a data expression marker.

```
DATAFLAG <x> <y> <expression>
```

Data flags are imported as directive labels. The font size defaults to 2.

### LINE

Draws a graphical line on the schematic.

```
LINE <line_width> <x1> <y1> <x2> <y2> [<line_style>]
```

|  |  |
| --- | --- |
| line\_width | `Normal` or `Wide` (case-insensitive). |
| x1, y1 | Start point. |
| x2, y2 | End point. |
| line\_style | Optional integer, defaults to 0. See [Line Style Values](#line-style-values). |

### CIRCLE

Draws a graphical circle. The circle is defined by its bounding rectangle.

```
CIRCLE <line_width> <x1> <y1> <x2> <y2> [<line_style>]
```

|  |  |
| --- | --- |
| line\_width | `Normal` or `Wide`. |
| x1, y1 | First corner of the bounding rectangle. |
| x2, y2 | Opposite corner of the bounding rectangle. |
| line\_style | Optional integer, defaults to 0. See [Line Style Values](#line-style-values). |

The center is computed as `((x1+x2)/2, (y1+y2)/2)` and the radius as `(x1-x2)/2`.

### ARC

Draws a graphical arc. The arc is inscribed in a bounding rectangle, with explicit
start and end points that lie on the arc. The arc is drawn counterclockwise from the
start point to the end point.

```
ARC <line_width> <x1> <y1> <x2> <y2> <start_x> <start_y> <end_x> <end_y> [<line_style>]
```

|  |  |
| --- | --- |
| line\_width | `Normal` or `Wide`. |
| x1, y1 | First corner of the bounding rectangle. |
| x2, y2 | Opposite corner of the bounding rectangle. |
| start\_x, start\_y | Arc start point. |
| end\_x, end\_y | Arc end point. |
| line\_style | Optional integer, defaults to 0. See [Line Style Values](#line-style-values). |

|  |  |
| --- | --- |
|  | In `.asc` files the parser swaps start and end points: the token labeled "start" in the file is stored as the arc end, and vice versa. This does not occur in `.asy` files. |

### RECTANGLE

Draws a graphical rectangle.

```
RECTANGLE <line_width> <x1> <y1> <x2> <y2> [<line_style>]
```

|  |  |
| --- | --- |
| line\_width | `Normal` or `Wide`. |
| x1, y1 | First corner. |
| x2, y2 | Opposite corner. |
| line\_style | Optional integer, defaults to 0. See [Line Style Values](#line-style-values). |

### TEXT

Places a text annotation or SPICE directive.

```
TEXT <x> <y> <justification> <font_size> <value>
```

|  |  |
| --- | --- |
| x, y | Text position. |
| justification | See [Justification Encoding](#justification-encoding). |
| font\_size | Integer font size (1—​7). |
| value | The text content. Multi-word values span to the end of the line. |

Text values use prefix characters to indicate SPICE directives versus comments:

* Values starting with `!` are SPICE directives. The leading `!` is stripped
  and subsequent `! ` sequences are converted to line breaks.
* Values starting with `;` are comments. The leading `;` is stripped and
  subsequent `; ` sequences are converted to line breaks.
* The escape sequence `\n` is converted to a line break in all cases.

### WINDOW

Overrides the display position of a symbol attribute field. Must follow a SYMBOL line.

```
WINDOW <number> <x> <y> <justification> <font_size>
```

|  |  |
| --- | --- |
| number | Window number identifying which attribute field to position. See [Window Number Mappings](#window-number-mappings). |
| x, y | Display position relative to the symbol origin. |
| justification | See [Justification Encoding](#justification-encoding). |
| font\_size | Integer font size. A font size of 0 hides the field. |

If a WINDOW line in an `.asc` file specifies a window number that already exists in
the symbol’s `.asy` definition, the `.asc` values override the `.asy` values.

### SYMATTR

Sets a symbol attribute value. Must follow a SYMBOL line.

```
SYMATTR <key> <value>
```

The key is stored in uppercase. The value spans to the end of the line. A value of
`""` (two double-quote characters) is treated as an empty string.
See [SYMATTR Keys](#symattr-keys) for known attribute keys.

### IOPIN

Marks a hierarchical I/O pin location.

```
IOPIN <x> <y> <polarity>
```

|  |  |
| --- | --- |
| polarity | One of `In`, `Out`, or `BiDir` (also accepted as `I`, `O`, `B`). |

IOPINs are matched to FLAG elements at the same coordinates to determine the pin name.
The matched FLAG is consumed and not imported as a separate net label.

### BUSTAP

Defines a bus tap connection.

```
BUSTAP <x1> <y1> <x2> <y2>
```

Wires connected to the bus tap’s start point are promoted to the bus layer.

## Orientation Encoding

Symbols can be placed in eight orientations, combining rotation and mirror operations.
The orientation value appears as the last parameter of a SYMBOL line.

| Value | Rotation | Mirror | KiCad Transformation |
| --- | --- | --- | --- |
| R0 | 0deg | No | No transformation |
| R90 | 90deg CW | No | Rotate 180deg then rotate 90deg CCW |
| R180 | 180deg | No | Rotate 180deg |
| R270 | 270deg CW | No | Rotate 90deg CCW |
| M0 | 0deg | Yes | Mirror about Y axis |
| M90 | 90deg CW | Yes | Mirror about Y axis then rotate 90deg CCW |
| M180 | 180deg | Yes | Mirror about X axis |
| M270 | 270deg CW | Yes | Mirror about Y axis then rotate 90deg CW |

## Justification Encoding

Text and window positions use justification strings to control alignment and orientation.
The "V" prefix indicates vertical (90deg) text.

| Value | Horizontal Align | Vertical Align | Text Angle |
| --- | --- | --- | --- |
| Left | Left | Center | Horizontal |
| Center | Center | Center | Horizontal |
| Right | Right | Center | Horizontal |
| Top | Center | Top | Horizontal |
| Bottom | Center | Bottom | Horizontal |
| VLeft | Left | Center | Vertical |
| VCenter | Center | Center | Vertical |
| VRight | Right | Center | Vertical |
| VTop | Center | Top | Vertical |
| VBottom | Center | Bottom | Vertical |
| Invisible | — | — | Hidden |

For multiline text, horizontal justification modes (Left, Center, Right) force
vertical alignment to Top with a half-line-height offset. Vertical text modes
(VLeft, VCenter, VRight) apply the same adjustment on the horizontal axis.

Pin justification uses a subset of these values (Left, Right, Top, Bottom, None and
their vertical variants). The pin justification determines pin orientation during
import: Left maps to pin pointing right, Right to left, Bottom to up, Top to down.
A justification of None hides the pin name.

## Line Style Values

Graphical elements (LINE, CIRCLE, ARC, RECTANGLE) accept an optional line style integer.

| Value | Style |
| --- | --- |
| 0 | Solid (default) |
| 1 | Dash |
| 2 | Dot |
| 3 | Dash-dot |
| 4 | Dash-dot-dot |

## Line Width Values

| Value | Width |
| --- | --- |
| Normal | 5 units (default) |
| Wide | 10 units |

KiCad maps Normal to 6 mils and Wide to 12 mils stroke width.

## Symbol Format (.asy)

An `.asy` file defines the graphical appearance and pin layout of a single LTspice
symbol. The file shares many keywords with the `.asc` format but adds pin and symbol
type definitions.

### Keywords

| Keyword | Description |
| --- | --- |
| LINE | Graphical line (same syntax as `.asc`) |
| RECTANGLE | Graphical rectangle (same syntax as `.asc`) |
| CIRCLE | Graphical circle (same syntax as `.asc`) |
| ARC | Graphical arc (same syntax as `.asc`, without the start/end swap) |
| WINDOW | Attribute display position |
| SYMATTR | Symbol attribute definition |
| PIN | Pin definition |
| PINATTR | Pin attribute (follows a PIN) |
| SYMBOLTYPE | Symbol type declaration |

### PIN

Defines a symbol pin.

```
PIN <x> <y> <justification> <name_offset>
```

|  |  |
| --- | --- |
| x, y | Pin location in symbol coordinates. |
| justification | Pin orientation and name visibility. See [Justification Encoding](#justification-encoding). |
| name\_offset | Integer offset for the pin name text. |

After a PIN line, any number of PINATTR lines may follow to set pin attributes.

### PINATTR

Sets an attribute on the most recently declared pin.

```
PINATTR <name> <value>
```

The value spans to the end of the line. Common pin attributes:

| Attribute | Description |
| --- | --- |
| PinName | Display name for the pin |
| SpiceOrder | Pin order in SPICE netlist |

### SYMBOLTYPE

Declares the symbol category.

```
SYMBOLTYPE <type>
```

| Value | Description |
| --- | --- |
| Cell | Standard component symbol (default) |
| Block | Block diagram or subcircuit symbol |

## Window Number Mappings

Window numbers identify which attribute field a WINDOW line positions. The importer
maps a subset of these to KiCad fields; unmapped numbers are recognized but ignored.

| Number | Attribute Name | KiCad Field Mapping |
| --- | --- | --- |
| -1 | PartNum | — |
| 0 | InstName | Reference |
| 1 | Type | — |
| 2 | RefName | — |
| 3 | Value | Value |
| 5 | QArea | — |
| 8 | Width | — |
| 9 | Length | — |
| 10 | Multi | — |
| 16 | Nec | — |
| 38 | SpiceModel | Sim.Name |
| 39 | SpiceLine | Sim.Params |
| 40 | SpiceLine2 | — |
| 47 | Def\_Sub | — |
| 50 | Digital\_Timing\_Model | — |
| 51 | Digital\_Extracts | — |
| 52 | Digital\_IO\_Model | — |
| 53 | Digital\_Line | — |
| 54 | Digital\_Primitive | — |
| 55 | Digital\_MNTYMXDLY | — |
| 56 | Digital\_IO\_LEVEL | — |
| 57 | Digital\_StdCell | — |
| 58 | Digital\_File | — |
| 105 | Cell | — |
| 106 | W/L | — |
| 107 | PSIZE | — |
| 108 | NSIZE | — |
| 109 | sheets | — |
| 110 | sh# | — |
| 111 | Em\_Scale | — |
| 112 | Epi | — |
| 113 | Sinker | — |
| 114 | Multi5 | — |
| 118 | AQ | — |
| 119 | AQSUB | — |
| 120 | ZSIZE | — |
| 121 | ESR | — |
| 123 | Value2 | — |
| 124 | COUPLE | — |
| 125 | Voltage | — |
| 126—​129 | Area1—​Area4 | — |
| 130—​133 | Multi1—​Multi4 | — |
| 134 | DArea | — |
| 135 | DPerim | — |
| 136 | CArea | — |
| 137 | CPerim | — |
| 138 | Shrink | — |
| 139 | Gate\_Resize | — |
| 142 | BP | — |
| 143 | BN | — |
| 144 | Sim\_Level | — |
| 146 | G\_Voltage | — |
| 150 | SpiceLine3 | — |
| 153 | D\_VOLTAGES | — |
| 156 | Version | — |
| 157 | Comment | — |
| 158 | XDef\_Sub | — |
| 159 | LVS\_Area | — |
| 162—​166 | User1—​User5 | — |
| 167 | Root | — |
| 168 | Class | — |
| 169 | Geometry | — |
| 170 | WL\_Delimiter | — |
| 175 | T1 | — |
| 176 | T2 | — |
| 184 | DsgnName | — |
| 185 | Designer | — |
| 190 | RTN | — |
| 191 | PWR | — |
| 192 | BW | — |
| 201 | CAPROWS | — |
| 202 | CAPCOLS | — |
| 203 | NF | — |
| 204 | SLICES | — |
| 205 | CUR | — |
| 206 | TEMPRISE | — |
| 207 | STRIPS | — |
| 208 | WEM | — |
| 209 | LEM | — |
| 210 | BASES | — |
| 211 | COLS | — |
| 212 | XDef\_Tub | — |

|  |  |
| --- | --- |
|  | Only window numbers 0, 3, 38, and 39 are actively mapped to KiCad fields. All other window numbers are parsed without error but have no effect on the imported schematic. |

## SYMATTR Keys

SYMATTR lines set key-value attributes on symbols. Keys are stored in uppercase
internally. The following keys are used during import:

| Key | Description |
| --- | --- |
| InstName | Reference designator (mapped to KiCad Reference field) |
| Value | Component value (mapped to KiCad Value field) |
| Value2 | Secondary value (used as fallback or appended to simulation model) |
| Prefix | SPICE netlist prefix character (R, C, L, X, etc.) |
| Type | Device type for semiconductor model lookup |
| Description | Component description text |
| SpiceLine | SPICE parameter string (mapped to Sim.Params) |
| SpiceLine2 | Additional SPICE parameters |
| ModelFile | Path to external SPICE model file (mapped to Sim.Library) |

The Prefix attribute has special significance for hierarchical design detection:
a symbol whose `.asy` file lacks a `Prefix` attribute is treated as a sub-schematic
rather than a component.

## Coordinate System

LTspice uses an integer coordinate system with Y increasing downward. The coordinate
scaling formula used during import is:

```
kicad_coord = MilsToIU( rescale( 50, ltspice_coord, 16 ) )
```

This maps 16 LTspice units to 50 mils (1.27 mm) in KiCad’s internal coordinate space.
The inverse transform is:

```
ltspice_coord = IUToMils( rescale( 16, kicad_coord, 50 ) )
```

### Page Centering

After converting all coordinates, the importer centers the design on the KiCad page.
It computes a bounding box of all elements and offsets them to center on the page,
clamping to a 10-grid margin if the design exceeds page dimensions. The offset snaps
to a 50-mil grid.

### Font Size Mapping

LTspice font sizes (1—​7) map to KiCad text sizes in mils:

| LTspice Size | KiCad Mils |
| --- | --- |
| 1 | 36 |
| 2 | 42 |
| 3 | 50 |
| 4 | 60 |
| 5 | 72 |
| 6 | 88 |
| 7 | 108 |

A font size of 0 in a WINDOW definition within an `.asy` file is treated as size 2
(LTspice appears to ignore the hidden property from `.asy` files). A font size of 0
in an `.asc` WINDOW override hides the field.

## SPICE Simulation Mapping

The importer translates LTspice component attributes into KiCad simulation fields
(`Sim.Device`, `Sim.Params`, `Sim.Library`, `Sim.Name`, `Sim.Type`) based on the
symbol’s Prefix attribute.

| Prefix | Sim.Device | Behavior |
| --- | --- | --- |
| R | R | Non-inferred passive; `Sim.Params=R=${VALUE}` |
| C | C | Non-inferred passive; `Sim.Params=C=${VALUE}` |
| L | L | Non-inferred passive; `Sim.Params=L=${VALUE}` |
| E, F, G, H | (prefix) | Controlled source; `Sim.Params=gain=${VALUE}` |
| B | V or I | Behavioral source; device is V for symbols starting with `BV`, I for `BI` |
| T | TLINE | Transmission line; value is passed directly as `Sim.Params` |
| V, I | SPICE | Voltage/current source with `type` and `model` parameters |
| X | SUBCKT | Subcircuit; SpiceLine becomes `Sim.Params` |
| (other) | SPICE | Generic SPICE device with model library lookup |

For generic SPICE devices, the importer resolves model libraries from:

* The `ModelFile` symbol attribute
* The `Type` attribute matched against standard library files (`standard.dio`,
  `standard.bjt`, `standard.jft`, `standard.mos`)
* Include paths discovered from `.include`, `.inc`, and `.lib` SPICE directives
  in TEXT elements

## Hierarchical Design Detection

A symbol is treated as a hierarchical sub-schematic when its `.asy` file does not
contain a `SYMATTR Prefix` line. The absence of a Prefix attribute signals that the
symbol represents a sub-circuit sheet rather than a component.

When a sub-schematic is detected:

* A corresponding `.asc` file is loaded as a child sheet.
* The symbol graphics from the `.asy` file are drawn directly on the parent sheet
  (not as a KiCad symbol), and a KiCad sheet object is sized to match.
* IOPIN elements in the `.asc` file become hierarchical labels.
* Wires connecting to sub-schematic pin locations are adjusted to connect to the
  sheet boundary.

## Imported Elements

* Component instances with position, orientation (8-way rotation/mirror), and attribute
  overrides from WINDOW and SYMATTR lines
* Symbol graphics (lines, rectangles, circles, arcs) from `.asy` files with line style
  and width mapping
* Pins with name, position, and orientation from `.asy` definitions
* Wires as electrical connections between two points
* Net labels from FLAG elements (with `0` converted to GND power symbol)
* Data expression markers from DATAFLAG elements as directive labels
* Bus taps with wire-to-bus layer promotion
* Text annotations and SPICE directives with font size mapping and multiline support
* SPICE simulation fields (Sim.Device, Sim.Params, Sim.Library, Sim.Name, Sim.Type)
  derived from Prefix, Value, SpiceLine, ModelFile, and Type attributes
* Hierarchical sub-schematics detected by the absence of a Prefix attribute, with IOPIN
  elements converted to hierarchical labels
* Page centering with bounding box calculation and 50-mil grid snapping

## Limitations

* Custom LTspice symbol search paths are not supported.
* Only global labels and directive labels are implemented; other label types are not
  handled.
* Hierarchical sheet pin placement on sheet boundaries is not functional.
* Many window number types are recognized but not mapped to KiCad fields (see the
  full [window number table](#window-number-mappings)).
* All pins are created as passive type regardless of actual pin function.
* Window numbers outside the known set are silently ignored.

## Undocumented Areas

* The complete set of SYMBOLTYPE values beyond `Cell` and `Block` is unknown.
* The purpose of dotted-pair version numbers (e.g., `4.1` vs `4`) is unclear.

 Last Modified 2026-02-10

[![Developer Documentation | KiCad](/img/kicad_logo_small.png)](/en)

Search

---

* [Getting Started](/en/getting-started/index.html)
* [Build](/en/build/index.html)
  + [Getting Started](/en/build/getting-started/index.html)
  + [Linux](/en/build/linux/index.html)
  + [macOS](/en/build/macos/index.html)
  + [Windows (MSYS2)](/en/build/windows-msys2/index.html)
  + [Windows (Visual Studio)](/en/build/windows-msvc/index.html)
  + [Build Options](/en/build/compile-options/index.html)
* [Rules and Guidelines](/en/rules-guidelines/index.html)
  + [Code Style Policy](/en/rules-guidelines/code-style/index.html)
  + [Commit Message Format Policy](/en/rules-guidelines/commit/index.html)
  + [Feature Contribution Policy](/en/rules-guidelines/feature-proposals/index.html)
  + [Stable Release Policy](/en/rules-guidelines/release-policy/index.html)
  + [Code Design Guidelines](/en/rules-guidelines/code-policy/index.html)
  + [Icon Design Guidelines](/en/rules-guidelines/icon-design/index.html)
  + [KiCad Developer Culture](/en/rules-guidelines/culture/index.html)
  + [User Interface Policy](/en/rules-guidelines/ui/index.html)
  + [Anti-Patterns](/en/rules-guidelines/anti-patterns/index.html)
  + [Tool-Generated Content Policy](/en/rules-guidelines/tool-generated-content/index.html)
* [Components](/en/components/index.html)
  + [Settings Framework](/en/components/settings/index.html)
  + [Tool Framework](/en/components/tool-framework/index.html)
  + [Plugins Framework](/en/components/plugins/index.html)
  + [Testing](/en/components/testing/index.html)
  + [S-Expressions](/en/components/sexpr/index.html)
* [APIs and Bindings](/en/apis-and-binding/index.html)
  + [KiCad IPC API](/en/apis-and-binding/ipc-api/index.html)
    - [For KiCad Developers](/en/apis-and-binding/ipc-api/for-kicad-developers/index.html)
    - [For Add-on Developers](/en/apis-and-binding/ipc-api/for-addon-developers/index.html)
  + [HTTP Libraries](/en/apis-and-binding/http-libraries/index.html)
  + [PCB Python Bindings](/en/apis-and-binding/pcbnew/index.html)
* [Source Code Docs](/en/source-doxygen/index.html)
* [Translation](/en/translation/index.html)
* [KiCad Addons](/en/addons/index.html)
* [File Formats](/en/file-formats/index.html)
  + [S-Expression Format](/en/file-formats/sexpr-intro/index.html)
  + [Footprint Library File Format](/en/file-formats/sexpr-footprint/index.html)
  + [Board File Format](/en/file-formats/sexpr-pcb/index.html)
  + [Symbol Library File Format](/en/file-formats/sexpr-symbol-lib/index.html)
  + [Schematic File Format](/en/file-formats/sexpr-schematic/index.html)
  + [Work Sheet File Format](/en/file-formats/sexpr-worksheet/index.html)
  + [Legacy Formats (4.0 up to 6.0)](/en/file-formats/legacy-4-to-6/index.html)
  + [Legacy Board Format (pre 4.0)](/en/file-formats/legacy-pcb/index.html)
* [Import Formats](/en/import-formats/index.html)
  + [Allegro](/en/import-formats/allegro/index.html)
  + [Altium](/en/import-formats/altium/index.html)
  + [CADSTAR](/en/import-formats/cadstar/index.html)
  + [Eagle](/en/import-formats/eagle/index.html)
  + [EasyEDA](/en/import-formats/easyeda/index.html)
  + [Fabmaster](/en/import-formats/fabmaster/index.html)
  + [gEDA / Lepton EDA](/en/import-formats/geda/index.html)
  + [LTspice](/en/import-formats/ltspice/index.html)
  + [P-CAD](/en/import-formats/pcad/index.html)
  + [PADS](/en/import-formats/pads/index.html)

More

* [GitLab repo](https://gitlab.com/kicad/services/kicad-dev-docs)

---

* Language

  English
* Theme

  Auto
  Zen Light
  Zen Dark
* Clear History

Built with  by [Hugo](https://gohugo.io/)