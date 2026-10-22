"""CLI integration tests: one per documented exit code, plus the output contract."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from shiva.cli import EXIT_FAILED, EXIT_OK, EXIT_USAGE, main

if TYPE_CHECKING:
    from collections.abc import Callable
    from email.message import EmailMessage
    from pathlib import Path

    from tests.conftest import FakeSSH


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "usage: shiva" in capsys.readouterr().out


def test_bad_flag_exits_two() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--no-such-flag"])
    assert exc.value.code == EXIT_USAGE


def test_no_command_exits_two(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["-c", str(config_file)]) == EXIT_USAGE
    assert "no command given" in capsys.readouterr().err


def test_missing_config_exits_two(tmp_path: Path) -> None:
    assert main(["-c", str(tmp_path / "nope.conf"), "uptime"]) == EXIT_USAGE


def test_unknown_group_exits_two(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["-c", str(config_file), "-g", "nope", "uptime"]) == EXIT_USAGE
    assert "could not find group: nope" in capsys.readouterr().err


def test_bad_fact_exits_two(config_file: Path) -> None:
    assert main(["-c", str(config_file), "--fact", "no-operator", "uptime"]) == EXIT_USAGE


def test_bad_jobs_exits_two(config_file: Path, fake_ssh: FakeSSH) -> None:
    assert main(["-c", str(config_file), "-j", "0", "uptime"]) == EXIT_USAGE
    assert fake_ssh.calls == []


def test_all_hosts_ok_exits_zero(
    config_file: Path, fake_ssh: FakeSSH, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["-c", str(config_file), "-g", "web", "uname", "-r"]) == EXIT_OK
    captured = capsys.readouterr()
    assert "=== web1 ===\nhello from web1" in captured.out
    assert "=== Successful (2) ===" in captured.err
    assert [call[1].splitlines()[1] for call in fake_ssh.calls] == ["uname -r", "uname -r"]


def test_one_failed_host_exits_one(
    config_file: Path, fake_ssh: FakeSSH, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_ssh.answers["web2"] = (3, "", "boom\n")
    assert main(["-c", str(config_file), "-g", "web", "false"]) == EXIT_FAILED
    err = capsys.readouterr().err
    assert "=== Unsuccessful (1) ===\nweb2  (exit code 3)" in err


def test_default_group_used_without_source(config_file: Path, fake_ssh: FakeSSH) -> None:
    assert main(["-c", str(config_file), "true"]) == EXIT_OK
    assert sorted(c[0][c[0].index("--") + 1] for c in fake_ssh.calls) == ["alpha", "beta"]


def test_hosts_from_piped_stdin(
    config_file: Path, fake_ssh: FakeSSH, stdin: Callable[[str, bool], None]
) -> None:
    stdin("db1\ndb2\n", False)
    assert main(["-c", str(config_file), "true"]) == EXIT_OK
    assert sorted(c[0][c[0].index("--") + 1] for c in fake_ssh.calls) == ["db1", "db2"]


def test_hosts_from_dash_file(
    config_file: Path, fake_ssh: FakeSSH, stdin: Callable[[str, bool], None]
) -> None:
    stdin("db3\n", True)
    assert main(["-c", str(config_file), "-f", "-", "true"]) == EXIT_OK
    assert len(fake_ssh.calls) == 1


def test_quiet_prints_nothing(
    config_file: Path, fake_ssh: FakeSSH, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["-c", str(config_file), "-q", "true"]) == EXIT_OK
    assert capsys.readouterr() == ("", "")


def test_json_report(
    config_file: Path, fake_ssh: FakeSSH, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_ssh.answers["beta"] = (77, "", "shiva: fact not matched\n")
    assert main(["-c", str(config_file), "--json", "--fact", "os.family=RedHat", "id"]) == EXIT_OK
    report = json.loads(capsys.readouterr().out)
    assert report["counts"] == {"ok": 1, "failed": 0, "skipped": 1}
    assert [h["status"] for h in report["hosts"]] == ["ok", "skipped"]


def test_timeout_flag_fails_hung_host(config_file: Path, fake_ssh: FakeSSH) -> None:
    fake_ssh.hang.add("beta")
    assert main(["-c", str(config_file), "-t", "5", "sleep", "9000"]) == EXIT_FAILED


def test_list_groups(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["-c", str(config_file), "-l"]) == EXIT_OK
    assert capsys.readouterr().out.split() == ["default", "web"]


def test_list_members(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["-c", str(config_file), "-L", "web"]) == EXIT_OK
    assert capsys.readouterr().out.split() == ["web1", "web2"]


def test_email_failure_does_not_change_exit(
    config_file: Path,
    fake_ssh: FakeSSH,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise ConnectionRefusedError(111, "Connection refused")

    monkeypatch.setattr("shiva.cli.send_email", refuse)
    assert main(["-c", str(config_file), "--email", "ops@example.com", "true"]) == EXIT_OK
    assert "could not send email" in capsys.readouterr().err


def test_email_sent(
    config_file: Path, fake_ssh: FakeSSH, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[str, EmailMessage]] = []

    class FakeSMTP:
        def __init__(self, host: str) -> None:
            self.host = host

        def __enter__(self) -> FakeSMTP:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def send_message(self, message: EmailMessage) -> None:
            sent.append((self.host, message))

    monkeypatch.setattr("shiva.report.smtplib.SMTP", FakeSMTP)
    assert main(["-c", str(config_file), "-q", "--email", "ops@example.com", "uptime"]) == EXIT_OK
    [(host, message)] = sent
    assert host == "localhost"
    assert message["To"] == "ops@example.com"
    assert message["Subject"] == "Shiva complete: uptime"
    assert "=== Successful (2) ===\nalpha\nbeta" in message.get_content()
