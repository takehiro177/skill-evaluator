# Methodology

## The question

> Does this skill actually help — and at what token cost?

A skill's `SKILL.md` *claims* to help with some class of tasks. skill-evaluator
tests that claim by having Claude solve representative tasks **with** and
**without** the skill's guidance and comparing the two arms on cost and quality.

## Why A/B, and why injection-based

A skill could "look" useful while making no difference, or even making things
worse (extra context, distracting instructions, over-scoping). The only honest
way to know is a controlled comparison where the skill is the **single
manipulated variable**.

We inject the skill's body text into the WITH arm's prompt and withhold it from
the WITHOUT arm. Both arms get the identical task, input, and framing. Because
the contrast is created by *injection* rather than by toggling an installed
skill, the experiment is:

- **Reproducible** — independent of what's installed in the user's project.
- **Clean** — no risk of an installed skill silently bleeding into the
  "without" arm via subagent inheritance.
- **Portable** — works for a skill that isn't installed anywhere yet (e.g. one
  under active development).

## Deriving tasks from the claim, not the code

Tasks are generated from what the skill **claims** (its `description` and the
intent in its body), not from its implementation. This keeps the evaluation
honest: we test whether the *promise* holds, and we don't accidentally write
tasks that only the skill's specific phrasing could satisfy.

Good task sets:
- spread across the skill's claimed capability surface;
- are solvable (if imperfectly) **without** the skill, so the comparison is meaningful;
- carry a **skill-agnostic rubric** describing a good outcome.

`--from-history` optionally grounds tasks in the user's real past prompts that
match the skill's trigger, trading some control for realism.

## Two metrics, two instruments

### 1. Tokens saved (cost)

Measured, not estimated. Each arm runs as a subagent; Claude Code records every
turn's `usage` in the session transcript. `transcript_tokens.py` attributes
those tokens to the correct arm via a unique **RUN MARKER** the runner echoes.

Tokens are **cost-weighted**, not summed flat: a cache-read token (0.1×), a
cache-write token (1.25×), an uncached input token (1×), and an output token
(5×) cost wildly different amounts, so the flat `input+cache+output` total
mis-weights cheap cached context against expensive generation. We report the
cost-weighted delta (`transcript_tokens.py --cost`) on the **axis the skill bills
on** (output / context / round-trips — see
[`token-accuracy.md`](token-accuracy.md)), and we separate one-time setup (e.g.
injected guidance) from recurring per-turn savings, with a breakeven.

A negative result is a real result and is reported as such.

### 2. Output quality (LLM-as-judge)

Scored by a **separate, blind** subagent. It receives only the task, the
rubric, and the two responses labeled `Response 1` / `Response 2` in randomized
order. It never learns:

- that an A/B test is happening,
- which response used the skill,
- the run markers, or
- any token figures.

This structural blindness is what makes the quality verdict trustworthy. The
judge guards explicitly against position bias and verbosity bias, and scores
against the rubric rather than personal taste.

## Threats to validity (and what we do about them)

| Threat | Mitigation |
|--------|------------|
| **Position bias** in the judge | Independent randomization of Response 1/2; explicit anti-bias instructions. |
| **Leakage** of arm identity to the judge | Judge is a separate context fed only clean inputs; no markers/tokens/skill words. |
| **Installed skill bleeding into WITHOUT arm** | Injection-based design + explicit "do not invoke specialized skills" instruction. |
| **Cherry-picked tasks** | Tasks derived from the claim surface and shown to the user; `--from-history` for realism. |
| **Small sample size** | Reported as directional, not conclusive; easy to raise `--tasks` or repeat. |
| **Estimated/guessed tokens** | Forbidden — tokens only ever come from the transcript; otherwise marked `unmeasured`. |
| **Flat-total mis-weighting** | Headline is **cost-weighted** (`--cost`), on the skill's billing axis — never the raw `input+cache+output` sum. See [`token-accuracy.md`](token-accuracy.md). |
| **Cache cold/warm by run order** | Warm the prefix with a primer + run arms serially; or normalize the shared prefix to a warm read for both arms. |
| **One-time setup charged per task** | Inject guidance / build the index **once** and run several turns; report breakeven + amortized, not just per-task. |
| **Wrong axis for the mechanism** | Phase 0 classifies the skill's mechanism; the metric matches it (output vs context vs round-trips). |
| **Run-to-run variance** | Acknowledged; repeats recommended for high-stakes calls. Stochastic outputs mean a single run is a sample, not the truth. |

## What this does *not* establish

- Statistical significance (N is small by design — it's an in-chat harness).
- That the skill triggers correctly in the wild (this tests *given* the skill is
  applied, does it help — a separate question from trigger accuracy; for that,
  see the `skill-creator` skill's eval tooling).
- Anything about latency or wall-clock time — only tokens and quality.
