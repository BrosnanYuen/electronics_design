"""Compatibility wrapper for the split LTspice validation modules."""  # Preserve the legacy module path used by tests and callers.

from __future__ import annotations  # Keep annotations lazy and consistent with the package code.

import os  # Re-export the shared os module so existing test patches still apply.

from . import ltspice_asc as _asc  # Import the ASC-specific implementation module.
from . import ltspice_asc_plot_schemdraw as _asc_plot_schemdraw  # Import the dedicated ASC plotting module.
from . import ltspice_asc_to_netlist as _asc_to_netlist  # Import the ASC-to-netlist conversion module.
from . import ltspice_asy as _asy  # Import the ASY-specific implementation module.
from . import ltspice_net as _net  # Import the netlist-specific implementation module.
from . import pathtracing as _pathtracing  # Import the path tracing GUI module.

is_valid_ltspice_asc_header = _asc.is_valid_ltspice_asc_header  # Re-export the ASC header validator.
is_valid_ltspice_asc_spacing = _asc.is_valid_ltspice_asc_spacing  # Re-export the ASC spacing validator.
is_valid_ltspice_asc_footer = _asc.is_valid_ltspice_asc_footer  # Re-export the ASC footer validator.
is_valid_ltspice_asc_file = _asc.is_valid_ltspice_asc_file  # Re-export the ASC whole-file validator.
ltspice_asc_plot_schemdraw = _asc_plot_schemdraw.ltspice_asc_plot_schemdraw  # Re-export the schemdraw schematic plotting helper.
ltspice_asc_to_netlist = _asc_to_netlist.ltspice_asc_to_netlist  # Re-export the ASC-to-netlist conversion helper.
ltspice_asc_structure_cmp = _asc_to_netlist.ltspice_asc_structure_cmp  # Re-export the ASC structural comparison helper.
get_ltspice_asc_symbol_info = _asc_to_netlist.get_ltspice_asc_symbol_info  # Re-export the ASC symbol-info helper.
is_valid_ltspice_asy = _asy.is_valid_ltspice_asy  # Re-export the ASY validator.
get_ltspice_asy_size = _asy.get_ltspice_asy_size  # Re-export the ASY size helper.
get_ltspice_asy_pins = _asy.get_ltspice_asy_pins  # Re-export the ASY pin extraction helper.
rectangle_points_to_lines = _asy.rectangle_points_to_lines  # Re-export the rectangle edge helper.

is_valid_ltspice_netlist_format = _net.is_valid_ltspice_netlist_format  # Re-export the netlist format validator.
is_valid_ltspice_netlist_footer = _net.is_valid_ltspice_netlist_footer  # Re-export the netlist footer validator.
is_ltspice_netlist_structure_connected = _net.is_ltspice_netlist_structure_connected  # Re-export the connectivity validator.
is_valid_ltspice_netlist_file = _net.is_valid_ltspice_netlist_file  # Re-export the netlist whole-file validator.
ltspice_netlist_plot_networkx = _net.ltspice_netlist_plot_networkx  # Re-export the network graph plotting helper.
ltspice_netlist_footer_cmp = _net.ltspice_netlist_footer_cmp  # Re-export the footer comparison helper.
ltspice_netlist_structure_cmp = _net.ltspice_netlist_structure_cmp  # Re-export the structural comparison helper.
gui_debug = _pathtracing.gui_debug  # Re-export the path tracing GUI helper.
find_wire_group_index = _pathtracing.find_wire_group_index  # Re-export the wire-group-index helper.
are_wires_intersecting_obstacles_detailed = _pathtracing.are_wires_intersecting_obstacles_detailed  # Re-export the detailed intersection helper.
place_wires_into_groups = _pathtracing.place_wires_into_groups  # Re-export the wire-grouping helper.

_classify_asc_line = _asc._classify_asc_line  # Re-export the ASC line classifier for focused tests.
_extract_asc_text_directive = _asc._extract_asc_text_directive  # Re-export the ASC directive extractor for focused tests.
_parse_directive_name = _net._parse_directive_name  # Re-export the directive parser for focused tests.
_strip_semicolon_comment = _net._strip_semicolon_comment  # Re-export the inline-comment stripper for focused tests.
_extract_nodes = _net._extract_nodes  # Re-export the node extractor for focused tests.
_is_exempt_node = _net._is_exempt_node  # Re-export the exempt-node helper for focused tests.

__all__ = [  # Publish the stable public API surface through the legacy wrapper.
    "is_valid_ltspice_asc_header",  # Export the ASC header validator.
    "is_valid_ltspice_asc_spacing",  # Export the ASC spacing validator.
    "is_valid_ltspice_asc_footer",  # Export the ASC footer validator.
    "is_valid_ltspice_asc_file",  # Export the ASC whole-file validator.
    "ltspice_asc_plot_schemdraw",  # Export the schemdraw schematic plotting helper.
    "ltspice_asc_to_netlist",  # Export the ASC-to-netlist conversion helper.
    "ltspice_asc_structure_cmp",  # Export the ASC structural comparison helper.
    "get_ltspice_asc_symbol_info",  # Export the ASC symbol-info helper.
    "is_valid_ltspice_asy",  # Export the ASY validator.
    "get_ltspice_asy_size",  # Export the ASY size helper.
    "get_ltspice_asy_pins",  # Export the ASY pin extraction helper.
    "rectangle_points_to_lines",  # Export the rectangle edge helper.
    "is_valid_ltspice_netlist_format",  # Export the netlist format validator.
    "is_valid_ltspice_netlist_footer",  # Export the netlist footer validator.
    "is_ltspice_netlist_structure_connected",  # Export the connectivity validator.
    "is_valid_ltspice_netlist_file",  # Export the netlist whole-file validator.
    "ltspice_netlist_plot_networkx",  # Export the network graph plotting helper.
    "ltspice_netlist_footer_cmp",  # Export the footer comparison helper.
    "ltspice_netlist_structure_cmp",  # Export the structural comparison helper.
    "gui_debug",  # Export the path tracing GUI helper.
    "find_wire_group_index",  # Export the wire-group-index helper.
    "are_wires_intersecting_obstacles_detailed",  # Export the detailed intersection helper.
    "place_wires_into_groups",  # Export the start/end position helper.
]  # Finish the public export list.
