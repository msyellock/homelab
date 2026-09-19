# LLM Council

A local, free, multi-model deliberation-and-vote pipeline. A prompt is
fanned out to 3 panelist LLMs on separate machines (Ollama or llama.cpp
`llama-server`), each states a position, they see each other's positions
and can revise, then vote. A separate non-voting curator model writes a
short note on where they agree and disagree; the answer itself is the
winning position's own text.

Why this exists, and the hardware findings that shaped it (RAM ceiling
on `illntentpc`, AVX2 gap on the old laptops, the move to a phone for
inference, and a bake-off for Panelist A), are in
[`docs/decisions/009-llm-council-fleet-distribution.md`](../../docs/decisions/009-llm-council-fleet-distribution.md).
The LAN setup steps this depends on are in
[`docs/runbook-ollama-lan-setup.md`](../../docs/runbook-ollama-lan-setup.md)
(Ollama hosts) and
[`docs/runbook-note10-llama-server.md`](../../docs/runbook-note10-llama-server.md)
(the phone).

## Current panel

| Panelist | Model | Lab | Host |
|---|---|---|---|
| A | Llama 3.2 3B (`llama3.2-3b`) | Meta | Note 10+ `:8081` (`llama-server`); fallback `ubuntu` (Ollama `llama3.2:3b`, slow) |
| B | `qwen2.5:3b` | Alibaba | local (`illntentpc`, Ollama) |
| C | Gemma 2 2B (`gemma2-2b`) | Google | Note 10+ `:8080` (`llama-server`); no fallback |

Curator: `llama3.2:3b`, local (Ollama), non-voting. Panelist C used to
run on `novo1`; that Ollama install was removed on 2026-09-19.

## Setup

On `illntentpc`:
```
python3 -m pip install --user ollama httpx
ollama pull llama3.2:3b     # curator (and the fallback model on ubuntu)
ollama pull qwen2.5:3b      # Panelist B
```

`llamaserver://<ip>:<port>` hosts in `PANEL` (the phone) are set up
with `docs/runbook-note10-llama-server.md`. Their API keys are read from
`LLAMA_SERVER_API_KEY` or `~/.config/council/llama-server-<ip>-<port>.key`
(then `-<ip>.key`); keys are never stored in this repo. Ollama hosts
(`ubuntu`, the fallback) follow `docs/runbook-ollama-lan-setup.md`.

## Usage
```
python3 council.py --check      # is every host up and does it have its model?
python3 council.py "should we rewrite the auth service in Rust?"
python3 council.py --build "sketch out a CLI todo app in Python"
```

Progress prints to stderr as each panelist finishes; the stages print
(with timings) when the run ends, and a `run_<timestamp>.json`
transcript is saved. `--build` needs all three panelists and has not
been re-tested against the phone hosts.

`--build`: after the vote, the curator breaks the winning decision into
a dependency-ordered task list, assigns tasks to panelists, and they
implement it via sandboxed file tools (`write_file`/`read_file`/`list_files`,
no shell access) under `projects/<run_id>/`.

## Design notes
- Panelist identities are anonymized to each other (Panelist A/B/C)
  during the rebuttal round, to avoid brand-bias between models.
- Vote tallying is plain Python, not an LLM call — the one place that
  must be deterministic actually is.
- Every model call has a hard `num_predict` ceiling
  (`MAX_TOKENS_JSON`/`MAX_TOKENS_TEXT`/`MAX_TOKENS_BUILD`). Without
  this, a small model fighting a JSON schema can generate for
  hundreds/thousands of tokens without converging — confirmed on
  `chromebook`, see ADR 009 — which on slow hardware is
  indistinguishable from a hang. The cap doesn't fix slow hardware, it
  just bounds the worst case.
- **Backends.** A host is either an Ollama URL (`http://ip:11434`) or a
  `llamaserver://ip:port` (llama.cpp's OpenAI-compatible server, API-key
  protected). Both return the same response shape to the pipeline.
- **Small models return junk that still parses**, so each panelist answer
  is checked (stance present and complete, not a placeholder such as
  "Retain unchanged", no leaked `Key risks:` text, reasoning and risks
  complete, English question answered in English) and retried with the
  problem fed back. Retries are cut off: at most 3 attempts, none started
  after 150 s, none continued past a hard 300 s cap per call, and a stuck
  model (the same problems twice in a row) stops early; a step is also
  bounded at 420 s. What is left is returned with a warning, never
  silently. Confidence is normalized to 0–1.
- **Failure handling.** A dead or hung host is dropped from that step
  instead of stalling the run (at least 2 panelists are required). If a
  host has a fallback in `FALLBACKS` it is used, at startup or mid-run,
  and every use is reported as a warning. A too-slow call is cut off, not
  failed over. A checkpoint file is written after each stage.
- **Voting is peer-only** (no self-votes: they carry no information). A
  vote-count tie is broken by fewest answer-quality warnings, then by the
  confidence of the votes received; otherwise the result is "no majority"
  and all positions are shown. Peer-only voting can produce a 1-1-1 cycle.
- **The answer is never the curator's invention.** It is the winning
  position's text plus the other positions verbatim; the curator's note is
  discarded if it lists items or contains characters no panelist wrote
  (in testing it once invented a word list).
- **Known limit: the checks measure form, not substance.** In the Panelist A
  bake-off (ADR 009 addendum) every candidate passed them at 7–8 of 8
  while giving weak or empty answers to a factual list question. Content
  checks (for instance, "top N" questions must return N items) are still
  to be added.

## Known limitations
- No authentication or rate-limiting in front of the Ollama calls this
  makes — same LAN-only trust model as the rest of the fleet (ADR 007).
- `--build` is implemented but has had limited end-to-end testing
  against the current 3-host panel.
