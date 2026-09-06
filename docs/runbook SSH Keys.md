# Runbook: SSH key generation and distribution

## Goal
Generate one SSH keypair on the workstation and distribute the public
half to every Linux host, so no password is ever typed for SSH again.

## Applies to
The workstation (key generation, one time) and every Linux host in the
fleet (key distribution, once per host).

## Prerequisites
- Password-based SSH already working to each target host — you need a
  password once, to install the key.
- Decided in advance: one key for the whole fleet, or one per host. For
  a single-operator lab where all keys would live in the same directory
  on the same workstation anyway, one key is the simpler and equally
  safe choice — key-per-host defends against a threat model (isolated
  key storage) this setup doesn't have.

## Steps

### Part 1 — generate the keypair (workstation, once)

1. Generate an ed25519 keypair.
   ```
   ssh-keygen -t ed25519 -C "workstation"
   ```
   Accept the default path. Set a passphrase or leave it blank —
   either is defensible; a passphrase protects the key file at rest
   (theft, backup exposure) but not against something already running
   as you on the same machine.

2. Confirm what was created.
   ```
   ls ~/.ssh
   ```
   Two files: one ending `.pub` (safe to share, plain text, one line),
   one with no extension (never leaves this machine).

### Part 2 — install the public key on a target host

3. Get the public key's contents onto the target and appended to its
   `authorized_keys` file. On Linux/macOS, `ssh-copy-id` does this in
   one command:
   ```
   ssh-copy-id user@target-host
   ```

   **Windows has no `ssh-copy-id`.** Do it manually — this is the
   general-purpose version, works from PowerShell:
   ```
   type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh user@target-host "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
   ```
   This creates `~/.ssh` on the target if missing, sets it to `700`,
   appends the piped key to `authorized_keys` (the bare `cat >>` with
   no filename reads from stdin, which is where the piped key lands),
   then locks `authorized_keys` to `600`.

4. Repeat step 3 for every remaining host.

### Part 3 — stop retyping the passphrase (if one was set)

5. Enable and start the SSH agent (Windows, Administrator PowerShell):
   ```
   Set-Service -Name ssh-agent -StartupType Automatic
   Start-Service ssh-agent
   ssh-add
   ```
   On Linux/macOS, `ssh-agent` is typically already running per-session;
   `ssh-add` alone is usually enough.

6. Add `AddKeysToAgent yes` to `~/.ssh/config` under a `Host *` block so
   this never needs doing by hand again after a reboot.

## Verification
```
ssh user@target-host
```
No password prompt. A passphrase prompt (not a password prompt) means
the key worked and the agent isn't loaded yet — see Common Failures.

```
ssh-add -l
```
Lists keys currently held by the agent. Confirms the agent is running
and has the key loaded.

## Common failures

- **Still prompted for the account password.** The key never made it
  into `authorized_keys`, or permissions are wrong. Check on the
  target: `ls -la ~/.ssh` — directory must be `700`, `authorized_keys`
  must be `600`. SSH silently refuses a file that's more open than it
  expects; the reason only shows up in the target's own auth log, not
  in the client's error message.
- **Prompted for a passphrase, not a password.** This means key auth
  *worked* — the server accepted the key, and your own machine is now
  asking to unlock it locally. Not a failure. Fix the repeated prompt
  with the agent (Part 3), not by troubleshooting the connection.
- **Public key split across two lines in `authorized_keys`.** Silently
  breaks the key. It must be exactly one line. Easy to introduce by
  pasting through a terminal that wraps long lines — verify with
  `cat authorized_keys` and confirm it's one unbroken line per key.
- **`ssh-agent` service is `Stopped`/`Disabled` on Windows.** Ships
  disabled by default. `Get-Service ssh-agent` to check; Part 3 fixes
  it. Needs an elevated (Administrator) PowerShell.

## Notes
The private key exists **only** on the workstation, by design. None of
the Linux hosts hold a private key, so none of them can SSH outward —
to each other or anywhere else — under this identity. That's expected
and correct; see `docs/decisions/006-hostname-naming.md` for the full
reasoning. Don't troubleshoot a lack of outbound SSH from a target host
as if it were a bug.
