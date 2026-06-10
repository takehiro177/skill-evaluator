---
name: skill-evaluator
description: >-
  Evaluate a Claude Code skill via blind A/B testing, entirely inside Claude
  Code chat. Use when the user asks to "evaluate a skill", "A/B test a skill",
  "measure if a skill helps", "benchmark a skill", or wants token-savings and
  output-quality numbers for a skill. Reads the target skill's SKILL.md to
  derive representative tasks, runs each task WITH and WITHOUT the skill via
  subagents, measures token deltas from the session transcript, scores quality
  with a blind LLM-as-judge subagent, and writes a Markdown evaluation report.
  Also evaluates TWO OR MORE skills COMBINED, quantifying their interaction
  (synergy, redundancy, or conflict) when stacked — use when the user asks to
  "evaluate skills combined", "A/B test multiple skills", "measure skill
  interaction/synergy", "do these skills work together", or points at 2+ skills.
---

# Skill Evaluator

You are running the **skill-evaluator** workflow: a self-contained, in-chat
A/B harness that measures whether a given Claude Code skill actually helps,
along two axes:

1. **Tokens saved** — the token-cost delta between solving a task WITH the
   skill's guidance vs WITHOUT it (measured from the real session transcript).
2. **Output quality** — scored by a **blind LLM-as-judge** subagent that never
   learns which response came from which arm.

