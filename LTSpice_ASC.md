# LTspice ASC/ASY Keyword Spec (researched)

Generated: 2026-04-25 (America/Vancouver)

## Scope and reliability

- LTspice does **not publish a complete official `.asc`/`.asy` grammar spec**.
- The tables below combine:
  - KiCad's LTspice importer documentation (most structured keyword/parameter reference).
  - LTspice help pages for SPICE directives (dot commands).
  - Real LTspice symbol/schematic examples for case/style confirmation.
- Confidence tags:
  - `High`: directly documented in KiCad LTspice format doc or LTspice help.
  - `Medium`: confirmed by real examples, but not fully formalized by vendor.

---

## Project validator rules

This repository now implements four public `.asc` validation APIs:

- `is_valid_ltspice_asc_header(filepath)`
- `is_valid_ltspice_asc_spacing(filepath)`
- `is_valid_ltspice_asc_footer(filepath)`
- `is_valid_ltspice_asc_file(filepath)`

These APIs do not attempt full semantic LTspice schematic validation. They implement a project-specific structural validator over a practical subset of the format documented below.

### Header rule used by this project

`is_valid_ltspice_asc_header(filepath)` requires:

- the first nonblank structural line to be `Version <n>` or `VERSION <n>`
- the second nonblank structural line to be `SHEET <sheet_number> <width> <height>`

The validator is intentionally strict here because the repository `valid_asc/` samples all follow that pattern.

### Spacing and record-syntax rule used by this project

`is_valid_ltspice_asc_spacing(filepath)` currently accepts these `.asc` line-leading keywords:

- `Version` / `VERSION`
- `SHEET`
- `WIRE`
- `FLAG`
- `DATAFLAG`
- `SYMBOL`
- `WINDOW`
- `SYMATTR`
- `TEXT`
- `LINE`
- `RECTANGLE`
- `CIRCLE`
- `ARC`
- `IOPIN`
- `BUSTAP`

The validator checks stable token structure only. Examples:

- `WIRE` requires four integer coordinates
- `FLAG` requires two integer coordinates plus a net-name token
- `SYMBOL` requires name, `x`, `y`, and an orientation in `R0/R90/R180/R270/M0/M90/M180/M270`
- `WINDOW` requires `number`, `x`, `y`, `justification`, `font_size`
- `TEXT` requires `x`, `y`, `justification`, `font_size`, and free-form payload
- `LINE`, `RECTANGLE`, `CIRCLE`, and `ARC` accept the documented width token and optional style id

It does not currently validate:

- symbol-library existence
- schematic electrical connectivity
- semantic correctness of arbitrary `SYMATTR` payloads
- exact drawing meaning of coordinates

### Footer rule used by this project

`.asc` does not have a literal footer like `.net`, so `is_valid_ltspice_asc_footer(filepath)` uses a schematic-specific rule:

- the file must already pass `.asc` spacing validation
- the file must contain at least one valid simulation analysis directive embedded in a `TEXT ... !.<directive>` line

Accepted analysis directives are:

- `.ac`
- `.dc`
- `.noise`
- `.op`
- `.tf`
- `.tran`
- `.fra`

Non-analysis directives such as `.step`, `.ic`, `.model`, `.lib`, and `.include` are allowed, but they do not satisfy the analysis requirement on their own.

One practical repository-specific rule is also implemented:

- `TEXT ... !;...` is treated as disabled/commented-out directive text, not as an active malformed directive

### Whole-file rule used by this project

`is_valid_ltspice_asc_file(filepath)` composes:

1. `is_valid_ltspice_asc_header(filepath)`
2. `is_valid_ltspice_asc_spacing(filepath)`
3. `is_valid_ltspice_asc_footer(filepath)`

The first failing public result is returned unchanged.

---

## 1) `.asc` schematic file: line-beginning keywords

