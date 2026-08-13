# LTspice Netlist → KiCad Schematic: Library Research & Ranking

Research date: 2026-08-12

Goal: find the best library among five candidates for converting LTspice
netlists (`.net`/`.cir`) into KiCad schematics (`.kicad_sch`).

## Headline finding

**None of the five candidates converts LTspice netlists to KiCad schematics.**
Verified by exhaustive grep across every repo (only match in any repo:
`kicad-tools/ROADMAP.md`, a *planned* SPICE **export** feature). All "netlist"
code in all five projects runs in the reverse direction (KiCad schematic →
netlist) or is read-only analysis. The ranking below is therefore by
**suitability as a foundation** for the KiCad-writing half of such a converter.

## Candidates (all LTspice conversion score: 0/10 out of the box)

### 1. kicad-tools — foundation score 3/10 (best pure-Python foundation)

- **What it is:** v0.20.0 (Beta), MIT, PyPI-published. Pure-Python S-expression
  toolkit for KiCad 8+ `.kicad_sch`/`.kicad_pcb` files, no running KiCad needed.
- **Schematic writing:** full `Schematic` model, symbol registry, symbol
  generator, wire/junction/PWR_FLAG handling (`src/kicad_tools/schematic/`).
  Proven on many real boards (boards/ fixtures, ERC/DRC/LVS end-to-end).
- **Netlist:** KiCad formats only (`.kicad_net`, `.kicad_xml` via kicad-cli).
  No SPICE parsing, no netlist→schematic tool. `Schematic` generation is
  Python-code-driven, not netlist-driven.
- **Testing:** 300+ test files; zero SPICE/LTspice tests.
- **Gaps for this task:** must build LTspice parsing + device→symbol mapping
  layer. No kicad-cli or KiCad runtime dependency (advantage).

### 2. KiCAD-MCP-Server — foundation score 3/10 (production-grade authoring backend)

- **What it is:** v2.6.0, MIT, 146 MCP tools, active (700+ commits 2026), TypeScript
  MCP layer + Python KiCad layer (`kicad_interface.py`, `commands/`).
- **Closest building blocks:** `create_schematic` (KiCad-10 template),
  `batch_add_and_connect` (places symbols + connects pins **by net name** from
  JSON — the nearest thing to netlist-driven layout), `connect_to_net`,
  dynamic symbol loader (~10k symbols), canonical `.kicad_sch` serializer,
  Eagle `.sch`→KiCad importer (proves foreign-format conversion machinery),
  ERC/SVG/netlist verification via kicad-cli.
- **Testing:** ~1,588 Python + 63 TS tests, real-KiCad 8/9/10 CI integration.
- **Gaps:** no SPICE parsing at all; requires KiCad 9+ (`pcbnew` SWIG or IPC)
  and `kicad-cli`; dual TS+Python stack.

### 3. SchGen (Microsoft) — foundation score 2/10 (reusable writer library, research-grade)

- **What it is:** ML-based schematic generation (natural language → KiCad
  schematic via LLM-emitted Python code). Single init commit, no tests,
  hardcoded personal paths, needs KiCad 8 + torch/CUDA. MIT (vendored
  `kiutils/` is GPL-3.0; `my_skip_lib/` is a modified kicad-skip).
- **Reusable asset:** `modules/kicad_sch_interface.py` — 1,584-line programmatic
  schematic-building API with auto wire routing, pin location queries,
  footprint matching, based on vendored kicad-skip.
- **Gaps:** no SPICE input of any kind; netlist handling is KiCad→netlist
  evaluation only. Research code, not a library.

### 4. KiCad-AI-Assistant (kcaa) — foundation score 2/10 (solid edit primitives, wrong paradigm)

- **What it is:** v0.1.9, MIT, KiCad 10 action plugin + MCP server driving an
  LLM chat panel inside KiCad. Schematic I/O via `kicad-skip` with atomic
  writes/.bak backups; netlist code is extraction-only.
- **Gaps:** creation is minimal boilerplate (empty child sheets, single-symbol
  insertion); full functionality assumes a running KiCad GUI (IPC) + LLM
  agent loop. Not a deterministic conversion pipeline.

### 5. kicad-mcp — foundation score 1/10 (read-only analyzer)

- **What it is:** v0.1.0, MIT, read-only MCP analysis server (~20 tools) for
  inspecting existing KiCad projects via kicad-cli; regex-based schematic
  reader (`netlist_parser.py`), no sexpr serializer, no writer.
- **Notable:** its own netlist builder `_build_netlist()` is an explicit TODO
  stub. Unused `COMMON_LIBRARIES`/`CIRCUIT_DEFAULTS` scaffolding in config.py.
- **Gaps:** nothing reads `.net`/`.cir`; nothing writes `.kicad_sch`; only
  2 test files.

## Ranked summary

| Rank | Project | LTspice parse | Netlist→sch | Sch writer | Requires KiCad | Foundation score |
|---|---|---|---|---|---|---|
| 1 | kicad-tools | No | No | Yes, pure-Python, proven | No | 3/10 |
| 2 | KiCAD-MCP-Server | No | No | Yes, batch net-name authoring | Yes (9+) | 3/10 |
| 3 | SchGen | No | No | Yes, kicad_sch_interface | Yes (8) | 2/10 |
| 4 | KiCad-AI-Assistant | No | No | Partial (edit primitives) | Yes (GUI) | 2/10 |
| 5 | kicad-mcp | No | No | No | Yes (cli) | 1/10 |

## Recommendation

The LTspice side of the conversion must be built in every case. This
repository (`electronics_design`) already owns the LTspice half (`.net`
parsing, validation, connectivity, orthogonal routing). Pair it with:

- **kicad-tools** — if a self-contained pure-Python pipeline is desired (no
  KiCad runtime); strongest engineering and testing.
- **KiCAD-MCP-Server** — if headless KiCad 9+ is acceptable; its
  `batch_add_and_connect` net-name-driven authoring and Eagle importer are the
  closest existing machinery.

Use the KiCad s-expression specs in `kicad_docs/sexpr-*.md` (already in this
repo) for the `.kicad_sch` writing half. Device→KiCad-symbol mapping and
placement work is new in all cases.
