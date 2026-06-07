# agent_tools

Standalone helper scripts that Claude Code can execute during a skill
evaluation. This folder is self-contained: it has its own `pyproject.toml` and
does not depend on anything else in the repo.

There are five tools, with very different requirements:

| Script | Purpose | Dependencies |
|--------|---------|--------------|
| `transcript_tokens.py` | Attribute token usage to each subagent (A/B arm) run by parsing the Claude Code session transcript. Flags the intermittent `output_tokens` logging stub. **Core** — used on every evaluation. | **None** (Python stdlib only) |
| `interaction_effects.py` | Quantify the **interaction** between 2+ combined skills (combined / individual / marginal / pairwise + total interaction, with a synergy/redundancy/conflict classification). Used in **combination mode**. | **None** (Python stdlib only; imports `transcript_tokens.py`) |
| `combo_spec_builder.py` | From one config (task list + arm→marker map) read the transcript once and write **all** downstream combination inputs: the interaction spec, the judge spec, the N-arm deepeval cases, and the per-arm/per-task deliverables. Used in **combination mode**. | **None** (Python stdlib only; imports `transcript_tokens.py`) |
| `judge_planner.py` | Plan + resolve the **blind judging** phase: emit ready-to-dispatch blind prompts with a private Response→arm map, then un-blind, derive the best single skill, and tally combo-vs-none / combo-vs-best-single. | **None** (Python stdlib only) |
| `deepeval_runner.py` | Library-backed GEval quality metrics via [`deepeval`](https://github.com/confident-ai/deepeval). **Required** — runs on every evaluation (skip only via `--no-deepeval` or a missing `ANTHROPIC_API_KEY`). | `deepeval`, `anthropic` |

The token half of the evaluation (deltas, interaction effects, and the blind
LLM-as-judge planning/resolution) runs with **only** the stdlib scripts; deepeval
adds a complementary library-backed quality score and
is now a **required phase** of every evaluation, with its results kept in
`reports/` (`<skill-name>-eval-<n>.deepeval.{json,md}`).

## `transcript_tokens.py` (no install)

> **Python command.** Use `python3` on macOS/Linux and `python` (or `py`) on
> Windows — the same stdlib-only interpreter (≥3.9). On Windows a bare `python3`
> is often a non-working Microsoft Store alias, so prefer `python`/`py` there.
> The `python …` examples below mean "whichever launcher your OS has".

```bash
# Per-run token totals for the current project's active transcript:
python transcript_tokens.py

# Machine-readable:
python transcript_tokens.py --json

# Pull a single A/B arm by its RUN MARKER:
python transcript_tokens.py --grep "SKILLEVAL-t1-A-7f3" --json

# Point at a specific transcript or project:
python transcript_tokens.py --session /path/to/session.jsonl
python transcript_tokens.py --project /path/to/other/project
```

It auto-detects `~/.claude/projects/<encoded-cwd>/<latest>.jsonl` (honoring
`CLAUDE_CONFIG_DIR`). See [`docs/token-measurement.md`](../../../docs/token-measurement.md)
for the transcript format and the attribution algorithm.

> **`output_tokens` stub detection.** Claude Code's subagent logging
> intermittently records a turn's `output_tokens` as a tiny placeholder
> (`1`/`3`/`4`) even though that turn emitted a full deliverable — a
> non-deterministic dropout that silently corrupts the output-token (and cost)
> figure of whichever arm it hits. Each run is checked: a text-bearing turn with
> implausibly few output tokens for its character count sets
> `output_tokens_suspect: true` (printed as a `⚠️` line and a stderr warning).
> When you see it, **re-run that arm** with a fresh RUN MARKER and identical
> prompt and use the clean read — never estimate the missing tokens.

## `interaction_effects.py` (no install) — combination mode

Used when evaluating **two or more skills combined**. Where `transcript_tokens.py`
attributes tokens to one arm, this combines the per-arm numbers into the
**interaction** between skills — the part single-skill testing misses. It reads a
JSON *spec* mapping each arm's skill `subset` to its RUN MARKER, resolves the
tokens from the transcript, and reports the combined effect, each skill's
individual/marginal effect, pairwise + total interaction (excess-over-additive),
and a classification (synergistic / additive / redundant / conflicting /
costs-more). Stdlib-only — it imports `transcript_tokens.py` and needs nothing else.

```bash
# Markdown report from a spec the workflow wrote (schema in the script's docstring):
python interaction_effects.py reports/caveman+code-map-combo-eval-1.spec.json

# Machine-readable, on the skill's billing axis instead of the cost headline:
python interaction_effects.py spec.json --json --metric output_tokens

# Durable result files next to the report (writes <out>.json and <out>.md):
python interaction_effects.py spec.json --out reports/caveman+code-map-combo-eval-1.interaction
```

See [`docs/combination-eval.md`](../../../docs/combination-eval.md) for the designs
(combined-vs-baseline / factorial / leave-one-out / full-factorial), the
interaction formula, and the classification rules.

## `combo_spec_builder.py` (no install) — combination mode

The one-step bridge from "the arms have run" to "every downstream tool has its
input". Instead of hand-writing the interaction spec, the judge spec, and the
deepeval cases separately, give it one config — the **task list** plus the **arm →
RUN MARKER** map — and it reads the transcript once, attributes each arm, splits
each arm's multi-task output into per-task deliverables, and writes all four
inputs. Stdlib-only.

```bash
python combo_spec_builder.py CONFIG.json --out reports/A+B-combo-eval-1
#   writes:
#     A+B-combo-eval-1.spec.json           -> interaction_effects.py
#     A+B-combo-eval-1.judge.spec.json     -> judge_planner.py plan
#     A+B-combo-eval-1.deepeval.cases.json -> deepeval_runner.py (N-arm)
#     A+B-combo-eval-1.deliverables.json   -> the records companion
```

Each arm's `subset` (skills injected) is **inferred from its name**
(`base`/`baseline`/`none` → none; `combo`/`all`/`both` or the joined skill set →
all; a name matching a skill → that skill) — override with an explicit `"subset"`.
Tasks can be inline or loaded from a `tasks_file` (e.g. the `*.tasks.json` the
workflow already wrote). It expects each arm's output to delimit tasks with
`## TASK <id>` after `=== FINAL OUTPUT ===` (override via `task_header_regex` /
`final_output_marker`). It re-checks every arm for the `output_tokens` stub and
**exits non-zero with a warning** if an arm needs re-running. Full config schema is
at the top of `combo_spec_builder.py`.

## `judge_planner.py` (no install) — blind judging

Mechanizes the most error-prone part of the workflow: building a clean judge
prompt per comparison, randomizing Response 1/2, keeping a private map to un-blind
later, and (in combination mode) picking the right comparisons. **You still
dispatch** each generated prompt to a fresh blind judge subagent; this tool only
prepares them and, afterwards, un-blinds and tallies. Stdlib-only.

```bash
# 1) Plan: spec (tasks + each arm's deliverable; schema in the script docstring)
#    -> blind prompts + a PRIVATE map.
python judge_planner.py plan SPEC.json --out reports/x-combo-eval-1.judge
#    writes x-combo-eval-1.judge.jobs.json (dispatch each jobs[].prompt) and
#           x-combo-eval-1.judge.map.json  (private — never show the judge)

# 2) Dispatch each jobs[].prompt to a blind judge subagent; collect the JSON
#    outputs as a single {job_id: <judge json>} object in results.json.

# 3) Resolve: un-blind + tally (best single derived from the head-to-heads).
python judge_planner.py resolve reports/x-combo-eval-1.judge.map.json results.json \
  --out reports/x-combo-eval-1.judge
#    writes x-combo-eval-1.judge.verdicts.{json,md}: per-task combo-vs-none and
#    combo-vs-best-single, with W/L/T tallies.
```

For combination it plans, per task, `combo vs none`, `combo vs each single`, and
each pair of singles (so best-single and combo-vs-best-single fall out with no
two-stage dependency). For a single-skill eval, give two arms
(`with_skill`/`without_skill`) and it plans the one with-vs-without comparison.
Override the auto-generated set with a `"comparisons"` list in the spec.

## `deepeval_runner.py` (required)

The deepeval judge backend is **pinned to Anthropic/Claude** — this project only
uses Claude, so there is no OpenAI fallback. The only thing you need is
`ANTHROPIC_API_KEY`. The runner reads it from the environment or, if it isn't set
there, **auto-loads it from a `.env`** in the working directory (searched upward)
or next to the script — no manual export needed (see
[`.env.example`](../../../.env.example)). To set it explicitly instead:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

> **Dependency gotcha:** `deepeval >=4` has **no** `[anthropic]` extra. A bare
> `--with "deepeval[anthropic]"` installs deepeval *without* the `anthropic`
> package and the run dies with `No module named 'anthropic'`. Always add
> `anthropic` explicitly (`--with deepeval --with anthropic`, or
> `pip install deepeval anthropic`).

Run it against a cases file the workflow wrote (see schema at the top of
`deepeval_runner.py`):

```bash
# Ephemeral dependencies via uv — installs nothing globally:
uv run --with deepeval --with anthropic python deepeval_runner.py cases.json --out report.deepeval

# …or installed into a venv:
pip install deepeval anthropic
python deepeval_runner.py cases.json --out report.deepeval
```

The judge defaults to `claude-sonnet-4-6` (a current, verified model id). Override
it with `--judge-model`:

```bash
uv run --with deepeval --with anthropic python deepeval_runner.py cases.json \
  --judge-model claude-opus-4-8 --out report.deepeval
```

This writes `report.deepeval.json` and `report.deepeval.md`. The workflow folds
the Markdown into the REQUIRED "deepeval metrics" section of the main report and
keeps both files (plus the `.cases.json`) in `reports/`.

> **Combination mode (N arms in one run).** Besides the single-skill
> `with_skill_output` / `without_skill_output` pair, a case may carry an `arms`
> object (`{"base": "...", "<skill>": "...", "combo": "..."}`). The runner then
> scores **every arm in one run** and emits a per-arm GEval table (with a
> Δ-vs-baseline row when an arm is named `base`/`baseline`/`none`) — no need for
> multiple paired runs. Schema is at the top of `deepeval_runner.py`.

> deepeval sends your task inputs and the candidate outputs to the Anthropic
> API (the pinned judge backend). Don't run it on sensitive content without
> checking Anthropic's data policy.
