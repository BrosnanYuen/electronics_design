# Schemdraw Guide For LLMs

Generated: 2026-06-25 (America/Vancouver)

This document is a practical guide for language models that need to write correct, maintainable `schemdraw` code for electronic schematics.

It is based on these Schemdraw documentation pages:

- `usage/start`
- `usage/placement`
- `usage/labels`
- `usage/styles`
- `usage/backends`
- `elements/electrical`
- `elements/intcircuits`
- `elements/compound`
- `gallery/analog`
- `gallery/opamp`
- `gallery/logicgate`
- `gallery/solidstate`
- `gallery/ic`

The goal is not to restate every API. The goal is to help an LLM generate code that is:

- structurally correct
- visually readable
- easy to extend
- predictable under revision

## 1) Core Mental Model

Schemdraw is stateful. A drawing has a current cursor position and a current direction. When you add an element, it is placed relative to that drawing state unless you override placement explicitly.

For an LLM, this has one major implication:

- Do not treat each element as independent.
- Treat the schematic as a routed path plus named anchors.

Good Schemdraw code usually alternates between:

1. place an element
2. capture important anchors or endpoints
3. branch from those anchors
4. add labels only after geometry is stable

## 2) Import Pattern

Use the standard import pattern unless the task requires something narrower:

```python
import schemdraw
import schemdraw.elements as elm
```

For integrated circuits and compound helpers, import the specialized modules explicitly when helpful:

```python
from schemdraw import Drawing
from schemdraw import elements as elm
from schemdraw.elements import intcircuits as ic
```

Prefer `elm.Resistor()` style over many individual symbol imports when generating new code. It is easier to read, easier to patch, and less error-prone for LLM output.

## 3) Minimal Stable Drawing Skeleton

Use a `with` block for compact examples and predictable rendering:

```python
import schemdraw
import schemdraw.elements as elm

with schemdraw.Drawing() as d:
    d += elm.SourceV().up().label('Vin')
    d += elm.Resistor().right().label('R1')
    d += elm.Capacitor().down().label('C1')
    d += elm.Ground()
```

Use an explicit variable when the drawing will be returned, saved, or modified in stages:

```python
d = schemdraw.Drawing()
v1 = d.add(elm.SourceV().up().label('Vin'))
r1 = d.add(elm.Resistor().right().label('R1'))
d.add(elm.Dot())
```

## 4) Placement Rules LLMs Should Follow

### 4.1 Prefer directional chaining first

The most robust pattern is:

```python
d += elm.Resistor().right()
d += elm.Capacitor().down()
d += elm.Line().left()
```

Use `.right()`, `.left()`, `.up()`, `.down()` when the exact coordinate does not matter and the schematic is being built incrementally.

### 4.2 Capture references for branching

When a branch or feedback path will be added later, store the element:

```python
r1 = d.add(elm.Resistor().right().label('R1'))
op = d.add(elm.Opamp().right())
```

Then use its anchors or end points instead of guessing coordinates.

### 4.3 Prefer anchors over raw coordinates

If an element exposes meaningful anchors, use them. This is more reliable than hardcoding `xy=(x, y)`.

Typical examples:

- op-amp pins such as inverting and noninverting inputs
- IC pins exposed by the integrated-circuit helpers
- transistor terminals
- source endpoints
- element start/end anchors

For LLM-generated code, anchor-based placement is usually the difference between code that survives edits and code that breaks after one change.

### 4.4 Use `at(...)` for branch starts, not for everything

Use `at(...)` when starting a new path from an existing anchor:

```python
d += elm.Line().at(op.in1).left()
```

Do not overuse `at(...)` for every part in a linear chain. Overconstraining placement makes code harder to reason about.

### 4.5 Use `to(...)`, `tox(...)`, `toy(...)` to close geometry cleanly

For feedback loops and rectangular routing, axis-constrained placement is often cleaner than inventing segment lengths.

Use:

- `to(point)` when the segment should end at a known point
- `tox(x)` when only the x coordinate should match
- `toy(y)` when only the y coordinate should match

These are especially useful for:

- op-amp feedback networks
- bridges and mirrored branches
- IC pin fanout
- logic gate wiring

### 4.6 Do not rely on accidental cursor state

Bad pattern:

```python
d += elm.Resistor()
d += elm.Capacitor()
```

This leaves direction implicit and makes later edits risky.

Prefer:

```python
d += elm.Resistor().right()
d += elm.Capacitor().down()
```

Every element that matters should make its placement intent obvious.

## 5) Labels: Make Them Explicit

Labels are one of the easiest places for LLM output to become unreadable.

### 5.1 Use `.label(...)` for normal element labels

```python
d += elm.Resistor().right().label('10 kOhm')
```

### 5.2 Use location-aware labels when ambiguity matters

