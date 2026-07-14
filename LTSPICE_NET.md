# LTspice `.net` Netlist File Format (Deep Technical Reference)

Generated: 2026-06-23 (America/Vancouver)

## 1) What a LTspice `.net` file is

A LTspice `.net` file is a SPICE netlist text file consumed by the LTspice simulator. In LTspice, `.net`, `.cir`, and `.sp` are all accepted as simulation netlists.

Important distinction:
- LTspice **simulation netlist** (`.net/.cir/.sp`) is for SPICE simulation.
- LTspice **Tools > Export Netlist** creates **PCB/layout exchange netlists** (ExpressPCB, Allegro, etc.), not simulation decks.

## 2) Lifecycle and where `.net` comes from

- In schematic workflow (`.asc`), LTspice flattens schematic hierarchy and generates a simulation netlist at run/update time.
- The simulator executes that flat textual deck.
- You can also hand-author or externally generate `.net/.cir/.sp` and run directly.

## 3) Parsing model: core grammar rules

## 3.1 File framing

- First line is ignored (treated as title/comment).
- `.END` usually terminates the deck; it can be omitted, but anything after `.END` is ignored.
- Order of statements (except local scoping constructs) is mostly declarative.

## 3.2 Line-classification rule

The **first non-blank character** determines line type.

Valid leading classes (current LTspice help, 2025 era):
- `*` : whole-line comment
- `+` : continuation of previous line
- `.` : dot directive
- Device prefixes: `A B C D E F G H I J K L M O Q R S T U V W X Z`
- FRA-related device prefixes: `@` (FRA analyzer), `&` (FRA probe)

## 3.3 Whitespace and case

- Leading spaces/tabs are ignored.
- Keywords are case-insensitive.

## 3.4 Continuation lines

- A line beginning with `+` appends to the previous logical line.
- The `+` itself is stripped.

## 3.5 Comments

- Whole-line comment: first nonblank char `*`.
- Inline comment: `;` begins comment from that point onward.
- In practice, generated or hand-edited decks sometimes also use a leading `;` as a whole-line comment. The local `electronics_design` validator accepts that form.

## 3.6 Encodings

Current LTspice help documents support for:
- UTF-16 LE (with/without BOM)
- UTF-8 (with/without BOM) — preferred
- Latin-1 fallback in specific invalid-UTF8 cases

Older LTspice docs reference ASCII/Unicode generally; modern behavior is broader and explicit.

## 4) Numeric literal rules (critical validity details)

## 4.1 Accepted numeric styles

- Scientific notation: `1e-3`
- Engineering suffixes: `T G Meg K mil m u/μ n p f`
- Compact notation: e.g., `6K34` meaning `6.34K`

## 4.2 Dangerous SPICE legacy behavior

Unrecognized letters after a number are often ignored unless strict mode is enabled.
Example pitfall:
- `4Farads` may be interpreted as `4f` (4 femto)

Mitigation:
- `.options reject_number_tails` (modern LTspice) to make such tails a syntax error.

## 4.3 Mega vs milli trap

- In SPICE tradition, `M` means milli (`1e-3`), not mega.
- Use `Meg` for mega (`1e6`).

## 5) Node naming and ground validity

- Ground node is `0` (and `GND` is treated specially).
- Node names are strings; `0` and `00` are different nodes.
- Node names can be parameterized/dynamic in modern LTspice using expressions in braces in some contexts.

## 6) “What is valid vs invalid” in `.net`

## 6.1 Structurally valid

- One or more element/directive lines following the first (ignored) title line
- Exactly one simulation analysis directive per run context (see Section 9)
- Properly paired `.SUBCKT ...` and `.ENDS`
- Legal element instance syntax for each leading prefix

## 6.2 Structurally invalid (common)

- Unknown first nonblank leading character (not in valid leading classes)
- Device line with wrong pin count/order for that device class
- Missing model name where required (`D`, `Q`, `J`, `M`, `S`, `W`, `O`, `U`, `Z`, etc.)
- Unmatched `.SUBCKT/.ENDS`
- Referencing undefined subcircuit on `X...` invocation
- Malformed parameter expression or unresolved parameter dependency cycle

