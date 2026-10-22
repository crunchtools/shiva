"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import TYPE_CHECKING

from shiva import __version__
from shiva.config import Config, ConfigError, load_config, load_env_file
from shiva.hosts import HostsError, group_members, list_groups, resolve_hosts
from shiva.katello import KatelloClient, KatelloError
from shiva.report import Run, send_email, to_json, write_human
from shiva.runner import Fact, HostResult, RunOptions, Status, load_keychain_agent, run_all

if TYPE_CHECKING:
    from collections.abc import Sequence

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shiva",
        description="Run one shell command on many hosts over ssh, in parallel.",
        epilog="Exit codes: 0 every host succeeded or was skipped, 1 a host failed, "
        "2 usage or configuration error.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("-f", "--file", metavar="FILE", help="read hosts from FILE ('-' = stdin)")
    source.add_argument(
        "-g", "--group", metavar="NAME", help="local group file or Katello host collection"
    )
    source.add_argument("-l", "--list-groups", action="store_true", help="list groups and exit")
    source.add_argument("-L", "--list-members", metavar="NAME", help="list a group and exit")
    parser.add_argument("-c", "--config", metavar="FILE", help="config file (default: search)")
    parser.add_argument("-u", "--user", default="root", help="remote user (default: root)")
    parser.add_argument("-j", "--jobs", type=int, metavar="N", help="hosts at once (max_slots)")
    parser.add_argument(
        "-t", "--timeout", type=int, metavar="SECONDS",
        help="fail a host whose command runs longer (command_timeout, 0 = none)",
    )
    parser.add_argument(
        "-A", "--accept-new-keys", action="store_true",
        help="accept host keys not seen before (never changed ones)",
    )
    parser.add_argument(
        "--fact", action="append", default=[], metavar="KEY=VALUE",
        help="run only where facter KEY equals VALUE (KEY!=VALUE negates); repeatable",
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument("-q", "--quiet", action="store_true", help="no output; exit code only")
    output.add_argument("--json", action="store_true", help="JSON report on stdout")
    parser.add_argument("--email", metavar="ADDRESS", help="mail the summary (default: config)")
    parser.add_argument("-v", "--verbose", action="store_true", help="progress on stderr")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="command to run")
    return parser


def _progress(result: HostResult) -> None:
    note = f" ({result.reason})" if result.reason else ""
    print(f"shiva: {result.host}: {result.status.value}{note}", file=sys.stderr)


class UsageError(Exception):
    """A bad argument or configuration. Exit code 2."""


def _options(args: argparse.Namespace, config: Config, facts: tuple[Fact, ...]) -> RunOptions:
    jobs = args.jobs if args.jobs is not None else config.max_slots
    timeout = args.timeout if args.timeout is not None else config.command_timeout
    if jobs < 1:
        raise UsageError("--jobs must be at least 1")
    if timeout < 0:
        raise UsageError("--timeout must not be negative")
    return RunOptions(
        user=args.user,
        ssh_timeout=config.ssh_timeout,
        command_timeout=timeout,
        accept_new_keys=args.accept_new_keys or config.accept_new_keys,
        jobs=jobs,
        facts=facts,
    )


def _execute(args: argparse.Namespace, config: Config, katello: KatelloClient | None) -> int:
    """Everything after configuration loads. Raises UsageError for exit code 2."""
    try:
        facts = tuple(Fact.parse(text) for text in args.fact)
    except ValueError as exc:
        raise UsageError(str(exc)) from None
    if args.list_groups:
        print("\n".join(list_groups(config, katello)))
        return EXIT_OK
    if args.list_members:
        print("\n".join(group_members(config, args.list_members, katello)))
        return EXIT_OK
    command = " ".join(args.command).strip()
    if not command:
        raise UsageError("no command given")
    hosts = resolve_hosts(
        config, file=args.file, group=args.group, stdin=sys.stdin, katello=katello
    )
    options = _options(args, config, facts)

    load_keychain_agent()
    started = datetime.now().astimezone()
    results = run_all(hosts, command, options, on_done=_progress if args.verbose else None)
    run = Run(command, started, datetime.now().astimezone(), results)

    if args.json:
        print(to_json(run))
    else:
        write_human(run, sys.stdout, sys.stderr, quiet=args.quiet)

    address = args.email or config.email_address
    if address:
        try:
            send_email(run, address)
        except OSError as exc:
            print(f"shiva: could not send email to {address}: {exc}", file=sys.stderr)

    return EXIT_FAILED if run.hosts(Status.FAILED) else EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        load_env_file()
        config = load_config(args.config)
        return _execute(args, config, KatelloClient.from_env())
    except (UsageError, ConfigError, HostsError, KatelloError) as exc:
        parser.print_usage(sys.stderr)
        print(f"shiva: error: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
