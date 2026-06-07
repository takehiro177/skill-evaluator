# Examples

## `caveman/` — a skill to evaluate

[`caveman/SKILL.md`](caveman/SKILL.md) is a self-contained example skill you can
point the evaluator at to see the whole pipeline end to end without touching your
own skills. `caveman` is an **`output`-mechanism** skill: it compresses the
*response* into terse "smart caveman" prose (dropping articles, filler, and
hedging while preserving technical terms, code, and error strings), so it bills
on **output tokens (5×)** — the axis the evaluator headlines for it.

> **Attribution.** `caveman` is third-party software by Julius Brussee, bundled
> here only as a sample to evaluate. It is MIT-licensed (see
> [`caveman/LICENSE`](caveman/LICENSE)); the canonical source is
> <https://github.com/JuliusBrussee/caveman>.

From a Claude Code chat opened in this repo:

```
Evaluate the skill at ./examples/caveman
```

The `skill-evaluator` skill will:

1. read `caveman/SKILL.md`, summarize what it claims, and classify its token
   mechanism as `output`;
2. derive ~3 representative technical-Q&A tasks with skill-agnostic rubrics;
3. prime the cache, then run each task WITH and WITHOUT the guidance via the
   runner subagent (single-injection, multi-task, so the one-time guidance load
   is amortized as in production);
4. attribute tokens per arm from the transcript — headlining the **output-token**
   delta and the **cost-weighted** delta, plus breakeven vs the one-time load;
5. score quality with the blind judge subagent;
6. run **deepeval** (a required step) for a complementary GEval quality score;
7. write a report to `reports/caveman-eval-<n>.md`, a verbatim records companion
   `reports/caveman-eval-<n>-records.md` (the actual WITH/WITHOUT outputs for manual
   review), and the deepeval outputs `reports/caveman-eval-<n>.deepeval.{md,json,cases.json}`.

A real run of exactly this is checked in as the worked example referenced
throughout the docs: [`reports/caveman-eval-1.md`](../reports/caveman-eval-1.md),
its [`-records`](../reports/caveman-eval-1-records.md) companion, and the
`caveman-eval-1.deepeval.*` outputs.

Expected shape of the result: an output-compression skill like this typically
**saves a large fraction of output tokens** for a **small quality cost** — the
classic "saves a lot, costs a little" profile, the mirror image of a
quality-boosting skill. Accuracy is usually preserved (compression drops fluff,
not facts); any quality loss tends to be minor completeness. Your exact numbers
will vary run to run.

### Evaluating a specific intensity level

caveman has intensity levels (`lite`, `full` (default), `ultra`, and `wenyan-*`).
To exercise the most aggressive prose compression, ask for ultra:

```
Evaluate the skill at ./examples/caveman with ultra mode
```

## `karpathy-guidelines/` — a behavioral skill, and the combination partner

[`karpathy-guidelines/SKILL.md`](karpathy-guidelines/SKILL.md) is a second
self-contained example with a deliberately different profile from `caveman`.
Where `caveman` is an **`output`-mechanism** skill (it changes *how much* is
said), `karpathy-guidelines` is a **`none`-mechanism** skill — it makes **no
token claim** and instead changes *what the model does*: surface assumptions
before coding, prefer the simplest solution, make surgical edits, and define
verifiable success criteria. It bills on nothing; its value is **behavioral
quality**, which the evaluator scores with the blind judge rather than a token
headline.

It is bundled for two reasons:

1. **Single-skill, a quality skill.** Pointed at on its own, it exercises the
   mirror image of `caveman`: a skill expected to **cost** a little context for a
   **quality** gain, instead of saving tokens. A good check that the harness
   reports the quality axis honestly when there is no token story to tell.
2. **The combination partner.** It is the intended counterpart for
   `caveman` in a **combination (interaction)** run. The two pull in opposite
   directions — `caveman` strips hedging and secondary detail; `karpathy-guidelines`
   asks the model to *add* explicit assumptions and surfaced tradeoffs — so
   stacking them is a natural test of **conflict**: does compression suppress the
   very assumption-surfacing the guidelines exist to add?

> **Attribution.** `karpathy-guidelines` is third-party software by `forrestchang`
> (the *andrej-karpathy-skills* project), bundled here only as a sample to
> evaluate. It is MIT-licensed (declared in the skill's own frontmatter; see
> [`karpathy-guidelines/LICENSE`](karpathy-guidelines/LICENSE)); the canonical
> source is <https://github.com/forrestchang/andrej-karpathy-skills>. The guidelines
> are derived from Andrej Karpathy's public observations on LLM coding pitfalls.

Single-skill:

```
Evaluate the skill at ./examples/karpathy-guidelines
```

Combined with `caveman` (the interaction run — a full 2×2 factorial):

```
Evaluate skills ./examples/caveman and ./examples/karpathy-guidelines combined
```

## Trying it on your own skill

Replace the path with any skill directory containing a `SKILL.md`:

```
Evaluate ./.claude/skills/my-skill
Evaluate ~/.claude/skills/my-skill with 5 tasks
Evaluate ./.claude/skills/my-skill   # deepeval runs automatically; add --no-deepeval to skip
```
