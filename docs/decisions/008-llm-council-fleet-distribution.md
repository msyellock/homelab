# 008. Distribute the LLM council panel across the fleet

**Date:** 2026-09-18
**Status:** Accepted

## Context

Built a local, free, multi-model deliberation-and-vote pipeline
("LLM council"): a prompt is fanned out to 3 panelist LLMs, each states
a position, they see each other's positions and can revise, then vote.
A separate, non-voting curator model formats the exchange and writes
the final synthesis. Everything runs on free, open-weight models via
Ollama — no API cost, no rate limits.

The first working version ran all 3 panelists plus the curator on
`illntentpc` alone, using one 7-8B model per panelist (Llama 3.1 8B,
Mistral 7B, Qwen 2.5 7B) for genuine cross-lab diversity.

## Options considered

**1. All panelists local, one box.** Simplest to build. Failed
immediately: the kernel OOM-killed Ollama's `llama-server` process
loading a single 7-8B model on `illntentpc` (7.6 GB RAM) — confirmed
via `dmesg`/`journalctl`, not a concurrency bug. This box cannot hold
even one 7-8B model reliably, let alone three.

**2. Downsize to ~2-3B models, still all local.** Fits in RAM, but
forces the 3 panelist calls to run strictly sequentially — no host can
hold more than one model loaded at a time regardless of size, so
`asyncio.gather`-style parallel fan-out isn't actually safe with everything
stacked on one machine. Also puts 100% of the inference load, and any
single-host issue, on the one machine already doing everything else.

**3. Distribute across the fleet — one panelist per host.** Each
panelist's model lives on its own machine's RAM, reachable over the LAN.
Restores genuine parallel fan-out (no shared-RAM contention between
panelists) and spreads compute across hardware that was otherwise idle.

## Decision

**Option 3.** Curator plus one panelist stay local on `illntentpc`
(comfortably handles two ~2-3B models plus orchestration); the other
two panelists run on remote fleet hosts, each reachable at
`http://<host-ip>:11434`.

| Panelist | Model | Lab | Host |
|---|---|---|---|
| A | Llama 3.2 3B | Meta | `ubuntu` |
| B | Qwen 2.5 3B | Alibaba | `illntentpc` (local) |
| C | Gemma 2 2B | Google | `chromebook` → `novo1` (see below) |

Model sizing (7-8B → ~2-3B) was driven by per-host RAM fit, not just
speed — see runbook `docs/runbook-ollama-lan-setup.md` for the setup
steps (systemd override to bind `0.0.0.0:11434`, UFW rule scoped to
`192.168.1.0/24`).

## Consequences

**Positive**
- No host holds more than one model in RAM — the actual RAM-exhaustion
  failure from Option 1 doesn't recur on any host.
- Genuine parallel fan-out across hosts, not simulated by round-robin.
- Reuses the fleet's existing SSH/UFW trust model (ADR 006, ADR 007)
  rather than inventing new access control for this project.

**Negative**
- Ollama's HTTP API has no authentication. Opening `11434/tcp` to the
  LAN subnet means anything on `192.168.1.0/24` can submit inference
  requests to a panelist host and consume its CPU. Accepted under the
  same single-operator trust model as ADR 007; scoped to the LAN, not
  `Anywhere`.
- **`chromebook`'s CPU (Celeron N3350) has no AVX2/FMA at all** —
  confirmed via `/proc/cpuinfo`. llama.cpp's CPU inference path
  degrades badly without it. A plain unconstrained prompt completed
  normally (8s). The identical prompt under JSON-schema-constrained
  decoding (used for every panelist call, to get structured output)
  generated 1400+ tokens without converging and was still incomplete
  after 42 minutes, manually killed. Not a chromebook-specific software
  bug — any model would hit the same wall on that CPU. This is the
  reason a hard `num_predict` ceiling was added to every call site in
  `council.py` afterward, independent of which host is involved.
- Swapped Panelist C to `novo1` (i3-2348M — also lacks AVX2, but has
  first-generation AVX plus 4 real cores @ 2.3GHz vs `chromebook`'s 2
  cores @ 1.1GHz with no AVX support at all). Confirmed working: same
  schema, same prompt, converged normally in 108s.

**Neutral**
- `novo1` was briefly considered too slow on its first measurement
  (~0.5 tok/s), before its unrelated pre-existing service stack
  (Nextcloud, Rocket.Chat, Wekan, Mosquitto, Prometheus, sabnzbd — none
  of it part of this repo's documented plan) was removed at operator
  request, following a security review. CPU contention from that stack
  was a likely confound in the first measurement; performance after
  removal was not independently re-isolated from the AVX/host swap
  before this was written. See `docs/hosts.md` Notes for the cleanup.
- `chromebook` still has Ollama and `gemma2:2b` installed — the UFW
  rule and install were never reverted after the panel moved off it.
  See Follow-up.

## Follow-up

- [ ] Port the manual systemd-override + UFW steps in
      `runbook-ollama-lan-setup.md` into an Ansible playbook, consistent
      with Phase 1's direction — `ansible/ufw.yml` currently only covers
      the SSH-only baseline.
- [ ] Decide whether to remove Ollama/`gemma2:2b` from `chromebook` or
      repurpose it for something within its actual "Network services"
      role, since it's currently installed and reachable but unused.
- [ ] `council.py` has no auth/rate-limiting in front of the Ollama
      calls it makes. Revisit if the LAN trust model here ever changes
      (same caveat already tracked in ADR 007's follow-up).
