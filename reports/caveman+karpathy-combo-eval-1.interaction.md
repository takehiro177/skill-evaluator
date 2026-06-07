# Skill combination - interaction effects

- **Skills:** `caveman`, `karpathy`
- **Design:** `factorial-2`
- **Headline metric:** `cost_units` (lower is better)

**Verdict:** additive - combined effect ~= the sum of the individual effects

## Aggregate decomposition (mean across tasks)

| quantity | value (in `cost_units`) |
|---|---:|
| baseline (no skills) | 13,611.5 |
| combo (all skills) | 9,394 |
| **combined effect** (combo - base) | -4,217.5 |
| combined savings | 4,217.5 |
| individual effect - `caveman` | -3,036.2 |
| individual effect - `karpathy` | -1,393.5 |
| marginal contribution - `caveman` (within stack) | -2,824 |
| marginal contribution - `karpathy` (within stack) | -1,181.3 |
| pairwise interaction - caveman x karpathy | 212.2 |
| additive prediction | 9,181.8 |
| **interaction** (excess over additive) | 212.2 |
| best single-skill savings | 3,036.2 |

## Per-task (headline metric: `cost_units`)

| task | arm (skills injected) | `cost_units` | combined savings | classification |
|---|---|---:|---:|---|
| all | (baseline) | 13,611.5 |  |  |
| all | caveman | 10,575.3 |  |  |
| all | karpathy | 12,218 |  |  |
| all | caveman+karpathy | 9,394 |  |  |
| all | **-> effect** |  | 4,217.5 | additive - combined effect ~= the sum of the individual effects |

> Interaction = combined effect minus the sum of individual effects: the part
> of the combined result that single-skill evaluation never sees. Tokens are
> sourced from the transcript via RUN MARKER, never estimated. Small N is
> directional, not conclusive.
