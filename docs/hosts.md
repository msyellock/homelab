# Lab hosts

| Hostname | Machine | RAM | Disk | OS | Planned role |
|---|---|---|---|---|---|
| `illntentpc` | HP, i5-1135G7 | 16 GB | 477 GB | Windows 11 | Workstation / Ansible control |
| `ubuntu-ThinkPad-T420s` | ThinkPad T420s, i5-2520M | 8 GB | 465 GB HDD | Ubuntu 24.04 | k3s server |
| `ubuntuserver` | Lenovo B590, i3-2348M | 6 GB | 465 GB HDD | Ubuntu Server 24.04 | k3s agent |
| `ChromeboxArch` | Acer, Celeron N3350 | 4 GB | 27 GB eMMC | Arch Linux | Network services |

Storage: 250 GB portable SSD (backup target), 1 TB flash (Ventoy install media).

## To do
- [ ] DHCP reservations, record IPs here
- [ ] Rename hosts: node01, node02, svc01, workstation
- [ ] SSH key distribution
