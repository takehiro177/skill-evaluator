# Contributing

Thanks for your interest in improving skill-evaluator! This is a small,
Claude Code-native tool, so the contribution surface is mostly Markdown
(the skill + subagent prompts) and two Python scripts.

## Project layout

See [`docs/architecture.md`](docs/architecture.md). In short:

- `skills/skill-evaluator/SKILL.md` — the orchestrator prompt/procedure.
- `agents/*.md` — the runner and blind-judge subagent prompts.
- `skills/skill-evaluator/agent_tools/*.py` — token attribution and multi-skill
  interaction effects (both stdlib) plus the deepeval metrics runner, bundled
  inside the skill.

## Ground rules for changes

The whole point of this tool is **trustworthy** evaluation. Please preserve
these invariants in any change:

1. **The judge stays blind.** No arm identity, run markers, token numbers, or
   the word "skill" may reach the judge subagent.
2. **Tokens come from the transcript.** Never estimate, never let the model
   invent token counts. Unattributable arms are reported as `unmeasured`.
3. **The skill is the only manipulated variable** between WITH and WITHOUT arms.
4. **The token half stays stdlib-only.** `transcript_tokens.py` and
   `interaction_effects.py` must run on a bare Python interpreter (no third-party
   imports; `interaction_effects.py` may import only `transcript_tokens.py`).
   deepeval is a required phase, but it must degrade to an `unavailable` report
   section — never a hard crash — when its deps or `ANTHROPIC_API_KEY` are missing.
5. **Negatives are reported honestly.** Don't bias the prompts toward "the skill
   helped".

## Pre-commit hooks

This repo ships a [`.pre-commit-config.yaml`](.pre-commit-config.yaml) covering
whitespace/EOF/line-ending hygiene, a private-key guard, and `ruff` lint +
format for the Python tools. Enable it once after cloning:

```bash
python -m pip install pre-commit
python -m pre_commit install            # run hooks automatically on commit
python -m pre_commit run --all-files    # optional: run across the whole repo now
```

## Developing the Python tools

```bash
cd skills/skill-evaluator/agent_tools
python -m pyflakes transcript_tokens.py interaction_effects.py deepeval_runner.py   # or your linter
python transcript_tokens.py --help
python interaction_effects.py --help
```

(`python` here is `python3` on macOS/Linux and `python`/`py` on Windows — the
scripts are stdlib-only and target Python ≥3.9.)

`transcript_tokens.py` and `interaction_effects.py` must not import anything
outside the standard library (`interaction_effects.py` may import only its sibling
`transcript_tokens.py`). If you add fields, read them defensively — Claude Code's
transcript schema
changes between versions.

## Submitting

- Keep prompt edits minimal and explain *why* in the PR (prompt wording is
  load-bearing here).
- If you change the transcript parser, include a sample anonymized JSONL line or
  a note on the Claude Code version you tested against.
- By contributing you agree your work is licensed under the repo's MIT license.
