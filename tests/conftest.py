from __future__ import annotations

import io
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep the developer's config, env file, agent and Katello out of every test."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("KATELLO_URL", "KATELLO_USERNAME", "KATELLO_PASSWORD", "KATELLO_PASSWORD_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("shiva.config.CONFIG_SEARCH_PATH", (home / ".config/shiva/shiva.conf",))
    monkeypatch.setattr("shiva.config.ENV_FILE", home / ".config/mcp-env/shiva.env")
    monkeypatch.setattr("shiva.cli.load_keychain_agent", lambda: None)
    return home


@pytest.fixture
def groups(tmp_path: Path) -> Path:
    directory = tmp_path / "groups"
    directory.mkdir()
    (directory / "default").write_text("alpha\nbeta\n")
    (directory / "web").write_text("# web tier\nweb1\nweb2  # primary\n\nweb1\n")
    return directory


@pytest.fixture
def config_file(tmp_path: Path, groups: Path) -> Path:
    path = tmp_path / "shiva.conf"
    path.write_text(f'group_files="{groups}"\nmax_slots=4\nemail_address=""\n')
    return path


@dataclass
class FakeSSH:
    """Stands in for subprocess.run; answers per host from a table."""

    answers: dict[str, tuple[int, str, str]] = field(default_factory=dict)
    calls: list[tuple[list[str], str]] = field(default_factory=list)
    hang: set[str] = field(default_factory=set)

    def __call__(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        host = argv[argv.index("--") + 1]
        script = str(kwargs["input"])
        self.calls.append((argv, script))
        if host in self.hang:
            raise subprocess.TimeoutExpired(argv, float(str(kwargs["timeout"])), b"partial\n")
        code, out, err = self.answers.get(host, (0, f"hello from {host}\n", ""))
        return subprocess.CompletedProcess(argv, code, out, err)


@pytest.fixture
def fake_ssh(monkeypatch: pytest.MonkeyPatch) -> FakeSSH:
    fake = FakeSSH()
    monkeypatch.setattr("shiva.runner.subprocess.run", fake)
    return fake


class TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def stdin(monkeypatch: pytest.MonkeyPatch) -> Callable[[str, bool], None]:
    def set_stdin(text: str = "", tty: bool = True) -> None:
        monkeypatch.setattr("sys.stdin", TTY(text) if tty else io.StringIO(text))

    set_stdin()
    return set_stdin
