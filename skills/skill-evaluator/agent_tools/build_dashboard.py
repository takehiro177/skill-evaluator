#!/usr/bin/env python3
"""Build the Skill Harness Dashboard from the evaluation summary data layer.

Part of skill-evaluator. Standalone, *standard-library only* — no install, no
third-party deps, no network. The skill-evaluator workflow ends every
evaluation (SKILL.md Phase 7) by writing a small, versioned
``reports/<name>-eval-<n>.summary.json`` next to the Markdown report; this
script validates those summaries and renders the governance view:

  * ``reports/index.json``     — all valid summaries in one machine-readable
                                 file (for CI gates, trend tooling, scripts).
  * ``reports/dashboard.html`` — a single self-contained static page (the
                                 template ships in ``../templates/``) with the
                                 JSON **embedded**, so it opens from ``file://``
                                 with no server, no build step, no CDN.

Detail enrichment: when building (not under ``--check``) the script also
embeds each run's sibling JSON artifacts — ``<id>.deepeval.cases.json`` (the
verbatim per-task arm outputs), ``<id>.deepeval.json``,
``<id>.interaction.json``, ``<id>.judge.verdicts.json``, or the paths named in
the summary's ``files`` map — into the dashboard payload under ``_detail``.
This powers each card's click-through detail view (WITH/WITHOUT output
comparison, deepeval results, raw judge verdicts). ``index.json`` stays
summaries-only. Skip embedding with ``--no-artifacts``.

Design rule: **the summary is a projection of the report, never a second
computation.** Every number in a summary must equal a figure already in the
report or its JSON artifacts (all transcript-sourced). This script therefore
only validates and packages — it never derives new metrics. Markdown is never
parsed; the data layer is the only ingestion path.

Summary schema (``schema_version: 1``)
--------------------------------------
One JSON object per evaluation run. ``<arm>`` keys in maps are the display
names used in ``metrics.arms[].name`` (e.g. ``WITH``/``WITHOUT`` or
``base``/``caveman``/``combo``). Fields marked *opt* may be omitted; anything
unmeasured is omitted (or flagged ``"available": false``) — never estimated.

    {
      "schema_version": 1,
      "id": "caveman-eval-1",              // unique; usually the report basename
      "kind": "single",                     // "single" | "combination"
      "skills": [                           // >= 1 entry; >= 2 for combination
        {"name": "caveman", "mode": "ultra", "mechanism": "output"}
      ],
      "design": "with-vs-without (single-injection, multi-task)",   // opt
      "run": 1,                             // opt
      "date": "2026-06-06",                 // recommended, YYYY-MM-DD
      "tasks": 3,                           // opt
      "verdict": {
        "label": "mixed-favorable",         // drives the card color; see below
        "emoji": "⚠️",                      // opt
        "headline": "one-line joint token+quality verdict",
        "bottom_line": "the report's actionable bottom line"        // opt
      },
      "metrics": {
        "mechanism": "output",              // output|context|round-trips|none|behavioral|mixed
        "primary_axis": "output_tokens",    // opt
        "headline": {                       // opt, but cost_delta_pct recommended
          "cost_delta_pct": -48.5,          // negative = cheaper than baseline
          "primary_delta_pct": -58.9,       // opt; omit for mechanism "none"
          "primary_label": "output tokens"  // opt
        },
        "arms": [                           // >= 2; one per arm/subset
          {"name": "WITHOUT", "skills": [],          "cost_units": 21799,
           "output_tokens": 4060},          // other token components opt
          {"name": "WITH",    "skills": ["caveman"], "cost_units": 11235,
           "output_tokens": 1668}
        ],
        "setup": {                          // opt — one-time vs recurring
          "one_time_cost_units": 1396,
          "per_turn_saving_cost_units": 3987,
          "breakeven_turns": 0.35
        }
      },
      "interaction": {                      // combination only (opt otherwise)
        "available": true,                  // false => give "reason"
        "classification": "additive",
        "value": 212.2,                     // excess over additive, eff-tok
        "combined_savings": 4217.5,
        "additive_prediction": 9181.8,
        "individual_effects": {"caveman": -3036.2, "karpathy": -1393.5},
        "marginal_effects":  {"caveman": -2824.0, "karpathy": -1181.3},
        "best_single": "caveman",
        "best_single_savings": 3036.2
      },
      "quality": {
        "pairwise": {                       // single-skill decisive comparison
          "comparison": "with_vs_without",
          "wins": 0, "ties": 0, "losses": 3, "mean_delta": -1.0
        },
        "combo_vs_none":        {"wins": 0, "ties": 0, "losses": 3},   // combination
        "combo_vs_best_single": {"wins": 2, "ties": 0, "losses": 1,
                                 "best_single": "karpathy"},           // combination
        "deepeval": {
          "available": true,
          "arm_means": {"WITH": 1.0, "WITHOUT": 1.0},
          "delta_vs_baseline": 0.0
        }
      },
      "per_task": [                         // opt; rendered in the card details
        {"id": "t1", "title": "short title", "winner": "WITHOUT",
         "margin": "slight", "scores": {"WITH": 8, "WITHOUT": 9},
         "deepeval": {"WITH": 1.0, "WITHOUT": 1.0},
         // combination extras:
         "best_single": "caveman", "combo_vs_best": {"result": "win", "margin": "slight"}
        }
      ],
      "caveats": ["small-n (3 tasks, 1 run)"],          // opt, plain strings
      "files": {                            // opt; paths relative to reports/
        "report": "caveman-eval-1.md", "records": "caveman-eval-1-records.md",
        "deepeval_md": "caveman-eval-1.deepeval.md"
      }
    }

Verdict labels and the card color they map to:
  helps, synergistic                          -> green
  additive, none, no-effect, no-token-claim  -> neutral
  mixed, mixed-favorable, redundant           -> amber
  conflicting, hurts, costs-more, regression  -> red

Schema evolution: adding *optional* fields is non-breaking (the dashboard
ignores what it doesn't know). A breaking change bumps ``schema_version``;
this builder warns and renders best-effort on versions newer than its own.

Usage
-----
    python build_dashboard.py                       # scan reports/, write both outputs
    python build_dashboard.py --check               # validate only (CI), write nothing
    python build_dashboard.py --reports DIR         # non-default reports dir
    python build_dashboard.py --out reports/dash.html
    python build_dashboard.py --template PATH       # non-bundled template
    python build_dashboard.py --no-artifacts        # skip detail-view embedding

Exit codes: 0 ok · 2 reports dir / template missing · 4 at least one invalid
summary (valid ones are still rendered; CI should treat 4 as a failure).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
SUMMARY_GLOB = "*.summary.json"
DATA_TOKEN = "null /*__SKILL_EVAL_DATA__*/"
KINDS = ("single", "combination")

# Sibling JSON artifacts embedded (per run, under "_detail") into the
# dashboard payload ONLY — never into index.json — to power the click-through
# detail view. Keys are `files` keys in the summary; values are the filename
# suffix tried (next to the summary) when `files` doesn't name the artifact.
ARTIFACT_SUFFIXES = {
    "deepeval_cases": ".deepeval.cases.json",  # verbatim per-task arm outputs
    "deepeval_json": ".deepeval.json",
    "interaction_json": ".interaction.json",
    "judge_verdicts_json": ".judge.verdicts.json",
}
ARTIFACT_DETAIL_KEYS = {
    "deepeval_cases": "cases",
    "deepeval_json": "deepeval",
    "interaction_json": "interaction",
    "judge_verdicts_json": "judge",
}
MAX_ARTIFACT_BYTES = 2_000_000  # per artifact; larger ones are linked, not embedded


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate_summary(d) -> "tuple[list[str], list[str]]":
    """Return (errors, warnings) for one parsed summary object.

    Errors block the summary from the dashboard; warnings don't. The checks
    mirror the schema in this module's docstring — keep the two in sync.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(d, dict):
        return (["summary is not a JSON object"], [])

    sv = d.get("schema_version")
    if not isinstance(sv, int):
        errors.append("schema_version missing or not an integer")
    elif sv > SCHEMA_VERSION:
        warnings.append(
            f"schema_version {sv} is newer than this builder ({SCHEMA_VERSION}); "
            "rendering best-effort"
        )

    if not isinstance(d.get("id"), str) or not d.get("id"):
        errors.append("id missing or not a non-empty string")

    kind = d.get("kind")
    if kind not in KINDS:
        errors.append(f"kind must be one of {KINDS}, got {kind!r}")

    skills = d.get("skills")
    if (
        not isinstance(skills, list)
        or not skills
        or not all(
            isinstance(s, dict) and isinstance(s.get("name"), str) for s in skills
        )
    ):
        errors.append("skills must be a non-empty list of objects with a 'name'")
    elif kind == "combination" and len(skills) < 2:
        errors.append("kind 'combination' needs at least two skills")

    verdict = d.get("verdict")
    if not isinstance(verdict, dict) or not isinstance(verdict.get("label"), str):
        errors.append("verdict.label missing or not a string")
    elif not isinstance(verdict.get("headline"), str) or not verdict.get("headline"):
        warnings.append("verdict.headline missing — the card will have no verdict line")

    metrics = d.get("metrics")
    if not isinstance(metrics, dict):
        errors.append("metrics missing or not an object")
    else:
        arms = metrics.get("arms")
        if not isinstance(arms, list) or len(arms) < 2:
            errors.append("metrics.arms must list at least two arms")
        else:
            measured = 0
            for i, arm in enumerate(arms):
                if not isinstance(arm, dict) or not isinstance(arm.get("name"), str):
                    errors.append(f"metrics.arms[{i}] needs a string 'name'")
                    continue
                if _is_num(arm.get("cost_units")):
                    measured += 1
                else:
                    warnings.append(
                        f"arm {arm.get('name')!r} has no numeric cost_units "
                        "(rendered as unmeasured)"
                    )
            if measured == 0:
                errors.append("no arm carries a numeric cost_units — nothing to plot")
        headline = metrics.get("headline") or {}
        if not _is_num(headline.get("cost_delta_pct")):
            warnings.append(
                "metrics.headline.cost_delta_pct missing (cost KPI shows '—')"
            )

    if not isinstance(d.get("date"), str):
        warnings.append("date missing — run sorts to the bottom of 'newest first'")
    quality = d.get("quality")
    if not isinstance(quality, dict):
        warnings.append("quality missing — the quality column shows '—'")
    elif kind == "combination" and not isinstance(quality.get("combo_vs_none"), dict):
        warnings.append(
            "combination quality without 'combo_vs_none' — the decisive combo-vs-"
            "baseline cell shows '—' on the card and detail"
        )
    if kind == "combination" and not isinstance(d.get("interaction"), dict):
        warnings.append("combination run without an 'interaction' block")
    return errors, warnings


