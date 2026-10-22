from __future__ import annotations

import io
import os
from typing import TYPE_CHECKING

import httpx
import pytest

from shiva.cli import EXIT_OK, main
from shiva.config import ConfigError, load_config, load_env_file, parse_key_values, read_secret
from shiva.hosts import HostsError, group_path, parse_hosts, resolve_hosts
from shiva.katello import KatelloClient, KatelloError

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import FakeSSH

LEGACY_CONF = """\
group_files="/usr/local/etc/shiva"
email_support="true"
email_address="root@example.com"
autoaddkeys_support="false"
max_slots=10
ssh_timeout="10"
spacecmd_support="false"
"""


def test_legacy_conf_parses() -> None:
    pairs = parse_key_values(LEGACY_CONF + "export command_timeout='30'\n# note\n")
    assert pairs["email_address"] == "root@example.com"
    assert pairs["ssh_timeout"] == "10"
    assert pairs["command_timeout"] == "30"


def test_load_config(tmp_path: Path) -> None:
    path = tmp_path / "shiva.conf"
    path.write_text(LEGACY_CONF + "command_timeout=30\nautoaddkeys_support=yes\n")
    config = load_config(str(path))
    assert config.max_slots == 10
    assert config.command_timeout == 30
    assert config.accept_new_keys is True
    assert config.source == path


def test_load_config_defaults_when_absent() -> None:
    config = load_config(None)
    assert config.source is None
    assert config.command_timeout == 0


@pytest.mark.parametrize("line", ["max_slots=ten", "command_timeout=-1"])
def test_bad_integers(tmp_path: Path, line: str) -> None:
    path = tmp_path / "shiva.conf"
    path.write_text(line + "\n")
    with pytest.raises(ConfigError):
        load_config(str(path))


def test_env_file_does_not_override_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / "shiva.env"
    env.write_text("KATELLO_URL=https://from-file\nKATELLO_USERNAME=admin\n")
    monkeypatch.setenv("KATELLO_URL", "https://from-shell")
    load_env_file(env)
    assert os.environ["KATELLO_URL"] == "https://from-shell"
    assert os.environ["KATELLO_USERNAME"] == "admin"


def test_secret_file_wins_and_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = tmp_path / "pw"
    secret.write_text("from-file\n")
    secret.chmod(0o644)
    monkeypatch.setenv("KATELLO_PASSWORD", "from-env")
    monkeypatch.setenv("KATELLO_PASSWORD_FILE", str(secret))
    assert read_secret("KATELLO_PASSWORD") == "from-file"
    assert "chmod 600" in capsys.readouterr().err
    secret.chmod(0o600)
    assert read_secret("KATELLO_PASSWORD") == "from-file"
    assert capsys.readouterr().err == ""


def test_unreadable_config(tmp_path: Path) -> None:
    path = tmp_path / "shiva.conf"
    path.write_bytes(b"max_slots=\xff\n")
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(str(path))


def test_host_file(config_file: Path, tmp_path: Path) -> None:
    config = load_config(str(config_file))
    hosts_file = tmp_path / "hosts.txt"
    hosts_file.write_text("a\nb # comment\n")
    tty = io.StringIO()
    assert resolve_hosts(config, file=str(hosts_file), group=None, stdin=tty, katello=None) == [
        "a",
        "b",
    ]
    with pytest.raises(HostsError, match="not found"):
        resolve_hosts(config, file=str(tmp_path / "nope"), group=None, stdin=tty, katello=None)
    hosts_file.write_bytes(b"\xff\n")
    with pytest.raises(HostsError, match="cannot read"):
        resolve_hosts(config, file=str(hosts_file), group=None, stdin=tty, katello=None)


def test_parse_hosts() -> None:
    assert parse_hosts(["a", "# c", "", " b ", "a", "c # x"]) == ["a", "b", "c"]


def test_group_path_refuses_escape(config_file: Path) -> None:
    config = load_config(str(config_file))
    assert group_path(config, "web") is not None
    assert group_path(config, "../shiva.conf") is None
    assert group_path(config, "..") is None


def test_empty_stdin_list_is_an_error(config_file: Path) -> None:
    config = load_config(str(config_file))
    with pytest.raises(HostsError, match="empty"):
        resolve_hosts(config, file="-", group=None, stdin=io.StringIO("# none\n"), katello=None)


def _katello(handler: object) -> KatelloClient:
    return KatelloClient(
        url="https://katello.example.com",
        username="admin",
        password="secret",
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )


def test_katello_hosts_paginated() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        page = int(request.url.params["page"])
        names = [f"host{page}a", f"host{page}b"] if page <= 2 else []
        return httpx.Response(200, json={"subtotal": 4, "results": [{"name": n} for n in names]})

    hosts = _katello(handler).hosts_in_collection('web "prod"')
    assert hosts == ["host1a", "host1b", "host2a", "host2b"]
    assert seen[0].url.path == "/api/v2/hosts"
    assert seen[0].url.params["search"] == 'host_collection = "web \\"prod\\""'
    assert seen[0].headers["authorization"].startswith("Basic ")
    assert len(seen) == 2


def test_katello_collections_sorted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/katello/api/host_collections"
        rows = [{"name": "zeta"}, {"name": "alpha"}]
        return httpx.Response(200, json={"subtotal": 2, "results": rows})

    assert _katello(handler).host_collections() == ["alpha", "zeta"]


def test_katello_http_error() -> None:
    client = _katello(lambda request: httpx.Response(401, json={}))
    with pytest.raises(KatelloError, match="HTTP 401"):
        client.hosts_in_collection("web")


def test_katello_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(KatelloError, match="failed"):
        _katello(handler).host_collections()


def test_katello_invalid_json() -> None:
    client = _katello(lambda request: httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(KatelloError, match="failed"):
        client.host_collections()


def test_katello_requires_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KATELLO_URL", "http://katello.example.com")
    monkeypatch.setenv("KATELLO_USERNAME", "admin")
    monkeypatch.setenv("KATELLO_PASSWORD", "secret")
    with pytest.raises(ConfigError, match="https"):
        KatelloClient.from_env()


def test_katello_repr_hides_password() -> None:
    assert "secret" not in repr(_katello(lambda request: httpx.Response(200)))


def test_katello_half_configured(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KATELLO_URL", "https://katello.example.com")
    assert main(["-c", str(config_file), "true"]) == 2


def test_cli_falls_back_to_katello_group(
    config_file: Path, fake_ssh: FakeSSH, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        KatelloClient, "hosts_in_collection", lambda self, name: [f"{name}-1", f"{name}-2"]
    )
    monkeypatch.setenv("KATELLO_URL", "https://katello.example.com")
    monkeypatch.setenv("KATELLO_USERNAME", "admin")
    monkeypatch.setenv("KATELLO_PASSWORD", "secret")
    assert main(["-c", str(config_file), "-g", "db", "true"]) == EXIT_OK
    assert sorted(c[0][c[0].index("--") + 1] for c in fake_ssh.calls) == ["db-1", "db-2"]
