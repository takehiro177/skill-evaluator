# Blind judge — resolved verdicts

- **Skills:** `caveman`, `karpathy`
- **combo vs none:** 0W / 3L / 0T
- **combo vs best single:** 2W / 1L / 0T

| Task | combo vs none | best single | combo vs best single |
|------|------|------|------|
| t1 | loss (slight) | caveman | win (slight) |
| t2 | loss (clear) | karpathy | win (slight) |
| t3 | loss (slight) | karpathy | loss (slight) |

## All comparisons (un-blinded)

| Job | Task | Comparison | Winner (arm) | Margin | Scores |
|-----|------|------------|--------------|--------|--------|
| t1__combo_vs_none | t1 | combo_vs_none | **base** | slight | combo=9.0 · base=9.0 |
| t1__combo_vs_caveman | t1 | combo_vs_caveman | **combo** | slight | combo=9.0 · caveman=9.0 |
| t1__combo_vs_karpathy | t1 | combo_vs_karpathy | **tie** | slight | karpathy=9.0 · combo=9.0 |
| t1__single_caveman_vs_karpathy | t1 | single_caveman_vs_karpathy | **caveman** | slight | caveman=9.0 · karpathy=9.0 |
| t2__combo_vs_none | t2 | combo_vs_none | **base** | clear | base=9.0 · combo=7.0 |
| t2__combo_vs_caveman | t2 | combo_vs_caveman | **combo** | slight | combo=9.0 · caveman=8.0 |
| t2__combo_vs_karpathy | t2 | combo_vs_karpathy | **combo** | slight | combo=9.0 · karpathy=8.0 |
| t2__single_caveman_vs_karpathy | t2 | single_caveman_vs_karpathy | **karpathy** | slight | karpathy=9.0 · caveman=8.0 |
| t3__combo_vs_none | t3 | combo_vs_none | **base** | slight | combo=9.2 · base=9.5 |
| t3__combo_vs_caveman | t3 | combo_vs_caveman | **combo** | slight | combo=9.0 · caveman=8.0 |
| t3__combo_vs_karpathy | t3 | combo_vs_karpathy | **karpathy** | slight | combo=9.0 · karpathy=9.0 |
| t3__single_caveman_vs_karpathy | t3 | single_caveman_vs_karpathy | **karpathy** | slight | caveman=9.2 · karpathy=9.5 |

> Winners were un-blinded from the private job→arm map AFTER judging; the judge saw only Response 1 / Response 2 with randomized positions.