If the drawing is dense, specify the label side:

```python
d += elm.Resistor().right().label('R1', loc='top')
d += elm.Capacitor().down().label('1 uF', loc='right')
```

### 5.3 Separate reference designators from values when needed

When the schematic should show both:

```python
d += elm.Resistor().right().label('R1', loc='top').label('10 kOhm', loc='bottom')
```

This is often better than cramming `R1\n10 kOhm` into one label.

### 5.4 Label nets with dots or explicit connection points

If multiple branches join, add a `Dot()` and place net labels near the node rather than on arbitrary wire segments.

### 5.5 Keep text short

Prefer:

- `VCC`
- `GND`
- `CLK`
- `R1`
- `100 kOhm`

Avoid long prose labels inside the drawing unless the user explicitly wants annotation-heavy output.

## 6) Styles: Use Consistency, Not Decoration

Schemdraw supports styling at the drawing and element level. LLMs should use this conservatively.

### 6.1 Set global style once when needed

If the user asks for a theme, line width change, or font adjustment, do it at the drawing level instead of repeating style on every element.

### 6.2 Override locally only for semantic emphasis

Good local overrides:

- highlight a signal path
- distinguish analog vs digital rails
- emphasize measurement points

Bad local overrides:

- random per-element colors
- inconsistent line widths
- mixed visual conventions with no meaning

### 6.3 Default to neutral output

Unless asked otherwise, generate black-and-white or near-neutral schematics. That matches the docs, the gallery examples, and common engineering expectations.

## 7) Backends and Rendering Decisions

Schemdraw supports different rendering backends. For LLM output, the practical rule is:

- generate drawing code first
- backend-specific output only when the user asks for saving, notebooks, or file export behavior

If the task is just “draw this circuit,” do not overcomplicate the snippet with backend configuration.

When the user asks for saved output, use a direct rendering flow such as:

```python
d = schemdraw.Drawing()
# ... add elements ...
d.save('circuit.svg')
```

Prefer `svg` when the user wants crisp scalable output. Prefer `png` only when bitmap output is explicitly needed.

## 8) Element Selection Rules

The electrical element library is broad. LLMs should choose symbols that match the abstraction level of the prompt.

### 8.1 Use simple passive symbols by default

For ordinary circuits, start with:

- `Resistor`
- `Capacitor`
- `Inductor`
- `Diode`
- `LED`
- `SourceV`
- `SourceI`
- `Ground`
- `Line`
- `Dot`

### 8.2 Use specialized active-device symbols only when they matter

Examples:

- BJT symbols for biasing, mirrors, discrete amplifiers
- FET symbols for switching and analog front ends
- op-amp symbols for amplifier/filter blocks
- logic gates for boolean circuits
- IC blocks when pin identity matters

Do not replace a simple op-amp block with a large IC package unless the prompt explicitly needs pin numbers or package-style presentation.

### 8.3 Match the gallery’s abstraction style

From the gallery pages, the common pattern is:

- analog examples use clean signal flow and compact passive placement
- op-amp examples rely heavily on anchor-based feedback routing
- logic examples prefer symmetric placement and short labeled interconnects
- solid-state examples emphasize terminal correctness
- IC examples use structured pin declarations rather than ad hoc graphics

This is the style LLMs should emulate.

## 9) Op-Amp Drawings

Op-amp schematics are a common failure mode for generated code because feedback geometry is easy to get wrong.

### 9.1 Place the op-amp early

Build the op-amp body first, then route around it:

```python
op = d.add(elm.Opamp().right())
```

### 9.2 Use input/output anchors

Do not guess where the pins are. Use the op-amp anchors exposed by the element.

Typical pattern:

```python
d += elm.Line().at(op.in1).left()
d += elm.Line().at(op.in2).left()
d += elm.Line().at(op.out).right()
```

### 9.3 Build feedback with constrained routing

Feedback loops should usually be rectangular and axis-aligned:

```python
d += elm.Line().at(op.out).up()
d += elm.Line().left()
d += elm.Line().to(op.in1)
```

Or use `tox(...)` and `toy(...)` for more stable closures.

### 9.4 Add supplies only if the prompt needs them

Many documentation and gallery examples omit explicit power rails for conceptual clarity. Follow the prompt:

- educational block diagram: omit supplies if not requested
- realistic analog schematic: include rails

## 10) Logic Gate Drawings

Logic circuits should be spatially organized by signal flow.

### 10.1 Keep left-to-right flow

Inputs on the left, outputs on the right, shared control or clocks consistently placed.

### 10.2 Align gates to a grid

Small vertical misalignments make logic diagrams look wrong immediately. If combining multiple gates, use explicit start points or anchor-based fanout.

### 10.3 Label signals, not just parts

For logic diagrams, net names such as `A`, `B`, `CLK`, `Q`, `Y` are usually more important than device reference names.

