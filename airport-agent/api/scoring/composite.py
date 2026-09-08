"""Composite aggregation, FAA tiering, and confidence.

Aggregation is a WEIGHTED GEOMETRIC MEAN, not an arithmetic one. That choice
is the economic heart of the model:

    Score = 100 * PROD_i ( pillar_i ^ w_i )

A geometric mean is *partially non-compensatory*: a near-zero pillar drags the
whole score down and cannot be bought off by strength elsewhere. An arithmetic
mean would let extreme congestion paper over zero buildability, and would rank
LaGuardia -- the most congested airport in the US and one of the worst places
to spend expansion capital -- at the very top. Congestion tells you where the
pain is; feasibility tells you where you can actually build.

Tiering comes from FAA Advisory Circular 150/5060-5 (Airport Capacity and
Delay), which sets published planning triggers against Annual Service Volume:
plan at 60% of ASV, build at 80%. Leading with the tier means leading with the
regulator's judgment rather than my weighting.
"""
from __future__ import annotations

import math
from typing import Sequence

from .profiles import PILLARS

# FAA AC 150/5060-5 planning triggers, expressed as demand / ASV.
TIERS = [
    ("A", 0.80, "Build now",
     "At or above 80% of Annual Service Volume: FAA guidance is that "
     "construction of additional capacity should be underway."),
    ("B", 0.60, "Plan now",
     "Between 60% and 80% of ASV: FAA guidance is that capacity planning "
     "should have started."),
    ("C", 0.45, "Monitor",
     "Approaching the 60% planning trigger."),
    ("D", 0.00, "No capacity case",
     "Below 45% of ASV: any investment case must rest on something other "
     "than airfield capacity."),
]


def assign_tier(dc_ratio: float | None) -> dict:
    """Map demand/ASV onto the FAA planning tiers."""
    if dc_ratio is None:
        return {
            "tier": None, "label": "Unknown",
            "rationale": "No demand/capacity ratio available for this airport.",
            "source": "FAA AC 150/5060-5",
        }
    for tier, threshold, label, rationale in TIERS:
        if dc_ratio >= threshold:
            return {
                "tier": tier, "label": label, "rationale": rationale,
                "threshold": threshold, "dc_ratio": round(dc_ratio, 3),
                "source": "FAA AC 150/5060-5",
            }
    return {"tier": "D", "label": "No capacity case", "rationale": "",
            "source": "FAA AC 150/5060-5"}


def geometric_score(pillars: dict, weights: dict, floor: float = 0.01) -> float:
    """Weighted geometric mean of pillar values, scaled to 0-100."""
    log_sum = 0.0
    used_weight = 0.0
    for name in PILLARS:
        w = weights.get(name, 0.0)
        if w <= 0:
            continue
        v = pillars.get(name)
        if v is None:
            continue
        log_sum += w * math.log(max(floor, min(1.0, v)))
        used_weight += w
    if used_weight <= 0:
        return 0.0
    # Renormalise by the weight actually used so partial data is not penalised
    # twice (once by the missing pillar, once by a shrunken exponent sum).
    return 100.0 * math.exp(log_sum / used_weight)


def pillar_contributions(pillars: dict, weights: dict,
                         floor: float = 0.01) -> list[dict]:
    """Explain the geometric score additively, in log space.

    Geometric contributions are not additive in level terms, so we report the
    log contribution share -- which *is* additive -- alongside the raw value.
    This is what `explain_score` surfaces to the user.
    """
    rows = []
    used = [(n, weights.get(n, 0.0), pillars.get(n))
            for n in PILLARS if weights.get(n, 0.0) > 0 and pillars.get(n) is not None]
    total_w = sum(w for _, w, _ in used) or 1.0
    log_terms = {n: (w / total_w) * math.log(max(floor, min(1.0, v)))
                 for n, w, v in used}
    log_total = sum(log_terms.values()) or -1e-9
    for name, w, v in used:
        rows.append({
            "pillar": name,
            "value": round(v, 4),
            "weight": round(w / total_w, 4),
            "log_contribution": round(log_terms[name], 4),
            # share of the *shortfall from 100* attributable to this pillar
            "share_of_shortfall": round(log_terms[name] / log_total, 4),
            "drag": v < 0.35,  # flag pillars actively dragging the geometric mean
        })
    rows.sort(key=lambda r: r["share_of_shortfall"], reverse=True)
    return rows


def confidence(coverage: dict, asv_source: str | None,
               vintage_age_months: float | None) -> dict:
    """A blunt, explainable data-quality score in [0,1].

    Deliberately simple and fully inspectable: an opaque confidence number
    would be worse than none at all.
    """
    cov = sum(coverage.values()) / max(1, len(coverage))

    asv_quality = {
        "faa_capacity_profile": 1.0,   # published called rates
        "runway_config": 0.5,          # AC 150/5060-5 configuration lookup
        "peer_regression": 0.2,        # fallback estimate
    }.get(asv_source or "", 0.2)

    if vintage_age_months is None:
        recency = 0.5
    else:
        recency = max(0.0, min(1.0, 1.0 - (vintage_age_months / 36.0)))

    score = 0.5 * cov + 0.2 * asv_quality + 0.3 * recency
    label = "high" if score >= 0.75 else "medium" if score >= 0.5 else "low"
    reasons = []
    if cov < 0.8:
        reasons.append(f"only {cov:.0%} of scoring inputs are backed by data")
    if asv_quality < 1.0:
        reasons.append(f"capacity denominator is {asv_source or 'unknown'}, not a published FAA profile")
    if recency < 0.8 and vintage_age_months is not None:
        reasons.append(f"data is about {vintage_age_months:.0f} months old")
    return {
        "score": round(score, 3),
        "label": label,
        "reasons": reasons or ["all scoring inputs present and current"],
    }


def score_cohort(rows: Sequence[dict], pillar_rows: Sequence[dict],
                 weights: dict, vintage_age_months: float | None = None) -> list[dict]:
    """Combine metrics + pillars into final ranked results."""
    results = []
    for r, p in zip(rows, pillar_rows):
        pillars = {k: p.get(k) for k in PILLARS}
        score = geometric_score(pillars, weights)
        tier = assign_tier(r.get("dc_ratio"))
        conf = confidence(p.get("coverage", {}), r.get("asv_source"),
                          vintage_age_months)
        results.append({
            "code": r.get("code"),
            "name": r.get("name"),
            "city": r.get("city"),
            "state": r.get("state"),
            "hub_class": r.get("hub_class"),
            "score": round(score, 1),
            "tier": tier["tier"],
            "tier_label": tier["label"],
            "tier_rationale": tier["rationale"],
            "pillars": {k: (round(v, 4) if v is not None else None)
                        for k, v in pillars.items()},
            "coverage": p.get("coverage", {}),
            "confidence": conf,
            "metrics": r,
        })
    results.sort(key=lambda x: x["score"], reverse=True)
    for i, res in enumerate(results, 1):
        res["rank"] = i
    return results
