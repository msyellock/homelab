#!/usr/bin/env python3
"""
LLM Council: a 3-model deliberation-and-vote pipeline running entirely on
local, free, open-weight models via Ollama.

Setup:
    Each panelist runs on its own machine, over the LAN, so no single box
    needs to hold more than one model in RAM at once. On this box:
        pip install ollama
        ollama pull llama3.2:3b        # curator (small/fast, non-voting, local)
    On each remote host (Ollama installed, OLLAMA_HOST=0.0.0.0:11434 via a
    systemd override, port 11434 opened on the LAN in the firewall):
        ollama pull <that host's assigned model>
    See PANEL below for which model/host pairs this run currently expects.

Usage:
    python3 council.py "should we rewrite the auth service in Rust?"
    python3 council.py --build "sketch out a CLI todo app in Python"

Design:
    - 3 panelists vote. They are deliberately different labs (Meta / Mistral
      AI / Alibaba) so their disagreements come from genuinely different
      training data and tuning, not just prompt variation on one model.
    - The curator (a separate, smaller model) never votes. It only formats
      the cross-pollination packet, plans/delegates build tasks, and writes
      the final synthesis/integration report. Vote tallying itself is plain
      Python, not an LLM call, so the one place that must be deterministic
      actually is.
    - Panelist identities are anonymized to each other (Panelist A/B/C)
      during the rebuttal round to avoid brand-bias between models.
    - Each panelist lives on its own machine (see PANEL's `host` field), so
      fan-out is genuinely parallel via asyncio.gather. This isn't just for
      speed: on this fleet, no single box has enough RAM to hold even one
      7-8B model reliably (confirmed -- the kernel OOM-killed Ollama's
      llama-server on a 7.6GB box loading qwen2.5:7b alone, no concurrency
      involved). Distributing across machines, each holding only its own
      one model, is what makes this reliable at all here, not an optimization.
    - With --build: after the vote, the curator splits the winning decision
      into a dependency-ordered task list and assigns each task to a
      panelist. Panelists execute sequentially (later tasks can read files
      earlier ones wrote) using file tools scoped to
      projects/<run_id>/ -- no shell execution is exposed to the panel, by
      design: unsupervised shell commands from a small local model are a
      real risk on a real machine, so this stays to inspectable file I/O.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
import ollama

class LlamaServerClient:
    """Minimal async client for a llama.cpp `llama-server` (OpenAI-compatible API).

    Exposes the one method council.py uses from ollama.AsyncClient -- chat() -- and
    returns the same {"message": {...}} shape, so call sites don't care which backend
    a panelist runs on. Selected by a host of the form "llamaserver://<ip>:<port>".
    Unlike Ollama, llama-server supports an API key; it is read from the
    LLAMA_SERVER_API_KEY env var or ~/.config/council/llama-server-<ip>-<port>.key, then -<ip>.key (never
    stored in the repo).
    """

    def __init__(self, host: str):
        self.hostport = host.split("://", 1)[1]
        self.base = f"http://{self.hostport}"
        ip = self.hostport.split(":")[0]
        key = os.environ.get("LLAMA_SERVER_API_KEY")
        if not key:
            port = self.hostport.split(":")[1] if ":" in self.hostport else ""
            cfg = Path.home() / ".config" / "council"
            for name in (f"llama-server-{ip}-{port}.key", f"llama-server-{ip}.key"):
                if (cfg / name).exists():
                    key = (cfg / name).read_text().strip()
                    break
            else:
                key = ""
        self.headers = {"Authorization": f"Bearer {key}"} if key else {}

    async def chat(self, model, messages, format=None, options=None, tools=None, keep_alive=None):
        options = options or {}
        body = {"model": model, "messages": messages, "stream": False}
        if "temperature" in options:
            body["temperature"] = options["temperature"]
        if "num_predict" in options:
            body["max_tokens"] = options["num_predict"]
        if format is not None:  # schema-constrained JSON, same intent as ollama's format=schema
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "strict": True, "schema": format},
            }
        if tools:
            body["tools"] = tools
        async with httpx.AsyncClient(timeout=httpx.Timeout(3600.0, connect=10.0)) as c:
            r = await c.post(f"{self.base}/v1/chat/completions", json=body, headers=self.headers)
            r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        return {"message": {
            "role": "assistant",
            "content": msg.get("content") or "",
            "tool_calls": msg.get("tool_calls") or [],
        }}


def make_client(host: str = None):
    """Ollama client for None / http:// hosts; llama-server client for llamaserver:// hosts."""
    if host and host.startswith("llamaserver://"):
        return LlamaServerClient(host)
    return ollama.AsyncClient(host=host) if host else ollama.AsyncClient()


# (model, label, host) -- host is None for this box, or "http://<lan-ip>:11434"
# for a remote panelist. Each host holds only its own one model in RAM.
# chromebook was in this rotation but its CPU (Celeron N3350) has no AVX2/FMA,
# which crippled llama.cpp to ~0.6-0.7 tok/s -- swapped to novo1 (i3-2348M,
# also no AVX2 but has AVX + 4 real cores @ 2.3GHz, and is otherwise idle
# now that its unrelated services were removed). Model kept as gemma2:2b to
# preserve the Google lab slot; only the host moved.
PANEL = [
    ("llama3.2-3b", "Panelist A (Llama 3.2 / Meta)", "llamaserver://192.168.1.167:8081"),  # Note 10+ (llama.cpp, 2nd server)
    ("qwen2.5:3b", "Panelist B (Qwen 2.5 / Alibaba)", None),                          # local
    ("gemma2-2b", "Panelist C (Gemma 2 / Google)", "llamaserver://192.168.1.167:8080"),  # Note 10+ (llama.cpp)
]
CURATOR_MODEL = "llama3.2:3b"  # stays local -- small enough this box handles it fine