## 6.3 Numerically invalid / semantically broken

- Physically impossible or out-of-range parameters (e.g., illegal coupling coefficient out of range for `K`)
- Values that parse but are unintended due to suffix mistakes (`1M` issue)
- Broken file paths/URLs in `.include`/`.lib`

## 6.4 Topology-invalid (netlist parses but simulation fails)

- Floating nodes, singular matrix conditions, inconsistent source loops
- Invalid transformer topology, etc. (can be checked by `topologycheck` option)

## 7) Complete keyword surface: line-leading keywords

For simulation `.net` decks, the primary lexical keywords are these line starters:

- `*` comment
- `+` continuation
- `.` directives
- `A` special function devices
- `B` behavioral source
- `C` capacitor
- `D` diode
- `E` VCVS
- `F` CCCS
- `G` VCCS
- `H` CCVS
- `I` independent current source
- `J` JFET
- `K` mutual inductance
- `L` inductor
- `M` MOSFET
- `O` lossy transmission line
- `Q` BJT
- `R` resistor
- `S` voltage-controlled switch
- `T` lossless transmission line
- `U` uniform RC line
- `V` independent voltage source
- `W` current-controlled switch
- `X` subcircuit instance
- `Z` MESFET/IGBT
- `@` frequency response analyzer device (new LTspice FRA flow)
- `&` frequency response probe device (new LTspice FRA flow)

## 8) Complete dot-directive keyword set (modern list)

Current LTspice help (2025-era online manual) lists:

- `.AC`
- `.BACKANNO`
- `.DC`
- `.END`
- `.ENDS`
- `.FOUR`
- `.FRA`
- `.FUNC`
- `.GLOBAL`
- `.IC`
- `.INCLUDE`
- `.KEEPNODE`
- `.LIB`
- `.LOADBIAS`
- `.LOADSTATE`
- `.MACHINE`
- `.MEASURE`
- `.MODEL`
- `.NET`
- `.NODESET`
- `.NOISE`
- `.OP`
- `.OPTIONS`
- `.PARAM`
- `.SAVE`
- `.SAVEBIAS`
- `.SAVESTATE`
- `.STEP`
- `.SUBCKT`
- `.TEMP`
- `.TF`
- `.TRAN`
- `.WAVE`

Legacy LTspice XVII help also documented directives like `.TEXT` and `.FERRET`; these are not listed in the modern official command index.

## 9) Analysis directives and run-mode validity

Modern LTspice help states there are seven primary analysis modes:
- `.AC`
- `.DC`
- `.NOISE`
- `.OP`
- `.TF`
- `.TRAN`
- `.FRA`

Typical rule: for a given run, specify one analysis mode command.

## 10) Canonical syntax snippets for major directives

- `.tran <Tstep> <Tstop> [Tstart [dTmax]] [modifiers]`
- `.ac <oct|dec|lin> <Nsteps> <StartFreq> <EndFreq>`
- `.ac list <f1> [f2 ...]`
- `.ac file=<filename>`
- `.dc <sweep1> [<sweep2> [<sweep3>]]`
- `.noise V(<out>[,<ref>]) <src> <oct|dec|lin> <Nsteps> <StartFreq> <EndFreq>`
- `.noise ... list ...` / `.noise ... file=...`
- `.tf V(<node>[,<ref>]) <source>` or `.tf I(<vsource>) <source>`
- `.op`
- `.fra [Tstart=...] [dTmax=...] [Tstep=...] [Tstop=...] [uic] [startup]`
- `.net [V(out[,ref])|I(Rout)] <Vin|Iin> [Rin=<val>] [Rout=<val>]`
- `.subckt <name> <pins...> [params...]`
- `.ends [name]`
- `.param <name>=<expr> ...`
- `.func <name>(args) {expr}` (modern LTspice also relaxes braces in many contexts)
- `.model <modname> <type>(<params...>)`
- `.step ...` supports linear/log stepping, `list`, and `file=` forms
- `.save ...` supports wildcard patterns
- `.lib <filename>` and `.lib <filename> <entryname>` sectional form
- `.include <filename>`
- `.options <k=v ...>` and flag options
- `.ic [V(node)=...] [I(Lx)=...]`
- `.nodeset V(node)=...`

