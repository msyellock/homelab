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
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import ollama

# (model, label, host) -- host is None for this box, or "http://<lan-ip>:11434"
# for a remote panelist. Each host holds only its own one model in RAM.
# chromebook was in this rotation but its CPU (Celeron N3350) has no AVX2/FMA,
# which crippled llama.cpp to ~0.6-0.7 tok/s -- swapped to novo1 (i3-2348M,
# also no AVX2 but has AVX + 4 real cores @ 2.3GHz, and is otherwise idle
# now that its unrelated services were removed). Model kept as gemma2:2b to
# preserve the Google lab slot; only the host moved.
PANEL = [
    ("llama3.2:3b", "Panelist A (Llama 3.2 / Meta)", "http://192.168.1.162:11434"),  # ubuntu
    ("qwen2.5:3b", "Panelist B (Qwen 2.5 / Alibaba)", None),                          # local
    ("gemma2:2b", "Panelist C (Gemma 2 / Google)", "http://192.168.1.160:11434"),    # novo1
]
CURATOR_MODEL = "llama3.2:3b"  # stays local -- small enough this box handles it fine
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


@dataclass
class Vote:
    panelist: str
    primary_choice: str
    supports_combination: bool
    combination_notes: str
    confidence: float


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


async def call_json(model: str, prompt: str, schema: dict, host: str = None, retries: int = 1) -> dict:
    """Call an Ollama model (local or remote) and force schema-constrained JSON output."""
    client = ollama.AsyncClient(host=host) if host else ollama.AsyncClient()
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = await client.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                format=schema,
                options={"temperature": 0.7, "num_predict": MAX_TOKENS_JSON},
            )
            return json.loads(resp["message"]["content"])
        except (json.JSONDecodeError, KeyError) as e:
            last_err = e
            prompt = prompt + "\n\nYour previous response was not valid JSON matching the schema. Respond with ONLY the JSON object, nothing else."
    raise RuntimeError(f"{model} failed to produce valid JSON after {retries + 1} attempts: {last_err}")


async def get_position(model: str, label: str, topic: str, host: str = None) -> Position:
    prompt = (
        f"A user is deciding: \"{topic}\"\n\n"
        "Give your independent position. Do not hedge into 'it depends' without "
        "committing to a stance. Be concrete about the risks you see."
    )
    data = await call_json(model, prompt, POSITION_SCHEMA, host=host)
    return Position(panelist=label, **data)


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
        "revise it, or concede to a peer's view. Justify whichever you choose."
    )
    data = await call_json(model, prompt, POSITION_SCHEMA, host=host)
    return Position(panelist=label, **data)


async def get_vote(model: str, label: str, topic: str, positions: dict, host: str = None) -> Vote:
    positions_text = "\n\n".join(
        f"{key} ({p.panelist}): {p.stance}\nReasoning: {p.reasoning}"
        for key, p in positions.items()
    )
    prompt = (
        f"Topic: \"{topic}\"\n\n"
        f"Final positions on the table:\n{positions_text}\n\n"
        "Vote for the single strongest position (A, B, or C). Separately, say whether "
        "you think the best real answer is actually a combination of two or more "
        "positions, and if so which parts."
    )
    data = await call_json(model, prompt, VOTE_SCHEMA, host=host)
    return Vote(panelist=label, **data)


def tally(votes: list) -> dict:
    """Plain deterministic counting -- no LLM involved."""
    counts = {"A": 0, "B": 0, "C": 0}
    for v in votes:
        counts[v.primary_choice] += 1
    winner = max(counts, key=counts.get)
    is_tie = list(counts.values()).count(counts[winner]) > 1
    combo_support = [v for v in votes if v.supports_combination]
    return {
        "counts": counts,
        "winner": None if is_tie else winner,
        "tie": is_tie,
        "combination_flagged": len(combo_support) >= 2,  # majority flagged a combo as better
        "combination_notes": [v.combination_notes for v in combo_support],
    }


async def synthesize(topic: str, positions: dict, votes: list, tally_result: dict) -> str:
    positions_text = "\n\n".join(f"{k}: {p.stance} -- {p.reasoning}" for k, p in positions.items())
    votes_text = "\n".join(
        f"{v.panelist} voted {v.primary_choice} (confidence {v.confidence}); "
        f"combination? {v.supports_combination}: {v.combination_notes}"
        for v in votes
    )
    prompt = (
        f"You are the curator of a 3-model decision panel, not a voter. Write a short, "
        f"clear human-facing summary of the panel's outcome on: \"{topic}\"\n\n"
        f"Final positions:\n{positions_text}\n\n"
        f"Votes:\n{votes_text}\n\n"
        f"Tally: {tally_result}\n\n"
        "State the winning decision (or the recommended combination if the tally flags "
        "one), note any real dissent, and keep it to a few sentences. Do not add your "
        "own opinion beyond synthesizing theirs."
    )
    client = ollama.AsyncClient()
    resp = await client.chat(
        model=CURATOR_MODEL, messages=[{"role": "user", "content": prompt}],
        options={"num_predict": MAX_TOKENS_TEXT},
    )
    return resp["message"]["content"]


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
    client = ollama.AsyncClient(host=host) if host else ollama.AsyncClient()
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


async def run_council(topic: str, build: bool = False) -> dict:
    keys = ["A", "B", "C"]

    # Genuinely parallel: each panelist lives on its own machine (see PANEL's
    # host field), so there's no shared-RAM contention to serialize around.
    initial = await asyncio.gather(*[get_position(m, l, topic, host=h) for m, l, h in PANEL])
    positions = dict(zip(keys, initial))

    for _ in range(REBUTTAL_ROUNDS):
        updated = await asyncio.gather(
            *[
                get_rebuttal(
                    PANEL[i][0], PANEL[i][1], topic, positions[keys[i]],
                    [p for k, p in positions.items() if k != keys[i]],
                    host=PANEL[i][2],
                )
                for i in range(3)
            ]
        )
        positions = dict(zip(keys, updated))

    votes = await asyncio.gather(*[get_vote(m, l, topic, positions, host=h) for m, l, h in PANEL])
    tally_result = tally(votes)
    summary = await synthesize(topic, positions, votes, tally_result)

    result = {
        "topic": topic,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "positions": {k: vars(p) for k, p in positions.items()},
        "votes": [vars(v) for v in votes],
        "tally": tally_result,
        "summary": summary,
    }

    if build:
        run_id = result["timestamp"].replace(":", "-")
        result["build"] = await run_build_phase(topic, summary, run_id)

    return result


def main():
    parser = argparse.ArgumentParser(description="LLM Council: local multi-model deliberation, vote, and build.")
    parser.add_argument("topic", nargs="+", help="the prompt/idea to deliberate on")
    parser.add_argument(
        "--build", action="store_true",
        help="after voting, have the panel implement the winning decision as files under projects/<run_id>/",
    )
    args = parser.parse_args()
    topic = " ".join(args.topic)

    result = asyncio.run(run_council(topic, build=args.build))

    print("\n=== POSITIONS ===")
    for k, p in result["positions"].items():
        print(f"\n[{k}] {p['panelist']}\n  stance: {p['stance']}\n  reasoning: {p['reasoning']}")

    print("\n=== VOTES ===")
    for v in result["votes"]:
        print(f"  {v['panelist']}: {v['primary_choice']} (conf {v['confidence']})")

    print(f"\n=== TALLY === {result['tally']}")
    print(f"\n=== SUMMARY ===\n{result['summary']}\n")

    if "build" in result:
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
