# Contributing

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools
python -m pip install -e .
```

## Run tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Build a distribution

```bash
python -m pip install -e ".[dev]"
python -m build
```

## Before publishing

- bump the version in `pyproject.toml`
- run tests
- build the package locally
