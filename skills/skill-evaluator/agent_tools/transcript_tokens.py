#!/usr/bin/env python3
"""Attribute token usage to individual Claude Code subagent runs.

Part of skill-evaluator. Standalone, *standard-library only* — no install,
no third-party deps. The skill-evaluator workflow calls this to measure the
WITH-skill vs WITHOUT-skill token deltas of an A/B test from the real session
transcript, rather than estimating.

Two transcript layouts are supported (Claude Code has used both):

* **Per-file subagents (newer):** each subagent has its own transcript at
  ``~/.claude/projects/<encoded-cwd>/<session-id>/subagents/agent-<hash>.jsonl``
  with a sibling ``agent-<hash>.meta.json`` (``agentType``, ``description``,
  ``toolUseId``). Each file is one run.
* **Inline sidechains (older):** subagent turns live in the main session
  ``<session-id>.jsonl`` as entries with ``isSidechain: true``; runs are
  reconstructed by following ``parentUuid`` chains.

In both cases the run's first user message is the dispatch prompt, which
contains the harness's RUN MARKER, so ``--grep`` can pull a single A/B arm.

Usage
-----
    python transcript_tokens.py [--json] [--session PATH] [--project PATH]
    python transcript_tokens.py --grep "SKILLEVAL-t1-A-7f3" [--json]
    python transcript_tokens.py --list-sessions

Add ``--full-text`` to also capture each run's **verbatim** content from the
transcript: the untruncated dispatch prompt (``first_user_text``) and the full
concatenated assistant output (``assistant_text``, which contains the runner's
``=== FINAL OUTPUT ===`` deliverable). This is what the skill-evaluator workflow
uses to build the human-reviewable WITH/WITHOUT *records* companion file — the
actual A/B outputs as they were recorded, not a summary::

    python transcript_tokens.py --grep "SKILLEVAL-t1-A-7f3" --json --full-text

**Stub detection.** Claude Code's subagent logging intermittently records a
turn's ``output_tokens`` as a tiny placeholder (``1``/``3``/``4``) even though
that turn emitted a large text block — a non-deterministic, content-independent
dropout that silently corrupts the output-token (and therefore cost) figure of
whichever arm it hits. Each run is checked: a text-bearing assistant turn whose
reported ``output_tokens`` is implausibly small for its character count sets
``output_tokens_suspect: true`` on the run (and prints a warning to stderr). When
you see it, **re-run that arm** with a fresh RUN MARKER and identical prompt and
use the clean read — never estimate the missing tokens.

Exit codes: 0 ok, 2 no transcript found, 3 marker not found.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

# --------------------------------------------------------------------------- #
# Locating the transcript
# --------------------------------------------------------------------------- #


def _projects_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    if base:
        return Path(base).expanduser() / "projects"
    return Path.home() / ".claude" / "projects"


def encode_cwd(path: Path) -> str:
    """Replicate Claude Code's project-folder encoding.

    Every non-alphanumeric character becomes a single ``-`` (not collapsed),
    so ``C:\\Users\\me\\proj`` -> ``C--Users-me-proj``.
    """
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def find_project_dir(project: Path | None) -> Path | None:
    cwd = (project or Path.cwd()).resolve()
    root = _projects_dir()
    if not root.is_dir():
        return None
    candidate = root / encode_cwd(cwd)
    if candidate.is_dir():
        return candidate
    enc = encode_cwd(cwd)
    matches = [
        d
        for d in root.iterdir()
        if d.is_dir() and (enc.endswith(d.name) or d.name.endswith(enc))
    ]
    return matches[0] if len(matches) == 1 else None


def latest_main_jsonl(directory: Path) -> Path | None:
    """Most-recently-modified top-level session transcript in a project dir."""
    files = sorted(
        directory.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return files[0] if files else None


def resolve_session(args) -> Path | None:
    if args.session:
        p = Path(args.session).expanduser()
        return p if p.is_file() else None
    proj_dir = find_project_dir(
        Path(args.project).expanduser() if args.project else None
    )
    if proj_dir is None:
        root = _projects_dir()
        if not root.is_dir():
            return None
        files = sorted(
            root.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        return files[0] if files else None
    return latest_main_jsonl(proj_dir)


# --------------------------------------------------------------------------- #
# Parsing primitives
# --------------------------------------------------------------------------- #


def load_entries(path: Path) -> list[dict]:
    entries = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _is_sidechain(e: dict) -> bool:
    return bool(e.get("isSidechain"))


def _is_assistant(e: dict) -> bool:
    return (e.get("message") or {}).get("role") == "assistant" or e.get(
        "type"
    ) == "assistant"


def _is_user(e: dict) -> bool:
    return (e.get("message") or {}).get("role") == "user" or e.get("type") == "user"


def _usage_of(e: dict) -> dict:
    msg = e.get("message") or {}
    usage = msg.get("usage") or e.get("usage") or {}
    return usage if isinstance(usage, dict) else {}


def _text_of(e: dict) -> str:
    msg = e.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif block.get("type") == "tool_result":
                    inner = block.get("content")
                    if isinstance(inner, str):
                        parts.append(inner)
                    elif isinstance(inner, list):
                        for ib in inner:
                            if isinstance(ib, dict) and isinstance(ib.get("text"), str):
                                parts.append(ib["text"])
        return "\n".join(parts)
    return ""


# --------------------------------------------------------------------------- #
# Cost weighting
# --------------------------------------------------------------------------- #
# Billing ratios relative to ONE base input token. The output:input ratio is 5x
# across the current Claude lineup (Opus $5/$25, Sonnet $3/$15, Haiku $1/$5), so
# it is model-independent. Cache write is 1.25x (5-minute TTL; 2x for 1h) and
# cache read is 0.1x; we assume the default 5-minute write. "cost_units" are
# therefore *effective base-input-token-equivalents* — a price-faithful stand-in
# for "tokens" that does NOT mis-weight cheap cached context (0.1x) against the
# 5x cost of generated output. Use this, never the flat token sum, for any
# "does this skill cost more/less" judgement.
COST_WEIGHTS = {
    "input_tokens": 1.0,
    "cache_creation_input_tokens": 1.25,
    "cache_read_input_tokens": 0.10,
    "output_tokens": 5.0,
}


def cost_units(usage: dict) -> float:
    """Effective base-input-token-equivalents for a usage/run/totals dict."""
    return sum(float(usage.get(k, 0) or 0) * w for k, w in COST_WEIGHTS.items())


# Stub-detection thresholds (see _build_run). A real assistant turn emits roughly
# 2-4 characters of text per output token; the logging stub reports 1/3/4 output
# tokens for hundreds-to-thousands of characters. So flag any text-bearing turn
# whose reported output_tokens is <= _STUB_OUTPUT_MAX while it emitted at least
# _STUB_TEXT_MIN characters — that combination cannot be a real measurement.
_STUB_OUTPUT_MAX = 4
_STUB_TEXT_MIN = 200


def _build_run(members: list[dict], include_text: bool = False, **extra) -> dict:
    """Summarize a list of entries belonging to ONE subagent run.

    With ``include_text`` the run also carries the **verbatim** dispatch prompt
    (untruncated ``first_user_text``) and the full concatenated assistant output
    (``assistant_text``) so callers can reconstruct the actual A/B records, not
    just the token totals.
    """
    members = sorted(members, key=lambda e: e.get("timestamp") or "")
    totals = defaultdict(int)
    assistant_turns = 0
    assistant_parts: list[str] = []
    assistant_chars = 0
    output_tokens_suspect = False
    for e in members:
        if _is_assistant(e):
            u = _usage_of(e)
            if u:
                assistant_turns += 1
            out_turn = int(u.get("output_tokens") or 0)
            totals["input_tokens"] += int(u.get("input_tokens") or 0)
            totals["output_tokens"] += out_turn
            totals["cache_creation_input_tokens"] += int(
                u.get("cache_creation_input_tokens") or 0
            )
            totals["cache_read_input_tokens"] += int(
                u.get("cache_read_input_tokens") or 0
            )
            # Measure the turn's text even when not storing it, so the stub check
            # (output_tokens implausibly small for the text emitted) always runs.
            text = _text_of(e)
            assistant_chars += len(text)
            if u and out_turn <= _STUB_OUTPUT_MAX and len(text) >= _STUB_TEXT_MIN:
                output_tokens_suspect = True
            if include_text and text:
                assistant_parts.append(text)

    first_user = next(
        (e for e in members if _is_user(e)), members[0] if members else None
    )
    first_text = _text_of(first_user) if first_user else ""

    context_tokens = (
        totals["input_tokens"]
        + totals["cache_creation_input_tokens"]
        + totals["cache_read_input_tokens"]
    )
    run = {
        "assistant_turns": assistant_turns,
        "input_tokens": totals["input_tokens"],
        "cache_creation_input_tokens": totals["cache_creation_input_tokens"],
        "cache_read_input_tokens": totals["cache_read_input_tokens"],
        "output_tokens": totals["output_tokens"],
        "context_tokens": context_tokens,
        "total_tokens": context_tokens + totals["output_tokens"],
        "cost_units": round(cost_units(totals), 1),
        "assistant_chars": assistant_chars,
        "output_tokens_suspect": output_tokens_suspect,
        "first_user_text": first_text if include_text else first_text[:2000],
        "start_ts": members[0].get("timestamp") if members else None,
        "end_ts": members[-1].get("timestamp") if members else None,
    }
    if include_text:
        run["assistant_text"] = "\n".join(assistant_parts)
    run.update(extra)
    return run


# --------------------------------------------------------------------------- #
# Layout A: inline sidechains in the main transcript
# --------------------------------------------------------------------------- #


def inline_runs(entries: list[dict], include_text: bool = False) -> list[dict]:
    side = {e.get("uuid"): e for e in entries if _is_sidechain(e) and e.get("uuid")}
    if not side:
        return []

    def root_of(uuid: str) -> str:
        seen = set()
        cur = uuid
        while True:
            e = side.get(cur)
            if e is None:
                return cur
            parent = e.get("parentUuid")
            if parent is None or parent not in side:
                return cur
            if parent in seen:
                return cur
            seen.add(cur)
            cur = parent

    groups: dict[str, list[dict]] = defaultdict(list)
    for uuid in side:
        groups[root_of(uuid)].append(side[uuid])

    return [
        _build_run(members, include_text=include_text, root_uuid=root, source="inline")
        for root, members in groups.items()
    ]


# --------------------------------------------------------------------------- #
# Layout B: per-file subagent transcripts
# --------------------------------------------------------------------------- #


def _read_meta(agent_file: Path) -> dict:
    meta_file = agent_file.with_suffix(".meta.json")
    if meta_file.is_file():
        try:
            return json.loads(meta_file.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def subagent_file_runs(main_path: Path, include_text: bool = False) -> list[dict]:
    """Runs from <session-id>/subagents/agent-*.jsonl, if that layout is in use."""
    sub_dir = main_path.with_suffix("") / "subagents"
    if not sub_dir.is_dir():
        return []
    runs = []
    for f in sorted(sub_dir.glob("agent-*.jsonl")):
        entries = load_entries(f)
        if not entries:
            continue
        meta = _read_meta(f)
        runs.append(
            _build_run(
                entries,
                include_text=include_text,
                root_uuid=f.name,
                source="subagent-file",
                agent_file=f.name,
                description=meta.get("description"),
                agent_type=meta.get("agentType"),
                tool_use_id=meta.get("toolUseId"),
            )
        )
    return runs


# --------------------------------------------------------------------------- #
# Combine
# --------------------------------------------------------------------------- #


def gather_runs(main_path: Path, include_text: bool = False) -> list[dict]:
    """All subagent runs for a session, across both transcript layouts."""
    runs = inline_runs(load_entries(main_path), include_text=include_text)
    runs.extend(subagent_file_runs(main_path, include_text=include_text))
    runs.sort(key=lambda r: r.get("start_ts") or "")
    return runs


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


def warn_suspect_runs(runs: list[dict]) -> bool:
    """Print an actionable stderr warning for any run with a stubbed output count.

    Returns True if at least one run looked stubbed, so callers can branch.
    """
    bad = [r for r in runs if r.get("output_tokens_suspect")]
    for r in bad:
        snippet = " ".join((r.get("first_user_text") or "").split())[:70]
        print(
            f"warning: run [{snippet}] reports output_tokens="
            f"{r.get('output_tokens')} for {r.get('assistant_chars', 0)} chars of "
            "assistant text -- this is Claude Code's output_tokens logging stub, "
            "NOT a real measurement. Its output_tokens/cost_units are unreliable; "
            "re-run this arm with a fresh RUN MARKER (identical prompt) and use the "
            "clean read. Do not estimate the missing tokens.",
            file=sys.stderr,
        )
    return bool(bad)


def print_human(session: Path, runs: list[dict], show_cost: bool = False) -> None:
    print(f"transcript: {session}")
    print(f"subagent runs found: {len(runs)}\n")
    if not runs:
        print("(no subagent runs in this transcript yet)")
        return
    for i, r in enumerate(runs, 1):
        snippet = " ".join(r["first_user_text"].split())[:90]
        desc = f'  "{r["description"]}"' if r.get("description") else ""
        print(
            f"[run {i}] total={r['total_tokens']:>9}  "
            f"ctx={r['context_tokens']:>9}  out={r['output_tokens']:>7}  "
            f"turns={r['assistant_turns']}  [{r.get('source', '?')}]{desc}"
        )
        print(
            f"         in={r['input_tokens']} cache_create={r['cache_creation_input_tokens']} "
            f"cache_read={r['cache_read_input_tokens']}"
        )
        if r.get("output_tokens_suspect"):
            print(
                f"         ⚠️  SUSPECT output_tokens={r['output_tokens']} for "
                f"{r.get('assistant_chars', 0)} chars — likely logging stub; re-run this arm."
            )
        if show_cost:
            print(
                f"         cost~{r.get('cost_units') or cost_units(r):.0f} eff-input-tok "
                f"(in*1 + cache_wr*1.25 + cache_rd*0.1 + out*5)"
            )
        if r.get("assistant_text") is not None:
            # --full-text mode: dump the verbatim records for this run.
            print("         --- dispatch prompt (verbatim) ---")
            print(r["first_user_text"])
            print("         --- assistant output (verbatim) ---")
            print(r["assistant_text"])
        else:
            print(f"         prompt: {snippet}")
        print()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Attribute token usage to Claude Code subagent runs."
    )
    ap.add_argument(
        "--session",
        help="Path to a specific main transcript .jsonl (or a single agent-*.jsonl).",
    )
    ap.add_argument(
        "--project",
        help="Project cwd to resolve the transcript for (default: current dir).",
    )
    ap.add_argument(
        "--grep",
        help="Print only the run whose dispatch prompt contains this marker/substring.",
    )
    ap.add_argument(
        "--json", action="store_true", help="Emit JSON instead of human-readable text."
    )
    ap.add_argument(
        "--full-text",
        action="store_true",
        help="Also include each run's verbatim dispatch prompt and full assistant "
        "output (for building the WITH/WITHOUT records companion).",
    )
    ap.add_argument(
        "--cost",
        action="store_true",
        help="Also show cost-weighted effective tokens (in×1, cache_wr×1.25, "
        "cache_rd×0.1, out×5). Use this, not the flat total, to judge cost.",
    )
    ap.add_argument(
        "--list-sessions",
        action="store_true",
        help="List candidate transcripts and exit.",
    )
    args = ap.parse_args(argv)

    # Make stdout/stderr UTF-8 so the warning glyphs and any non-ASCII transcript
    # text never die on a legacy console code page (e.g. cp932/cp1252 on Windows).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    if args.list_sessions:
        proj_dir = find_project_dir(
            Path(args.project).expanduser() if args.project else None
        )
        root = proj_dir or _projects_dir()
        # Transcripts sit directly inside a project dir, but one level down from
        # the projects root (…/projects/<encoded-cwd>/<session>.jsonl), so glob
        # one extra level when we fell back to the root.
        pattern = "*.jsonl" if proj_dir else "*/*.jsonl"
        files = sorted(
            Path(root).glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for f in files[:25]:
            print(f"{f.stat().st_mtime:.0f}  {f}")
        return 0

    session = resolve_session(args)
    if session is None:
        print(
            "error: could not locate a transcript. Pass --session PATH.",
            file=sys.stderr,
        )
        return 2

    runs = gather_runs(session, include_text=args.full_text)

    if args.grep:
        matches = [r for r in runs if args.grep in r["first_user_text"]]
        if not matches:
            print(
                f"error: no subagent run matched marker {args.grep!r}", file=sys.stderr
            )
            return 3
        if args.json:
            print(json.dumps(matches[0] if len(matches) == 1 else matches, indent=2))
        else:
            for m in matches:
                print_human(session, [m], show_cost=args.cost)
        warn_suspect_runs(matches)
        return 0

    if args.json:
        print(json.dumps({"session": str(session), "runs": runs}, indent=2))
    else:
        print_human(session, runs, show_cost=args.cost)
    warn_suspect_runs(runs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
