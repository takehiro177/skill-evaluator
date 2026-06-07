#!/usr/bin/env python3
"""Assemble every downstream spec for a combination eval from the transcript.

Part of skill-evaluator. Standalone, *standard-library only* (it imports only the
sibling ``transcript_tokens.py``, itself stdlib-only). This is the glue that, in a
hand-run combination evaluation, you would otherwise write by hand every time:
pull each arm's verbatim output from the session transcript, split it into
per-task deliverables, and emit the input files the other helpers consume. With
this, the orchestrator's only hand-written JSON is the **task list** plus the
**arm → RUN MARKER** map (which it already has, having minted the markers).

Given one *build config*, it reads the transcript once, attributes each arm by its
RUN MARKER, splits each arm's multi-task output into per-task deliverables, and
writes:

  * ``<out>.judge.spec.json``    -> feed to ``judge_planner.py plan``
  * ``<out>.deepeval.cases.json``-> feed to ``deepeval_runner.py`` (N-arm schema)
  * ``<out>.spec.json``          -> feed to ``interaction_effects.py``
  * ``<out>.deliverables.json``  -> per-arm/per-task text (for the records file)

It also **surfaces the output_tokens stub**: if any arm's run looks stubbed
(``output_tokens_suspect``), it warns so you re-run that arm before building specs
off unreliable token numbers.

Build config schema
-------------------
    {
      "skills": ["caveman", "karpathy-guidelines"],   # ordered skill names
      "design": "factorial-2",                         # optional, informational
      "seed": 7,                                        # optional, for judge_planner positions
      "metric": "cost_units",                          # optional, interaction headline metric
      "tasks": [                                        # the ONE hand-written list
        {"id": "t1", "prompt": "...", "input": "...", "rubric": "..."}
      ],
      "tasks_file": "reports/x.tasks.json",            # ...or load tasks from a file instead
      "arms": [
        {"name": "base",                "marker": "SKILLEVAL-...-BASE-7f3"},
        {"name": "caveman",             "marker": "SKILLEVAL-...-S1-9a2"},
        {"name": "karpathy-guidelines", "marker": "SKILLEVAL-...-S2-4c1"},
        {"name": "combo",               "marker": "SKILLEVAL-...-COMBO-2bd"}
      ],
      "final_output_marker": "=== FINAL OUTPUT ===",   # optional (default shown)
      "task_header_regex": "(?im)^#{1,6}\\s*TASK\\s+{id}\\b"  # optional; {id} is substituted
    }

Each arm's ``subset`` (the skills injected into it) is **inferred** from its name
(``base``/``baseline``/``none`` -> none; ``combo``/``all``/``both`` or the joined
skill set -> all; a name matching a skill -> that one skill); pass an explicit
``"subset": [...]`` on an arm to override. ``tasks_file`` may be a bare list or a
``{"tasks": [...]}`` object (e.g. the ``*.tasks.json`` the workflow already wrote).

Usage
-----
    python combo_spec_builder.py CONFIG.json --out reports/A+B-combo-eval-1
    python combo_spec_builder.py CONFIG.json --out reports/A+B-combo-eval-1 --session PATH

Exit codes: 0 ok, 2 config/transcript problem, 4 an arm or task could not be
attributed/split (specs still written for what resolved, with warnings).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import transcript_tokens as tt  # noqa: E402

BASELINE_NAMES = ("base", "baseline", "none", "without_skill")
COMBO_NAMES = ("combo", "all", "both")
DEFAULT_FINAL_MARKER = "=== FINAL OUTPUT ==="


# --------------------------------------------------------------------------- #
# Config helpers
# --------------------------------------------------------------------------- #


def load_tasks(config: dict) -> list[dict]:
    tasks = config.get("tasks")
    if not tasks and config.get("tasks_file"):
        raw = json.loads(Path(config["tasks_file"]).read_text(encoding="utf-8"))
        tasks = raw.get("tasks") if isinstance(raw, dict) else raw
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("config needs a non-empty 'tasks' list (or 'tasks_file')")
    for t in tasks:
        if "id" not in t:
            raise ValueError(f"task missing 'id': {t!r}")
    return tasks


def infer_subset(name: str, skills: list[str]) -> list[str] | None:
    n = name.lower()
    if n in BASELINE_NAMES:
        return []
    if n in COMBO_NAMES:
        return list(skills)
    for s in skills:
        if s.lower() == n:
            return [s]
    parts = {p.strip().lower() for p in name.replace("+", ",").split(",")}
    if parts == {s.lower() for s in skills}:
        return list(skills)
    return None


# --------------------------------------------------------------------------- #
# Transcript extraction
# --------------------------------------------------------------------------- #


def split_tasks(
    assistant_text: str,
    task_ids: list[str],
    final_marker: str,
    header_regex_tmpl: str | None,
) -> dict[str, str]:
    """Slice an arm's multi-task output into ``{task_id: deliverable}``.

    Takes everything after the LAST ``final_marker`` (the ``=== FINAL OUTPUT ===``
    block), locates each task header, and slices between consecutive headers.
    Tasks whose header isn't found come back as ``""`` (caller warns).
    """
    body = assistant_text or ""
    idx = body.rfind(final_marker)
    if idx >= 0:
        body = body[idx + len(final_marker) :]

    spans: list[tuple[str, int, int]] = []
    for tid in task_ids:
        if header_regex_tmpl:
            pat = re.compile(header_regex_tmpl.replace("{id}", re.escape(tid)))
        else:
            pat = re.compile(rf"(?im)^#{{1,6}}\s*TASK\s+{re.escape(tid)}\b")
        m = pat.search(body)
        spans.append((tid, m.start() if m else -1, m.end() if m else -1))

    found = sorted([s for s in spans if s[1] >= 0], key=lambda x: x[1])
    out: dict[str, str] = {tid: "" for tid, _, _ in spans}
    for i, (tid, _start, end) in enumerate(found):
        nxt = found[i + 1][1] if i + 1 < len(found) else len(body)
        out[tid] = body[end:nxt].strip()
    return out


def resolve_arm_run(marker: str, runs: list[dict]) -> tuple[dict | None, str]:
    matches = [r for r in runs if marker in (r.get("first_user_text") or "")]
    if not matches:
        return None, "marker not found"
    if len(matches) > 1:
        return matches[0], f"ambiguous ({len(matches)} matches; used first)"
    return matches[0], "ok"


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #


def build(config: dict, runs: list[dict]) -> tuple[dict, list[str]]:
    skills = list(config.get("skills") or [])
    if len(skills) < 2:
        raise ValueError("config.skills must list at least two skills")
    tasks = load_tasks(config)
    task_ids = [t["id"] for t in tasks]
    arms = config.get("arms") or []
    if not arms:
        raise ValueError("config needs an 'arms' list (name + marker each)")
    final_marker = config.get("final_output_marker", DEFAULT_FINAL_MARKER)
    header_tmpl = config.get("task_header_regex")

    warnings: list[str] = []

    # Per arm: resolve run, record subset, split deliverables.
    arm_meta: list[dict] = []
    deliverables: dict[str, dict[str, str]] = {}
    for arm in arms:
        name = arm.get("name")
        marker = arm.get("marker")
        if not name or not marker:
            raise ValueError(f"each arm needs 'name' and 'marker': {arm!r}")
        subset = arm.get("subset")
        if subset is None:
            subset = infer_subset(name, skills)
            if subset is None:
                raise ValueError(
                    f"arm {name!r}: cannot infer subset from name; add an explicit 'subset'"
                )
        run, note = resolve_arm_run(marker, runs)
        if run is None:
            warnings.append(f"arm {name!r}: {note} ({marker}) -> UNMEASURED")
            deliverables[name] = {tid: "" for tid in task_ids}
            arm_meta.append(
                {"name": name, "subset": subset, "marker": marker, "resolved": note}
            )
            continue
        if note != "ok":
            warnings.append(f"arm {name!r}: {note}")
        if run.get("output_tokens_suspect"):
            warnings.append(
                f"arm {name!r}: output_tokens looks like the logging stub "
                f"(output_tokens={run.get('output_tokens')}, "
                f"{run.get('assistant_chars', 0)} chars) -- RE-RUN this arm before "
                "trusting its token/cost numbers."
            )
        per_task = split_tasks(
            run.get("assistant_text", ""), task_ids, final_marker, header_tmpl
        )
        for tid, text in per_task.items():
            if not text:
                warnings.append(f"arm {name!r}: no deliverable found for task {tid!r}")
        deliverables[name] = per_task
        arm_meta.append(
            {"name": name, "subset": subset, "marker": marker, "resolved": note}
        )

    # 1) judge_planner spec (per-task arms with deliverable text)
    judge_spec = {
        "skills": skills,
        "design": config.get("design"),
        "seed": config.get("seed", 0),
        "tasks": [
            {
                "id": t["id"],
                "prompt": t.get("prompt", ""),
                "input": t.get("input", ""),
                "rubric": t.get("rubric", ""),
                "arms": {
                    a["name"]: deliverables[a["name"]].get(t["id"], "")
                    for a in arm_meta
                },
            }
            for t in tasks
        ],
    }

    # 2) deepeval N-arm cases
    deepeval_cases = [
        {
            "id": t["id"],
            "input": (
                t.get("prompt", "")
                + ("\n\nINPUT:\n" + t["input"] if t.get("input") else "")
            ),
            "rubric": t.get("rubric", ""),
            "arms": {
                a["name"]: deliverables[a["name"]].get(t["id"], "") for a in arm_meta
            },
        }
        for t in tasks
    ]

    # 3) interaction_effects spec (per-arm session totals, by marker + subset)
    interaction_spec = {
        "skills": skills,
        "design": config.get("design", "factorial-2"),
        "metric": config.get("metric", "cost_units"),
        "lower_is_better": True,
        "tasks": [
            {
                "id": "session",
                "arms": [
                    {"subset": a["subset"], "marker": a["marker"]} for a in arm_meta
                ],
            }
        ],
    }

    return (
        {
            "judge_spec": judge_spec,
            "deepeval_cases": deepeval_cases,
            "interaction_spec": interaction_spec,
            "deliverables": deliverables,
            "arm_meta": arm_meta,
        },
        warnings,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(
        description="Build all downstream combination-eval specs from the transcript."
    )
    ap.add_argument("config", help="Build config JSON (schema in module docstring).")
    ap.add_argument(
        "--out", required=True, help="Output basename (e.g. reports/A+B-combo-eval-1)."
    )
    ap.add_argument(
        "--session", help="Specific transcript .jsonl (default: auto-detect)."
    )
    ap.add_argument("--project", help="Project cwd to resolve the transcript for.")
    args = ap.parse_args(argv)

    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: cannot read config {args.config!r}: {e}", file=sys.stderr)
        return 2

    session = tt.resolve_session(args)
    if session is None:
        print(
            "error: could not locate a transcript. Pass --session PATH.",
            file=sys.stderr,
        )
        return 2
    runs = tt.gather_runs(session, include_text=True)

    try:
        result, warnings = build(config, runs)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    out = args.out
    Path(out + ".judge.spec.json").write_text(
        json.dumps(result["judge_spec"], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    Path(out + ".deepeval.cases.json").write_text(
        json.dumps(result["deepeval_cases"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    Path(out + ".spec.json").write_text(
        json.dumps(result["interaction_spec"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    Path(out + ".deliverables.json").write_text(
        json.dumps(result["deliverables"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    arms = ", ".join(
        f"{a['name']}({'+'.join(a['subset']) or '-'})" for a in result["arm_meta"]
    )
    print(f"transcript: {session}")
    print(f"arms: {arms}")
    print("wrote:")
    for suffix in (
        ".judge.spec.json",
        ".deepeval.cases.json",
        ".spec.json",
        ".deliverables.json",
    ):
        print(f"  {out}{suffix}")
    print("\nnext:")
    print(f"  python interaction_effects.py {out}.spec.json --out {out}.interaction")
    print(f"  python judge_planner.py plan {out}.judge.spec.json --out {out}.judge")
    print(
        f"  (deepeval) deepeval_runner.py {out}.deepeval.cases.json --out {out}.deepeval"
    )

    if warnings:
        print("\nwarnings:", file=sys.stderr)
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
