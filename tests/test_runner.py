from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

import pytest

from shiva.runner import (
    Fact,
    RunOptions,
    Status,
    build_script,
    classify,
    load_keychain_agent,
    run_all,
    ssh_argv,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import FakeSSH


def test_command_goes_over_stdin_not_scp(fake_ssh: FakeSSH) -> None:
    run_all(["h1"], "echo 'a b' * $HOME", RunOptions())
    argv, script = fake_ssh.calls[0]
    assert argv[-2:] == ["sh", "-s"]
    assert "scp" not in argv
    assert "echo 'a b' * $HOME" in script.splitlines()


def test_script_body_reads_dev_null() -> None:
    script = build_script("cat", ())
    assert script == "{\ncat\n} </dev/null\n"


def test_script_runs_in_real_shell() -> None:
    proc = subprocess.run(
        ["sh", "-s"],
        input=build_script("printf '%s|' \"a  b\" *nomatch*; read x || echo eof", ()),
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout == "a  b|*nomatch*|eof\n"


def test_ssh_argv_options() -> None:
    argv = ssh_argv("-oProxyCommand=x", RunOptions(user="ops", ssh_timeout=4, accept_new_keys=True))
    assert argv[:5] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4"]
    assert "StrictHostKeyChecking=accept-new" in argv
    assert argv[argv.index("-l") + 1] == "ops"
    assert argv.index("--") < argv.index("-oProxyCommand=x")


def test_results_keep_host_order(fake_ssh: FakeSSH) -> None:
    hosts = [f"h{i}" for i in range(20)]
    results = run_all(hosts, "true", RunOptions(jobs=5))
    assert [r.host for r in results] == hosts
    assert all(r.status is Status.OK for r in results)


def test_timeout_marks_failed_and_keeps_partial_output(fake_ssh: FakeSSH) -> None:
    fake_ssh.hang.add("slow")
    [result] = run_all(["slow"], "sleep 9000", RunOptions(command_timeout=2))
    assert result.status is Status.FAILED
    assert result.reason == "timed out after 2s"
    assert result.stdout == "partial\n"


def test_missing_ssh_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_ssh(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr("shiva.runner.subprocess.run", no_ssh)
    [result] = run_all(["h"], "true", RunOptions())
    assert result.status is Status.FAILED
    assert result.reason == "cannot run ssh: No such file or directory"


@pytest.mark.parametrize(
    ("code", "stderr", "facts", "expected"),
    [
        (0, "", False, (Status.OK, "")),
        (77, "shiva: fact not matched\n", True, (Status.SKIPPED, "fact not matched")),
        (77, "shiva: fact not matched\n", False, (Status.FAILED, "exit code 77")),
        (77, "", True, (Status.FAILED, "exit code 77")),
        (78, "shiva: facter is not installed\n", True, (Status.FAILED, "facter is not installed")),
        (255, "", False, (Status.FAILED, "ssh connection failed")),
        (1, "", False, (Status.FAILED, "exit code 1")),
    ],
)
def test_classify(code: int, stderr: str, facts: bool, expected: tuple[Status, str]) -> None:
    assert classify(code, stderr, facts) == expected


def test_fact_parse() -> None:
    assert Fact.parse("os.family=RedHat") == Fact("os.family", "RedHat")
    assert Fact.parse("virtual!=physical") == Fact("virtual", "physical", negate=True)
    assert Fact.parse("empty=") == Fact("empty", "")
    with pytest.raises(ValueError, match="KEY=VALUE"):
        Fact.parse("$(reboot)=x")


def test_fact_value_is_quoted() -> None:
    script = build_script("id", (Fact("os.name", "Red Hat'; reboot; '"),))
    assert "'Red Hat'\"'\"'; reboot; '\"'\"''" in script


def _fake_facter(tmp_path: Path, value: str) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    facter = bin_dir / "facter"
    facter.write_text(f"#!/bin/sh\necho '{value}'\n")
    facter.chmod(0o755)
    return str(bin_dir)


@pytest.mark.parametrize(
    ("fact", "expected_code"),
    [("os.family=RedHat", 0), ("os.family=Debian", 77), ("os.family!=RedHat", 77)],
)
def test_fact_gate_in_real_shell(tmp_path: Path, fact: str, expected_code: int) -> None:
    path = _fake_facter(tmp_path, "RedHat") + ":/usr/bin:/bin"
    proc = subprocess.run(
        ["sh", "-s"],
        input=build_script("echo ran", (Fact.parse(fact),)),
        capture_output=True,
        text=True,
        env={"PATH": path},
        check=False,
    )
    assert proc.returncode == expected_code
    assert (proc.stdout == "ran\n") is (expected_code == 0)


def test_fact_gate_without_facter(tmp_path: Path) -> None:
    proc = subprocess.run(
        ["/bin/sh", "-s"],
        input=build_script("echo ran", (Fact.parse("a=b"),)),
        capture_output=True,
        text=True,
        env={"PATH": str(tmp_path)},
        check=False,
    )
    assert classify(proc.returncode, proc.stderr, True) == (
        Status.FAILED,
        "facter is not installed",
    )


def test_keychain_agent_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    monkeypatch.delenv("SSH_AGENT_PID", raising=False)
    monkeypatch.setattr("shiva.runner.socket.gethostname", lambda: "box")
    (tmp_path / ".keychain").mkdir()
    (tmp_path / ".keychain" / "box-sh").write_text(
        "SSH_AUTH_SOCK=/tmp/agent.1; export SSH_AUTH_SOCK;\n"
        "SSH_AGENT_PID=42; export SSH_AGENT_PID;\n"
    )
    load_keychain_agent(home=tmp_path)
    assert os.environ["SSH_AUTH_SOCK"] == "/tmp/agent.1"
    assert os.environ["SSH_AGENT_PID"] == "42"
