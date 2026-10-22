# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.1] - 2026-10-22

### Changed
- PyPI releases publish only from the `pypi` GitHub environment, which admits
  only `v*.*.*` tags. First release on PyPI as `shiva-crunchtools`.

## [1.0.0] - 2026-10-22

Python rewrite of the bash script. The last bash version is tag `v0.5-bash`.

### Added
- `-t/--timeout` and `command_timeout` fail a host whose command runs too long (#16).
- Katello host collections work as groups with `-g`, `-l` and `-L` (#17).
- Hosts from stdin, piped or with `-f -` (#18).
- `--fact KEY=VALUE` and `KEY!=VALUE` run only on hosts whose facter facts match;
  others are reported as skipped (#20).
- `--json`, `-q/--quiet`, `-j/--jobs`, `--email`, `--version`.
- Documented exit codes: 0 success, 1 a host failed, 2 usage error.
- Container image at `quay.io/crunchtools/shiva` and `ghcr.io/crunchtools/shiva`.

### Changed
- Commands go to `sh -s` over the ssh session's stdin. Shiva no longer copies files to
  the hosts or needs `scp` there (#19).
- `-A` uses `StrictHostKeyChecking=accept-new`: new keys are accepted, changed keys
  are still refused.
- The summary goes to stderr and host output to stdout.
- Mail is off unless `email_address` or `--email` is set.
- License changed from GPL-3.0 to AGPL-3.0-or-later.

### Removed
- Spacewalk (`spacecmd`) support.
- `install.sh`; install with `uv tool install shiva-crunchtools`.

### Fixed
- Commands with quotes, globs or `$` reach the host exactly as typed.
- Hosts are tracked in memory instead of racing on files in `/tmp`, and a run no
  longer sleeps three seconds per host.

### Security
- Host output is spooled to temporary files and capped at 1 MiB per stream, so a
  runaway command cannot exhaust memory.
- `KATELLO_URL` must be https, since every request carries credentials.
