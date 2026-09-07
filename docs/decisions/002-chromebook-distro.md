# 002. Chromebook distro: Ubuntu Server over Arch

**Date:** 2026-09-06 (backfilled — decision was made and acted on 2026-08-26)
**Status:** Accepted

## Context

The Chromebook (`chromebook`, Acer Chromebook 15, Celeron N3350, 4 GB
RAM, 29 GB eMMC) came into the lab already running Arch Linux, installed
prior to this project starting. It was never deliberately chosen — it
was the operating system already on the hardware when the machine was
repurposed for the lab.

Session 04 assigned this host a dual, contradictory role: "network
services + Arch playground." Those two purposes conflict. A host
running services other machines depend on needs to be stable and
predictable. A playground host, by definition, is not something
anything else should rely on.

Separately, the machine had 6.5 GB of free disk space out of 27 GB
total under the existing Arch + KDE Plasma install — most of it
consumed by the desktop environment on a machine intended to run
headless.

## Options considered

**1. Keep Arch, strip the desktop environment.** Removes the KDE
footprint without a full reinstall. Fastest path to reclaiming disk
space. Leaves the host on a rolling-release distribution, which is
disqualifying for anything the lab depends on — a rolling release can
break on any given update, with no fixed release cycle to test against
first.

**2. Reinstall as Debian or Ubuntu Server, no desktop.** Matches the
other two Linux hosts' distribution family (`apt`, not `pacman`),
removing a real inconsistency that would otherwise complicate Ansible
playbooks in Phase 1 — one package-manager branch instead of two.
Fixed-release, not rolling. Solves the disk problem as a side effect of
a clean install rather than a separate cleanup step.

**3. Leave it as Arch, assign no dependent role.** Keep the machine as a
genuine playground only, hosting nothing the lab needs. Avoids a
reinstall entirely. Leaves the disk-space problem unresolved and keeps
a permanently idle host in the fleet rather than a working fourth node.

## Decision

**Option 2.** Reinstalled as Ubuntu Server 24.04.4 LTS, matching
`novo1` and `ubuntu`.

This decision was effectively made through the reinstall itself during
a wireless-connectivity troubleshooting session, rather than through a
deliberate options review beforehand — hence this record being written
after the fact. The reasoning holds up under review regardless:

- Fleet consistency was worth more than preserving Arch exposure.
  Learning a second package manager is a reasonable thing to want, but
  a lab's dependency hosts are the wrong place to practice it — the
  Bandit challenge and general exploration are lower-stakes venues for
  that curiosity if it resurfaces.
- The disk problem and the role-conflict problem were the same
  problem, solved by the same action. A clean, headless Ubuntu Server
  install has no desktop environment to consume space in the first
  place.
- Rolling-release is specifically wrong for a host anything else
  depends on. Fixed LTS releases are testable and reproducible in a
  way `pacman -Syu` on an arbitrary day is not.

## Consequences

**Positive**
- All three Linux hosts now share one distribution family and one
  package manager, removing a fork Ansible playbooks would otherwise
  need to handle.
- Reinstall also resolved the disk-space problem as a byproduct: 13 GB
  usable rose to 26 GB after the subsequent LVM extend (see
  `docs/hosts.md`), versus 6.5 GB free under the prior Arch + KDE
  install.
- The host now has an unambiguous single role — network services —
  rather than the contradictory dual role assigned in Session 04.

**Negative**
- No hands-on Arch/`pacman` exposure remains anywhere in the lab. Not
  currently a loss against any stated goal; flagged here only because
  it was previously listed as a mild point in Arch's favor.
- The reinstall was prompted by an immediate networking problem rather
  than a scheduled decision point, so it happened without the
  deliberation this kind of change usually gets in this lab. The
  outcome held up on review, but the process is worth naming as a
  minor inconsistency in how decisions are normally made here.

## Follow-up
None. Decision is fully acted on; this document exists to record the
reasoning after the fact.
