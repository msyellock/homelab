# Runbook: Ubuntu Server install (bare metal)

## Goal
Produce reliable, verified install media and complete a bare-metal
Ubuntu Server install without the two-evening failure chain documented
in `postmortem-boot-failure.md`.

## Applies to
Any x86_64 machine in the fleet receiving a fresh Ubuntu Server
install. Used for `novo1` and `chromebook`.

## Prerequisites
- A USB drive whose integrity is not in question. See "Common
  failures" below before assuming a drive is fine just because it's
  new — one drive in this fleet's history reported a fake capacity
  and a failing controller, and looked ordinary until tested.
- Ethernet connectivity available at the target machine, or a known
  working WiFi path (see the offline-install note if neither is
  available immediately).
- AC power connected, lid open, for the duration of the install.

## Steps

1. Download the ISO to local disk — not directly to the USB drive.
   ```
   ubuntu-24.04.x-live-server-amd64.iso
   ```
   Confirm it is the **live-server** amd64 image, not desktop, not
   arm64.

2. Verify the checksum before writing anything. This is the single
   step most likely to be skipped and most likely to matter.
   ```
   Get-FileHash .\ubuntu-24.04.x-live-server-amd64.iso -Algorithm SHA256
   ```
   Compare the output against the value published on ubuntu.com. **Do
   not proceed on a mismatch** — download again rather than writing a
   known-bad file.

3. Write the ISO to the USB drive using DD mode, not ISO mode. In
   Rufus, this is offered as "Write in DD Image mode" when an
   isohybrid image is detected — take it. balenaEtcher writes DD mode
   only, with no choice to get wrong, and is the simpler option if
   available.

4. If Windows offers to format the drive afterward — **cancel.** The
   drive is fine; Windows simply cannot read a Linux partition layout.

5. Insert the drive into a USB 2.0 port on the target machine.
   Firmware of this generation does not reliably initialize USB 3.0
   controllers before OS handoff — using a 3.0 port has caused boot
   failures independent of the media itself.

6. Power on, tap **F12** at the moment of power-on, select the USB
   device.

## Verification
The machine should reach a **GRUB menu**, not a `grub rescue>` prompt.

This is the load-bearing checkpoint of the whole runbook: a rescue
prompt at this stage means the media itself is wrong, and no amount of
troubleshooting the installer forward from there will fix it. Stop and
rewrite the media on a different physical drive rather than
attempting to recover the boot chain by hand.

Proceed through the installer:
- Select **Ubuntu Server** (not "minimized")
- Network: DHCP should assign an address automatically; note it
- Proxy: leave blank
- Mirror: accept the default
- Storage: **Use an entire disk**, check **Set up this disk as an LVM
  group**. Leave encryption **unchecked** — full-disk encryption on a
  headless server means typing a passphrase at the physical machine
  on every boot, which defeats the point of a server left unattended.
- Profile: hostname, username, password of your choosing
- **Check "Install OpenSSH server."** Do not skip this — it is the
  only way to reach the machine remotely afterward.
- Snaps: select none. Add anything actually needed later,
  deliberately — see `docs/decisions/001-k3s-vs-microk8s.md` for what
  unmanaged snap accumulation costs.
- Remove the USB when prompted, before the reboot completes.

After first boot:
```
ip a
```
Confirm an address was assigned, then confirm remote access:
```
ssh username@that-address
```

## Common failures

- **USB device appears in the boot menu, screen flickers, machine
  returns to the previous OS.** The firmware attempted the handoff and
  aborted. Usually media-related — verify the checksum was actually
  checked, and confirm DD mode was used, not ISO mode.
- **`grub rescue>` prompt instead of a menu.** GRUB's first stage
  loaded but could not find its own module directory — almost always
  a media problem, not a configuration problem. Rewrite on a different
  physical drive rather than attempting a manual GRUB recovery; see
  `postmortem-boot-failure.md` for what that manual recovery looks
  like if it's ever unavoidable.
- **`apt-get update` fails with exit status 100 during install, and
  the failure appears to coincide with typing on the profile screen.**
  It doesn't — Subiquity begins installing in the background the
  moment the storage confirmation screen is accepted, before the
  remaining interactive screens are even reached. The timing is
  coincidental, not causal. If this occurs with the network cable
  physically disconnected, the ISO's own package pool is what's
  failing to read, which points at the media, not connectivity.
- **A USB drive passes a casual glance but fails partway through
  writing or installing.** Media can report a fake capacity and still
  appear to mount and accept files up to that fake ceiling. A `dd`
  write test that fails partway through, or reports I/O errors and USB
  timeouts, confirms a genuinely defective or counterfeit drive rather
  than a configuration problem. Do not reuse a drive that has ever
  failed this way, even after a successful-looking rewrite.

## Notes
Every symptom above was, in the specific incident that prompted this
runbook, traced to a single defective USB drive rather than six
separate faults — the failure signature simply changed depending on
which part of the media the installer was reading from at the moment.
See `postmortem-boot-failure.md` for the full investigation, including
two incorrect hypotheses about the hardware that were tested and ruled
out with `smartctl` before the actual cause was found.
