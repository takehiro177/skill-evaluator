#!/usr/bin/env python3
"""Plan and resolve the blind LLM-as-judge phase of a skill evaluation.

Part of skill-evaluator. Standalone, *standard-library only* — no install, no
deps. The judging phase is the most accident-prone part to do by hand: you must
build a clean prompt per comparison, randomize which response is "1" vs "2",
keep a private map so you can un-blind afterwards, and — in combination mode —
enumerate the right comparisons (combo vs none, combo vs the *best* single
skill) without leaking arm identities. This script makes all of that mechanical
and reproducible while keeping the actual judging blind: **you** still dispatch
each generated prompt to a fresh judge subagent; this tool only prepares the
prompts and, afterwards, un-blinds and tallies the results.

Two subcommands
---------------
``plan``    Read a spec (tasks + each arm's deliverable) and emit:
              * ``<out>.jobs.json``  — one job per comparison, each with the
                full, ready-to-dispatch **blind** judge prompt (responses
                labelled only Response 1 / Response 2, positions randomized).
              * ``<out>.map.json``   — the PRIVATE job_id → arm map (which arm is
                Response 1 vs 2 in each job). Do NOT show this to the judge.
            You dispatch each job's ``prompt`` to a `skill-eval-judge`-style
            subagent and collect their JSON outputs as ``{job_id: <judge json>}``.

``resolve`` Read the ``.map.json`` and your collected ``<results>.json`` and emit
            the **un-blinded** verdicts + the decision the report needs: per task,
            *combo vs none* and *combo vs the best single skill*, plus W/L/T
            tallies. Writes ``<out>.verdicts.json`` and ``<out>.verdicts.md``.

Spec schema (``plan`` input)
----------------------------
    {
      "skills": ["caveman", "karpathy-guidelines"],   # optional, for labels
      "design": "factorial-2",                         # optional, informational
      "seed": 1234,                                     # optional, for reproducible positions
      "tasks": [
        {
          "id": "t1",
          "prompt": "the exact user request",
          "input": "any input data/files (may be empty)",
          "rubric": "skill-agnostic criteria a great answer must satisfy",
          "arms": {                                      # arm-name -> that arm's deliverable
            "base": "...", "caveman": "...",
            "karpathy-guidelines": "...", "combo": "..."
          }
        }
      ]
    }

Arm naming: an arm called ``base``/``baseline``/``none`` is the no-skills
baseline; an arm called ``combo`` (or the full skill set) is the all-skills arm;
everything else is a single skill. For a **single-skill** eval just use two arms
named ``with_skill`` and ``without_skill`` (or ``base`` + one skill) — the tool
then plans the one with-vs-without comparison.

Comparisons planned (combination): per task — ``combo vs base`` (does the stack
help?), ``combo vs each single`` (so combo-vs-best-single falls out with no
two-stage dependency), and each pair of singles (to rank them). ``resolve`` picks
the best single from the singles' head-to-heads and reports the matching
combo-vs-best-single verdict. Pass an explicit ``"comparisons"`` list in the spec
to override.

Usage
-----
    python judge_planner.py plan SPEC.json --out reports/x-combo-eval-1.judge
    # ... dispatch each jobs[].prompt to a blind judge subagent, save as
    #     {job_id: judge_json} in results.json ...
    python judge_planner.py resolve reports/x-combo-eval-1.judge.map.json \
        results.json --out reports/x-combo-eval-1.judge

Exit codes: 0 ok, 2 bad spec/inputs, 4 results missing jobs.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

BASELINE_NAMES = ("base", "baseline", "none", "without_skill")
COMBO_NAMES = ("combo", "all", "both")

# The blind judge's instructions, embedded so each generated prompt is fully
# self-contained and matches agents/skill-eval-judge.md. No arm identity, no
# markers, no token data — Response 1 / Response 2 only.
JUDGE_HEADER = """\
You are an impartial evaluator. You are given a TASK, a RUBRIC, and TWO candidate \
responses labeled Response 1 and Response 2. Score each against the rubric and \
decide which better fulfills the task. You have no information about where the \
responses came from; do not speculate.

Guard against bias: the order (Response 1 vs Response 2) is arbitrary — no position \
bias; briefly consider the strongest case for each before scoring. No verbosity \
bias — longer is not better; reward correctness, relevance, and completeness \
against the rubric, and penalize padding, hedging, and unrequested scope. Rubric \
is the law.

