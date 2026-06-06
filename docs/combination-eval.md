# Combination (multi-skill) evaluation

Single-skill evaluation answers *does this one skill help?* But skills rarely run
alone — several can be active in the same session, and when they are, their
**interaction** (do they reinforce, duplicate, or fight each other?) is the part
that normally goes un-measured. This document describes how skill-evaluator
extends its blind A/B harness to measure that interaction.

It is the combination-mode companion to [`methodology.md`](methodology.md) (the
single-skill method) and [`token-accuracy.md`](token-accuracy.md) (cost-weighting,
which applies unchanged here).

## The question

> When two or more skills are applied together, is the combined result **more**
> than the sum of the individual skills (synergy), **less** (redundancy /
> diminishing returns), or **worse than the best single skill** (conflict) — on
> tokens *and* on quality?

A single-skill report can tell you skill A saves 20% and skill B saves 10%. It
cannot tell you whether running A+B saves 30% (additive), 40% (synergy), 25%
(redundant overlap), or actually *costs more* because the two give the model
contradictory instructions. That last case is common and silent: two
output-compression skills, or one "be exhaustive" skill stacked with one "be
terse" skill, can quietly cancel out. Combination mode measures it.

## Method: blind A/B over skill *subsets*

We keep everything that makes the single-skill eval trustworthy and change one
thing: instead of two arms (WITH / WITHOUT one skill), an arm is defined by the
**subset of skills injected into it**. The baseline arm injects none; the combo
arm injects all of them; intermediate arms (if the design uses them) inject some.
The injected subset is still the single manipulated variable, so the contrast is
clean, reproducible, and independent of what's installed — exactly as in
[`methodology.md`](methodology.md#why-ab-and-why-injection-based).

Each arm gets a unique RUN MARKER, so `transcript_tokens.py` attributes tokens to
it from the real transcript, and `interaction_effects.py` then combines the
per-arm numbers into the effects below. Quality is scored by the same blind
`skill-eval-judge`.

## Designs (and how many arms they cost)

You pick how much you want to spend; the analysis adapts to whatever arms exist.
For N skills:

| Design | Arms / task | What you learn | When to use |
|--------|------------|----------------|-------------|
| **combined-vs-baseline** *(default for N ≥ 3)* | 2 | Combined effect only ("does the bundle help?"). **No** per-skill attribution, **no** interaction term. | Quick read on a stack; many skills. |
| **factorial-2** *(default for N = 2)* | 4 | Full 2×2: each skill's individual effect **and** the exact interaction. | The common "do these two play well together?" question. |
| **leave-one-out** | N + 2 | Combined effect + each skill's **marginal contribution within the stack** (drop it, see what changes). | "Which skill in my stack is pulling its weight?" |
| **full-factorial** | 2ᴺ | Every individual effect, every pairwise interaction, total excess-over-additive. | Small N, high-stakes, you want the complete map. Cost grows 2ᴺ. |

The default is deliberately cheap: for N ≥ 3 we run **combined-vs-baseline** and
report the bundle's overall effect, and you opt into `--leave-one-out` or
`--full-factorial` when you want the interaction attributed. For N = 2 the full
2×2 factorial is only 4 arms, so we always run it — the interaction comes for
nearly free.

## The interaction number

On a chosen metric (default the cost-weighted `cost_units`; or the skill's billing
axis — output / context / round-trips, see
[`token-accuracy.md`](token-accuracy.md#match-the-metric-to-the-mechanism)), with
cell value `V[subset]`:

- **combined effect** = `V[all] − V[∅]` — the whole stack vs nothing.
- **individual effect** of skill *i* = `V[{i}] − V[∅]` — that skill alone.
  *(needs the single-skill arms: factorial / full-factorial)*
- **additive prediction** = `V[∅] + Σᵢ individual effectᵢ` — what you'd get if the
  skills simply stacked with no interaction.
- **interaction** = `combined effect − Σᵢ individual effect` = `V[all] − additive
  prediction` — the **excess over additive**: the part of the combined result that
  the individual skills do not explain. *This is the number single-skill
  evaluation never produces.*
- **marginal contribution** of skill *i* = `V[all] − V[all\{i}]` — the effect of
  *adding i to everything else*. *(leave-one-out / full-factorial)*
- **pairwise interaction** (i, j) = `V[{i,j}] − V[{i}] − V[{j}] + V[∅]`.
  *(factorial / full-factorial)*

`interaction_effects.py` reports whichever of these the supplied arms allow, per
task and aggregated over tasks, and never fabricates one it can't source — an arm
it can't attribute is `unmeasured`, not guessed.

## Classification

On the headline metric (lower = cheaper, for token reducers), with
`savings = V[∅] − V[subset]`:

| Label | Condition | Meaning |
|-------|-----------|---------|
| **synergistic** | combined savings > additive prediction (beyond tolerance) | The stack beats the sum of its parts — the skills reinforce each other. |
| **additive** | combined savings ≈ additive prediction | Effects just add up; no meaningful interaction. |
| **redundant / sub-additive** | combined savings < additive but still > best single | Diminishing returns — the skills overlap, but stacking still beats either alone. |
| **conflicting / antagonistic** | combined savings < best single skill | Stacking is **worse than just using the strongest skill** — a red flag. |
| **costs more** | combined savings < 0 | The bundle is worse than running no skill at all. |

The tolerance band (default ±10% of the additive prediction, `--rel-tol`) keeps
small measurement noise from being read as synergy or redundancy. The report
always prints the raw numbers next to the label so you can judge a borderline call
yourself.

## Mechanism overlap — the prior

Before running, classify each skill's token mechanism (output / context /
round-trips / none — Phase 0.4 of the skill). It predicts the interaction:

- **Same axis** (e.g. two `output` compressors): expect **redundancy or
  conflict** — they're fighting over the same lever, and the second one often adds
  little or contradicts the first.
- **Different axes** (e.g. an `output` compressor + a `context`/code-map skill):
  expect **roughly additive** — they pull different levers and tend not to step on
  each other.

This is only a prior; the measured interaction confirms or refutes it, and a
surprising result (same-axis skills that turn out synergistic, or orthogonal ones
that conflict) is exactly what's worth reporting.

## Quality: two decisive comparisons

The blind judge stays blind and pairwise, but combination mode asks it the two
questions that matter for a stack:

1. **combo vs none** — does applying the whole stack produce a better answer than
   applying nothing? (The combination's quality must hold, not just its tokens.)
2. **combo vs the best single skill** — does stacking actually beat just using the
   strongest skill alone? If the combination loses here, the extra skills are at
   best dead weight and at worst harmful, *no matter what the token numbers say*.

Each comparison is a separate judge subagent fed only the task, a skill-agnostic
rubric, and two anonymized responses in randomized order — no skill names, arm
labels, markers, or token figures. deepeval scores every arm (base / each single /
combo) in isolation as a complementary cross-check.

The headline is a **joint verdict**: a token synergy with a quality regression (or
a combo that the judge rates below a single skill) is reported as a regression,
not a win.

## What this does *not* establish

- **Co-triggering.** Like the single-skill eval, this **injects** the skills, so it
  measures the combination *when both are in effect* — not whether both would
  actually trigger on the same real prompt. Trigger overlap is a separate question
  (for trigger accuracy, see Anthropic's `skill-creator` eval tooling).
- **Statistical significance.** N is small by design. The interaction is a
  *difference of differences*, so it is the noisiest figure in the report — treat
  it as directional and repeat / raise `--tasks` for high-stakes calls.
- **Anything about latency.** Tokens and quality only.

## Worked sketch

Two output-style skills, cost-weighted `cost_units`, factorial-2:

```
base = 1000,  A = 800,  B = 900,  combo (A+B) = 600
individual: A −200, B −100        → additive prediction = 700
combined effect = −400            → interaction = 600 − 700 = −100
combined savings 400 > additive savings 300 + tol → SYNERGISTIC
```

…versus the same skills that fight over output length:

```
base = 1000,  A = 700,  B = 750,  combo = 820
combined savings 180 < best single savings 300 → CONFLICTING
```

Both are produced verbatim by `interaction_effects.py`; the report turns them into
the verdict and the bottom-line recommendation.
