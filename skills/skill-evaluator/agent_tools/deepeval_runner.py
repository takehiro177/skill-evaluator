#!/usr/bin/env python3
"""deepeval metrics for skill-evaluator A/B outputs.

This is a REQUIRED phase of the skill-evaluator workflow: every evaluation runs
it for a complementary, library-backed GEval quality score alongside the blind
LLM-as-judge. It is skipped only with an explicit `--no-deepeval`, or when
`ANTHROPIC_API_KEY` / the deps are unavailable — in which case the report marks
its deepeval section `unavailable` rather than omitting it. Backed by `deepeval`
(https://github.com/confident-ai/deepeval).

It reads a JSON "cases" file produced by the workflow, runs a GEval quality
metric on each arm's output, and writes a JSON + Markdown summary of the
per-case score deltas (WITH minus WITHOUT).

Input cases file (JSON list). Two schemas are accepted:

  * Single-skill (legacy pair) — WITH vs WITHOUT, emits the Δ table:
    [
      {
        "id": "t1",
        "input": "the task prompt",
        "rubric": "what a good answer must satisfy",
        "with_skill_output": "...",
        "without_skill_output": "..."
      }
    ]

  * Combination (N arms) — score every subset in ONE run; emits a per-arm table
    (and a Δ-vs-baseline row if an arm is named base/baseline/none):
    [
      {
        "id": "t1",
        "input": "the task prompt",
        "rubric": "what a good answer must satisfy",
        "arms": {"base": "...", "caveman": "...", "karpathy": "...", "combo": "..."}
      }
    ]

`ANTHROPIC_API_KEY` is read from the environment or, if absent there, from a
`.env` in the CWD (searched upward) or next to this script — no manual export
needed.

This project only uses Claude, so the deepeval judge backend is PINNED to
Anthropic — there is no OpenAI fallback. The single requirement is an
`ANTHROPIC_API_KEY` in the environment (or a .env file; see .env.example).

Run it (uv makes the deps ephemeral — nothing installed globally). NOTE:
deepeval >=4 has NO "[anthropic]" extra, so add the `anthropic` package
explicitly or the run fails with `No module named 'anthropic'`:

    uv run --with deepeval --with anthropic python deepeval_runner.py cases.json --out report.deepeval

Or, in an environment where you've installed them:

    pip install deepeval anthropic
    python deepeval_runner.py cases.json --out report.deepeval

The judge model defaults to claude-sonnet-4-6; override with --judge-model.
See agent_tools/README.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# The deepeval judge is pinned to Anthropic/Claude — this project only uses Claude.
# Default to a current, verified Claude model id.
DEFAULT_JUDGE_MODEL = "claude-sonnet-4-6"


def _load_dotenv() -> None:
    """Best-effort ``.env`` loader (stdlib only) so the documented "or a .env
    file" behavior actually works without python-dotenv.

    Populates ``os.environ`` for keys that are not already set, searching the
    current working directory upward a few levels and this script's directory.
    Only simple ``KEY=VALUE`` lines are parsed (``#`` comments and blanks
    skipped; surrounding quotes stripped). Never overrides an existing env var.
    """
    candidates: list[Path] = []
    cwd = Path.cwd()
    candidates.append(cwd)
    candidates.extend(list(cwd.parents)[:4])
    candidates.append(Path(__file__).resolve().parent)
    seen: set[str] = set()
    for d in candidates:
        f = d / ".env"
        key = str(f)
        if key in seen:
            continue
        seen.add(key)
        if not f.is_file():
            continue
        try:
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        except OSError:
            continue


def _build_judge(model_name: str):
    """Construct the Anthropic (Claude) judge model deepeval will use.

    Pinning the backend here keeps the run deterministic and self-contained: it
    never silently falls back to deepeval's default OpenAI backend.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "error: ANTHROPIC_API_KEY is not set.\n"
            "  This tool uses Claude (Anthropic) as the deepeval judge backend.\n"
            "  Set it in your environment or a .env file (see .env.example)."
        )
    try:
        from deepeval.models import AnthropicModel
    except ImportError as exc:  # pragma: no cover - guidance path
        raise SystemExit(
            "error: deepeval (>=4, with the Anthropic SDK) is not installed.\n"
            "  uv run --with deepeval --with anthropic python deepeval_runner.py ...\n"
            "  or: pip install 'deepeval>=4' anthropic\n"
            "  (deepeval has no '[anthropic]' extra — install 'anthropic' explicitly.)\n"
            f"(import error: {exc})"
        )
    # temperature=0 for a stable, repeatable judge.
    return AnthropicModel(model=model_name, temperature=0)


