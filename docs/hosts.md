# Lab hosts

| Hostname | Machine | CPU | RAM | Storage | OS | Role |
|---|---|---|---|---|---|---|
| `illntentpc` | HP Laptop 17-by4xxx | i5-1135G7 (4C/8T) | 16 GB | 477 GB NVMe (Intel SSDPEKNW512G8) | Windows 11 Home + WSL2 (Ubuntu 24.04) | Workstation / Ansible control |
| `ubuntu` | ThinkPad T420s | i5-2520M (2C/4T) | 8 GB | 465 GB HDD (7200 RPM) | Ubuntu 24.04 (desktop install) | k3s server *(planned)*; fallback LLM host; serves the status file for the ESP32 gadget (port 8090) |
| `novo1` | Lenovo B590 | i3-2348M (2C/4T) | 6 GB | 465 GB HDD (5400 RPM) | Ubuntu Server 24.04 | k3s agent *(planned)*; idle |
| `chromebook` | Acer Chromebook 15 (Google "Sand") | Celeron N3350 (2C) | 4 GB | 29.1 GB eMMC | Ubuntu Server 24.04 | Network services *(planned; nothing deployed yet)* |
| *(none)* | Samsung Galaxy Note 10+ 5G (SM-N976V) | Snapdragon 855 (8C) | 12 GB | 256 GB (229 GB user data) | Android 12 (One UI 4.1), debloated, + Termux | LLM inference node (below) |
| `esp32-gadget` | ESP32 2.8" touch-screen board (ESP32-WROOM-32E) | ESP32 dual core 240 MHz | 520 KB (no PSRAM) | 4 MB flash + micro SD slot | custom C++ firmware | Fleet-health gadget (below); not the official monitor |

*Verified by polling each host on 2026-09-19 (see "State snapshot" in Notes).*

Hostnames match SSH usernames by design — a single-operator lab, so the
coupling between hostname and account was an acceptable tradeoff. See
`decisions/006-hostname-naming.md`.

Portable storage: 250 GB portable SSD (backup target), 1 TB flash — **failed
integrity test, discarded.** See Notes.

### LLM inference node: Galaxy Note 10+ (`SM-N976V`)

A spare phone repurposed as a dedicated inference host for the LLM council
(`decisions/009-llm-council-fleet-distribution.md`). It is the fleet's fastest
compute for this job by a wide margin: about 9 tokens/s generation on a 3B model
(Q4_K_M, 4 threads, measured), against about 1 token/s measured on `novo1`. It
has no hostname and is not managed like the Linux hosts.

- **What runs on it:** Termux (sideloaded GitHub build; no Play Store) with
  llama.cpp built from source for ARMv8.2 + dot-product + fp16, and two
  OpenAI-compatible `llama-server` processes (4 threads, 2048-token context, one
  request at a time): `:8080` Gemma 2 2B (council Panelist C) and `:8081`
  Llama 3.2 3B (Panelist A). Two models running at once share the CPU and memory
  bandwidth, so they are effectively serialized (each gets about 60–65% of its
  solo speed).
- **How it was prepared:** factory reset, then about 190 preinstalled packages
  removed for the user (carrier apps, Samsung consumer apps, Knox/MDM, Google Play
  Store and Play services) with `pm uninstall --user 0` — reversible with
  `cmd package install-existing` or a factory reset. Verizon variant: bootloader
  locked, no root, no custom OS.
- **Network and access:** Wi-Fi, `192.168.1.167` (DHCP, randomized private MAC).
  Managed from `illntentpc` over Wireless debugging (adb; needs re-pairing after
  a phone reboot) and a Termux `sshd` on port 8022 (key-only; the key exists only on
  the workstation). Android has no firewall, so the `llama-server` ports rely on
  their API keys instead: anything on the LAN can reach them and gets `401`
  without the key. Keys live outside this repo.
- **Caveats:** the servers and `sshd` do not survive a phone reboot on their own.
  Since 2026-09-20 the Termux:Boot add-on (v0.8.1, sideloaded GitHub build, checksum
  verified) starts `sshd` and both servers from `~/.termux/boot/start-services.sh`
  after a reboot and one unlock (see the runbook); this has been tested by running
  the script twice, not by a real reboot. Wireless debugging still has to be
  re-enabled by hand after a reboot and uses a new port each time. Sustained load heats it: a 35-minute continuous run
  while charging over USB took the battery to 45.8 °C and the CPU to 64 °C, so
  long benchmark runs pause when the battery passes 42 °C.
