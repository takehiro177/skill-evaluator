# Architecture

skill-evaluator is a **Claude Code-native** evaluation harness. There is no
server, no daemon, and no external orchestration — the entire pipeline runs as
one Claude Code session driving subagents, plus a few tiny local Python scripts.

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
                         │   • reports/<skill>-eval-<n>.summary.json │
                         │     (versioned data layer, Phase 7)       │
                         └───────────────┬───────────────────────────┘
                                         │ required (skip: --no-deepeval)
                                         ▼
                         skills/skill-evaluator/agent_tools/deepeval_runner.py  (GEval cross-check)
                                         │
                                         ▼ Phase 7 (stdlib, offline)
                         skills/skill-evaluator/agent_tools/build_dashboard.py
                           validates reports/*.summary.json and writes:
                            • reports/index.json      (machine-readable, for CI/tooling)
                            • reports/dashboard.html  (Skill Harness Dashboard,
                              self-contained — data embedded, opens from file://)
```

## Components

| Component | Type | Role |
|-----------|------|------|
| `skills/skill-evaluator/SKILL.md` | Claude Code skill | Orchestrator. The only thing the user invokes. Holds the secret arm mapping; keeps the judge blind. |
| `agents/skill-eval-runner.md` | Subagent | Solves one task as one arm. Injection-based WITH/WITHOUT. Echoes a RUN MARKER for token attribution. |
| `agents/skill-eval-judge.md` | Subagent | Blind comparative judge. Sees only task + rubric + two anonymized responses. |
| `skills/skill-evaluator/agent_tools/transcript_tokens.py` | Python (stdlib) | Reads the session transcript, groups sidechain runs, sums token usage, matches by RUN MARKER. `--full-text` also returns each run's verbatim prompt + output for the records companion. |
| `skills/skill-evaluator/agent_tools/interaction_effects.py` | Python (stdlib) | **Combination mode.** Combines per-arm token totals (resolved from the transcript by marker) into the interaction between 2+ skills: combined / individual / marginal / pairwise + total interaction, with a synergy/redundancy/conflict classification. |
| `skills/skill-evaluator/agent_tools/build_dashboard.py` | Python (stdlib) | **Phase 7.** Validates every `reports/*.summary.json` against the versioned schema (in its docstring) and builds the Skill Harness Dashboard: `reports/index.json` + a self-contained `reports/dashboard.html` with the data embedded (works from `file://`, zero deps). `--check` is the validate-only CI mode. |
| `skills/skill-evaluator/templates/dashboard.html` | HTML template | The dashboard UI — one file, vanilla HTML/CSS/JS, no CDN. `build_dashboard.py` injects the summaries into its data token. |
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
- **Three output layers, one source of truth.** Every run emits (1) the
  **Markdown** report/records/deepeval files for humans and audit — never
  parsed by anything; (2) the **summary JSON** data layer — a versioned,
  validated *projection* of the report (same transcript-sourced numbers, never
  recomputed); (3) the **generated HTML** Skill Harness Dashboard + `index.json`
  for governance and tooling, rebuilt from the data layer by a stdlib script
  with zero runtime dependencies. See [`dashboard.md`](dashboard.md).
- **Everything degrades gracefully.** No Python → manual transcript fallback.
  deepeval deps/key missing → its section is marked `unavailable` and the rest of
  the report is still complete. Can't attribute an arm → report it as
  `unmeasured` rather than guessing — and the summary/dashboard show
  `unmeasured` too, never a guess.

### Combination mode (2+ skills)

When given two or more skills, the same pipeline runs over **skill subsets**: an
arm injects a defined subset (baseline injects none, combo injects all), tokens are
attributed per arm exactly as above, and `interaction_effects.py` then combines the
arms into the **interaction** term — the synergy/redundancy/conflict that
single-skill evaluation can't see. The blind judge makes two calls (combo vs none,
combo vs the best single skill), and the orchestrator writes the
[combination report](../skills/skill-evaluator/templates/combo-report-template.md)
instead of the single-skill one — followed by the combination summary JSON and a
dashboard refresh (Phase 7), exactly as in single-skill mode. The
injection-based, transcript-sourced, blind-judge invariants are unchanged. See
[`combination-eval.md`](combination-eval.md).

See [`methodology.md`](methodology.md) for *why* this measures what it claims to,
[`token-measurement.md`](token-measurement.md) for the transcript details, and
[`dashboard.md`](dashboard.md) for the dashboard's schema and governance
workflows.
