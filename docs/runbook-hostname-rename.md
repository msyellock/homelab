# Runbook: Rename a host and set up cross-host name resolution

## Goal
Rename a Linux host's static hostname, and ensure every other host on the
lab network can reach it by that name — without breaking `sudo` in the
process.

## Applies to
Any Ubuntu host in the lab. Performed on `novo1`, `ubuntu`, and
`chromebook`.

## Prerequisites
- Root or sudo access on the host being renamed.
- The new name decided in advance and consistent everywhere it will be
  used (SSH config aliases, this host's own record, every other host's
  `/etc/hosts`).
- DHCP reservations already set — this runbook assumes IPs are stable.
  See `docs/hosts.md`.

## Steps

### Part 1 — rename the host itself

1. Set the new static hostname.
   ```
   sudo hostnamectl set-hostname newname
   ```

2. Fix the local hosts file to match. `hostnamectl` does **not** touch
   this file — it only changes what the system calls itself.
   ```
   sudo nano /etc/hosts
   ```
   Find the line starting `127.0.1.1` and change the old hostname to the
   new one. This is the step that's easy to skip and the one that causes
   the failure in "Common failures" below.

### Part 2 — let every other host find this one by name

3. On **each of the other hosts**, add a line to `/etc/hosts` for this
   machine:
   ```
   192.168.1.x    newname
   ```
   Use the reserved IP from `docs/hosts.md`, not whatever address the
   machine happens to hold at the moment — reservations exist so this
   stays correct.

4. Repeat step 3 in the other direction for every host pair. With three
   hosts this means six lines total across three files — two per host,
   one for each of the other two.

## Verification

On the renamed host:
```
hostnamectl
```
**Static hostname** shows the new name.

```
sudo whoami
```
Returns `root` instantly. See Common Failures if this pauses first.

From every other host:
```
ping -c1 newname
ssh newname
```
Both succeed using the name alone — no IP, no full hostname.

## Common failures

- **`sudo` pauses for several seconds before every command.** Part of
  `sudo`'s startup does a reverse lookup of the system's own hostname.
  If `/etc/hosts` still has the old name (or no entry at all) next to
  `127.0.1.1`, that lookup fails or times out before falling through.
  Fix: complete step 2. This is the single most common thing to forget,
  because `hostnamectl` gives no warning that it hasn't happened.

- **First ping after a period of inactivity is very slow (500ms–1s+),
  then normal on the next attempt.** Not a naming problem. On a
  wireless host, this is the radio waking from a power-save state.
  Confirm with a second and third ping before concluding anything is
  wrong. If it persists past the first couple of pings, see the
  WiFi powersave fix in `decisions/003-networkmanager-on-b590.md`.

- **`ssh newname` gives `Permission denied (publickey)` when
  connecting from a host that is not the workstation.** Expected if
  your private key lives only on the workstation, by design — see
  `decisions/006-hostname-naming.md`. Not a resolution problem; name
  resolution can succeed (confirmed by `ping`) while SSH still
  correctly refuses, because the two systems check entirely different
  things.

## Notes
This process is manual and repeats per host with only the hostname and
IP changing each time. That repetition — the same file, the same two
lines, three times over — is the direct motivation for Phase 1
(Ansible): a host inventory and a template would generate every one of
these `/etc/hosts` entries from a single source of truth instead of
hand-editing six files.