## 11) `.TRAN` modifier keywords (valid)

- `uic`
- `steady`
- `nodiscard`
- `startup`
- `step`

## 12) Device keyword/syntax inventory (instance prefixes)

## 12.1 Passive/standard linear

- `Rxxx n1 n2 <value> [tc=...] [temp=...]`
- `Cxxx n1 n2 <cap> [ic=...] [Rser=...] [Lser=...] [Rpar=...] [Cpar=...] [m=...] [RLshunt=...] [temp=...]`
- `Lxxx n+ n- <L> [ic=...] [Rser=...] [Rpar=...] [Cpar=...] [m=...] [temp=...]`
- `Kxxx L1 L2 [L3 ...] <coupling_coeff>`
- `Txxx L+ L- R+ R- Zo=<value> Td=<value>`
- `Oxxx L+ L- R+ R- <LTRA_model>`
- `Uxxx N1 N2 Ncom <URC_model> L=<len> [N=<lumps>]`

## 12.2 Independent sources

- `Vxxx n+ n- <dc_or_waveform> [AC=...] [Rser=...] [Cpar=...]`
- `Ixxx n+ n- <dc_or_waveform> [AC=...] [load]`

Waveform keywords commonly valid in source value field:
- `PULSE(...)`
- `SINE(...)`
- `EXP(...)`
- `SFFM(...)`
- `PWL(...)`
- `wavefile=<filename> [chan=<n>]`
- Additional source forms include tables and step-load forms for current sources in LTspice docs.

## 12.3 Controlled/dependent and behavioral

- `Exxx ...` VCVS (gain / table / Laplace / value expression / POLY)
- `Fxxx ...` CCCS (gain / expression / POLY)
- `Gxxx ...` VCCS (gain / table / Laplace / value expression / POLY)
- `Hxxx ...` CCVS (gain / expression / POLY)
- `Bxxx ...` arbitrary behavioral source (`V=` or `I=` with expression, Laplace options)

## 12.4 Semiconductor/model-required devices

- `Dxxx anode cathode <model> ...`
- `Qxxx C B E [S] <model> ...`
- `Jxxx D G S <model> ...`
- `Mxxx D G S B <model> ...` (and VDMOS form)
- `Sxxx ... <SW_model> ...`
- `Wxxx ... <CSW_model> ...`
- `Zxxx ... <NMF/PMF/NIGBT/PIGBT-context model> ...`

## 12.5 Hierarchy/device abstraction

- `Xxxx nodes... <subckt_name> [param=expr ...]`
- `Axxx ... <model> [params...]` special-function devices (partly undocumented and version-sensitive)

## 12.6 FRA-specific new device classes

- `@xxx ...` FRA analyzer device
- `&xxx ...` FRA probe device

## 13) `.MODEL` model-type keywords

Core model type keywords include:
- `SW`, `CSW`, `URC`, `LTRA`, `D`, `NPN`, `PNP`, `NJF`, `PJF`, `NMOS`, `PMOS`, `NMF`, `PMF`, `NIGBT`, `PIGBT`, `VDMOS`

Model parameter sets are type-specific and extensive.

## 14) Expression language keywords and operators

Used in `.param`, behavioral sources, and expression-valued parameters.

Highlights:
- Constants (e.g., `PI`, `BOLTZ`, etc.; some defaults are redefinable)
- Functions: arithmetic, trig, random, table lookup, selection, logic helpers
- Boolean/logical operators and arithmetic operators
- String support in modern LTspice `.param` (not only numeric), including `select(...)` patterns for model/subckt name parameterization

Version note:
- Modern LTspice (24.1+) relaxes mandatory braces/apostrophes for many substitutions, except where omission becomes ambiguous.

## 15) `.include` / `.lib` validity and path syntax

Valid:
- Relative or absolute file paths
- Quoted paths when spaces exist
- `.lib` sectional form: `.lib "file" <entryname>` with `.lib <entryname> ... .endl` in library

