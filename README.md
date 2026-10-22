# shiva

Mass SSH client. Shiva runs one shell command on many hosts at once and tells you which
ones worked.

```
$ shiva -g web 'systemctl is-active httpd'
=== web1 ===
active

=== web2 ===
inactive

Shiva from bastion: completed, 2 host(s)
Start time: 2026-10-22T09:14:02-04:00
End time:   2026-10-22T09:14:03-04:00

=== Successful (1) ===
web1

=== Unsuccessful (1) ===
web2  (exit code 3)
```

Each host's output goes to stdout and the summary goes to stderr, so
`shiva -g web uptime > out.txt` keeps the report on your terminal.

## Install

```
uv tool install shiva-crunchtools     # or: pipx install shiva-crunchtools
podman run --rm quay.io/crunchtools/shiva --help
```

Shiva needs `ssh` on the machine it runs on and `sh` on every host. Nothing else
needs to be installed on the hosts: commands go over the ssh session's stdin, so
there is no `scp` and nothing is left in the hosts' `/tmp`.

Authentication is your ssh agent (`BatchMode=yes`, so Shiva never prompts for a
password). If `SSH_AUTH_SOCK` is unset and keychain manages your agent, Shiva reads
`~/.keychain/<hostname>-sh`.

## Picking hosts

| Source | Example |
|--------|---------|
| Group file in `group_files` | `shiva -g web uptime` |
| Any file | `shiva -f hosts.txt uptime` |
| stdin | `grep db inventory \| shiva uptime` or `shiva -f - uptime` |
| Katello host collection | `shiva -g "Prod Web" uptime` |
| None of the above | the `default` group |

Host lists hold one host per line; `#` starts a comment and duplicates are dropped.
`shiva -l` lists groups (local files, then Katello host collections) and
`shiva -L web` prints a group.

## Options

```
-g, --group NAME        local group file or Katello host collection
-f, --file FILE         hosts from FILE ('-' = stdin)
-u, --user USER         remote user (default: root)
-j, --jobs N            hosts at once (default: max_slots, 10)
-t, --timeout SECONDS   fail a host whose command runs longer (default: none)
-A, --accept-new-keys   accept host keys not seen before (changed keys are refused)
--fact KEY=VALUE        run only where `facter KEY` prints VALUE; KEY!=VALUE negates
-q, --quiet             no output, exit code only
--json                  one JSON document on stdout
--email ADDRESS         mail the summary through the local MTA
-c, --config FILE       config file
-v, --verbose           report each host on stderr as it finishes
```

Exit codes: `0` every host succeeded or was skipped, `1` at least one host failed,
`2` usage or configuration error.

### Facts

```
shiva --fact os.family=RedHat --fact 'virtual!=physical' 'dnf -y update'
```

Hosts whose facts do not match are reported as skipped, not failed. A host without
`facter` fails with "facter is not installed".

### Timeouts

`-t` stops waiting and marks the host failed. Shiva kills its local `ssh`; a remote
command that never reads or writes may keep running until it ends on its own. Wrap
it in `timeout(1)` on the host when that matters.

## Configuration

Shiva reads the first of `-c FILE`, `~/.config/shiva/shiva.conf`,
`/usr/local/etc/shiva.conf` and `/etc/shiva.conf`. See
[examples/shiva.conf](examples/shiva.conf). Config files from shiva 0.x load unchanged;
the spacecmd keys are ignored.

Katello credentials come from the environment or `~/.config/mcp-env/shiva.env`:

```
KATELLO_URL=https://katello.example.com
KATELLO_USERNAME=admin
KATELLO_PASSWORD_FILE=/home/me/.config/shiva/katello-password   # or KATELLO_PASSWORD
KATELLO_CA_BUNDLE=/etc/pki/tls/certs/katello-ca.pem             # optional
```

## Upgrading from 0.x

Shiva 1.0 is a Python rewrite of the 2012 bash script, which is kept at tag
[`v0.5-bash`](https://github.com/crunchtools/shiva/tree/v0.5-bash). Spacewalk
(`spacecmd`) support is gone; Katello host collections take its place. The license
changed from GPL-3.0 to AGPL-3.0-or-later.

## License

AGPL-3.0-or-later.
