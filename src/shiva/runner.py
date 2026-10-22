"""Run one command on many hosts over ssh, in parallel."""

from __future__ import annotations

import os
import re
import shlex
import socket
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import IO, TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

SKIP_EXIT = 77
NO_FACTER_EXIT = 78
SSH_ERROR_EXIT = 255
MAX_OUTPUT = 1024 * 1024
SKIP_MARKER = "shiva: fact not matched"
NO_FACTER_MARKER = "shiva: facter is not installed"
FACT_RE = re.compile(r"^(?P<key>[A-Za-z0-9_.:-]+)(?P<op>!?=)(?P<value>.*)$")


class Status(StrEnum):
    """Outcome of one host: ran and exited 0, did not, or skipped by --fact."""

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
    """A --fact condition: `facter KEY` must print VALUE (or must not, if negate)."""

    key: str
    value: str
    negate: bool = False

    @classmethod
    def parse(cls, text: str) -> Fact:
        """Parse KEY=VALUE or KEY!=VALUE. Raises ValueError for anything else."""
        match = FACT_RE.match(text)
        if not match:
            raise ValueError(f"fact must look like KEY=VALUE or KEY!=VALUE, got {text!r}")
        return cls(match["key"], match["value"], negate=match["op"] == "!=")

    def test(self) -> str:
        """Shell test that is true when the fact holds; key and value are quoted."""
        op = "!=" if self.negate else "="
        return f'[ "$(facter {shlex.quote(self.key)})" {op} {shlex.quote(self.value)} ]'


@dataclass(frozen=True)
class RunOptions:
    """How hosts are reached: login user, timeouts, host key policy, parallelism, facts."""

    user: str = "root"
    ssh_timeout: int = 10
    command_timeout: int = 0
    accept_new_keys: bool = False
    jobs: int = 10
    facts: tuple[Fact, ...] = ()


@dataclass
class HostResult:
    """Result for one host. exit_code is None when ssh never finished; reason explains."""

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
    """ssh argv for HOST. `--` precedes the host so a name cannot be read as an option."""
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
    """Map an exit code to (status, reason). Fact-gate codes need their stderr marker."""
    gate = FACT_GATE_EXITS.get(code) if facts_requested else None
    if gate is not None and gate[0] in stderr:
        return gate[1], gate[2]
    if code == 0:
        return Status.OK, ""
    if code == SSH_ERROR_EXIT:
        return Status.FAILED, "ssh connection failed"
    return Status.FAILED, f"exit code {code}"


def _read_capped(spool: IO[bytes]) -> str:
    spool.seek(0)
    head = spool.read(MAX_OUTPUT + 1)
    text = head[:MAX_OUTPUT].decode(errors="replace")
    if len(head) > MAX_OUTPUT:
        text += f"\n[shiva: output truncated at {MAX_OUTPUT} bytes]\n"
    return text


def run_host(host: str, script: str, options: RunOptions) -> HostResult:
    """Run SCRIPT on HOST. ssh errors and timeouts come back as FAILED results.

    Output is spooled to temporary files rather than memory, and at most
    MAX_OUTPUT bytes of each stream are kept.
    """
    start = time.monotonic()
    code: int | None = None
    reason = ""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.run(
                ssh_argv(host, options),
                input=script.encode(),
                stdout=out,
                stderr=err,
                timeout=options.command_timeout or None,
                check=False,
            )
            code = proc.returncode
        except subprocess.TimeoutExpired:
            reason = f"timed out after {options.command_timeout}s"
        except OSError as exc:
            reason = f"cannot run ssh: {exc.strerror}"
        stdout, stderr = _read_capped(out), _read_capped(err)
    seconds = time.monotonic() - start
    if code is None:
        return HostResult(host, Status.FAILED, None, stdout, stderr, seconds, reason)
    status, reason = classify(code, stderr, bool(options.facts))
    return HostResult(host, status, code, stdout, stderr, seconds, reason)


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
