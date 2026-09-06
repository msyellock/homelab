# Runbook: UFW firewall setup (SSH-only)

## Goal
Enable a default-deny firewall on a host, allowing only SSH inbound,
without losing the SSH session used to configure it.

## Applies to
Any Linux host in the fleet. Applied to `novo1`, `ubuntu`, and
`chromebook`.

## Prerequisites
- Connected to the target host over SSH, ideally with key auth already
  working (password auth may be disabled by the time this runs — see
  `runbook-disable-password-auth.md`).
- Understand the ordering rationale below before running anything —
  this is the entire point of the runbook, not just the commands.

## The ordering, and why it's safe

Three commands, and the order is what prevents a lockout:

1. `ufw default deny incoming` — sets a **policy**. Inert on its own;
   UFW isn't running yet, so nothing is actually being blocked.
2. `ufw allow in ssh` — adds a **rule**. Also inert while UFW is
   disabled; the rule exists but isn't being enforced yet.
3. `ufw enable` — the only command that actually activates anything.
   The moment this runs, the deny policy and the allow rule apply
   **simultaneously**. The current SSH session was never at risk,
   because the exception (step 2) existed before enforcement began
   (step 3).

Reversing steps 2 and 3 — enabling before the SSH rule exists — is the
classic way to lock yourself out of a remote Linux host. It's
recoverable on hardware sitting next to you; it would not be on a
cloud VM with no console access. Build the habit here regardless.

## Steps

1. Set the default policy for incoming traffic.
   ```
   sudo ufw default deny incoming
   ```

2. Explicitly allow SSH before enabling anything.
   ```
   sudo ufw allow in ssh
   ```

3. Enable the firewall.
   ```
   sudo ufw enable
   ```

## Verification
```
sudo ufw status verbose
```
Expected:
```
Status: active
Default: deny (incoming), allow (outgoing), disabled (routed)
22/tcp      ALLOW IN  Anywhere
22/tcp (v6) ALLOW IN  Anywhere (v6)
```
Confirm the existing SSH session is still responsive — run any
command in it. This is the real test; the `ufw status` output alone
doesn't prove the session survived.

## Common failures

- **Locked out after `ufw enable`.** Means the allow rule wasn't
  actually in place before enabling — check whether step 2 was run
  and succeeded, or whether a typo (`ufw allow ssh` vs `ufw allow in
  ssh` — both work, but confirm neither was mistyped) caused it to
  silently do nothing. Recovery on local hardware: use physical
  console access to run `sudo ufw disable`, then redo steps 2 and 3 in
  order.
- **`ufw allow in ssh` succeeds but the rule doesn't appear for IPv6.**
  UFW generates IPv4 and IPv6 rules together from a single `allow`
  command by default — if only one appears in `ufw status verbose`,
  check whether IPv6 is disabled system-wide on that host; this is a
  configuration signal, not a UFW bug.
- **Confusing UFW rules with what's actually enforcing them.** UFW is
  a front end to netfilter (via `iptables` or `nftables`). To see the
  underlying rules UFW generated:
  ```
  sudo iptables -L -n
  ```
  Considerably less readable than `ufw status` — that's the entire
  reason UFW exists as a layer on top.

## Notes
This is the same "define the exception before flipping the switch"
pattern that recurs elsewhere in infrastructure work — Ansible's
`become` privilege model, cloud security group rules, Kubernetes
network policies. The specific commands here are UFW-specific; the
underlying discipline (stage the safe state, then activate
enforcement) is not, and is worth recognizing as a repeatable idea
rather than a UFW quirk.
