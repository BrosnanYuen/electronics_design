* [Introduction](#_introduction)
* [Layout](#_layout)
* [Header Section](#_header_section)
* [Footprint Section](#_footprint_section)

1. [File Formats](/en/file-formats/index.html) >
2. Footprint Library File Format

# Footprint Library File Format

## Introduction

This documents the s-expression footprint library file format for all versions of KiCad from 6.0.

* Footprint library files use the `.kicad_mod` extension.
* Footprint library files can only define a single footprint.
* Footprint libraries are defined a folder containing one or more footprint library files.

|  |  |
| --- | --- |
|  | This file format was introduced with the launch of KiCad 4.0. |

|  |  |
| --- | --- |
|  | Prior to version 6 of KiCad, strings were only quoted when necessary. Saving an older board file to the latest file format will result in these strings being quoted even though there is no functional change in the board itself. |

## Layout

A footprint library file includes the following sections:

* [Header](#_header_section)
* [Footprint Definition](#_footprint_section)

## Header Section

The `footprint` token indicates that it is KiCad footprint library file. This section is required.

|  |  |
| --- | --- |
|  | Third party scripts should not use `pcbnew` as the generator identifier. Please use some other identifier so that bugs introduced by third party generators are not confused with a footprint library file created by KiCad. |

```
(footprint "NAME"                                               (1)
  (version VERSION)                                             (2)
  (generator GENERATOR)                                         (3)

  ;; contents of the footprint library file...                  (4)
)
```

|  |  |
| --- | --- |
| **1** | The footprint `NAME` is a quoted string that defines the name of the footprint. |
| **2** | The `version` token attribute defines the board version using the YYYYMMDD date format. |
| **3** | The `generator` token attribute defines the program used to write the file. |
| **4** | The footprint definition goes here. |

## Footprint Section

See the [footprint](../sexpr-intro/index.html#_footprint) in the s-expression board common
definitions.

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