# --------------------------------------------------------------------------- #
# Collect & build
# --------------------------------------------------------------------------- #


def collect(reports_dir: Path) -> "tuple[list[dict], list[str], int]":
    """Load every summary; return (valid_runs, problem_lines, error_file_count)."""
    runs: list[dict] = []
    problems: list[str] = []
    bad_files = 0
    seen_ids: dict[str, str] = {}
    for path in sorted(reports_dir.glob(SUMMARY_GLOB)):
        try:
            # utf-8-sig: tolerate a leading BOM (Windows editors / PowerShell
            # Out-File add one) — plain utf-8 would choke on it and silently
            # drop the summary, building an empty dashboard despite valid data.
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as e:
            problems.append(f"ERROR {path.name}: unreadable JSON ({e})")
            bad_files += 1
            continue
        errors, warnings = validate_summary(data)
        for w in warnings:
            problems.append(f"warn  {path.name}: {w}")
        if errors:
            for e in errors:
                problems.append(f"ERROR {path.name}: {e}")
            problems.append(
                f"ERROR {path.name}: skipped (fix the summary, then rebuild)"
            )
            bad_files += 1
            continue
        rid = data["id"]
        if rid in seen_ids:
            problems.append(
                f"warn  {path.name}: duplicate id {rid!r} (also in {seen_ids[rid]}); "
                "keeping both"
            )
        seen_ids.setdefault(rid, path.name)
        data["_source"] = path.name
        runs.append(data)
    runs.sort(key=lambda r: (r.get("date") or "", str(r.get("id"))), reverse=True)
    return runs, problems, bad_files


