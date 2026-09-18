# Improvement Proposals for `electronics_design`

These proposals come from a real end-to-end exercise: designing an 80 V AC →
+17.3 V/4 A and −3.7 V/3 A power supply with LTspice 24 library parts
(`LT4320-1`, `LTC3895`, `LTC3896`), simulating it through `bltspice_mcp`, and
converting the netlist to `.asc`, `.kicad_sch`, and `.kicad_pcb`. Each item
below is specific to this repository, includes the observed failure, and
proposes a concrete change. Priorities: **P1** = correctness/blocking,
**P2** = robustness/usability, **P3** = polish.

---

## 1. (P1) Map X-device nodes by `SpiceOrder` in `ltspice_netlist_to_kicad_sch`

**Problem.** Modern LTspice `.sub` models expose more pins than the matching
`.asy` symbol: `LTC3895.sub`/`LTC3896.sub` are 39-pin subcircuits while
`LTC3895.asy`/`LTC3896.asy` only define 28 pins with sparse `SpiceOrder`
values (1–8, 10, 11, 13, 14, 17, 18, 19, 20, 21, 22, 24, 26, 28, 30, 32, 34,
36, 37, 38, 39). A correct LTspice deck therefore has 39 nodes on the `X`
line, but `ltspice_netlist_to_kicad_sch` rejects it:

```
UNKNOWN_SYMBOL: Unable to resolve a KiCad symbol for device 'XU2' in
kicad_path candidates ['LTC3895'] or the configured LTspice ASY search paths
```

The blocker is `_symbol_pin_count_matches()` (requires
`pin_count == len(element.nodes)`) and `_extra_no_connect_pins_match()`
(only handles *extra symbol pins*, never *extra deck nodes*). The same deck
converts fine with `ltspice_netlist_to_asc`, whose wiring stage already
indexes pins with `node_index = pin.spice_order - 1`
(`ltspice_netlist_to_wiring.py`, `_collect_*` pin loop).

**Proposal.**

- In `_resolve_symbol`, when an `.asy`/KiCad symbol resolves but
  `pin_count < len(element.nodes)`, accept it when the symbol's `SpiceOrder`
  values are all within range **and** every deck node not addressed by a
  `SpiceOrder` is unconnected (appears only on this `X` line) or matches the
  `NC*` convention.
- In `_build_pin_map`, map node index `spice_order - 1` instead of relying on
  the position of the symbol's sorted pin numbers, so the KiCad netlist is
  correct even when the deck carries filler nodes.
- Add a `convert_settings` opt-out, e.g.
  `kicad_sch_allow_spice_order_gaps` (default `True`), so callers can force
  strict equality if they prefer.
- Alternative deeper fix: when generating the embedded `.kicad_sym` from an
  `.asy` whose `SpiceOrder` set is sparse, annotate the missing package pins
  as `no_connect` and number them by package pin, then reuse the existing
  `_extra_no_connect_pins_match()` path.

**Affected:** `src/electronics_design/ltspice_netlist_to_kicad_sch.py`
(`_symbol_pin_count_matches`, `_extra_no_connect_pins_match`,
`_build_pin_map`, `_resolve_symbol`).

---

## 2. (P1) Validate X-line node counts against `.asy` `SpiceOrder`

**Problem.** Out-of-range pin indices are silently ignored:

```python
node_index = pin.spice_order - 1
if node_index < 0 or node_index >= len(node_names):
    continue          # ltspice_netlist_to_wiring.py
```

A short `X` line drops pins without an error; a long `X` line ignores extra
nodes even when they carry real nets. Both cases produce a schematic/netlist
that looks valid but is electrically wrong.

**Proposal.** Add an explicit validation pass (in
`ltspice_netlist_to_symbol_initial` or `ltspice_resolve_symbol_pose`, where
the `.asy` pins are first resolved) that raises a dedicated error, e.g.
`X_PIN_COUNT_MISMATCH` with the line number, when:

1. any symbol pin's `spice_order - 1` is outside the `X` line's node list; or
2. any deck node beyond the symbol's `SpiceOrder` coverage is a real net
   (appears on another device or is not `NC*`).

Keep the current silent-skip only as a fallback behind an explicit setting.

