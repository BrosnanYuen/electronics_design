* [Introduction](#_introduction)
  + [Work Sheet Coordinates](#_work_sheet_coordinates)
  + [Object Incrementing](#_object_incrementing)
* [Layout](#_layout)
* [Header Section](#_header_section)
* [Set Up Section](#_set_up_section)
* [Drawing Object Section](#_drawing_object_section)
  + [Title Block Text](#_title_block_text)
  + [Graphical Line](#_graphical_line)
  + [Graphical Rectangle](#_graphical_rectangle)
  + [Graphical Polygon](#_graphical_polygon)
  + [Image](#_image)

1. [File Formats](/en/file-formats/index.html) >
2. Work Sheet File Format

# Work Sheet File Format

## Introduction

This documents the s-expression work sheet file format for all versions of KiCad from 6.0.
Work sheet files are used to change the default border and title block for schematics and
boards.

* Work sheet files use the `.kicad_wks` extension.

### Work Sheet Coordinates

* The minimum internal unit for work sheet files is 1 micrometer so there is maximum resolution
  of three decimal places or 0.001 mm. Any precision beyond three places will be truncated.

### Object Incrementing

All graphical objects can be drawn multiple times with a given repeat count and X and/or Y
incremental distances. The direction of the increment is controlled by defining a start
corner and/or end corner depending on the graphical object type. The table below defines
the corner tokens and their meaning.

| Token | Description |
| --- | --- |
| ltcorner | Top left corner of the start or end point. |
| lbcorner | Bottom left corner of the start or end point. |
| rbcorner | Bottom right corner of the start or end point. |
| rtcorner | Top right corner of the start or end point. |

## Layout

A work sheet file includes the following sections:

* [Header](#_header_section)
* [Set Up Section](#_set_up_section)
* [Drawing Object Section](#_drawing_object_section)

## Header Section

The `kicad_wks` token indicates that it is KiCad work sheet file. This section is required.

|  |  |
| --- | --- |
|  | Third party scripts should not use `pl_editor` as the generator identifier. Please use some other identifier so that bugs introduced by third party generators are not confused with a work sheet file created by KiCad. |

```
(kicad_wks
  (version VERSION)                                             (1)
  (generator GENERATOR)                                         (2)

  ;; contents of the schematic file...                          (3)
)
```

|  |  |
| --- | --- |
| **1** | The `version` token attribute defines the work sheet version using the YYYYMMDD date format. |
| **2** | The `generator` token attribute defines the program used to write the file. |
| **3** | The work sheet sections go here. |

## Set Up Section

The `setup` token defines the configuration information for the work sheet.

```
  (setup
    (textsize WIDTH HEIGHT)                                     (1)
    (linewidth WIDTH)                                           (2)
    (textlinewidth WIDTH)                                       (3)
    (left_margin DISTANCE)                                      (4)
    (right_margin DISTANCE)                                     (5)
    (top_margin DISTANCE)                                       (6)
    (bottom_margin DISTANCE)                                    (7)
  )
```

|  |  |
| --- | --- |
| **1** | The `textsize` token attributes define the default WIDTH and HEIGHT of text. |
| **2** | The `linewidth` token attribute defines the default WIDTH of lines. |
| **3** | The `textlinewidth` token attribute define the default WIDTH of the lines used to draw text. |
| **4** | The `left_margin` token attributed defines the DISTANCE from the left edge of the page. |
| **5** | The `right_margin` token attributed defines the DISTANCE from the right edge of the page. |
| **6** | The `top_margin` token attributed defines the DISTANCE from the top edge of the page. |
| **7** | The `bottom_margin` token attributed defines the DISTANCE from the bottom edge of the page. |

## Drawing Object Section

The drawing object section can contain zero or more [title block text](#_title_block_text),
[graphical line](#_graphical_line), [graphical rectangle](#_graphical_rectangle),
[graphical polygon](#_graphical_polygon), or [image](#_image). The objects are ordered
as they are added to the work sheet.

### Title Block Text

The `tbtext` token attributes define text used in the title block of a work sheet.

```
  (tbtext
    "TEXT"                                                      (1)
    (name "NAME")                                               (2)
    (pos X Y [CORNER])                                          (3)
    (font [(size WIDTH HEIGHT)] [bold] [italic])                (4)
    [(repeat COUNT)]                                            (5)
    [(incrx DISTANCE)]                                          (6)
    [(incry DISTANCE)]                                          (7)
    [(comment "COMMENT")]                                       (8)
  )
```

|  |  |
| --- | --- |
| **1** | The `tbtext` token attribute defines the TEXT string. |
| **2** | The `name` token attribute defines the NAME of the text object. |
| **3** | The `pos` token attributes define the X and Y coordinates the text. The optional CORNER attribute is used to define the [initial corner](#_object_incrementing) for repeating incremental text. |
| **4** | The `font` token attributes define how the text is drawn. The optional `size` token attributes define the size of the font used to draw the text. If not defined, the default text size defined in the [set up section](#_set_up_section) is used. The optional `bold` token indicates the text be drawn with a bold font. The optional `italic` token indicates the text be drawn italicized. |
| **5** | The optional `repeat` token attribute defines the COUNT for repeated incremental text. |
| **6** | The optional `incrx` token attribute defines the repeat DISTANCE on the X axis. |
| **7** | The optional `incry` token attribute defines the repeat DISTANCE on the Y axis. |
| **8** | The optional `comment` token attribute is a comment for the text object. |

### Graphical Line

The `line` token attributes define how a line is drawn in the work sheet.

```
  (line
    (name "NAME")                                               (1)
    (start X Y [CORNER])                                        (2)
    (end X Y [CORNER])                                          (3)
    [(repeat COUNT)]                                            (4)
    [(incrx DISTANCE)]                                          (5)
    [(incry DISTANCE)]                                          (6)
    [(comment "COMMENT")]                                       (7)
  )
```

|  |  |
| --- | --- |
| **1** | The `name` token attribute defines the NAME of the line object. |
| **2** | The `start` token attributes define the X and Y coordinates of the start point of the line. The optional CORNER attribute defines the [initial corner](#_object_incrementing) for repeating incremental lines. |
| **3** | The `end` token attributes define the X and Y coordinates of the end point of the line. The optional CORNER attribute defines the [end corner](#_object_incrementing) for repeating incremental lines. |
| **4** | The optional `repeat` token attribute defines the COUNT for repeated incremental lines. |
| **5** | The optional `incrx` token attribute defines the repeat DISTANCE on the X axis. |
| **6** | The optional `incry` token attribute defines the repeat DISTANCE on the Y axis. |
| **7** | The optional `comment` token attribute is a comment for the line object. |

### Graphical Rectangle

The `rect` token attributes define how a rectangle is drawn in the work sheet.

```
  (rect
    (name "NAME")                                               (1)
    (start X Y [CORNER])                                        (2)
    (end X Y [CORNER])                                          (3)
    [(repeat COUNT)]                                            (4)
    [(incrx DISTANCE)]                                          (5)
    [(incry DISTANCE)]                                          (6)
    [(comment "COMMENT")]                                       (7)
  )
```

|  |  |
| --- | --- |
| **1** | The `name` token attribute defines the NAME of the rectangle object. |
| **2** | The `start` token attributes define the X and Y coordinates of the start point of the rectangle. The optional CORNER attribute defines the [initial corner](#_object_incrementing) for repeating incremental rectangles. |
| **3** | The `end` token attributes define the X and Y coordinates of the end point of the rectangle. The optional CORNER attribute defines the [end corner](#_object_incrementing) for repeating incremental rectangles. |
| **4** | The optional `repeat` token attribute defines the COUNT for repeated incremental rectangles. |
| **5** | The optional `incrx` token attribute defines the repeat DISTANCE on the X axis. |
| **6** | The optional `incry` token attribute defines the repeat DISTANCE on the Y axis. |
| **7** | The optional `comment` token attribute is a comment for the rectangle object. |

### Graphical Polygon

The `polygon` token defines a graphical polygon. This section will not exist if there are no
polygons in the work sheet.

```
  (polygon
    (name "NAME")                                               (1)
    (pos X Y [CORNER])                                          (2)
    [(rotate ANGLE)]                                            (3)
    [(linewidth WIDTH)]                                         (4)
    COORDINATE_POINT_LIST                                       (5)
    [(repeat COUNT)]                                            (6)
    [(incrx DISTANCE)]                                          (7)
    [(incry DISTANCE)]                                          (8)
    [(comment "COMMENT")]                                       (9)
  )
```

|  |  |
| --- | --- |
| **1** | The `name` token attribute defines the NAME of the polygon object. |
| **2** | The `pos` token attributes define the X and Y coordinates the text. The optional CORNER attribute is used to define the [initial corner](#_object_incrementing) for repeating incremental polygons. |
| **3** | The optional `rotate` token attribute defines the rotation angle of the polygon object. |
| **4** | The optional `linewidth` token attribute defines the width of all of the polygons. If not defined, the default line width in the [set up section](#_set_up_section) is used. |
| **5** | The COORDINATE\_POINT\_LIST defines the list of [X/Y coordinates](../sexpr-intro/index.html#_coordinate_point_list) of to draw line(s) between. A minimum of two points is required. |
| **6** | The optional `repeat` token attribute defines the COUNT for repeated incremental polygons. |
| **7** | The optional `incrx` token attribute defines the repeat DISTANCE on the X axis. |
| **8** | The optional `incry` token attribute defines the repeat DISTANCE on the Y axis. |
| **9** | The optional `comment` token attribute is a comment for the polygon object. |

### Image

The `image` token defines one or more embedded images. This section will not exist if no images
are in the work sheet.

```
  (bitmap
    (name "NAME")                                               (1)
    (pos X Y )                                                  (2)
    (scale SCALAR)                                              (3)
    [(repeat COUNT)]                                            (4)
    [(incrx DISTANCE)]                                          (5)
    [(incry DISTANCE)]                                          (6)
    [(comment "COMMENT")]                                       (7)
    (pngdata IMAGE_DATA)                                        (8)
  )
```

|  |  |
| --- | --- |
| **1** | The `name` toke attribute defines the NAME of the image. |
| **2** | The `pos` token attributes define the X and Y coordinates of the image. The optional CORNER attribute defines the [start corner](#_object_incrementing) for repeating incremental images. |
| **3** | The `scale` token attribute defines the SCALE\_FACTOR of the image. |
| **4** | The optional `repeat` token attribute defines the COUNT for repeated incremental image. |
| **5** | The optional `incrx` token attribute defines the repeat DISTANCE on the X axis. |
| **6** | The optional `incry` token attribute defines the repeat DISTANCE on the Y axis. |
| **7** | The optional `comment` token attribute is a comment for the image object. |
| **8** | The `pngdata` token attribute defines the [IMAGE\_DATA](#_image_data) in the [portable network graphics format (PNG)](https://en.wikipedia.org/wiki/Portable_Network_Graphics). |

#### Image Data

The `data` token defines the raw image data.

```
  (data XX1 ... XXN )                                           (1)
  ...
```

|  |  |
| --- | --- |
| **1** | The `data` token attributes define the hexadecimal byte data separated by a space. A maximum of 32 bytes will be defined for each `data` token. The `data` tokens are defined until all of the image data is defined. |

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