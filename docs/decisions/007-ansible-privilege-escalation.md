# 007. Passwordless sudo for Ansible privilege escalation

**Date:** 2026-09-06
**Status:** Accepted

## Context

Ansible's `become: yes` directive runs tasks with elevated privileges on
target hosts, equivalent to prefixing a command with `sudo`. By default,
`sudo` on all three Linux hosts prompts interactively for a password —
the same constraint that causes `ssh host "sudo command"` to fail when
no pseudo-terminal is allocated (see
`runbook-disable-password-auth.md`, Common Failures).

Running a playbook with `become: yes` against these hosts failed
immediately with `"Missing sudo password"`, since Ansible has no
interactive terminal to supply one into during a normal run.

A decision was needed on how privilege escalation should work going
forward, since typing a password per run defeats a meaningful part of
Ansible's value once playbooks are run often.

## Options considered

**1. `--ask-become-pass` on every run.** No configuration change to any
host. Ansible prompts once at the start of each invocation and reuses
that password for all `become` tasks in the run. Safe in the sense
that nothing new is exposed, but adds friction to every single
playbook execution going forward.

**2. Broad passwordless sudo (`NOPASSWD:ALL`).** The account used for
Ansible gets unrestricted root access with no password prompt, on all
three hosts. Maximum convenience. Means the SSH private key alone —
already the sole credential in this lab, per `006-hostname-naming.md`
— now also grants unrestricted root with no second factor at all.

**3. Scoped passwordless sudo.** `NOPASSWD` limited to a specific list
of commands (e.g. `apt`, `ufw`, `systemctl`) rather than `ALL`. Reduces
blast radius if the key is ever compromised, at the cost of needing the
list maintained and expanded as new playbooks need new commands.

## Decision

**Option 2 — broad passwordless sudo.**

```
username ALL=(ALL) NOPASSWD:ALL
```
placed in `/etc/sudoers.d/ansible-nopasswd` on each host, using that
host's own username (`novo1`, `ubuntu`, `chromebook`), edited via
`visudo -f` rather than a plain text editor to avoid a syntax error
that could break `sudo` entirely.

Reasoning:

- This lab already operates on a single-key, single-operator trust
  model (ADR 006). The private key already unlocks SSH access to every
  host; extending the same key to also imply unrestricted root is a
  consistent extension of an existing decision, not a new category of
  risk.
- Every machine is physically present and accessible. Recovery from a
  mistake — including a broken sudoers file, mitigated by using
  `visudo` — does not depend on remote access succeeding.
- Scoped sudo (Option 3) would need to be revisited and expanded with
  nearly every new playbook written from here forward — Phase 1 alone
  will introduce package installation, service management, and file
  operations, each needing its own scoped entry. The maintenance
  burden was judged not worth it for a single-operator lab.

## Consequences

**Positive**
- Playbooks run non-interactively, with no password prompt, which is
  required for any future automation (scheduled runs, CI/CD-triggered
  playbook execution in later phases).
- One line per host, easy to audit — `cat
  /etc/sudoers.d/ansible-nopasswd` shows the entire privilege grant at
  a glance.

**Negative**
- A compromised SSH private key now grants unrestricted root on every
  host in the fleet, not just user-level access. There is no second
  factor and no command restriction standing between the key and full
  system control.
- This decision should be revisited if the fleet ever grows beyond a
  single operator, or if any host stops being physically local and
  recoverable.

**Neutral**
- Discovered during setup: the SSH client configuration
  (`~/.ssh/config`, containing the `novo1`/`ubuntu`/`chromebook`
  aliases) exists only on the Windows side of the workstation and was
  not present inside WSL2, where Ansible runs. `ssh novo1` from a WSL2
  shell failed with "couldn't resolve hostname" until the config file
  was copied over, the same way the private key itself had to be
  copied in earlier. Not a security decision, but a real gap in the
  WSL2 setup worth noting: anything SSH needs — key, known_hosts,
  config — has to exist on both sides of the Windows/WSL2 boundary
  independently, since they are separate filesystems despite being the
  same physical machine.

## Follow-up

- [ ] If a second operator or remote (non-physical) host is ever added
      to this lab, revisit this decision — Option 3 (scoped sudo)
      becomes the more defensible choice once the single-operator,
      single-location assumptions no longer hold.
- [ ] Confirm `~/.ssh/config` inside WSL2 stays in sync with the
      Windows-side version if either is ever edited.
