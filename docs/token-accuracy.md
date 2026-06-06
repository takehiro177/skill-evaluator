# Token accuracy in skill-evaluator

How to measure a skill's token claim *accurately*: measure the axis the skill
actually bills on, under production-like conditions, priced correctly, and gated
on quality. This is the reference behind the six rules baked into the
orchestrator `SKILL.md`.

## Why a flat token count lies

Claude Code transcripts record four token types per turn, billed at very
different rates (ratios relative to one base input token; the output:input ratio
is **5×** across the current Claude lineup — Opus $5/$25, Sonnet $3/$15, Haiku
$1/$5, so it is model-independent):

| field | meaning | price |
|---|---|---|
| `input_tokens` | uncached prompt remainder | 1.0× |
| `cache_creation_input_tokens` | written to cache | 1.25× (5-min TTL; 2× for 1h) |
| `cache_read_input_tokens` | served from cache | 0.10× |
| `output_tokens` | generated | 5.0× |

`total = input + cache_create + cache_read + output`. Summing them 1:1 (the
naive "total tokens" metric) prices a cached-context token the same as a
generated token — a **50× error at the extremes**. A skill that adds cheap
cached guidance to save expensive output looks like it "costs more" on the flat
sum while being cheaper to actually run. (caveman is exactly this kind of skill:
its flat-sum reading can look like a wash or worse, while the cost-weighted,
output-axis reading shows a clear saving — see the worked example below.)

→ **Rule: never headline the flat total. Use cost-weighted "effective
input-token-equivalents"** — `transcript_tokens.py --cost`.

## Match the metric to the mechanism

Every "reduces tokens" claim acts on one axis. Classify it first (SKILL.md
Phase 0.4), then measure that axis:

| mechanism | example | axis it bills on | headline metric | task design |
|---|---|---|---|---|
| **output** reducer | caveman (compress responses) | output (5×) | Δ output tokens, cost-weighted, quality-gated | any task with a substantive answer |
| **context** reducer | graphify / code-map / index | input + cache-read pulled in | Δ context tokens + # / size of files read | a **real repo** + retrieval/navigation tasks |
| **round-trips** reducer | plan-once / batch-tools | # tool calls / assistant turns | Δ tool calls or turns | tasks needing multi-step tool use |
| **none** | style/format-only, no token claim | — | report "no token claim" | — |

A context reducer measured on output, or an output reducer measured on the flat
total, will mis-rank the skill. For a `context` skill the concrete proxy is the
number and size of files the agent reads — sum the `tool_result` token counts in
the transcript WITH vs WITHOUT.

## Measure under production conditions

Three things distort an isolated A/B vs. how the skill runs for real:

1. **One-time setup vs recurring savings.** caveman loads its guidance once per
   session (SessionStart hook); a context skill builds its index once. Per-task
   injection re-charges that setup *every task*, so the skill looks worse than it
   is. → **Inject/build the setup ONCE and run several turns/queries against it**
   (single-injection, multi-task runner). Report the one-time cost, the per-turn
   saving, the **breakeven**, and an N-turn amortized projection separately.
2. **Cache cold/warm by run order.** The first subagent after a >5-min idle pays
   the shared prefix as a cold 1.25× write; later ones read it warm at 0.1×.
   Whichever arm runs first eats the cold write — a pure ordering artifact that
   can swamp the real signal (we measured a `+4,334` cost result flip to
   `−5,787` purely from a cold cache). → **Warm the cache with a throwaway primer
   turn, then run arms serially.** If you can't, normalize: charge the shared
   prefix as a warm read for both arms.
3. **Persistent skills are multi-turn.** A per-turn output style only shows its
   true economics across a session, not one isolated turn — covered by rule 1's
   multi-turn runner.

## Gate tokens on quality (joint verdict)

"Fewer tokens" is only a win if the answer is still correct — and a naive harness
can be gamed by simply answering worse. → **The headline is a JOINT verdict:**
"saved X% (cost-weighted) AND quality within noise", or "saved X% **but** at Δq
quality (lost W/T/L)". Combine the blind judge's win/tie/loss + mean score delta
with the cost delta. A token win with a quality loss is a regression — report it
as one.

## The six rules (as implemented in `SKILL.md`)

1. **Phase 0.4** declares the skill's `mechanism` (output | context | round-trips | none).
2. **Per-mechanism headline metric** — never the flat total.
3. **Always cost-weight** (1 / 1.25 / 0.1 / 5) and **split one-time vs recurring**, with breakeven + amortized projection.
4. **Production conditions:** warm cache + serial arms; single-injection multi-turn runner for persistent skills.
5. **Joint token+quality verdict.**
6. **`transcript_tokens.py --cost`** emits the cost-weighted view automatically.

## Worked example

[`reports/caveman-eval-1.md`](../reports/caveman-eval-1.md) applies all six rules
to caveman at `ultra`: a single guidance injection across a 3-task session, cache
primed and arms run serially, an output-token headline, cost-weighted, with a
joint token+quality verdict and a deepeval GEval cross-check. It records:

- **Output-axis headline, not the flat sum:** −59% output tokens / −48%
  cost-weighted, with the per-task vs session distinction made explicit.
- **One-time setup split from recurring saving:** a ~1.1k-token guidance load
  charged once, ~797 output tok/turn saved, breakeven ≈ 0.35 turns, plus an
  amortized-over-10-turns projection.
- **Production conditions:** both arms read the shared prefix warm (equal
  `cache_read`), so neither ate a cold-cache write.
- **Joint verdict:** a large token win against a small, consistent quality cost
  (judge −1/10 each task) with zero technical errors — reported as "mixed,
  favorable", not a clean win.

Its companion [`reports/caveman-eval-1-records.md`](../reports/caveman-eval-1-records.md)
holds the verbatim WITH/WITHOUT arm outputs so the numbers can be checked by hand.
