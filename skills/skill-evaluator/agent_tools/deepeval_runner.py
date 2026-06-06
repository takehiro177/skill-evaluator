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

Input cases file (JSON list):
    [
      {
        "id": "t1",
        "input": "the task prompt",
        "rubric": "what a good answer must satisfy",
        "with_skill_output": "...",
        "without_skill_output": "..."
      },
      ...
    ]

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

    results = []
    for case in cases:
        rubric = case.get("rubric", "Respond accurately, completely, and usefully.")
        # A fresh metric per case so the rubric/criteria match the task.
        metric = GEval(
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
        task_input = case.get("input", "")
        with_score, with_reason = _score_arm(
            metric, task_input, case.get("with_skill_output", "")
        )
        # New metric instance to avoid state bleed between measurements.
        metric_b = GEval(
            name="TaskQuality",
            criteria=metric.criteria,
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.ACTUAL_OUTPUT,
            ],
            model=judge,
        )
        without_score, without_reason = _score_arm(
            metric_b, task_input, case.get("without_skill_output", "")
        )

        results.append(
            {
                "id": case.get("id"),
                "with_skill_score": with_score,
                "without_skill_score": without_score,
                "score_delta": (with_score or 0) - (without_score or 0),
                "with_skill_reason": with_reason,
                "without_skill_reason": without_reason,
            }
        )

    n = len(results) or 1
    mean_delta = sum(r["score_delta"] for r in results) / n
    return {
        "results": results,
        "mean_score_delta": mean_delta,
        "num_cases": len(results),
    }


def to_markdown(summary: dict) -> str:
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