**Two modes.** *Single-skill* (default) measures one skill WITH vs WITHOUT.
*Combination* measures **2+ skills applied together** and quantifies their
**interaction** — whether stacking them helps beyond the sum of the parts (synergy),
merely duplicates (redundancy), or actively conflicts. The phases below describe
single-skill mode; **[Combination mode](#combination-mode-2-skills)** at the end
lists exactly what changes when more than one skill is given.

Everything runs through Claude Code subagents. You (the orchestrator) own the
secret arm→label mapping; the judge never sees it. Be rigorous, be honest, and
never fabricate numbers — every token figure must come from the transcript and
every quality verdict must come from the judge subagent.

---

## Inputs

The user points you at a skill to evaluate. Accept any of:

- A path to a skill directory containing `SKILL.md`
  (e.g. `./.claude/skills/my-skill` or an absolute path).
- A path directly to a `SKILL.md` file.
- A skill name — search `./.claude/skills/`, `~/.claude/skills/`, and any
  plugin skill dirs for a matching `SKILL.md`.

**Multiple skills → combination mode.** If the user names **two or more** skills
(e.g. "evaluate skills A and B combined", "do X and Y work together"), resolve each
the same way and run **[Combination mode](#combination-mode-2-skills)** instead of
the single-skill procedure. Default design: full 2×2 factorial for exactly two
skills, combined-vs-baseline for three or more (override with `--leave-one-out` /
`--full-factorial`).

Optional knobs (ask only if ambiguous; otherwise use defaults):

| Knob              | Default | Meaning                                             |
|-------------------|---------|-----------------------------------------------------|
| `--tasks N`       | `3`     | Number of evaluation tasks to derive.               |
| `--from-history`  | off     | Also mine the user's past sessions for real tasks.  |
| `--no-deepeval`   | off     | Skip the deepeval metrics. deepeval runs by **default** — it is a REQUIRED phase (Phase 6). Only skip if no `ANTHROPIC_API_KEY` / deps are available, and then say so explicitly in the report. |
| `--report PATH`   | auto    | Where to write the report (default `reports/`).     |
| `--leave-one-out` | off     | **(combination)** Add an arm per skill *dropped* from the full stack, to measure each skill's marginal contribution. N + 2 arms. |
| `--full-factorial`| off     | **(combination)** Run *every* subset (2ᴺ arms) for the complete interaction map. Warn the user before N ≥ 4. |

---

## Procedure

Work through the phases in order. Announce each phase briefly. Do **not**
parallelize the two arms of the same task in a way that loses token
attribution — see Phase 3.

> **Bundled resources & paths.** This skill ships its own helper scripts and
> templates inside its directory: `agent_tools/` and `templates/`. Every
> `agent_tools/…` and `templates/…` path in this document is **relative to this
> skill's own directory** (the folder that contains this `SKILL.md`) — *not* the
> project working directory. Since you are normally invoked from a project root,
> run the Python helper by its path inside this skill directory (or `cd` into
> that directory first), e.g. `python <this-skill-dir>/agent_tools/transcript_tokens.py`.
>
> **Python command (cross-platform).** Invoke the helper with whichever Python 3
> launcher the host has: `python3` on macOS/Linux, `python` (or the `py` launcher)
> on Windows — they're the same interpreter (≥3.9, stdlib only). If the first
> isn't on `PATH`, try the other; on Windows in particular a bare `python3` is
> often a non-functional Microsoft Store alias, so prefer `python`/`py` there.
> Every `python …` example below means "whichever of these runs on this OS".

### Phase 0 — Locate & understand the target skill

1. Resolve the skill path from the user input. Read its `SKILL.md` (frontmatter
   **and** body). If it references bundled resources (other files in the skill
   dir), skim them too.
2. Write a short, neutral **capability summary**: what the skill claims to do,
   what triggers it, what inputs it expects, and what outputs/artifacts it
   promises. Quote the skill's own `description` verbatim as the source of
   truth for "what it claims".
3. Record the **full skill body text** — you will inject it into the WITH arm.
4. **Classify the skill's token mechanism** — the axis it actually bills on. This
   decides the primary metric (Phase 3/5) and the task design (Phase 1):
   - `output` — compresses/shortens the *response* (e.g. a terse output style).
     Bills on **output tokens** (5× price). One-time cost: a guidance load.
   - `context` — makes Claude *read less* into context (e.g. a code-map / index /
     "graphify" skill that avoids reading many files). Bills on **input +
     cache-read tokens pulled in**; proxy = number / size of files read.
   - `round-trips` — avoids tool calls / turns (e.g. plan-once, batch-tools).
     Bills on **# tool calls / assistant turns**.
   - `none` — no token claim (pure behavior/format). Say so and skip the token
     headline.
   Quote the claim that implies the mechanism; if unsure, pick the closest and
   note it. See [`docs/token-accuracy.md`](../../docs/token-accuracy.md).

> If you cannot find a `SKILL.md`, stop and ask the user for the correct path.

### Phase 1 — Derive evaluation tasks

Generate `--tasks N` (default 3) **representative, concrete, self-contained**
tasks that a real user would plausibly ask and that fall squarely inside what
the skill *claims* to help with. Derive them from the skill's claims — not from
its implementation details — so the test measures the promise, not the prose.

For each task produce a JSON object:

```json
{
  "id": "t1",
  "prompt": "The exact user request, fully self-contained.",
  "input": "Any input data/files the task needs, inline or as a path. May be empty.",
  "rubric": "3-6 concrete, skill-agnostic criteria a great answer must satisfy."
}
```

Rules for good tasks:

- **Cover the claim surface.** If the skill claims several capabilities, spread
  tasks across them rather than testing one thing three times.
- **Be answerable without the skill.** Both arms must be *able* to attempt it;
  the skill should help, not be strictly required, or the comparison is moot.
- **Keep rubrics skill-agnostic.** The rubric describes a good *outcome*, never
  mentions the skill, "with/without", or any methodology. The judge will see it.
- **Avoid leakage.** No task text may name the skill or hint that an A/B test is
  happening.
- **Exercise the mechanism (Phase 0.4).** A `context` skill needs tasks over a
  real repo that *require reading several files*; a `round-trips` skill needs
  multi-step tool tasks. If the task can't engage the skill's mechanism, the
  comparison is moot.

If `--from-history` is set, also search past session transcripts (see
`docs/token-measurement.md` for transcript locations) for real user prompts
that match the skill's trigger description, and adapt 1-2 of them into tasks.
Strip anything sensitive; keep them self-contained.

Show the derived tasks to the user before running (a quick list is fine).

### Phase 2 — Run the A/B arms via the runner subagent

For **each** task, you will dispatch the `skill-eval-runner` subagent **twice**
— once per arm. Use **injection-based A/B**: the WITH arm receives the skill's
full body text inline; the WITHOUT arm does not. This makes the test
reproducible and independent of whether the skill is installed.

> **If `skill-eval-runner` / `skill-eval-judge` aren't registered as subagent
> types** (e.g. running from the source repo, where they live in `agents/` rather
> than an installed `.claude/agents/`), dispatch a generic subagent instead and
> **embed that agent's rules verbatim** at the top of the prompt (the runner's hard
> rules; the judge's blind-scoring rules + JSON schema). Behavior and blindness are
> identical — the agent files are just instruction sets. Installing the skill (or
> `claude --plugin-dir .`) registers them so you can call them by name.

Before dispatching, for each (task, arm) mint a unique **run marker** of the
form `SKILLEVAL-<taskId>-<A|B>-<short-random>` (vary the random suffix per run;
e.g. derive it from the task id and arm). Keep a **private mapping** in your own
working notes:

```
t1-A  -> WITH     marker=SKILLEVAL-t1-A-7f3
t1-B  -> WITHOUT  marker=SKILLEVAL-t1-B-9a2
...
```

**Randomize** which arm is "A" vs "B" per task so position can't be guessed.

Dispatch the **WITHOUT** arm with a prompt shaped like:

```
RUN MARKER: <marker>     # echo this exact line back as your first output line

You are completing one task in isolation. Use only general knowledge and the
standard tools. Do not load or invoke any specialized skill.

TASK:
<task.prompt>

INPUT:
<task.input>

Produce the best possible result. End with a clearly delimited
=== FINAL OUTPUT === section containing only the deliverable.
```

Dispatch the **WITH** arm identically, but insert, right after the marker line:

```
You have the following skill guidance available. Apply it as intended:

<<<SKILL GUIDANCE
<full SKILL.md body text of the target skill>
SKILL GUIDANCE>>>
```

Important runner rules to bake into every dispatch:

- The runner must **echo the RUN MARKER as its very first output line** — this
  is how token usage is later attributed to the correct arm.
- The runner must **not** mention or speculate about A/B testing.
- Keep both prompts identical except for the injected skill guidance and the
  marker, so the only variable is the skill.

Run all arms for all tasks **within this same session** so their token usage
lands in this session's transcript.

**Production conditions (do not skip — these are what make tokens accurate):**

- **Warm the cache, run arms serially.** The first subagent after a >5-min idle
  pays the shared prompt prefix as a *cold* cache write (1.25×); later arms read
  it warm (0.1×). Whichever arm runs first eats that cold write — a pure ordering
  artifact that can dwarf the real signal. Fire one throwaway **primer** subagent
  first to warm the prefix, then run the arms **sequentially** (not in parallel,
  so concurrent cold writes can't happen). If you can't warm it, normalize in
  Phase 3 by charging the shared prefix as a warm read for both arms.
- **Amortize one-time setup — for a persistent / `output` skill, inject ONCE and
  run several turns.** Re-injecting the guidance per task charges its one-time
  cost N times and makes the skill look worse than it is. Prefer a
  **single-injection, multi-task** runner: give the WITH runner the guidance once
  and have it answer several representative requests in one session (the control
  answers the same set with no guidance). This mirrors how the skill loads its
  guidance once per real session and amortizes it across every turn.

Collect each runner's returned `=== FINAL OUTPUT ===` text, keyed by run id.

### Phase 3 — Measure tokens from the transcript

Token figures come from the session transcript JSONL, never from estimation.

Use the bundled helper (stdlib-only, no install needed):

```
python agent_tools/transcript_tokens.py --json
```

It auto-detects the current project's most-recently-active transcript, segments
each subagent (sidechain) run, and prints per-run token totals plus each run's
first user-message text (which contains the RUN MARKER). To pull a single arm:

```
python agent_tools/transcript_tokens.py --grep "SKILLEVAL-t1-A-7f3"
```

Add `--full-text` to also capture each run's **verbatim** dispatch prompt and
full assistant output (the runner's `=== FINAL OUTPUT ===` included). You will
need this in Phase 5 to build the human-reviewable records companion, so it is
efficient to capture it now, per arm:

```
python agent_tools/transcript_tokens.py --grep "SKILLEVAL-t1-A-7f3" --json --full-text
```

This text is the ground-truth A/B record — do not paraphrase or reconstruct the
arm outputs from your own memory; always source them from the transcript.

For each task (or each session, for a single-injection multi-task run), map the
runs via their markers and compute:

- The four components per arm: `input`, `cache_creation`, `cache_read`, `output`
  (the helper reports all four).
- **Primary metric = the axis from Phase 0.4**, never the flat total:
  - `output` skill → `output_tokens` delta (and % reduction);
  - `context` skill → `input + cache_read` delta (and # / size of files read);
  - `round-trips` skill → tool-call / turn count delta.
- **Cost-weighted "effective tokens" (always).** The flat sum
  (`input + cache + output`) prices a 0.1× cache-read token the same as a 5×
  output token and *will mislead*. Run the helper with `--cost` and report the
  cost-weighted delta as the cost headline:

  ```
  python agent_tools/transcript_tokens.py --grep "<marker>" --cost
  ```

  (Ratios: input 1×, cache-write 1.25×, cache-read 0.1×, output 5× — the
  output:input 5× ratio holds across the current Claude lineup.) A negative
  result is real and reportable — say so plainly.
- **Separate one-time setup from recurring savings.** Identify the skill's
  one-time cost (the injected-guidance `cache_creation` delta, or an index build)
  and the per-turn / per-query saving. Compute **breakeven** (turns/queries to
  repay setup) and an **N-turn amortized** projection. The flat per-task total is
  a real number — but label it the harness artifact it is when setup is charged
  per task.

**Watch for the `output_tokens` stub.** Claude Code's subagent logging
intermittently records an arm's final-turn `output_tokens` as a tiny placeholder
(`1`/`3`/`4`) even though that turn emitted a full deliverable — a
non-deterministic, content-independent dropout that silently corrupts the
output-token (and cost) figure of whichever arm it hits. `transcript_tokens.py`
detects this and sets **`output_tokens_suspect: true`** on the run (plus a stderr
warning). When you see it, **re-run that arm** with a *fresh* RUN MARKER and an
*identical* prompt, then use the clean read — keeping arms comparable means
re-running them all under one consistent prompt if their instructions would
otherwise differ. Single-turn, zero-tool runners are least prone to it. **Never
estimate the missing tokens.**

If the helper cannot run (no Python, unusual transcript location), fall back to
reading the JSONL directly per `docs/token-measurement.md`. If you genuinely
cannot attribute tokens for an arm, mark it `unmeasured` in the report rather
than guessing.

### Phase 4 — Blind LLM-as-judge

For **each** task, dispatch the `skill-eval-judge` subagent with a **clean
prompt** — the judge must receive only: the task, the rubric, and the two
responses labeled neutrally (`Response 1` / `Response 2`). Randomize which arm
is Response 1 vs Response 2, **independently** of the Phase 2 randomization, and
record this mapping privately too.

The judge prompt must contain **none** of:

- the words "skill", "with/without", "arm", "A/B", "treatment", "baseline";
- the run markers;
- any token numbers;
- any hint about which response was expected to be better.

The judge returns structured scores per response and a winner (or tie) with a
rationale. After it returns, **un-blind** using your private Response→arm map.

> The judge is a fresh subagent every time. Never reuse a judge context across
> tasks, and never let judge and runner share a context.

### Phase 5 — Aggregate & write the report

Combine token deltas (Phase 3) and quality verdicts (Phase 4) into one report
using `templates/report-template.md`. Include:

- The skill's **mechanism** (Phase 0.4) and the **primary metric** chosen for it.
- A **joint headline verdict**: the cost-weighted token result AND the quality
  result, combined — e.g. "saved ~X% (cost-weighted) with quality within noise",
  or "saved tokens **but** cost ~Δq quality (lost W/T/L)". A token win with a
  quality loss is a regression, not a win — say so. Never headline the flat total.
- A per-task / per-session table: primary-metric delta, cost-weighted delta, judge
  winner, judge scores.
- One-time setup cost, per-turn / query saving, **breakeven**, and an N-turn
  **amortized** projection (Phase 3).
- Aggregates: total & mean primary-metric saved; quality win/loss/tie tally; mean
  score delta (WITH minus WITHOUT).
- **A REQUIRED deepeval section** (Phase 6): per-task GEval scores (0–1), mean Δ
  (WITH − WITHOUT), and a one-line note on how it corroborates/contrasts the blind
  judge. Link the standalone `<skill-name>-eval-<n>.deepeval.{md,json}` outputs. If
  deepeval could not run, state `unavailable — <reason>` here — never omit it.
- **Methodology & caveats**: injection-based A/B, blind judging, sample size,
  variance warning (N is small; treat as directional, not statistical proof),
  and any `unmeasured` arms.
- The exact derived tasks and rubrics (appendix), for reproducibility.

Write the report to `reports/<skill-name>-eval-<n>.md` (pick an unused name; do
not invent a timestamp — number sequentially or ask the user). Print the
headline verdict and the report path in chat.

### Phase 5b — Write the verbatim records companion

The report summarizes; the **records file** preserves the actual experiment so a
human can review the WITH/WITHOUT difference and check your work by hand. Write a
second file alongside the report using `templates/records-template.md`:

`reports/<skill-name>-eval-<n>-records.md` (same base name + `-records`).

For **each task**, pull both arms' verbatim content from the transcript and lay
them out **side by side** (WITH left, WITHOUT right) in a two-column HTML table,
so a reader can diff the arms at a glance — see `templates/records-template.md`:

```
python agent_tools/transcript_tokens.py --grep "<arm RUN MARKER>" --json --full-text
```

Use the returned `first_user_text` (the exact dispatch prompt) and
`assistant_text` (the full runner output, including its `=== FINAL OUTPUT ===`).
Put each arm's `assistant_text` in its side-by-side `<pre>` cell, **HTML-escaped
only** (`&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;`) so it renders without breaking
the table — change nothing else. Collapse the near-identical dispatch prompts
under a `<details>` toggle per task. Then un-blind: label each arm WITH / WITHOUT
using your private marker→arm map, and annotate each task with its rubric, the
judge's verdict, and the token totals (so the records file stands on its own next
to the report).

Rules for the records file:

- **Content-exact.** Never rewrite, summarize, trim for content, or reconstruct
  an arm's output from memory — the only permitted transform is HTML-escaping for
  rendering inside `<pre>`. A byte-exact copy must stay reproducible via
  `transcript_tokens.py --grep "<marker>" --full-text`. Token-savings claims are
  only credible if the records back them up.
- **Source from the transcript, not your chat memory.** The runner outputs you
  saw returned in Phase 2 are a convenience; the records file's source of truth
  is the JSONL via `--full-text`.
- If an arm genuinely cannot be recovered from the transcript, mark it
  `unmeasured` here too — do not fabricate it.
- The records file may legitimately be large. That is fine; it is the audit
  trail, not the summary.

Print both paths (report + records) in chat when done.

### Phase 6 — deepeval metrics (REQUIRED)

deepeval runs on **every** evaluation — it is mandatory, not opt-in. Skip it only
with explicit `--no-deepeval`, or when `ANTHROPIC_API_KEY` / deps are genuinely
unavailable; in that case the report's deepeval section must say
`unavailable — <reason>` rather than be omitted. Hand off to the standalone tool
in `agent_tools/`:

1. Write the per-task arm outputs to a JSON cases file
   `reports/<skill-name>-eval-<n>.deepeval.cases.json` (schema at the top of
   `agent_tools/deepeval_runner.py`: a list of
   `{id, input, rubric, with_skill_output, without_skill_output}`).
2. Run it, writing **durable** result files next to the report:

   ```
   uv run --with deepeval --with anthropic python agent_tools/deepeval_runner.py \
     reports/<skill-name>-eval-<n>.deepeval.cases.json \
     --out reports/<skill-name>-eval-<n>.deepeval
   ```

   `deepeval >=4` has **no** `[anthropic]` extra — install the `anthropic` package
   explicitly as shown (a bare `--with "deepeval[anthropic]"` silently omits it and
   the run fails with `No module named 'anthropic'`). The judge needs
   `ANTHROPIC_API_KEY` in the environment (load it from a `.env` if needed; do not
   echo the key). See `agent_tools/README.md`.

3. This writes `reports/<skill-name>-eval-<n>.deepeval.json` and `.deepeval.md`.
   These plus the `.deepeval.cases.json` are **deliverables — keep them in
   `reports/`; never delete them in cleanup.** Fold the `.deepeval.md` table into
   the report's REQUIRED "deepeval metrics" section (Phase 5).

deepeval's GEval is an **absolute** 0–1 quality score per arm (it scores each
answer in isolation and tends to saturate, so it does not discriminate the fine
pairwise gaps the blind judge catches). Report it **alongside** the blind judge
as a complementary cross-check, never as a replacement, and print the
`.deepeval.md` path in chat alongside the report and records paths.

### Phase 7 — Summary JSON + Skill Harness Dashboard (REQUIRED)

The Markdown report is the human/audit layer. Phase 7 publishes the same result
into the **data layer** — a small, versioned JSON next to the report — and
refreshes the **Skill Harness Dashboard**, the single static page that shows
every evaluation in `reports/` as a report card so a team can govern its skill
portfolio (adopt / reject / re-run) without re-reading every report.

**1. Write the summary JSON** to
`reports/<skill-name>-eval-<n>.summary.json` (combination:
`reports/<combo>-combo-eval-<n>.summary.json`) — same base name as the report
plus `.summary.json`. The full schema and field reference live at the top of
`agent_tools/build_dashboard.py`; this is the shape (single-skill; plain JSON —
copy, fill, and delete what you didn't measure):

```json
{
  "schema_version": 1,
  "id": "<report basename, e.g. my-skill-eval-1>",
  "kind": "single",
  "skills": [{"name": "<skill>", "mode": "<mode-if-any>", "mechanism": "output"}],
  "design": "with-vs-without (single-injection, multi-task)",
  "run": 1,
  "date": "YYYY-MM-DD",
  "tasks": 3,
  "verdict": {
    "label": "helps",
    "emoji": "✅",
    "headline": "<the report's one-line joint token+quality verdict>",
    "bottom_line": "<the report's Bottom line>"
  },
  "metrics": {
    "mechanism": "output",
    "primary_axis": "output_tokens",
    "headline": {"cost_delta_pct": -48.5, "primary_delta_pct": -58.9,
                 "primary_label": "output tokens"},
    "arms": [
      {"name": "WITHOUT", "skills": [], "cost_units": 21799, "output_tokens": 4060},
      {"name": "WITH", "skills": ["<skill>"], "cost_units": 11235, "output_tokens": 1668}
    ],
    "setup": {"one_time_cost_units": 1396, "per_turn_saving_cost_units": 3987,
              "breakeven_turns": 0.35}
  },
  "quality": {
    "pairwise": {"comparison": "with_vs_without", "wins": 0, "ties": 0,
                 "losses": 3, "mean_delta": -1.0},
    "deepeval": {"available": true, "arm_means": {"WITH": 1.0, "WITHOUT": 1.0},
                 "delta_vs_baseline": 0.0}
  },
  "per_task": [
    {"id": "t1", "title": "<short title>", "winner": "WITHOUT", "margin": "slight",
     "scores": {"WITH": 8, "WITHOUT": 9}, "deepeval": {"WITH": 1.0, "WITHOUT": 1.0}}
  ],
  "caveats": ["small-n (3 tasks, 1 run)"],
  "files": {"report": "<basename>.md", "records": "<basename>-records.md",
            "deepeval_md": "<basename>.deepeval.md"}
}
```

A **combination** summary uses `"kind": "combination"`, lists every skill in
`skills`, one `metrics.arms` entry **per subset** (base / each single / combo,
with each arm's injected `skills` list), and adds the `interaction` block
(classification, `value` = excess over additive, `combined_savings`,
`additive_prediction`, `individual_effects`, `marginal_effects`, `best_single`,
`best_single_savings` — all from `interaction_effects.py`'s output) plus
`quality.combo_vs_none` and `quality.combo_vs_best_single` (from
`judge_planner.py resolve`'s tally). The tracked examples
`reports/caveman-eval-1.summary.json` and
`reports/caveman+karpathy-combo-eval-1.summary.json` are complete references
for both kinds.

**HARD RULE — the summary is a projection of the report, never a second
computation.** Every number must equal a figure that is already in the report
or its JSON artifacts (`*.interaction.json`, `*.judge.verdicts.json`,
`*.deepeval.json` — all transcript-sourced). Do not re-derive, re-round
differently, or estimate. Anything unmeasured is **omitted** (or flagged
`"available": false`), exactly as the report marks it `unmeasured`.

**2. Validate, then rebuild the dashboard** with the bundled stdlib-only
builder (no deps, no network):

```
python agent_tools/build_dashboard.py --check --reports reports
python agent_tools/build_dashboard.py --reports reports
```

`--check` schema-validates every `reports/*.summary.json` and prints
errors/warnings — fix the summary (not the validator) until it passes. The
second command writes `reports/index.json` (every valid summary in one
machine-readable file, for CI gates and tooling) and `reports/dashboard.html`
(the self-contained governance page with the data embedded — opens from
`file://`, no server). The build also embeds each run's sibling JSON
artifacts (`*.deepeval.cases.json` — the verbatim per-task arm outputs —
`*.deepeval.json`, `*.interaction.json`, `*.judge.verdicts.json`) so every
card clicks through to a full detail page with the WITH/WITHOUT output
comparison and deepeval results — one more reason those deliverables stay in
`reports/`. Never hand-edit the two outputs; regenerate them.

**3. Print the dashboard path** in chat alongside the report, records, and
deepeval paths, e.g. "Dashboard refreshed: `reports/dashboard.html`".

---

## Combination mode (2+ skills)

When the user points you at **two or more** skills, you evaluate them *together*
and measure their **interaction** — the impact single-skill A/B never captures.
Everything from single-skill mode carries over (injection-based arms,
transcript-sourced **cost-weighted** tokens, the blind judge, deepeval, every
integrity rule); the one change is that **an arm is now defined by the *subset* of
skills injected into it**, and two new artifacts are produced. The methodology is
[`docs/combination-eval.md`](../../docs/combination-eval.md).

### Design — how many arms

Let **N** = number of skills. Pick the design (user may override):

| N / flag | Design | Arms / task | Subsets run |
|---|---|---|---|
| N = 2 (default) | **factorial-2** | 4 | ∅, {A}, {B}, {A,B} |
| N ≥ 3 (default) | **combined-vs-baseline** | 2 | ∅, {all} |
| `--leave-one-out` | leave-one-out | N + 2 | ∅, {all}, and {all}\{i} for each skill |
| `--full-factorial` | full-factorial | 2ᴺ | every subset |

`combined-vs-baseline` is the cheap default for 3+ skills: it answers "does the
bundle help?" but **cannot** attribute the effect to a skill or compute an
interaction term. Say so, and offer `--leave-one-out` / `--full-factorial` when the
user wants per-skill attribution. Warn before running full-factorial for N ≥ 4
(16+ arms × tasks).

### Phase 0 (combination) — mechanism overlap

Run Phase 0 for **each** skill. Then add an **overlap prior** by comparing their
mechanisms (Phase 0.4): same axis (e.g. two `output` reducers) ⇒ expect redundancy
or conflict; different axes (e.g. `output` + `context`) ⇒ expect roughly additive.
State the prior — the measured interaction will confirm or refute it.

### Phase 1 (combination) — tasks that engage every skill

Derive tasks inside the **overlap of the skills' claim surfaces** so the
combination can actually engage. A task only one skill can help with cannot reveal
interaction; each task must be able to exercise all the skills at once (most of
them, for leave-one-out).

### Phase 2 (combination) — subset injection + markers

For each task, dispatch one `skill-eval-runner` per arm in the design. Each arm
injects the bodies of **exactly the skills in its subset**, each in its own
**labelled** guidance block, in a fixed order:

```
You have the following skill guidance available. Apply ALL of it as intended:

<<<SKILL GUIDANCE [<skill-a name>]
<skill-a body>
SKILL GUIDANCE>>>

<<<SKILL GUIDANCE [<skill-b name>]
<skill-b body>
SKILL GUIDANCE>>>
```

The baseline arm injects **no** guidance block; the combo arm injects **all**.
Mint a unique marker per (task, subset): `SKILLEVAL-t1-BASE-<rand>`,
`SKILLEVAL-t1-S<i>-<rand>` (single skill *i*), `SKILLEVAL-t1-NOT<i>-<rand>`
(leave-one-out, all but *i*), `SKILLEVAL-t1-COMBO-<rand>`. Keep the private
subset→marker map in your notes, and **randomize arm order**. **Warm the cache +
run arms serially** and **amortize one-time setup** exactly as in single-skill
Phase 2 — these matter *more* here because more arms share the prefix.

### Phase 3 (combination) — interaction effects

> **Build every downstream spec in one step with `combo_spec_builder.py`.** Rather
> than hand-writing the interaction spec, the judge spec, and the deepeval cases
> separately, give the builder one config — your **task list** plus the **arm →
> RUN MARKER** map (it infers each arm's `subset` from its name) — and it reads the
> transcript once and writes all of them:
> `python agent_tools/combo_spec_builder.py CONFIG.json --out reports/<combo>-combo-eval-<n>`
> produces `<…>.spec.json` (interaction), `<…>.judge.spec.json` (judging),
> `<…>.deepeval.cases.json` (N-arm deepeval), and `<…>.deliverables.json` (verbatim
> per-arm/per-task text for the records file). It also re-checks every arm for the
> `output_tokens` stub and **exits non-zero with a warning if any arm needs
> re-running** — do that before trusting the numbers. Config schema is in the
> script's docstring; it expects each arm's multi-task output to delimit tasks with
> `## TASK <id>` after `=== FINAL OUTPUT ===` (the runner format above).

Pull each arm's tokens with `transcript_tokens.py --grep "<marker>" --cost` as
usual. Then write a **spec file** (schema in the script's docstring) mapping every
arm's `subset` + `marker` — or use the `<…>.spec.json` the builder just wrote — and
run the helper:

```
python agent_tools/interaction_effects.py reports/<combo>-combo-eval-<n>.spec.json \
  --out reports/<combo>-combo-eval-<n>.interaction
```

It resolves each marker from the transcript and computes, per task and aggregated:
the **combined effect**, each skill's **individual effect** (factorial), **marginal
contribution** (leave-one-out), **pairwise** + **total interaction**
(excess-over-additive), and a **classification** (synergistic / additive /
redundant / conflicting / costs-more). Re-run with `--metric output_tokens` (etc.)
to view the effects on the skills' billing axis as well as the cost-weighted
headline. **Never compute the interaction by hand** — the helper sources every arm
from the transcript; an arm it cannot attribute is `unmeasured`, not guessed.

### Phase 4 (combination) — two decisive judge comparisons

Keep the judge blind and pairwise, but make the two comparisons that matter for a
stack, **per task**:

1. **combo vs none** — combo arm vs baseline arm (does the stack help at all?).
2. **combo vs best single skill** — combo arm vs the single-skill arm with the best
   solo result (factorial / full-factorial / leave-one-out only; skip if no single
   arms exist). If the combination loses here, the extra skills are dead weight or
   harmful *regardless of the token numbers*.

Randomize Response 1/2 independently for each comparison; un-blind privately after.

> **Mechanize this with `judge_planner.py`** — building these prompts and tracking
> the private Response→arm map by hand is the most error-prone step. Write a spec
> (tasks + each arm's deliverable, schema in the script's docstring) and run
> `python agent_tools/judge_planner.py plan SPEC.json --out reports/<combo>-eval-<n>.judge`.
> It emits `<…>.jobs.json` (one **ready-to-dispatch blind prompt** per comparison —
> combo-vs-none, combo-vs-each-single, and the singles head-to-head, with Response
> 1/2 positions randomized) and a **private** `<…>.map.json`. Dispatch each
> `jobs[].prompt` to a fresh judge subagent, collect outputs as
> `{job_id: <judge json>}`, then
> `judge_planner.py resolve <…>.map.json results.json --out reports/<combo>-eval-<n>.judge`
> un-blinds, **derives the best single skill from the head-to-heads**, and tallies
> combo-vs-none and combo-vs-best-single — no two-stage bookkeeping, no leaked arm
> identities. (Works for single-skill too: two arms → one with-vs-without job.)

### Phase 5 / 5b (combination) — combo report + records

Write the report with [`templates/combo-report-template.md`](templates/combo-report-template.md)
to `reports/<combo>-combo-eval-<n>.md` (name `<combo>` like `<skill-a>+<skill-b>`).
**Headline the combined effect and the interaction/classification jointly with
quality** (combo vs none *and* combo vs best single) — a token synergy with a
quality regression, or a combo the judge rates below a single skill, is a
regression, not a win. Write the verbatim records companion
`reports/<combo>-combo-eval-<n>-records.md` from the transcript as in single-skill
mode; with >2 arms, lead with baseline vs combo side by side and list the remaining
arms below. **Phase 7 then writes the combination summary**
(`reports/<combo>-combo-eval-<n>.summary.json` — `kind: "combination"`, one arm
per subset, plus the `interaction` block) and refreshes the dashboard, exactly as
in single-skill mode.

### Phase 6 (combination) — deepeval

Required, as always. Score **every arm** (base / each single / combo) in **one**
run: write a single cases file whose each case carries an **`arms` object**
(`{"base": "...", "<skill-a>": "...", …, "combo": "..."}`) instead of the
single-skill `with_skill_output`/`without_skill_output` pair — `deepeval_runner.py`
then emits a per-arm GEval table (with a Δ-vs-baseline row when an arm is named
`base`/`baseline`/`none`). Fold that table into the report's deepeval section. GEval
saturates, so report it as weak corroboration of the blind judge, not a
replacement.

---

## Integrity rules (do not violate)

- **Never fabricate tokens or scores.** Transcript or it didn't happen; judge
  subagent or it isn't a quality verdict.
- **Records are verbatim.** The records companion must contain the actual
  transcript text for each arm, copied unchanged — never a paraphrase or a
  reconstruction from memory. If you can't source it from the JSONL, mark it
  `unmeasured`.
- **Keep the judge blind.** No arm identity, markers, or token data in any judge
  prompt. Randomize positions.
- **Only the injected guidance differs between arms.** Same task, same input,
  same instructions otherwise.
- **Report negatives honestly.** "This skill costs more tokens / lowers quality"
  is a valid and valuable outcome.
- **Never headline the flat token sum.** Cost-weight (`--cost`) and report on the
  skill's billing axis (Phase 0.4); the flat total mis-weights cheap cached
  context against 5× output. See [`docs/token-accuracy.md`](../../docs/token-accuracy.md).
- **Joint verdict only.** A token result without its quality result (or vice
  versa) is not a verdict. Tokens are a win only if quality holds.
- **Warm + serial, amortize setup.** Eliminate the cache cold/warm artifact and
  charge one-time setup once, not per task (Phase 2).
- **Small N ⇒ directional.** Always state that results are indicative, not
  statistically conclusive, and suggest more tasks/repeats for confidence.
- **deepeval is required & its results are kept.** Run deepeval every evaluation
  (Phase 6) and keep its `*.deepeval.{json,md,cases.json}` outputs in `reports/`;
  the report must carry the deepeval section. If it cannot run, mark it
  `unavailable — <reason>` — never silently skip or delete its outputs.
- **The dashboard mirrors the report.** The Phase 7 summary JSON is a
  *projection* of the report's transcript-sourced numbers — never a second
  computation, never an estimate. `reports/index.json` and
  `reports/dashboard.html` are generated by `build_dashboard.py`, never
  hand-edited, and refreshed after every evaluation.
- **Combination = interaction, sourced.** When combining skills, the headline must
  include the **interaction** (synergy / redundancy / conflict) from
  `interaction_effects.py`, computed from transcript-attributed arms — never
  estimated by hand. Report a combo that loses to its best single skill as a
  regression. A `combined-vs-baseline` run reports **no** interaction term — say so
  plainly rather than implying one.

## Related files

Bundled inside this skill's own directory (they travel with it on install):

- `agent_tools/transcript_tokens.py` — transcript token attribution (no deps);
  `--full-text` extracts verbatim per-run prompt + output; `--cost` reports the
  cost-weighted view.
- `agent_tools/deepeval_runner.py` — deepeval GEval metrics (a **REQUIRED** phase;
  run with `--with deepeval --with anthropic`; outputs kept in `reports/`).
- `agent_tools/interaction_effects.py` — **(combination mode)** multi-skill
  interaction effects (combined / individual / marginal / interaction +
  classification) from the transcript; stdlib-only, no deps.
- `agent_tools/judge_planner.py` — plans the blind judging phase (`plan`: emits
  ready-to-dispatch blind prompts + a private Response→arm map; `resolve`:
  un-blinds, derives the best single skill, tallies combo-vs-none /
  combo-vs-best-single). Stdlib-only; removes the manual prompt-building and
  blinding bookkeeping in Phase 4.
- `agent_tools/combo_spec_builder.py` — **(combination mode)** from one config
  (task list + arm→marker map) reads the transcript once and writes all downstream
  inputs: the interaction `spec.json`, the `judge.spec.json`, the N-arm
  `deepeval.cases.json`, and the `deliverables.json` for the records file (warns +
  exits non-zero on a stubbed arm). Stdlib-only.
- `agent_tools/build_dashboard.py` — **(Phase 7)** validates every
  `reports/*.summary.json` against the versioned schema (in its docstring) and
  builds the **Skill Harness Dashboard**: `reports/index.json` +
  a self-contained `reports/dashboard.html`. Stdlib-only; `--check` is the
  validate-only CI mode.
- `templates/report-template.md` — single-skill report skeleton.
- `templates/combo-report-template.md` — **(combination mode)** multi-skill report
  skeleton (interaction decomposition + synergy verdict).
- `templates/records-template.md` — verbatim WITH/WITHOUT records companion.
- `templates/dashboard.html` — **(Phase 7)** the Skill Harness Dashboard
  template (single file, vanilla HTML/CSS/JS, zero dependencies);
  `build_dashboard.py` embeds the summaries into it.

Installed alongside the skill or kept in the source repo:

- `skill-eval-runner` / `skill-eval-judge` — the per-arm runner and the blind
  judge subagents (installed into `.claude/agents/`).
- `docs/token-accuracy.md` — the six rules for token-accurate evaluation
  (mechanism, cost-weighting, production conditions, joint verdict).
- `docs/combination-eval.md` — **(combination mode)** designs, the interaction
  formula, classification, and the honest scope (combination-when-applied, not
  co-triggering).
- `docs/dashboard.md` — the Skill Harness Dashboard: the three-layer output
  design, the summary schema + validation rules, the UI guide, and governance
  workflows (CI gates over `reports/index.json`).
- `docs/methodology.md`, `docs/token-measurement.md`, `docs/architecture.md`.
