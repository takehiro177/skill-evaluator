# agent_tools

Standalone helper scripts that Claude Code can execute during a skill
evaluation. This folder is self-contained: it has its own `pyproject.toml` and
does not depend on anything else in the repo.

There are two tools, with very different requirements:

| Script | Purpose | Dependencies |
|--------|---------|--------------|
| `transcript_tokens.py` | Attribute token usage to each subagent (A/B arm) run by parsing the Claude Code session transcript. **Core** — used on every evaluation. | **None** (Python stdlib only) |
| `deepeval_runner.py` | Library-backed GEval quality metrics via [`deepeval`](https://github.com/confident-ai/deepeval). **Required** — runs on every evaluation (skip only via `--no-deepeval` or a missing `ANTHROPIC_API_KEY`). | `deepeval`, `anthropic` |

The token half of the evaluation (deltas + blind LLM-as-judge) runs with **only**
the stdlib script; deepeval adds a complementary library-backed quality score and
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

## `deepeval_runner.py` (required)

The deepeval judge backend is **pinned to Anthropic/Claude** — this project only
uses Claude, so there is no OpenAI fallback. The only thing you need to set is
`ANTHROPIC_API_KEY` (export it, or put it in a `.env`; see
[`.env.example`](../../../.env.example)):

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

> deepeval sends your task inputs and the candidate outputs to the Anthropic
> API (the pinned judge backend). Don't run it on sensitive content without
> checking Anthropic's data policy.
