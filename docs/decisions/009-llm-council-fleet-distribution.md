# 009. Distribute the LLM council panel across the fleet

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
- `chromebook` initially kept Ollama and `gemma2:2b` installed with
  the UFW rule still open after the panel moved off it — reverted
  2026-09-18 (see Follow-up, now checked off): Ollama service, binary,
  model data, and the `11434` UFW rule all removed, back to the
  SSH-only baseline.

## Follow-up

- [ ] Port the manual systemd-override + UFW steps in
      `runbook-ollama-lan-setup.md` into an Ansible playbook, consistent
      with Phase 1's direction — `ansible/ufw.yml` currently only covers
      the SSH-only baseline.
- [x] Decide whether to remove Ollama/`gemma2:2b` from `chromebook` or
      repurpose it — removed 2026-09-18, back to SSH-only baseline.
- [ ] `council.py` has no auth/rate-limiting in front of the Ollama
      calls it makes. Revisit if the LAN trust model here ever changes
      (same caveat already tracked in ADR 007's follow-up).

---

## Addendum — 2026-09-19: inference moved to a phone; council hardened; Panelist A bake-off

Everything above records the decision as made on 2026-09-18 and is left as
written. What changed the next day, and why:

### What changed

- **Panelists A and C now run on a repurposed phone** (Samsung Galaxy Note 10+,
  Snapdragon 855) as two API-key-protected llama.cpp `llama-server` processes
  (`:8081` Llama 3.2 3B, `:8080` Gemma 2 2B). Panelist B stays local on
  `illntentpc`. Setup: `runbook-note10-llama-server.md`; the machine is described
  in `hosts.md`.
- **`novo1` was retired from the council.** Its Ollama service, binary, models,
  user and the `11434` UFW rule were removed (steps in
  `runbook-ollama-lan-setup.md`, "Undoing this runbook"). `ubuntu` keeps its
  Ollama and is now Panelist A's slow fallback; Panelist C has no fallback.
- **`council.py` was hardened**: output validation with bounded retries, a
  `llamaserver://` backend, fallbacks, peer-only voting with a defined tie-break,
  a deterministic answer (the curator can no longer supply content), progress
  output, checkpoints, and `--check`. See `services/llm-council/README.md`.

### Why the phone

The three lab laptops have no AVX2 and two physical cores, so CPU inference on
them is slow: about 1 token/s was measured on `novo1`, and a full council run
took 12+ minutes, mostly waiting on `ubuntu`. The phone's Snapdragon 855 has
NEON dot-product instructions and, with a llama.cpp build compiled for them
(ARMv8.2 + dotprod + fp16), measured 31 tokens/s prompt processing and 9.25
tokens/s generation on a 3B Q4_K_M model when cool and charged (18.9 and 7.3 on the
same build when it was already hot and at low battery; the generic prebuilt
Termux package measured 8.2 and 5.75 earlier, at low battery). Two servers running
at once share the CPU and memory bandwidth and each keep only about 60–65% of solo
speed, so they are effectively serialized. Moving A and C there cut one
measured run from 12.5 to 5.8 minutes; later runs varied between 5.8 and 12
minutes because of retries, not hardware.

### Consequences (additional)

- **Positive:** the fleet's fastest inference node was an unused phone; two
  laptops were rolled back to the SSH-only baseline (smaller attack surface).
- **Negative:** the phone is now a single point of failure for two of three
  panelists. Its servers and `sshd` do not survive a reboot. Android has no
  firewall, so the ports are protected by API key only. Sustained load heats it:
  35 minutes of continuous inference while charging over USB reached battery
  45.8 °C and CPU 64 °C, so long runs are paused above 42 °C.

### Panelist A bake-off

Panelist A (Llama 3.2 3B) was the weak link on both quality and time. A bake-off
tried to find a better model for that slot.

**Method.** Each candidate ran through the council's own `get_position`,
`get_rebuttal` and `get_vote` (same prompts, validators and retries) against a
`llama-server` with identical flags, one candidate at a time: 4 topics x 2 samples
for positions, plus 2 rebuttals and 2 votes on fixed peer answers, so 12 calls per
candidate. A thermal guard paused the run whenever the battery exceeded 42 °C and
started each candidate below 38 °C; pauses fall outside the timed sections.
"Clean" means the final answer had no validator warning. For the factual question
("the 10 most important words to learn in Mandarin Chinese") the answers were also
scored for Chinese terms present and for pinyin matching the characters (checked
with `pypinyin`).

| Candidate | Position calls clean | Rebuttals / votes clean | Mean call | 12 calls total |
|---|---|---|---|---|
| Llama 3.2 3B (baseline, run 1, unguarded) | 7/8 | 2/2, 2/2 | 93 s | 1122 s |
| Llama 3.2 3B (re-run, guarded) | 7/8 | 2/2, 2/2 | 98 s | 1175 s |
| Granite 3.3 2B | 8/8 | 2/2, 2/2 | 81 s | 976 s |
| SmolLM2 1.7B | 7/8 | 1/2, 2/2 | 83 s | 993 s |
| Phi-3.5-mini | unusable: every call fails (HTTP 400, see below) | | | |

**Findings.**

1. **The validators measure form, not substance.** Every candidate passed them
   at 7–8 of 8 while giving weak or empty answers to the factual question:
   Llama, over four samples, gave one usable list (10 romanized phrases with pinyin
   and glosses, but no characters) and three failures: a preface with no words, a
   numbered list with the words missing, and garbled pinyin; Granite gave category-style lists with mostly wrong pinyin
   (1 of 9 pairs exact) in one sample and no words at all in the other; SmolLM2 gave
   no words in either sample ("Strongly Agree", a preface). By contrast the council's
   other panelists produced 10 real items with characters and pinyin on the same
   question (Qwen 2.5 3B: 9/10 exact tone marks, 10/10 tone-less; Gemma 2 2B: 8/10
   and 10/10).
2. **No candidate justifies replacing Llama 3.2 3B.** Granite and SmolLM2 were
   11–17% faster in total (single run each; the two Llama runs differed by 4.7%, so
   this is a modest edge that one run per candidate cannot fully establish), and
   Granite's 8/8 clean rate did not come with better content.
3. **Phi-3.5-mini cannot be used with this pipeline.** With this llama.cpp build,
   any grammar-constrained request (`json_schema` or `json_object`) fails with
   "Failed to initialize samplers" for Phi's vocabulary; without a grammar it works
   but wraps its JSON in code fences, which the council does not parse.
4. **Thermal behaviour:** the guard paused the Llama re-run for about 320 s in total
   and SmolLM2 for 160 s; peak battery temperature was 42.4 °C.

**Decision.** Panelist A stays Llama 3.2 3B. Caveats: 8 position calls and 2
Mandarin samples per candidate is a small sample, only three small models were
tried, and content was judged on one factual question by objective metrics plus a
manual read.

### Follow-up (additional)

- [ ] Add answer-substance checks to the validators (for a "top N" question, require
      N items; require the answer to contain the thing asked for), since form checks
      alone let empty answers through.
- [ ] Try a larger Meta model (an 8B-class Llama) in slot A; expect it to be
      considerably slower on this phone.
- [ ] Give Panelist C a fallback host, or accept a two-panelist run when the phone
      is down.
- [ ] Repeat the bake-off with more topics and samples before drawing finer
      conclusions.
