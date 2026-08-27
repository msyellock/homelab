# Lab hosts

| Hostname | Machine | CPU | RAM | Storage | OS | Planned role |
|---|---|---|---|---|---|---|
| `illntentpc` | HP | i5-1135G7 | 16 GB | 477 GB | Windows 11 | Workstation / Ansible control |
| `ubuntu-ThinkPad-T420s` | ThinkPad T420s | i5-2520M | 8 GB | 465 GB HDD (7200 RPM) | Ubuntu 24.04 | k3s server |
| `ubuntuserver` | Lenovo B590 | i3-2348M | 6 GB | 465 GB HDD (5400 RPM) | Ubuntu Server 24.04 | k3s agent |
| `chromebookubuntu` | Acer Chromebook 15 (Google "Sand") | Celeron N3350 | 4 GB | 29.1 GB eMMC | Ubuntu Server 24.04.4 | Network services |

Storage: 250 GB portable SSD (backup target), 1 TB flash (Ventoy install media).

## Network

Subnet `192.168.1.0/24`, gateway `192.168.1.1` (Verizon Fios).

| Host | IP | MAC | Interface |
|---|---|---|---|
| `chromebookubuntu` | 192.168.1.153 | `5c:5f:67:60:f0:ea` | wlp1s0 (Intel 7265, WiFi) |

## Hardware baselines

Captured 2026-08-27.

| Host | Drive | Health |
|---|---|---|
| `ubuntuserver` | HGST HTS545050A7E380 | 0 reallocated, 0 pending, 14,165 power-on hours |
| `ubuntu-ThinkPad-T420s` | HGST HTS725050A7E630 | 0 reallocated, 0 pending, 3,099 power-on hours |
| `chromebookubuntu` | eMMC (soldered) | `life_time 0x01 0x03`, `pre_eol_info 0x01` — 20–30% of write cycles used on the user area |

eMMC is not replaceable. Keep workloads on that host read-mostly.

## Notes

Both Ubuntu installs shipped with the LVM logical volume claiming only part of the volume group. Extended online with `lvextend -l +100%FREE` and `resize2fs`, no downtime:

- `ubuntuserver` — 98 GB → 455 GB
- `chromebookubuntu` — 13 GB → 26 GB

## To do
- [ ] DHCP reservations for all hosts, record IPs and MACs above
- [ ] Rename hosts: node01, node02, svc01, workstation
- [ ] SSH key distribution from workstation
- [ ] `HandleLidSwitch=ignore` on all laptop nodes
