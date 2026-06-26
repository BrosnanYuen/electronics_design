# Submission Guide

## 1. Verify The Project

Run all tests:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

or run the sequential test script:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_all_tests.py
```

Confirm the required runtime dependency is installed:

```bash
.venv/bin/python -m pip install "networkx>=3.6.1" "schemdraw>=0.23" "matplotlib>=3.11.0"
```

## 2. Build The Distribution

Install build tools if needed:

```bash
.venv/bin/python -m pip install --upgrade build twine
```

Create source and wheel distributions:

```bash
.venv/bin/python -m build
```

Expected outputs are created in `dist/`.

## 3. Validate The Distributions

Check the generated files before upload:

```bash
.venv/bin/python -m twine check dist/*
```

## 4. Upload To PyPI

Upload to the real PyPI index:

```bash
.venv/bin/python -m twine upload dist/*
```

Upload to TestPyPI first if you want a dry run:

```bash
.venv/bin/python -m twine upload --repository testpypi dist/*
```

## 5. Release Checklist

- Update the version in `pyproject.toml`
- Run the full test suite
- Confirm the `networkx`, `schemdraw`, and `matplotlib` dependencies are declared and installed
- Build the package
- Run `twine check`
- Upload the package
- Confirm the published project metadata and README rendering on PyPI