| Keyword (line start) | Typical syntax | Parameters (what each means) | Meaning / role | Confidence |
|---|---|---|---|---|
| `VERSION` / `Version` | `VERSION <version>` | `version`: format version (`4`, `4.1`, etc.) | Declares schematic file format version. | High |
| `SHEET` | `SHEET <sheet_number> <width> <height>` | `sheet_number`: logical sheet id; `width`,`height`: drawing area in LTspice coords | Sheet metadata and canvas size. | High |
| `SYMBOL` | `SYMBOL <name> <x> <y> <orientation>` | `name`: symbol/library-relative path; `x`,`y`: placement origin; `orientation`: one of `R0/R90/R180/R270/M0/M90/M180/M270` | Places a component instance. | High |
| `WIRE` | `WIRE <x1> <y1> <x2> <y2>` | start/end coordinates | Electrical connection segment. | High |
| `FLAG` | `FLAG <x> <y> <name>` | `x`,`y`: label location; `name`: net label (`0` is ground) | Net naming / ground marker. | High |
| `DATAFLAG` | `DATAFLAG <x> <y> <expression>` | `x`,`y`: marker position; `expression`: data/probe text | Data expression marker attached to net/wire area. | High |
| `LINE` | `LINE <line_width> <x1> <y1> <x2> <y2> [<line_style>]` | `line_width`: `Normal`/`Wide`; points; optional style id | Graphical line (non-electrical drawing). | High |
| `CIRCLE` | `CIRCLE <line_width> <x1> <y1> <x2> <y2> [<line_style>]` | bounding-rectangle corners + optional style | Graphical circle. | High |
| `ARC` | `ARC <line_width> <x1> <y1> <x2> <y2> <start_x> <start_y> <end_x> <end_y> [<line_style>]` | bounding rectangle, arc start/end points, style | Graphical arc. | High |
| `RECTANGLE` | `RECTANGLE <line_width> <x1> <y1> <x2> <y2> [<line_style>]` | corners + optional style | Graphical rectangle. | High |
| `TEXT` | `TEXT <x> <y> <justification> <font_size> <value>` | `x`,`y`: location; `justification`: alignment/orientation; `font_size`: integer; `value`: text to EOL | Annotation or directive carrier (`!` for SPICE directive, `;` for comment). | High |
| `WINDOW` | `WINDOW <number> <x> <y> <justification> <font_size>` | `number`: attribute-window id; `x`,`y`: offset; `justification`; `font_size` (`0` may hide in `.asc`) | Overrides symbol attribute display position (must follow `SYMBOL`). | High |
| `SYMATTR` | `SYMATTR <key> <value>` | `key`: attribute name; `value`: attribute text to EOL | Sets instance attribute (must follow `SYMBOL`). | High |
| `IOPIN` | `IOPIN <x> <y> <polarity>` | `x`,`y`: pin marker location; `polarity`: `In/Out/BiDir` (or `I/O/B`) | Hierarchical sheet I/O marker. | High |
| `BUSTAP` | `BUSTAP <x1> <y1> <x2> <y2>` | tap endpoints | Bus tap connection geometry. | High |

---

## 2) Shared parameter value sets used by `.asc`

### 2.1 `SYMBOL` orientation

| Value | Meaning |
|---|---|
| `R0` | Rotate 0 deg |
| `R90` | Rotate 90 deg |
| `R180` | Rotate 180 deg |
| `R270` | Rotate 270 deg |
| `M0` | Mirrored, 0 deg |
| `M90` | Mirrored + 90 deg |
| `M180` | Mirrored + 180 deg |
| `M270` | Mirrored + 270 deg |

### 2.2 Text/window justification

| Value | Meaning |
|---|---|
| `Left` `Center` `Right` | Horizontal text alignment |
| `Top` `Bottom` | Vertical alignment variants |
| `VLeft` `VCenter` `VRight` `VTop` `VBottom` | Vertical text orientation variants |
| `Invisible` | Hidden text |

