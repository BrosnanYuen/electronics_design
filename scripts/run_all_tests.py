"""Run unit tests and integration tests sequentially for this project."""  # Describe the script purpose.

from __future__ import annotations  # Keep annotations lazy and consistent with the package code.

from pathlib import Path  # Resolve the repository root and the src directory.
import sys  # Exit with a non-zero code when a test suite fails.
import unittest  # Use the standard library test loader and runner.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[1]  # Resolve the project root from the script location.
_SOURCE_DIRECTORY = _ROOT_DIRECTORY / "src"  # Resolve the source directory that contains the package.

if str(_SOURCE_DIRECTORY) not in sys.path:  # Ensure the package source directory is importable when the script runs directly.
    sys.path.insert(0, str(_SOURCE_DIRECTORY))  # Prepend the source directory so local package imports resolve correctly.


def _run_suite(start_directory: str, label: str) -> bool:  # Discover and run one test suite tree.
    loader = unittest.TestLoader()  # Create a unittest loader for discovery.
    suite = loader.discover(start_dir=start_directory)  # Discover tests under the requested directory.
    runner = unittest.TextTestRunner(verbosity=2)  # Use a verbose runner so failures are easy to inspect.
    print(f"\nRunning {label} tests from {start_directory}\n")  # Print a clear banner before the suite starts.
    result = runner.run(suite)  # Execute the discovered test suite.
    if not result.wasSuccessful():  # Stop the overall run when the suite reports any failure or error.
        return False  # Signal suite failure to the caller.
    return True  # Signal suite success to the caller.


def main() -> int:  # Run the project test suites in the requested sequential order.
    unit_result = _run_suite("tests/unit", "unit")  # Run the unit tests first.
    if not unit_result:  # Stop immediately if unit tests fail.
        return 1  # Return a non-zero exit code for failure.
    integration_result = _run_suite("tests/integration", "integration")  # Run the integration tests second.
    if not integration_result:  # Stop when integration tests fail.
        return 1  # Return a non-zero exit code for failure.
    return 0  # Return success when all suites pass.


if __name__ == "__main__":  # Execute the main entry point only when run as a script.
    raise SystemExit(main())  # Exit the process using the computed return code.