Score each response on four dimensions, 0-10 each: correctness, task_fulfillment, \
rubric_adherence, usefulness. Then an overall 0-10 (holistic, not necessarily the \
mean)."""

JUDGE_FOOTER = """\
Return EXACTLY this JSON object and nothing else (no preamble, no code fence):
{"response_1":{"correctness":0,"task_fulfillment":0,"rubric_adherence":0,\
"usefulness":0,"overall":0,"notes":"1-3 sentences citing rubric criteria."},\
"response_2":{"correctness":0,"task_fulfillment":0,"rubric_adherence":0,\
"usefulness":0,"overall":0,"notes":"1-3 sentences citing rubric criteria."},\
"winner":"response_1 | response_2 | tie","margin":"decisive | clear | slight | tie",\
"rationale":"2-4 sentences comparing the two against the rubric."}"""


# --------------------------------------------------------------------------- #
# Arm classification
# --------------------------------------------------------------------------- #


def classify_arms(
    arm_names: list[str], skills: list[str]
) -> tuple[str | None, str | None, list[str]]:
    """Return (base_name, combo_name, [single_names]) from a task's arm keys."""
    base = next((a for a in arm_names if a.lower() in BASELINE_NAMES), None)
    combo = next((a for a in arm_names if a.lower() in COMBO_NAMES), None)
    if combo is None and skills and len(skills) >= 2:
        # An arm keyed by the full joined skill set also counts as the combo.
        full = {s.lower() for s in skills}
        for a in arm_names:
            parts = {p.strip().lower() for p in a.replace("+", ",").split(",")}
            if parts == full:
                combo = a
                break
    singles = [a for a in arm_names if a not in (base, combo)]
    return base, combo, singles


def default_comparisons(base, combo, singles: list[str]) -> list[tuple[str, str, str]]:
    """(arm_a, arm_b, label) comparisons for one task.

    Single-stage and complete: combo vs base, combo vs each single, and each
    pair of singles. ``resolve`` derives best-single + combo-vs-best from these.
    """
    comps: list[tuple[str, str, str]] = []
    if combo and base:
        comps.append((combo, base, "combo_vs_none"))
    for s in singles:
        if combo:
            comps.append((combo, s, f"combo_vs_{s}"))
    for i in range(len(singles)):
        for j in range(i + 1, len(singles)):
            comps.append(
                (singles[i], singles[j], f"single_{singles[i]}_vs_{singles[j]}")
            )
    if not comps:
        # Single-skill fallback: exactly two arms, judge them head to head.
        names = ([base] if base else []) + singles + ([combo] if combo else [])
        names = [n for n in names if n]
        if len(names) == 2:
            comps.append((names[0], names[1], "with_vs_without"))
    return comps


# --------------------------------------------------------------------------- #
# plan
# --------------------------------------------------------------------------- #


def build_prompt(task: dict, r1_text: str, r2_text: str) -> str:
    parts = [JUDGE_HEADER, "", "TASK:", (task.get("prompt") or "").strip()]
    inp = (task.get("input") or "").strip()
    if inp:
        parts += ["", "INPUT:", inp]
    parts += [
        "",
        "RUBRIC:",
        (task.get("rubric") or "Respond accurately, completely, and usefully.").strip(),
        "",
        "=== Response 1 ===",
        (r1_text or "").strip(),
        "",
        "=== Response 2 ===",
        (r2_text or "").strip(),
        "",
        JUDGE_FOOTER,
    ]
    return "\n".join(parts)


def plan(spec: dict) -> tuple[dict, dict]:
    skills = list(spec.get("skills") or [])
    rng = random.Random(spec.get("seed", 0))
    jobs, mapping = [], []
    for task in spec.get("tasks") or []:
        tid = task.get("id")
        arms = task.get("arms") or {}
        if not isinstance(arms, dict) or len(arms) < 2:
            raise ValueError(f"task {tid!r}: needs an 'arms' object with >= 2 arms")
        names = list(arms.keys())
        base, combo, singles = classify_arms(names, skills)
        explicit = task.get("comparisons") or spec.get("comparisons")
        if explicit:
            comps = [
                (c["a"], c["b"], c.get("label") or f"{c['a']}_vs_{c['b']}")
                for c in explicit
            ]
        else:
            comps = default_comparisons(base, combo, singles)
        if not comps:
            raise ValueError(
                f"task {tid!r}: could not derive any comparison from arms {names}"
            )
        for arm_a, arm_b, label in comps:
            if arm_a not in arms or arm_b not in arms:
                raise ValueError(
                    f"task {tid!r}: comparison {label} names a missing arm"
                )
            # Randomize Response 1/2 positions independently per job.
            if rng.random() < 0.5:
                r1, r2 = arm_a, arm_b
            else:
                r1, r2 = arm_b, arm_a
            job_id = f"{tid}__{label}"
            jobs.append(
                {
                    "job_id": job_id,
                    "task": tid,
                    "label": label,
                    "prompt": build_prompt(task, arms[r1], arms[r2]),
                }
            )
            mapping.append(
                {
                    "job_id": job_id,
                    "task": tid,
                    "label": label,
                    "response_1": r1,
                    "response_2": r2,
                }
            )
    meta = {"skills": skills, "design": spec.get("design")}
    jobs_doc = {"meta": meta, "jobs": jobs}
    map_doc = {"meta": meta, "jobs": mapping}
    return jobs_doc, map_doc