def attach_artifacts(run: dict, reports_dir: Path) -> "list[str]":
    """Embed the run's sibling JSON artifacts under ``run["_detail"]``.

    Powers the dashboard's detail view (verbatim WITH/WITHOUT outputs from the
    deepeval cases file, raw deepeval / interaction / judge-verdict JSON).
    Paths come from the summary's ``files`` map when present, otherwise from
    the ``<id><suffix>`` convention next to the summary. Returns warning
    lines; index.json never carries these payloads.
    """
    warns: list[str] = []
    files = run.get("files") if isinstance(run.get("files"), dict) else {}
    detail: dict = {}
    for fkey, suffix in ARTIFACT_SUFFIXES.items():
        rel = files.get(fkey)
        if isinstance(rel, str) and rel:
            path = reports_dir / rel
        else:
            path = reports_dir / f"{run.get('id')}{suffix}"
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > MAX_ARTIFACT_BYTES:
                warns.append(
                    f"warn  {path.name}: {path.stat().st_size} bytes — too large "
                    "to embed; the detail view links to it instead"
                )
                continue
            detail[ARTIFACT_DETAIL_KEYS[fkey]] = json.loads(
                path.read_text(encoding="utf-8-sig")  # tolerate a leading BOM
            )
        except (OSError, json.JSONDecodeError) as e:
            warns.append(
                f"warn  {path.name}: unreadable artifact ({e}); "
                "skipped from the detail view"
            )
    if detail:
        run["_detail"] = detail
    return warns