# Fallbacks: (primary model, primary host) -> (fallback model, fallback host). Used when the
# primary is unreachable at the start of a run or fails mid-run (e.g. the phone rebooted, which
# kills its llama-servers). Fallbacks are slower and are always reported as warnings.
# Panelist C has no fallback: novo1 was retired 2026-09-19 and no other host carries Gemma.
FALLBACKS = {
    ("llama3.2-3b", "llamaserver://192.168.1.167:8081"): ("llama3.2:3b", "http://192.168.1.162:11434"),  # ubuntu
}
ROUTE: dict = {}  # per-run, sticky: primary -> fallback once a primary has failed
REBUTTAL_ROUNDS = 1  # keep this low; debate quality plateaus fast and cost/time triples per round

PROJECTS_ROOT = Path("/home/msyel/llm-council/projects")
MAX_TOOL_ITERS = 6  # per-task cap on the tool-call loop, so a stuck panelist can't run forever
# Hard ceiling on generated tokens per call. Without this, a small model fighting
# a JSON schema can generate for hundreds/thousands of tokens without converging
# (confirmed: gemma2:2b hit 1400+ tokens on a single position call before being
# killed manually) -- on slow hardware that looks indistinguishable from a hang.
# This turns "maybe hangs forever" into "worst case, still bounded and slow."
MAX_TOKENS_JSON = 500   # position/rebuttal/vote/task-plan schema calls
MAX_TOKENS_TEXT = 400   # synthesis/integration report (plain text, no schema)
MAX_TOKENS_BUILD = 2000  # per tool-call turn while writing files
RETRY_BUDGET_S = 150  # don't START another attempt once a call has used this long
CALL_BUDGET_S = 300  # HARD cap on one call_json (all attempts, including one already running); best-effort result or failure after this
STAGE_DEADLINE_S = 420  # backstop: no single panelist step (position/rebuttal/vote) may run longer than this
MIN_ATTEMPT_S = 30.0  # an attempt near the budget edge still gets at least this long
KEEP_ALIVE = "30m"  # keep Ollama models resident between calls (avoids reload churn on this 7.6 GB box)
MAX_TASKS = 8  # bound plan size; these are slow local models

POSITION_SCHEMA = {
    "type": "object",
    "properties": {
        "stance": {"type": "string"},
        "reasoning": {"type": "string"},
        "key_risks": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["stance", "reasoning", "key_risks", "confidence"],
}

VOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "primary_choice": {"type": "string", "enum": ["A", "B", "C"]},
        "supports_combination": {"type": "boolean"},
        "combination_notes": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["primary_choice", "supports_combination", "combination_notes", "confidence"],
}


@dataclass
class Position:
    panelist: str
    stance: str
    reasoning: str
    key_risks: list = field(default_factory=list)
    confidence: float = 0.0
    warnings: list = field(default_factory=list)  # quality problems left after retries


@dataclass
class Vote:
    panelist: str
    primary_choice: str
    supports_combination: bool
    combination_notes: str
    confidence: float
    warnings: list = field(default_factory=list)


@dataclass
class Task:
    id: str
    description: str
    assignee: str  # "A" | "B" | "C"
    depends_on: list = field(default_factory=list)
    output_files: list = field(default_factory=list)


TASK_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "description": {"type": "string"},
                    "assignee": {"type": "string", "enum": ["A", "B", "C"]},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "output_files": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "description", "assignee", "depends_on", "output_files"],
            },
        }
    },
    "required": ["tasks"],
}

