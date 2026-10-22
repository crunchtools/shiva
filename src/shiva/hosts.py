"""Turn a file, a group name, a Katello host collection or stdin into hosts."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from collections.abc import Iterable

    from shiva.config import Config
    from shiva.katello import KatelloClient

DEFAULT_GROUP = "default"


class HostsError(Exception):
    """Raised when no host list can be found. Maps to exit code 2."""


def parse_hosts(lines: Iterable[str]) -> list[str]:
    """One host per line; comments, blanks and duplicates are dropped, order kept."""
    seen: dict[str, None] = {}
    for raw in lines:
        host = raw.split("#", 1)[0].strip()
        if host:
            seen.setdefault(host, None)
    return list(seen)


def _read_hosts(path: Path) -> list[str]:
    try:
        return parse_hosts(path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeError) as exc:
        raise HostsError(f"cannot read host list {path}: {exc}") from None


def group_path(config: Config, name: str) -> Path | None:
    """Return the group file for NAME inside group_files, refusing path escapes."""
    if not name or "/" in name or name in {".", ".."}:
        return None
    path = config.group_files / name
    return path if path.is_file() else None


def list_groups(config: Config, katello: KatelloClient | None) -> list[str]:
    """Local group files, then Katello host collections not shadowed by one."""
    local = sorted(p.name for p in config.group_files.glob("*") if p.is_file())
    remote = katello.host_collections() if katello else []
    return local + [name for name in remote if name not in local]


def group_members(config: Config, name: str, katello: KatelloClient | None) -> list[str]:
    """Hosts in a local group file, else in the Katello host collection NAME."""
    path = group_path(config, name)
    if path is not None:
        return _read_hosts(path)
    if katello is not None:
        members = katello.hosts_in_collection(name)
        if members:
            return members
    raise HostsError(f"could not find group: {name}")


def resolve_hosts(
    config: Config,
    *,
    file: str | None,
    group: str | None,
    stdin: TextIO,
    katello: KatelloClient | None,
) -> list[str]:
    """Pick the host list: -f (or -f - for stdin), -g, piped stdin, then 'default'."""
    if file == "-":
        hosts = parse_hosts(stdin)
    elif file is not None:
        path = Path(file).expanduser()
        if not path.is_file():
            raise HostsError(f"host file not found: {path}")
        hosts = _read_hosts(path)
    elif group is not None:
        hosts = group_members(config, group, katello)
    else:
        # Under cron stdin is not a terminal but carries nothing; fall through.
        hosts = [] if stdin.isatty() else parse_hosts(stdin)
        hosts = hosts or group_members(config, DEFAULT_GROUP, None)
    if not hosts:
        raise HostsError("the host list is empty")
    return hosts