- Setup steps: `runbook-note10-llama-server.md`.

### Status gadget: ESP32 touch-screen board (`esp32-gadget`)

A 2.8" 240x320 resistive-touch ESP32 board that shows every machine as an animated character (owl `illntentpc`,
ox `ubuntu`, fox `novo1`, meerkat `chromebook`, hummingbird Note 10+) whose pose and aura reflect its health, with a
special-move animation on tap. It is a **personal network gadget, not the official monitor**
(`decisions/010-esp32-fleet-status-gadget.md`); code and setup are in `../services/esp32-fleet-gadget/`.

- **Network:** Wi-Fi (2.4 GHz only), `192.168.1.168` (address reserved in the router by the owner on 2026-09-20),
  hostname `esp32-gadget`, MAC `70:4b:ca:8e:09:28`. It opens no ports; it only fetches
  `http://192.168.1.162:8090/status.json` every 20 s.
- **Secrets:** none of the lab's. Its Wi-Fi password lives in the chip's NVS, never in the firmware or this repo.
  It holds no SSH keys.
- **Data path:** `illntentpc` runs `collector.py` from cron every minute (read-only checks of all five machines) and
  copies `status.json` to `ubuntu:~/status/`; `ubuntu` serves it (see Firewalls). The fleet key has a passphrase, so
  cron can only run the collector while an `ssh-agent` holds it; otherwise the run is skipped and the board dims
  everything after 150 s ("collector offline").
- **Firmware:** the original AT firmware was backed up before the board was reflashed (kept off-repo); the board ran
  MicroPython for a day and now runs custom C++ (Arduino core 2.0.17, TFT_eSPI). Flashing is done from Windows
  because the serial port is not visible inside WSL.

## Network

Subnet `192.168.1.0/24`, gateway `192.168.1.1` (Verizon Fios G3100 router).
DHCP dynamic range: `192.168.1.100` – `192.168.1.254`.

Reservations sit inside the dynamic range rather than the free `.2`–`.99`
block. Functional, since the router honours reservations either way —
renumbering into the static block would be a tidiness improvement, not a fix.

| Host | Interface | Hardware | MAC | Address |
|---|---|---|---|---|
| `illntentpc` | wired | Realtek PCIe GbE | `48:9e:bd:df:cc:97` | 192.168.1.161 |
| `illntentpc` | wireless | — | `5c:61:99:5a:6a:0d` | 192.168.1.155 *(adapter disconnected as of 2026-09-19; Ethernet in use)* |
| `ubuntu` | `enp0s25` | Intel Gigabit | `f0:de:f1:d9:3a:80` | 192.168.1.162 |
| `ubuntu` | `wlp3s0` | — | `10:0b:a9:93:3f:04` | 192.168.1.163 |
| `novo1` | `enp4s0` | Realtek RTL8111/8168 Gigabit | `3c:97:0e:90:83:8f` | 192.168.1.160 |
| `novo1` | `wlp3s0` | Broadcom BCM43228 802.11a/b/g/n | `9c:2a:70:88:4e:e9` | 192.168.1.159 |
| `chromebook` | `wlp1s0` | Intel Wireless 7265 (dual band AC) | `5c:5f:67:60:f0:ea` | 192.168.1.153 |
| Note 10+ | `wlan0` | Wi-Fi (phone SoC) | randomized (Android private MAC) | 192.168.1.167 *(DHCP)* |
| `esp32-gadget` | Wi-Fi | ESP32-WROOM-32E | `70:4b:ca:8e:09:28` | 192.168.1.168 *(reserved in the router, 2026-09-20)* |

