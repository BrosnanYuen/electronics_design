# ASC API Implementation Plan

## Scope

This document plans the implementation of four new public APIs for LTspice schematic (`.asc`) validation:

- `is_valid_ltspice_asc_header(filepath)`
- `is_valid_ltspice_asc_spacing(filepath)`
- `is_valid_ltspice_asc_footer(filepath)`
- `is_valid_ltspice_asc_file(filepath)`

No code is defined here. This is an implementation plan only.

## Goals

- Reuse the current project conventions used by the `.net` validators.
- Keep the public API shape consistent:
  - success: `(True, "")`
  - failure: `(False, "<message>")`
- Separate validation responsibilities clearly so each API has one job.
- Add unit and integration coverage before treating the feature as complete.

## Public API Contracts

### `is_valid_ltspice_asc_header(filepath)`

Purpose:
- Validate the required opening structure of an LTspice `.asc` file.

Expected checks:
- File exists.
- File is readable.
- First nonblank line is a valid `Version` or `VERSION` header.
- A valid `SHEET` line exists in the required early header region.
- Header tokens are structurally separated by valid whitespace.

Expected returns:
- `False, "File not found!"`
- `False, "No permission to read file!"`
- `False, "Header information is invalid! Line <n>"`
- `True, ""`

### `is_valid_ltspice_asc_spacing(filepath)`

Purpose:
- Validate line-level spacing and basic syntax for `.asc` schematic lines.

Expected checks:
- File exists.
- File is readable.
- Each nonblank line starts with a supported `.asc` keyword.
- Required keyword token counts are present.
- Keywords and arguments are separated by valid whitespace.
- No merged tokens such as malformed `WIRE`, `FLAG`, `SYMBOL`, `SYMATTR`, or `TEXT` lines.

Expected returns:
- `False, "File not found!"`
- `False, "No permission to read file!"`
- `False, "Line format/spacing is invalid! Line <n>"`
- `True, ""`

### `is_valid_ltspice_asc_footer(filepath)`

Purpose:
- Validate the closing simulation-information region of a schematic.

Expected checks:
- File exists.
- File is readable.
- File already passes basic line parsing assumptions.
- At least one simulation directive is present in `TEXT ... !.<directive>` form.
- Footer-style directive text is structurally valid.
- Reject malformed directive carriers such as broken `TEXT` records or merged `!.tran10m` style commands.

Expected returns:
- `False, "File not found!"`
- `False, "No permission to read file!"`
- `False, "Footer information is invalid! Line <n>"`
- `True, ""`

Note:
- For `.asc`, “footer” is not as rigid as `.net`. The implementation should define a project rule for what counts as valid simulation directive presence and placement.

### `is_valid_ltspice_asc_file(filepath)`

Purpose:
- Validate a schematic file by composing the three `.asc` validators.

Expected flow:
- Run header validation first.
- Run spacing validation second.
- Run footer validation third.
- Return the first failing public result unchanged.

Expected returns:
- `False, "File not found!"`
- `False, "No permission to read file!"`
- `False, "<propagated validator message>"`
- `True, ""`

## Proposed Validation Model

### 1. Shared file reading

Plan:
- Reuse the current safe file reader pattern from the `.net` APIs.
- Keep path coercion, existence checks, permission checks, and decoding behavior aligned with existing code.

Reason:
- The project already has stable filesystem error semantics. The new APIs should not invent new ones.

### 2. `.asc` line classification

Plan:
- Introduce a dedicated internal classifier for `.asc` records.
- Supported line-leading keywords should include:
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

Reason:
- The `valid_asc/` samples use these keywords and the existing `LTSpice_ASC.md` research document already establishes them as the initial project surface.

### 3. Header validation

Plan:
- Require a valid version line near the start.
- Require a valid `SHEET` line immediately after the version line or within a tightly defined early header region.
- Ignore blank lines only if the project chooses to be lenient.
- Decide whether keyword casing should be accepted exactly as used in samples or case-insensitively.

Open decision:
- Strict mode:
  - require line 1 = `Version 4` or `VERSION 4`
  - require line 2 = `SHEET ...`
- Practical mode:
  - require the first two nonblank structural lines to be `Version` then `SHEET`

Recommendation:
- Use practical mode. It is strict enough for the repository samples while not overfitting exact line numbers.

### 4. Spacing validation

Plan:
- Validate each supported keyword using minimal token-count rules.
- Treat `TEXT` specially because the final payload extends to end-of-line.
- Treat `SYMATTR` specially because values may contain spaces.
- Validate numeric field count only where the field structure is stable and unambiguous.

Suggested first-pass rules:
- `Version <n>`
- `SHEET <sheet_id> <width> <height>`
- `WIRE <x1> <y1> <x2> <y2>`
- `FLAG <x> <y> <name>`
- `SYMBOL <name> <x> <y> <orientation>`
- `WINDOW <number> <x> <y> <justification> <font_size>`
- `SYMATTR <key> <value...>`
- `TEXT <x> <y> <justification> <font_size> <value...>`
- `LINE <width> <x1> <y1> <x2> <y2> [style]`
- `RECTANGLE <width> <x1> <y1> <x2> <y2> [style]`
- `CIRCLE <width> <x1> <y1> <x2> <y2> [style]`
- `ARC <width> <x1> <y1> <x2> <y2> <sx> <sy> <ex> <ey> [style]`
- `IOPIN <x> <y> <polarity>`
- `BUSTAP <x1> <y1> <x2> <y2>`
- `DATAFLAG <x> <y> <expression...>`