# --------------------------------------------------------------------------- #
# resolve
# --------------------------------------------------------------------------- #


def _overall(resp: dict) -> float | None:
    if not isinstance(resp, dict):
        return None
    if isinstance(resp.get("overall"), (int, float)):
        return float(resp["overall"])
    dims = [
        resp.get(k)
        for k in ("correctness", "task_fulfillment", "rubric_adherence", "usefulness")
    ]
    dims = [float(x) for x in dims if isinstance(x, (int, float))]
    return sum(dims) / len(dims) if dims else None


def resolve(map_doc: dict, results: dict) -> dict:
    by_id = {m["job_id"]: m for m in map_doc.get("jobs", [])}
    missing = [jid for jid in by_id if jid not in results]
    verdicts = []
    # task -> {label -> verdict}
    per_task: dict[str, dict[str, dict]] = defaultdict(dict)
    for jid, m in by_id.items():
        res = results.get(jid)
        if not isinstance(res, dict):
            verdicts.append(
                {"job_id": jid, **m, "winner_arm": None, "note": "no result"}
            )
            continue
        a1, a2 = m["response_1"], m["response_2"]
        w = res.get("winner")
        winner_arm = a1 if w == "response_1" else a2 if w == "response_2" else "tie"
        s1, s2 = _overall(res.get("response_1")), _overall(res.get("response_2"))
        v = {
            "job_id": jid,
            "task": m["task"],
            "label": m["label"],
            "arm_response_1": a1,
            "arm_response_2": a2,
            "winner_arm": winner_arm,
            "margin": res.get("margin"),
            "scores": {a1: s1, a2: s2},
            "rationale": res.get("rationale"),
        }
        verdicts.append(v)
        per_task[m["task"]][m["label"]] = v

    # Per-task decisions the report needs.
    decisions = []
    tally = {
        "combo_vs_none": {"win": 0, "loss": 0, "tie": 0},
        "combo_vs_best_single": {"win": 0, "loss": 0, "tie": 0},
    }
    for tid, labelled in per_task.items():
        d: dict = {"task": tid}
        # combo vs none
        cn = labelled.get("combo_vs_none")
        if cn:
            # combo is the non-baseline arm of the combo_vs_none pair.
            combo_arm = next(
                (
                    a
                    for a in (cn["arm_response_1"], cn["arm_response_2"])
                    if a.lower() not in BASELINE_NAMES
                ),
                None,
            )
            res = _wlt(cn["winner_arm"], combo_arm)
            d["combo_vs_none"] = {
                "winner_arm": cn["winner_arm"],
                "margin": cn["margin"],
                "result": res,
            }
            tally["combo_vs_none"][res] += 1
            d["combo_arm"] = combo_arm
        # best single from singles head-to-heads
        best = _best_single(labelled)
        d["best_single"] = best
        if best is not None:
            cb = labelled.get(f"combo_vs_{best}")
            if cb:
                # combo is the non-single arm of the combo_vs_<best> pair.
                combo_arm = next(
                    (
                        a
                        for a in (cb["arm_response_1"], cb["arm_response_2"])
                        if a != best
                    ),
                    None,
                )
                res = _wlt(cb["winner_arm"], combo_arm)
                d["combo_vs_best_single"] = {
                    "best_single": best,
                    "winner_arm": cb["winner_arm"],
                    "margin": cb["margin"],
                    "result": res,
                }
                tally["combo_vs_best_single"][res] += 1
        decisions.append(d)

    return {
        "meta": map_doc.get("meta", {}),
        "verdicts": verdicts,
        "decisions": decisions,
        "tally": tally,
        "missing_results": missing,
    }


def _wlt(winner_arm: str | None, focus_arm: str | None) -> str:
    if winner_arm == "tie" or winner_arm is None:
        return "tie"
    return "win" if winner_arm == focus_arm else "loss"