**ARP flux on `ubuntu` and `novo1`.** Both machines keep their wired and wireless
interfaces up on the same subnet. Linux answers ARP for either of its addresses on
either NIC by default, so a LAN sweep from the workstation (2026-09-19) sees the
*wired* MAC for both `.160`/`.159` (`novo1`) and `.162`/`.163` (`ubuntu`): the
wireless addresses effectively ride the wired link. Harmless as configured. Fixing
it (`arp_ignore=1`, `arp_announce=2`, or dropping Wi-Fi while wired) is not applied.

### SSH

Key-only. Password authentication disabled on all three Linux hosts.
Aliased in `~/.ssh/config` on the workstation — `ssh novo1`, `ssh ubuntu`,
`ssh chromebook`, no IPs or usernames typed.

`novo1` runs wired for normal operation (`.160`). Wireless (`.159`) is a
fallback if the Ethernet cable is disconnected.

The lab's private key exists only on the workstation, and the Linux hosts
are not meant to SSH outward to one another or elsewhere — by design, not
oversight. See `decisions/006-hostname-naming.md` for the related reasoning on
single-key, single-location key management. A second key on the workstation
(`note10_ed25519`) authorizes the Note 10+'s Termux `sshd` (port 8022) and nothing
else. Effective `sshd` config re-verified on all three hosts on 2026-09-19:
`passwordauthentication no`, `pubkeyauthentication yes`, `permitrootlogin
without-password`.

**Finding, `ubuntu` holds a private key: its GitHub key.** Contrary to the paragraph
above, `ubuntu` holds a passphrase-less private key (`~/.ssh/id_ed25519`, comment
`ubuntu@ubuntu-ThinkPad-T420s`, created 2025-10-30, the day the OS was installed
and before the lab's key setup). It is not authorized on any lab host (checked
against all three `authorized_keys`), so it is not part of the lab's access path.
It *is* the only SSH key registered on the maintainer's GitHub account (fingerprints
match): it was generated during the initial Git setup on that laptop and gives
`ubuntu` push access to GitHub. Consequence: anyone who gets a shell on `ubuntu`
can push to that account's repositories, including this one. Options if that
matters: protect the key with a passphrase (`ssh-keygen -p`), or replace it with a
per-repository deploy key. Deleting it would cut off `ubuntu`'s GitHub access.
Also harmless: `chromebook`'s `authorized_keys` lists the workstation key twice.

### Firewalls

UFW active on all three Linux hosts. Baseline: default deny incoming,
default allow outgoing, SSH (22/tcp, IPv4 and IPv6) as the only inbound
rule — see `runbook-ufw-setup.md`.

