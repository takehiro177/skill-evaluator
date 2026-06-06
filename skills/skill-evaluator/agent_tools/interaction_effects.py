#!/usr/bin/env python3
"""Quantify the interaction between TWO OR MORE skills applied together.

Part of skill-evaluator. Standalone, *standard-library only* - no install, no
third-party deps (it imports only the sibling ``transcript_tokens.py``, which is
itself stdlib-only). Where ``transcript_tokens.py`` attributes tokens to a single
A/B arm, this script answers the question single-skill evaluation cannot:

    When several skills are applied at once, is the combined result MORE than the
    sum of the individual skills (synergy), LESS (redundancy / diminishing
    returns), or actively worse than the best single skill (conflict)?

That "interaction" term is the impact that goes un-measured when you only test
one skill at a time. This tool measures it from the real session transcript.

Designs it understands (it infers which from the arms you give it, by their
``subset`` - the set of skills injected into that arm):

* **combined-vs-baseline** - just ``base`` (no skills) and ``combo`` (all
  skills). Reports the combined effect only; interaction is NOT decomposable.
* **factorial-2** - ``base``, each single skill, and ``combo``. Full 2x2
  interaction (excess-over-additive) for two skills.
* **leave-one-out** - ``base``, ``combo`` (all), and ``combo`` minus each skill.
  Reports each skill's *marginal contribution within the stack*.
* **full-factorial** - every subset. Individual effects, pairwise interactions,
  and the total excess-over-additive.

Each arm's tokens are pulled from the transcript by its RUN MARKER (the same
marker scheme ``transcript_tokens.py`` uses), so the numbers are sourced, never
estimated. Effects are computed on every standard metric; the headline metric
(default ``cost_units`` - the cost-weighted, price-faithful figure) drives the
classification.

Input: a JSON *spec* describing the experiment. Schema::

    {
      "skills": ["alpha", "beta"],            # ordered skill names/labels
      "design": "factorial-2",                # optional; inferred if omitted
      "metric": "cost_units",                 # optional; default cost_units
      "lower_is_better": true,                 # optional; default true (tokens)
      "tasks": [
        {
          "id": "t1",
          "arms": [
            {"subset": [],               "marker": "SKILLEVAL-t1-BASE-7f3"},
            {"subset": ["alpha"],        "marker": "SKILLEVAL-t1-S1-9a2"},
            {"subset": ["beta"],         "marker": "SKILLEVAL-t1-S2-4c1"},
            {"subset": ["alpha","beta"], "marker": "SKILLEVAL-t1-COMBO-2bd"}
          ]
        }
      ]
    }

An arm may carry an inline ``"totals"`` dict (token components) instead of a
marker - used only for testing or as a fallback when the transcript can't be
read; a resolvable marker always wins, so the transcript stays the source of
truth.

Usage
-----
    python interaction_effects.py SPEC.json
    python interaction_effects.py SPEC.json --json
    python interaction_effects.py SPEC.json --metric output_tokens
    python interaction_effects.py SPEC.json --out reports/x-combo-eval-1.interaction
    python interaction_effects.py SPEC.json --session /path/to/session.jsonl

Exit codes: 0 ok, 2 no transcript found, 4 spec invalid / arm unmeasured.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Reuse the stdlib-only transcript reader that lives next to this script. Insert
# its directory on sys.path so the import resolves no matter the caller's CWD.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import transcript_tokens as tt  # noqa: E402

# Metrics we compute effects on. The first is the headline default; the rest are
# carried so the report can switch axes (output / context / round-trips) without
# re-running the experiment. "cost_units" is the cost-weighted, price-faithful
# figure - never headline the flat "total_tokens" sum (see docs/token-accuracy.md).
METRICS = [
    "cost_units",
    "output_tokens",
    "context_tokens",
    "total_tokens",
    "assistant_turns",
]

# Token/cost metrics are "lower is better" (a skill that saves tokens lowers
# them). Quality metrics would be higher-is-better; pass lower_is_better=false.
DEFAULT_METRIC = "cost_units"


# --------------------------------------------------------------------------- #
# Resolving arm token totals
# --------------------------------------------------------------------------- #


def _frozen(subset) -> frozenset:
    return frozenset(subset or [])


def resolve_arm_totals(arm: dict, runs: list[dict]) -> tuple[dict | None, str]:
    """Return (metrics_dict, note) for one arm.

    Prefers the transcript (matched by RUN MARKER); falls back to an inline
    ``totals`` dict only if the marker is absent or unresolvable. ``note`` flags
    how it was resolved (or why it is ``unmeasured``).
    """
    marker = arm.get("marker")
    if marker:
        matches = [r for r in runs if marker in (r.get("first_user_text") or "")]
        if len(matches) == 1:
            return matches[0], "transcript"
        if len(matches) > 1:
            # Ambiguous: a marker should be unique. Take the first, but say so.
            return matches[0], f"transcript (ambiguous: {len(matches)} matches)"
    totals = arm.get("totals")
    if isinstance(totals, dict):
        run = dict(totals)
        # Derive composite metrics if the caller gave only raw components.
        run.setdefault(
            "context_tokens",
            int(run.get("input_tokens", 0))
            + int(run.get("cache_creation_input_tokens", 0))
            + int(run.get("cache_read_input_tokens", 0)),
        )
        run.setdefault(
            "total_tokens",
            run["context_tokens"] + int(run.get("output_tokens", 0)),
        )
        run.setdefault("cost_units", round(tt.cost_units(run), 1))
        run.setdefault("assistant_turns", 0)
        src = "inline-totals" if not marker else "inline-totals (marker unresolved)"
        return run, src
    return None, "unmeasured"


# --------------------------------------------------------------------------- #
# Effect math (on a single chosen metric)
# --------------------------------------------------------------------------- #


def _val(cell: dict, metric: str) -> float:
    return float(cell.get(metric, 0) or 0)


def compute_effects(
    cells: dict,
    skills: list[str],
    metric: str,
    lower_is_better: bool,
    rel_tol: float,
) -> dict:
    """Decompose the combined effect into individual, marginal & interaction parts.

    ``cells`` maps ``frozenset(subset) -> metrics_dict``. Every piece degrades
    gracefully: a quantity is reported only when the arms needed to compute it
    are present, so the same function serves all four designs.
    """
    full = _frozen(skills)
    base_cell = cells.get(frozenset())
    combo_cell = cells.get(full)

    out: dict = {"metric": metric, "lower_is_better": lower_is_better}
    if base_cell is None or combo_cell is None:
        out["error"] = "need both a baseline (no skills) and a combo (all skills) arm"
        return out

    base = _val(base_cell, metric)
    combo = _val(combo_cell, metric)
    out["base"] = round(base, 1)
    out["combo"] = round(combo, 1)
    # Effect is signed (combo - base); savings is the "good direction" magnitude.
    out["combined_effect"] = round(combo - base, 1)
    out["combined_savings"] = round(
        (base - combo) if lower_is_better else (combo - base), 1
    )

    def savings(cell_v: float) -> float:
        return (base - cell_v) if lower_is_better else (cell_v - base)

    # Individual effects: skill i alone vs baseline (needs each single arm).
    individual: dict[str, float] = {}
    for s in skills:
        c = cells.get(frozenset([s]))
        if c is not None:
            individual[s] = round(_val(c, metric) - base, 1)
    if individual:
        out["individual_effects"] = individual
        out["individual_savings"] = {
            s: round(savings(base + d), 1) for s, d in individual.items()
        }

    # Marginal contributions: adding skill i to "everything else" (leave-one-out).
    marginal: dict[str, float] = {}
    for s in skills:
        loo = cells.get(full - {s})
        if loo is not None and len(full) >= 2:
            marginal[s] = round(combo - _val(loo, metric), 1)
    if marginal:
        out["marginal_effects"] = marginal

    # Pairwise interaction for any pair whose 4 cells (base, {i}, {j}, {i,j}) exist.
    pair_inter: dict[str, float] = {}
    for i in range(len(skills)):
        for j in range(i + 1, len(skills)):
            si, sj = skills[i], skills[j]
            cij = cells.get(frozenset([si, sj]))
            ci = cells.get(frozenset([si]))
            cj = cells.get(frozenset([sj]))
            if cij is not None and ci is not None and cj is not None:
                inter = _val(cij, metric) - _val(ci, metric) - _val(cj, metric) + base
                pair_inter[f"{si} x {sj}"] = round(inter, 1)
    if pair_inter:
        out["pairwise_interaction"] = pair_inter

    # Total interaction = excess of the combined effect over the additive
    # prediction from each skill's individual effect. Needs ALL single arms.
    have_all_singles = len(individual) == len(skills) and len(skills) >= 2
    if have_all_singles:
        additive_pred = base + sum(individual.values())
        interaction = combo - additive_pred  # signed, in metric units
        out["additive_prediction"] = round(additive_pred, 1)
        out["interaction"] = round(interaction, 1)
        additive_savings = sum(savings(base + d) for d in individual.values())
        out["additive_savings"] = round(additive_savings, 1)
        best_single_savings = max(savings(base + d) for d in individual.values())
        out["best_single_savings"] = round(best_single_savings, 1)

    out["classification"] = classify(out, rel_tol)
    return out


def classify(eff: dict, rel_tol: float) -> str:
    """Label the combination: synergistic / additive / redundant / conflicting."""
    combined_savings = eff.get("combined_savings", 0.0)
    if combined_savings < 0:
        return "costs-more - the stack is worse than no skills at all"

    if "interaction" not in eff:
        # combined-vs-baseline or leave-one-out: no additive prediction to test.
        if "marginal_effects" in eff:
            return "helps overall - see per-skill marginal contributions (no full interaction term)"
        return "helps overall - interaction not decomposed (add single-skill arms to measure it)"

    additive = eff.get("additive_savings", 0.0)
    best_single = eff.get("best_single_savings", 0.0)
    tol = max(rel_tol * abs(additive), 0.0)

    if combined_savings + tol < best_single:
        return (
            "conflicting / antagonistic - stacking is worse than the best single skill"
        )
    if combined_savings > additive + tol:
        return "synergistic - combined effect exceeds the sum of the parts"
    if combined_savings < additive - tol:
        return "redundant / sub-additive - diminishing returns, but still beats either alone"
    return "additive - combined effect ~= the sum of the individual effects"


# --------------------------------------------------------------------------- #
# Driver over tasks + aggregate
# --------------------------------------------------------------------------- #


def infer_design(skills: list[str], subsets: list[frozenset]) -> str:
    n = len(skills)
    full = _frozen(skills)
    have_base = frozenset() in subsets
    have_combo = full in subsets
    uniq = set(subsets)
    singles = sum(1 for s in uniq if len(s) == 1)
    loo = sum(1 for s in uniq if len(s) == n - 1 and len(s) >= 1 and s != full)
    if n == 2 and singles == 2 and have_base and have_combo:
        return "factorial-2"
    if len(uniq) >= 2**n:
        return "full-factorial"
    if loo >= 1 and have_base and have_combo and singles < n:
        return "leave-one-out"
    if have_base and have_combo:
        return "combined-vs-baseline"
    return "custom"


def analyze(spec: dict, runs: list[dict], args) -> dict:
    skills = list(spec.get("skills") or [])
    if len(skills) < 2:
        raise ValueError("spec.skills must list at least two skills")
    metric = args.metric or spec.get("metric") or DEFAULT_METRIC
    lower = spec.get("lower_is_better", True)
    rel_tol = args.rel_tol

    tasks_out = []
    # Accumulate arm metric values across tasks (by subset) to build an aggregate.
    agg_cells: dict[frozenset, dict[str, float]] = {}
    agg_counts: dict[frozenset, int] = {}
    notes = []
    all_subsets: list[frozenset] = []

    for task in spec.get("tasks") or []:
        cells: dict[frozenset, dict] = {}
        arm_rows = []
        for arm in task.get("arms") or []:
            subset = _frozen(arm.get("subset"))
            all_subsets.append(subset)
            totals, note = resolve_arm_totals(arm, runs)
            label = "+".join(sorted(subset)) or "(baseline)"
            if totals is None:
                notes.append(f"task {task.get('id')}: arm {label} unmeasured ({note})")
                arm_rows.append({"subset": sorted(subset), "resolved": note})
                continue
            cells[subset] = totals
            arm_rows.append(
                {
                    "subset": sorted(subset),
                    "resolved": note,
                    **{m: round(_val(totals, m), 1) for m in METRICS},
                }
            )
            acc = agg_cells.setdefault(subset, {m: 0.0 for m in METRICS})
            for m in METRICS:
                acc[m] += _val(totals, m)
            agg_counts[subset] = agg_counts.get(subset, 0) + 1

        eff = compute_effects(cells, skills, metric, lower, rel_tol)
        tasks_out.append({"id": task.get("id"), "arms": arm_rows, "effects": eff})

    # Aggregate = mean arm value across tasks, then the same decomposition.
    agg_mean = {
        subset: {m: vals[m] / agg_counts[subset] for m in METRICS}
        for subset, vals in agg_cells.items()
    }
    agg_eff = compute_effects(agg_mean, skills, metric, lower, rel_tol)

    design = spec.get("design") or infer_design(skills, all_subsets)
    return {
        "skills": skills,
        "design": design,
        "metric": metric,
        "lower_is_better": lower,
        "rel_tol": rel_tol,
        "per_task": tasks_out,
        "aggregate": {
            "arms": {
                "+".join(sorted(s)) or "(baseline)": {
                    m: round(v[m], 1) for m in METRICS
                }
                for s, v in agg_mean.items()
            },
            "effects": agg_eff,
        },
        "notes": notes,
    }


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _fmt(x) -> str:
    if isinstance(x, float):
        return f"{x:,.1f}".rstrip("0").rstrip(".") if x % 1 else f"{int(x):,}"
    return str(x)


def render_markdown(result: dict) -> str:
    skills = result["skills"]
    metric = result["metric"]
    agg = result["aggregate"]["effects"]
    lines = []
    lines.append("# Skill combination - interaction effects")
    lines.append("")
    lines.append(f"- **Skills:** {', '.join('`%s`' % s for s in skills)}")
    lines.append(f"- **Design:** `{result['design']}`")
    lines.append(
        f"- **Headline metric:** `{metric}` "
        f"({'lower is better' if result['lower_is_better'] else 'higher is better'})"
    )
    lines.append("")
    lines.append(f"**Verdict:** {agg.get('classification', 'n/a')}")
    lines.append("")

    if "error" not in agg:
        lines.append("## Aggregate decomposition (mean across tasks)")
        lines.append("")
        lines.append("| quantity | value (in `%s`) |" % metric)
        lines.append("|---|---:|")
        lines.append(f"| baseline (no skills) | {_fmt(agg.get('base'))} |")
        lines.append(f"| combo (all skills) | {_fmt(agg.get('combo'))} |")
        lines.append(
            f"| **combined effect** (combo - base) | {_fmt(agg.get('combined_effect'))} |"
        )
        lines.append(f"| combined savings | {_fmt(agg.get('combined_savings'))} |")
        for s, d in (agg.get("individual_effects") or {}).items():
            lines.append(f"| individual effect - `{s}` | {_fmt(d)} |")
        for s, d in (agg.get("marginal_effects") or {}).items():
            lines.append(
                f"| marginal contribution - `{s}` (within stack) | {_fmt(d)} |"
            )
        for pair, d in (agg.get("pairwise_interaction") or {}).items():
            lines.append(f"| pairwise interaction - {pair} | {_fmt(d)} |")
        if "interaction" in agg:
            lines.append(
                f"| additive prediction | {_fmt(agg.get('additive_prediction'))} |"
            )
            lines.append(
                f"| **interaction** (excess over additive) | {_fmt(agg.get('interaction'))} |"
            )
            lines.append(
                f"| best single-skill savings | {_fmt(agg.get('best_single_savings'))} |"
            )
        lines.append("")

    # Per-task arm table on the headline metric.
    lines.append("## Per-task (headline metric: `%s`)" % metric)
    lines.append("")
    lines.append(
        "| task | arm (skills injected) | `%s` | combined savings | classification |"
        % metric
    )
    lines.append("|---|---|---:|---:|---|")
    for t in result["per_task"]:
        eff = t["effects"]
        for arm in t["arms"]:
            label = "+".join(arm["subset"]) or "(baseline)"
            val = arm.get(metric)
            lines.append(
                f"| {t['id']} | {label} | {_fmt(val) if val is not None else '-'} |  |  |"
            )
        lines.append(
            f"| {t['id']} | **-> effect** |  | "
            f"{_fmt(eff.get('combined_savings'))} | {eff.get('classification', 'n/a')} |"
        )
    lines.append("")

    if result.get("notes"):
        lines.append("## Notes")
        lines.append("")
        for n in result["notes"]:
            lines.append(f"- {n}")
        lines.append("")

    lines.append(
        "> Interaction = combined effect minus the sum of individual effects: the part"
    )
    lines.append(
        "> of the combined result that single-skill evaluation never sees. Tokens are"
    )
    lines.append(
        "> sourced from the transcript via RUN MARKER, never estimated. Small N is"
    )
    lines.append("> directional, not conclusive.")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Quantify the interaction between 2+ combined skills."
    )
    ap.add_argument(
        "spec", help="Path to the JSON experiment spec (schema in module docstring)."
    )
    ap.add_argument(
        "--session", help="Specific transcript .jsonl (default: auto-detect)."
    )
    ap.add_argument("--project", help="Project cwd to resolve the transcript for.")
    ap.add_argument("--metric", help=f"Headline metric (default {DEFAULT_METRIC}).")
    ap.add_argument(
        "--rel-tol",
        type=float,
        default=0.10,
        help="Relative tolerance for additive vs synergistic/redundant (default 0.10).",
    )
    ap.add_argument(
        "--json", action="store_true", help="Emit JSON instead of Markdown."
    )
    ap.add_argument(
        "--out",
        help="Output basename - writes <out>.json and <out>.md (durable result files).",
    )
    args = ap.parse_args(argv)

    # Skill names can be non-ASCII; make stdout/stderr UTF-8 so printing the
    # Markdown table never dies on a legacy console code page (e.g. cp932/cp1252).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    try:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: cannot read spec {args.spec!r}: {e}", file=sys.stderr)
        return 4

    # Resolve the transcript once; arms with inline totals don't need it.
    needs_transcript = any(
        arm.get("marker")
        for task in (spec.get("tasks") or [])
        for arm in (task.get("arms") or [])
    )
    runs: list[dict] = []
    if needs_transcript:
        session = tt.resolve_session(args)
        if session is None:
            print(
                "error: could not locate a transcript. Pass --session PATH.",
                file=sys.stderr,
            )
            return 2
        runs = tt.gather_runs(session, include_text=False)

    try:
        result = analyze(spec, runs, args)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 4

    md = render_markdown(result)
    if args.out:
        Path(args.out + ".json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        Path(args.out + ".md").write_text(md, encoding="utf-8")
        print(f"wrote {args.out}.json and {args.out}.md")
    elif args.json:
        print(json.dumps(result, indent=2))
    else:
        print(md)

    # Surface unmeasured arms as a non-zero exit so callers notice.
    return 4 if result.get("notes") else 0


if __name__ == "__main__":
    raise SystemExit(main())