### 2.3 Drawing style parameters

| Parameter | Allowed values | Meaning |
|---|---|---|
| `line_width` | `Normal`, `Wide` | Stroke width class |
| `line_style` | `0..4` | `0=Solid`, `1=Dash`, `2=Dot`, `3=Dash-dot`, `4=Dash-dot-dot` |

### 2.4 `IOPIN` polarity

| Value | Meaning |
|---|---|
| `In` / `I` | Input pin |
| `Out` / `O` | Output pin |
| `BiDir` / `B` | Bidirectional pin |

---

## 3) `.asy` symbol file: line-beginning keywords

| Keyword (line start) | Typical syntax | Parameters (what each means) | Meaning / role | Confidence |
|---|---|---|---|---|
| `VERSION` / `Version` | `Version <version>` | `version`: symbol format version (commonly `4`) | Symbol file header version. | Medium (example-confirmed) |
| `SYMBOLTYPE` / `SymbolType` | `SymbolType <CELL|BLOCK>` | symbol class | Declares symbol type. | High |
| `LINE` | same as `.asc` | width + coords + optional style | Symbol graphic primitive. | High |
| `RECTANGLE` | same as `.asc` | width + corners + style | Symbol graphic primitive. | High |
| `CIRCLE` | same as `.asc` | width + corners + style | Symbol graphic primitive. | High |
| `ARC` | same as `.asc` | width + bounding box + start/end + style | Symbol graphic primitive. | High |
| `WINDOW` | `WINDOW <number> <x> <y> <justification> <font_size>` | window id + position/display settings | Controls where symbol attributes are shown. | High |
| `SYMATTR` | `SYMATTR <key> <value>` | key/value attribute | Symbol attribute metadata. | High |
| `PIN` | `PIN <x> <y> <justification> <name_offset>` | `x`,`y`: pin location; `justification`: pin orientation/label side; `name_offset`: label offset control | Declares symbol pin. | High |
| `PINATTR` | `PINATTR <key> <value>` | common keys: `PinName`, `SpiceOrder` | Metadata for the most recent `PIN`. | High |

Notes:
- `.asy` keyword casing is commonly mixed (`Version`, `SymbolType`) in real files.
- Real-world `PINATTR` keys most frequently seen: `PinName`, `SpiceOrder`.

---

## 4) `SYMATTR` keys that matter for simulation/library/schematic generation

`SYMATTR` is open-ended, but these keys are the most important for practical LTspice generation pipelines:

| Key | Meaning |
|---|---|
| `InstName` | Instance reference designator (`R1`, `U2`, etc.) |
| `Value` | Primary value/model text |
| `Value2` | Secondary value text (frequently extra model params) |
| `Prefix` | SPICE device prefix (`R`, `C`, `L`, `X`, etc.) |
| `Type` | Device/model type hint |
| `ModelFile` | External model library file path |
| `SpiceLine` | Additional SPICE parameter string |
| `SpiceLine2` | Additional secondary SPICE parameter string |
| `Description` | Human-readable description |

---

## 5) Simulation and library control inside `.asc` via `TEXT` directives

In `.asc`, simulation and library commands are usually encoded as:

`TEXT <x> <y> <justification> <font_size> !<dot-command ...>`

Examples:
- `TEXT 120 344 Left 2 !.tran 10m`
- `TEXT 120 376 Left 2 !.include opamp.lib`
- `TEXT 120 408 Left 2 !.lib vendor_models.lib`

### 5.1 Complete dot-command keyword set (from LTspice help index)