## 11) Transistors And Solid-State Devices

Terminal correctness matters more than visual flair.

### 11.1 Use the right symbol family

Choose BJT, JFET, MOSFET, photodiode, SCR, or related devices according to the prompt. Do not substitute one active symbol for another merely because the geometry is similar.

### 11.2 Respect terminal anchors

For transistor drawings, collector/drain/source/base/gate/emitter placement should follow the element’s intended anchors rather than arbitrary wires.

### 11.3 Add polarity and orientation intentionally

If the user asks for PNP vs NPN, PMOS vs NMOS, or diode direction, ensure the selected symbol actually encodes that difference. Do not assume a mirror transform alone is enough unless you verify the resulting terminal semantics.

## 12) Integrated Circuits And `intcircuits`

Use the integrated-circuit helpers when the prompt requires pin names, pin numbers, grouped sides, or package-like presentation.

### 12.1 Prefer declarative pin definitions

The IC helpers are designed around pin metadata. That is better than drawing a rectangle and attaching loose wires.

Typical reasons to use an IC helper:

- 555 timer
- logic IC with named pins
- ADC/DAC or interface chip
- custom block with many labeled pins

### 12.2 Group pins by side and function

A readable IC drawing usually organizes:

- inputs on the left
- outputs on the right
- supplies on top/bottom or clearly separated
- related control pins together

### 12.3 Keep custom ICs sparse

Do not define twenty decorative fields if the prompt only needs six functional pins. Over-specification makes generated code noisy and harder to maintain.

## 13) Compound Elements

Compound elements are useful when the user wants a common subassembly as one reusable visual block.

Use them when:

- a repeated structure appears multiple times
- the schematic benefits from abstraction
- the docs already model the pattern as a compound helper

Avoid them when:

- the user needs to inspect each primitive component
- the task is educational and should show internal structure

## 14) Recommended Construction Workflow For LLMs

When generating a nontrivial schematic, use this order:

1. Choose the abstraction level.
2. Place the main signal-path elements.
3. Capture anchors for branch points.
4. Add secondary branches and feedback paths.
5. Add dots and ground/reference markers.
6. Add labels.
7. Add styling only if requested.
8. Save or display only if requested.

This order reduces rewrite churn.

## 15) Patterns That Usually Work Well

### 15.1 Linear chain

```python
with schemdraw.Drawing() as d:
    d += elm.SourceV().up().label('Vin')
    d += elm.Resistor().right().label('R1', loc='top')
    d += elm.Capacitor().down().label('C1', loc='right')
    d += elm.Ground()
```

### 15.2 Branch from a stored node

```python
with schemdraw.Drawing() as d:
    r1 = d.add(elm.Resistor().right().label('R1'))
    d += elm.Dot()
    d += elm.Resistor().down().label('R2')
    d += elm.Ground()
    d += elm.Line().at(r1.end).right()
```

### 15.3 Op-amp with anchor-based routing

```python
with schemdraw.Drawing() as d:
    op = d.add(elm.Opamp().right())
    d += elm.Line().at(op.in1).left().label('V-', loc='left')
    d += elm.Line().at(op.in2).left().label('V+', loc='left')
    d += elm.Line().at(op.out).right().label('Vout', loc='right')
```

## 16) Common LLM Failure Modes

Avoid these:

- mixing implicit and explicit placement randomly
- hardcoding many raw coordinates for a simple drawing
- failing to store references before making branches
- labeling before the geometry is stable
- drawing wires that visually touch but are not anchored consistently
- using the wrong element class for the requested device
- adding style noise unrelated to circuit meaning
- generating package-level IC drawings when a symbolic block is enough

## 17) Practical Heuristics

Use these default heuristics unless the prompt says otherwise:

- Prefer left-to-right signal flow.
- Prefer anchor-based routing for op-amps, gates, transistors, and ICs.
- Prefer explicit directions on all significant elements.
- Prefer short labels with standard electrical abbreviations.
- Prefer `svg` output for saved figures.
- Prefer simple primitive elements until pin-level detail is required.

## 18) What To Do When The Prompt Is Ambiguous

If the user says “draw an amplifier” and does not specify the abstraction level:

- choose the simplest schematic that satisfies the request
- use standard symbols
- include labels for the major functional parts
- avoid package-specific IC detail unless requested

If the user asks for a “realistic” or “pin-accurate” drawing:

- switch to anchor-heavy placement
- include supplies and reference nodes where relevant
- use `intcircuits` or explicit device terminals as needed

## 19) Final Rule

For LLM-generated Schemdraw code, correctness comes from disciplined placement, not from memorizing every element class.

The safest default strategy is:

- place in a clear direction
- store references early
- route from anchors
- label after geometry settles
- keep the visual language simple