def build_index(runs: "list[dict]") -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "generator": "skill-evaluator/build_dashboard.py",
        "count": len(runs),
        "runs": runs,
    }


def render_dashboard(index: dict, template_path: Path) -> str:
    template = template_path.read_text(encoding="utf-8-sig")  # tolerate a BOM
    if DATA_TOKEN not in template:
        raise ValueError(
            f"template {template_path} has no '{DATA_TOKEN}' injection token — "
            "is this the bundled templates/dashboard.html?"
        )
    # </ would close the <script> early if a summary string ever contains it.
    payload = json.dumps(index, ensure_ascii=False).replace("</", "<\\/")
    return template.replace(DATA_TOKEN, payload, 1)


def default_template() -> Path:
    return Path(__file__).resolve().parent.parent / "templates" / "dashboard.html"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Validate reports/*.summary.json and build the Skill Harness "
        "Dashboard (index.json + a self-contained dashboard.html)."
    )
    ap.add_argument(
        "--reports",
        default="reports",
        help="Directory containing *.summary.json (default: reports/).",
    )
    ap.add_argument(
        "--out",
        help="Dashboard HTML path (default: <reports>/dashboard.html). "
        "index.json is written next to it.",
    )
    ap.add_argument(
        "--template",
        help="Dashboard template (default: the templates/dashboard.html bundled "
        "next to this script).",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Validate the summaries only; write nothing (CI mode).",
    )
    ap.add_argument(
        "--no-artifacts",
        action="store_true",
        help="Don't embed sibling JSON artifacts (deepeval cases/results, "
        "interaction, judge verdicts) into the dashboard's detail views.",
    )
    ap.add_argument("--quiet", action="store_true", help="Only print problems.")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    reports_dir = Path(args.reports).expanduser()
    if not reports_dir.is_dir():
        print(f"error: reports directory not found: {reports_dir}", file=sys.stderr)
        return 2

    runs, problems, bad_files = collect(reports_dir)
    for line in problems:
        print(line, file=sys.stderr)

    if not args.quiet:
        print(f"summaries: {len(runs)} valid, {bad_files} invalid, in {reports_dir}/")
        for r in runs:
            verdict = (r.get("verdict") or {}).get("label", "?")
            headline = (r.get("verdict") or {}).get("headline", "")
            print(f"  · {r['id']:42} [{verdict}] {headline}")

    if args.check:
        return 4 if bad_files else 0

    template_path = (
        Path(args.template).expanduser() if args.template else default_template()
    )
    if not template_path.is_file():
        print(f"error: dashboard template not found: {template_path}", file=sys.stderr)
        return 2

    out_html = (
        Path(args.out).expanduser() if args.out else reports_dir / "dashboard.html"
    )
    out_index = out_html.parent / "index.json"
    if not args.no_artifacts:
        for r in runs:
            for line in attach_artifacts(r, reports_dir):
                print(line, file=sys.stderr)
    # index.json stays summaries-only; the embedded payload carries "_detail".
    index = build_index([{k: v for k, v in r.items() if k != "_detail"} for r in runs])
    payload = dict(index)
    payload["runs"] = runs
    try:
        html = render_dashboard(payload, template_path)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    out_index.write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    out_html.write_text(html, encoding="utf-8")
    if not args.quiet:
        print(f"wrote {out_index}")
        print(f"wrote {out_html}")
        print("open it in a browser (double-click works — no server needed).")
    return 4 if bad_files else 0


if __name__ == "__main__":
    raise SystemExit(main())