**Affected:** `ltspice_netlist_to_symbol_initial.py`,
`ltspice_resolve_symbol_pose.py`, `ltspice_netlist_to_wiring.py`.

---

## 3. (P1) Make generated netlists ASCII-safe (micro sign) and configurable

**Problem.** `ltspice_asc_to_netlist` writes UTF-8:

```python
output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
```

and preserves the `µ` character from the `.asc` (`150µ`, `0.1µ`, …). LTspice 24
under Wine does **not** recognize UTF-8 `µ` (0xC2 0xB5): the value is silently
truncated to the bare number, so `470µ` becomes `470 F`. This made a working
bridge rectifier look like a short circuit and cost significant debugging time.
The `.asc` writer already uses Latin-1 (`_write_latin1_asc_file`), so the two
writers are inconsistent.

**Proposal.**

- Default `convert_settings["ltspice_micro_symbol"] = "u"` for
  `ltspice_asc_to_netlist` and `ltspice_netlist_to_asc`; allow `"µ"` (UTF-8)
  and `"latin-1"` for users who need exact round-trips.
- Write generated netlists in Latin-1 (like the `.asc` writer) when the micro
  symbol is `"µ"`, otherwise ASCII.
- Have `is_valid_ltspice_netlist_format` (or a new optional check) warn when a
  netlist contains non-ASCII bytes, naming the offending lines.

**Affected:** `ltspice_asc_to_netlist.py`, `ltspice_net.py`,
`ltspice_netlist_to_asc.py`; README (`Return Conventions`/encoding note).

---

## 4. (P1) Recursively resolve `.asy` files under `lib/sym`

**Problem.** `_find_asy_file` only checks three locations per root:

```
<root>/<name>.asy
<root>/sym/<name>.asy
<root>/lib/sym/<name>.asy
```

Real LTspice symbols live in subdirectories (`lib/sym/PowerProducts/LTC3895.asy`,
`lib/sym/SpecialFunctions/LT4320-1.asy`, `lib/sym/OpAmps/…`). Conversion failed
until the subdirectories were added manually to `custom_search_paths`.
`ltspice_asc_to_netlist` already builds a full `symbol_path_lookup`, so the
knowledge exists in the package but is not shared.

**Proposal.** Extract one library resolver used by every module:

- walk the configured roots once, cache `{lowercase stem → path}` for `.asy`
  files (bounded depth, ignore case), and
- let `_find_asy_file`, `ltspice_netlist_to_symbol_initial`, and
  `ltspice_asc_to_netlist` all consume it.

Keep `custom_search_paths` as the highest-priority root. This also removes
duplicated path logic and keeps AGENTS.md's "look pin data up via
`convert_settings`" rule intact.

**Affected:** new `ltspice_library.py` (or similar),
`ltspice_netlist_to_kicad_sch.py`, `ltspice_netlist_to_symbol_initial.py`,
`ltspice_asc_to_netlist.py`.

---

## 5. (P2) Actionable `UNKNOWN_SYMBOL` diagnostics

**Problem.** The current message names the candidate and the configured search
paths but not where the converter actually looked, nor the fix. The user has to
guess between "symbol name is wrong", "root is missing", and "symbol is in a
subdirectory".

**Proposal.** Extend the error payload with:

- every candidate `.asy` basename tried,
- every resolved root and the concrete paths attempted,
- a ready-to-paste `custom_search_paths` suggestion for the closest match
  (e.g., the directory that contains a file with the same stem),
- a note that LTspice symbols are commonly nested under `lib/sym/<category>/`.

**Affected:** `ltspice_netlist_to_kicad_sch.py` (`_resolve_symbol` error
returns).

---

## 6. (P2) Normalize LTspice `xN` value multipliers

**Problem.** `.asc` → `.net` conversion preserves LTspice's parallel-device
shorthand: `C1 OUT 0 150µ x3 Rser=0.1`. LTspice accepts it, but the token is
meaningless to the KiCad conversion, netlist comparison, and any downstream
consumer that parses values.

**Proposal.** In `_split_value_and_spiceline` / the value formatter, translate
a trailing `xN` token into the standard instance parameter `m=N`, or expand it
into `N` parallel devices when the consumer cannot represent `m`. Add a
validator rule for stray `xN` tokens. Document the behavior.

