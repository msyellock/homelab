# 006. Hostnames match SSH usernames

**Date:** 2026-09-05
**Status:** Accepted

## Context

Phase 0 originally proposed a role-based hostname scheme (`node01`,
`node02`, `svc01`, `workstation`) to describe each machine's function in
the cluster. By the time hostnames were actually changed, an
`~/.ssh/config` on the workstation already aliased each host by its
account username (`novo1`, `ubuntu`, `chromebook`), and those aliases
were in daily use.

A decision was needed: adopt the originally planned role-based scheme, or
rename the hosts to match the usernames already in use.

## Options considered

**1. Role-based hostnames (`node01`, `node02`, `svc01`).** Describes
function, not account. Independent of any single user — a second
operator or a renamed account wouldn't affect the hostname. More
conventional for a cluster that may grow.

**2. Username-matched hostnames (`novo1`, `ubuntu`, `chromebook`).**
Matches the SSH aliases already in use, so hostname and connection alias
are the same word everywhere — one less mapping to hold in memory.
Couples two things that are conceptually independent: what a machine
is, and who logs into it.

## Decision

**Option 2.** Hosts renamed to `novo1`, `ubuntu`, and `chromebook`,
matching the existing SSH usernames and config aliases.

Reasoning:

- This is a single-operator lab. The coupling between hostname and
  account is a real tradeoff, but the risk it creates — a second user,
  or a renamed account — is not currently anticipated and isn't planned.
- Reduces cognitive load daily: one name per host instead of two
  (hostname and SSH alias) that happen to usually be typed together but
  aren't guaranteed to match.
- Cheaper to change now, while the fleet is small and the rename is
  three hosts, than after Ansible inventory, `/etc/hosts` entries across
  multiple machines, and documentation all reference one scheme or the
  other.

## Related: single private key, per-host authorized_keys

Made during Phase 0 and recorded here since it's the same category of
decision (one operator, coupling account identity to infrastructure) and
wasn't previously written down.

One SSH keypair, generated once on the workstation, distributed to all
three Linux hosts' `authorized_keys`. No per-host keys.

Considered and rejected: a separate keypair per host, for finer-grained
revocation. Rejected because all keys would live in the same `.ssh`
directory on the same workstation regardless — the isolation a
key-per-host arrangement buys against a *stolen key* doesn't exist here,
since compromising the workstation compromises all of them equally. The
overhead would defend against a threat model this setup doesn't actually
have.

Consequence: the private key exists **only** on the workstation. The
three Linux hosts hold only the public half, in `authorized_keys`. This
means none of them can SSH outward — to each other or anywhere else —
under this identity. Discovered during Level 9 of Phase 0 when SSH
between two Linux hosts by hostname correctly failed with `Permission
denied (publickey)`, despite name resolution (`ping`) succeeding. Not a
bug: the workstation is the only source of outbound SSH by design, which
matches the "cattle, not pets" model described in Session 07 — the
Linux hosts are managed *from* the workstation, never management points
themselves.

## Consequences

**Positive**
- One name to remember per host, used consistently in SSH config,
  `/etc/hosts`, and now the hostname itself.
- The key-location decision is now explicit and documented, rather than
  an implicit consequence of "however Level 1 happened to be done."

**Negative**
- If a second user or a renamed account is ever introduced, the
  hostname will no longer describe anything meaningful and would need
  revisiting.
- Hostnames convey no information about role (server vs. agent vs.
  services host) the way `node01`/`node02`/`svc01` would have. That
  mapping now lives only in `docs/hosts.md`, not in the name itself.

**Neutral**
- Lateral SSH between Linux hosts is unavailable under the current key
  setup. Not currently needed — Ansible connects outward from the
  control node to each target, never target-to-target — but worth
  knowing before assuming any two lab hosts can reach each other over
  SSH.

## Follow-up

- [ ] If lateral SSH between hosts is ever required, generate and
      distribute a separate keypair for that specific purpose rather
      than copying the workstation's private key onto additional
      machines.
