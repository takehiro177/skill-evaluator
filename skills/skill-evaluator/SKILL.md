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
---

# Skill Evaluator

You are running the **skill-evaluator** workflow: a self-contained, in-chat
A/B harness that measures whether a given Claude Code skill actually helps,
along two axes:

1. **Tokens saved** — the token-cost delta between solving a task WITH the
   skill's guidance vs WITHOUT it (measured from the real session transcript).
2. **Output quality** — scored by a **blind LLM-as-judge** subagent that never
   learns which response came from which arm.

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

Optional knobs (ask only if ambiguous; otherwise use defaults):

| Knob              | Default | Meaning                                             |
|-------------------|---------|-----------------------------------------------------|
| `--tasks N`       | `3`     | Number of evaluation tasks to derive.               |
| `--from-history`  | off     | Also mine the user's past sessions for real tasks.  |
| `--no-deepeval`   | off     | Skip the deepeval metrics. deepeval runs by **default** — it is a REQUIRED phase (Phase 6). Only skip if no `ANTHROPIC_API_KEY` / deps are available, and then say so explicitly in the report. |
| `--report PATH`   | auto    | Where to write the report (default `reports/`).     |

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

## Related files

Bundled inside this skill's own directory (they travel with it on install):

- `agent_tools/transcript_tokens.py` — transcript token attribution (no deps);
  `--full-text` extracts verbatim per-run prompt + output; `--cost` reports the
  cost-weighted view.
- `agent_tools/deepeval_runner.py` — deepeval GEval metrics (a **REQUIRED** phase;
  run with `--with deepeval --with anthropic`; outputs kept in `reports/`).
- `templates/report-template.md` — report skeleton.
- `templates/records-template.md` — verbatim WITH/WITHOUT records companion.

Installed alongside the skill or kept in the source repo:

- `skill-eval-runner` / `skill-eval-judge` — the per-arm runner and the blind
  judge subagents (installed into `.claude/agents/`).
- `docs/token-accuracy.md` — the six rules for token-accurate evaluation
  (mechanism, cost-weighting, production conditions, joint verdict).
- `docs/methodology.md`, `docs/token-measurement.md`, `docs/architecture.md`.
