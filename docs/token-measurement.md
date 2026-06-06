# Token measurement

Token figures in a report are **read from the Claude Code session transcript**,
never estimated. This document explains where that data lives and how
`skills/skill-evaluator/agent_tools/transcript_tokens.py` attributes it to each A/B arm.

## Where transcripts live

Claude Code writes one JSONL file per session under:

```
~/.claude/projects/<encoded-cwd>/<session-id>.jsonl
```

- The config root honors `CLAUDE_CONFIG_DIR` if set (default `~/.claude`). On
  Windows this is `%USERPROFILE%\.claude`; the helper resolves it the same way via
  `pathlib`, so the commands below work unchanged.
- **Python command:** the `python …` examples below are `python3` on macOS/Linux
  and `python` (or `py`) on Windows — whichever launcher the host provides.
- `<encoded-cwd>` is the project's working directory with **every
  non-alphanumeric character replaced by a single `-`** (not collapsed). E.g.
  `C:\Users\me\proj` → `C--Users-me-proj`, and
  `/home/me/proj` → `-home-me-proj`.
- The active session is normally the most-recently-modified `.jsonl` in that
  folder. The helper auto-detects it; override with `--session`.

## What a line looks like

Each line is one JSON object (an "entry"). The fields we rely on:

| Field | Meaning |
|-------|---------|
| `uuid` | Unique id for this entry. |
| `parentUuid` | The entry this one replied to (forms the conversation tree). |
| `isSidechain` | `true` for subagent ("Task") turns — this is how we find arm runs. |
| `type` / `message.role` | `user` or `assistant`. |
| `message.usage` | Token counts on assistant turns (see below). |
| `message.content` | Text/blocks; for the root user turn this is the dispatch prompt (contains the RUN MARKER). |
| `timestamp` | ISO time, used for ordering. |

The `usage` object carries:

```
input_tokens                  # fresh prompt tokens
cache_creation_input_tokens   # tokens written into the prompt cache
cache_read_input_tokens       # tokens served from the prompt cache
output_tokens                 # generated tokens
```

We define, per run:

```
context_tokens = input_tokens + cache_creation_input_tokens + cache_read_input_tokens
total_tokens   = context_tokens + output_tokens
```

## Attributing tokens to an arm

1. **Keep only sidechain entries** (`isSidechain == true`) — these are subagent
   turns. Main-conversation turns (the orchestrator itself) are excluded.
2. **Group entries into runs.** Each subagent run is a tree rooted at its
   dispatch prompt. For every sidechain entry we walk `parentUuid` upward until
   the parent is no longer a sidechain (or is null) — that root identifies the
   run. Grouping by root correctly separates runs even if two subagents were
   dispatched in the same turn and their entries interleave.
3. **Sum usage** across the assistant entries in each group.
4. **Identify the arm.** The run's root user text is the dispatch prompt, which
   contains the unique `SKILLEVAL-<task>-<arm>-<rand>` RUN MARKER. Matching the
   marker maps a run's token totals to the correct (task, arm).

```bash
# All runs, machine-readable:
python skills/skill-evaluator/agent_tools/transcript_tokens.py --json

# Just one arm:
python skills/skill-evaluator/agent_tools/transcript_tokens.py --grep "SKILLEVAL-t1-A-7f3" --json
```

### Extracting verbatim run text (`--full-text`)

By default the helper reports only token totals plus a truncated copy of each
run's dispatch prompt. Add `--full-text` to also include, per run:

| Field | Meaning |
|-------|---------|
| `first_user_text` | The **untruncated** dispatch prompt (for the WITH arm, this includes the injected `<<<SKILL GUIDANCE …>>>` block). |
| `assistant_text` | The full concatenation of the run's assistant **text** output, including the runner's `=== FINAL OUTPUT ===` deliverable. Internal thinking blocks are not part of the transcript text and are excluded. |

```bash
# One arm, with its full prompt and full output:
python skills/skill-evaluator/agent_tools/transcript_tokens.py --grep "SKILLEVAL-t1-A-7f3" --json --full-text
```

This is the data source for the **records companion file** the workflow writes
next to the report (`reports/<skill>-eval-<n>-records.md`) — the actual WITH /
WITHOUT outputs, verbatim from the transcript, so a human can review the
difference by hand. The token numbers and the records both come from the same
JSONL, so they always agree.

## Manual fallback (no Python)

If Python isn't available, the orchestrator can attribute tokens by hand:

1. Locate the transcript folder as above.
2. Open the active `.jsonl`. Find the lines with `"isSidechain":true`.
3. For the WITH arm, find the sidechain whose first user message contains that
   arm's RUN MARKER, then walk its `parentUuid` children and sum each
   assistant turn's `message.usage`. Repeat for the WITHOUT arm.

This is exactly what the script automates; use it only as a backstop. If an
arm's tokens truly can't be recovered, report it as `unmeasured` rather than
guessing.

## Caveats

- **Cache reads are cheaper than fresh input** in dollar terms but still count
  as tokens processed. The report keeps context vs output split so you can
  weight them as you like.
- **Prompt caching can make absolute numbers depend on what ran just before.**
  For the cleanest comparison, run both arms of a task close together in the
  same session, which the workflow does.
- **Schema drift:** the helper reads fields defensively and skips unparseable
  lines, but Claude Code's transcript format can change between versions. If
  numbers look wrong, inspect a few lines of the `.jsonl` directly.
