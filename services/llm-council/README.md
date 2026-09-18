# LLM Council

A local, free, multi-model deliberation-and-vote pipeline. A prompt is
fanned out to 3 panelist LLMs (Ollama, one per lab host), each states a
position, they see each other's positions and can revise, then vote. A
separate non-voting curator model formats the exchange and writes the
final synthesis.

Why this exists, and the hardware findings that shaped it (RAM ceiling
on `illntentpc`, AVX2 gap on `chromebook`), are in
[`docs/decisions/009-llm-council-fleet-distribution.md`](../../docs/decisions/009-llm-council-fleet-distribution.md).
The LAN setup steps this depends on are in
[`docs/runbook-ollama-lan-setup.md`](../../docs/runbook-ollama-lan-setup.md).

## Current panel

| Panelist | Model | Lab | Host |
|---|---|---|---|
| A | `llama3.2:3b` | Meta | `ubuntu` |
| B | `qwen2.5:3b` | Alibaba | local (`illntentpc`) |
| C | `gemma2:2b` | Google | `novo1` |

Curator: `llama3.2:3b`, local, non-voting.

## Setup

On `illntentpc`:
```
python3 -m pip install --user ollama
ollama pull llama3.2:3b
ollama pull qwen2.5:3b
```

On each remote host in `PANEL`: follow
`docs/runbook-ollama-lan-setup.md`, then `ollama pull <that host's model>`.

## Usage
```
python3 council.py "should we rewrite the auth service in Rust?"
python3 council.py --build "sketch out a CLI todo app in Python"
```

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

## Known limitations
- No authentication or rate-limiting in front of the Ollama calls this
  makes — same LAN-only trust model as the rest of the fleet (ADR 007).
- `--build` is implemented but has had limited end-to-end testing
  against the current 3-host panel.