**Affected:** `ltspice_netlist_to_symbol_initial.py`,
`ltspice_asc_to_netlist.py`, `ltspice_net.py`.

---

## 7. (P2) Retry placement when wiring collides

**Problem.** Schematic generation aborted after ~500 s with:

```
WIRING_GENERATION_ERROR: power symbol '#PWR26' intersects a symbol body
```

The flow placement produced a layout whose power symbols could not be wired;
a second run with a larger page and more placement iterations succeeded
(130 s). A single deterministic layout is brittle for dense decks.

**Proposal.** Add a bounded retry ladder inside `ltspice_netlist_to_kicad_sch`:

1. retry with increased inter-symbol spacing / next paper size in the
   A4→A3→A2 ladder,
2. retry with `kicad_placement_seed` bumped (deterministically),
3. fall back to the `rows` strategy for the failing subgraph only.

Report the symbol, pin, and coordinates in the error if all retries fail.

**Affected:** `ltspice_netlist_to_kicad_sch.py` (wiring stage),
`flow_placement.py`.

---

## 8. (P2) Expose PCB routing effort and coverage in the result

**Problem.** `kicad_sch_to_kicad_pcb` returns `(True, "OK", 0)` even when many
pads are unrouted (observed: 47 unrouted pads at 600 s; 16 at 1800 s). The only
control is the boolean `kicad_pcb_require_complete_routing`; there is no way to
ask for more routing effort or to see coverage without reopening the board.

**Proposal.** Add validated settings:

```python
"kicad_pcb_routing_trials": 1,             # independent routing attempts
"kicad_pcb_trace_optimization_passes": 1,  # rip-up/retry passes
"kicad_pcb_min_routing_coverage": 0.0,     # 0.0–1.0; fail below this
"kicad_pcb_routing_report": "",            # optional JSON report path
```

and include coverage statistics in the success path (e.g., an out-parameter or
the report file) so callers can distinguish "fully routed" from "best effort".

**Affected:** `kicad_sch_to_kicad_pcb.py`; README settings table.

---

## 9. (P2) Progress reporting for long conversions

**Problem.** The two KiCad conversions ran 130 s and 617–1219 s with no
output; from the outside they look hung. There is no `logging` use in either
module and no progress callback.

**Proposal.** Add an optional `convert_settings["kicad_progress_callback"]`
(Python callable) and/or module `logging` loggers emitting phase transitions
(parse, place, route net *i/N*, text pass, validate) with per-phase timings.
Default to silent to preserve current behavior.

**Affected:** `ltspice_netlist_to_kicad_sch.py`,
`kicad_sch_to_kicad_pcb.py`, `schematic_grid_router.py`.

---

## 10. (P2) Portable library references in generated netlists

**Problem.** `ltspice_asc_to_netlist` emits absolute Windows `.lib` paths from
`convert_settings["ltspice_windows_path"]`, e.g.
`C:\users\brosnan\AppData\Local\LTspice\lib\cmp\standard.mos`. The same deck
cannot run under a different wine prefix (a container, another user), and the
`.lib` path is rewritten by hand when moving between host and container.

**Proposal.** Add `convert_settings["ltspice_library_reference_style"]`:

- `"absolute"` (current behavior),
- `"basename"` → `.lib standard.mos` / `.lib LTC3895.sub` (LTspice resolves
  these against its own `lib/cmp` and `lib/sub`),
- `"relative"` → path relative to the netlist's directory.

Also expose a helper `rewrite_ltspice_library_paths(netlist, style, settings)`
so existing decks can be made portable without regenerating them.

**Affected:** `ltspice_asc_to_netlist.py`, `ltspice_netlist_to_asc.py`,
`ltspice_net.py`.

---

## 11. (P3) Cache `.asy` → `.kicad_sym` conversions

**Problem.** Every conversion re-runs `ltspice_asy_to_kicad_symbol` for the
same embedded symbols (`LTC3895`, `LTC3896`, `LT4320-1`, `nmos`, `res`, `cap`,
…). In iterative work this is repeated work.

**Proposal.** Process-level cache keyed by
`(asy_path, mtime, generator/version/default-footprint settings)` storing the
generated symbol text; invalidate on settings change. Expose
`convert_settings["kicad_symbol_cache"] = True/False`.

