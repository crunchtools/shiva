"""Run one command on many hosts over ssh, in parallel."""

from __future__ import annotations

import os
import re
import shlex
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

SKIP_EXIT = 77
NO_FACTER_EXIT = 78
SSH_ERROR_EXIT = 255
SKIP_MARKER = "shiva: fact not matched"
NO_FACTER_MARKER = "shiva: facter is not installed"
FACT_RE = re.compile(r"^(?P<key>[A-Za-z0-9_.:-]+)(?P<op>!?=)(?P<value>.*)$")


class Status(StrEnum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


# Exit codes only the fact gate produces, each confirmed by its stderr marker.
FACT_GATE_EXITS = {
    SKIP_EXIT: (SKIP_MARKER, Status.SKIPPED, "fact not matched"),
    NO_FACTER_EXIT: (NO_FACTER_MARKER, Status.FAILED, "facter is not installed"),
}


@dataclass(frozen=True)
class Fact:
    key: str
    value: str
    negate: bool = False

    @classmethod
    def parse(cls, text: str) -> Fact:
        match = FACT_RE.match(text)
        if not match:
            raise ValueError(f"fact must look like KEY=VALUE or KEY!=VALUE, got {text!r}")
        return cls(match["key"], match["value"], negate=match["op"] == "!=")

    def test(self) -> str:
        op = "!=" if self.negate else "="
        return f'[ "$(facter {shlex.quote(self.key)})" {op} {shlex.quote(self.value)} ]'


@dataclass(frozen=True)
class RunOptions:
    user: str = "root"
    ssh_timeout: int = 10
    command_timeout: int = 0
    accept_new_keys: bool = False
    jobs: int = 10
    facts: tuple[Fact, ...] = ()


@dataclass
class HostResult:
    host: str
    status: Status
    exit_code: int | None
    stdout: str
    stderr: str
    seconds: float
    reason: str = ""


def build_script(command: str, facts: Sequence[Fact]) -> str:
    """Return the shell script sent to the remote ``sh -s`` on stdin.

    The body is one brace group with stdin from /dev/null: sh parses the whole
    group before running it, so a command that reads stdin cannot swallow the
    rest of the script, and nothing has to be copied to the host first.
    """
    lines = ["{"]
    if facts:
        lines.append(
            f"command -v facter >/dev/null 2>&1 || "
            f"{{ echo {shlex.quote(NO_FACTER_MARKER)} >&2; exit {NO_FACTER_EXIT}; }}"
        )
        for fact in facts:
            lines.append(
                f"{fact.test()} || {{ echo {shlex.quote(SKIP_MARKER)} >&2; exit {SKIP_EXIT}; }}"
            )
    lines.append(command)
    lines.append("} </dev/null")
    return "\n".join(lines) + "\n"


def ssh_argv(host: str, options: RunOptions) -> list[str]:
    argv = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={options.ssh_timeout}",
    ]
    if options.accept_new_keys:
        argv += ["-o", "StrictHostKeyChecking=accept-new"]
    argv += ["-l", options.user, "--", host, "sh", "-s"]
    return argv


def classify(code: int, stderr: str, facts_requested: bool) -> tuple[Status, str]:
    gate = FACT_GATE_EXITS.get(code) if facts_requested else None
    if gate is not None and gate[0] in stderr:
        return gate[1], gate[2]
    if code == 0:
        return Status.OK, ""
    if code == SSH_ERROR_EXIT:
        return Status.FAILED, "ssh connection failed"
    return Status.FAILED, f"exit code {code}"


def _text(captured: bytes | str | None) -> str:
    if captured is None:
        return ""
    return captured.decode(errors="replace") if isinstance(captured, bytes) else captured


def run_host(host: str, script: str, options: RunOptions) -> HostResult:
    start = time.monotonic()
    timeout = options.command_timeout or None
    try:
        proc = subprocess.run(
            ssh_argv(host, options),
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return HostResult(
            host, Status.FAILED, None, _text(exc.stdout), _text(exc.stderr),
            time.monotonic() - start, f"timed out after {options.command_timeout}s",
        )
    except OSError as exc:
        return HostResult(
            host, Status.FAILED, None, "", "", time.monotonic() - start,
            f"cannot run ssh: {exc.strerror}",
        )
    status, reason = classify(proc.returncode, proc.stderr, bool(options.facts))
    return HostResult(
        host, status, proc.returncode, proc.stdout, proc.stderr,
        time.monotonic() - start, reason,
    )


def run_all(
    hosts: Sequence[str],
    command: str,
    options: RunOptions,
    on_done: Callable[[HostResult], None] | None = None,
) -> list[HostResult]:
    """Run COMMAND on every host, at most options.jobs at a time; keep host order."""
    script = build_script(command, options.facts)
    with ThreadPoolExecutor(max_workers=max(1, options.jobs)) as pool:
        futures = [pool.submit(run_host, host, script, options) for host in hosts]
        results = []
        for future in futures:
            result = future.result()
            if on_done is not None:
                on_done(result)
            results.append(result)
    return results


def load_keychain_agent(home: Path | None = None) -> None:
    """Pick up a keychain-managed ssh-agent when SSH_AUTH_SOCK is not set."""
    if os.environ.get("SSH_AUTH_SOCK"):
        return
    path = (home or Path.home()) / ".keychain" / f"{socket.gethostname()}-sh"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for name in ("SSH_AUTH_SOCK", "SSH_AGENT_PID"):
        match = re.search(rf"{name}=([^;\s]+)", text)
        if match:
            os.environ[name] = match.group(1)