| Dot keyword | Meaning |
|---|---|
| `.AC` | Small-signal AC analysis |
| `.BACKANNO` | Annotate subcircuit pin names on port currents |
| `.DC` | DC source sweep analysis |
| `.END` | End of netlist |
| `.ENDS` | End of subcircuit definition |
| `.FOUR` | Fourier analysis output |
| `.FUNC` | User-defined function |
| `.FERRET` | URL/file retrieval helper |
| `.GLOBAL` | Declare global nodes |
| `.IC` | Initial conditions |
| `.INCLUDE` (also `.INC`) | Include external file into netlist |
| `.LIB` | Include library definitions |
| `.LOADBIAS` | Load saved DC bias point |
| `.MACHINE` | State machine directive |
| `.MEASURE` | Measurement/evaluation command |
| `.MODEL` | Device model definition |
| `.NET` | Network parameter computation (in `.AC`) |
| `.NODESET` | Initial solution hints |
| `.NOISE` | Noise analysis |
| `.OP` | DC operating point |
| `.OPTIONS` | Solver/simulation options |
| `.PARAM` | User parameters |
| `.SAVE` | Limit/select saved waveforms |
| `.SAVEBIAS` | Save DC operating point |
| `.STEP` | Parameter/source/temp sweeps |
| `.SUBCKT` | Subcircuit definition |
| `.TEMP` | Temperature sweep/setup |
| `.TEXT` | User-defined strings |
| `.TF` | DC small-signal transfer function |
| `.TRAN` | Transient analysis |
| `.WAVE` | Write selected nodes to `.wav` |

### 5.2 Analysis directives (the six core simulation modes)

| Directive | Core parameters |
|---|---|
| `.tran` | `<Tstep> <Tstop> [Tstart [dTmax]] [modifiers]` |
| `.ac` | `<oct|dec|lin> <Nsteps> <StartFreq> <EndFreq>` |
| `.dc` | `<src> <start> <stop> <inc> [2nd source sweep...]` |
| `.noise` | `V(<out>[,<ref>]) <src> <oct|dec|lin> <Nsteps> <StartFreq> <EndFreq>` |
| `.tf` | `V(<node>[,<ref>]) <source>` or `I(<vsource>) <source>` |
| `.op` | no positional parameters |

---

## 6) Minimal generation templates

### 6.1 Minimal `.asc` skeleton

```text
Version 4.1
SHEET 1 880 680
WIRE 224 96 128 96
FLAG 224 304 0
SYMBOL res 208 80 R0
SYMATTR InstName R1
SYMATTR Value 1k
TEXT 120 344 Left 2 !.tran 10m
```

### 6.2 Minimal `.asy` skeleton

```text
Version 4.1
SymbolType CELL
LINE Normal 0 0 32 0
WINDOW 0 36 40 Left 2
SYMATTR Prefix R
PIN 0 0 LEFT 0
PINATTR PinName A
PINATTR SpiceOrder 1
PIN 32 0 RIGHT 0
PINATTR PinName B
PINATTR SpiceOrder 2
```

---

## Sources

1. KiCad developer docs: LTspice importer format (`.asc` and `.asy` keywords, parameter semantics, enums, SYMATTR usage)
   - https://dev-docs.kicad.org/en/import-formats/ltspice/index.html
2. LTspice help (dot-command index)
   - https://ltwiki.org/files/LTspiceHelp.chm/html/DotCommands.htm
3. LTspice help: `.INCLUDE`
   - https://ltwiki.org/files/LTspiceHelp.chm/html/DotInclude.htm
4. LTspice help: `.LIB`
   - https://ltwiki.org/files/LTspiceHelp.chm/html/DotLib.htm
5. LTspice help: simulation command syntax (`.tran`, `.ac`, `.dc`, `.noise`, `.tf`, `.op`)
   - https://ltwiki.org/index.php?title=Simulation_Command
6. Real `.asy` example confirming `Version`/`SymbolType` and keyword style
   - https://ltwiki.org/images/2/2c/Res.asy
7. Community confirmation that LTspice `.asc/.asy` format is not officially published
   - https://groups.io/g/LTspice/topic/asc_file_format/50232429
   - https://groups.io/g/LTspice/topic/where_can_i_find_syntax/50218198
