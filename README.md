# Hanly

Hanly is a Korean OCR popup-dictionary desktop app under active development.

The repository currently contains the minimal Python package foundation:

- `packages/hanly` is the reusable engine distribution and imports as `hanly`.
- `packages/hanly-app` is the desktop distribution and imports as `hanly_app`.

The desktop package depends on the engine; the engine remains independent of the desktop package.

Install development tools and both packages from the repository root:

```bash
python -m pip install --upgrade pip
python -m pip install --group dev
python -m pip install --editable packages/hanly
python -m pip install --editable packages/hanly-app
```

Run the local quality gates:

```bash
python -m pytest
python -m ruff check benchmarks packages packaging tests tools
python -m mypy benchmarks packages packaging tests tools
```

After installing the desktop runtime, `hanly run` opens a session-only capture
selector (whole monitor or a dragged region) and then starts the same Hanly
desktop composition. The ordinary `hanly-desktop` entry point remains the
direct app launch.