Non-goals for first iteration:
- Full semantic validation of coordinates.
- Symbol library existence checks.
- Cross-line schematic connectivity correctness.
- Detailed validation of every possible `SYMATTR` key.

### 5. Footer validation

Plan:
- Define `.asc` footer validation around simulation directives embedded in `TEXT` records.
- Detect directive text starting with `!`.
- Parse the contained SPICE directive using a directive parser parallel to the current `.net` directive validation logic.
- Require at least one supported analysis directive:
  - `.ac`
  - `.dc`
  - `.noise`
  - `.op`
  - `.tf`
  - `.tran`
  - `.fra` if supported by the project
- Allow non-analysis directive helpers such as:
  - `.step`
  - `.ic`
  - `.model`
  - `.lib`
  - `.include`

Open decision:
- Whether “footer” means:
  - the file must end with directive-bearing `TEXT` lines, or
  - the file must simply contain valid simulation `TEXT` directives anywhere

Recommendation:
- Use directive presence anywhere in the file, not literal end-of-file placement.

Reason:
- The repository `valid_asc/` samples place directive `TEXT` near the lower drawing area, but `.asc` is schematic geometry, not a strict sequential footer like `.net`.

### 6. Whole-file validation

Plan:
- Mirror the `.net` composition model:
  - `header`
  - `spacing`
  - `footer`
- Return the first failing tuple unchanged.

Reason:
- This keeps user-facing behavior predictable and consistent with existing APIs.

## Internal Helper Plan

Expected internal helpers:
- Shared `.asc` keyword classifier
- Shared `.asc` token validator
- `TEXT` directive extractor
- `.asc` header validator working on loaded lines
- `.asc` spacing validator working on loaded lines
- `.asc` footer validator working on loaded lines

Expected reuse from existing `.net` code:
- safe file reading
- path coercion
- line-numbered public message formatting
- directive parsing ideas and analysis-directive whitelist structure

## Test Plan

### Unit tests

Add new unit test modules:
- `tests/unit/test_asc_header.py`
- `tests/unit/test_asc_spacing.py`
- `tests/unit/test_asc_footer.py`
- `tests/unit/test_asc_validation.py`

Add API error-path coverage:
- extend `tests/unit/test_api_errors.py` for missing file and permission cases

### Fixture directories

Create new fixture trees:
- `test_files/asc_header/valid/`
- `test_files/asc_header/invalid/`
- `test_files/asc_spacing/valid/`
- `test_files/asc_spacing/invalid/`
- `test_files/asc_footer/valid/`
- `test_files/asc_footer/invalid/`
- `test_files/asc_validation/valid/`
- `test_files/asc_validation/invalid/`

Suggested initial count:
- 10 valid and 10 invalid fixtures per validator area

### Integration tests

Add integration coverage using `valid_asc/`:
- all repository samples should pass spacing validation
- all repository samples should pass header validation
- selected repository samples should pass footer validation
- selected repository samples should pass whole-file validation

Reason:
- Some future `.asc` samples may be intentionally schematic-only without simulation directives, so footer and whole-file integration tests should use a curated subset if needed.

## Implementation Order

1. Define the `.asc` keyword surface and token-count rules.
2. Implement internal `.asc` line classification.
3. Implement header validation.
4. Implement spacing validation.
5. Implement `TEXT` directive extraction and footer validation.
6. Implement whole-file composition API.
7. Add unit fixtures and unit tests.
8. Add integration tests against `valid_asc/`.
9. Run full test suite and adjust strictness only where repository samples justify it.

## Risks

- `.asc` files are less rigid than `.net` files, especially around “footer” meaning.
- `TEXT` and `SYMATTR` payloads can contain spaces, comments, and free-form content.
- Exact casing and optional drawing-style arguments may vary across LTspice versions.
- Unicode micro-symbol and encoding artifacts already appear in sample files.

## Decisions To Lock Before Coding

- Whether header validation is line-position strict or first-nonblank strict.
- Whether `.asc` footer requires simulation directives at the physical end of file or anywhere in schematic text.
- Whether directive parsing inside `TEXT` should accept the same directive whitelist as `.net`.
- How strict to be about keyword casing.
- Whether helper/comment `TEXT` lines beginning with `;` should be accepted unconditionally.

## Recommended Defaults

- Header: first nonblank structural lines must be `Version` then `SHEET`
- Spacing: strict keyword/token validation, lenient free-text payload handling for `TEXT` and `SYMATTR`
- Footer: require at least one valid analysis directive carried by a `TEXT ... !.<directive>` line
- Whole-file: composed validator that propagates the first public error unchanged

## Deliverables

- Four new public APIs exposed from `src/electronics_design/__init__.py`
- Internal `.asc` validation helpers in `src/electronics_design/ltspice.py`
- New `.asc` fixture trees under `test_files/`
- New unit and integration tests
- README update documenting the four new APIs after implementation