Risky/invalid patterns:
- Missing extension when file actually requires one
- Wrong search path assumptions
- Broken URL includes/libraries (if using URL forms)

Conversion portability note:
- A `.lib` reference identifies the simulation library; it does not necessarily identify the `.asy` symbol used to draw an `X...` instance.
- A subcircuit name and its symbol filename may differ. For example, `level2` can be defined inside `UniversalOpAmp2.lib` while the matching symbol is `UniversalOpAmp2.asy`.
- If a netlist will be converted back to an `.asc`, preserve LTspice's `ModelFile` comment hint or provide an equivalent symbol mapping through the conversion settings. Do not assume that the `.subckt` name is an `.asy` basename.

## 16) Scoping and expansion semantics

- `.subckt/.ends` defines local scope.
- `.param` and `.func` can be scoped within subcircuits.
- LTspice expands hierarchy to flat netlist before simulation.
- Subcircuit instances get unique expanded instance names.

## 17) Validity checklist for robust `.net` authoring

1. Ensure one valid analysis directive (`.tran` / `.ac` / `.dc` / `.noise` / `.op` / `.tf` / `.fra`).
2. Ensure all model-requiring instances reference an existing `.model` or included model.
3. Ensure all `X...` calls map to defined `.subckt` names.
4. Ensure no unknown line-leading characters.
5. Ensure continuation lines begin with `+` in column after optional whitespace.
6. Validate numeric suffixes (`Meg` vs `M`, tail text).
7. Use `.options reject_number_tails` for strict numeric parsing.
8. Verify ground/reference node strategy (`0` / `GND`) and avoid floating islands.
9. Validate file paths for `.include/.lib/.wavefile`.
10. If using modern-only features (`@`, `&`, `.fra`, relaxed substitution), verify target LTspice version.

## 17.1 `electronics_design` package validation profile

The Python package in this repository intentionally implements a **stricter project-level validation profile** than raw LTspice parsing in a few places. This is deliberate so the API can catch formatting mistakes early and return stable error messages.

### `is_valid_ltspice_netlist_format(filepath)`

This validator checks:

- file exists
- file is readable
- each nonblank line starts with a valid LTspice line class
- continuation lines only appear after a prior logical line
- dot directives must have a whitespace boundary after the directive name
- device lines must have at least the minimum positional token count for their prefix
- project-specific spacing mistakes such as `R1Vcc ...`, `V1Vcc ...`, `.stepPARAM ...`, and `.libC:\...` are rejected

Important implementation nuance:

- For this project, `Q` lines are treated strictly as needing collector, base, emitter, substrate, and model tokens in order to catch merged-node spacing mistakes such as `Q1 N001N002 0 0 2N3904`.
- `V` and `I` lines allow the source value to be omitted because LTspice sample decks can use those sources as sweep variables, e.g. `V1 N001 0`.

Public API return contract:

- `False, "File not found!"`
- `False, "No permission to read file!"`
- `False, "Line format/spacing is invalid! Line <n>"`
- `True, ""`

### `is_valid_ltspice_netlist_footer(filepath)`

This validator is not a generic LTspice theorem prover. It enforces the footer convention used in this repository and test suite.

It requires:

- the file must already pass the format validator
- at least one simulation analysis directive somewhere in the deck
- final nonblank line must be `.end`
- penultimate nonblank line must be `.backanno`

So, a syntactically parseable LTspice deck can still fail this validator if it omits an analysis command or does not end with the repository-style footer.

Public API return contract:

- `False, "File not found!"`
- `False, "No permission to read file!"`
- `False, "Footer information is invalid! Line <n>"`
- `True, ""`

### `is_ltspice_netlist_structure_connected(filepath)`

This validator performs a lightweight structural connectivity check, not a full simulator topology solve.

It counts element-port references and requires each non-exempt node to appear on at least two device ports.

Nodes treated as exempt:

- `0`
- `GND`
- names beginning with `NC`, `NC_`, or `NC-`

Important limitations:

