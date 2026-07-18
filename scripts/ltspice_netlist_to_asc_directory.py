"""Convert every LTspice netlist in a directory tree to an ASC file in parallel."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import subprocess
import sys
import time


_SCRIPT_PATH = Path(__file__).with_name("ltspice_netlist_to_asc.py")


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert every LTspice .net file in a directory tree to .asc files in parallel.",
    )
    parser.add_argument(
        "directory",
        help="Directory to search recursively for LTspice .net files.",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Optional output directory. Defaults to writing each .asc beside its .net file.",
    )
    parser.add_argument(
        "--ltspice-windows-path",
        default="C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
        help="Windows-style LTspice root path used for symbol lookup.",
    )
    parser.add_argument(
        "--ltspice-wine-path",
        default="~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
        help="Local LTspice root path used at runtime to browse .asy and library files.",
    )
    parser.add_argument(
        "--custom-search-paths",
        nargs="*",
        default=["./valid_asy/"],
        help="Optional additional search paths for LTspice .asy and library files.",
    )
    parser.add_argument(
        "--minimum-dist",
        type=int,
        default=32,
        help="Minimum clearance distance around symbol rectangles. Default: 32.",
    )
    parser.add_argument(
        "--wire-pin-out-dist",
        type=int,
        default=16,
        help="Distance a wire exits a symbol pin before global routing. Default: 16.",
    )
    parser.add_argument(
        "--autoplace-iter",
        type=int,
        default=12,
        help="Number of autoplace optimization iterations. Default: 12.",
    )
    parser.add_argument(
        "--grid-size",
        type=int,
        default=16,
        help="Routing and placement grid spacing. Default: 16.",
    )
    parser.add_argument(
        "--ltspice-version",
        type=float,
        default=4.1,
        help="LTspice file format version used in generated ASC files. Default: 4.1.",
    )
    parser.add_argument(
        "--voltage-must-have-dc",
        action="store_true",
        help="Insert a zero DC value before AC-only voltage-source payloads.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600,
        help="Maximum seconds allowed for each conversion. Default: 600 (10 minutes).",
    )
    return parser


def _conversion_command(
    netlist_path: Path,
    output_path: Path,
    arguments: argparse.Namespace,
) -> list[str]:
    command = [
        sys.executable,
        str(_SCRIPT_PATH),
        str(netlist_path),
        "--out",
        str(output_path),
        "--ltspice-windows-path",
        arguments.ltspice_windows_path,
        "--ltspice-wine-path",
        arguments.ltspice_wine_path,
        "--minimum-dist",
        str(arguments.minimum_dist),
        "--wire-pin-out-dist",
        str(arguments.wire_pin_out_dist),
        "--autoplace-iter",
        str(arguments.autoplace_iter),
        "--grid-size",
        str(arguments.grid_size),
        "--ltspice-version",
        str(arguments.ltspice_version),
    ]
    if arguments.voltage_must_have_dc:
        command.append("--voltage-must-have-dc")
    command.append("--custom-search-paths")
    command.extend(arguments.custom_search_paths)
    return command


def _convert_one(
    netlist_path: Path,
    output_path: Path,
    arguments: argparse.Namespace,
) -> tuple[Path, int | None, float, str]:
    started_at = time.perf_counter()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            _conversion_command(netlist_path, output_path, arguments),
            cwd=_SCRIPT_PATH.parent.parent,
            capture_output=True,
            text=True,
            timeout=arguments.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        diagnostics = "\n".join(
            part.strip()
            for part in (error.stdout, error.stderr)
            if isinstance(part, str) and part.strip()
        )
        return (
            netlist_path,
            None,
            time.perf_counter() - started_at,
            f"timed out after {arguments.timeout:g} seconds"
            + (f"\n{diagnostics}" if diagnostics else ""),
        )

    diagnostics = "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
    )
    return (
        netlist_path,
        completed.returncode,
        time.perf_counter() - started_at,
        diagnostics,
    )


def main() -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args()

    directory_path = Path(arguments.directory)
    if not directory_path.is_dir():
        print(f"{arguments.directory}: not a directory", file=sys.stderr)
        return 1

    netlist_files = sorted(directory_path.rglob("*.net"))
    if not netlist_files:
        print(f"{arguments.directory}: no .net files found", file=sys.stderr)
        return 0

    output_dir = Path(arguments.out_dir) if arguments.out_dir is not None else None
    jobs = []
    for netlist_path in netlist_files:
        if output_dir is None:
            output_path = netlist_path.with_suffix(".asc")
        else:
            output_path = output_dir / netlist_path.relative_to(directory_path).with_suffix(".asc")
        jobs.append((netlist_path, output_path))

    exit_code = 0
    started_at = time.perf_counter()
    worker_count = os.cpu_count() or 1
    print(
        f"Starting conversion of {len(jobs)} .net file(s) with "
        f"{worker_count} worker(s); timeout per file: {arguments.timeout:g} seconds.",
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(_convert_one, netlist_path, output_path, arguments): netlist_path
            for netlist_path, output_path in jobs
        }
        for netlist_path in futures.values():
            print(f"[START] {netlist_path}", flush=True)
        for future in as_completed(futures):
            netlist_path = futures[future]
            try:
                _, returncode, elapsed, diagnostics = future.result()
            except (OSError, subprocess.SubprocessError) as error:
                print(f"[ERROR] {netlist_path}: {error}", file=sys.stderr, flush=True)
                exit_code = 1
                continue
            if returncode is None:
                print(
                    f"[TIMEOUT] {netlist_path.name}: {diagnostics} "
                    f"(elapsed {elapsed:.2f}s)",
                    file=sys.stderr,
                    flush=True,
                )
                exit_code = 1
            elif returncode != 0:
                print(
                    f"[ERROR] {netlist_path.name}: conversion failed "
                    f"(exit {returncode}, elapsed {elapsed:.2f}s)",
                    file=sys.stderr,
                    flush=True,
                )
                if diagnostics:
                    print(diagnostics, file=sys.stderr, flush=True)
                exit_code = 1
            else:
                print(
                    f"[FINISHED] {netlist_path.name}: converted successfully "
                    f"(elapsed {elapsed:.2f}s)",
                    flush=True,
                )

    total_elapsed = time.perf_counter() - started_at
    if exit_code == 0:
        print(f"Completed all conversions successfully in {total_elapsed:.2f}s.", flush=True)
    else:
        print(f"Completed with errors in {total_elapsed:.2f}s.", file=sys.stderr, flush=True)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
