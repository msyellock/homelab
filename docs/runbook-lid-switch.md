# Runbook: Prevent lid close from suspending a laptop server

## Goal
Closing the lid on a laptop being used as a server must not suspend
the machine or drop active sessions.

## Applies to
Any laptop host running headless or semi-headless as lab
infrastructure. Applied to `novo1`, `chromebook`, and `ubuntu`.

## Prerequisites
None unusual. Root/sudo access on the target host.

## Steps

1. Confirm the kernel actually sees a lid switch before assuming
   software is the right layer to fix.
   ```
   cat /proc/acpi/button/lid/LID0/state
   ```
   Should report `open` (or `closed`). If this path doesn't exist,
   the lid is being handled below the OS — logind settings won't help,
   and the fix belongs in firmware/BIOS instead.

2. Edit `/etc/systemd/logind.conf`. The relevant directives are usually
   present but commented out with their defaults shown — uncomment and
   set all three:
   ```
   HandleLidSwitch=ignore
   HandleLidSwitchExternalPower=ignore
   HandleLidSwitchDocked=ignore
   ```
   Setting all three, not just the first, matters — a laptop on AC
   power or in a dock can be governed by a different directive than
   a laptop running on battery with the lid closed.

3. Tell the running daemon to pick up the change. Editing the file
   alone is not sufficient — `systemd-logind` holds its config in
   memory from when it started, exactly like `sshd`.
   ```
   sudo systemctl restart systemd-logind
   ```
   Note: `restart`, not `reload` — logind does not support a reload
   for this setting; it must be restarted. Confirm the restart
   actually happened by checking the service's uptime resets:
   ```
   systemctl status systemd-logind | head -5
   ```
   `Active: active (running) since ...` should show a timestamp from
   moments ago, not hours or days.

## Verification
With an SSH session open to the host:
1. Close the lid.
2. Wait at least a minute.
3. In the already-open session, run any command.

It must respond. Do not just check that the screen looks a certain
way — the actual test is whether an existing session survives, since
that's the failure mode that matters for a server.

For a live view while testing:
```
journalctl -u systemd-logind -f
```
Close the lid and watch. The line `Lid closed.` should appear with
**no** `Suspending...` line following it.

## Common failures

- **Config file is correct, daemon status shows it's been running for
  hours, and the lid still suspends the machine.** This is the one
  that matters most. `systemd-logind` does not re-read its config file
  on its own — a change on disk has zero effect until the daemon is
  told to restart. This was hit on two separate hosts during setup;
  in both cases the config was correct on the first attempt and the
  fix was simply remembering step 3. Check `systemctl status
  systemd-logind` first, always, before re-checking the config file a
  second time.
- **On a machine with a desktop environment (GNOME confirmed), the fix
  appears correct but the machine still suspends.** GNOME's own power
  settings can override logind. Check and correct both:
  ```
  gsettings get org.gnome.settings-daemon.plugins.power lid-close-ac-action
  gsettings get org.gnome.settings-daemon.plugins.power lid-close-battery-action
  ```
  Set either to `nothing` if it returns `suspend`.
- **An unrelated inhibitor lock appears to be involved (e.g. from
  `ModemManager` or `unattended-upgrades`).** `systemd-inhibit --list`
  shows active inhibitors and what they're blocking. These can
  interact with `LidSwitchIgnoreInhibited` (a separate, related
  directive) in ways that are easy to mistake for the primary fix
  working or not working. If a machine's lid behavior seems to depend
  on which services happen to be running, that's a sign two settings
  are both in play — verify `HandleLidSwitch=ignore` alone is
  sufficient by temporarily reverting any change to
  `LidSwitchIgnoreInhibited` and re-testing.

## Notes
The general pattern here — edit a config file, nothing changes, the
service simply hasn't reloaded — is not specific to `logind`. It's the
same shape of failure as SSH's `PasswordAuthentication` setting (see
`runbook-disable-password-auth.md`). Any time a config change appears
to do nothing, check whether the responsible service has actually been
told to reload or restart before assuming the setting itself is wrong.
