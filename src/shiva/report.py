"""Human, JSON and email reports of a run."""

from __future__ import annotations

import json
import smtplib
import socket
from dataclasses import dataclass
from email.message import EmailMessage
from typing import TYPE_CHECKING, TextIO

from shiva.runner import HostResult, Status

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime


@dataclass
class Run:
    command: str
    started: datetime
    finished: datetime
    results: Sequence[HostResult]

    def hosts(self, status: Status) -> list[str]:
        return [r.host for r in self.results if r.status is status]


def summary(run: Run) -> str:
    lines = [
        f"Shiva from {socket.gethostname()}: completed, {len(run.results)} host(s)",
        f"Start time: {run.started.isoformat(timespec='seconds')}",
        f"End time:   {run.finished.isoformat(timespec='seconds')}",
    ]
    for status, title in (
        (Status.OK, "Successful"),
        (Status.SKIPPED, "Skipped"),
        (Status.FAILED, "Unsuccessful"),
    ):
        hosts = run.hosts(status)
        if hosts:
            lines += ["", f"=== {title} ({len(hosts)}) ==="]
            for result in run.results:
                if result.status is status:
                    note = f"  ({result.reason})" if result.reason else ""
                    lines.append(f"{result.host}{note}")
    return "\n".join(lines) + "\n"


def host_block(result: HostResult) -> str:
    """Output of one host, as printed to stdout in the human format."""
    out = [f"=== {result.host} ==="]
    if result.stdout:
        out.append(result.stdout.rstrip("\n"))
    if result.status is Status.FAILED and result.stderr:
        out.append(result.stderr.rstrip("\n"))
    return "\n".join(out) + "\n"


def write_human(run: Run, stdout: TextIO, stderr: TextIO, *, quiet: bool) -> None:
    if quiet:
        return
    for result in run.results:
        if result.status is not Status.SKIPPED:
            stdout.write(host_block(result) + "\n")
    stderr.write(summary(run))


def to_json(run: Run) -> str:
    return json.dumps(
        {
            "command": run.command,
            "started": run.started.isoformat(),
            "finished": run.finished.isoformat(),
            "counts": {s.value: len(run.hosts(s)) for s in Status},
            "hosts": [
                {
                    "host": r.host,
                    "status": r.status.value,
                    "exit_code": r.exit_code,
                    "reason": r.reason,
                    "seconds": round(r.seconds, 3),
                    "stdout": r.stdout,
                    "stderr": r.stderr,
                }
                for r in run.results
            ],
        },
        indent=2,
    )


def send_email(run: Run, address: str, smtp_host: str = "localhost") -> None:
    message = EmailMessage()
    message["Subject"] = f"Shiva complete: {run.command}"
    message["From"] = f"shiva@{socket.getfqdn()}"
    message["To"] = address
    message.set_content(summary(run))
    with smtplib.SMTP(smtp_host) as smtp:
        smtp.send_message(message)
