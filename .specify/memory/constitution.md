# shiva Constitution

> **Version:** 1.0.0
> **Ratified:** 2026-10-22
> **Status:** Active
> **Inherits:** [crunchtools/constitution](https://github.com/crunchtools/constitution) v1.27.0
> **Profile:** CLI Tool

This file holds shiva's own rules. The fleet rules and the CLI Tool profile apply at
the inherited version and are checked by `constitution.yml`. They are not restated here.

## Purpose

Run one shell command on many hosts over ssh in parallel and report which hosts
succeeded, failed or were skipped.

## Versioning

Semantic Versioning 2.0.0. MAJOR for a changed flag, exit code or config key; MINOR
for a new flag or host source; PATCH for fixes.

## CLI Interface

argparse, flat flags: `-g/--group`, `-f/--file` (`-` = stdin), `-l/--list-groups`,
`-L/--list-members`, `-c/--config`, `-u/--user`, `-j/--jobs`, `-t/--timeout`,
`-A/--accept-new-keys`, `--fact`, `-q/--quiet`, `--json`, `--email`, `-v/--verbose`,
`--version`, then the command.

Exit `0` when every host succeeded or was skipped by `--fact`, `1` when any host
failed (including timeouts and ssh errors), `2` for usage or configuration errors,
which are raised before any host is contacted.

Host output goes to stdout and the summary to stderr; `--json` puts one document on
stdout instead.

## Remote Execution

The command reaches the host only as stdin of `ssh ... -- HOST sh -s`, wrapped in a
brace group reading `/dev/null`. Shiva never copies files to a host, never needs
anything there but `sh` (and `facter` when `--fact` is used), and never builds a
remote command line from user input. Fact keys are validated against
`[A-Za-z0-9_.:-]+` and values are `shlex.quote`d. ssh always runs with
`BatchMode=yes`; host key checking is never turned off, only `accept-new` with `-A`.

## Configuration

`shiva.conf` stays KEY=VALUE so configs from 0.x load. Keys: `group_files`,
`max_slots`, `ssh_timeout`, `command_timeout`, `autoaddkeys_support`,
`email_address`. Flags override keys.

## External APIs

Katello (optional): `GET /api/v2/hosts?search=host_collection = "NAME"` and
`GET /katello/api/host_collections`, via httpx with basic auth. Credentials:
`KATELLO_URL`, `KATELLO_USERNAME`, `KATELLO_PASSWORD` or `KATELLO_PASSWORD_FILE`,
optional `KATELLO_CA_BUNDLE`, loaded from `~/.config/mcp-env/shiva.env`. TLS
verification is never disabled.

## Quality Gates

1. `uv run ruff check src tests`
2. `uv run mypy src`
3. `uv run pytest -v` (ssh and Katello mocked; the remote script is run in a real `sh`)
4. Gourmand
5. Container build

## Container

`quay.io/hummingbird/python:3.14-fips-builder` plus `openssh-clients` (ssh is a runtime
dependency). Published to `quay.io/crunchtools/shiva` and `ghcr.io/crunchtools/shiva`
on `v*.*.*` tags.