# Panelists get file tools only -- no shell execution. A 7-8B local model
# proposing arbitrary shell commands unsupervised is not a risk worth taking
# on a real machine; file I/O scoped to the project directory is enough for
# "write files that implement the decision" and stays inspectable/reversible.
BUILD_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write (or overwrite) a file inside the project directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the project directory."},
                    "content": {"type": "string", "description": "Full file content."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file already written inside the project directory.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List all files currently in the project directory.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# --- Output-quality checks -------------------------------------------------
# Small models under schema-constrained decoding often return JSON that parses but is
# junk: strings cut off mid-sentence, placeholder stances ("Revised Position"), empty
# risks, confidence on inconsistent scales. Found in the first Mandarin-words test run
# (see run_2026-09-19T05-39-06*.json). These checks let call_json retry instead of
# passing garbage downstream.
_CLEAN_END = re.compile(r'[.!?\u3002\uff01\uff1f)\]"\u201d\'*]\s*$')
_PLACEHOLDER = re.compile(r"^\W*(retain|retained|unchanged|revised|revision|no change|same|keep)\b", re.I)


_CJK_END = re.compile(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]\s*$')
# a stance that talks ABOUT an earlier answer instead of stating one
_META_STANCE = re.compile(r"\b(original|earlier|previous|initial|prior)\b.{0,40}\b(position|list|answer|stance)\b|"
                          r"\b(stand by|stick with|remain(s)? (unchanged|the same))\b", re.I)


def _ends_clean(text: str) -> bool:
    return bool(_CLEAN_END.search((text or "").strip()))


def norm_conf(x) -> float:
    """Map whatever scale a model used (0-1, 0-10, 0-100) onto 0-1."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0.0
    if x > 1:
        x = x / 100.0 if x > 10 else x / 10.0
    return max(0.0, min(1.0, x))


_FIELD_LEAK = re.compile(r"\b(key risks?|confidence|reasoning)\s*:", re.I)


def _cjk_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    return sum('\u4e00' <= ch <= '\u9fff' for ch in letters) / len(letters) if letters else 0.0


def check_position(d: dict, topic: str = "") -> list:
    problems = []
    if topic and _cjk_ratio(topic) < 0.2 and _cjk_ratio(str(d.get("stance", "")) + str(d.get("reasoning", ""))) > 0.5:
        problems.append("you answered in Chinese but the question is in English; answer in English (you may quote Chinese characters with pinyin and an English gloss)")
    if _FIELD_LEAK.search(str(d.get("stance", ""))):
        problems.append("stance contains 'Key risks/Confidence/Reasoning' text; put only the answer in stance and use the separate fields for the rest")
    if any(_FIELD_LEAK.search(str(r)) or str(r).strip().lower() == "confidence" for r in (d.get("key_risks") or [])):
        problems.append("key_risks contains 'Key risks/Confidence/Reasoning' text; list only the risks themselves")
    stance, reasoning = str(d.get("stance", "")).strip(), str(d.get("reasoning", "")).strip()
    risks = d.get("key_risks") or []
    if len(stance) < 20 or _PLACEHOLDER.match(stance) and len(stance) < 60:
        problems.append("stance is empty or a placeholder label; it must state the actual answer in full")
    elif _META_STANCE.search(stance) and len(stance) < 300:
        problems.append("stance describes an earlier answer instead of stating the answer; write the full answer out")
    elif not (_ends_clean(stance) or _CJK_END.search(stance)):
        problems.append("stance is cut off; finish it")
    if len(reasoning) < 60 or not _ends_clean(reasoning):
        problems.append("reasoning is missing or cut off; write 2-4 complete sentences")
    if not risks or any(len(str(r).strip()) < 15 for r in risks):
        problems.append("key_risks must list 1-3 complete sentences")
    return problems


def check_vote(d: dict, allowed=("A", "B", "C")) -> list:
    problems = []
    if d.get("primary_choice") not in allowed:
        problems.append("primary_choice must be one of " + ", ".join(allowed))
    notes = str(d.get("combination_notes", "")).strip()
    if d.get("supports_combination") and (len(notes) < 20 or not _ends_clean(notes)):
        problems.append("combination_notes must be complete sentences when supports_combination is true")
    return problems


HOST_ERRORS = (httpx.TransportError, ConnectionError, OSError, asyncio.TimeoutError)


def _host_error(e: Exception) -> bool:
    """True if the failure means the HOST is unusable (as opposed to a bad model answer)."""
    if isinstance(e, HOST_ERRORS):
        return True
    return isinstance(e, httpx.HTTPStatusError) and e.response.status_code >= 500


async def call_json(model: str, prompt: str, schema: dict, host: str = None, retries: int = 1, check=None) -> dict:
    """Call a model (Ollama or llama-server, local or remote) and force schema-constrained JSON.

    If `check` is given it returns a list of problems with the parsed dict; a non-empty
    list triggers a retry (up to `retries`) with the problems fed back and a lower
    temperature. If problems remain after the last attempt, the best-effort dict is
    returned with its leftover problems under "_warnings" rather than failing the run.

    If the host itself fails (unreachable, timeout, 5xx) and FALLBACKS has an entry for it,
    the call switches to the fallback (sticky for the rest of the run, without using up a
    retry) and a warning records that.
    """
    orig = (model, host)
    model, host = ROUTE.get(orig, orig)
    extra = [f"served by fallback {model} @ {host}"] if (model, host) != orig else []
    client = make_client(host)
    last_err, best, prev_problems, cut = None, None, None, None
    base_prompt = prompt
    t_call = time.monotonic()
    attempt = 0
    while attempt <= retries:
        elapsed = time.monotonic() - t_call
        if attempt and elapsed > RETRY_BUDGET_S:
            cut = f"retry budget {RETRY_BUDGET_S}s used"
            break
        temp = max(0.2, 0.7 - 0.25 * attempt)
        try:
            resp = await asyncio.wait_for(client.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                format=schema,
                options={"temperature": temp, "num_predict": MAX_TOKENS_JSON},
                keep_alive=KEEP_ALIVE,
            ), max(MIN_ATTEMPT_S, CALL_BUDGET_S - elapsed))
            data = json.loads(resp["message"]["content"])
        except asyncio.TimeoutError:
            # Too slow, not dead: cut off rather than fail over to another (slower) host.
            cut = f"call budget {CALL_BUDGET_S}s exhausted"
            break
        except (json.JSONDecodeError, KeyError) as e:
            last_err = e
            prompt = base_prompt + "\n\nYour previous response was not valid JSON matching the schema. Respond with ONLY the JSON object, nothing else."
            attempt += 1
            continue
        except Exception as e:  # noqa: BLE001
            fb = FALLBACKS.get(orig)
            if _host_error(e) and fb and (model, host) != fb:
                plog(f"{model} @ {host} failed ({type(e).__name__}: {e}); failing over to {fb[0]} @ {fb[1]}")
                ROUTE[orig] = fb
                model, host = fb
                client = make_client(host)
                extra = [f"served by fallback {model} @ {host} (primary failed: {type(e).__name__})"]
                continue  # same attempt number: a host failure doesn't cost a retry
            raise
        problems = check(data) if check else []
        if not problems:
            if extra:
                data["_warnings"] = list(extra)
            return data
        best = (data, problems)
        if prev_problems is not None and set(problems) == set(prev_problems):
            cut = "same problems twice in a row (model is stuck)"
            break  # more retries would burn time without changing the outcome
        prev_problems = problems
        prompt = base_prompt + "\n\nYour previous answer had problems: " + "; ".join(problems) + ". Fix all of them and answer again."
        attempt += 1
    if best:
        data, problems = best
        data["_warnings"] = extra + problems + ([f"retries cut off: {cut}"] if cut else [])
        return data
    raise RuntimeError(f"{model} gave no usable answer ({cut or f'{retries + 1} attempts failed: {last_err}'})")


def format_rules(topic: str) -> str:
    """Shared prompt suffix. For an English question we say so explicitly and up front: in test
    runs Qwen 2.5 3B answered in Chinese to any English question that mentioned Chinese."""
    if _cjk_ratio(topic) < 0.2:
        lang = ("\n\nWrite your ENTIRE answer in English. Chinese (or other non-English) words may "
                "appear only as quoted examples, each followed by pinyin/transliteration and its English meaning.")
    else:
        lang = "\n\nAnswer in the same language as the question above (do not switch languages)."
    return (
        lang +
        " Format rules: put your actual, complete answer in `stance` (for a list question, "
        "the full list) -- never a label such as 'Revised Position' or 'Retain unchanged'. "
        "Write `reasoning` as 2-4 complete sentences. Give 1-3 short complete sentences in "
        "`key_risks`. Set `confidence` to a number between 0 and 1."
        + ("\nRemember: respond in English." if _cjk_ratio(topic) < 0.2 else "")
    )


def _build_position(label: str, data: dict) -> Position:
    warnings = data.pop("_warnings", [])
    data["confidence"] = norm_conf(data.get("confidence"))
    return Position(panelist=label, warnings=warnings, **data)


async def get_position(model: str, label: str, topic: str, host: str = None) -> Position:
    prompt = (
        f"A user is deciding: \"{topic}\"\n\n"
        "Give your independent position. Do not hedge into 'it depends' without "
        "committing to a stance. Be concrete about the risks you see."
        + format_rules(topic)
    )
    data = await call_json(model, prompt, POSITION_SCHEMA, host=host, retries=2, check=lambda d: check_position(d, topic))
    return _build_position(label, data)


async def get_rebuttal(model: str, label: str, topic: str, self_pos: Position, peers: list, host: str = None) -> Position:
    peer_text = "\n\n".join(
        f"{i.panelist}: {i.stance}\nReasoning: {i.reasoning}\nRisks: {', '.join(i.key_risks)}"
        for i in peers
    )
    prompt = (
        f"Topic: \"{topic}\"\n\n"
        f"Your earlier position:\n{self_pos.stance}\nReasoning: {self_pos.reasoning}\n\n"
        f"Your peers' positions:\n{peer_text}\n\n"
        "Having seen your peers' reasoning, restate your position: keep it unchanged, "
        "revise it, or concede to a peer's view. Check your peers' answers for factual "
        "errors (for example, words that are not actually in the language being asked "
        "about) and correct anything wrong, including in your own answer. "
        "Whichever you choose, write your full final answer out in `stance`. If you are not "
        "changing your answer, copy your earlier answer word for word into `stance`."
        + format_rules(topic)
    )
    data = await call_json(model, prompt, POSITION_SCHEMA, host=host, retries=2, check=lambda d: check_position(d, topic))
    # Placeholder / meta stances that survive all retries ("Keep my original answer...") carry no
    # answer, which would make this panelist's final position empty. Carry the earlier answer
    # forward verbatim instead, and say so.
    ws = data.get("_warnings", [])
    if any(w.startswith(("stance is empty or a placeholder", "stance describes an earlier answer")) for w in ws):
        data["stance"] = self_pos.stance
        data["_warnings"] = [w for w in ws if not w.startswith(("stance is empty or a placeholder", "stance describes an earlier answer"))] \
            + ["rebuttal stance was a placeholder; carried forward the earlier answer unchanged"]
    return _build_position(label, data)


async def get_vote(model: str, label: str, topic: str, positions: dict, host: str = None, own_key: str = None) -> Vote:
    # Peer vote only: voting for your own position carries no information (in test run 3 all
    # three panelists voted for themselves, so the tally was a meaningless 1-1-1).
    allowed = tuple(k for k in positions if k != own_key)
    positions_text = "\n\n".join(
        f"{key} ({p.panelist}): {p.stance}\nReasoning: {p.reasoning}"
        for key, p in positions.items()
    )
    prompt = (
        f"Topic: \"{topic}\"\n\n"
        f"Final positions on the table:\n{positions_text}\n\n"
        "Vote for the single position whose actual answer is the most correct and useful "
        f"({', '.join(allowed)}); you cannot vote for your own position. Penalize answers containing factual "
        "errors. Your choice must agree with your notes. Separately, say whether you "
        "think the best real answer is actually a combination of two or more positions, "
        "and if so which parts. Use complete sentences. Set `confidence` between 0 and 1."
        + ("\nWrite in English." if _cjk_ratio(topic) < 0.2 else "")
    )
    schema = json.loads(json.dumps(VOTE_SCHEMA))
    schema["properties"]["primary_choice"]["enum"] = list(allowed)
    data = await call_json(model, prompt, schema, host=host, retries=2, check=lambda d: check_vote(d, allowed))
    warnings = data.pop("_warnings", [])
    data["confidence"] = norm_conf(data.get("confidence"))
    return Vote(panelist=label, warnings=warnings, **data)


def _quality_warnings(pos) -> int:
    """Answer-quality warnings on a position (host-fallback notices don't count against the answer)."""
    return len([w for w in getattr(pos, "warnings", []) if not w.startswith("served by fallback")])


def tally(votes: list, keys=("A", "B", "C"), positions: dict = None) -> dict:
    """Plain deterministic counting -- no LLM involved.

    Ties on vote count are broken, in order, by (1) fewest answer-quality warnings on the
    position, then (2) highest total confidence of the votes the position received. If
    that still leaves a tie there is no winner ("no majority"); we don't invent one. Peer-only
    voting can produce a 1-1-1 cycle (A->B, B->C, C->A), which is a genuine split.
    """
    counts = {k: 0 for k in keys}
    for v in votes:
        counts[v.primary_choice] += 1
    top = max(counts.values())
    leaders = [k for k, c in counts.items() if c == top]
    winner, broken_by = (leaders[0] if len(leaders) == 1 else None), None
    if len(leaders) > 1:
        cands = leaders
        if positions:
            fewest = min(_quality_warnings(positions[k]) for k in cands)
            narrowed = [k for k in cands if _quality_warnings(positions[k]) == fewest]
            if len(narrowed) == 1:
                winner, broken_by = narrowed[0], "fewest quality warnings"
            cands = narrowed
        if winner is None:
            recv = {k: sum(v.confidence for v in votes if v.primary_choice == k) for k in cands}
            best = max(recv.values())
            top_conf = [k for k in cands if abs(recv[k] - best) < 1e-9]
            if len(top_conf) == 1:
                winner, broken_by = top_conf[0], "highest received vote confidence"
    combo_support = [v for v in votes if v.supports_combination]
    return {
        "counts": counts,
        "winner": winner,
        "tie": winner is None,
        "tie_broken_by": broken_by,
        "combination_flagged": len(combo_support) >= 2,  # majority flagged a combo as better
        "combination_notes": [v.combination_notes for v in combo_support],
    }


def _foreign_chars(curator_text: str, positions: dict) -> str:
    """Non-ASCII characters in the curator's text that no panelist wrote -- the sign of
    the curator inventing content (seen in test run 2: it made up a word list)."""
    seen = set("".join(p.stance + p.reasoning for p in positions.values()))
    return "".join(sorted({ch for ch in curator_text if ord(ch) > 127 and ch not in seen}))


async def synthesize(topic: str, positions: dict, votes: list, tally_result: dict) -> str:
    """The answer itself is assembled deterministically from panelist text. The curator LLM
    only writes a short note on agreement/dissent, and its text is discarded if it lists
    content or introduces characters no panelist wrote."""
    positions_text = "\n\n".join(f"{k}: {p.stance} -- {p.reasoning}" for k, p in positions.items())
    votes_text = "\n".join(
        f"{v.panelist} voted {v.primary_choice} (confidence {v.confidence:.2f}); "
        f"combination? {v.supports_combination}: {v.combination_notes}"
        for v in votes
    )
    prompt = (
        f"You are the curator of a 3-model decision panel, not a voter. The question was: \"{topic}\"\n\n"
        f"Final positions:\n{positions_text}\n\n"
        f"Votes:\n{votes_text}\n\n"
        f"Tally: {tally_result}\n\n"
        "In 1-3 plain sentences, say where the panelists agree and where they disagree. "
        "Do NOT state, list or restate the answer itself, and do not add any content of "
        "your own; the answer is attached separately."
    )
    client = ollama.AsyncClient()
    resp = await asyncio.wait_for(client.chat(
        model=CURATOR_MODEL, messages=[{"role": "user", "content": prompt}],
        options={"num_predict": MAX_TOKENS_TEXT}, keep_alive=KEEP_ALIVE,
    ), CALL_BUDGET_S)
    curator_text = resp["message"]["content"].strip()
    foreign = _foreign_chars(curator_text, positions)
    if foreign or re.search(r"^\s*\d+[.)]", curator_text, re.M):
        note = f"(curator note discarded: it {'introduced characters no panelist wrote: ' + foreign if foreign else 'listed items instead of summarizing'})"
        curator_text = note

    if tally_result["winner"]:
        w = tally_result["winner"]
        head = (f"Winning position ({positions[w].panelist}, votes {tally_result['counts']}"
                f"{', tie broken by ' + tally_result['tie_broken_by'] if tally_result.get('tie_broken_by') else ''}):\n"
                f"{positions[w].stance}")
        others = [(k, p) for k, p in positions.items() if k != w]
    else:
        head = f"No majority (votes {tally_result['counts']}). All positions:"
        others = list(positions.items())
    other_text = "\n".join(f"  [{k}] {p.panelist}: {p.stance}" for k, p in others)
    combo = "\n".join(f"  - {n}" for n in tally_result["combination_notes"] if n.strip())
    out = head
    if other_text:
        out += "\n\nOther positions (verbatim):\n" + other_text
    if tally_result["combination_flagged"] and combo:
        out += "\n\nPanelists suggested combining positions (their words):\n" + combo
    return out + "\n\nCurator note:\n" + curator_text


def resolve_safe_path(root: Path, rel_path: str) -> Path:
    """Resolve a panelist-supplied relative path, refusing anything that escapes root."""
    candidate = (root / rel_path).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError(f"path '{rel_path}' escapes the project directory")
    return candidate


def run_tool(root: Path, name: str, args: dict) -> str:
    try:
        if name == "write_file":
            path = resolve_safe_path(root, args["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"])
            return f"wrote {args['path']} ({len(args['content'])} bytes)"
        elif name == "read_file":
            path = resolve_safe_path(root, args["path"])
            return path.read_text() if path.exists() else f"error: {args['path']} does not exist"
        elif name == "list_files":
            return "\n".join(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()) or "(empty)"
        else:
            return f"error: unknown tool {name}"
    except Exception as e:
        return f"error: {e}"


async def plan_tasks(topic: str, summary: str) -> list:
    prompt = (
        f"Topic: \"{topic}\"\n\nThe panel's decided direction:\n{summary}\n\n"
        f"Break this into at most {MAX_TASKS} concrete implementation tasks. Each task "
        "needs a short id, a clear description, an assignee (A, B, or C -- distribute "
        "work roughly evenly), any task ids it depends on, and the files it should "
        "produce. Order tasks so dependencies make sense (e.g. scaffolding before code "
        "that imports it)."
    )
    data = await call_json(CURATOR_MODEL, prompt, TASK_PLAN_SCHEMA)
    return [Task(**t) for t in data["tasks"][:MAX_TASKS]]


def topological_order(tasks: list) -> list:
    by_id = {t.id: t for t in tasks}
    done, ordered = set(), []
    remaining = list(tasks)
    while remaining:
        progressed = False
        for t in list(remaining):
            if all(dep in done or dep not in by_id for dep in t.depends_on):
                ordered.append(t)
                done.add(t.id)
                remaining.remove(t)
                progressed = True
        if not progressed:  # circular/unsatisfiable dependency -- just append what's left
            ordered.extend(remaining)
            break
    return ordered


async def execute_task(model: str, label: str, root: Path, task: Task, topic: str, host: str = None) -> dict:
    existing = run_tool(root, "list_files", {})
    system_prompt = (
        f"You are {label}, implementing part of a plan for: \"{topic}\"\n\n"
        f"Your task ({task.id}): {task.description}\n"
        f"Expected output files: {', '.join(task.output_files) or '(none specified)'}\n\n"
        f"Files already in the project:\n{existing}\n\n"
        "Use the write_file tool to produce your output. Use read_file/list_files if you "
        "need to see what teammates already built. When your task is complete, reply with "
        "a short plain-text confirmation and no further tool calls."
    )
    client = make_client(host)
    messages = [{"role": "user", "content": system_prompt}]
    files_touched = []

    for _ in range(MAX_TOOL_ITERS):
        resp = await client.chat(
            model=model, messages=messages, tools=BUILD_TOOLS,
            options={"num_predict": MAX_TOKENS_BUILD},
        )
        msg = resp["message"]
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            return {"task_id": task.id, "assignee": label, "note": msg.get("content", ""), "files": files_touched}

        messages.append(msg)
        for call in tool_calls:
            fn = call["function"]["name"]
            args = call["function"]["arguments"]
            if isinstance(args, str):
                args = json.loads(args)
            result = run_tool(root, fn, args)
            if fn == "write_file" and "error" not in result:
                files_touched.append(args["path"])
            messages.append({"role": "tool", "content": result})

    return {"task_id": task.id, "assignee": label, "note": "hit max tool iterations", "files": files_touched}


async def integration_report(topic: str, root: Path, task_results: list) -> str:
    file_list = run_tool(root, "list_files", {})
    notes = "\n".join(f"- {r['task_id']} ({r['assignee']}): {r['note']}" for r in task_results)
    prompt = (
        f"The panel just implemented a decision for: \"{topic}\"\n\n"
        f"Task completion notes:\n{notes}\n\n"
        f"Final file tree:\n{file_list}\n\n"
        "Write a short human-facing summary: what got built, by whom, and flag anything "
        "that looks incomplete or inconsistent between tasks (you are reporting, not editing)."
    )
    client = ollama.AsyncClient()
    resp = await client.chat(
        model=CURATOR_MODEL, messages=[{"role": "user", "content": prompt}],
        options={"num_predict": MAX_TOKENS_TEXT},
    )
    return resp["message"]["content"]


async def run_build_phase(topic: str, summary: str, run_id: str) -> dict:
    root = PROJECTS_ROOT / run_id
    root.mkdir(parents=True, exist_ok=True)

    tasks = await plan_tasks(topic, summary)
    ordered = topological_order(tasks)
    panel_by_key = {"A": PANEL[0], "B": PANEL[1], "C": PANEL[2]}  # key -> (model, label, host)

    results = []
    for task in ordered:  # sequential: later tasks may read files earlier ones wrote
        model, label, host = panel_by_key[task.assignee]
        result = await execute_task(model, label, root, task, topic, host=host)
        results.append(result)

    report = await integration_report(topic, root, results)
    return {
        "project_dir": str(root),
        "tasks": [vars(t) for t in ordered],
        "results": results,
        "integration_report": report,
    }


T_START = time.monotonic()


def plog(msg: str) -> None:
    """Live progress on stderr (results still print at the end on stdout)."""
    print(f"[{time.monotonic() - T_START:6.1f}s] {msg}", file=sys.stderr, flush=True)


async def _timed(stage: str, label: str, coro):
    t = time.monotonic()
    try:
        r = await asyncio.wait_for(coro, STAGE_DEADLINE_S)
    except Exception as e:  # noqa: BLE001 -- surfaced to the caller, which decides how to degrade
        plog(f"{stage}: {label} FAILED after {time.monotonic() - t:.0f}s: {type(e).__name__}: {e}")
        raise
    w = getattr(r, "warnings", None)
    plog(f"{stage}: {label} done in {time.monotonic() - t:.0f}s" + (f"  (quality warnings: {len(w)})" if w else ""))
    return r


async def _host_up(host: str, timeout: float = 3.0) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            if host and host.startswith("llamaserver://"):
                cl = LlamaServerClient(host)
                r = await c.get(f"{cl.base}/v1/models", headers=cl.headers)
            else:
                r = await c.get(f"{host or 'http://localhost:11434'}/api/tags")
            return r.status_code < 400
    except Exception:  # noqa: BLE001
        return False


async def preflight() -> None:
    """Route panelists whose primary host is down straight to their fallback (sticky for this run)."""
    for model, label, host in PANEL:
        if await _host_up(host):
            continue
        fb = FALLBACKS.get((model, host))
        if fb:
            ROUTE[(model, host)] = fb
            plog(f"preflight: {label} primary {host} is DOWN; using fallback {fb[0]} @ {fb[1]}")
        else:
            plog(f"preflight: {label} primary {host} is DOWN and has no fallback (panelist will be dropped)")


async def check_hosts() -> bool:
    """`council.py --check`: is every panel host reachable and does it have its model?"""
    ok = True
    entries = [(m, l, h) for m, l, h in PANEL] + [(CURATOR_MODEL, "Curator", None)]
    async with httpx.AsyncClient(timeout=8.0) as c:
        for model, label, host in entries:
            t = time.monotonic()
            try:
                if host and host.startswith("llamaserver://"):
                    cl = LlamaServerClient(host)
                    r = await c.get(f"{cl.base}/v1/models", headers=cl.headers)
                    r.raise_for_status()
                    names = [m.get("id") or m.get("name") for m in r.json().get("data", r.json().get("models", []))]
                else:
                    r = await c.get(f"{host or 'http://localhost:11434'}/api/tags")
                    r.raise_for_status()
                    names = [m["name"] for m in r.json()["models"]]
                have = any(n == model or (n or "").startswith(model) for n in names)
                print(f"{'OK ' if have else 'MISSING MODEL'} {label:36s} {model:14s} {host or 'local':38s} {1000*(time.monotonic()-t):.0f} ms")
                ok &= have
            except Exception as e:  # noqa: BLE001
                fb = FALLBACKS.get((model, host))
                print(f"DOWN {label:36s} {model:14s} {host or 'local':38s} {type(e).__name__}: {e}"
                      + (f"  -> fallback {fb[0]} @ {fb[1]} is {'UP' if await _host_up(fb[1]) else 'DOWN'}" if fb else "  (no fallback)"))
                ok = False
    return ok


async def run_council(topic: str, build: bool = False) -> dict:
    global T_START
    T_START = time.monotonic()
    ROUTE.clear()
    await preflight()
    keys = ["A", "B", "C"]
    started = datetime.now(timezone.utc).isoformat()
    partial = Path(f"/home/msyel/llm-council/run_{started.replace(':', '-')}.partial.json")
    timings, dropped, rebuttal_failures, vote_failures = {}, {}, {}, {}

    def checkpoint(**state):
        # Written after every stage so a crash/drop keeps everything finished so far.
        with open(partial, "w") as f:
            json.dump({"topic": topic, "started": started, "timings": timings, "dropped": dropped, **state}, f, indent=2)

    # Genuinely parallel: each panelist lives on its own machine (see PANEL's host
    # field). return_exceptions so one dead/hung host degrades the panel instead of
    # killing the run.
    plog("stage 1: initial positions")
    t0 = time.monotonic()
    res = await asyncio.gather(
        *[_timed("position", l, get_position(m, l, topic, host=h)) for m, l, h in PANEL],
        return_exceptions=True,
    )
    positions = {}
    for k, r in zip(keys, res):
        if isinstance(r, Exception):
            dropped[k] = f"{type(r).__name__}: {r}"
        else:
            positions[k] = r
    if len(positions) < 2:
        raise RuntimeError(f"fewer than 2 panelists responded: {dropped}")
    initial_positions = {k: vars(p) for k, p in positions.items()}
    timings["positions_s"] = round(time.monotonic() - t0, 1)
    checkpoint(initial_positions=initial_positions)

    plog("stage 2: rebuttals")
    t0 = time.monotonic()
    for _ in range(REBUTTAL_ROUNDS):
        active = list(positions)
        res = await asyncio.gather(
            *[
                _timed("rebuttal", PANEL[keys.index(k)][1], get_rebuttal(
                    PANEL[keys.index(k)][0], PANEL[keys.index(k)][1], topic, positions[k],
                    [positions[o] for o in active if o != k],
                    host=PANEL[keys.index(k)][2],
                ))
                for k in active
            ],
            return_exceptions=True,
        )
        new = {}
        for k, r in zip(active, res):
            if isinstance(r, Exception):
                rebuttal_failures[k] = f"{type(r).__name__}: {r}"
                new[k] = positions[k]  # keep the earlier position rather than lose the panelist
            else:
                new[k] = r
        positions = new
    timings["rebuttals_s"] = round(time.monotonic() - t0, 1)
    checkpoint(initial_positions=initial_positions, positions={k: vars(p) for k, p in positions.items()})

    plog("stage 3: votes")
    t0 = time.monotonic()
    res = await asyncio.gather(
        *[
            _timed("vote", PANEL[keys.index(k)][1], get_vote(
                PANEL[keys.index(k)][0], PANEL[keys.index(k)][1], topic, positions, host=PANEL[keys.index(k)][2],
                own_key=k,
            ))
            for k in positions
        ],
        return_exceptions=True,
    )
    votes = []
    for k, r in zip(list(positions), res):
        if isinstance(r, Exception):
            vote_failures[k] = f"{type(r).__name__}: {r}"
        else:
            votes.append(r)
    if not votes:
        raise RuntimeError(f"no votes were cast: {vote_failures}")
    timings["votes_s"] = round(time.monotonic() - t0, 1)
    tally_result = tally(votes, keys=tuple(positions), positions=positions)
    checkpoint(initial_positions=initial_positions, positions={k: vars(p) for k, p in positions.items()},
               votes=[vars(v) for v in votes], tally=tally_result)

    plog("stage 4: curator synthesis")
    t0 = time.monotonic()
    summary = await synthesize(topic, positions, votes, tally_result)
    timings["synthesis_s"] = round(time.monotonic() - t0, 1)
    plog("done")

    result = {
        "topic": topic,
        "timestamp": started,
        "initial_positions": initial_positions,
        "positions": {k: vars(p) for k, p in positions.items()},
        "timings": timings,
        "dropped_panelists": dropped,
        "fallback_routes": {f"{m}@{h}": f"{fm}@{fh}" for (m, h), (fm, fh) in ROUTE.items()},
        "rebuttal_failures": rebuttal_failures,
        "vote_failures": vote_failures,
        "votes": [vars(v) for v in votes],
        "tally": tally_result,
        "summary": summary,
    }

    if build:
        if len(positions) < 3:
            result["build"] = None
            plog("build skipped: it needs all 3 panelists")
        else:
            run_id = result["timestamp"].replace(":", "-")
            result["build"] = await run_build_phase(topic, summary, run_id)

    partial.unlink(missing_ok=True)
    return result


def main():
    parser = argparse.ArgumentParser(description="LLM Council: local multi-model deliberation, vote, and build.")
    parser.add_argument("topic", nargs="*", help="the prompt/idea to deliberate on")
    parser.add_argument("--check", action="store_true", help="check that every panel host is reachable and has its model, then exit")
    parser.add_argument(
        "--build", action="store_true",
        help="after voting, have the panel implement the winning decision as files under projects/<run_id>/",
    )
    args = parser.parse_args()
    if args.check:
        sys.exit(0 if asyncio.run(check_hosts()) else 1)
    if not args.topic:
        parser.error("a topic is required (or use --check)")
    topic = " ".join(args.topic)

    result = asyncio.run(run_council(topic, build=args.build))

    def show(title, group):
        print(f"\n=== {title} ===")
        for k, p in group.items():
            print(f"\n[{k}] {p['panelist']}  (confidence {p['confidence']})\n  stance: {p['stance']}\n  reasoning: {p['reasoning']}\n  risks: {p['key_risks']}" + (f"\n  WARNINGS: {p['warnings']}" if p.get('warnings') else ""))

    show(f"STAGE 1: INITIAL POSITIONS ({result['timings']['positions_s']}s)", result["initial_positions"])
    show(f"STAGE 2: AFTER REBUTTAL ({result['timings']['rebuttals_s']}s)", result["positions"])

    print(f"\n=== STAGE 3: VOTES ({result['timings']['votes_s']}s) ===")
    for v in result["votes"]:
        print(f"  {v['panelist']}: {v['primary_choice']} (conf {v['confidence']}); combination={v['supports_combination']}: {v['combination_notes']}" + (f"  WARNINGS: {v['warnings']}" if v.get('warnings') else ""))

    for label, d in (("DROPPED PANELISTS", result["dropped_panelists"]), ("REBUTTAL FAILURES (kept earlier position)", result["rebuttal_failures"]), ("VOTE FAILURES", result["vote_failures"])):
        if d:
            print(f"\n!! {label}: {d}")
    print(f"\n=== STAGE 4: TALLY === {result['tally']}")
    print(f"\n=== STAGE 5: CURATOR SYNTHESIS ({result['timings']['synthesis_s']}s) ===\n{result['summary']}\n")

    if result.get("build"):
        b = result["build"]
        print(f"=== BUILD ({len(b['tasks'])} tasks) ===")
        for r in b["results"]:
            print(f"  [{r['assignee']}] {r['task_id']}: {r['note']} -- files: {r['files']}")
        print(f"\nProject written to: {b['project_dir']}")
        print(f"\n=== INTEGRATION REPORT ===\n{b['integration_report']}\n")

    out_path = f"/home/msyel/llm-council/run_{result['timestamp'].replace(':', '-')}.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Full transcript saved to {out_path}")


if __name__ == "__main__":
    main()
