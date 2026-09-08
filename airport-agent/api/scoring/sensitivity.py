"""Weight-sensitivity analysis.

The weights are my judgment. Rather than defend them, defend the *robustness
of the conclusion to* them: re-run the ranking many times with perturbed
weights and report how much each airport's rank actually moves.

"BOS is #1 in 92% of weight draws" is a far stronger claim than any argument
for one particular weight vector. This follows the uncertainty/sensitivity
step of the OECD/JRC composite-indicator handbook.

Weights are drawn from a Dirichlet distribution centred on the profile's
weights; concentration controls the spread. Sampling uses random.gammavariate
(stdlib) via the standard gamma-normalisation construction of a Dirichlet.
"""
from __future__ import annotations

import random
from statistics import median
from typing import Sequence

from .composite import geometric_score
from .profiles import PILLARS


def dirichlet(mean_weights: dict, concentration: float,
              rng: random.Random) -> dict:
    """Sample a weight vector centred on `mean_weights`.

    Higher concentration -> tighter around the centre. Pillars with zero mean
    weight stay at zero (a profile that excludes growth keeps excluding it).
    """
    alphas = {k: max(1e-9, v * concentration) for k, v in mean_weights.items()}
    draws = {}
    for k, a in alphas.items():
        draws[k] = 0.0 if mean_weights.get(k, 0.0) <= 0 else rng.gammavariate(a, 1.0)
    total = sum(draws.values())
    if total <= 0:
        return dict(mean_weights)
    return {k: v / total for k, v in draws.items()}


def rank_stability(scored_rows: Sequence[dict], base_weights: dict,
                   n_draws: int = 500, concentration: float = 40.0,
                   seed: int = 20260908) -> dict:
    """Re-rank under perturbed weights; report rank distribution per airport.

    `scored_rows` must carry a `pillars` dict per airport (the output of
    score_cohort). Returns per-airport rank bands plus a headline stability
    statement the agent can quote directly.
    """
    rng = random.Random(seed)
    codes = [r["code"] for r in scored_rows]
    pillars = {r["code"]: r["pillars"] for r in scored_rows}
    ranks: dict[str, list[int]] = {c: [] for c in codes}

    for _ in range(n_draws):
        w = dirichlet(base_weights, concentration, rng)
        scores = [(c, geometric_score(pillars[c], w)) for c in codes]
        scores.sort(key=lambda t: t[1], reverse=True)
        for pos, (c, _s) in enumerate(scores, 1):
            ranks[c].append(pos)

    def band(vals: list[int]) -> dict:
        s = sorted(vals)
        n = len(s)
        return {
            "median_rank": median(s),
            "p10_rank": s[max(0, int(0.10 * n) - 1)],
            "p90_rank": s[min(n - 1, int(0.90 * n))],
            "best": s[0],
            "worst": s[-1],
        }

    out = {}
    for c in codes:
        b = band(ranks[c])
        b["p_top3"] = round(sum(1 for r in ranks[c] if r <= 3) / n_draws, 3)
        b["p_top1"] = round(sum(1 for r in ranks[c] if r == 1) / n_draws, 3)
        b["stable"] = (b["p90_rank"] - b["p10_rank"]) <= 2
        out[c] = b

    leader = max(codes, key=lambda c: out[c]["p_top1"]) if codes else None
    headline = None
    if leader:
        p = out[leader]["p_top1"]
        if p >= 0.7:
            headline = (f"{leader} ranks first in {p:.0%} of weight draws -- the "
                        f"top of this ranking is robust to how the pillars are weighted.")
        elif p >= 0.4:
            headline = (f"{leader} ranks first in {p:.0%} of weight draws -- the "
                        f"leader is likely but not certain under other weightings.")
        else:
            headline = ("No airport leads in a majority of weight draws: treat "
                        "the ordering at the top as genuinely unsettled.")

    return {
        "n_draws": n_draws,
        "concentration": concentration,
        "base_weights": base_weights,
        "per_airport": out,
        "headline": headline,
        "method": ("Dirichlet-perturbed weights around the profile centre; "
                   "OECD/JRC composite-indicator uncertainty analysis."),
    }
