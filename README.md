# homelab

Four-machine bare-metal Linux lab. Built to learn infrastructure by running it rather than reading about it.

Everything here is real hardware — no cloud instances, no VMs standing in for nodes. When something breaks, it breaks for reasons.

## Hardware

| Host | Hardware | OS | Role |
|---|---|---|---|
| `illntentpc` | Intel i5-1135G7, 16 GB | Windows 11 + WSL2 | Control node, Ansible *(planned)* |
| `ubuntu-ThinkPad-T420s` | ThinkPad T420s, i5-2520M, 8 GB | Ubuntu 24.04 LTS | k3s server *(planned)* |
| `ubuntuserver` | Lenovo B590, i3-2348M, 6 GB | Ubuntu Server 24.04 LTS | k3s agent *(planned)* |
| `ChromeboxArch` | Acer, Celeron N3350, 4 GB, 27 GB eMMC | Arch Linux | Network services |

Storage: 250 GB portable SSD (backup target), 1 TB flash (Ventoy install media).

## Status

**Done**

- [x] Bare-metal Ubuntu Server 24.04 provisioned on `ubuntuserver` — UEFI/GPT, LVM, OpenSSH
- [x] Root filesystem extended online, 98 GB → 455 GB, no downtime
- [x] SMART monitoring (`smartd`) deployed and verified across both servers
- [x] Drive health baselines captured

**In progress**

- [ ] Phase 0 — DHCP reservations, hostname scheme, SSH key distribution, password auth disabled, UFW
- [ ] Phase 1 — Ansible: the whole lab configured from code
- [ ] Phase 2 — Docker
- [ ] Phase 3 — k3s cluster
- [ ] Phase 4 — Prometheus and Grafana
- [ ] Phase 5 — CI/CD: commit → build → deploy
- [ ] Phase 6 — Terraform

## Notable

**[Postmortem: two evenings, six symptoms, one bad USB drive](docs/postmortem-boot-failure.md)**

Getting the first server installed took two full evenings and produced six apparently unrelated failures — a boot menu that flickered back to Windows, a reset loop, a `grub rescue>` prompt, a sector read error, and finally `apt-get update` failing with exit 100. Firmware settings, boot modes, partition schemes, RAM, and the hard drive were all investigated and cleared.

The cause was bad USB install media — a defective flash drive, a corrupt ISO, or both. The postmortem covers what the evidence did and didn't isolate.

Two separate hypotheses pointed at a failing hard drive along the way — one from a misread GRUB error address, one from the drive's age. Both were tested with `smartctl` rather than acted on. Both were wrong: zero reallocated sectors, zero pending sectors, both drives healthy. Continuing to investigate rather than replacing hardware on those hypotheses is what eventually isolated the real cause.

## Repository structure

- `docs/` — runbooks, postmortems, network documentation
- `ansible/` — inventory and playbooks
- `k8s/` — manifests
- `scripts/` — utilities
## Notes

This is a learning lab, kept deliberately in the open — including the parts that went wrong. The failures are the useful record.
