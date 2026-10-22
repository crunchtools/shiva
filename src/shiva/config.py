"""Configuration: shiva.conf, the mcp-env file, and credentials."""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

CONFIG_SEARCH_PATH = (
    Path("~/.config/shiva/shiva.conf"),
    Path("/usr/local/etc/shiva.conf"),
    Path("/etc/shiva.conf"),
)
ENV_FILE = Path("~/.config/mcp-env/shiva.env")
TRUE_VALUES = {"1", "true", "yes", "on"}


class ConfigError(Exception):
    """Raised for a missing or malformed configuration. Maps to exit code 2."""


@dataclass
class Config:
    group_files: Path = Path("/usr/local/etc/shiva")
    max_slots: int = 10
    ssh_timeout: int = 10
    command_timeout: int = 0
    accept_new_keys: bool = False
    email_address: str = ""
    source: Path | None = None


def parse_key_values(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines. Accepts the bash-sourced shiva.conf of 0.x.

    Blank lines and comments are skipped, a leading ``export`` is dropped, and
    one pair of matching surrounding quotes is removed from the value.
    """
    pairs: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        line = line.removeprefix("export ").strip()
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        pairs[key.strip()] = value
    return pairs


def _to_int(pairs: dict[str, str], key: str, default: int) -> int:
    raw = pairs.get(key, str(default))
    try:
        number = int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from None
    if number < 0:
        raise ConfigError(f"{key} must not be negative, got {number}")
    return number


def find_config(explicit: str | None) -> Path | None:
    """Return the config file to load, or None to run on defaults."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
        return path
    for candidate in CONFIG_SEARCH_PATH:
        path = candidate.expanduser()
        if path.is_file():
            return path
    return None


def load_config(explicit: str | None = None) -> Config:
    path = find_config(explicit)
    if path is None:
        return Config()
    pairs = parse_key_values(path.read_text(encoding="utf-8"))
    defaults = Config()
    return Config(
        group_files=Path(pairs.get("group_files", str(defaults.group_files))).expanduser(),
        max_slots=max(1, _to_int(pairs, "max_slots", defaults.max_slots)),
        ssh_timeout=_to_int(pairs, "ssh_timeout", defaults.ssh_timeout),
        command_timeout=_to_int(pairs, "command_timeout", defaults.command_timeout),
        accept_new_keys=pairs.get("autoaddkeys_support", "false").lower() in TRUE_VALUES,
        email_address=pairs.get("email_address", ""),
        source=path,
    )


def load_env_file(path: Path = ENV_FILE) -> None:
    """Load KEY=VALUE pairs into os.environ. Variables already set win."""
    path = path.expanduser()
    if not path.is_file():
        return
    for key, value in parse_key_values(path.read_text(encoding="utf-8")).items():
        os.environ.setdefault(key, value)


def read_secret(name: str) -> str | None:
    """Return a credential from NAME_FILE (preferred) or NAME.

    Warns on stderr when the file is readable by group or others.
    """
    file_name = os.environ.get(f"{name}_FILE")
    if file_name:
        path = Path(file_name).expanduser()
        try:
            mode = path.stat().st_mode
            secret = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError(f"cannot read {name}_FILE {path}: {exc.strerror}") from None
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            print(
                f"shiva: warning: {path} is accessible by group or others; use chmod 600",
                file=sys.stderr,
            )
        return secret
    return os.environ.get(name) or None