def _best_single(labelled: dict[str, dict]) -> str | None:
    """Rank singles by their head-to-head wins, then mean score."""
    wins: dict[str, int] = defaultdict(int)
    score_sum: dict[str, float] = defaultdict(float)
    score_n: dict[str, int] = defaultdict(int)
    seen: set[str] = set()
    for label, v in labelled.items():
        if not label.startswith("single_"):
            continue
        a1, a2 = v["arm_response_1"], v["arm_response_2"]
        seen.update([a1, a2])
        if v["winner_arm"] in (a1, a2):
            wins[v["winner_arm"]] += 1
        for a in (a1, a2):
            s = v["scores"].get(a)
            if isinstance(s, (int, float)):
                score_sum[a] += s
                score_n[a] += 1
    if not seen:
        return None

    def keyf(a: str):
        mean = score_sum[a] / score_n[a] if score_n[a] else 0.0
        return (wins[a], mean)

    return max(seen, key=keyf)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def render_resolve_md(out: dict) -> str:
    L = ["# Blind judge — resolved verdicts", ""]
    skills = out["meta"].get("skills") or []
    if skills:
        L.append("- **Skills:** " + ", ".join(f"`{s}`" for s in skills))
    t = out["tally"]
    L.append(
        f"- **combo vs none:** {t['combo_vs_none']['win']}W / "
        f"{t['combo_vs_none']['loss']}L / {t['combo_vs_none']['tie']}T"
    )
    L.append(
        f"- **combo vs best single:** {t['combo_vs_best_single']['win']}W / "
        f"{t['combo_vs_best_single']['loss']}L / {t['combo_vs_best_single']['tie']}T"
    )
    if out["missing_results"]:
        L.append(f"- ⚠️ **missing judge results:** {', '.join(out['missing_results'])}")
    L.append("")
    L.append("| Task | combo vs none | best single | combo vs best single |")
    L.append("|------|------|------|------|")
    for d in out["decisions"]:
        cn = d.get("combo_vs_none", {})
        cb = d.get("combo_vs_best_single", {})
        cn_s = f"{cn.get('result', '-')} ({cn.get('margin', '-')})" if cn else "-"
        cb_s = f"{cb.get('result', '-')} ({cb.get('margin', '-')})" if cb else "-"
        L.append(f"| {d['task']} | {cn_s} | {d.get('best_single', '-')} | {cb_s} |")
    L.append("")
    L.append("## All comparisons (un-blinded)")
    L.append("")
    L.append("| Job | Task | Comparison | Winner (arm) | Margin | Scores |")
    L.append("|-----|------|------------|--------------|--------|--------|")
    for v in out["verdicts"]:
        sc = " · ".join(
            f"{a}={('%.1f' % s) if isinstance(s, (int, float)) else '?'}"
            for a, s in (v.get("scores") or {}).items()
        )
        L.append(
            f"| {v['job_id']} | {v.get('task', '-')} | {v.get('label', '-')} | "
            f"**{v.get('winner_arm', '-')}** | {v.get('margin', '-')} | {sc} |"
        )
    L.append("")
    L.append(
        "> Winners were un-blinded from the private job→arm map AFTER judging; the "
        "judge saw only Response 1 / Response 2 with randomized positions."
    )
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _reconfigure_utf8():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv=None) -> int:
    _reconfigure_utf8()
    ap = argparse.ArgumentParser(description="Plan/resolve the blind judging phase.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="Emit blind judge prompts + private map.")
    p_plan.add_argument("spec", help="Spec JSON (schema in module docstring).")
    p_plan.add_argument(
        "--out",
        required=True,
        help="Output basename: writes <out>.jobs.json and <out>.map.json.",
    )

    p_res = sub.add_parser("resolve", help="Un-blind + tally collected judge results.")
    p_res.add_argument("map", help="The <out>.map.json written by 'plan'.")
    p_res.add_argument(
        "results", help="JSON object {job_id: <judge json>} you collected."
    )
    p_res.add_argument(
        "--out", help="Output basename: writes <out>.verdicts.json and .verdicts.md."
    )

    args = ap.parse_args(argv)

    if args.cmd == "plan":
        try:
            spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
            jobs_doc, map_doc = plan(spec)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        Path(args.out + ".jobs.json").write_text(
            json.dumps(jobs_doc, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        Path(args.out + ".map.json").write_text(
            json.dumps(map_doc, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(
            f"wrote {args.out}.jobs.json ({len(jobs_doc['jobs'])} judge jobs) and {args.out}.map.json (private)"
        )
        for j in jobs_doc["jobs"]:
            print(f"  {j['job_id']:32}  [{j['label']}]")
        print(
            "\nDispatch each jobs[].prompt to a fresh blind judge subagent; save outputs as"
        )
        print(
            "{job_id: <judge json>} then run: judge_planner.py resolve <out>.map.json results.json --out <out>"
        )
        return 0

    # resolve
    try:
        map_doc = json.loads(Path(args.map).read_text(encoding="utf-8"))
        results = json.loads(Path(args.results).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not isinstance(results, dict):
        print(
            "error: results must be a JSON object {job_id: judge_json}", file=sys.stderr
        )
        return 2
    out = resolve(map_doc, results)
    md = render_resolve_md(out)
    if args.out:
        Path(args.out + ".verdicts.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        Path(args.out + ".verdicts.md").write_text(md, encoding="utf-8")
        print(f"wrote {args.out}.verdicts.json and {args.out}.verdicts.md")
    else:
        print(md)
    return 4 if out["missing_results"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
