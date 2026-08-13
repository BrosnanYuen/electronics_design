* [Introduction](#_introduction)
  + [Instance Path](#_instance_path)
  + [Label and Pin Shapes](#_label_and_pin_shapes)
* [Layout](#_layout)
* [Header Section](#_header_section)
* [Unique Identifier Section](#_unique_identifier_section)
* [Library Symbol Section](#_library_symbol_section)
* [Junction Section](#_junction_section)
* [No Connect Section](#_no_connect_section)
* [Bus Entry Section](#_bus_entry_section)
* [Wire and Bus Section](#_wire_and_bus_section)
* [Image Section](#_image_section)
* [Graphical Line Section](#_graphical_line_section)
* [Graphical Text Section](#_graphical_text_section)
* [Local Label Section](#_local_label_section)
* [Global Label Section](#_global_label_section)
* [Hierarchical Label Section](#_hierarchical_label_section)
* [Symbol Section](#_symbol_section)
* [Hierarchical Sheet Section](#_hierarchical_sheet_section)
  + [Hierarchical Sheet Pin Definition](#_hierarchical_sheet_pin_definition)
* [Root Sheet Instance Section](#_root_sheet_instance_section)

1. [File Formats](/en/file-formats/index.html) >
2. Schematic File Format

# Schematic File Format

## Introduction

This documents the s-expression schematic file format for all versions of KiCad from 6.0.

* Schematic files use the `.kicad_sch` extension.

### Instance Path

Because KiCad schematics can support multiple instances of the same schematic using hierarchical
sheets, information for shared sheets is done using paths consisting of the
[universally unique identifiers](../sexpr-intro/index.html#_universally_unique_identifier)
that represent the hierarchical path for the sheet the instance separated by a forward slash
('/'). A typical instance path would look like:

```
"/00000000-0000-0000-0000-00004b3a13a4/00000000-0000-0000-0000-00004b617b88"
```

|  |  |
| --- | --- |
|  | The first identifier must be the root [sheet](#_hierarchical_sheet_section) which is the same identifier as the root schematic file. |

### Label and Pin Shapes

The table below defines the valid shape tokens [global labels](#_global_label_section),
[hierarchical labels](#_hierarchical_label_section), and
[hierarchical sheet pins](#_hierarchical_sheet_pin_definition).

| Token | Definition | Image |
| --- | --- | --- |
| input | Label or pin is an input shape | ![images/label_shape_input](images/label-shape-input.png) |
| output | Label or pin is an output shape | ![images/label_shape_output](images/label-shape-output.png) |
| bidirectional | Label or pin is a bidirectional shape | ![images/label_shape_bidirectional](images/label-shape-bidirectional.png) |
| tri\_state | Label or pin is a tri-state shape | ![images/label_shape_tristate](images/label-shape-tristate.png) |
| passive | Label or pin is a tri-state shape | ![images/label_shape_passive](images/label-shape-passive.png) |

## Layout

A schematic file includes the following sections:

* [Header](#_header_section)
* [Unique Identifier](#_unique_identifier_section)
* [Page Settings](../sexpr-intro/index.html#_page_settings)
* [Title Block Section](../sexpr-intro/index.html#_title_block)
* [Symbol Library Symbol Definition](#_library_symbol_section)
* [Junction Section](#_junction_section)
* [No Connect Section](#_no_connect_section)
* [Wire and Bus Section](#_wire_and_bus_section)
* [Image Section](#_image_section)
* [Graphical Line Section](#_graphical_line_section)
* [Graphical Text Section](#_graphical_text_section)
* [Local Label Section](#_local_label_section)
* [Global Label Section](#_global_label_section)
* [Symbol Section](#_symbol_section)
* [Hierarchical Sheet Section](#_hierarchical_sheet_section)
* [Root Sheet Instance Section](#_root_sheet_instance_section)

## Header Section

The `kicad_sch` token indicates that it is KiCad schematic file. This section is required.

|  |  |
| --- | --- |
|  | Third party scripts should not use `eeschema` as the generator identifier. Please use some other identifier so that bugs introduced by third party generators are not confused with a schematic file created by KiCad. |

```
(kicad_sch
  (version VERSION)                                             (1)
  (generator GENERATOR)                                         (2)

  ;; contents of the schematic file...                          (3)
)
```

|  |  |
| --- | --- |
| **1** | The `version` token attribute defines the schematic version using the YYYYMMDD date format. |
| **2** | The `generator` token attribute defines the program used to write the file. |
| **3** | The schematic sections go here. |

## Unique Identifier Section

The `uuid` token defines the globally unique identifier that identifies the schematic.

```
  UNIQUE_IDENTIFIER                                             (1)
```

NOTE Only the root schematic identifier is used as the virtual root sheet identifier. All other
identifiers are belong to [hierarchical sheet objects](#_hierarchical_sheet_section).

|  |  |
| --- | --- |
| **1** | The UNIQUE\_IDENTIFIER defines the [universally unique identifier](../sexpr-intro/index.html#_universally_unique_identifier) for the schematic file. This identifier is used when creating hierarchical sheet paths which are used to reference symbol instance data and [hierarchical sheet instance](#_hierarchical_sheet_instance_section) information. |

## Library Symbol Section

The `lib_symbols` token defines a symbol library contain all of the symbols used in the
schematic.

```
  (lib_symbols
    SYMBOL_DEFINITIONS...                                       (1)
  )
```

|  |  |
| --- | --- |
| **1** | A list of 0 or more [symbols](../sexpr-intro/index.html#_symbols). |

## Junction Section

The `junction` token defines a junction in the schematic. The junction section will not exist
if there are no junctions in the schematic.

```
  (junction
    POSITION_IDENTIFIER                                         (1)
    (diameter DIAMETER)                                         (2)
    (color R G B A)                                             (3)
    UNIQUE_IDENTIFIER                                           (4)
  )
```

|  |  |
| --- | --- |
| **1** | The POSITION\_IDENTIFIER defines the [X and Y coordinates](../sexpr-intro/index.html#_position_identifier) of the junction. |
| **2** | The `diameter` token attribute defines the DIAMETER of the junction. A diameter of 0 is the default diameter in the system settings. |
| **3** | The `color` token attributes define the Red, Green, Blue, and Alpha transparency of the junction. If all four attributes are 0, the default junction color is used. |
| **4** | The UNIQUE\_IDENTIFIER defines the [universally unique identifier](../sexpr-intro/index.html#_universally_unique_identifier) for the junction. |

## No Connect Section

The `no_connect` token defines a unused pin connection in the schematic. The no connect section
will not exist if there are not any no connects in the schematic.

```
  (no_connect
    POSITION_IDENTIFIER                                         (1)
    UNIQUE_IDENTIFIER                                           (2)
  )
```

|  |  |
| --- | --- |
| **1** | The POSITION\_IDENTIFIER defines the [X and Y coordinates](../sexpr-intro/index.html#_position_identifier) of the no connect. |
| **2** | The UNIQUE\_IDENTIFIER defines the [universally unique identifier](../sexpr-intro/index.html#_universally_unique_identifier) for the no connect. |

## Bus Entry Section

The `bus_entry` token defines a bus entry in the schematic. The bus entry section will not
exist if there are no bus entries in the schematic.

```
  (bus_entry
    POSITION_IDENTIFIER                                         (1)
    (size X Y)                                                  (2)
    STROKE_DEFINITION                                           (3)
    UNIQUE_IDENTIFIER                                           (4)
  )
```

|  |  |
| --- | --- |
| **1** | The POSITION\_IDENTIFIER defines the [X and Y coordinates](../sexpr-intro/index.html#_position_identifier) of the bus entry. |
| **2** | The `size` token attributes define the X and Y distance of the end point from the position of the bus entry. |
| **3** | The STROKE\_DEFINITION defines how the bus entry [is drawn](../sexpr-intro/index.html#_stroke_definition). |
| **4** | The UNIQUE\_IDENTIFIER defines the [universally unique identifier](../sexpr-intro/index.html#_universally_unique_identifier) for the bus entry. |

## Wire and Bus Section

The `wire` and `bus` tokens define wires and buses in the schematic. This section will not
exist if there are no wires or buses in the schematic.

```
  (wire | bus
    COORDINATE_POINT_LIST                                       (1)
    STROKE_DEFINITION                                           (2)
    UNIQUE_IDENTIFIER                                           (3)
  )
```

|  |  |
| --- | --- |
| **1** | The COORDINATE\_POINT\_LIST defines the list of [X and Y coordinates](../sexpr-intro/index.html#_coordinate_point_list) of start and end points of the wire or bus. |
| **2** | The STROKE\_DEFINITION defines how the wire or bus [is drawn](../sexpr-intro/index.html#_stroke_definition). |
| **3** | The UNIQUE\_IDENTIFIER defines the [universally unique identifier](../sexpr-intro/index.html#_universally_unique_identifier) for the wire or bus. |

## Image Section

See common [Images](../sexpr-intro/index.html#_images) section.

## Graphical Line Section

The `polyline` token defines one or more lines that may or may not represent a polygon. This
section will not exist if there are no lines in the schematic.

```
  (polyline
    COORDINATE_POINT_LIST                                       (1)
    STROKE_DEFINITION                                           (2)
    UNIQUE_IDENTIFIER                                           (3)
  )
```

|  |  |
| --- | --- |
| **1** | The COORDINATE\_POINT\_LIST defines the list of [X/Y coordinates](../sexpr-intro/index.html#_coordinate_point_list) of to draw line(s) between. A minimum of two points is required. |
| **2** | The STROKE\_DEFINITION defines how the graphical line [is drawn](../sexpr-intro/index.html#_stroke_definition).. |
| **3** | The UNIQUE\_IDENTIFIER defines the [universally unique identifier](../sexpr-intro/index.html#_universally_unique_identifier) for the graphical line. |

## Graphical Text Section

The `text` token defines graphical text in a schematic.

```
  (text
    "TEXT"                                                      (1)
    POSITION_IDENTIFIER                                         (2)
    TEXT_EFFECTS                                                (3)
    UNIQUE_IDENTIFIER                                           (4)
  )
```

|  |  |
| --- | --- |
| **1** | The TEXT is a quoted string that defines the text. |
| **2** | The POSITION\_IDENTIFIER defines the [X and Y coordinates and rotation angle](../sexpr-intro/index.html#_position_identifier) of the text. |
| **3** | The TEXT\_EFFECTS section defines how the [text is drawn](../sexpr-intro/index.html#_text_effects). |
| **4** | The UNIQUE\_IDENTIFIER defines the [universally unique identifier](../sexpr-intro/index.html#_universally_unique_identifier) for the graphical text. |

## Local Label Section

The `label` token defines an wire or bus label name in a schematic.

```
  (label
    "TEXT"                                                      (1)
    POSITION_IDENTIFIER                                         (2)
    TEXT_EFFECTS                                                (3)
    UNIQUE_IDENTIFIER                                           (4)
  )
```

|  |  |
| --- | --- |
| **1** | The TEXT is a quoted string that defines the label. |
| **2** | The POSITION\_IDENTIFIER defines the [X and Y coordinates and rotation angle](../sexpr-intro/index.html#_position_identifier) of the label. |
| **3** | The TEXT\_EFFECTS section defines how the [label text is drawn](../sexpr-intro/index.html#_text_effects). |
| **4** | The UNIQUE\_IDENTIFIER defines the [universally unique identifier](../sexpr-intro/index.html#_universally_unique_identifier) for the label. |

## Global Label Section

The `global_label` token defines a label name that is visible across all schematics in
a design. This section will not exist if no global labels are defined in the schematic.

```
  (global_label
    "TEXT"                                                      (1)
    (shape SHAPE)                                               (2)
    [(fields_autoplaced)]                                       (3)
    POSITION_IDENTIFIER                                         (4)
    TEXT_EFFECTS                                                (5)
    UNIQUE_IDENTIFIER                                           (6)
    PROPERTIES                                                  (7)
  )
```

|  |  |
| --- | --- |
| **1** | The TEXT is a quoted string that defines the global label. |
| **2** | The `shape` token attribute defines the way the global label is drawn. See table below for global label shapes. |
| **3** | The optional `fields_autoplaced` is a flag that indicates that any PROPERTIES associated with the global label have been place automatically. |
| **4** | The POSITION\_IDENTIFIER defines the [X and Y coordinates and rotation angle](../sexpr-intro/index.html#_position_identifier) of the label. |
| **5** | The TEXT\_EFFECTS section defines how the [global label text is drawn](../sexpr-intro/index.html#_text_effects). |
| **6** | The UNIQUE\_IDENTIFIER defines the [universally unique identifier](../sexpr-intro/index.html#_universally_unique_identifier) for the global label. |
| **7** | The PROPERTIES section defines the [properties](../sexpr-intro/index.html#_symbol_property) of the global label. Currently, the only supported property is the inter-sheet reference. |

## Hierarchical Label Section

The `hierarchical_label` section defines labels that are used by
[hierarchical sheets](#_hierarchical_sheet_section) to define connections between sheet in
hierarchical designs. This section will not exist if no global labels are defined in the
schematic.

```
  (hierarchical_label
    "TEXT"                                                      (1)
    (shape SHAPE)                                               (2)
    POSITION_IDENTIFIER                                         (3)
    TEXT_EFFECTS                                                (4)
    UNIQUE_IDENTIFIER                                           (5)
  )
```

|  |  |
| --- | --- |
| **1** | The TEXT is a quoted string that defines the hierarchical label. |
| **2** | The `shape` token attribute defines the way the hierarchical label is drawn. See table below for hierarchical label shapes. |
| **3** | The POSITION\_IDENTIFIER defines the [X and Y coordinates and rotation angle](../sexpr-intro/index.html#_position_identifier) of the label. |
| **4** | The TEXT\_EFFECTS section defines how the [hierarchical label text is drawn](../sexpr-intro/index.html#_text_effects). |
| **5** | The UNIQUE\_IDENTIFIER defines the [universally unique identifier](../sexpr-intro/index.html#_universally_unique_identifier) for the hierarchical label. |

## Symbol Section

The `symbol` token in the symbol section of the schematic defines an instance of a symbol from
[the library symbol section](#_library_symbol_section) of the schematic.

```
  (symbol
    "LIBRARY_IDENTIFIER"                                        (1)
    POSITION_IDENTIFIER                                         (2)
    (unit UNIT)                                                 (3)
    (in_bom yes|no)                                             (4)
    (on_board yes|no)                                           (5)
    UNIQUE_IDENTIFIER                                           (6)
    PROPERTIES                                                  (7)
    (pin "1" (uuid e148648c-6605-4af1-832a-31eaf808c2f8))       (8)
    (instances                                                  (9)
      (project "PROJECT_NAME"                                   (10)
        (path "PATH_INSTANCE"                                   (11)
          (reference "REFERENCE")                               (12)
          (unit UNIT)                                           (13)
        )

        ;; Optional symbol instances for this `project`...
      )

      ;; Optional symbol instances for other `project`...
    )
  )
```

|  |  |
| --- | --- |
| **1** | The [LIBRARY\_IDENTIFIER](../sexpr-intro/index.html#_library_identifier) defines which symbol in the [library symbol section](#_library_symbol_section) of the schematic that this schematic symbol references. |
| **2** | The POSITION\_IDENTIFIER defines the [X and Y coordinates and angle of rotation](../sexpr-intro/index.html#_position_identifier) of the symbol. |
| **3** | The `unit` token attribute defines which unit in the symbol library definition that the schematic symbol represents. |
| **4** | The `in_bom` token attribute determines whether the schematic symbol appears in any bill of materials output. |
| **5** | The `on_board` token attribute determines if the footprint associated with the symbol is exported to the board via the netlist. |
| **6** | The UNIQUE\_IDENTIFIER defines the [universally unique identifier](../sexpr-intro/index.html#_universally_unique_identifier) for the symbol. This is used to map the symbol the [symbol instance information](#_symbol_instance_section). |
| **7** | The PROPERTIES section defines a list of [symbol properties](../sexpr-intro/index.html#_symbol_property) of the schematic symbol. |
| **8** | The `pin` token attributes define ???. |
| **9** | The `instances` token defines a list of symbol instances grouped by project. Every symbol will have a least one instance. |
| **10** | The `project` token attribute defines the name of the project to which the instance data belongs. There can be instance data from other project when schematics are shared across multiple projects. The projects will be sorted by the `PROJECT_NAME` in alphabetical order. |
| **11** | The `path` token attribute is the [path to the sheet instance](#_instance_path) for the instance data. |
| **12** | The `reference` token attribute is a string that defines the reference designator for the symbol instance. |
| **13** | The `unit` token attribute is a integer ordinal that defines the symbol unit for the symbol instance. For symbols that do not define multiple units, this will always be 1. |

## Hierarchical Sheet Section

The `sheet` token defines a hierarchical sheet of the schematic.

```
  (sheet
    POSITION_IDENTIFIER                                         (1)
    (size WIDTH HEIGHT)                                         (2)
    [(fields_autoplaced)]                                       (3)
    STROKE_DEFINITION                                           (4)
    FILL_DEFINITION                                             (5)
    UNIQUE_IDENTIFIER                                           (6)
    SHEET_NAME_PROPERTY                                         (7)
    FILE_NAME_PROPERTY                                          (8)
    HIERARCHICAL_PINS                                           (9)
    (instances                                                  (10)
      (project "PROJECT_NAME"                                   (11)
        (path "PATH_INSTANCE"                                   (12)
          (page "PAGE_NUMBER")                                  (13)
        )

        ;; Optional sheet instances for this `project`...
      )

      ;; Optional sheet instances for other `project`...
    )
  )
```

|  |  |
| --- | --- |
| **1** | The POSITION\_IDENTIFIER defines the [X and Y coordinates and angle of rotation](../sexpr-intro/index.html#_position_identifier) of the sheet in the schematic. |
| **2** | The `size` token attributes define the WIDTH and HEIGHT of the sheet. |
| **3** | The optional `fields_autoplaced` token indicates if the properties have been automatically placed. |
| **4** | The STROKE\_DEFINITION defines how the sheet [outline is drawn](../sexpr-intro/index.html#_stroke_definition). |
| **5** | The FILL\_DEFINITION defines how the sheet is [filled](../sexpr-intro/index.html#_fill_definition). |
| **6** | The UNIQUE\_IDENTIFIER defines the [universally unique identifier](../sexpr-intro/index.html#_universally_unique_identifier) for the sheet. This is used to map the sheet [symbol instance information](#_symbol_instance_section) and [sheet instance information](#_hierarchical_sheet_instance_section). |
| **7** | The SHEET\_PROPERTY\_NAME is a [property](../sexpr-intro/index.html#_symbol_property) that defines the name of the sheet. This property is mandatory. |
| **8** | The FILE\_NAME\_PROPERTY is a [property](../sexpr-intro/index.html#_symbol_property) that defines the file name of the sheet. This property is mandatory. |
| **9** | The HIERARCHICAL\_PINS section is a list of [hierarchical pins](#_hierarchical_sheet_pin_definition) that map a [hierarchical label](#_hierarchical_label_section) defined in the associated schematic file. |
| **10** | The `instances` token defines a list of sheet instances grouped by project. Every sheet will have a least one instance. |
| **11** | The `project` token attribute defines the name of the project to which the instance data belongs. There can be instance data from other project when schematics are shared across multiple projects. The projects will be sorted by the `PROJECT_NAME` in alphabetical order. |
| **12** | The `path` token attribute is the [path to the sheet instance](#_instance_path) for the sheet instance data. |
| **13** | The `page` token attribute is a string that defines the page number for the sheet instance. |

### Hierarchical Sheet Pin Definition

The `pin` token in a [sheet](#_hierarchical_sheet_section) object defines an electrical connection
between the sheet in a schematic with the [hierarchical label](#_hierarchical_label_section)
defined in the associated schematic file.

```
  (pin
    "NAME"                                                      (1)
    input | output | bidirectional | tri_state | passive        (2)
    POSITION_IDENTIFIER                                         (3)
    TEXT_EFFECTS                                                (4)
    UNIQUE_IDENTIFIER                                           (5)
  )
```

|  |  |
| --- | --- |
| **1** | The "NAME" attribute defines the name of the sheet pin. It must have an identically named [hierarchical label](#_hierarchical_label_section) in the associated schematic file. |
| **2** | The electrical connect type token defines the type of electrical connect made by the sheet pin. |
| **3** | The POSITION\_IDENTIFIER defines the [X and Y coordinates and angle of rotation](../sexpr-intro/index.html#_position_identifier) of the pin in the sheet. |
| **4** | The TEXT\_EFFECTS section defines how the [pin name text is drawn](../sexpr-intro/index.html#_text_effects). |
| **5** | The UNIQUE\_IDENTIFIER defines the [universally unique identifier](../sexpr-intro/index.html#_universally_unique_identifier) for the pin. |

## Root Sheet Instance Section

```
 (path
    "/"                                                         (1)
    (page "PAGE")                                               (2)
  )
```

|  |  |
| --- | --- |
| **1** | The instance path is always empty ("/") since there are no sheets pointing to the root sheet. |
| **2** | The `page` token defines the page number of the root sheet. Page numbers can be any valid string. |

 Last Modified 2024-12-05

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