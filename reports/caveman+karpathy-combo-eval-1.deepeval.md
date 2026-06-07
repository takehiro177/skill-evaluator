# deepeval metrics

Cases: 3  
GEval (0–1) per arm, each arm scored in isolation against the task rubric.

| Task | base | caveman | karpathy | combo |
|------|-----------:|-----------:|-----------:|-----------:|
| t1 | 1.000 | 1.000 | 1.000 | 1.000 |
| t2 | 1.000 | 0.600 | 1.000 | 1.000 |
| t3 | 0.900 | 1.000 | 1.000 | 1.000 |
| **mean** | 0.967 | 0.867 | 1.000 | 1.000 |

Δ vs `base` (per-arm mean − baseline mean): `caveman` -0.100 · `karpathy` +0.033 · `combo` +0.033

Scores are GEval (0–1), each arm judged in isolation; GEval saturates, so use it to corroborate the blind pairwise judge, not to replace it.
