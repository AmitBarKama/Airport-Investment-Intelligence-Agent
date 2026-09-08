"""Named scoring profiles.

Different questions need different weightings. Rather than pretending one
ranking answers everything, the agent picks a profile and *says which one it
used*. Weights are explicit, overridable per request, and echoed in every
response.
"""
from __future__ import annotations

PILLARS = ["saturation", "unmet_demand", "growth", "feasibility", "monetization"]

PROFILES: dict[str, dict] = {
    "investment": {
        "label": "Investment attractiveness (default)",
        "description": (
            "Where is expansion capital most likely to pay off? Balances how "
            "constrained an airport is against how much demand is suppressed, "
            "how fast it is growing, and whether it can physically be built on."
        ),
        "weights": {
            "saturation": 0.30,
            "unmet_demand": 0.25,
            "growth": 0.20,
            "feasibility": 0.15,
            "monetization": 0.10,
        },
    },
    "terminal": {
        "label": "Terminal expansion candidacy",
        "description": (
            "Terminal facilities are sized off the design-day peak hour, not "
            "annual totals (FAA AC 150/5360-13A, ACRP 25). This profile leans "
            "on peak-hour passengers, peaking factor and growth, and de-"
            "emphasises runway demand/capacity."
        ),
        "weights": {
            "saturation": 0.20,
            "unmet_demand": 0.25,
            "growth": 0.28,
            "feasibility": 0.17,
            "monetization": 0.10,
        },
        "saturation_mix": {  # re-weight what "saturation" means for terminals
            "dc_ratio": 0.20, "taxi_out_p50": 0.10,
            "del15_rate": 0.20, "peaking": 0.50,
        },
    },
    "congestion": {
        "label": "Congestion comparison",
        "description": (
            "Pure congestion: how full and how delayed, right now. No growth, "
            "feasibility or monetization -- those are investment questions, "
            "not congestion questions."
        ),
        "weights": {
            "saturation": 0.70,
            "unmet_demand": 0.30,
            "growth": 0.0,
            "feasibility": 0.0,
            "monetization": 0.0,
        },
    },
    "airfield": {
        "label": "Airfield / runway capacity",
        "description": (
            "Runway-side constraint: demand against Annual Service Volume, "
            "surface queueing (taxi-out) and weather-driven capacity loss."
        ),
        "weights": {
            "saturation": 0.45,
            "unmet_demand": 0.30,
            "growth": 0.15,
            "feasibility": 0.10,
            "monetization": 0.0,
        },
        "saturation_mix": {
            "dc_ratio": 0.55, "taxi_out_p50": 0.25,
            "del15_rate": 0.15, "peaking": 0.05,
        },
    },
}

DEFAULT_SATURATION_MIX = {
    "dc_ratio": 0.50, "taxi_out_p50": 0.25, "del15_rate": 0.15, "peaking": 0.10,
}

DEFAULT_PROFILE = "investment"


def get_profile(name: str | None) -> dict:
    key = (name or DEFAULT_PROFILE).lower().strip()
    if key not in PROFILES:
        raise KeyError(
            f"unknown profile {name!r}; available: {sorted(PROFILES)}"
        )
    return PROFILES[key]


def resolve_weights(profile: str | None,
                    overrides: dict | None = None) -> tuple[dict, dict]:
    """Return (weights, profile_meta). Overrides are renormalised to sum to 1."""
    meta = get_profile(profile)
    weights = dict(meta["weights"])
    if overrides:
        unknown = set(overrides) - set(PILLARS)
        if unknown:
            raise KeyError(f"unknown pillar(s): {sorted(unknown)}")
        weights.update({k: float(v) for k, v in overrides.items()})
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("weights must sum to something positive")
    weights = {k: v / total for k, v in weights.items()}
    return weights, meta