def _load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("error: cases file must be a JSON list of case objects.")
    return data


def _score_arm(metric, task_input: str, output: str):
    """Score one arm's output with a GEval metric; return (score, reason)."""
    from deepeval.test_case import LLMTestCase

    tc = LLMTestCase(input=task_input, actual_output=output or "")
    metric.measure(tc)
    return metric.score, getattr(metric, "reason", "")


def _case_arms(case: dict) -> "dict[str, str]":
    """Normalize a case to an ordered ``{arm_name: output}`` mapping.

    Two schemas are accepted:

    * **N-arm (combination):** ``{"arms": {"base": "...", "caveman": "...", ...}}``
      — each arm scored in isolation. Use this for 2+ skills so every subset
      (baseline / each single / combo) is scored in one run.
    * **Legacy pair (single-skill):** ``{"with_skill_output", "without_skill_output"}``
      — kept for backward compatibility; mapped to arms ``with_skill`` /
      ``without_skill``.
    """
    arms = case.get("arms")
    if isinstance(arms, dict) and arms:
        return {str(k): (v or "") for k, v in arms.items()}
    return {
        "with_skill": case.get("with_skill_output", "") or "",
        "without_skill": case.get("without_skill_output", "") or "",
    }


def run(cases: list[dict], judge_model: str = DEFAULT_JUDGE_MODEL) -> dict:
    try:
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCaseParams
    except ImportError as exc:  # pragma: no cover - guidance path
        raise SystemExit(
            "error: deepeval is not installed.\n"
            "  uv run --with deepeval --with anthropic python deepeval_runner.py ...\n"
            "  or: pip install 'deepeval>=4' anthropic\n"
            "  (deepeval has no '[anthropic]' extra — install 'anthropic' explicitly.)\n"
            f"(import error: {exc})"
        )

    # Pinned Anthropic/Claude judge, shared across every metric in this run.
    judge = _build_judge(judge_model)

    def make_metric(rubric: str):
        # A fresh metric per (case, arm) so the rubric matches the task and no
        # measurement state bleeds between arms.
        return GEval(
            name="TaskQuality",
            criteria=(
                "Given the task INPUT and the response ACTUAL_OUTPUT, judge how well "
                "the response fulfills the task. A good response satisfies: " + rubric
            ),
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.ACTUAL_OUTPUT,
            ],
            model=judge,
        )

    n_arm_mode = any(isinstance(c.get("arms"), dict) and c["arms"] for c in cases)
    arm_order: list[str] = []
    results = []
    for case in cases:
        rubric = case.get("rubric", "Respond accurately, completely, and usefully.")
        task_input = case.get("input", "")
        arms = _case_arms(case)
        scores: dict[str, float] = {}
        reasons: dict[str, str] = {}
        for arm_name, output in arms.items():
            if arm_name not in arm_order:
                arm_order.append(arm_name)
            score, reason = _score_arm(make_metric(rubric), task_input, output)
            scores[arm_name] = score
            reasons[arm_name] = reason

        row = {"id": case.get("id"), "scores": scores, "reasons": reasons}
        # Backward-compatible convenience fields for the legacy with/without pair.
        if not n_arm_mode:
            ws, wos = scores.get("with_skill"), scores.get("without_skill")
            row.update(
                {
                    "with_skill_score": ws,
                    "without_skill_score": wos,
                    "score_delta": (ws or 0) - (wos or 0),
                    "with_skill_reason": reasons.get("with_skill"),
                    "without_skill_reason": reasons.get("without_skill"),
                }
            )
        results.append(row)

    n = len(results) or 1
    arm_means = {
        a: sum((r["scores"].get(a) or 0) for r in results) / n for a in arm_order
    }
    summary = {
        "results": results,
        "num_cases": len(results),
        "arms": arm_order,
        "arm_means": arm_means,
        "n_arm_mode": n_arm_mode,
    }
    if not n_arm_mode:
        summary["mean_score_delta"] = sum(r["score_delta"] for r in results) / n
    return summary


