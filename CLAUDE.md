# shiva

Mass SSH client (CLI Tool profile). Rules: `.specify/memory/constitution.md`.

- `src/shiva/cli.py` argparse and exit codes; `runner.py` ssh and the remote script;
  `hosts.py` host sources; `katello.py` Katello API; `config.py` shiva.conf and env;
  `report.py` human, JSON and mail output.
- Gates: `uv run ruff check src tests && uv run mypy src && uv run pytest -v`.
- Never put user input on the ssh command line; it goes in the stdin script.
- Release: bump `version` in `pyproject.toml`, `src/shiva/__init__.py` and the
  Containerfile label, add a CHANGELOG entry, tag `vX.Y.Z`. CI builds and pushes.
