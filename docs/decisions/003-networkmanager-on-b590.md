# 003. NetworkManager on `ubuntuserver`

**Date:** 2026-08-27
**Status:** Accepted

## Context

`ubuntuserver` (Lenovo B590) has a Broadcom BCM43228 wireless card. Getting it
working required installing `bcmwl-kernel-source`, since no in-tree driver
exists in the Ubuntu Server ISO — `lshw` reported `driver=bcma-pci-bridge`,
meaning the kernel saw the PCI slot but had no driver for the radio itself.

Once the `wl` module loaded and a `wlp3s0` interface appeared, the link
associated but showed `degraded (configuring)` and dropped intermittently.
Aggressive WiFi power management on older Broadcom cards is a known cause of
this: connections idle out, latency spikes, and SSH sessions die without
obvious reason.

Ubuntu Server defaults to `systemd-networkd` as its network backend.
NetworkManager ships the persistent power-management configuration that fixes
this behaviour.

## Options considered

**1. Stay on `systemd-networkd`, disable powersave via a udev rule or a
systemd unit.** Keeps the fleet consistent on one backend. Requires writing
custom units for something NetworkManager handles with a config key.

**2. Install NetworkManager on this host only.** Solves the problem directly.
Introduces a second network stack into a four-machine fleet.

**3. Move the whole fleet to NetworkManager.** Consistent, but changes a
working configuration on `chromebookubuntu` for no benefit — that host has an
Intel card with no power-management problem.

**4. Run wired only, skip wireless entirely.** Simplest. Loses a working
fallback link and the exercise of getting the driver going.

## Decision

**Option 2.** NetworkManager installed on `ubuntuserver` only.

WiFi power saving disabled persistently:

```
sudo iwconfig wlp3s0 power off     # immediate, does not survive reboot
sudo sed -i 's/wifi.powersave = 3/wifi.powersave = 2/' \
  /etc/NetworkManager/conf.d/default-wifi-powersave-on.conf
```

The `iwconfig` command takes effect at once but is lost on reboot. The `sed`
edit is what makes it persist.

Backend ownership declared explicitly rather than left ambiguous:

```yaml
network:
  version: 2
  renderer: NetworkManager
```

`systemd-networkd` disabled on this host. With both backends installed and
neither explicitly chosen, which one wins after a reboot or a netplan
regeneration is not guaranteed — a configuration that works today and fails
later for no visible reason.

## Consequences

**Positive**

- Wireless works reliably as a fallback link.
- Power-management fix is persistent and survives reboots.
- Backend ownership is unambiguous.
- Exercised the full diagnostic path: PCI enumeration, driver loading, DKMS,
  and the difference between a device existing and a device being usable.

**Negative**

- The fleet now runs two network backends. `ubuntuserver` uses
  NetworkManager; `chromebookubuntu` uses `systemd-networkd`. Phase 1 Ansible
  playbooks will need to account for both, or the divergence gets resolved
  first.

**Neutral**

- `bcmwl-kernel-source` is a DKMS module and rebuilds on every kernel update.
  If wireless disappears after an upgrade, `sudo dkms status` is the first
  check.

## Follow-up

- [x] Declare `renderer: NetworkManager` in netplan on this host
- [x] Disable `systemd-networkd` on this host
- [ ] Decide whether the fleet standardises on one backend before Phase 1

Wired remains the primary link for this machine regardless. Wireless on a
cluster node produces intermittent failures that are unpleasant to diagnose,
and this host is the planned k3s agent.
