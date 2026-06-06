# skill-evaluator

**Evaluate Claude Code skills with blind A/B testing — entirely inside Claude
Code chat.**

Point it at a skill, and it measures whether that skill actually helps: it reads
what the skill *claims* to do, derives representative tasks, solves each one
**with** and **without** the skill via subagents, attributes real token costs
from the session transcript, scores output quality with a **blind LLM-as-judge**
subagent, and writes a Markdown report.

No SaaS, no API server, no harness to run — just a Claude Code skill plus two
subagents and two tiny local scripts. Drop it into **any** project.

**New in 0.2 —** point it at *two or more* skills and it measures their
**interaction** when combined: synergy, redundancy, or conflict, the impact that
single-skill testing never captures. See
[Evaluate skills combined](#evaluate-skills-combined-multi-skill-interaction).

```
You:    Evaluate the skill at ./.claude/skills/my-skill
Claude: → reads my-skill/SKILL.md, derives 3 tasks
        → runs each task WITH vs WITHOUT the skill (subagents)
        → measures token deltas from the transcript
        → scores quality with a blind judge subagent
        → writes reports/my-skill-eval-1.md
                 + reports/my-skill-eval-1-records.md  (verbatim A/B outputs)

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
  └─ un-blinds privately, writes reports/<skill>-eval-<n>.md
```

- **Injection-based A/B** makes the skill the only manipulated variable and
  works even for skills that aren't installed anywhere yet.
- **The judge is structurally blind** — a separate subagent context handed only
  clean inputs. No arm labels, no markers, no token numbers, never the word
  "skill".
- **Tokens are read from the transcript, never estimated.**

Full details: [`docs/architecture.md`](docs/architecture.md) ·
[`docs/methodology.md`](docs/methodology.md) ·
[`docs/token-measurement.md`](docs/token-measurement.md).

## Requirements

- **Claude Code** (this tool runs as a skill + subagents inside it).
- **Python 3.9+** on PATH for token attribution (standard library only — nothing
  to install). It's invoked as `python3` on macOS/Linux and `python` (or `py`) on
  Windows — the workflow uses whichever exists.
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
step; the skill is Markdown plus two stdlib Python scripts.)

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

> **Note — `caveman` is a third-party skill, bundled here only as an example.**
> It is the work of Julius Brussee; the official, maintained source is
> <https://github.com/JuliusBrussee/caveman> (MIT). The copy under
> [`examples/caveman/`](examples/caveman/) is a snapshot for demonstration — refer
> to the upstream repo for the canonical version and any updates.

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
│   ├── SKILL.md                      #   the procedure you invoke
│   ├── agent_tools/                  #   bundled helper scripts, installed with it
│   │   ├── transcript_tokens.py      #     token attribution (stdlib only)
│   │   ├── interaction_effects.py    #     multi-skill interaction effects (stdlib only)
│   │   ├── deepeval_runner.py        #     deepeval metrics (required)
│   │   ├── pyproject.toml
│   │   └── README.md
│   └── templates/
│       ├── report-template.md        #   the single-skill summary report
│       ├── combo-report-template.md  #   the multi-skill combination report
│       └── records-template.md       #   verbatim WITH/WITHOUT records companion
├── agents/
│   ├── skill-eval-runner.md          # runs one task as one A/B arm
│   └── skill-eval-judge.md           # blind comparative judge
├── docs/                             # architecture, methodology, tokens, combination-eval
├── examples/caveman/                 # an example skill to evaluate end-to-end
├── reports/                          # generated reports land here (gitignored; one sample is tracked)
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

**Bundled as an example.** [`examples/caveman/`](examples/caveman/) is a snapshot
of the third-party **caveman** skill by Julius Brussee, included solely as a
sample to evaluate. It is MIT-licensed and its license is kept alongside it at
[`examples/caveman/LICENSE`](examples/caveman/LICENSE); the canonical, maintained
source is <https://github.com/JuliusBrussee/caveman>. No other third-party source
is vendored in this repository.

**Integrated, not bundled.** The one external library the tooling calls is
installed separately by the user, never vendored here:

- [**deepeval**](https://github.com/confident-ai/deepeval) — Apache License 2.0,
  © Confident AI Inc. Used only via its public API in
  [`agent_tools/deepeval_runner.py`](skills/skill-evaluator/agent_tools/deepeval_runner.py).
  "DeepEval" is a name of Confident AI Inc., referenced here solely to identify
  the upstream project.
