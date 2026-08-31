# Lab hosts

| Hostname | Machine | CPU | RAM | Storage | OS | Planned role |
|---|---|---|---|---|---|---|
| `illntentpc` | HP | i5-1135G7 | 16 GB | 477 GB | Windows 11 | Workstation / Ansible control |
| `ubuntu-ThinkPad-T420s` | ThinkPad T420s | i5-2520M | 8 GB | 465 GB HDD (7200 RPM) | Ubuntu 24.04 | k3s server |
| `ubuntuserver` | Lenovo B590 | i3-2348M | 6 GB | 465 GB HDD (5400 RPM) | Ubuntu Server 24.04 | k3s agent |
| `chromebookubuntu` | Acer Chromebook 15 (Google "Sand") | Celeron N3350 | 4 GB | 29.1 GB eMMC | Ubuntu Server 24.04.4 | Network services |

Portable storage: 250 GB portable SSD (backup target), 1 TB flash (Ventoy install media, integrity not yet verified).

## Network

Subnet `192.168.1.0/24`, gateway `192.168.1.1` (Verizon Fios).
DHCP dynamic range: `192.168.1.2` – `192.168.1.254`.

All addresses below are DHCP reservations set on the router, so they persist
across reboots and lease renewals.

| Host | Interface | Hardware | MAC | Address |
|---|---|---|---|---|
| `illntentpc` | wired | — | `48:9e:bd:df:cc:97` | 192.168.1.161 |
| `illntentpc` | wireless | — | `5c:61:99:5a:6a:0d` | 192.168.1.155 |
| `ubuntu-ThinkPad-T420s` | `enp0s25` | Intel Gigabit | `f0:de:f1:d9:3a:80` | 192.168.1.162 |
| `ubuntu-ThinkPad-T420s` | `wlp3s0` | — | `10:0b:a9:93:3f:04` | 192.168.1.163 |
| `ubuntuserver` | `enp4s0` | Realtek RTL8111/8168 Gigabit | `3c:97:0e:90:83:8f` | 192.168.1.160 |
| `ubuntuserver` | `wlp3s0` | Broadcom BCM43228 802.11a/b/g/n | `9c:2a:70:88:4e:e9` | 192.168.1.159 |
| `chromebookubuntu` | `wlp1s0` | Intel Wireless 7265 (dual band AC) | `5c:5f:67:60:f0:ea` | 192.168.1.153 |

### SSH targets

| Host | Address |
|---|---|
| `ubuntu-ThinkPad-T420s` | 192.168.1.162 |
| `ubuntuserver` | 192.168.1.160 |
| `chromebookubuntu` | 192.168.1.153 |

`ubuntuserver` runs wired for normal operation. Wireless is configured as a
fallback — WiFi on a cluster node produces intermittent failures that are
difficult to diagnose. If the Ethernet cable is disconnected, the machine
remains reachable at 192.168.1.159 instead.

The reservations were set on a Verizon Fios router under
**Advanced → Network Settings → IPv4 Address Distribution → Connection List**.

## Hardware baselines

Captured 2026-08-27.

| Host | Drive | Health |
|---|---|---|
| `ubuntuserver` | HGST HTS545050A7E380 (Travelstar Z5K500) | 0 reallocated sectors, 0 pending, 20 reallocation events, 14,165 power-on hours |
| `ubuntu-ThinkPad-T420s` | HGST HTS725050A7E630 (Travelstar Z7K500) | 0 reallocated sectors, 0 pending, 0 events, 3,099 power-on hours |
| `chromebookubuntu` | eMMC, soldered | `life_time 0x01 0x03`, `pre_eol_info 0x01` — 20–30% of write cycles consumed on the user area |

`smartd` is enabled and running on both Lenovo hosts. eMMC does not implement
SMART; the `/sys/block/mmcblk1/device/` interface reports the equivalent
values.

The Chromebook's storage is soldered and not replaceable. Workloads on that
host should stay read-mostly.

## Notes

### LVM under-allocation

Both Ubuntu installers created a logical volume claiming only part of the
available volume group. Extended online with no unmount and no downtime:

```
sudo lvextend -l +100%FREE /dev/ubuntu-vg/ubuntu-lv
sudo resize2fs /dev/mapper/ubuntu--vg-ubuntu--lv
```

| Host | Before | After |
|---|---|---|
| `ubuntuserver` | 98 GB | 455 GB |
| `chromebookubuntu` | 13 GB | 26 GB |

Worth checking on any guided LVM install — the installer does not use the
whole disk by default.

### Broadcom wireless on `ubuntuserver`

The BCM43228 has no in-tree driver in the Ubuntu Server ISO. `lshw` reported
`driver=bcma-pci-bridge`, meaning the kernel saw the PCI slot but not the
radio, so no wireless interface existed for netplan to configure.

Resolved while wired:

```
sudo apt install bcmwl-kernel-source
sudo modprobe wl
```

This is a DKMS module and rebuilds on every kernel update. If wireless
disappears after an upgrade, check `sudo dkms status` first.

### Network backend divergence

`ubuntuserver` runs NetworkManager, with `systemd-networkd` disabled and
`renderer: NetworkManager` declared in netplan.

`chromebookubuntu` runs `systemd-networkd`.

This inconsistency should be resolved before Phase 1, since Ansible playbooks
will otherwise need to handle two network stacks.

See [`decisions/003-networkmanager-on-b590.md`](decisions/003-networkmanager-on-b590.md).

## To do

- [x] DHCP reservations for all hosts
- [ ] Rename hosts: `node01`, `node02`, `svc01`, `workstation`
- [ ] SSH keypair generated on workstation, public key distributed
- [ ] Password authentication disabled on all Linux hosts
- [ ] UFW configured on all Linux hosts
- [ ] `HandleLidSwitch=ignore` on all laptop nodes
- [ ] `f3` integrity test on the 1 TB flash drive
- [ ] Resolve network backend divergence
