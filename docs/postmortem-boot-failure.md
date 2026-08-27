# Postmortem: Two Evenings, Six Symptoms, One Bad USB Drive

**Date:** August 2026
**System:** Lenovo B590 (2012), Ubuntu Server 24.04 LTS install
**Duration:** ~2 evenings
**Root cause:** Defective USB flash media (see *Limitations* — two variables changed together)

---

## Summary

Installing Ubuntu Server on a 2012 Lenovo B590 took two full evenings and produced six failures that appeared to come from six different subsystems. Firmware settings, boot modes, partition schemes, system memory, network configuration, and the internal hard drive were each investigated and cleared.

The cause was bad install media. Replacing the physical USB stick — with a freshly downloaded ISO — resolved everything.

---

## Symptoms, in the order they appeared

1. **F2 and F12 unresponsive.** No BIOS access, no boot menu.
2. **USB listed in the boot menu, but selecting it flickered and returned to Windows.**
3. **Boot loop.** With USB first in the boot order, the machine reset repeatedly.
4. **`grub rescue>` prompt.** GRUB loaded but could not find its own modules.
5. **`error: failure reading sector 0x82200 from 'hd0'`.**
6. **`apt-get update` returned exit status 100** during the installer's `configure_apt` step.

Six symptoms across firmware, bootloader, storage, and package management. One cause.

---

## Investigation

### Symptom 1: firmware access

Two real issues, both unrelated to the main fault:

- **Hotkey Mode** was enabled in BIOS, so F1–F12 acted as media keys. `Fn+F2` was required.
- **Windows Fast Startup** meant "shutdown" was actually a hybrid hibernate, so the machine never performed a full POST and never listened for the keypress.

`powercfg /h off` fixed the second. Windows can also command the firmware directly:

```
shutdown /r /fw /t 0     # restart into BIOS setup
shutdown /r /o /t 0      # restart into Advanced Startup ("Use a device")
```

These bypass hotkey timing entirely. Useful — but they only got me to the real problem faster.

### Symptom 2: flicker and return

The firmware enumerated the device, began the handoff, and aborted within a second. That pattern means the transfer started and failed — not that the device wasn't detected.

Two candidates: Secure Boot rejecting the bootloader signature, or a malformed bootloader on the media. Secure Boot was disabled. The symptom persisted.

### Symptom 3: the boot loop

Mechanical and not mysterious. USB was first in the boot order, the boot attempt faulted, the firmware reset, the boot order sent it back to the USB. It repeated until the stick was removed.

Lesson: **boot order is the default; the F12 menu is a per-boot override.** Leaving USB last in the order prevents the loop and costs nothing, because F12 supersedes it when needed.

### Symptoms 4 and 5: grub rescue and the sector read error

`grub rescue>` means GRUB's first stage loaded successfully but could not find `/boot/grub`. GRUB's stage 1 is a few hundred bytes with a hardcoded `prefix` path baked in at build time. If the module directory isn't there — or isn't readable — it drops to a minimal shell.

The rescue prompt is a launcher, not just an error. It can be driven manually:

```
ls                                      # list devices
ls (hd0,msdos1)/                        # inspect a partition
set prefix=(hd0,msdos1)/boot/grub
set root=(hd0,msdos1)
insmod normal
normal
```

`normal` ran, then the machine reset — GRUB reached full mode and died loading video modules. That layer can be skipped entirely by loading the kernel by hand:

```
insmod linux
linux /casper/vmlinuz boot=casper nomodeset ---
initrd /casper/initrd
boot
```

The sector read error at `0x82200` — roughly 267 MB into the device — was the single most informative piece of evidence in the investigation, and I initially attributed it to the wrong device.

**`hd0` is not an identity.** It is a position in a list the firmware builds for that boot. When a machine boots from USB, the firmware commonly promotes the USB device to the first drive slot, pushing the internal drive down. The read error was on the flash drive, not the hard disk.

This is the same reason production Linux systems reference disks by UUID in `/etc/fstab` rather than `/dev/sda`. Device ordering is not stable.

It is also the strongest single piece of evidence for the root cause. `failure reading sector` is a **block-level** read failure reported by GRUB's disk layer — a media signature, not a file-content one. A truncated or corrupt file produces missing or short files at the filesystem layer; it does not produce a failed sector read.

### Symptom 6: apt-get update, exit 100

After finally reaching the installer, it failed at `configure_apt`:

```
subiquity/Install/install/configure_apt: FAIL
Command [... 'apt-get', 'update'] returned non-zero exit status 100
```

Two things about this were misleading.

**First, the timing.** The log showed:

```
12:57:16.065  confirm_POST          storage confirmed
12:57:16.069  configure_apt begins  install starts
12:57:37.087  FAIL, exit 100        21 seconds later
```

Subiquity begins installing in the background the moment the storage wipe is confirmed — it does not wait for the remaining interactive screens. So the install was already failing while I was typing my username, and the crash dialog appeared over the profile form. It looked like the username field caused it. It never did. Twenty-one seconds is simply how long it takes to fill in those fields.

**Lesson: in a system with concurrent tasks, what is on screen is not necessarily what is failing.** Timestamps establish causality; the UI does not.

**Second, the error itself.** Exit 100 is apt's generic failure, and I read it as "cannot reach the mirror." Disconnecting the Ethernet cable entirely and retrying produced the identical failure. The traceback showed why:

```
install.py:605  for_install_path = "cp://" + await self.configure_apt(...)
```

`cp://` is a local copy source. apt was pointed at the ISO's own package pool on the USB stick — not the internet — and still could not read it.

That reframed the whole investigation. Every symptom was a read failure against the same device, surfacing at whichever layer happened to be reading it.

---

## Root cause

**Bad USB install media.**

