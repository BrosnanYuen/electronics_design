* [Introduction](#_introduction)
  + [Syntax](#_syntax)
  + [Conventions](#_conventions)
  + [Coordinates and Sizes](#_coordinates_and_sizes)
* [Common Syntax](#_common_syntax)
  + [Library Identifier](#_library_identifier)
  + [Position Identifier](#_position_identifier)
  + [Coordinate Point List](#_coordinate_point_list)
  + [Stroke Definition](#_stroke_definition)
  + [Text Effects](#_text_effects)
  + [Page Settings](#_page_settings)
  + [Title Block](#_title_block)
  + [Properties](#_properties)
  + [Universally Unique Identifier](#_universally_unique_identifier)
  + [Images](#_images)
* [Board Common Syntax](#_board_common_syntax)
* [Board Coordinates](#_board_coordinates)
* [Layers](#_layers)
  + [Capacity](#_capacity)
  + [Canonical Layer Names](#_canonical_layer_names)
  + [Footprint](#_footprint)
  + [Graphic Items](#_graphic_items)
  + [Graphical Text Box](#_graphical_text_box)
  + [Zone](#_zone)
* [Group](#_group)
* [Schematic and Symbol Library Common Syntax](#_schematic_and_symbol_library_common_syntax)
  + [Schematic Coordinates](#_schematic_coordinates)
  + [Symbol Unit Identifier](#_symbol_unit_identifier)
  + [Fill Definition](#_fill_definition)
  + [Symbols](#_symbols)

1. [File Formats](/en/file-formats/index.html) >
2. S-Expression Format

# S-Expression Format

## Introduction

KiCad uses an s-expression file format for symbol libraries, footprint libraries,
schematics, printed circuit boards, and title block and border worksheets.

### Syntax

* Syntax is based on the Specctra DSN file format.
* Token definitions are delimited by opening `(` and closing `)` parenthesis.
* All tokens are lowercase.
* Tokens cannot contain any white space characters or special characters other than the
  underscore '\_' character.
* All strings are quoted using the double quote character (") and are UTF-8 encoded.
* Tokens can have zero or more attributes.
* Human readability is a design goal.

### Conventions

In order to use the file format documentation properly, there are a few notation conventions
that must be understood.

* Token attributes are upper case descriptive names. For example `(at X Y)`, X is the
  horizontal coordinate and Y is the vertical coordinate.
* Some tokens have a limited number of possible attribute values which are separated by a
  logical or character '|'. For example `(visible yes|no)` the only valid attributes for
  the `visible` token are `yes` or `no`.
* Some tokens have optional attributes which are enclosed in square braces. For example
  `(paper A0 [portrait])` the page portrait setting is optional.

### Coordinates and Sizes

* All values are given in millimeters.
* Exponential floating point values are not used for readability purposes.
* All coordinates are relative to the origin of their containing object.

## Common Syntax

This section defines all syntax that is shared across the symbol library, footprint library,
schematic, board, and work sheet file formats.

### Library Identifier

The [schematic symbol library](../sexpr-symbol-lib/index.html#_introduction) and
[printed circuit board footprint library](../sexpr-footprint/index.html#_introduction)
file formats use library identifiers. Library identifiers are defined as a quoted string
using the "LIBRARY\_NICKNAME:ENTRY\_NAME" format where "LIBRARY\_NICKNAME" is the nickname
of the library in the symbol or footprint library table and "ENTRY\_NAME" is the name of
the symbol or footprint in the library separated by a colon.

|  |  |
| --- | --- |
|  | The "LIBRARY\_NICKNAME" is not stored in the library files because a library cannot know what the assigned library table nickname is in advance. Only the "ENTRY\_NAME" is saved in the library files. |

### Position Identifier

The `at` token defines the positional coordinates and rotation of an object.

```
  (at
    X                                                           (1)
    Y                                                           (2)
    [ANGLE]                                                     (3)
  )
```

|  |  |
| --- | --- |
| **1** | The X attribute defines the horizontal position of the object. |
| **2** | The Y attribute defines the vertical position of the object. |
| **3** | The optional ANGLE attribute defines the rotational angle of the object. Not all objects have rotational position definitions. |

|  |  |
| --- | --- |
|  | Symbol `text` ANGLEs are stored in tenth’s of a degree. All other ANGLEs are stored in degrees. |

### Coordinate Point List

The `pts` token defines a list of X/Y coordinate points.

```
  (pts
    (xy X Y)                                                    (1)
    ...
    (xy X Y)
  )
```

|  |  |
| --- | --- |
| **1** | The `xy` token defines a single X and Y coordinate pair. The number of points is determined by the object type. |

### Stroke Definition

The `stroke` token defines how the outlines of graphical objects are drawn.

```
  (stroke
    (width WIDTH)                                               (1)
    (type TYPE)                                                 (2)
    (color R G B A)                                             (3)
  )
```

|  |  |
| --- | --- |
| **1** | The `width` token attribute defines the line width of the graphic object. |
| **2** | The `type` token attribute defines the line style of the graphic object. Valid stroke line styles are: * `dash` * `dash_dot` * `dash_dot_dot` (from version 7) * `dot` * `default` * `solid` |
| **3** | The `color` token attributes define the line red, green, blue, and alpha color settings. |

### Text Effects

All text objects can have an optional `effects` section that defines how the text is displayed.

```
  (effects
    (font                                                       (1)
      [(face FACE_NAME)]                                        (2)
      (size HEIGHT WIDTH)                                       (3)
      [(thickness THICKNESS)]                                   (4)
      [bold]                                                    (5)
      [italic]                                                  (6)
      [(line_spacing LINE_SPACING)]                             (7)
    )
    [(justify [left | right] [top | bottom] [mirror])]          (8)(9)
    [hide]                                                      (10)
  )
```

|  |  |
| --- | --- |
| **1** | The `font` token attributes define how the text is shown. |
| **2** | The optional `face` token indicates the font family. It should be a TrueType font family name or "KiCad Font" for the KiCad stroke font. (from version 7) |
| **3** | The `size` token attributes define the font height and width. |
| **4** | The `thickness` token attribute defines the line thickness of the font. |
| **5** | The `bold` token specifies if the font should be bold. |
| **6** | The `italic` token specifies if the font should be italicized. |
| **7** | The `line_spacing` token specifies the spacing between lines as a ratio of standard line-spacing. (Not yet supported) |
| **8** | The optional `justify` token attributes define if the text is justified horizontally `right` or `left` and/or vertically `top` or `bottom` and/or mirrored. If the justification is not defined, then the text is center justified both horizontally and vertically and not mirrored. |
| **9** | The `mirror` token is only supported in the PCB Editor and Footprints. |
| **10** | The optional `hide` token defines if the text is hidden. |

### Page Settings

The `paper` token defines the drawing page size and orientation.

```
  (paper
    PAPER_SIZE | WIDTH HEIGHT                                   (1)
    [portrait]                                                  (2)
  )
```

|  |  |
| --- | --- |
| **1** | Valid pages sizes are A0, A1, A2, A3, A4, A5, A, B, C, D, and E or the WIDTH and HEIGHT attributes are used for custom user defined page sizes. |
| **2** | The `portrait` token defines if the page is shown in the portrait mode. If not defined, the landscape page layout mode is used. |

### Title Block

The `title_block` token defines the contents of the title block.

```
  (title_block
    (title "TITLE")                                             (1)
    (date "DATE")                                               (2)
    (rev "REVISION")                                            (3)
    (company "COMPANY_NAME")                                    (4)
    (comment N "COMMENT")                                       (5)
  )
```

|  |  |
| --- | --- |
| **1** | The `title` token attribute is a quoted string that defines the document title. |
| **2** | The `date` token attribute is a quoted string that defines the document date using the YYYY-MM-DD format. |
| **3** | The `rev` token attribute is a quoted string that defines the document revision. |
| **4** | The `company` token attribute is a quoted string that defines the document company name. |
| **5** | The `comment` token attributes define the document comments where N is a number from 1 to 9 and COMMENT is a quoted string. |

### Properties

The `property` token defines a key value pair for storing user defined information.

```
  (property
    "KEY"                                                       (1)
    "VALUE"                                                     (2)
  )
```

|  |  |
| --- | --- |
| **1** | The property key attribute is a string that defines the name of the property. Property keys must be unique. |
| **2** | The property value attribute is a string associated with the key attribute. |

### Universally Unique Identifier

The `uuid` token defines an universally unique identifier.

```
  (uuid
    UUID                                                        (1)(2)
  )
```

|  |  |
| --- | --- |
| **1** | The UUID attribute is a Version 4 (random) UUID that should be globally unique. KiCad UUIDs are generated using the [mt19937 Mersenne Twister](https://en.wikipedia.org/wiki/Mersenne_Twister) algorithm. |
| **2** | Files converted from legacy versions of KiCad (prior to 6.0) have their locally-unique timestamps re-encoded in UUID format. |

### Images

The `image` token defines an embedded image. This section will not exist if no images
are present.

```
  (image
    POSITION_IDENTIFIER                                         (1)
    [(scale SCALAR)]                                            (2)
    [(layer LAYER_DEFINITIONS)]                                 (3)
    UNIQUE_IDENTIFIER                                           (4)
    (data IMAGE_DATA)                                           (5)
  )
```

|  |  |
| --- | --- |
| **1** | The POSITION\_IDENTIFIER defines the [X and Y coordinates](../sexpr-intro/index.html#_position_identifier) of the image. |
| **2** | The optional `scale` token attribute defines the SCALE\_FACTOR of the image. |
| **3** | The `layer` token attribute defines the associated board layer of the image using one [canonical layer name](#_canonical_layer_names). Only used by board and footprint images. |
| **4** | The UNIQUE\_IDENTIFIER defines the [universally unique identifier](../sexpr-intro/index.html#_universally_unique_identifier) for the image. |
| **5** | The `data` token attribute defines the image data in the [portable network graphics format (PNG)](https://en.wikipedia.org/wiki/Portable_Network_Graphics) encoded with [MIME type base64](https://en.wikipedia.org/wiki/Base64#MIME). |

## Board Common Syntax

This section defines all syntax that is shared across the footprint library and printed
circuit board file formats.

## Board Coordinates

* The minimum internal unit for printed circuit board and footprint files is one nanometer so
  there is maximum resolution of six decimal places or 0.000001 mm. Any precision beyond six
  places will be truncated.

## Layers

All drawable board and footprint objects exist on a `layer` which is defined in the drawable
item definition. All layers can be renamed by the user.

|  |  |
| --- | --- |
|  | Internally, all layer names are canonical. User defined layer names are only used for display and output purposes. |

```
  (layer
    LAYER_DEFINITION                                            (1)
  )
```

|  |  |
| --- | --- |
| **1** | Layer definitions can be specified as a list of one or more [canonical layer names](#_canonical_layer_names) or with a '\*' wildcard to represent all layers that match the rest of the wildcard. For instance, `*.Cu` represents all of the copper layers. This only applies to [canonical layers names](#_canonical_layer_names). |

### Capacity

* 60 total layers.
* 32 copper layers.
* 8 paired technical layers for silk screen, solder mask, solder paste, and adhesive.
* 4 user pre-defined layers for drawings, engineering change order (ECO), and comments.
* 1 layer to define the board outline.
* 1 layer to define the board margins.
* 9 optional user definable layers.

### Canonical Layer Names

The table below list all of the canonical layer names used in the file format.

| Canonical Name | Description |
| --- | --- |
| F.Cu | Front copper layer |
| In1.Cu | Inner copper layer 1 |
| In2.Cu | Inner copper layer 2 |
| In3.Cu | Inner copper layer 3 |
| In4.Cu | Inner copper layer 4 |
| In5.Cu | Inner copper layer 5 |
| In6.Cu | Inner copper layer 6 |
| In7.Cu | Inner copper layer 7 |
| In8.Cu | Inner copper layer 8 |
| In9.Cu | Inner copper layer 9 |
| In10.Cu | Inner copper layer 10 |
| In11.Cu | Inner copper layer 11 |
| In12.Cu | Inner copper layer 12 |
| In13.Cu | Inner copper layer 13 |
| In14.Cu | Inner copper layer 14 |
| In15.Cu | Inner copper layer 15 |
| In16.Cu | Inner copper layer 16 |
| In17.Cu | Inner copper layer 17 |
| In18.Cu | Inner copper layer 18 |
| In19.Cu | Inner copper layer 19 |
| In20.Cu | Inner copper layer 20 |
| In21.Cu | Inner copper layer 21 |
| In22.Cu | Inner copper layer 22 |
| In23.Cu | Inner copper layer 23 |
| In24.Cu | Inner copper layer 24 |
| In25.Cu | Inner copper layer 25 |
| In26.Cu | Inner copper layer 26 |
| In27.Cu | Inner copper layer 27 |
| In28.Cu | Inner copper layer 28 |
| In29.Cu | Inner copper layer 29 |
| In30.Cu | Inner copper layer 30 |
| B.Cu | Back copper layer |
| B.Adhes | Back adhesive layer |
| F.Adhes | Front adhesive layer |
| B.Paste | Back solder paste layer |
| F.Paste | Front solder paste layer |
| B.SilkS | Back silk screen layer |
| F.SilkS | Front silk screen layer |
| B.Mask | Back solder mask layer |
| F.Mask | Front solder mask layer |
| Dwgs.User | User drawing layer |
| Cmts.User | User comment layer |
| Eco1.User | User engineering change order layer 1 |
| Eco2.User | User engineering change order layer 2 |
| Edge.Cuts | Board outline layer |
| F.CrtYd | Footprint front courtyard layer |
| B.CrtYd | Footprint back courtyard layer |
| F.Fab | Footprint front fabrication layer |
| B.Fab | Footprint back fabrication layer |
| User.1 | User definable layer 1 |
| User.2 | User definable layer 2 |
| User.3 | User definable layer 3 |
| User.4 | User definable layer 4 |
| User.5 | User definable layer 5 |
| User.6 | User definable layer 6 |
| User.7 | User definable layer 7 |
| User.8 | User definable layer 8 |
| User.9 | User definable layer 9 |

### Footprint

The `footprint` token defines a footprint.

|  |  |
| --- | --- |
|  | Prior to version 6, the `footprint` token was referred to as `module`. |

```
  (footprint
    ["LIBRARY_LINK"]                                            (1)
    [locked]                                                    (2)
    [placed]                                                    (3)
    (layer LAYER_DEFINITIONS)                                   (4)
    (tedit TIME_STAMP)                                          (5)
    [(uuid UUID)]                                               (6)
    [POSITION_IDENTIFIER]                                       (7)
    [(descr "DESCRIPTION")]                                     (8)
    [(tags "NAME")]                                             (9)
    [(property "KEY" "VALUE") ...]                              (10)
    (path "PATH")                                               (11)
    [(autoplace_cost90 COST)]                                   (12)
    [(autoplace_cost180 COST)]                                  (13)
    [(solder_mask_margin MARGIN)]                               (14)
    [(solder_paste_margin MARGIN)]                              (15)
    [(solder_paste_ratio RATIO)]                                (16)
    [(clearance CLEARANCE)]                                     (17)
    [(zone_connect CONNECTION_TYPE)]                            (18)
    [(thermal_width WIDTH)]                                     (19)
    [(thermal_gap DISTANCE)]                                    (20)
    [ATTRIBUTES]                                                (21)
    [(private_layers LAYER_DEFINITIONS)]                        (22)
    [(net_tie_pad_groups PAD_GROUP_DEFINITIONS)]                (23)
    GRAPHIC_ITEMS...                                            (24)
    PADS...                                                     (25)
    ZONES...                                                    (26)
    GROUPS...                                                   (27)
    3D_MODEL                                                    (28)
  )
```

|  |  |
| --- | --- |
| **1** | The "LIBRARY\_LINK" attribute defines the link to footprint library of the footprint. This only applies to footprints defined in the board file format. |
| **2** | The optional `locked` token defines a flag to indicate the footprint cannot be edited. |
| **3** | The optional `placed` token defines a flag to indicate that the footprint has not been placed. |
| **4** | The `layer` token defines the [canonical layer](#_canonical_layer_names) the footprint is placed. |
| **5** | The `tedit` token defines a the last time the footprint was edited. |
| **6** | The `uuid` token defines the unique identifier for the footprint. This only applies to footprints defined in the board file format. |
| **7** | The [POSITION\_IDENTIFIER](#_position_identifier) defines the X and Y coordinates and rotational angle of the footprint. This only applies to footprints defined in the board file format. |
| **8** | The optional `tags` token defines a string of search tags for the footprint. |
| **9** | The optional `descr` token defines a string containing the description of the footprint. |
| **10** | The optional `property` token defines a property for the footprint. |
| **11** | The `path` token defines the hierarchical path of the schematic symbol linked to the footprint. This only applies to footprints defined in the board file format. |
| **12** | The optional `autoplace_cost90` token defines the vertical cost of when using the automatic footprint placement tool. Valid values are integers 1 through 10. This only applies to footprints defined in the board file format. |
| **13** | The optional `autoplace_cost180` token defines the horizontal cost of when using the automatic footprint placement tool. Valid values are integers 1 through 10. This only applies to footprints defined in the board file format. |
| **14** | The optional `solder_mask_margin` token defines the solder mask distance from all pads in the footprint. If not set, the board `solder_mask_margin` setting is used. |
| **15** | The optional `solder_paste_margin` token defines the solder paste distance from all pads in the footprint. If not set, the board `solder_paste_margin` setting is used. |
| **16** | The optional `solder_paste_ratio` token defines the percentage of the pad size used to define the solder paste for all pads in the footprint. If not set, the board `solder_paste_ratio` setting is used. |
| **17** | The optional `clearance` token defines the clearance to all board copper objects for all pads in the footprint. If not set, the board `clearance` setting is used. |
| **18** | The optional `zone_connect` token defines how all pads are connected to filled zone. If not defined, then the zone `connect_pads` setting is used. Valid connection types are integers values from 0 to 3 which defines: * 0 - Pads are not connect to zone. * 1 - Pads are connected to zone using thermal reliefs. * 2 - Pads are connected to zone using solid fill. |
| **19** | The optional `thermal_width` token defined the thermal relief spoke width used for zone connections for all pads in the footprint. This only affects pads connected to zones with thermal reliefs. If not set, the zone `thermal_width` setting is used. |
| **20** | The optional `thermal_gap` is the distance from the pad to the zone of thermal relief connections for all pads in the footprint. If not set, the zone `thermal_gap` setting is used. If not set, the zone `thermal_gap` setting is used. |
| **21** | The optional [attributes section](#_footprint_attributes) defines the attributes of the footprint. |
| **22** | An optional list of [canonical layer names](#_canonical_layer_names) which are private to the footprint. |
| **23** | An optional list of [net-tie pad groups](#_net_tie_pad_groups). |
| **24** | The graphic objects section is a list of one or more [graphical objects](#_footprint_graphics_items) in the footprint. At a minimum, the reference designator and value [text objects](#_footprint_text) are defined. All other graphical objects are optional. |
| **25** | The optional pads section is a list of [pads](#_footprint_pad) in the footprint. |
| **26** | The optional zones section is a list of [keep out zones](#_zone) in the footprint. |
| **27** | The optional groups section is a list of [grouped objects](#_group) in the footprint. |
| **28** | The [3D model section](#_footprint_3d_model) defines the 3D model object associated with the footprint. |

#### Footprint Attributes

Footprint `attr` token defines the list of attributes of the footprint.

```
    (attr
      TYPE                                                      (1)
      [board_only]                                              (2)
      [exclude_from_pos_files]                                  (3)
      [exclude_from_bom]                                        (4)
    )
```

|  |  |
| --- | --- |
| **1** | The TYPE token defines the type of footprint. Valid footprint types are `smd` and `through_hole`. |
| **2** | The optional `board_only` token indicates that the footprint is only defined in the board and has no reference to any schematic symbol. |
| **3** | The optional `exclude_from_pos_files` token indicates that the footprint position information should not be included when creating position files. |
| **4** | The optional `exclude_from_bom` token indicates that the footprint should be excluded when creating bill of materials (BOM) files. |

#### Net-tie Pad Groups

A space-separated list of quoted strings, each containing a comma-separated list of pad names.
Nets attached to pads within a single pad-group are allowed to short.

#### Footprint Graphics Items

Footprint graphical items define all of the drawing items that are used in the
[footprint definition](#_footprint). This includes [text](#_footprint_text),
[text boxes](#_footprint_text_box), [lines](#_footprint_line), [rectangles](#_footprint_rectangle),
[circles](#_footprint_circle), [arcs](#_footprint_arc), [polygons](#_footprint_polygon),
[curves](#_footprint_curve), and [dimensions](#_dimension).

|  |  |
| --- | --- |
|  | Footprint graphic items starting with `fp_` are not valid outside of a footprint definition. |

#### Footprint Images

See the [images](#_images) section. This section will not exist if there are no images on the
footprint. Footprint images are not displayed on the PCB when a footprint is placed, only in
the footprint editor.

##### Footprint Text

The `fp_text` token defines text in a [footprint definition](#_footprint).

```
    (fp_text
      TYPE                                                      (1)
      "TEXT"                                                    (2)
      POSITION_IDENTIFIER                                       (3)
      [unlocked]                                                (4)
      (layer LAYER_DEFINITION)                                  (5)
      [hide]                                                    (6)
      (effects TEXT_EFFECTS)                                    (7)
      (uuid UUID)                                               (8)
    )
```

|  |  |
| --- | --- |
| **1** | The TYPE attribute defines the type of text. Valid types are `reference`, `value`, and `user`. |
| **2** | The "TEXT" attribute is a quoted string that defines the text. |
| **3** | The [POSITION\_IDENTIFIER](#_position_identifier) defines the X and Y position coordinates and optional orientation angle of the text. |
| **4** | The optional `unlocked` token indicates if the text orientation can be anything other than the upright orientation. |
| **5** | The `layer` token defines the [canonical layer](#_canonical_layer_names) the text resides on. |
| **6** | The optional [hide] token, defines if the text is hidden. |
| **7** | The `effects` token defines how the [text is displayed](#_text_effects). |
| **8** | The `uuid` token defines the unique identifier of the text object. |

##### Footprint Text Box

(from version 7)

The `fp_text_box` token defines a rectangle containing line-wrapped text.

```
  (fp_text_box
    [locked]                                                    (1)
    "TEXT"                                                      (2)
    [(start X Y)]                                               (3)
    [(end X Y)]                                                 (4)
    [(pts (xy X Y) (xy X Y) (xy X Y) (xy X Y))]                 (5)
    [(angle ROTATION)]                                          (6)
    (layer LAYER_DEFINITION)                                    (7)
    (uuid UUID)                                                 (8)
    TEXT_EFFECTS                                                (9)
    [STROKE_DEFINITION]                                         (10)
    [(render_cache RENDER_CACHE)]                               (11)
  )
```

|  |  |
| --- | --- |
| **1** | The optional `locked` token specifies if the text box can be moved. |
| **2** | The content of the text box |
| **3** | The `start` token defines the top-left of a cardinally oriented text box. |
| **4** | The `end` token defines the bottom-right of a cardinally oriented text box. |
| **5** | The `pts` token defines the four corners of a non-cardianlly oriented text box. The corners must be in order, but the winding can be either direction. |
| **6** | The optional `angle` token defines the rotation of the text box in degrees. |
| **7** | The `layer` token defines the [canonical layer](#_canonical_layer_names) the text box resides on. |
| **8** | The `uuid` token defines the unique identifier of the text box. |
| **9** | The [TEXT\_EFFECTS](#_text_effects) describe the style of the text in the text box. |
| **10** | The [STROKE\_DEFINITION](#_stroke_definition) describes the style of an optional border to be drawn around the text box. |
| **11** | If the `TEXT_EFFECTS` prescribe a TrueType font then a render cache should be given in case the font can not be found on the current system. |

|  |  |
| --- | --- |
|  | If `angle` is not given, or is a cardinal angle (0, 90, 180 or 270), then the text box MUST have `start` and `end` tokens. |

|  |  |
| --- | --- |
|  | If `angle` is given and is not a cardinal angle, then the text box MUST have a `pts` token (with 4 pts). |

##### Footprint Line

The `fp_line` token defines a graphic line in a [footprint definition](#_footprint).

```
    (fp_line
      (start X Y)                                               (1)
      (end X Y)                                                 (2)
      (layer LAYER_DEFINITION)                                  (3)
      (width WIDTH)                                             (4)
      STROKE_DEFINITION                                         (5)
      [(locked)]                                                (6)
      (uuid UUID)                                               (7)
    )
```

|  |  |
| --- | --- |
| **1** | The `start` token defines the coordinates of the beginning of the line. |
| **2** | The `end` token defines the coordinates of the end of the line. |
| **3** | The `layer` token defines the [canonical layer](#_canonical_layer_names) the line resides on. |
| **4** | The `width` token defines the line width. (prior to version 7) |
| **5** | The [STROKE\_DEFINITION](#_stroke_definition) describes the width and style of the line. (from version 7) |
| **6** | The optional `locked` token defines if the line cannot be edited. |
| **7** | The `uuid` token defines the unique identifier of the line object. |

##### Footprint Rectangle

The `fp_rect` token defines a graphic rectangle in a [footprint definition](#_footprint).

```
    (fp_rect
      (start X Y)                                               (1)
      (end X Y)                                                 (2)
      (layer LAYER_DEFINITION)                                  (3)
      (width WIDTH)                                             (4)
      STROKE_DEFINITION                                         (5)
      [(fill yes | no)]                                         (6)
      [(locked)]                                                (7)
      (uuid UUID)                                               (8)
    )
```

|  |  |
| --- | --- |
| **1** | The `start` token defines the coordinates of the upper left corner of the rectangle. |
| **2** | The `end` token defines the coordinates of the low right corner of the rectangle. |
| **3** | The `layer` token defines the [canonical layer](#_canonical_layer_names) the rectangle resides on. |
| **4** | The `width` token defines the line width of the rectangle. (prior to version 7) |
| **5** | The [STROKE\_DEFINITION](#_stroke_definition) describes the line width and style of the rectangle. (from version 7) |
| **6** | The optional `fill` token defines if the rectangle is filled. If not defined, the rectangle is not filled. |
| **7** | The optional `locked` token defines if the rectangle cannot be edited. |
| **8** | The `uuid` token defines the unique identifier of the rectangle object. |

##### Footprint Circle

The `fp_circle` token defines a graphic circle in a [footprint definition](#_footprint).

```
    (fp_circle
      (center X Y)                                              (1)
      (end X Y)                                                 (2)
      (layer LAYER_DEFINITION)                                  (3)
      (width WIDTH)                                             (4)
      STROKE_DEFINITION                                         (5)
      [(fill yes | no)]                                         (6)
      [(locked)]                                                (7)
      (uuid UUID)                                               (8)
    )
```

|  |  |
| --- | --- |
| **1** | The `center` token defines the coordinates of the center of the circle. |
| **2** | The `end` token defines the coordinates of the end of the radius of the circle. |
| **3** | The `layer` token defines the [canonical layer](#_canonical_layer_names) the circle resides on. |
| **4** | The `width` token defines the line width of the circle. (prior to version 7) |
| **5** | The [STROKE\_DEFINITION](#_stroke_definition) describes the line width and style of the circle. (from version 7) |
| **6** | The optional `fill` token defines if the circle is filled. If not defined, the circle is not filled. |
| **7** | The optional `locked` token defines if the circle cannot be edited. |
| **8** | The `uuid` token defines the unique identifier of the circle object. |

##### Footprint Arc

The `fp_arc` token defines a graphic arc in a [footprint definition](#_footprint).

```
    (fp_arc
      (start X Y)                                               (1)
      (mid X Y)                                                 (2)
      (end X Y)                                                 (3)
      (layer LAYER_DEFINITION)                                  (4)
      (width WIDTH)                                             (5)
      STROKE_DEFINITION                                         (6)
      [(locked)]                                                (7)
      (uuid UUID)                                               (8)
    )
```

|  |  |
| --- | --- |
| **1** | The `start` token defines the coordinates of the start position of the arc radius. |
| **2** | The `mid` token defines the coordinates of the midpoint along the arc. |
| **3** | The `end` token defines the coordinates of the end position of the arc radius. |
| **4** | The `layer` token defines the [canonical layer](#_canonical_layer_names) the arc resides on. |
| **5** | The `width` token defines the line width of the arc. (prior to version 7) |
| **6** | The [STROKE\_DEFINITION](#_stroke_definition) describes the line width and style of the arc. (from version 7) |
| **7** | The optional `locked` token defines if the arc cannot be edited. |
| **8** | The `uuid` token defines the unique identifier of the arc object. |

##### Footprint Polygon

The `fp_poly` token defines a graphic polygon in a [footprint definition](#_footprint).

```
    (fp_poly
      COORDINATE_POINT_LIST                                     (1)
      (layer LAYER_DEFINITION)                                  (2)
      (width WIDTH)                                             (3)
      STROKE_DEFINITION                                         (4)
      [(fill yes | no)]                                         (5)
      [(locked)]                                                (6)
      (uuid UUID)                                               (7)
    )
```

|  |  |
| --- | --- |
| **1** | The COORDINATE\_POINT\_LIST defines the list of [X/Y coordinates](#_coordinate_point_list) of the polygon outline. |
| **2** | The `layer` token defines the [canonical layer](#_canonical_layer_names) the polygon resides on. |
| **3** | The `width` token defines the line width of the polygon. (prior to version 7) |
| **4** | The [STROKE\_DEFINITION](#_stroke_definition) describes the line width and style of the polygon. (from version 7) |
| **5** | The optional `fill` token defines if the polygon is filled. If not defined, the polygon is not filled. |
| **6** | The optional `locked` token defines if the polygon cannot be edited. |
| **7** | The `uuid` token defines the unique identifier of the polygon object. |

##### Footprint Curve

The `fp_curve` token defines a graphic
[Cubic Bezier curve](https://en.wikipedia.org/wiki/B%C3%A9zier_curve#Quadratic_B%C3%A9zier_curves)
in a [footprint definition](#_footprint).

```
    (fp_curve
      COORDINATE_POINT_LIST                                     (1)
      (layer LAYER_DEFINITION)                                  (2)
      (width WIDTH)                                             (3)
      STROKE_DEFINITION                                         (4)
      [(locked)]                                                (5)
      (uuid UUID)                                               (6)
    )
```

|  |  |
| --- | --- |
| **1** | The COORDINATE\_POINT\_LIST defines the four [X/Y coordinates](#_coordinate_point_list) of each point of the curve. |
| **2** | The `layer` token defines the [canonical layer](#_canonical_layer_names) the curve resides on. |
| **3** | The `width` token defines the line width of the curve. (prior to version 7) |
| **4** | The [STROKE\_DEFINITION](#_stroke_definition) describes the line width and style of the curve. (from version 7) |
| **5** | The optional `locked` token defines if the curve cannot be edited. |
| **6** | The `uuid` token defines the unique identifier of the curve object. |

#### Footprint Pad

The `pad` token defines a pad in a [footprint definition](#_footprint).

```
    (pad
      "NUMBER"                                                  (1)
      TYPE                                                      (2)
      SHAPE                                                     (3)
      POSITION_IDENTIFIER                                       (4)
      [(locked)]                                                (5)
      (size X Y)                                                (6)
      [(drill DRILL_DEFINITION)]                                (7)
      (layers "CANONICAL_LAYER_LIST")                           (8)
      [(property PROPERTY)]                                     (9)
      [(remove_unused_layer)]                                   (10)
      [(keep_end_layers)]                                       (11)
      [(roundrect_rratio RATIO)]                                (12)
      [(chamfer_ratio RATIO)]                                   (13)
      [(chamfer CORNER_LIST)]                                   (14)
      (net NUMBER "NAME")                                       (15)
      (uuid UUID)                                               (16)
      [(pinfunction "PIN_FUNCTION")]                            (17)
      [(pintype "PIN_TYPE")]                                    (18)
      [(die_length LENGTH)]                                     (19)
      [(solder_mask_margin MARGIN)]                             (20)
      [(solder_paste_margin MARGIN)]                            (21)
      [(solder_paste_margin_ratio RATIO)]                       (22)
      [(clearance CLEARANCE)]                                   (23)
      [(zone_connect ZONE)]                                     (24)
      [(thermal_width WIDTH)]                                   (25)
      [(thermal_gap DISTANCE)]                                  (26)
      [CUSTOM_PAD_OPTIONS]                                      (27)
      [CUSTOM_PAD_PRIMITIVES]                                   (28)
    )
```

|  |  |
| --- | --- |
| **1** | The "NUMBER" attribute is the pad number. |
| **2** | The pad TYPE can be defined as `thru_hole`, `smd`, `connect`, or `np_thru_hole`. |
| **3** | The pad SHAPE can be defined as `circle`, `rect`, `oval`, `trapezoid`, `roundrect`, or `custom`. |
| **4** | The POSITION\_IDENTIFIER defines the [X and Y coordinates and optional orientation angle](#_position_identifier) of the pad. |
| **5** | The optional `locked` token defines if the footprint pad can be edited. |
| **6** | The `size` token defines the width and height of the pad. |
| **7** | The optional [pad DRILL\_DEFINITION](#_pad_drill_definition) defines the pad drill requirements. |
| **8** | The `layers` token defines the [layer or layers](#_layers) the pad reside on. |
| **9** | The optional `property` token defines any special properties for the pad. Valid properties are `pad_prop_bga`, `pad_prop_fiducial_glob`, `pad_prop_fiducial_loc`, `pad_prop_testpoint`, `pad_prop_heatsink`, `pad_prop_heatsink`, and `pad_prop_castellated`. |
| **10** | The optional `remove_unused_layer` token specifies that the copper should be removed from any layers the pad is not connected to. |
| **11** | The optional `keep_end_layers` token specifies that the top and bottom layers should be retained when removing the copper from unused layers. |
| **12** | The optional `roundrect_rratio` token defines the scaling factor of the pad to corner radius for rounded rectangular and chamfered corner rectangular pads. The scaling factor is a number between 0 and 1. |
| **13** | The optional `chamfer_ratio` token defines the scaling factor of the pad to chamfer size. The scaling factor is a number between 0 and 1. |
| **14** | The optional `chamfer` token defines a list of one or more rectangular pad corners that get chamfered. Valid chamfer corner attributes are `top_left`, `top_right`, `bottom_left`, and `bottom_right`. |
| **15** | The optional `net` token defines the integer number and name string of the net connection for the pad. |
| **16** | The `uuid` token defines the unique identifier of the pad object. |
| **17** | The optional `pinfunction` token attribute defines the associated schematic symbol pin name. |
| **18** | The optional `pintype` token attribute defines the associated schematic pin electrical type. |
| **19** | The optional `die_length` token attribute defines the die length between the component pad and physical chip inside the component package. |
| **20** | The optional `solder_mask_margin` token attribute defines the distance between the pad and the solder mask for the pad. If not set, the footprint `solder_mask_margin` is used. |
| **21** | The optional `solder_paste_margin` token attribute defines the distance the solder paste should be changed for the pad. |
| **22** | The optional `solder_paste_margin_ratio` token attribute defines the percentage to reduce the pad outline by to generate the solder paste size. |
| **23** | The optional `clearance` token attribute defines the clearance from all copper to the pad. If not set, the footprint `clearance` is used. |
| **24** | The optional `zone_connection` token attribute defines type of zone connect for the pad. If not defined, the footprint `zone_connection` setting is used. Valid connection types are integers values from 0 to 3 which defines: * 0 - Pad is not connect to zone. * 1 - Pad is connected to zone using thermal relief. * 2 - Pad is connected to zone using solid fill. |
| **25** | The optional `thermal_width` token attribute defines the thermal relief spoke width used for zone connection for the pad. This only affects a pad connected to a zone with a thermal relief. If not set, the footprint `thermal_width` setting is used. |
| **26** | The optional `thermal_gap` token attribute defines the distance from the pad to the zone of the thermal relief connection for the pad. This only affects a pad connected to a zone with a thermal relief. If not set, the footprint `thermal_gap` setting is used. |
| **27** | The optional [custom pad options](#_custom_pad_options) defines the options when a custom pad is defined. |
| **28** | The optional [custom pad primitives](#_custom_pad_primitives) defines the drawing objects and options used to define a custom pad. |

##### Pad Drill Definition

The `drill` token defines the drill attributes for a [footprint pad](#_footprint_pad).

```
      (drill
        [oval]                                                  (1)
        DIAMETER                                                (2)
        [WIDTH]                                                 (3)
        [(offset X Y)]                                          (4)
      )
```

|  |  |
| --- | --- |
| **1** | The optional `oval` token defines if the drill is oval instead of round. |
| **2** | The diameter attribute defines the drill diameter. |
| **3** | The optional width attribute defines the width of the slot for oval drills. |
| **4** | The optional `offset` token defines the drill offset coordinates from the center of the pad. |

##### Custom Pad Options

The optional `options` token attributes define the settings used for custom pads. This token
is only used when a [custom pad](#_footprint_pad) is defined.

```
      (options
        (clearance CLEARANCE_TYPE)                              (1)
        (anchor PAD_SHAPE)                                      (2)
      )
```

|  |  |
| --- | --- |
| **1** | The `clearance` token defines the type of clearance used for a custom pad. Valid clearance types are `outline` and `convexhull`. |
| **2** | The `anchor` token defines the anchor pad shape of a custom pad. Valid anchor pad shapes are `rect` and `circle`. |

##### Custom Pad Primitives

The optional `primitives` token defines a list of graphical items used to define the outline of
a custom pad shape. This token is only used when a [custom pad](#_footprint_pad) is defined.

```
      (primitives
        GRAPHIC_ITEMS...                                        (1)
        (width WIDTH)                                           (2)
        [(fill yes)]                                            (3)
      )
```

|  |  |
| --- | --- |
| **1** | The graphical items is a list of graphical [lines](#_graphical_line), [rectangles](#_graphical_rectangle), [arcs](#_graphical_arc), [circles](#_graphical_circle), [curves](#_graphical_curve), [polygons](#_graphical_polygon), and [annotation bounding boxes](#_annotation_bounding_box) that define the shape of the custom pad (annotation bounding boxes from version 7). The item definitions only include the geometrical information that defines the item. The annotation bounding box defines the location (and size) of the pad number and netname. |
| **2** | The `width` token defines the line width of the [graphical items](#_graphical_items_section). |
| **3** | The optional `fill` token attribute `yes` indicates the geometry defined by the [graphical items](#_graphical_items_section) should be filled. |

#### Footprint 3D Model

The `model` token defines the 3D model associated with a [footprint](#_footprint).

```
    (model
      "3D_MODEL_FILE"                                           (1)
      (at (xyz X Y Z))                                          (2)
      (scale (xyz X Y Z))                                       (3)
      (rotate (xyz X Y Z))                                      (4)
    )
```

|  |  |
| --- | --- |
| **1** | The 3D\_MODEL\_FILE attribute is the path and file name of the 3D model. |
| **2** | The `at` token specifies the 3D position coordinates of the model relative to the footprint. |
| **3** | The `scale` token specifies the model scale factor for each 3D axis. |
| **4** | The `rotate` token specifies the model rotation for each 3D axis relative to the footprint. |

### Graphic Items

The graphical items are footprint and board items that are outside of the connectivity
items. This includes graphical items on technical, user, and copper layers. Graphical
items are also used to define complex [pad](#_footprint_pad) geometries.

#### Graphical Text

The `gr_text` token defines graphical text.

```
  (gr_text
    "TEXT"                                                      (1)
    POSITION_INDENTIFIER                                        (2)
    (layer LAYER_DEFINITION [knockout])                         (3)
    (uuid UUID)                                                 (4)
    (effects TEXT_EFFECTS)                                      (5)
  )
```

|  |  |
| --- | --- |
| **1** | The "TEXT" attribute is a quoted string that defines the text. |
| **2** | The POSITION\_IDENTIFER defines the [X and Y coordinates and optional orientation angle](#_position_identifier) of the text. |
| **3** | The `layer` token defines the [canonical layer](#_canonical_layer_names) the text resides on. It is optionally followed by a `knockout` token indicating the text should be knocked out. |
| **4** | The `uuid` token defines the unique identifier of the text object. |
| **5** | The TEXT\_EFFECTS defines how the [text is displayed](#_text_effects). |

### Graphical Text Box

(from version 7)

The `gr_text_box` token defines a rectangle containing line-wrapped text.

```
  (gr_text_box
    [locked]                                                    (1)
    "TEXT"                                                      (2)
    [(start X Y)]                                               (3)
    [(end X Y)]                                                 (4)
    [(pts (xy X Y) (xy X Y) (xy X Y) (xy X Y))]                 (5)
    [(angle ROTATION)]                                          (6)
    (layer LAYER_DEFINITION)                                    (7)
    (uuid UUID)                                                 (8)
    TEXT_EFFECTS                                                (9)
    [STROKE_DEFINITION]                                         (10)
    [(render_cache RENDER_CACHE)]                               (11)
  )
```

|  |  |
| --- | --- |
| **1** | The optional `locked` token specifies if the text box can be moved. |
| **2** | The content of the text box |
| **3** | The `start` token defines the top-left of a cardinally oriented text box. |
| **4** | The `end` token defines the bottom-right of a cardinally oriented text box. |
| **5** | The `pts` token defines the four corners of a non-cardianlly oriented text box. The corners must be in order, but the winding can be either direction. |
| **6** | The optional `angle` token defines the rotation of the text box in degrees. |
| **7** | The `layer` token defines the [canonical layer](#_canonical_layer_names) the text box resides on. |
| **8** | The `uuid` token defines the unique identifier of the text box. |
| **9** | The [TEXT\_EFFECTS](#_text_effects) describe the style of the text in the text box. |
| **10** | The [STROKE\_DEFINITION](#_stroke_definition) describes the style of an optional border to be drawn around the text box. |
| **11** | If the `TEXT_EFFECTS` prescribe a TrueType font then a render cache should be given in case the font can not be found on the current system. |

|  |  |
| --- | --- |
|  | If `angle` is not given, or is a cardinal angle (0, 90, 180 or 270), then the text box MUST have `start` and `end` tokens. |

|  |  |
| --- | --- |
|  | If `angle` is given and is not a cardinal angle, then the text box MUST have a `pts` token (with 4 pts). |

#### Graphical Line

The `gr_line` token defines a graphical line.

```
  (gr_line
    (start X Y)                                                 (1)
    (end X Y)                                                   (2)
    [(angle ANGLE)]                                             (3)
    (layer LAYER_DEFINITION)                                    (4)
    (width WIDTH)                                               (5)
    (uuid UUID)                                                 (6)
  )
```

|  |  |
| --- | --- |
| **1** | The `start` token defines the coordinates of the beginning of the line. |
| **2** | The `end` token defines the coordinates of the end of the line. |
| **3** | The optional `angle` token defines the rotational angle of the line. |
| **4** | The `layer` token defines the [canonical layer](#_canonical_layer_names) the line resides on. |
| **5** | The `width` token defines the line width. |
| **6** | The `uuid` token defines the unique identifier of the line object. |

#### Graphical Rectangle

The `gr_rect` token defines a graphical rectangle.

```
  (gr_rect
    (start X Y)                                                 (1)
    (end X Y)                                                   (2)
    (layer LAYER_DEFINITION)                                    (3)
    (width WIDTH)                                               (4)
    [(fill yes | no)]                                           (5)
    (uuid UUID)                                                 (6)
  )
```

|  |  |
| --- | --- |
| **1** | The `start` token defines the coordinates of the upper left corner of the rectangle. |
| **2** | The `end` token defines the coordinates of the low right corner of the rectangle. |
| **3** | The `layer` token defines the [canonical layer](#_canonical_layer_names) the rectangle resides on. |
| **4** | The `width` token defines the line width of the rectangle. |
| **5** | The optional `fill` token defines how the rectangle is filled. If not defined, the rectangle is not filled. |
| **6** | The `uuid` token defines the unique identifier of the rectangle object. |

#### Graphical Circle

The `gr_circle` token defines a graphical circle.

```
  (gr_circle
    (center X Y)                                                (1)
    (end X Y)                                                   (2)
    (layer LAYER_DEFINITION)                                    (3)
    (width WIDTH)                                               (4)
    [(fill yes | no)]                                           (5)
    (uuid UUID)                                                 (6)
  )
```

|  |  |
| --- | --- |
| **1** | The `center` token defines the coordinates of the center of the circle. |
| **2** | The `end` token defines the coordinates of the end of the radius of the circle. |
| **3** | The `layer` token defines the [canonical layer](#_canonical_layer_names) the circle resides on. |
| **4** | The `width` token defines the line width of the circle. |
| **5** | The optional `fill` token defines how the circle is filled. If not defined, the circle is not filled. |
| **6** | The `uuid` token defines the unique identifier of the circle object. |

#### Graphical Arc

The `gr_arc` token defines a graphical arc.

```
  (gr_arc
    (start X Y)                                                 (1)
    (mid X Y)                                                   (2)
    (end X Y)                                                   (3)
    (layer LAYER_DEFINITION)                                    (4)
    (width WIDTH)                                               (5)
    (uuid UUID)                                                 (6)
  )
```

|  |  |
| --- | --- |
| **1** | The `start` token defines the coordinates of the start position of the arc radius. |
| **2** | The `mid` token defines the coordinates of the midpoint along the arc. |
| **3** | The `end` token defines the coordinates of the end position of the arc radius. |
| **4** | The `layer` token defines the [canonical layer](#_canonical_layer_names) the arc resides on. |
| **5** | The `width` token defines the line width of the arc. |
| **6** | The `uuid` token defines the unique identifier of the arc object. |

#### Graphical Polygon

The `gr_poly` token defines a graphical polygon.

```
  (gr_poly
    COORDINATE_POINT_LIST                                       (1)
    (layer LAYER_DEFINITION)                                    (2)
    (width WIDTH)                                               (3)
    [(fill yes | no)]                                           (4)
    (uuid UUID)                                                 (5)
  )
```

|  |  |
| --- | --- |
| **1** | The COORDINATE\_POINT\_LIST defines the list of [X/Y coordinates](#_coordinate_point_list) of the polygon outline. |
| **2** | The `layer` token defines the [canonical layer](#_canonical_layer_names) the polygon resides on. |
| **3** | The `width` token defines the line width of the polygon. |
| **4** | The optional `fill` token defines how the polygon is filled. If not defined, the polygon is not filled. |
| **5** | The `uuid` token defines the unique identifier of the polygon object. |

#### Graphical Curve

The `bezier` token defines a graphic
[Cubic Bezier curve](https://en.wikipedia.org/wiki/B%C3%A9zier_curve#Quadratic_B%C3%A9zier_curves).

```
  (bezier
    COORDINATE_POINT_LIST                                       (1)
    (layer LAYER_DEFINITION)                                    (2)
    (width WIDTH)                                               (3)
    (uuid UUID)                                                 (4)
  )
```

|  |  |
| --- | --- |
| **1** | The COORDINATE\_POINT\_LIST defines the list of [X/Y coordinates](#_coordinate_point_list) of the four pointS of the curve. |
| **2** | The `layer` token defines the [canonical layer](#_canonical_layer_names) the curve resides on. |
| **3** | The `width` token defines the line width of the curve. |
| **4** | The `uuid` token defines the unique identifier of the curve object. |

#### Annotation Bounding Box

(from version 7)

The `gr_bbox` token defines a bounding box inside which annotations (such as pad numbers
and netnames) will be shown.

```
  (gr_bbox
    (start X Y)                                                 (1)
    (end X Y)                                                   (2)
  )
```

|  |  |
| --- | --- |
| **1** | The `start` token defines the coordinates of the upper left corner of the rectangle. |
| **2** | The `end` token defines the coordinates of the low right corner of the rectangle. |

#### Dimension

The `dimension` token defines a dimension object.

```
  (dimension
    [locked]                                                    (1)
    (type DIMENSION_TYPE)                                       (2)
    (layer LAYER_DEFINITION)                                    (3)
    (uuid UUID)                                                 (4)
    (pts (xy X Y) (xy X Y))                                     (5)
    [(height HEIGHT)]                                           (6)
    [(orientation ORIENTATION)]                                 (7)
    [(leader_length LEADER_LENGTH)]                             (8)
    [(gr_text GRAPHICAL_TEXT)]                                  (9)
    [(format DIMENSION_FORMAT)]                                 (10)
    (style DIMENSION_STYLE)                                     (11)
  )
```

|  |  |
| --- | --- |
| **1** | The optional `locked` token specifies if the dimension can be moved. |
| **2** | The `type` token attribute defines the type of dimension. Valid dimension types are `aligned`, `leader`, `center`, `orthogonal`, and `radial` (`radial` from version 7). |
| **3** | The `layer` token defines the [canonical layer](../sexpr-intro/index.html#_canonical_layer_names) the polygon resides on. |
| **4** | The `uuid` token defines the unique identifier of the dimension object. |
| **5** | The `pts` token attributes define the list of `xy` coordinates of the dimension. |
| **6** | The optional `height` token attribute defines the height of aligned dimensions. |
| **7** | The optional `orientation` token attribute defines the rotation angle for orthogonal dimensions. |
| **8** | The optional `leader_length` token attribute defines the distance from the marked radius to the knee for radial dimensions. |
| **9** | The optional `gr_text` token attributes define the dimension text formatting for all dimension types except center dimensions. |
| **10** | The optional `format` token attributes define the [dimension formatting](#_dimension_format) for all dimension types except center dimensions. |
| **11** | The `style` token attributes define the [dimension style](#_dimension_style) information. |

##### Dimension Format

The `format` token attributes define the text formatting of the dimension.

```
    (format
      [(prefix "PREFIX")]                                       (1)
      [(suffix "SUFFIX")]                                       (2)
      (units UNITS)                                             (3)
      (units_format UNITS_FORMAT)                               (4)
      (precision PRECISION)                                     (5)
      [(override_value "VALUE")]                                (6)
      [(suppress_zeros yes | no)]                               (7)
    )
```

|  |  |
| --- | --- |
| **1** | The optional `prefix` token attribute defines the string to add to the beginning of the dimension text. |
| **2** | The optional `suffix` token attribute defines the string to add to the end of the dimension text. |
| **3** | The `units` token attribute defines the dimension units used to display the dimension text. Valid units are as follows: * 0 - Inches. * 1 - Mils. * 2 - Millimeters. * 3 - Automatic. |
| **4** | The `units_format` token attribute defines how the unit’s suffix is formatted. Valid units formats are as follows: * 0 - No suffix. * 1 - Bare suffix. * 2 - Wrap suffix in parenthesis. |
| **5** | The `precision` token attribute defines the number of significant digits to display. From version 7, a `precision` above 5 indicates a units-scaled precision: * 6 - 0.00 in / 0 mils / 0.0 mm * 7 - 0.000 in / 0 mils / 0.00 mm * 8 - 0.0000 in / 0.0 mils / 0.000mm * 9 - 0.00000 in / 0.00 mils / 0.0000mm |
| **6** | The optional `override_value` token attribute defines the text to substitute for the actual physical dimension. |
| **7** | The optional `suppress_zeros` token removes all trailing zeros from the dimension text. The only valid attributes are `yes` and `no`. |

##### Dimension Style

```
    (style
      (thickness THICKNESS)                                     (1)
      (arrow_length LENGTH)                                     (2)
      (text_position_mode MODE)                                 (3)
      [(arrow_direction DIRECTION)]                             (4)
      [(extension_height HEIGHT)]                               (5)
      [(text_frame TEXT_FRAME_TYPE)]                            (6)
      [(extension_offset OFFSET)]                               (7)
      [(keep_text_aligned yes | no)]                            (8)
    )
```

|  |  |
| --- | --- |
| **1** | The `thickness` token attribute defines the line thickness of the dimension. |
| **2** | The `arrow_length` token attribute defines the length of the dimension arrows. |
| **3** | The `text_position_mode` token attribute defines the position mode of the dimension text. Valid position modes are as follows: * 0 - Text is outside the dimension line. * 1 - Text is in line with the dimension line. * 2 - Text has been manually placed by the user. |
| **4** | The `arrow_direction` token attribute defines the direction of the dimension arrows. Only `aligned` and `orthogonal` dimensions support this attribute. Valid directions are as follows: * `outward`: The arrows face outward, pointing away from midpoint of the crossbar. * `inward`: The arrows face inward, pointing towards the midpoint of the crossbar. |
| **5** | The optional `extension_height` token attribute defines the length of the extension lines past the dimension crossbar. |
| **6** | The optional `text_frame` token attribute defines the style of the frame around the dimension text. This only applies to `leader` dimensions. Valid text frames are as follows: * 0 - No text frame. * 1 - Rectangle. * 2 - Circle. * 3 - Rounded rectangle. |
| **7** | The optional `extension_offset` token attribute defines the distance from feature points to extension line start. |
| **8** | The optional `keep_text_aligned` token indicates that the dimension text should be kept in line with the dimension crossbar. When not defined, the dimension text is shown horizontally regardless of the orientation of the dimension. |

### Zone

The `zone` token defines a zone on the board or footprint. Zones serve two purposes in KiCad:
filled copper zones and keep out areas.

```
  (zone
    (net NET_NUMBER)                                            (1)
    (net_name "NET_NAME")                                       (2)
    (layer LAYER_DEFINITION)                                    (3)
    (uuid UUID)                                                 (4)
    [(name "NAME")]                                             (5)
    (hatch STYLE PITCH)                                         (6)
    [(priority PRIORITY)]                                       (7)
    (connect_pads [CONNECTION_TYPE] (clearance CLEARANCE))      (8)
    (min_thickness THICKNESS)                                   (9)
    [(filled_areas_thickness no)]                               (10)
    [ZONE_KEEPOUT_SETTINGS]                                     (11)
    ZONE_FILL_SETTINGS                                          (12)
    (polygon COORDINATE_POINT_LIST)                             (13)
    [ZONE_FILL_POLYGONS...]                                     (14)
    [ZONE_FILL_SEGMENTS...]                                     (15)
  )
```

|  |  |
| --- | --- |
| **1** | The `net` token attribute defines by the net ordinal number which net in the [nets section](../sexpr-pcb/index.html#_nets_section) that the zone is part of. |
| **2** | The `net_name` token attribute defines the [name of the net](../sexpr-pcb/index.html#_nets_section) if the zone is not a keep out area. The net name attribute will be an empty string if the zone is a keep out area. |
| **3** | The `layer` token defines the [canonical layer](#_canonical_layer_names) the zone resides on. |
| **4** | The `uuid` token defines the unique identifier of the zone object. |
| **5** | The optional `name` token attribute defines the name of the zone if one has been assigned. |
| **6** | The `hatch` token attributes define the zone outline display hatch style and pitch. Valid hatch styles are `none`, `edge`, and `full`. |
| **7** | The optional `priority` attribute defines the zone priority if it is not zero. |
| **8** | The `connect_pads` token attributes define the pad connection type and clearance. Valid pad connection types are `thru_hole_only`, `full`, and `no`. If the pad connection type is not defined, thermal relief pad connections are used. |
| **9** | The `min_thickness` token attributed defines the minimum fill width allowed in the zone. |
| **10** | The optional `filled_areas_thickness` attribute `no` specifies if the zone like width is not used when determining the zone fill area. This is to maintain compatibility with older board files that included the line thickness when performing zone fills when it is not defined. |
| **11** | The optional [zone keep out settings](#_zone_keep_out_settings) section defines the keep out items if the zone defines as a keep out area. |
| **12** | The [zone fill settings section](#_zone_fill_settings) defines how the zone is to be filled. * 0 - All footprint pads are not connect to zone. * 1 - All footprint pads are connected to zone using thermal relief. * 2 - All footprint pads are connected to zone using solid fill. * 3 - Only footprint through hole pads are connected to zone using thermal relief. Surface   mount pads are connected using solid fill. |
| **13** | The `polygon` token attribute defines the COORDINATE\_POINT\_LIST of [X/Y coordinates](#_coordinate_point_list) of corner points of the polygon outline. the corners of the zone outline polygon. |
| **14** | The optional [zone fill polygons section](#_zone_fill_polygons) defines all of the polygons used to fill the zone. This section will not exist if the zone has not been filled or is filled with segments. |
| **15** | The optional [zone fill segments section](#_zone_fill_segments) defines a list of track segments used to fill the zone. This is only used when boards prior to version 4 of KiCad are loaded. |

#### Zone Keep Out Settings

The optional `keepout` token attributes define which objects should be kept out of the zone. This
section only applies to keep out zones.

```
    (keepout
      (tracks KEEPOUT)                                          (1)
      (vias KEEPOUT)                                            (2)
      (pads KEEPOUT)                                            (3)
      (copperpour KEEPOUT)                                      (4)
      (footprints KEEPOUT)                                      (5)
    )
```

|  |  |
| --- | --- |
| **1** | The `tracks` token attribute defines whether or not tracks should be excluded from the keep out area. Valid attributes are `allowed` and `not_allowed`. |
| **2** | The `vias` token attribute defines whether or not vias should be excluded from the keep out area. Valid attributes are `allowed` and `not_allowed`. |
| **3** | The `pads` token attribute defines whether or not pads should be excluded from the keep out area. Valid attributes are `allowed` and `not_allowed`. |
| **4** | The `copperpour` token attribute defines whether or not copper pours should be excluded from the keep out area. Valid attributes are `allowed` and `not_allowed`. |
| **5** | The `footprints` token attribute defines whether or not footprints should be excluded from the keep out area. Valid attributes are `allowed` and `not_allowed`. |

#### Zone Fill Settings

The `fill` token attributes define how the zone is to be filled.

```
    (fill
      [yes]                                                     (1)
      [(mode FILL_MODE)]                                        (2)
      (thermal_gap GAP)                                         (3)
      (thermal_bridge_width WIDTH)                              (4)
      [(smoothing STYLE)]                                       (5)
      [(radius RADIUS)]                                         (6)
      [(island_removal_mode MODE)]                              (7)
      [(island_area_min AREA)]                                  (8)
      [(hatch_thickness THICKNESS)]                             (9)
      [(hatch_gap GAP)]                                         (10)
      [(hatch_orientation ORIENTATION)]                         (11)
      [(hatch_smoothing_level LEVEL)]                           (12)
      [(hatch_smoothing_value VALUE)]                           (13)
      [(hatch_border_algorithm TYPE)]                           (14)
      [(hatch_min_hole_area AREA)]                              (15)
    )
```

|  |  |
| --- | --- |
| **1** | The `yes` token specifies if the zone should be filled. If not specified, the zone is not filled and no additional attributes are required. |
| **2** | The optional `mode` token attribute defines how the zone is filled. The only valid fill mode is `hatched`. When not defined, the fill mode is solid. |
| **3** | The optional `thermal_gap` token attribute defines the distance from the zone to all pad thermal relief connections to the zone. |
| **4** | The optional `thermal_bridge_width` token attribute defines the spoke width for all pad thermal relief connection to the zone. |
| **5** | The optional `smoothing` token attributes define the style of corner smoothing. Valid smoothing styles are `chamfer` and `fillet`. |
| **6** | The optional `radius` token defines the radius of the corner smoothing. |
| **7** | The optional `island_removal_mode` token attribute defines the island removal mode. Valid island removal modes are: * 0 - Always remove islands. * 1 - Never remove islands. * 2 - Minimum area island to allow. |
| **8** | The optional `island_area_min` token attribute defines the minimum allowable zone island. This only valid when the remove islands mode is set to 2. |
| **9** | The optional `hatch_thickness` token attribute defines the thickness for hatched fills. |
| **10** | The optional `hatch_gap` token attribute defines the distance between lines for hatched fills. |
| **11** | The optional `hatch_orientation` token attribute defines the line angle for hatched fills. |
| **12** | The optional `hatch_smoothing_level` token attribute defines how hatch outlines are smoothed. Valid hatch smoothing levels are: * 0 - No smoothing. * 1 - Fillet. * 2 - Arc minimum. * 3 - Arc maximum. |
| **13** | The optional `hatch_smoothing_value` token attribute defines the ratio between the hole and the chamfer/fillet size. |
| **14** | The optional `hatch_border_algorithm` token attribute defines the if the zone line thickness is used when performing a hatch fill. Valid values for the hatch border algorithm are: * 0 - Use zone minimum thickness. * 1 - Use hatch thickness. |
| **15** | The optional `hatch_min_hole_area` token attribute defines the minimum area a hatch file hole can be. |

#### Zone Fill Polygons

The `filled_polygon` token defines the polygons used to fill the zone. This token will not exist
if the zone has not been filled.

```
    (filled_polygon
      (layer LAYER_DEFINITION)                                  (1)
      COORDINATE_POINT_LIST                                     (2)
    )
```

|  |  |
| --- | --- |
| **1** | The `layer` token attribute defines the [canonical layer](#_canonical_layer_names) the zone fill resides on. |
| **2** | The COORDINATE\_POINT\_LIST defines the list of polygon [X/Y coordinates](#_coordinate_point_list) used to fill the zone. |

#### Zone Fill Segments

The `filled_segments` token defines the segments used to fill the zone. This is only used when
loading boards prior to version 4 which filled zones with segments. Once the zone has been
refilled, it will be filled with polygons and this token will not exist.

```
    (fill_segments
      (layer LAYER_DEFINITION)                                  (1)
      COORDINATED_POINT_LIST                                    (2)
    )
```

|  |  |
| --- | --- |
| **1** | The `layer` token attribute defines the [canonical layer](#_canonical_layer_names) the zone fill resides on. |
| **2** | The COORDINATE\_POINT\_LIST defines the list of [X and Y coordinates](#_coordinate_point_list) of the segments used to fill the zone. |

## Group

The `group` token defines a group of items.

```
  (group
    "NAME"                                                      (1)
    (id UUID)                                                   (2)
    (members UUID1 ... UUIDN)                                   (3)
  )
```

|  |  |
| --- | --- |
| **1** | The name attribute defines the name of the group. |
| **2** | The `id` token attribute defines the unique identifier of the group. |
| **3** | The `members` token attributes define a list of unique identifiers of the objects belonging to the group. |

## Schematic and Symbol Library Common Syntax

This section defines all syntax that is shared across the symbol library and schematic file
formats.

### Schematic Coordinates

* The minimum internal unit for schematic and symbol library files is one nanometer so there is
  maximum resolution of four decimal places or 0.0001 mm. Any precision beyond four places will
  be truncated.

### Symbol Unit Identifier

Symbol unit identifiers define how symbol units are identified. The unit identifier is a quoted
string have the format "NAME\_UNIT\_STYLE". "NAME" is the parent symbol name. "UNIT" is an integer
that identifies which unit the symbol represents. A "UNIT" value of zero (0) indicates that the
symbol is common to all units. The "STYLE" indicates which body style the unit represents.

|  |  |
| --- | --- |
|  | This identifier is a temporary solution until the full symbol inheritance model is implemented. |

|  |  |
| --- | --- |
|  | KiCad only supports two body styles so the only valid values for the "STYLE" are 1 and 2. |

### Fill Definition

The `fill` token defines how schematic and symbol library graphical items are filled.

```
  (fill
    (type none | outline | background)                          (1)
  )
```

|  |  |
| --- | --- |
| **1** | The `fill` token attributes define how the arc is filled. The table below describes the fill type modes. |

The table below defines the schematic and symbol graphical object fill modes.

| Token | Description |
| --- | --- |
| none | Graphic item not filled. |
| outline | Graphic item filled with the line color. |
| background | Graphic filled with the theme background color. |

### Symbols

The `symbol` token defines a symbol or sub-unit of a parent symbol. There can be zero or more
`symbol` tokens in a symbol library file.

```
  (symbol
    "LIBRARY_ID" | "UNIT_ID"                                    (1)
    [(extends "LIBRARY_ID")]                                    (2)
    [(pin_numbers hide)]                                        (3)
    [(pin_names [(offset OFFSET)] hide)]                        (4)
    (in_bom yes | no)                                           (5)
    (on_board yes | no)                                         (6)
    SYMBOL_PROPERTIES...                                        (7)
    GRAPHIC_ITEMS...                                            (8)
    PINS...                                                     (9)
    UNITS...                                                    (10)
    [(unit_name "UNIT_NAME")]                                   (11)
  )
```

|  |  |
| --- | --- |
| **1** | Each symbol must have a unique ["LIBRARY\_ID"](#_library_identifier) for each top level symbol in the library or a unique ["UNIT\_ID"](#_symbol_unit_identifier) for each unit embedded in a parent symbol. Library identifiers are only valid it top level symbols and unit identifiers are on valid as unit symbols inside a parent symbol. |
| **2** | The optional `extends` token attribute defines the ["LIBRARY\_ID"](#_library_identifier) of another symbol inside the current library from which to derive a new symbol. Extended symbols currently can only have different [SYMBOL\_PROPERTIES](#_symbol_properties) than their parent symbol. |
| **3** | The optional `pin_numbers` token defines the visibility setting of the symbol pin numbers for the entire symbol. If not defined, the all of the pin numbers in the symbol are visible. |
| **4** | The optional `pin_names` token defines the attributes for all of the pin names of the symbol. The optional `offset` token defines the pin name offset for all pin names of the symbol. If not defined, the pin name offset is 0.508mm (0.020"). If the `pin_name` token is not defined, the all symbol pins are shown with the default offset. |
| **5** | The `in_bom` token, defines if a symbol is to be include in the bill of material output. The only valid attributes are yes and no. |
| **6** | The `on_board` token, defines if a symbol is to be exported from the schematic to the printed circuit board. The only valid attributes are yes and no. |
| **7** | The [SYMBOL\_PROPERTIES](#_symbol_properties) is a list of properties that define the symbol. The following properties are mandatory when defining a parent symbol: "Reference", "Value", "Footprint", and "Datasheet". All other properties are optional. Unit symbols cannot have any properties. |
| **8** | The [GRAPHIC ITEMS](#_symbol_graphic_items) section is list of graphical arcs, circles, curves, lines, polygons, rectangles and text that define the symbol drawing. This section can be empty if the symbol has no graphical items. |
| **9** | The [PINS](#_symbol_pin) section is a list of pins that are used by the symbol. This section can be empty if the symbol does not have any pins. |
| **10** | The optional UNITS can be one or more child `symbol` tokens embedded in a parent `symbol`. |
| **11** | The optional `unit_name` token defines the display name of a subunit in the symbol editor and symbol chooser. It is only permitted for child `symbol` tokens embedded in a parent `symbol`. |

#### Symbol Properties

The `property` token defines a symbol property when used inside a `symbol` definition.

|  |  |
| --- | --- |
|  | Symbol properties are different than [general purpose properties](#_properties) defined above. |

```
    (property
      "KEY"                                                     (1)
      "VALUE"                                                   (2)
      (id N)                                                    (3)
      POSITION_IDENTIFIER                                       (4)
      TEXT_EFFECTS                                              (5)
    }
```

|  |  |
| --- | --- |
| **1** | The "KEY" string defines the name of the property and must be unique. |
| **2** | The "VALUE" string defines the value of the property. |
| **3** | The `id` token defines an integer ID for the property and must be unique. |
| **4** | The POSITION\_IDENTIFIER defines the [X and Y coordinates and rotation angle](#_position_identifier) of the property. |
| **5** | The TEXT\_EFFECTS section defines how the [text is displayed](#_text_effects). |

##### Mandatory Symbol Properties

The table below defines the mandatory properties for parent symbols.

Table 1. Mandatory Properties

| Key | Ordinal | Description | Empty Allowed |
| --- | --- | --- | --- |
| Reference | 0 | Symbol reference designator | No |
| Value | 1 | Symbol value string | No |
| Footprint | 2 | Symbol footprint [library identifier](#_library_identifier) | Yes |
| Datasheet | 3 | Symbol datasheet link | Yes |

##### Reserved Symbol Property Keys

The list below is the list of property keys reserve by KiCad and cannot be user for user defined
properties.

* `ki_keywords`
* `ki_description`
* `ki_locked`
* `ki_fp_filters`

#### Symbol Graphic Items

This section documents the various graphical objects used in symbol definitions.

#### Symbol Arc

The `arc` token defines a graphical arc in a symbol definition.

```
  (arc
    (start X Y)                                                 (1)
    (mid X Y)                                                   (2)
    (end X Y)                                                   (3)
    STROKE_DEFINITION                                           (4)
    FILL_DEFINITION                                             (5)
  )
```

|  |  |
| --- | --- |
| **1** | The `start` token defines the coordinates of start point of the arc. |
| **2** | The `mid` token defines the coordinates of mid point of the arc. |
| **3** | The `end` token defines the coordinates of end point of the arc. |
| **4** | The STROKE\_DEFINITION defines how the arc [outline is drawn](#_stroke_definition). |
| **5** | The `fill` token attributes define how the arc is [filled](#_fill_definition). |

#### Symbol Circle

The `circle` token defines a graphical circle in a symbol definition.

```
  (circle
    (center X Y)                                                (1)
    (radius RADIUS)                                             (2)
    STROKE_DEFINITION                                           (3)
    FILL_DEFINITION                                             (4)
  )
```

|  |  |
| --- | --- |
| **1** | The `center` token defines the coordinates of center point of the circle. |
| **2** | The radius token defines the length of the radius of the circle. |
| **3** | The STROKE\_DEFINITION defines how the circle [outline is drawn](#_stroke_definition). |
| **4** | The FILL\_DEFINTION defines how the circle is [filled](#_fill_definition). |

#### Symbol Curve

The `bezier` token defines a graphical .
[Qubic Bezier curve](https://en.wikipedia.org/wiki/B%C3%A9zier_curve#Quadratic_B%C3%A9zier_curves).

```
  (bezier
    COORDINATE_POINT_LIST                                       (1)
    STROKE_DEFINITION                                           (2)
    FILL_DEFINITION                                             (3)
  )
```

|  |  |
| --- | --- |
| **1** | The COORDINATE\_POINT\_LIST defines the four [X/Y coordinates](#_coordinate_point_list) of each point of the curve. |
| **2** | The STROKE\_DEFINITION defines how the curve [outline is drawn](#_stroke_definition). |
| **3** | The FILL\_DEFINTION defines how the curve is [filled](#_fill_definition). |

#### Symbol Line

The `polyline` token defines one or more graphical lines that may or may not define a polygon.

```
  (polyline
    COORDINATE_POINT_LIST                                       (1)
    STROKE_DEFINITION                                           (2)
    FILL_DEFINITION                                             (3)
  )
```

|  |  |
| --- | --- |
| **1** | The COORDINATE\_POINT\_LIST defines the list of [X/Y coordinates](#_coordinate_point_list) of the line(s). There must be a minimum of two points. |
| **2** | The STROKE\_DEFINITION defines how the polygon formed by the lines [outline is drawn](#_stroke_definition). |
| **3** | The `fill` token attributes define how the polygon formed by the lines is [filled](#_fill_definition). |

#### Symbol Rectangle

The `rectangle` token defines a graphical rectangle in a symbol definition.

```
  (rectangle
    (start X Y)                                                 (1)
    (end X Y)                                                   (2)
    STROKE_DEFINITION                                           (3)
    FILL_DEFINITION                                             (4)
  )
```

|  |  |
| --- | --- |
| **1** | The `start` token attributes define the coordinates of the start point of the rectangle. |
| **2** | The `end` token attributes define the coordinates of the end point of the rectangle. |
| **3** | The STROKE\_DEFINITION defines how the rectangle [outline is drawn](#_stroke_definition). |
| **4** | The FILL\_DEFINTION defines how the rectangle is [filled](#_fill_definition). |

#### Symbol Text

The `text` token defines graphical text in a symbol definition.

```
  (text
    "TEXT"                                                      (1)
    POSITION_IDENTIFIER                                         (2)
    (effects TEXT_EFFECTS)                                      (3)
  )
```

|  |  |
| --- | --- |
| **1** | The "TEXT" attribute is a quoted string that defines the text. |
| **2** | The POSITION\_IDENTIFIER defines the [X and Y coordinates and rotation angle](#_position_identifier) of the text. |
| **3** | The TEXT\_EFFECTS defines how the [text is displayed](#_text_effects). |

#### Symbol Pin

The `pin` token defines a pin in a symbol definition.

```
  (pin
    PIN_ELECTRICAL_TYPE                                         (1)
    PIN_GRAPHIC_STYLE                                           (2)
    POSITION_IDENTIFIER                                         (3)
    (length LENGTH)                                             (4)
    (name "NAME" TEXT_EFFECTS)                                  (5)
    (number "NUMBER" TEXT_EFFECTS)                              (6)
  )
```

|  |  |
| --- | --- |
| **1** | The PIN\_ELECTRICAL\_TYPE defines the pin electrical connection. See table below for valid pin electrical connection types and descriptions. |
| **2** | The PIN\_GRAPHICAL\_STYLE defines the graphical style used to draw the pin. See table below for valid pin graphical styles and descriptions. |
| **3** | The POSITION\_IDENTIFIER defines the [X and Y coordinates and rotation angle](#_position_identifier) of the connection point of the pin relative to the symbol origin position. The only supported rotation angles for pins are 0, 90, 180, and 270 degrees. |
| **4** | The `length` token attribute defines the LENGTH of the pin. |
| **5** | The `name` token defines a quoted string containing the NAME of the pin and the TEXT\_EFFECTS defines how the [text is displayed](#_text_effects). |
| **6** | The `number` token defines a quoted string containing the NUMBER of the pin and the TEXT\_EFFECTS defines how the [text is displayed](#_text_effects). |

The table below defines the pin electrical types.

| Token | Description |
| --- | --- |
| input | Pin is an input. |
| output | Pin is an output. |
| bidirectional | Pin can be both input and output. |
| tri\_state | Pin is a tri-state output. |
| passive | Pin is electrically passive. |
| free | Not internally connected. |
| unspecified | Pin does not have a specified electrical type. |
| power\_in | Pin is a power input. |
| power\_out | Pin is a power output. |
| open\_collector | Pin is an open collector output. |
| open\_emitter | Pin is an open emitter output. |
| no\_connect | Pin has no electrical connection. |

The table below defines the pin graphical styles.

| Token | Pin Image |
| --- | --- |
| line | ![images/pinshape_normal_16](images/pinshape_normal_16.png) |
| inverted | ![images/pinshape_invert_16](images/pinshape_invert_16.png) |
| clock | ![images/pinshape_clock_normal_16](images/pinshape_clock_normal_16.png) |
| inverted\_clock | ![images/pinshape_clock_invert_16](images/pinshape_clock_invert_16.png) |
| input\_low | ![images/pinshape_active_low_input_16](images/pinshape_active_low_input_16.png) |
| clock\_low | ![images/pinshape_clock_active_low_16](images/pinshape_clock_active_low_16.png) |
| output\_low | ![images/pinshape_active_low_output_16](images/pinshape_active_low_output_16.png) |
| edge\_clock\_high | ![images/pinshape_clock_fall_16](images/pinshape_clock_fall_16.png) |
| non\_logic | ![images/pinshape_nonlogic_16](images/pinshape_nonlogic_16.png) |

 Last Modified 2024-11-04

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