Only `ubuntu` allows any inbound port beyond SSH: `11434/tcp` (Ollama's API; plus `8090/tcp`, below) from the
LAN subnet, added on 2026-09-18 for the distributed LLM council project — see
`runbook-ollama-lan-setup.md` and
`decisions/009-llm-council-fleet-distribution.md`. It is now the council's
fallback host (Panelist A); the rest of the council's inference runs on the
Note 10+. The other two hosts were rolled back to the SSH-only baseline:
`chromebook` first (its CPU lacks AVX2 entirely, ADR 009), then `novo1` on
2026-09-19, when the panel moved to the phone — its Ollama service, binary,
models, `ollama` user and the `11434` UFW rule were all removed. Re-verified on
2026-09-19: `ufw status` on `novo1` and `chromebook` shows only `22/tcp` (v4 and
v6), and nothing listens on `11434` on either.

`ubuntu`'s ruleset, the only one that differs from the baseline:

```
sudo ufw status verbose
```
```
Status: active
Default: deny (incoming), allow (outgoing), disabled (routed)
22/tcp        ALLOW IN  Anywhere
22/tcp (v6)   ALLOW IN  Anywhere (v6)
11434/tcp     ALLOW IN  192.168.1.0/24
8090/tcp      ALLOW IN  192.168.1.0/24
```

`8090/tcp` (added 2026-09-20) serves one read-only file, `~/status/status.json`, for the ESP32 gadget through a
*user* systemd unit (`status-web.service`, Python's `http.server`, `loginctl enable-linger ubuntu` so it runs with
nobody logged in). The file holds only hostnames, temperatures, load, memory and disk percentages, uptime and alert
text. Same LAN-only scope and single-operator trust model as the Ollama rule; no authentication. To undo:
`systemctl --user disable --now status-web`, `sudo ufw delete allow from 192.168.1.0/24 to any port 8090 proto tcp`,
`sudo loginctl disable-linger ubuntu`.

Ollama's HTTP API has no authentication of its own — the LAN-only scope
is the only thing standing between "anything on this subnet can submit
inference requests" and fully open. Accepted under the same
single-operator trust model as ADR 007. The Note 10+'s `llama-server` ports
(`8080`, `8081`) are different: Android has no firewall, so they are reachable from
the whole LAN, but they enforce an API key (`401` without it).

**Finding, unscoped SSH (re-verified 2026-09-19):** unlike the Ollama rule above, SSH's `22/tcp`
rule is `ALLOW IN Anywhere` on all three hosts — not scoped to
`192.168.1.0/24`. Not an active exposure today: `PasswordAuthentication
no` is verified on all three (see SSH section above), so a bare port
scan gets nothing without the private key, which exists only on the
workstation (ADR 006). Worth scoping to the LAN anyway the next time
these UFW rules are touched, for the same reason the Ollama rule was
scoped from the start — less exposed surface to a future SSH CVE or a
misconfiguration that weakens auth, not a response to any current
active risk.

### Name resolution

`/etc/hosts` on each Linux host contains entries for the other two,
alongside its own `127.0.1.1` line. All three resolve each other by
hostname at normal LAN latency (sub-5ms wired, low single digits ms over
WiFi once the radio is warm — see Notes).

### Lid handling

`HandleLidSwitch=ignore` set on all three laptop hosts. Closing the lid
does not suspend the machine or drop an active session. Confirmed on
`novo1`, `chromebook`, and `ubuntu` — the latter required an explicit
`systemctl restart systemd-logind` after editing the config, since a
running daemon does not re-read its config file on its own.

## Hardware baselines

Captured 2026-08-27; re-checked 2026-09-19.

| Host | Drive | Health, 2026-08-27 | Health, 2026-09-19 |
|---|---|---|---|
| `novo1` | HGST HTS545050A7E380 (Travelstar Z5K500) | 0 reallocated sectors, 0 pending, 20 reallocation events, 14,165 power-on hours | unchanged: 0 / 0 / 20 events, SMART PASSED, 14,737 power-on hours, 47 °C |
| `ubuntu` | HGST HTS725050A7E630 (Travelstar Z7K500) | 0 reallocated sectors, 0 pending, 0 events, 3,099 power-on hours | unchanged: 0 / 0 / 0, SMART PASSED, 3,597 power-on hours |
| `chromebook` | eMMC, soldered | `life_time 0x01 0x03`, `pre_eol_info 0x01` — 20–30% of write cycles consumed on the user area | unchanged |
| `illntentpc` | Intel SSDPEKNW512G8 NVMe, 477 GB | — | Windows reports Healthy / OK (no SMART detail collected); 120 GB free |
| Note 10+ | internal UFS | — | 229 GB user partition, 9% used |

`smartd` enabled and running on both Lenovo hosts. eMMC has no SMART
support; `/sys/block/mmcblk1/device/` reports the equivalent values.
`chromebook`'s `smartd` unit is in a `failed` state (since 2026-09-15): expected,
since there is no SMART device for it to monitor; disabling it would clear the
failure. Chromebook storage is soldered and not replaceable — keep workloads
read-mostly.

## Notes

### LVM under-allocation
Both Ubuntu installers left part of the volume group unallocated. Extended
online, no downtime:
```
sudo lvextend -l +100%FREE /dev/ubuntu-vg/ubuntu-lv
sudo resize2fs /dev/mapper/ubuntu--vg-ubuntu--lv
```
| Host | Before | After |
|---|---|---|
| `novo1` | 98 GB | 455 GB |
| `chromebook` | 13 GB | 26 GB |
| `ubuntu` | not recorded | 455 GB (volume group fully allocated as of 2026-09-19; whether the installer or a manual extend did it wasn't recorded) |

### Broadcom wireless on `novo1`
BCM43228 had no in-tree driver (`lshw` showed `driver=bcma-pci-bridge`).
Resolved with the proprietary `wl` driver, packaged as `broadcom-sta-dkms`
(6.30.223.271; DKMS — rebuilds on kernel updates, check `dkms status` if wireless
disappears after an upgrade). Re-checked 2026-09-19: `wl` loaded, interface up,
Wi-Fi power-save off. (This note previously named the package
`bcmwl-kernel-source`; the installed package is `broadcom-sta-dkms`.)

### GPU and NVIDIA driver on `novo1`
Besides the Intel integrated graphics, the B590 carries an NVIDIA GeForce 610M
(GF119M). The NVIDIA userspace stack and a DKMS driver (`615.71.09`, built for
both installed kernels) are installed on this headless server. Not documented
anywhere before; unused by any workload here.

**Finding and fix, 2026-09-20:** the installed driver (`nvidia-driver-open`, the open kernel modules) does not
support this GPU, and `nouveau` owns it. Something kept running `modprobe nvidia` about twice a second (7,866
attempts in one hour, each failing with "already bound to nouveau"), which held a core busy and kept `novo1` at
about 80 °C under light load; `nvidia-persistenced.service` was in a failed/retry state. Fixed reversibly, nothing
uninstalled: `systemctl mask --now nvidia-persistenced.service` and `/etc/modprobe.d/zz-disable-nvidia.conf`
(`blacklist nvidia`, `install nvidia /bin/false`). After a reboot: 0 load attempts in 45 s, load 0.6, about 60 °C.
To undo, delete that file and unmask the service.

### Network backend on `novo1`
Running NetworkManager (`systemd-networkd` disabled, `renderer:
NetworkManager` declared in netplan) to get persistent WiFi power-save
control — `wifi.powersave = 2` in
`/etc/NetworkManager/conf.d/default-wifi-powersave-on.conf`. Fixed
intermittent association drops on the Broadcom card. `chromebook` remains
on `systemd-networkd`. Divergence still open — see
`decisions/003-networkmanager-on-b590.md`.

### Pre-existing services removed from `novo1`
`novo1` was running a substantial, undocumented service stack unrelated
to this lab's plan: Nextcloud, Rocket.Chat (plus bundled Mongo), Wekan
(plus FerretDB), Mosquitto, Prometheus, and sabnzbd, alongside several
unused CLI snaps (`doctl`, `powershell`, `slcli`, `tldr`, `wormhole`).
None of it appears in this repo's stated roles or phases. Removed
2026-09-18 at operator request after a security review turned it up —
each removal left a `snapd` recovery snapshot (~31-day window, `snap
restore <id>` to undo). `novo1`'s snap list is now just the base
runtimes, `canonical-livepatch`, and `snapd`. Ollama was installed here
for the LLM council project (ADR 009) and removed again on 2026-09-19 when
the panel moved to the Note 10+.

### CPU instruction set limits (`chromebook`, `novo1`, `ubuntu`)
None of the three Linux hosts supports AVX2/FMA — confirmed via `grep -E
'avx2|fma' /proc/cpuinfo` (empty on each; `ubuntu`'s i5-2520M is the same
Sandy Bridge generation as `novo1`'s Ivy Bridge, re-checked 2026-09-19).
`chromebook` lacks even first-generation AVX; `novo1` and `ubuntu` have it.
Hardware virtualization (the `vmx` flag) is exposed on `novo1` and `chromebook`
but not on `ubuntu`; its i5-2520M supports VT-x, so it is presumably switched off
in the firmware. Worth knowing if VMs or a hypervisor are ever considered.
Relevant for any future CPU-bound compute placement on this fleet:
llama.cpp-based inference (Ollama) on `chromebook` degraded badly
enough under JSON-schema-constrained decoding to look like a hang
rather than merely "slow" — see ADR 009. Not obviously relevant to
non-ML workloads, but worth checking `/proc/cpuinfo` before assuming
two "similar enough" hosts perform similarly on compute-heavy tasks.

### Chromebook WiFi latency (transient, resolved)
First ping to `chromebook` after a period of inactivity has been observed
as high as 1275ms, dropping to normal (2–30ms) over the following several
pings. Consistent with the wireless radio waking from a power-save state
rather than an ongoing fault — same underlying mechanism as the Broadcom
fix above, on Intel hardware. Not yet made persistent on this host; if it
recurs, apply the equivalent `iwconfig`/NetworkManager powersave fix here.

### 1 TB flash drive — failed integrity test
`dd` write test failed at 66 GB of a claimed 1 TB, with USB timeouts
(`error -110`) and I/O errors throughout, running at ~3 MB/s (well below
even USB 2.0 speed). Counterfeit capacity and a physically failing
controller. This closes the ambiguity noted in the original boot-failure
postmortem — the failure was media, and this is a second, independent
confirmation. **Drive discarded.** Ventoy media now lives on the 250 GB
SSD only.

### USB disk errors on `illntentpc` (disk not identified)
Over the 30 days to 2026-09-19 the Windows System log recorded 119 `UASPStor`
event 129 entries ("Reset to device, `\Device\RaidPort8`, was issued"), 54 `disk`
event 51 entries (an error "during a paging operation" on `\Device\Harddisk1`) and
smaller counts of `disk` 153 and NTFS 140, all against a USB-attached disk. It is
not attached now, so it could not be identified. If it is the 250 GB portable SSD,
test it before relying on it as a backup target. These errors did not coincide with
the workstation's unexpected shutdowns (none in the 15 minutes before any of them).

### Scheduled jobs on `illntentpc`
- Cron (in WSL), every minute: `~/sysmon/collector.py` (the ESP32 gadget's data source; needs a loaded `ssh-agent`, see
  above). Not in this repo: the copy in `services/esp32-fleet-gadget/collector/` is the source.
- Windows scheduled task `WSL-KeepAlive` (registered 2026-09-20, at logon): runs
  `wsl.exe -d Ubuntu-24.04 -e sh -c "exec sleep infinity"` so WSL, and its cron jobs, keep running after a Windows
  restart. Not yet proven by a restart. Remove with `Unregister-ScheduledTask WSL-KeepAlive`.

### State snapshot (2026-09-19)
| Host | Kernel | Uptime | Reboot pending |
|---|---|---|---|
| `ubuntu` | 7.0.0-30 | 13 days | yes (7.0.0-31 installed) |
| `novo1` | 6.8.0-138 | 17 days | yes (6.8.0-139, libc6) |
| `chromebook` | 6.8.0-139 | 4 days | no |

### State snapshot (2026-09-20, after the reboots)
| Host | Kernel | Uptime at check | Reboot pending |
|---|---|---|---|
| `ubuntu` | 7.0.0-31 | rebooted 2026-09-20 | no |
| `novo1` | 6.8.0-139 | rebooted 2026-09-20 | no |
| `chromebook` | 6.8.0-139 | 5 days | no |

The pending reboots recorded above were done on 2026-09-20 (`ubuntu`: plain LVM, no disk encryption, `ssh` and
`ollama` start at boot; both hosts came back over SSH within about two minutes). `illntentpc` was not rebooted.

Docker and k3s are not installed on any host (Phases 2 and 3 not started).
Ansible (`ansible-core` 2.16.3 in the workstation's WSL) reaches all three
Linux hosts with `ansible all -m ping` using the inventory in `ansible/`.
`ubuntu` runs a full desktop install (GNOME/`gdm`, CUPS, avahi, Thunderbird and
Firefox snaps) — relevant to its planned k3s-server role, both for memory and for
attack surface.

## Phase 0 — complete

- [x] Reachable from workstation
- [x] SSH keypair generated on workstation
- [x] Passwordless key auth on all three Linux hosts
- [x] SSH config with short aliases
- [x] Password authentication disabled on all three hosts
- [x] Lids close without consequence (all three laptops)
- [x] UFW active, deny-incoming, SSH-only, all three hosts
- [x] Hostnames renamed (`novo1`, `ubuntu`, `chromebook`), `/etc/hosts`
      updated to match on each host
- [x] Cross-host name resolution — all three resolve each other
- [x] Documented and committed

## Next

Phase 1 — Ansible. Inventory covering all three Linux hosts, playbooks for
users, SSH hardening, base packages, UFW. The repeated manual work in this
file (three hosts, same commands, three times each) is the argument for it.
Playbooks for SSH, packages and UFW already exist in `ansible/`, and
connectivity is verified (see the state snapshot above).