Bad flash cells sit at fixed physical addresses. The failure was therefore perfectly reproducible, while appearing to move between subsystems as the installer demanded different regions of the media — the boot sector, then GRUB's modules, then the kernel, then the package pool.

The ISO checksum was also never verified before writing, so a corrupt download cannot be excluded as a contributing factor.

---

## Limitations of this conclusion

**Two variables changed on the successful attempt: a different physical USB stick *and* a freshly downloaded ISO.** Both were replaced at once.

That proves what fixed the problem. It does not fully isolate which of the two was broken.

The sector read error is the strongest evidence for the drive specifically, for the reason described above — block-level read failures are a media signature. But the honest statement is that the media was bad in one of two ways, and the investigation did not separate them.

This was an avoidable gap. Having spent two evenings changing one variable at a time, I changed two at the finish line because I wanted it working. **Discipline is easiest to abandon at the exact moment it stops feeling necessary.**

If I needed to know, the test is cheap: write the verified ISO to the original stick and see whether it fails again.

### Notes on things that were *not* the cause

Rufus **ISO Image mode** was used on every attempt, including the successful one. It is therefore not implicated. I had assumed at one point that ISO mode's rebuilding of the disk layout could break GRUB's `prefix` path — plausible in principle, but contradicted by the evidence here.

DD mode remains preferable on general principle, since a byte-for-byte clone removes a variable. But it was not the fix, and claiming it was would be inventing a tidier story than the facts support.

---

## What was ruled out

| Suspected | Verdict | How it was cleared |
|---|---|---|
| Internal hard drive | Healthy | `smartctl`: 0 reallocated sectors, 0 pending |
| System RAM | Fine | 6 GB installed; never a constraint |
| BIOS / firmware | Working correctly | Behaved as documented once Fast Startup was off |
| USB ports | Working | Device enumerated every time |
| Network | Working | Failure reproduced with the cable unplugged |
| Write method (Rufus ISO mode) | Not implicated | Same mode used on the successful install |
| Secure Boot / boot mode / partition scheme | Not the cause | All downstream of bad media |

### The two drive-failure hypotheses

Twice the evidence appeared to point at a failing hard disk — once from the `hd0` sector read error, once from the drive's age. The second time, a replacement SSD had already been selected.

Both were tested with `smartctl` rather than acted on:

```
  5  Reallocated_Sector_Ct     0
  9  Power_On_Hours        14165
196  Reallocated_Event_Count  20
197  Current_Pending_Sector    0
```

Zero reallocated sectors. Zero pending. 14,165 hours is about 1.6 years of runtime spread across fourteen calendar years — light use. The 20 reallocation *events* against 0 reallocated *sectors* mean the drive encountered conditions it handled without consuming any spares.

The second machine's drive came back cleaner still: 3,099 hours, zeros across every failure indicator.

**Both hypotheses were wrong.** Replacing the drive would have cost money and left the actual fault in place. Continuing to investigate is what eventually isolated it.

---

## Resolution

A different physical USB stick, with a freshly downloaded ISO, written with Rufus in ISO Image mode.

The install completed without incident.

---

## What I would check first next time

1. **Verify the checksum before writing.** A 99% complete file is indistinguishable from a complete one until something tries to execute the missing part. This single habit would have shortened the investigation dramatically — and would have separated the two variables.

2. **A checksum validates the file, not the device.** A correct image written to defective flash is still unbootable. When media misbehaves after a verified write, replace the hardware — do not rewrite the same stick a third time.

3. **Treat `grub rescue>` as a media verdict, not a puzzle.** Correctly written Ubuntu media boots to a GRUB menu. A rescue prompt means something is wrong with the media. Replace it rather than troubleshooting forward.

4. **Identify storage by contents, never by device number.**

5. **Read the log before forming a hypothesis.** The apt error was written to disk on every single attempt. Three rounds of theorizing preceded anyone reading it, and it resolved the question in one line.

6. **When the same configuration produces different results across attempts, suspect the inputs** — media, cables, memory — before rewriting configuration.

7. **Keep changing one variable at a time all the way to the end**, including the attempt you expect to succeed.

---

## Working procedure

The runbook this produced:

1. Download `ubuntu-24.04.x-live-server-amd64.iso` to local disk.
2. `Get-FileHash .\<iso> -Algorithm SHA256` — compare against ubuntu.com. Do not proceed on a mismatch.
3. Write with Rufus. When it detects the isohybrid image, ISO Image mode works; DD Image mode is marginally safer since it clones rather than rebuilds.
4. Insert into a USB 2.0 port. Older firmware may not initialize USB 3.0 before OS handoff.
5. AC power connected, Ethernet connected, lid open.
6. Restart, tap F12, select the USB.
7. **Expect a GRUB menu.** A rescue prompt means the media is wrong — stop and rewrite, or replace the stick.
8. Ubuntu Server (not minimized), blank proxy, default mirror.
9. Storage: entire disk with LVM. Encryption off for a headless machine.
10. Check "Install OpenSSH server."
11. No snaps. Remove the USB when prompted.

---

## Postscript

Ubuntu's guided LVM install allocated only 98 GB of the 465 GB disk to the root logical volume, leaving ~360 GB unallocated inside the volume group. Extended online, on a mounted root filesystem, with no unmount and no reboot:

```
sudo lvextend -l +100%FREE /dev/ubuntu-vg/ubuntu-lv
sudo resize2fs /dev/mapper/ubuntu--vg-ubuntu--lv
```

98 GB → 455 GB. The kernel reported `on-line resizing required` and ext4 rewrote its group descriptor table live (`old_desc_blocks = 13, new_desc_blocks = 58`).

Two layers, two operations, and the order cannot be reversed — a filesystem cannot expand into space its volume does not own.
