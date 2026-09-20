# 010. An ESP32 touch-screen gadget shows fleet health (not the official monitor)

**Date:** 2026-09-20
**Status:** Accepted

## Context

A 2.8" ESP32 touch-screen board was available. The owner wanted every machine in the lab shown as an animated
character whose animation reflects the machine's health, with a special-move animation when tapped. Project files:
[`services/esp32-fleet-gadget/`](../../services/esp32-fleet-gadget/).

Constraints found while building it:

- The board has 520 KB of RAM, no PSRAM and 4 MB of flash, and no place to keep SSH keys by design (ADR 006:
  the private key exists only on the workstation, and the Linux hosts cannot SSH to each other).
- The workstation's WSL2 is behind Windows NAT, so a web server inside WSL is not reachable from the LAN without
  extra Windows port forwarding, and the workstation restarts and crashes more than the always-on hosts.
- The fleet SSH key has a passphrase and works only through an `ssh-agent`, which cron does not have.

## Decision

1. **The gadget is a personal network gadget, not the fleet's official monitor.** Nothing depends on it. Real
   monitoring, when it is built, is a separate decision (Prometheus is planned in Phase 4).
2. **A collector on the workstation, a static file on `ubuntu`, and a client on the board.** `collector.py` runs from
   cron every minute, gathers read-only health data over the existing SSH access (plus PowerShell for the
   workstation itself and Termux `sshd` for the phone), and copies one `status.json` to `ubuntu`. `ubuntu` serves it
   read-only on port 8090 through a user systemd unit, with a UFW rule limited to `192.168.1.0/24`. The board only
   fetches that file over HTTP.
3. **The board holds no keys.** Its one secret is the Wi-Fi password, stored in the chip's NVS and provisioned over USB
   serial. It is not in the firmware image, this repo, or any note.
4. **No new SSH keys on the hosts.** The collector finds an `ssh-agent` that already holds the fleet key; if none is
   running it skips the run and leaves the last good file, and the board shows "collector offline" once the file is
   older than 150 s. This keeps the ADR 006 key model but means the collector pauses after a workstation reboot until
   the key is added to an agent again.
5. **The art is generated, not committed.** Characters are original and produced with an AI image service; the images
   and the converted sprite blob stay out of the repo (unclear copyright on AI output, 1 MB binary). The tools and the
   prompts are committed.

## Alternatives considered

- **The board hosts the server and the workstation pushes to it:** opens an inbound port on a device that is hard to
  patch and wears its flash with constant writes. Rejected.
- **Serve `status.json` from the workstation:** unreachable from the LAN without Windows port forwarding, and the
  workstation is the least reliable host. Rejected.
- **A dedicated passphrase-less, restricted monitoring key on every host** (`restrict,command=` plus a probe script):
  the robust fix for the unattended collector. Not done: it changes SSH configuration on three hosts and needs the
  owner's decision. Recorded as a follow-up.
- **Run the collector on `ubuntu`:** the Linux hosts cannot SSH to each other by design (ADR 006). Rejected.

## Consequences

- `ubuntu` gains a second inbound rule (`8090/tcp` from the LAN) and a user service that needs `linger`; documented in
  `docs/hosts.md`. The file contains only hostnames, temperatures, load, memory and disk percentages and alert text.
- A new device on the LAN: the board (`esp32-gadget`, `192.168.1.168`, address reserved in the router by the owner).
- The workstation gains a per-minute cron job, and a Windows logon task (`WSL-KeepAlive`) keeps WSL running so the
  cron jobs survive a Windows restart.
- Two failures were found and fixed while building it and are worth remembering: cron has no `ssh-agent` (the first
  scheduled run marked every Linux host "offline" and the push failed; the fix is the agent lookup above), and
  MicroPython needs `with open(...)` for file writes (an unclosed write left a zero-byte file).
