"""Compare every matching LTspice ASC file pair across two directories in parallel."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import subprocess
import sys
import time


_SCRIPT_PATH = Path(__file__).with_name("ltspice_asc_structure_cmp.py")


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare every matching LTspice .asc file pair across two directories in parallel.",
    )
    parser.add_argument(
        "first_dir",
        help="Directory containing the first set of .asc files.",
    )
    parser.add_argument(
        "second_dir",
        help="Directory containing the second set of .asc files.",
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
        "--timeout",
        type=float,
        default=600,
        help="Maximum seconds allowed for each comparison. Default: 600.",
    )
    return parser


def _comparison_command(
    first_path: Path,
    second_path: Path,
    arguments: argparse.Namespace,
) -> list[str]:
    command = [
        sys.executable,
        str(_SCRIPT_PATH),
        str(first_path),
        str(second_path),
        "--ltspice-windows-path",
        arguments.ltspice_windows_path,
        "--ltspice-wine-path",
        arguments.ltspice_wine_path,
        "--custom-search-paths",
    ]
    command.extend(arguments.custom_search_paths)
    return command


def _compare_one(
    first_path: Path,
    second_path: Path,
    arguments: argparse.Namespace,
) -> tuple[str, int | None, float, str]:
    started_at = time.perf_counter()
    try:
        completed = subprocess.run(
            _comparison_command(first_path, second_path, arguments),
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
            first_path.name,
            None,
            time.perf_counter() - started_at,
            f"timed out after {arguments.timeout:g} seconds"
            + (f"\n{diagnostics}" if diagnostics else ""),
        )

    diagnostics = "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
    )
    return (
        first_path.name,
        completed.returncode,
        time.perf_counter() - started_at,
        diagnostics,
    )


def main() -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args()

    first_dir = Path(arguments.first_dir)
    second_dir = Path(arguments.second_dir)

    if not first_dir.is_dir():
        print(f"{first_dir}: not a directory", file=sys.stderr)
        return 1
    if not second_dir.is_dir():
        print(f"{second_dir}: not a directory", file=sys.stderr)
        return 1

    first_stems: dict[str, Path] = {}
    for asc_path in sorted(first_dir.rglob("*.asc")):
        first_stems[asc_path.stem] = asc_path

    second_stems: dict[str, Path] = {}
    for asc_path in sorted(second_dir.rglob("*.asc")):
        second_stems[asc_path.stem] = asc_path

    common_stems = sorted(set(first_stems.keys()) & set(second_stems.keys()))

    if not common_stems:
        print("No matching .asc filenames found across the two directories.", file=sys.stderr)
        first_only = sorted(set(first_stems.keys()) - set(second_stems.keys()))
        second_only = sorted(set(second_stems.keys()) - set(first_stems.keys()))
        if first_only:
            print(f"Only in {first_dir}: {', '.join(first_only)}", file=sys.stderr)
        if second_only:
            print(f"Only in {second_dir}: {', '.join(second_only)}", file=sys.stderr)
        return 1

    jobs = [(first_stems[stem], second_stems[stem]) for stem in common_stems]

    exit_code = 0
    matched = 0
    mismatched = 0
    errors = 0
    started_at = time.perf_counter()
    worker_count = os.cpu_count() or 1

    print(
        f"Comparing {len(jobs)} matching .asc pair(s) with "
        f"{worker_count} worker(s); timeout per comparison: {arguments.timeout:g} seconds.",
        flush=True,
    )

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(_compare_one, first_path, second_path, arguments): first_path.stem
            for first_path, second_path in jobs
        }
        for future in as_completed(futures):
            stem = futures[future]
            try:
                name, returncode, elapsed, diagnostics = future.result()
            except (OSError, subprocess.SubprocessError) as error:
                print(f"[ERROR] {name}: {error}", file=sys.stderr, flush=True)
                errors += 1
                exit_code = 1
                continue

            if returncode is None:
                print(
                    f"[TIMEOUT] {name}: {diagnostics} "
                    f"(elapsed {elapsed:.2f}s)",
                    file=sys.stderr,
                    flush=True,
                )
                errors += 1
                exit_code = 1
            elif returncode == 0:
                print(f"[MATCH]  {name} (elapsed {elapsed:.2f}s)", flush=True)
                matched += 1
                if diagnostics:
                    print(f"  {diagnostics}", file=sys.stderr)
            else:
                print(f"[MISMATCH] {name} (elapsed {elapsed:.2f}s)", flush=True)
                mismatched += 1
                exit_code = 1
                if diagnostics:
                    print(f"  {diagnostics}", file=sys.stderr)

    total_elapsed = time.perf_counter() - started_at
    print(
        f"\nResults: {matched} match(es), {mismatched} mismatch(es), "
        f"{errors} error(s) in {total_elapsed:.2f}s",
        flush=True,
    )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
