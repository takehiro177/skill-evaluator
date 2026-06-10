# skill-evaluator

> **Cost-weighted A/B *performance* testing for Claude Code skills — one skill, or
> several *combined*.** It measures real token cost and blind-judged output quality
> from live runs; it is **not** a static linter or security scanner.

**Do your Claude Code skills actually earn their context — alone, and stacked together?**

Point skill-evaluator at **two or more skills** and it measures the thing single-skill
testing never captures: their **interaction** when combined — **synergy**,
**redundancy**, or outright **conflict**. Point it at **one** skill and it runs the same
rigorous check on that skill alone. Either way you get two numbers you can act on:
**cost-weighted token economics** (priced on the axis the skill actually bills on, read
from the real session transcript — never estimated) and **output quality** (scored by a
**blind LLM-as-judge**) — all from a blind, injection-based A/B test, entirely inside
Claude Code chat.

No SaaS, no API server, no harness to run — just a Claude Code skill plus two subagents
and three small local scripts. Drop it into **any** project, or install it as a plugin.

> **New — the Skill Harness Dashboard.** Every evaluation now also writes a
> versioned `reports/<name>-eval-<n>.summary.json` (the machine-readable **data
> layer**) and refreshes `reports/dashboard.html` — a **single static page, zero
> dependencies**, that shows your whole `reports/` directory as compact report
> cards, and **every card clicks through to a full detail page**: verdict +
> recommendation, per-arm cost bars, interaction decomposition, deepeval
> results, and the **verbatim WITH/WITHOUT outputs side by side**. Open it by
> double-clicking the file — it is your skill portfolio's governance view.
> See [Skill Harness Dashboard](#skill-harness-dashboard-governance-view).

```
You:    Evaluate skills ./caveman and ./code-map combined
Claude: → 2×2 factorial arms: none / caveman / code-map / both
        → measures each arm's cost-weighted tokens from the transcript
        → interaction = combined effect − (caveman + code-map alone)
        → blind judge: combo vs none, and combo vs the best single skill
        → writes reports/caveman+code-map-combo-eval-1.md
        → writes the .summary.json + refreshes reports/dashboard.html

        Verdict: redundant — stacked, they save no more than code-map alone.

You:    Evaluate the skill at ./.claude/skills/my-skill   # single-skill mode
Claude: → runs the task WITH vs WITHOUT the skill, scores tokens + quality
        Verdict: saved ~1.8k tokens/task on average; quality WITH won 2/3.
```

---

## Why

A `SKILL.md` *claims* to help. But does it? It might make no difference, or even
hurt — extra context, distracting instructions, over-scoping. The only honest
answer is a controlled comparison where the skill is the **single variable**.
This tool runs that comparison and reports two things you can act on:

- **Tokens saved** — the measured token-cost delta between solving a task with
  the skill's guidance vs without it. (Negative is a valid, reported result.)
- **Output quality** — scored 0–10 by a blind judge that never learns which
  response used the skill.

## How it works (30 seconds)

```
skill-evaluator (orchestrator skill)
  ├─ reads target SKILL.md → derives N tasks + skill-agnostic rubrics
  ├─ per task, dispatches skill-eval-runner ×2:
  │     WITH  = skill body injected into the prompt
  │     WITHOUT = identical prompt, no skill
  │     (each echoes a unique RUN MARKER)
  ├─ transcript_tokens.py → token totals per arm (matched by RUN MARKER)
  ├─ per task, dispatches skill-eval-judge (BLIND):
  │     sees only task + rubric + 2 anonymized responses → scores + winner
  ├─ un-blinds privately, writes reports/<skill>-eval-<n>.md
  └─ writes reports/<skill>-eval-<n>.summary.json (data layer)
        → build_dashboard.py refreshes reports/dashboard.html + index.json
```

- **Injection-based A/B** makes the skill the only manipulated variable and
  works even for skills that aren't installed anywhere yet.
- **The judge is structurally blind** — a separate subagent context handed only
  clean inputs. No arm labels, no markers, no token numbers, never the word
  "skill".
- **Tokens are read from the transcript, never estimated.**

Full details: [`docs/architecture.md`](docs/architecture.md) ·
[`docs/methodology.md`](docs/methodology.md) ·
[`docs/token-measurement.md`](docs/token-measurement.md) ·
[`docs/dashboard.md`](docs/dashboard.md).

## Requirements

- **Claude Code** (this tool runs as a skill + subagents inside it).
- **Python 3.9+** on PATH for token attribution and the dashboard build
  (standard library only — nothing to install). It's invoked as `python3` on
  macOS/Linux and `python` (or `py`) on Windows — the workflow uses whichever
  exists.
- [`deepeval`](https://github.com/confident-ai/deepeval) plus an
  `ANTHROPIC_API_KEY` for the required deepeval metrics phase. The deps are
  pulled in on demand via [`uv`](https://docs.astral.sh/uv/) (nothing installed
  globally); pass `--no-deepeval` to skip the phase if you have no key.

## Install

Clone the repo, then install the skill + subagents into a project or your
global config. The skill is self-contained — its `agent_tools/` scripts and
`templates/` are bundled inside `skills/skill-evaluator/`, so they install along
with it and resolve relative to the installed skill, from any project:

```bash
git clone https://github.com/takehiro177/skill-evaluator
cd skill-evaluator

# into the current project's .claude/ :
./install.sh                 # macOS/Linux
./install.ps1                # Windows PowerShell

# into another project:
./install.sh /path/to/app
./install.ps1 -Target C:\src\app

# or globally, for every project:
./install.sh --global
./install.ps1 -Global
```

This copies `skills/skill-evaluator/` (with its bundled `agent_tools/` and
`templates/`) and `agents/skill-eval-*.md` into the target `.claude/`. (No build
step; the skill is Markdown plus a few stdlib Python scripts.)

> On Windows, if PowerShell refuses to run the script ("running scripts is
> disabled on this system"), invoke it without changing your machine's policy:
> `powershell -ExecutionPolicy Bypass -File .\install.ps1`.

> Prefer not to run a script? Just copy `skills/skill-evaluator` into
> `.claude/skills/` and the two `agents/*.md` files into `.claude/agents/`.

### …or install as a Claude Code plugin

This repo ships a `.claude-plugin/` manifest, so it doubles as an installable
plugin **and** its own marketplace — versioned updates, one command, no copying:

```
/plugin marketplace add takehiro177/skill-evaluator
/plugin install skill-evaluator@takehiro177
```

The plugin bundles the `skill-evaluator` skill (with its `agent_tools/` +
`templates/`) and both `skill-eval-*` subagents. To try it locally before
installing, run `claude --plugin-dir .` from the repo root (and
`claude plugin validate . --strict` to check the manifest).

## Usage

Open Claude Code in a project where the skill is installed and ask in plain
language:

```
Evaluate the skill at ./.claude/skills/my-skill
Evaluate my-skill with 5 tasks
Evaluate ~/.claude/skills/my-skill and ground tasks in my real history
Evaluate ./.claude/skills/my-skill and also run deepeval
```

Options the orchestrator understands:

| Phrase / flag | Effect |
|---------------|--------|
| `with N tasks` / `--tasks N` | Number of eval tasks (default 3). |
| `from history` / `--from-history` | Also mine your past sessions for real tasks. |
| `skip deepeval` / `--no-deepeval` | deepeval runs by default (required); use this to skip it. |
| `write the report to PATH` / `--report PATH` | Custom report path. |
| `--leave-one-out` | **(combination)** add an arm per skill dropped, for each skill's marginal contribution. |
| `--full-factorial` | **(combination)** run every subset (2ᴺ arms) for the complete interaction map. |

### Evaluate skills *combined* (multi-skill interaction)

Skills rarely run alone. Point the evaluator at **two or more** skills and it
measures their **interaction** — whether stacking them helps beyond the sum of the
parts (**synergy**), merely duplicates (**redundancy**), or actively fights
(**conflict**) — the impact that single-skill evaluation never captures:

```
Evaluate skills ./.claude/skills/caveman and ./.claude/skills/code-map combined
Do my "terse" and "exhaustive" skills work together or conflict?
Evaluate skills A, B and C combined --leave-one-out
Measure the interaction of skill-x and skill-y with 5 tasks
```

It runs the same blind, injection-based A/B, but an arm is now defined by the
*subset* of skills injected. The default is cheap — a full 2×2 factorial for two
skills (the exact interaction term), or combined-vs-baseline for three or more
(the bundle's overall effect); add `--leave-one-out` / `--full-factorial` to
attribute the effect per skill. You get a combination report with an **interaction
decomposition** (combined / individual / marginal / interaction, cost-weighted) and
**two judge calls** — combo vs none, and combo vs the *best single skill*. Details:
[`docs/combination-eval.md`](docs/combination-eval.md).

### Try it on the bundled example

```
Evaluate the skill at ./examples/caveman
```

See [`examples/README.md`](examples/README.md).

> **Note — the bundled `examples/` skills are third-party, included only as
> samples.** `caveman` is the work of Julius Brussee
> (<https://github.com/JuliusBrussee/caveman>, MIT); `karpathy-guidelines` is the
> work of `forrestchang` (<https://github.com/forrestchang/andrej-karpathy-skills>,
> MIT). The copies under [`examples/`](examples/) are snapshots for demonstration —
> refer to each upstream repo for the canonical version and any updates.

## What you get

Per evaluation, in `reports/`:

**1. The report** — `<skill>-eval-<n>.md` (see
[`report-template.md`](skills/skill-evaluator/templates/report-template.md)) with:

- a headline verdict (helps / hurts / mixed, on tokens and on quality);
- a per-task table — tokens WITH / WITHOUT / saved, judge winner, score delta;
- aggregates and a methodology + caveats section;
- the full derived tasks & rubrics for reproducibility.

**2. The records companion** — `<skill>-eval-<n>-records.md` (see
[`records-template.md`](skills/skill-evaluator/templates/records-template.md)): the
**verbatim** WITH-skill and WITHOUT-skill outputs for every task, pulled
straight from the session transcript JSONL (not summarized), laid out
back-to-back. This is the audit trail — read it to **eyeball the with/without
difference yourself** and confirm the report's numbers and the judge's calls
against the actual responses.

**3. The deepeval metrics** — `<skill>-eval-<n>.deepeval.{md,json}` plus the
`.cases.json` input: a complementary, library-backed GEval (0–1) quality score
per arm, folded into the report's required deepeval section and kept alongside it.

**4. The summary JSON (data layer)** — `<skill>-eval-<n>.summary.json`: the
report's headline numbers as one small, **schema-validated** JSON
(`schema_version: 1`) — verdict, cost-weighted deltas, per-arm tokens,
quality tallies, interaction (combination), caveats, artifact links. It is a
*projection* of the report (same transcript-sourced figures, never recomputed)
and the **only** thing the dashboard ingests. Schema: the docstring of
[`build_dashboard.py`](skills/skill-evaluator/agent_tools/build_dashboard.py)
and [`docs/dashboard.md`](docs/dashboard.md).

**5. The Skill Harness Dashboard (refreshed)** — `reports/dashboard.html` +
`reports/index.json`: the workflow's Phase 7 validates every summary and
regenerates the one-page governance view over **all** runs, automatically.

## Skill Harness Dashboard (governance view)

Open [`reports/dashboard.html`](reports/dashboard.html) in a browser
(double-click works — it is a single self-contained file: no server, no build
step, no CDN, vanilla HTML/CSS/JS). The tracked copy is a live demo built from
the two real example runs in this repo.

One screen shows your whole skill harness as **report cards** — this is where
you analyze results across runs and make the call per skill: **adopt, reject,
or re-run**:

- a **KPI strip** — evaluations on file, distinct skills covered, the verdict
  mix as a proportional color bar (✅ ➖ ⚠️ ❌ counts), the median cost-weighted
  Δ, and a **quality-flag count** (runs where the baseline beat the skill on
  the decisive comparison);
- compact, **clickable** cards — verdict badge, cost-weighted Δ%, the
  primary-axis Δ% on the skill's billing mechanism (or "no token claim"), the
  decisive blind-judge W·T·L, and the ⚑ flag; the whole card opens its detail
  page;
- a **detail page per run** (hash-routed — back button and deep links work,
  still one static file): the report's verdict + recommendation, per-arm cost
  bars with the setup/breakeven note, the **interaction decomposition** for
  combinations, **deepeval results** (per-arm GEval means + Δ, raw JSON in a
  collapsible), and per task the judge verdict, prompt/rubric, and the
  **verbatim WITH vs WITHOUT outputs side by side** (embedded at build time
  from the run's `deepeval.cases.json` — never parsed from Markdown), plus all
  caveats and artifact links;
- **search, filters** (single vs combination; verdict buckets) and **sorting**
  (newest, biggest cost savings, best quality delta, name), a light/dark theme,
  and a print stylesheet for review meetings.

Regenerate it any time (stdlib-only, offline):

```bash
python skills/skill-evaluator/agent_tools/build_dashboard.py            # build
python skills/skill-evaluator/agent_tools/build_dashboard.py --check   # validate only (CI)
```

The skill itself refreshes the dashboard at the end of every evaluation
(Phase 7), so it is always current.

### How ingestion stays reliable (no Markdown parsing)

The dashboard never parses Markdown — parsing prose is brittle and silently
wrong. Instead every evaluation emits **three layers from the same
transcript-sourced numbers**:

1. **Human / audit layer** — the Markdown report, records, and deepeval files.
   Written for people, rendered by GitHub, diffed in review. Never ingested.
2. **Data layer** — `<name>-eval-<n>.summary.json`, written by the workflow at
   evaluation time as a *projection of the report*: same figures, versioned
   schema, validated by `build_dashboard.py --check` (CI runs this on every
   push). Anything unmeasured is omitted or `"available": false` — never
   estimated. This is the single ingestion path.
3. **Presentation layer** — `dashboard.html`, generated from the data layer
   with the JSON **embedded** in the file, so it works from `file://` with zero
   dependencies. `index.json` exposes the same data for your own tooling — CI
   gates ("fail the build if any run is `conflicting`"), trend tracking,
   scripts. See [`docs/dashboard.md`](docs/dashboard.md) for the schema, the
   validation rules, and a copy-paste CI gate.

**Backfilling old runs:** reports written before the dashboard existed have no
summary. Ask the skill in chat — *"Backfill
`reports/<name>-eval-<n>.summary.json` from its report and artifacts"* — and it
projects the existing numbers into the schema (never re-measuring), then
rebuilds the dashboard.

## deepeval (required)

Every evaluation also runs **deepeval** for a complementary, library-backed GEval
quality score. The evaluator writes the arm outputs to a cases file and runs the
standalone tool in [`skills/skill-evaluator/agent_tools/`](skills/skill-evaluator/agent_tools/README.md),
which has its own `pyproject.toml`. The judge backend is pinned to
Anthropic/Claude, so the only thing to configure is `ANTHROPIC_API_KEY`. Note that
`deepeval >=4` has **no** `[anthropic]` extra — the `anthropic` package is
installed explicitly (`--with deepeval --with anthropic`); see
[`agent_tools/README.md`](skills/skill-evaluator/agent_tools/README.md). To skip it
(e.g. no API key), pass `--no-deepeval`; the report then marks the section
`unavailable`.

## Repository layout

```
skill-evaluator/
├── skills/skill-evaluator/           # the orchestrator skill (self-contained)
│   ├── SKILL.md                      #   the procedure you invoke (Phases 0–7)
│   ├── agent_tools/                  #   bundled helper scripts, installed with it
│   │   ├── transcript_tokens.py      #     token attribution (stdlib only)
│   │   ├── interaction_effects.py    #     multi-skill interaction effects (stdlib only)
│   │   ├── combo_spec_builder.py     #     combination spec builder (stdlib only)
│   │   ├── judge_planner.py          #     blind-judge planning/resolution (stdlib only)
│   │   ├── build_dashboard.py        #     summary validation + dashboard build (stdlib only)
│   │   ├── deepeval_runner.py        #     deepeval metrics (required)
│   │   ├── pyproject.toml
│   │   └── README.md
│   └── templates/
│       ├── report-template.md        #   the single-skill summary report
│       ├── combo-report-template.md  #   the multi-skill combination report
│       ├── records-template.md       #   verbatim WITH/WITHOUT records companion
│       └── dashboard.html            #   Skill Harness Dashboard template (zero deps)
├── agents/
│   ├── skill-eval-runner.md          # runs one task as one A/B arm
│   └── skill-eval-judge.md           # blind comparative judge
├── docs/                             # architecture, methodology, tokens, combination-eval, dashboard
├── examples/caveman/                 # an example skill to evaluate end-to-end
├── reports/                          # generated reports land here (gitignored; the worked
│                                     #   examples + their .summary.json + the demo
│                                     #   dashboard.html / index.json are tracked)
├── install.sh / install.ps1
├── LICENSE                           # MIT
└── README.md
```

## Limitations

This is an **in-chat, small-N** harness. Results are **directional, not
statistically conclusive** — raise `--tasks` or repeat runs for high-stakes
calls. It measures *given the skill is applied, does it help?* — not whether the
skill **triggers** correctly in the wild (for trigger accuracy, see Anthropic's
`skill-creator` eval tooling). It measures tokens and quality, not latency.
**Combination mode** is bound by the same limits, plus two of its own: it measures
the skills *applied together*, **not** whether they would actually **co-trigger**
on the same real prompt; and the interaction is a *difference of differences*, so
it is the noisiest figure in a report — repeat it before acting on a borderline
call. See
[`docs/methodology.md`](docs/methodology.md#threats-to-validity-and-what-we-do-about-them)
and [`docs/combination-eval.md`](docs/combination-eval.md) for the full list and
mitigations.

## License

[MIT](LICENSE). Contributions welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md).

### Third-party software

**Bundled as examples.** Two third-party skills are vendored under
[`examples/`](examples/), each solely as a sample to evaluate, each MIT-licensed
with its license kept alongside it:

- [`examples/caveman/`](examples/caveman/) — the **caveman** skill by Julius
  Brussee ([`LICENSE`](examples/caveman/LICENSE); canonical source
  <https://github.com/JuliusBrussee/caveman>).
- [`examples/karpathy-guidelines/`](examples/karpathy-guidelines/) — the
  **karpathy-guidelines** skill by `forrestchang` (the *andrej-karpathy-skills*
  project; MIT per the skill's frontmatter,
  [`LICENSE`](examples/karpathy-guidelines/LICENSE); canonical source
  <https://github.com/forrestchang/andrej-karpathy-skills>).

No other third-party source is vendored in this repository.

**Integrated, not bundled.** The one external library the tooling calls is
installed separately by the user, never vendored here:

- [**deepeval**](https://github.com/confident-ai/deepeval) — Apache License 2.0,
  © Confident AI Inc. Used only via its public API in
  [`agent_tools/deepeval_runner.py`](skills/skill-evaluator/agent_tools/deepeval_runner.py).
  "DeepEval" is a name of Confident AI Inc., referenced here solely to identify
  the upstream project.
