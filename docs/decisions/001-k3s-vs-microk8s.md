001. k3s over microk8s
Date: 2026-08-28 Status: Accepted
Context
The lab plan calls for a multi-node Kubernetes cluster: control plane on ubuntu-ThinkPad-T420s (8 GB), agent on ubuntuserver (6 GB). Both are Sandy Bridge laptops from 2011–2012.

microk8s is already installed on ubuntuserver, alongside lxd, standalone etcd, and keepalived — all snaps accumulated before any of them had a defined role. None are in use.

A distribution needs to be chosen and the others removed. Having two container orchestration platforms installed and neither running is the state to exit.
Options considered
1. k3s. Single binary, roughly 60 MB. Purpose-built for constrained and edge environments. Ships SQLite as its default datastore instead of etcd, which meaningfully reduces memory and disk I/O. Multi-node join is one command with a token. CNCF-certified — a conformant Kubernetes distribution, not a subset.

2. microk8s. Canonical's distribution, already installed here. Snap-based, with add-ons enabled via microk8s enable. Also CNCF-certified. Heavier resting footprint than k3s. Multi-node clustering works but involves more moving parts. Being snap-based means it carries snapd's update behaviour, which is not always wanted on a server.

3. kubeadm / upstream Kubernetes. The most educationally complete option — you assemble every component yourself. Also the heaviest, and it would consume most of Phase 3 on cluster bootstrap rather than on using Kubernetes.

4. Neither — stay with Docker and Compose. Simplest. Skips the entire orchestration layer, which is the part the target job descriptions actually name.
Decision
k3s.

Reasoning, in order of weight:

Memory. 6 GB on the agent node, 8 GB on the server, with other services expected alongside. k3s has the smallest resting footprint of the viable options, and SQLite instead of etcd removes a memory-hungry component.
Disk I/O. Both nodes are on 5400 and 7200 RPM spinning disks. etcd is sensitive to fsync latency, and on mechanical media that produces missed heartbeats and spurious leader elections — failures that present as random cluster instability. Avoiding etcd sidesteps this entirely.
Multi-node simplicity. Server, then agents join with a token and a URL. Less to go wrong on hardware that has already been uncooperative.
Job relevance. k3s appears more often in homelab and edge job descriptions. Either distribution transfers, but this one is more commonly named.
CKA preparation. k3s is conformant. Exam material transfers.

microk8s is a reasonable choice and this decision is not a criticism of it. The deciding factor is hardware constraints, not quality.
Consequences
Positive

Lowest resource cost on hardware that has little to spare.
Straightforward two-node cluster in Phase 3.
Removing the overlapping snaps frees memory and reduces the number of services running without purpose.

Negative

SQLite as the default datastore means no built-in HA control plane. Not a constraint at this scale — a single control plane is correct for a two-node lab — but it is a difference from production clusters worth being aware of.
k3s bundles opinionated defaults: Traefik as ingress, ServiceLB, local-path storage. Convenient, and slightly further from vanilla Kubernetes than kubeadm would be. Components can be disabled at install if needed.

Neutral

Some Helm charts assume specific storage or ingress classes. k3s's defaults usually work; occasionally a chart needs a values override.
Actions
Removing the superseded and unused snaps from ubuntuserver:

sudo snap remove --purge microk8s

sudo snap remove --purge lxd

sudo snap remove --purge etcd

sudo snap remove --purge keepalived

microk8s — superseded by this decision
lxd — overlapping container platform, no defined role
etcd — redundant; k3s ships its own datastore
keepalived — provides virtual-IP failover across multiple nodes, so it does nothing on a single host

k3s is not installed yet. Installation belongs to Phase 3. Phase 0 (networking, SSH keys, firewall) and Phase 1 (Ansible) come first, and installing the cluster early would repeat the accumulation pattern this decision exists to correct.
Follow-up
Remove the four snaps listed above
Audit remaining snaps — nextcloud, rocketchat-server, wekan, sabnzbd, mosquitto, prometheus — and remove any without a defined role. Services wanted later belong in the cluster, not as snaps.
Record df -h / before and after