- This is a graph-style connection count, not a full singular-matrix or operating-point analysis.
- `K` mutual inductance statements do not contribute nodes because they reference inductors, not electrical nets.
- Subcircuit `X...` lines contribute all positional tokens before the subcircuit name and before any `param=value` tokens.

Public API return contract:

- `False, "File not found!"`
- `False, "No permission to read file!"`
- `False, "Node is not connected correctly! Line <n>"`
- `True, ""`

### Netlist-to-ASC symbol mapping advice

`ltspice_netlist_to_asc()` uses the public symbol-initial, autoplace, and wiring stages. The netlist must therefore carry enough information to resolve every device to an available `.asy` file.

For ordinary primitives, the mapping is usually direct:

```spice
R1 in out 1k       ; res.asy
C1 out 0 100n      ; cap.asy
```

For `X...` subcircuits, keep the simulation subcircuit name unchanged and preserve the LTspice-generated `ModelFile` hint when the symbol filename differs:

```spice
XU1 in out VCC VEE out level2 Avol=1Meg
* Library below included based on ModelFile attribute of instance XU1 (C:\users\user\AppData\Local\LTspice\lib\sym\OpAmps\UniversalOpAmp2.asy)
.lib C:\users\user\AppData\Local\LTspice\lib\sub\UniversalOpAmp2.lib
```

The comment is metadata for schematic reconstruction; it does not alter SPICE simulation. The converter extracts the `.asy` basename from the hint and searches the configured `custom_search_paths`, Wine path, and Windows path. The path in the hint may remain Windows-style, but the actual symbol must exist in one of the configured search roots.

Before conversion, check:

1. Every `X...` instance has either a matching `.asy` basename or a `ModelFile` hint.
2. The hinted `.asy` file exists in a configured search root.
3. The `.lib` file contains the referenced `.subckt` name and remains available for simulation.
4. Run `ltspice_netlist_to_symbol_initial()` first and inspect that each `SYMBOL` value names the intended `.asy` file before invoking autoplace.

If symbol geometry cannot be resolved, the current autoplace API reports the generic `AUTOPLACE_FAILED`; inspect the generated symbol-initial JSON to distinguish a missing file from a placement or routing failure.

## 18) Concrete valid vs invalid examples

## 18.1 Voltages valid

VALID V2 voltage of 12V DC from Vcc to ground 0
```spice
V2 Vcc 0 12
```

VALID V1 voltage with a 4V DC and 2V AC from Node IN to ground 0
```spice
V1 IN 0 4 AC 2
```

## 18.2 Voltages invalid

INVALID, Missing DC voltages
```spice
V1 IN 0 AC 1
```

## 18.3 Valid minimal transient deck

```spice
* RC step
V1 in 0 PULSE(0 1 0 1n 1n 1u 2u)
R1 in out 1k
C1 out 0 100n
.tran 0 10u
.end
```

## 18.4 Invalid: unknown leading keyword

```spice
Y1 a b 1k
```

`Y` is not a valid standard LTspice device prefix.

## 18.5 Invalid intent due to suffix trap

```spice
R1 a b 1M
```

Parses as 1 milliohm in SPICE semantics, not 1 megaohm.

## 18.6 Invalid hierarchy reference

```spice
X1 a b c MissingSubckt
.tran 1m
.end
```

Fails if `MissingSubckt` is never defined/included.

## 18.7 Potentially valid syntax but semantically bad

```spice
C1 a b 4Farads
```

May parse to `4f` unexpectedly unless strict number-tail rejection is enabled.

## 19) Version differences you must account for

- LTspice XVII-era docs and LTspice 24/26 docs are not identical.
- Newer docs add FRA flow (`.fra`, `@`, `&`), state save/load directives, modern parser details.
- Some older-documented directives (e.g., `.text`, `.ferret`) are absent from current official dot-command index.
- String/quote handling and parameter substitution behavior changed in newer versions (notably 24.1+).
- Repository tooling may be stricter than LTspice itself; treat this document's Section 17.1 as the authoritative description of the local Python API behavior.

## 20) Practical answer to “all possible keywords”

For simulation `.net`, “all possible keywords” is best interpreted in layers:

