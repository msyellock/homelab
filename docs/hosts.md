Lab hosts
Hostname	Machine	CPU	RAM	Storage	OS	Role
illntentpc	HP	i5-1135G7	16 GB	477 GB	Windows 11	Workstation / Ansible control
ubuntu	ThinkPad T420s	i5-2520M	8 GB	465 GB HDD (7200 RPM)	Ubuntu 24.04	k3s server
novo1	Lenovo B590	i3-2348M	6 GB	465 GB HDD (5400 RPM)	Ubuntu Server 24.04	k3s agent
chromebook	Acer Chromebook 15 (Google "Sand")	Celeron N3350	4 GB	29.1 GB eMMC	Ubuntu Server 24.04.4	Network services

Hostnames match SSH usernames by design — a single-operator lab, so the coupling between hostname and account was an acceptable tradeoff. See decisions/006-hostname-naming.md.

Portable storage: 250 GB portable SSD (backup target), 1 TB flash — failed integrity test, discarded. See Notes.

Network

Subnet 192.168.1.0/24, gateway 192.168.1.1 (Verizon Fios). DHCP dynamic range: 192.168.1.100 – 192.168.1.254.

Reservations sit inside the dynamic range rather than the free .2–.99 block. Functional, since the router honours reservations either way — renumbering into the static block would be a tidiness improvement, not a fix.

Host	Interface	Hardware	MAC	Address
illntentpc	wired	—	48:9e:bd:df:cc:97	192.168.1.161
illntentpc	wireless	—	5c:61:99:5a:6a:0d	192.168.1.155
ubuntu	enp0s25	Intel Gigabit	f0:de:f1:d9:3a:80	192.168.1.162
ubuntu	wlp3s0	—	10:0b:a9:93:3f:04	192.168.1.163
novo1	enp4s0	Realtek RTL8111/8168 Gigabit	3c:97:0e:90:83:8f	192.168.1.160
novo1	wlp3s0	Broadcom BCM43228 802.11a/b/g/n	9c:2a:70:88:4e:e9	192.168.1.159
chromebook	wlp1s0	Intel Wireless 7265 (dual band AC)	5c:5f:67:60:f0:ea	192.168.1.153
SSH

Key-only. Password authentication disabled on all three Linux hosts. Aliased in ~/.ssh/config on the workstation — ssh novo1, ssh ubuntu, ssh chromebook, no IPs or usernames typed.

novo1 runs wired for normal operation (.160). Wireless (.159) is a fallback if the Ethernet cable is disconnected.

Private key exists only on the workstation. The Linux hosts hold no private key and cannot SSH outward to one another or elsewhere — by design, not oversight. See decisions/006-hostname-naming.md for the related reasoning on single-key, single-location key management.

Firewalls

UFW active on all three Linux hosts. Default deny incoming, default allow outgoing, SSH (22/tcp, IPv4 and IPv6) is the only inbound rule.

sudo ufw status verbose
Status: active
Default: deny (incoming), allow (outgoing), disabled (routed)
22/tcp      ALLOW IN  Anywhere
22/tcp (v6) ALLOW IN  Anywhere (v6)
Name resolution

/etc/hosts on each Linux host contains entries for the other two, alongside its own 127.0.1.1 line. All three resolve each other by hostname at normal LAN latency (sub-5ms wired, low single digits ms over WiFi once the radio is warm — see Notes).

Lid handling

HandleLidSwitch=ignore set on all three laptop hosts. Closing the lid does not suspend the machine or drop an active session. Confirmed on novo1, chromebook, and ubuntu — the latter required an explicit systemctl restart systemd-logind after editing the config, since a running daemon does not re-read its config file on its own.

Hardware baselines

Captured 2026-08-27.

Host	Drive	Health
novo1	HGST HTS545050A7E380 (Travelstar Z5K500)	0 reallocated sectors, 0 pending, 20 reallocation events, 14,165 power-on hours
ubuntu	HGST HTS725050A7E630 (Travelstar Z7K500)	0 reallocated sectors, 0 pending, 0 events, 3,099 power-on hours
chromebook	eMMC, soldered	life_time 0x01 0x03, pre_eol_info 0x01 — 20–30% of write cycles consumed on the user area

smartd enabled and running on both Lenovo hosts. eMMC has no SMART support; /sys/block/mmcblk1/device/ reports the equivalent values. Chromebook storage is soldered and not replaceable — keep workloads read-mostly.

Notes
LVM under-allocation

Both Ubuntu installers left part of the volume group unallocated. Extended online, no downtime:

sudo lvextend -l +100%FREE /dev/ubuntu-vg/ubuntu-lv
sudo resize2fs /dev/mapper/ubuntu--vg-ubuntu--lv
Host	Before	After
novo1	98 GB	455 GB
chromebook	13 GB	26 GB
Broadcom wireless on novo1

BCM43228 had no in-tree driver (lshw showed driver=bcma-pci-bridge). Resolved with bcmwl-kernel-source (DKMS — rebuilds on kernel updates, check dkms status if wireless disappears after an upgrade).

Network backend on novo1

Running NetworkManager (systemd-networkd disabled, renderer: NetworkManager declared in netplan) to get persistent WiFi power-save control — wifi.powersave = 2 in /etc/NetworkManager/conf.d/default-wifi-powersave-on.conf. Fixed intermittent association drops on the Broadcom card. chromebook remains on systemd-networkd. Divergence still open — see decisions/003-networkmanager-on-b590.md.

Chromebook WiFi latency (transient, resolved)

First ping to chromebook after a period of inactivity has been observed as high as 1275ms, dropping to normal (2–30ms) over the following several pings. Consistent with the wireless radio waking from a power-save state rather than an ongoing fault — same underlying mechanism as the Broadcom fix above, on Intel hardware. Not yet made persistent on this host; if it recurs, apply the equivalent iwconfig/NetworkManager powersave fix here.

1 TB flash drive — failed integrity test

dd write test failed at 66 GB of a claimed 1 TB, with USB timeouts (error -110) and I/O errors throughout, running at ~3 MB/s (well below even USB 2.0 speed). Counterfeit capacity and a physically failing controller. This closes the ambiguity noted in the original boot-failure postmortem — the failure was media, and this is a second, independent confirmation. Drive discarded. Ventoy media now lives on the 250 GB SSD only.

Phase 0 — complete
 Reachable from workstation
 SSH keypair generated on workstation
 Passwordless key auth on all three Linux hosts
 SSH config with short aliases
 Password authentication disabled on all three hosts
 Lids close without consequence (all three laptops)
 UFW active, deny-incoming, SSH-only, all three hosts
 Hostnames renamed (novo1, ubuntu, chromebook), /etc/hosts updated to match on each host
 Cross-host name resolution — all three resolve each other
 Documented and committed
Next

Phase 1 — Ansible. Inventory covering all three Linux hosts, playbooks for users, SSH hardening, base packages, UFW. The repeated manual work in this file (three hosts, same commands, three times each) is the argument for it.
