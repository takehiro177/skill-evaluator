# Architecture

skill-evaluator is a **Claude Code-native** evaluation harness. There is no
server, no daemon, and no external orchestration — the entire pipeline runs as
one Claude Code session driving subagents, plus two tiny local Python scripts.

```
                         ┌─────────────────────────────────────────┐
   user: "evaluate       │   skill-evaluator  (Skill / orchestrator)│
   the my-docx skill"    │   - reads target SKILL.md                │
            ─────────────▶   - derives N tasks + rubrics            │
                         │   - owns the SECRET arm→label mapping     │
                         └───────┬───────────────────────┬──────────┘
                                 │ dispatch (Task)        │ dispatch (Task)
                                 ▼                        ▼
                   ┌─────────────────────────┐  ┌─────────────────────────┐
   per task ×2 →   │  skill-eval-runner (A)  │  │  skill-eval-runner (B)  │
                   │  WITH skill injected    │  │  WITHOUT skill          │
                   │  echoes RUN MARKER      │  │  echoes RUN MARKER      │
                   └───────────┬─────────────┘  └───────────┬─────────────┘
                               │ outputs                     │ outputs
                               ▼                             ▼
                         ┌───────────────────────────────────────────┐
   transcript    ◀───────│  session transcript (.jsonl, sidechains)  │
   parsing               └───────────────────────────────────────────┘
        │ skills/skill-evaluator/agent_tools/transcript_tokens.py  (stdlib, by RUN MARKER)
        ▼
   token deltas
                                 │ clean prompt (task + rubric + 2 anon responses)
                                 ▼
                   ┌─────────────────────────────────────┐
   per task →      │  skill-eval-judge  (BLIND)          │
                   │  no skill/arm/token info, returns    │
                   │  structured scores + winner          │
                   └───────────────────┬─────────────────┘
                                       ▼
                         ┌─────────────────────────────────────────┐
                         │  orchestrator un-blinds & writes:         │
                         │   • reports/<skill>-eval-<n>.md  (summary)│
                         │   • reports/<skill>-eval-<n>-records.md   │
                         │     (verbatim A/B outputs, from JSONL via │
                         │      transcript_tokens.py --full-text)    │
                         └───────────────────────────────────────────┘
                                       │ required (skip: --no-deepeval)
                                       ▼
                         skills/skill-evaluator/agent_tools/deepeval_runner.py  (GEval cross-check)
```

## Components

| Component | Type | Role |
|-----------|------|------|
| `skills/skill-evaluator/SKILL.md` | Claude Code skill | Orchestrator. The only thing the user invokes. Holds the secret arm mapping; keeps the judge blind. |
| `agents/skill-eval-runner.md` | Subagent | Solves one task as one arm. Injection-based WITH/WITHOUT. Echoes a RUN MARKER for token attribution. |
| `agents/skill-eval-judge.md` | Subagent | Blind comparative judge. Sees only task + rubric + two anonymized responses. |
| `skills/skill-evaluator/agent_tools/transcript_tokens.py` | Python (stdlib) | Reads the session transcript, groups sidechain runs, sums token usage, matches by RUN MARKER. `--full-text` also returns each run's verbatim prompt + output for the records companion. |
| `skills/skill-evaluator/agent_tools/deepeval_runner.py` | Python (deepeval) | Required GEval quality cross-check; degrades to an `unavailable` section without a key/deps. |

## Key design choices

- **Injection-based A/B.** The WITH arm gets the skill's body text injected into
  its prompt; the WITHOUT arm doesn't. This isolates the skill as the *only*
  variable and makes runs reproducible regardless of what's installed in the
  project. (An alternative — toggling an installed skill — is harder to control
  and leaks across subagents.)
- **Two independent randomizations.** Arm→"A/B" (Phase 2) and arm→"Response
  1/2" (Phase 4) are randomized separately, so neither the runner ordering nor
  the judge ordering encodes which arm is the skill.
- **Blindness is structural, not polite.** The judge is a *separate subagent
  context* that is only ever handed clean inputs. It cannot see the
  orchestrator's mapping, the markers, or the token numbers.
- **Tokens come from the transcript, never estimates.** The only trustworthy
  source of token counts is the recorded `usage` in the JSONL.
- **The records companion is the audit trail.** Alongside the summary report,
  the workflow writes the *verbatim* WITH/WITHOUT outputs for every task,
  extracted from the same JSONL. The report tells you what the numbers say; the
  records let a human verify them — read the actual responses and judge the
  with/without difference directly, rather than trusting the summary.
- **Everything degrades gracefully.** No Python → manual transcript fallback.
  deepeval deps/key missing → its section is marked `unavailable` and the rest of
  the report is still complete. Can't attribute an arm → report it as
  `unmeasured` rather than guessing.

See [`methodology.md`](methodology.md) for *why* this measures what it claims to,
and [`token-measurement.md`](token-measurement.md) for the transcript details.
