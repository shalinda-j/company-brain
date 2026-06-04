# Contributing to Company Brain

Thanks for your interest in improving Company Brain! Contributions of all kinds
are welcome — bug reports, docs, tests, and features.

## Development setup

```bash
git clone https://github.com/USERNAME/company-brain
cd company-brain
python -m venv venv && . venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"     # ruff + pytest, plus the `brain` / `brain-mcp` commands
```

## Run the checks

The CI runs exactly these three commands — run them locally before pushing:

```bash
ruff check .            # lint
ruff format --check .   # formatting
pytest                  # tests (offline; uses a fake embedder, no model download)
```

`make check` runs all three.

## Code style

- Formatting and linting are handled by [ruff](https://docs.astral.sh/ruff/)
  (config in `pyproject.toml`). Run `ruff format .` to auto-format.
- Keep functions small and readable; prefer clear names over comments.
- Type hints are encouraged.

## Tests

- Tests live in `tests/` and run fully offline using `tests/_fake.py`
  (`FakeEmbedder`), so no embedding model is downloaded in CI.
- Add or update tests for any behavioural change.
- The fixtures in `tests/conftest.py` give you an isolated `brain` instance or
  an authenticated API `client`.

## Pull requests

1. Fork and create a topic branch.
2. Make your change with tests and docs.
3. Ensure `make check` passes.
4. Update `CHANGELOG.md` under "Unreleased" if user-facing.
5. Open a PR using the template.

## Reporting security issues

Please **do not** open a public issue. See [SECURITY.md](SECURITY.md).

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