**Affected:** `ltspice_netlist_to_kicad_sch.py`, `ltspice_asy_to_kicad_symbol.py`.

---

## 12. (P3) Public introspection for netlist/`.asy` pin compatibility

**Problem.** Determining that `LTC3895` needs a 39-node `X` line required
probing LTspice with 28/30/…/39-node decks. There is no public way to ask the
package what a symbol expects.

**Proposal.** Add small public helpers:

- `get_ltspice_asy_pins()` already exists; add
  `get_ltspice_asy_spice_orders(filepath) -> list[int]` and
  `get_ltspice_asy_pin_count(filepath) -> int`,
- `get_ltspice_netlist_device_pins(netlist_filepath, convert_settings)` that
  reports, per device, the symbol resolved, the `.asy` pin count, the deck node
  count, and whether the mapping is valid.

This turns the trial-and-error pin probing into a documented API and is a
natural companion to proposal 2.

**Affected:** `ltspice_asy.py`, new netlist introspection helper,
`__init__.py` exports, README.

---

## 13. (P3) Consistent handling of `PREFIX§NAME` device identifiers

**Problem.** Netlists produced by `ltspice_asc_to_netlist` use
`M§Q1`/`X§U1` style identifiers (the `§` separates primitive prefix from
reference), while hand-written decks use `M1`/`XU1`. Public functions
generally tolerate both, but the convention is undocumented and is easy to
trip over when round-tripping generated decks back through the converters.

**Proposal.** Centralize identifier parsing in one helper
(`split_device_identifier`), document the `§` convention in the README, and add
round-trip tests (`asc → net → asc`, `net → asc → net`) that include `§` names.

**Affected:** `ltspice_net.py`, `ltspice_netlist_to_symbol_initial.py`,
`ltspice_netlist_symbol_wire_to_asc.py`, README.

---

## 14. (P3) Test fixtures for LTspice 24 encrypted models

**Problem.** The issues above (39-pin `X` lines, nested `.asy` directories,
UTF-8 micro sign, `xN` multipliers) are all observable with the stock LTspice
24 `LTC3895`/`LTC3896`/`LT4320-1` parts, but the test suite has no fixtures
that exercise them end to end.

**Proposal.** Add small checked-in fixtures and integration tests:

- a 39-node `X` deck plus the 28-pin `.asy` and the derived 28-node deck,
- nested `.asy` layout under a fake `lib/sym/<Category>/` root,
- UTF-8 `µ` vs ASCII `u` netlists asserting the encoding option,
- `xN` value normalization,
- `ltspice_netlist_to_asc` / `ltspice_netlist_to_kicad_sch` success on all of
  the above, with round-trip netlist comparison.

**Affected:** `tests/`, `test_files/`, `valid_netlist/`.

## 15. PCB Wires and wiring bends must be greater than or equal to 120 degrees

**Problem.**  When autorouting PCBs, the minimum angle between two PCB wires can be less than 90 degrees
which is bad for signal integrity and aesthetics

**Proposal.** Only have  the minimum angle between two PCB wires be greather than or equal to 120 degrees, like wire bends of 120 , 140 , 180 degrees is fine but 90, 100, 110 degrees is banned

## 16. PCB must not be sparse and must not take up a lot of space

**Problem.**  When autorouting, PCBs components are far away for each other and makes the wires have more delay
and makes the PCB cost exponentially more money to manufacture.

**Proposal.** Should make the PCB as small as possible with all the footprints and wires and only have a minimum distance of 
footprints from each other to make the PCB more dense. must pass all pcb checks too

Components should not be faraway from each other.


---

## Suggested order

1. Proposal 1 + 2 (unblocks real LTspice 24 decks; highest user impact).
2. Proposal 3 + 4 (encoding and library lookup; removes the two most confusing
   failure modes).
3. Proposal 6 + 7 + 8 + 9 (robustness of the long conversions).
4. Proposal 10 + 11 + 12 + 13 (portability, performance, introspection).
5. Proposal 14 (lock everything in with fixtures) — ideally started alongside
   proposal 1 so the 39-node deck is a permanent regression test.
