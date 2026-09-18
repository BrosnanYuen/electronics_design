"""Shared discovery, lookup, and pin validation for LTspice ``.asy`` symbols.

Every converter that needs to locate an LTspice symbol or check its
``SpiceOrder`` coverage consumes this module so the search rules stay in one
place.  The configured search roots are walked once and cached as a
``{lowercase key: filepath}`` mapping keyed by relative path, filename, and
stem, which makes nested layouts such as ``lib/sym/PowerProducts/LTC3895.asy``
resolve without extra configuration.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path
import threading
from typing import Dict
from typing import List
from typing import Mapping
from typing import Optional
from typing import Sequence
from typing import Set
from typing import Tuple

ASYRecord = Tuple[str, str, str, str]  # filepath, relative path, filename, stem

_NC_NODE_PREFIXES = ("NC", "NC_", "NC-")  # Mirror the netlist validator's no-connect conventions.
_ASY_LOOKUP_CACHE: Dict[Tuple[str, ...], Dict[str, str]] = {}  # Cache path lookups by search-root tuple.
_ASY_LOOKUP_LOCK = threading.Lock()  # Guard the process-level path-lookup cache.


def resolve_search_roots(convert_settings: Mapping[str, object]) -> Tuple[str, ...]:
    """Return the configured LTspice search roots in priority order."""

    custom_paths = _normalize_custom_search_paths(convert_settings.get("custom_search_paths", ()))
    wine_path = _normalize_install_path(convert_settings.get("ltspice_wine_path", ""))
    windows_path = _normalize_install_path(convert_settings.get("ltspice_windows_path", ""))
    search_roots: List[str] = []
    for candidate_path in (*custom_paths, wine_path, windows_path):
        if candidate_path == "" or candidate_path in search_roots:
            continue
        search_roots.append(candidate_path)
    return tuple(search_roots)


def discover_asy_records_for_root(symbol_root: str) -> List[ASYRecord]:
    """Collect every ``.asy`` record below one search root deterministically."""

    if not os.path.isdir(symbol_root):
        return []
    records: List[ASYRecord] = []
    for symbol_path in sorted(Path(symbol_root).rglob("*.asy")):
        records.append(
            (
                str(symbol_path),
                symbol_path.relative_to(symbol_root).as_posix(),
                symbol_path.name,
                symbol_path.stem,
            )
        )
    return records


def discover_asy_records(search_roots: Sequence[str]) -> List[ASYRecord]:
    """Collect every ``.asy`` record below the given search roots."""

    records: List[ASYRecord] = []
    for symbol_root in search_roots:
        records.extend(discover_asy_records_for_root(symbol_root))
    return records


def build_asy_filepath_lookup(search_roots: Sequence[str]) -> Dict[str, str]:
    """Build (and cache) the lowercase-keyed ``.asy`` filepath lookup for roots."""

    cache_key = tuple(search_roots)
    with _ASY_LOOKUP_LOCK:
        cached_lookup = _ASY_LOOKUP_CACHE.get(cache_key)
    if cached_lookup is not None:
        return cached_lookup
    lookup: Dict[str, str] = {}
    for filepath, relative_path, filename, stem in discover_asy_records(search_roots):
        lookup.setdefault(relative_path.lower(), filepath)
        lookup.setdefault(filename.lower(), filepath)
        lookup.setdefault(stem.lower(), filepath)
    with _ASY_LOOKUP_LOCK:
        return _ASY_LOOKUP_CACHE.setdefault(cache_key, lookup)


def resolve_asy_filepath(asy_name: str, symbol_paths: Mapping[str, str]) -> Optional[str]:
    """Resolve one symbol reference against a lowercase-keyed path lookup."""

    normalized_name = _normalize_asy_reference(asy_name)
    if normalized_name == "":
        return None
    basename = normalized_name.split("/")[-1]
    stem = basename[:-4] if basename.endswith(".asy") else basename
    for lookup_key in (normalized_name, f"{normalized_name}.asy", basename, f"{basename}.asy", stem):
        resolved_path = symbol_paths.get(lookup_key)
        if resolved_path is not None:
            return resolved_path
    return None


def find_asy_file(asy_name: str, convert_settings: Mapping[str, object]) -> Optional[str]:
    """Search the configured roots recursively for one ``.asy`` reference."""

    search_roots = resolve_search_roots(convert_settings)
    return resolve_asy_filepath(asy_name, build_asy_filepath_lookup(search_roots))


def describe_asy_search(
    asy_names: Sequence[str],
    convert_settings: Mapping[str, object],
) -> Tuple[List[str], List[Tuple[str, List[str]]]]:
    """Report the roots and the concrete conventional paths searched for names."""

    search_roots = list(resolve_search_roots(convert_settings))
    attempts: List[Tuple[str, List[str]]] = []
    for search_root in search_roots:
        candidates = [
            os.path.join(search_root, asy_name) for asy_name in asy_names
        ] + [
            os.path.join(search_root, "sym", asy_name) for asy_name in asy_names
        ] + [
            os.path.join(search_root, "lib", "sym", asy_name) for asy_name in asy_names
        ]
        attempts.append((search_root, candidates))
    return search_roots, attempts


def suggest_asy_search_paths(
    asy_names: Sequence[str],
    convert_settings: Mapping[str, object],
    limit: int = 3,
) -> List[str]:
    """Suggest directories holding symbols with the same or a close stem."""

    search_roots = resolve_search_roots(convert_settings)
    stem_by_path: Dict[str, str] = {}
    for filepath, _relative_path, _filename, stem in discover_asy_records(search_roots):
        stem_by_path.setdefault(stem.lower(), filepath)
    suggestions: List[str] = []
    for asy_name in asy_names:
        normalized_name = _normalize_asy_reference(asy_name)
        basename = normalized_name.split("/")[-1]
        stem = basename[:-4] if basename.endswith(".asy") else basename
        closest_path = stem_by_path.get(stem)
        if closest_path is None:
            close_stems = difflib.get_close_matches(stem, list(stem_by_path), n=1, cutoff=0.7)
            closest_path = stem_by_path[close_stems[0]] if close_stems else None
        if closest_path is None:
            continue
        directory = os.path.dirname(closest_path)
        if directory and directory not in suggestions:
            suggestions.append(directory)
        if len(suggestions) >= limit:
            break
    return suggestions


def validate_x_pin_coverage(
    instance_name: str,
    nodes: Sequence[str],
    spice_orders: Sequence[int],
    node_devices: Mapping[str, Set[str]],
) -> Optional[str]:
    """Return an ``X_PIN_COUNT_MISMATCH`` detail when an X line cannot map."""

    node_count = len(nodes)
    covered: Set[int] = set()
    for spice_order in spice_orders:
        if spice_order < 1 or spice_order > node_count:
            return (
                f"X_PIN_COUNT_MISMATCH: pin SpiceOrder {spice_order} of device '{instance_name}' "
                f"is outside the {node_count}-node X line"
            )
        covered.add(spice_order)
    for position, node in enumerate(nodes, start=1):
        if position in covered:
            continue
        node_name = str(node)
        if node_name.upper().startswith(_NC_NODE_PREFIXES):
            continue
        if node_devices.get(node_name, set()) - {instance_name}:
            return (
                f"X_PIN_COUNT_MISMATCH: node '{node_name}' at position {position} of device "
                f"'{instance_name}' has no matching SpiceOrder pin but is a connected net"
            )
    return None


def build_node_device_index(device_nodes: Sequence[Tuple[str, Sequence[str]]]) -> Dict[str, Set[str]]:
    """Index every node name onto the device instances that reference it."""

    node_devices: Dict[str, Set[str]] = {}
    for instance_name, nodes in device_nodes:
        for node in nodes:
            node_devices.setdefault(str(node), set()).add(instance_name)
    return node_devices


def _normalize_asy_reference(asy_name: str) -> str:
    try:
        path_string = os.fspath(asy_name)
    except TypeError:
        return ""
    return path_string.replace("\\", "/").strip().lstrip("./").lower()


def _normalize_custom_search_paths(value: object) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, os.PathLike)):
        normalized_path = _normalize_search_path(value)
        return (normalized_path,) if normalized_path != "" else ()
    try:
        values = tuple(value)
    except TypeError:
        return ()
    return tuple(
        normalized_path
        for normalized_path in (_normalize_search_path(item) for item in values)
        if normalized_path != ""
    )


def _normalize_search_path(value: object) -> str:
    try:
        path_string = os.fspath(value).strip()
    except TypeError:
        return ""
    if path_string == "":
        return ""
    return os.path.expanduser(path_string)


def _normalize_install_path(value: object) -> str:
    normalized_path = _normalize_search_path(value)
    if normalized_path == "":
        return ""
    return os.path.expanduser(normalized_path.replace("\\", "/"))