# Arm names treated as the "no skills" baseline for the Δ row, in priority order.
_BASELINE_NAMES = ("base", "baseline", "none", "without_skill")


def to_markdown(summary: dict) -> str:
    if summary.get("n_arm_mode"):
        return _to_markdown_n_arm(summary)
    lines = [
        "# deepeval metrics",
        "",
        f"Cases: {summary['num_cases']}  ",
        f"Mean quality delta (WITH − WITHOUT): **{summary['mean_score_delta']:+.3f}**",
        "",
        "| Task | WITH skill | WITHOUT skill | Δ (with − without) |",
        "|------|-----------:|--------------:|-------------------:|",
    ]
    for r in summary["results"]:
        lines.append(
            f"| {r['id']} | {r['with_skill_score']:.3f} | "
            f"{r['without_skill_score']:.3f} | {r['score_delta']:+.3f} |"
        )
    lines.append("")
    lines.append(
        "Scores are GEval (0–1). Positive Δ means the skill improved quality on that task."
    )
    return "\n".join(lines)


def _to_markdown_n_arm(summary: dict) -> str:
    """Per-arm GEval table for a combination (2+ skills / N subsets) run."""
    arms = summary["arms"]
    means = summary["arm_means"]
    header = "| Task | " + " | ".join(arms) + " |"
    sep = "|------|" + "|".join(["-----------:"] * len(arms)) + "|"
    lines = [
        "# deepeval metrics",
        "",
        f"Cases: {summary['num_cases']}  ",
        "GEval (0–1) per arm, each arm scored in isolation against the task rubric.",
        "",
        header,
        sep,
    ]
    for r in summary["results"]:
        cells = " | ".join(f"{(r['scores'].get(a) or 0):.3f}" for a in arms)
        lines.append(f"| {r['id']} | {cells} |")
    mean_cells = " | ".join(f"{means.get(a, 0):.3f}" for a in arms)
    lines.append(f"| **mean** | {mean_cells} |")
    lines.append("")
    base = next((a for a in _BASELINE_NAMES if a in arms), None)
    if base:
        deltas = " · ".join(
            f"`{a}` {means[a] - means[base]:+.3f}" for a in arms if a != base
        )
        lines.append(f"Δ vs `{base}` (per-arm mean − baseline mean): {deltas}")
        lines.append("")
    lines.append(
        "Scores are GEval (0–1), each arm judged in isolation; GEval saturates, so "
        "use it to corroborate the blind pairwise judge, not to replace it."
    )
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="deepeval metrics for skill A/B outputs (Anthropic-only judge)."
    )
    ap.add_argument("cases", help="Path to the JSON cases file.")
    ap.add_argument("--out", help="Output basename (writes <out>.json and <out>.md).")
    ap.add_argument(
        "--judge-model",
        default=DEFAULT_JUDGE_MODEL,
        help=f"Claude model for the deepeval judge (default: {DEFAULT_JUDGE_MODEL}).",
    )
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    # Pick up ANTHROPIC_API_KEY from a project .env if it isn't already exported.
    _load_dotenv()

    cases = _load_cases(Path(args.cases))
    summary = run(cases, judge_model=args.judge_model)
    md = to_markdown(summary)

    if args.out:
        Path(args.out + ".json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        Path(args.out + ".md").write_text(md, encoding="utf-8")
        print(f"wrote {args.out}.json and {args.out}.md")
    else:
        print(json.dumps(summary, indent=2))
        print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