1. Lexical line starters (`* + . A..Z @ &`) — finite and listed above.
2. Dot directives (current full list above).
3. Device-instance parameter keywords (very large, device-specific, version-evolving).
4. Model-parameter keywords (`.model` type dependent; extremely large).
5. Expression language functions/operators and reserved names.

So: the format is not a single tiny grammar; it is a compact top-level grammar plus many device/model subgrammars.

---

## Sources

Primary references used:

1. LTspice Help (current online manual), General Structure and Conventions
- https://ltspicehelpmanual.azurewebsites.net/GeneralStructureandConventions.htm

2. LTspice Help, Dot Commands (current list)
- https://ltspicehelpmanual.azurewebsites.net/dotcommands.htm

3. LTspice Help, Circuit Elements (current quick syntax + flags/dynamic nodes)
- https://ltspicehelpmanual.azurewebsites.net/circuitelements.htm

4. LTspice Help, `.AC`
- https://ltspicehelpmanual.azurewebsites.net/ac--performansmallsignalacanalys.htm

5. LTspice Help, `.DC`
- https://ltspicehelpmanual.azurewebsites.net/dc--performadcsourcesweepanalysi.htm?agt=index

6. LTspice Help, `.NOISE`
- https://ltspicehelpmanual.azurewebsites.net/noise--performanoiseanalysis.htm?agt=index

7. LTspice Help, `.TF`
- https://ltspicehelpmanual.azurewebsites.net/tf--findthedcsmall-signaltransfe.htm

8. LTspice Help, `.TRAN` and modifiers
- https://ltspicehelpmanual.azurewebsites.net/TRAN--DoaNonlinearTransientAnaly.htm
- https://ltspicehelpmanual.azurewebsites.net/transientanalysisoptions.htm

9. LTspice Help, `.NET`
- https://ltspicehelpmanual.azurewebsites.net/net--computenetworkparametersina.htm

10. LTspice Help, `.PARAM`
- https://ltspicehelpmanual.azurewebsites.net/PARAM--User-DefinedParameters.htm

11. LTspice Help, `.OPTIONS`
- https://ltspicehelpmanual.azurewebsites.net/options--setsimulatoroptions.htm

12. LTspice Help, `.LIB`
- https://ltspicehelpmanual.azurewebsites.net/LIB--IncludeaLibrary.htm

13. LTspice Help, `.SAVE`
- https://ltspicehelpmanual.azurewebsites.net/save--limitthequantityofsaveddat.htm

14. LTspice Help, `.STEP`
- https://ltspicehelpmanual.azurewebsites.net/STEP--ParameterSweeps.htm

15. LTspice Help, `.FRA` and FRA devices `@` / `&`
- https://ltspicehelpmanual.azurewebsites.net/dotfra.html
- https://ltspicehelpmanual.azurewebsites.net/fra_device.html
- https://ltspicehelpmanual.azurewebsites.net/fra_probe.html

16. LTspice Help, SPICE Netlist / PCB Netlist Extraction
- https://ltspicehelpmanual.azurewebsites.net/spicenetlist.htm
- https://ltspicehelpmanual.azurewebsites.net/pcbnetlistextraction.htm

17. LTspice EngineerZone clarification (LTspice 26 netlist syntax and export-netlist confusion)
- https://ez.analog.com/design-tools-and-calculators/ltspice/f/q-a/603860/ltspice-netlist-syntax

18. LTspice XVII legacy help mirror (cross-check of historical syntax and directives)
- https://ltwiki.org/files/LTspiceHelp.chm/html/GeneralConventions.htm
- https://ltwiki.org/files/LTspiceHelp.chm/html/DotCommands.htm
- https://ltwiki.org/files/LTspiceHelp.chm/html/CircuitElementQuickReference.htm
- https://ltwiki.org/files/LTspiceHelp.chm/html/DotModel.htm
- https://ltwiki.org/files/LTspiceHelp.chm/html/V-device.htm
- https://ltwiki.org/files/LTspiceHelp.chm/html/I-device.htm
- https://ltwiki.org/files/LTspiceHelp.chm/html/ExternalNetlists.htm
