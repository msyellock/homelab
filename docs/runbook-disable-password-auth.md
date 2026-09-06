# Runbook: Disable SSH password authentication

## Goal
Reject password-based SSH login entirely, on a host where key-based
login already works. Keys become the only way in.

## Applies to
Any Linux host where key auth has already been verified working (see
`runbook-ssh-keys.md`). Do not run this on a host you haven't already
confirmed key login on — that's the lockout scenario.

## Prerequisites
- Passwordless key login already confirmed working to this host, from
  the workstation, right now, in an open session.
- A second, currently-open SSH session to the same host is good
  insurance while making this change — if this session gets closed
  accidentally, a second one already open can fix it.
- Physical or console access to the machine as a last-resort recovery
  path, if remote access is somehow lost. On a home lab this exists by
  default; note it explicitly anyway, since it won't on a cloud VM.

## Steps

1. Check for an `Include` directive near the top of the main config —
   this determines load order and is the source of the most common
   failure below.
   ```
   head -20 /etc/ssh/sshd_config
   ls /etc/ssh/sshd_config.d/
   ```

2. Set the directive. If a relevant `.conf` file already exists in
   `sshd_config.d/`, edit that one — files there load *after* the main
   config and win any conflict, which is exactly why they exist (your
   change survives package upgrades that might reset the main file). If
   none exists, edit `/etc/ssh/sshd_config` directly.
   ```
   PasswordAuthentication no
   ```

3. Tell the running daemon to re-read its config. Editing the file
   alone does nothing — a running service holds its config in memory
   from when it started.
   ```
   sudo systemctl reload ssh
   ```
   `reload` re-reads config without dropping existing connections.
   `restart` stops and starts the whole daemon — only needed if
   `reload` doesn't seem to take effect.

4. Confirm what the daemon actually believes, not just what the file
   says.
   ```
   sudo sshd -T | grep -i passwordauthentication
   ```
   Must return `no`. If it returns `yes` here despite the file being
   edited correctly, something later in the include order is
   overriding it — go back to step 1 and check what else is in
   `sshd_config.d/`.

## Verification
From the workstation, force a password-only attempt:
```
ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no user@host
```
This must be **rejected** — `Permission denied (publickey)`. If it
prompts for a password, the change hasn't taken effect; do not consider
this done until the rejection is confirmed.

## Common failures

- **File edited, daemon reloaded, `sshd -T` still says `yes`.** Another
  file in the include chain sets `PasswordAuthentication yes` and loads
  after the one just edited. `grep -rn PasswordAuthentication
  /etc/ssh/` shows every occurrence across all files at once — the one
  that wins is whichever loads last.
- **Edited the file, nothing seems different, no error anywhere.** The
  daemon was never told to reload. This is the single most common
  mistake here — a config file change is inert until the service
  re-reads it. Run step 3.
- **Ran a `systemctl` command against `sshd` and got "unit not found."**
  On Ubuntu the unit is named `ssh`, not `sshd`. The binary is `sshd`;
  the systemd service is `ssh`.
- **A command over SSH with an attached shell command fails with a
  `sudo` terminal error, unrelated to this change.** `ssh host "sudo
  something"` fails because no pseudo-terminal is allocated for a
  one-off remote command, and `sudo` needs one to prompt. Force one
  with `ssh -t`. Separate issue from password authentication, easy to
  conflate when both come up in the same session.

## Notes
This is the single biggest security change made to any of these hosts
— from here, brute-force password guessing against them accomplishes
nothing. Worth re-running the verification step after any future OS
upgrade, since a package update could in principle reset
`/etc/ssh/sshd_config` to a shipped default that re-enables password
auth, silently reopening this door.
