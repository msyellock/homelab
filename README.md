# homelab

Four-machine bare-metal Linux lab. Built to learn infrastructure by running it rather than reading about it.

Everything here is real hardware — no cloud instances, no VMs standing in for nodes. When something breaks, it breaks for reasons.

## Hardware

| Host | Hardware | OS | Role |
|---|---|---|---|
| `illntentpc` | Intel i5-1135G7, 16 GB | Windows 11 + WSL2 | Workstation / Ansible control node |
| `ubuntu` | ThinkPad T420s, i5-2520M, 8 GB | Ubuntu 24.04 LTS | k3s server *(planned)* |
| `novo1` | Lenovo B590, i3-2348M, 6 GB | Ubuntu Server 24.04 LTS | k3s agent *(planned)* |
| `chromebook` | Acer Chromebook 15, Celeron N3350, 4 GB, 29 GB eMMC | Ubuntu Server 24.04.4 | Network services |

Hostnames match SSH usernames by design — see [`docs/decisions/006-hostname-naming.md`](docs/decisions/006-hostname-naming.md).

Storage: 250 GB portable SSD (backup target). The original 1 TB flash drive failed an integrity test — counterfeit capacity, failing controller — and was discarded; see `docs/hosts.md`.

## Status

**Done**

- [x] Bare-metal Ubuntu Server 24.04 provisioned on `novo1` — UEFI/GPT, LVM, OpenSSH
- [x] Ubuntu Server provisioned on `chromebook`, replacing Arch
- [x] Root filesystems extended online with LVM — no downtime, on two hosts
- [x] SMART monitoring (`smartd`) deployed and verified on both Lenovo hosts
- [x] Drive health baselines captured across the fleet
- [x] Broadcom BCM43228 wireless working on `novo1`
- [x] **Phase 0 — SSH key auth, password auth disabled, UFW, hostnames, cross-host name resolution, lid handling — all three Linux hosts**

**In progress**

- [ ] Phase 1 — Ansible: the whole lab configured from code
- [ ] Phase 2 — Docker
- [ ] Phase 3 — k3s cluster
- [ ] Phase 4 — Prometheus and Grafana
- [ ] Phase 5 — CI/CD: commit → build → deploy
- [ ] Phase 6 — Terraform

## Notable

**[Postmortem: two evenings, six symptoms, one bad USB drive](docs/postmortem-boot-failure.md)**

Getting the first server installed took two full evenings and produced six apparently unrelated failures — a boot menu that flickered back to Windows, a reset loop, a `grub rescue>` prompt, a sector read error, and finally `apt-get update` failing with exit 100. Firmware settings, boot modes, partition schemes, RAM, and the hard drive were all investigated and cleared.

The cause was bad USB install media — a defective flash drive, a corrupt ISO, or both; the original investigation couldn't fully separate the two. A later integrity test on the same drive settled it: it failed at 66 GB of a claimed 1 TB, with USB timeouts and I/O errors throughout. Counterfeit capacity and a physically failing controller, confirmed independently of the original incident.

Two separate hypotheses pointed at a failing hard drive along the way — one from a misread GRUB error address, one from the drive's age. Both were tested with `smartctl` rather than acted on. Both were wrong: zero reallocated sectors, zero pending sectors, both drives healthy. Continuing to investigate rather than replacing hardware on those hypotheses is what eventually isolated the real cause.

## Repository structure

- [`docs/hosts.md`](docs/hosts.md) — machine inventory, network layout, hardware baselines, Phase 0 status
- [`docs/postmortem-boot-failure.md`](docs/postmortem-boot-failure.md) — install failure investigation
- [`docs/runbook-hostname-rename.md`](docs/runbook-hostname-rename.md) — hostname rename and cross-host resolution procedure
- [`docs/runbook-ssh-keys.md`](docs/runbook-ssh-keys.md) — SSH key generation and distribution across the fleet
- [`docs/runbook-disable-password-auth.md`](docs/runbook-disable-password-auth.md) — disabling SSH password authentication
- [`docs/runbook-lid-switch.md`](docs/runbook-lid-switch.md) — preventing lid close from suspending a laptop server
- [`docs/runbook-ufw-setup.md`](docs/runbook-ufw-setup.md) — UFW firewall setup with safe enable ordering
- [`docs/decisions/`](docs/decisions) — architecture decision records
- [`ansible/`](inventory.ini`) — [`ansible/`](ufw.yml) -inventory and playbooks 
- `k8s/` — manifests *(planned)*
- `scripts/` — utilities *(planned)*

## Notes

This is a learning lab, kept deliberately in the open — including the parts that went wrong. The failures are the useful record.
