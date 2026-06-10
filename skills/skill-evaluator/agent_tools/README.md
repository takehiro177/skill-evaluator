# agent_tools

Helper scripts bundled **inside the skill** (they install with it and resolve
relative to it). Everything except `deepeval_runner.py` is **standard-library
only** — Python ≥ 3.9, no install, no network.

| Tool | Deps | Role |
|------|------|------|
| `transcript_tokens.py` | stdlib | Per-run token attribution from the session transcript JSONL (by RUN MARKER). `--cost` for the cost-weighted view; `--full-text` for verbatim prompt + output (records companion); detects the `output_tokens` stub. |
| `interaction_effects.py` | stdlib | **Combination mode.** Combines per-arm totals (resolved from the transcript by marker) into combined / individual / marginal / interaction effects + a synergy/redundancy/conflict classification. |
| `combo_spec_builder.py` | stdlib | **Combination mode.** From one config (tasks + arm→marker map) reads the transcript once and writes every downstream input: interaction `spec.json`, `judge.spec.json`, N-arm `deepeval.cases.json`, and `deliverables.json`; exits non-zero if any arm is stubbed. |
| `judge_planner.py` | stdlib | Plans the blind judging phase: `plan` emits ready-to-dispatch blind prompts + a private Response→arm map; `resolve` un-blinds, derives the best single skill, tallies combo-vs-none / combo-vs-best-single. |
| `build_dashboard.py` | stdlib | **Phase 7.** Validates `reports/*.summary.json` against the versioned schema (in its docstring) and builds the Skill Harness Dashboard: `reports/index.json` + a self-contained `reports/dashboard.html`. |
| `deepeval_runner.py` | `deepeval`, `anthropic` | Required GEval quality cross-check (0–1 per arm), run via `uv` on demand. |

Schemas live where they're used: each script's input/output schema is in its
own docstring — the docstring is the contract.

## transcript_tokens.py

```bash
python transcript_tokens.py --json                 # all runs in the active transcript
python transcript_tokens.py --grep "SKILLEVAL-t1-A-7f3"          # one arm
python transcript_tokens.py --grep "<marker>" --cost              # cost-weighted
python transcript_tokens.py --grep "<marker>" --json --full-text  # + verbatim text
```

Cost weighting prices the four components at input 1× · cache-write 1.25× ·
cache-read 0.1× · output 5×. A run whose final turn logged the `output_tokens`
stub is flagged `output_tokens_suspect: true` — re-run that arm with a fresh
marker; never estimate.

## interaction_effects.py · combo_spec_builder.py · judge_planner.py

Combination-mode pipeline (specs and configs documented in each docstring):

```bash
python combo_spec_builder.py CONFIG.json --out reports/<combo>-combo-eval-<n>
python interaction_effects.py reports/<combo>-combo-eval-<n>.spec.json \
  --out reports/<combo>-combo-eval-<n>.interaction
python judge_planner.py plan  SPEC.json --out reports/<combo>-eval-<n>.judge
python judge_planner.py resolve reports/<combo>-eval-<n>.judge.map.json results.json \
  --out reports/<combo>-eval-<n>.judge
```

## build_dashboard.py

Validates the data layer and renders the governance view. Run from the repo
root (or pass `--reports`):

```bash
python build_dashboard.py --check --reports ../../../reports   # validate only (CI)
python build_dashboard.py --reports ../../../reports           # write index.json + dashboard.html
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--reports DIR` | `reports/` | Directory scanned for `*.summary.json`. |
| `--out PATH` | `<reports>/dashboard.html` | `index.json` is written next to it. |
| `--template PATH` | bundled `../templates/dashboard.html` | Resolved relative to this script. |
| `--check` | off | Validate only; write nothing. |
| `--no-artifacts` | off | Don't embed sibling JSON artifacts into the detail views. |
| `--quiet` | off | Only print problems. |

When building (not `--check`) the script also embeds each run's sibling JSON
artifacts — `<id>.deepeval.cases.json` (verbatim per-task arm outputs),
`<id>.deepeval.json`, `<id>.interaction.json`, `<id>.judge.verdicts.json`, or
the paths in the summary's `files` map — into the dashboard payload, which
powers each card's click-through detail view (WITH/WITHOUT output comparison,
deepeval results). `index.json` stays summaries-only.

Exit codes: 0 ok · 2 reports dir / template missing · 4 ≥ 1 invalid summary
(valid ones still render; CI treats 4 as failure). The summary schema
(`schema_version: 1`) is in this script's docstring; the summaries themselves
are written by the skill's **Phase 7** and must **mirror the report's
transcript-sourced numbers** — the builder validates and packages, it never
derives metrics. `reports/index.json` and `reports/dashboard.html` are build
products: regenerate them, never hand-edit. See
[`../../../docs/dashboard.md`](../../../docs/dashboard.md).

## deepeval_runner.py

```bash
uv run --with deepeval --with anthropic python deepeval_runner.py \
  reports/<name>-eval-<n>.deepeval.cases.json \
  --out reports/<name>-eval-<n>.deepeval
```

`deepeval >= 4` has **no** `[anthropic]` extra — install the `anthropic`
package explicitly as shown, or the run fails with
`No module named 'anthropic'`. Requires `ANTHROPIC_API_KEY` in the environment
(load from `.env` if needed; never echo the key). The cases-file schema —
single-skill pairs or a combination `arms` object — is in the docstring.
Outputs (`.deepeval.json`, `.deepeval.md`) are deliverables: keep them in
`reports/`.

## Packaging

`pyproject.toml` registers each module and a console script per tool
(`skilleval-tokens`, `skilleval-interaction`, `skilleval-combo-spec`,
`skilleval-judge`, `skilleval-dashboard`, `skilleval-deepeval`) for anyone who
prefers `pip install ./agent_tools` — entirely optional; the workflow always
invokes the scripts by path.
