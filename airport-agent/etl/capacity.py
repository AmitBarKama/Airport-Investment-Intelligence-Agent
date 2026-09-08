"""Runway configuration -> Annual Service Volume (ASV).

ASV is the denominator of the demand/capacity ratio that drives the FAA
tiering, so it matters a lot. Three sources, in descending order of quality:

  1. `faa_capacity_profile` -- called arrival/departure rates published by the
     FAA for ~40 major airports. Best. Transcribe from the FAA PDFs into
     etl/curated/capacity_profiles.csv.
  2. `runway_config` -- classify the airfield from real runway geometry
     (count, parallel vs intersecting, and centreline separation computed from
     the threshold coordinates in OurAirports), then look up a representative
     ASV for that configuration class from FAA AC 150/5060-5.
  3. `peer_regression` -- last-resort fallback.

>>> IMPORTANT, AND DELIBERATELY LOUD <<<
The ASV_BY_CONFIG numbers below are ORDER-OF-MAGNITUDE PLACEHOLDERS chosen to
be representative of the ranges discussed in AC 150/5060-5. They have NOT been
transcribed from the advisory circular's figures. Anyone using this for real
analysis must replace them with values read directly out of the AC (Chapter 2
capacity figures) or, better, with published FAA capacity profiles.

They are flagged as `asv_source="runway_config"`, which drives the confidence
score down, and every API response carries that flag. Fabricating a precise
number here and presenting it as authoritative would be the single worst thing
this codebase could do, so it says plainly what it is instead.
"""
from __future__ import annotations

import math

# Representative annual operations by configuration class.
# PLACEHOLDERS -- see the module docstring. Verify against AC 150/5060-5.
ASV_BY_CONFIG: dict[str, int] = {
    "single":                220_000,
    "two_parallel_close":    275_000,   # centreline separation < 2,500 ft
    "two_parallel_medium":   315_000,   # 2,500 - 4,299 ft
    "two_parallel_far":      385_000,   # >= 4,300 ft (independent IFR approaches)
    "two_intersecting":      240_000,
    "three_runway":          560_000,
    "four_plus_runway":      750_000,
    "unknown":               220_000,
}

CONFIG_LABEL = {
    "single": "Single runway",
    "two_parallel_close": "Two close parallel runways (<2,500 ft apart)",
    "two_parallel_medium": "Two intermediate parallel runways (2,500-4,299 ft)",
    "two_parallel_far": "Two far parallel runways (>=4,300 ft, independent IFR approaches)",
    "two_intersecting": "Two intersecting runways",
    "three_runway": "Three runways",
    "four_plus_runway": "Four or more runways",
    "unknown": "Unknown configuration",
}

# Below 4,300 ft, simultaneous independent instrument approaches are not
# permitted, so arrival capacity degrades materially in low visibility.
INDEPENDENT_IFR_SEPARATION_FT = 4300

# Annual capacity discount applied when the primary parallel pair is too close
# for independent IFR approaches. Representative, not measured -- see caveat.
IMC_CAPACITY_FACTOR = 0.85

# Two runways count as "parallel" only if their true headings agree closely.
# A loose tolerance produces spurious pairs: at Boston, runways 14 and 15R sit
# 10 degrees apart and are not operationally parallel, but a 15-degree window
# pairs them and wrongly credits the airfield with independent approaches.
PARALLEL_HEADING_TOLERANCE_DEG = 8.0


def _haversine_ft(lat1, lon1, lat2, lon2) -> float:
    R_ft = 20_902_231.0  # mean Earth radius in feet
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_ft * math.asin(min(1.0, math.sqrt(a)))


def _heading_diff(h1: float, h2: float) -> float:
    """Smallest angle between two runway headings, treating 180-degree
    reciprocals as the same physical alignment."""
    d = abs((h1 - h2) % 180.0)
    return min(d, 180.0 - d)


def _perp_separation_ft(r1: dict, r2: dict, heading: float) -> float | None:
    """Perpendicular distance between two parallel runway centrelines."""
    try:
        lat1, lon1 = float(r1["le_latitude_deg"]), float(r1["le_longitude_deg"])
        lat2, lon2 = float(r2["le_latitude_deg"]), float(r2["le_longitude_deg"])
    except (TypeError, ValueError, KeyError):
        return None
    d = _haversine_ft(lat1, lon1, lat2, lon2)
    if d == 0:
        return 0.0
    brg = _bearing_deg(lat1, lon1, lat2, lon2)
    # component of the threshold-to-threshold vector perpendicular to the
    # runway alignment
    return abs(d * math.sin(math.radians(_heading_diff(brg, heading))))


def _runway_length(r: dict) -> int:
    try:
        return int(float(r.get("length_ft") or 0))
    except (TypeError, ValueError):
        return 0


def _runway_heading(r: dict) -> float | None:
    try:
        h = float(r.get("le_heading_degT"))
        return h if not math.isnan(h) else None
    except (TypeError, ValueError):
        return None


def parallel_pairs(runways: list[dict]) -> list[dict]:
    """All parallel runway pairs with their centreline separations."""
    pairs = []
    for i in range(len(runways)):
        for j in range(i + 1, len(runways)):
            h1, h2 = _runway_heading(runways[i]), _runway_heading(runways[j])
            if h1 is None or h2 is None:
                continue
            if _heading_diff(h1, h2) > PARALLEL_HEADING_TOLERANCE_DEG:
                continue
            sep = _perp_separation_ft(runways[i], runways[j], h1)
            if sep is None:
                continue
            pairs.append({
                "runways": [runways[i].get("le_ident"), runways[j].get("le_ident")],
                "separation_ft": round(sep),
                "combined_length_ft": _runway_length(runways[i]) + _runway_length(runways[j]),
                "independent_ifr": sep >= INDEPENDENT_IFR_SEPARATION_FT,
            })
    return pairs


def classify(runways: list[dict]) -> dict:
    """Classify an airfield from its runway geometry.

    `runways` come straight from OurAirports runways.csv (closed ones filtered
    out). Beyond counting runways, this computes the separation of every
    parallel pair from the real threshold coordinates, because closely spaced
    parallels are a first-order capacity constraint: below about 4,300 ft,
    simultaneous independent instrument approaches are not permitted, so
    arrival capacity degrades sharply in low visibility.

    That distinction is why San Francisco (four runways, but arranged as two
    closely spaced pairs) is not the same airfield as Dallas/Fort Worth (seven
    widely spaced runways), even though a naive runway count says otherwise.

    Known limitation: this is pure geometry. It does not know which runway
    pairs are actually certified or used for simultaneous approaches, nor
    about terrain, airspace or noise procedures that constrain real operations.
    It is a screening heuristic, and airports where it matters should be
    replaced with published FAA capacity profiles.
    """
    usable = [r for r in runways if _runway_length(r) >= 3000]
    n = len(usable)
    pairs = parallel_pairs(usable)

    # The "primary" arrival pair: the parallel pair with the most pavement.
    primary = max(pairs, key=lambda p: p["combined_length_ft"]) if pairs else None
    min_sep = min((p["separation_ft"] for p in pairs), default=None)
    max_sep = max((p["separation_ft"] for p in pairs), default=None)

    if n == 0:
        config = "unknown"
    elif n == 1:
        config = "single"
    elif n == 2:
        if primary is None:
            config = "two_intersecting"
        elif primary["separation_ft"] >= INDEPENDENT_IFR_SEPARATION_FT:
            config = "two_parallel_far"
        elif primary["separation_ft"] >= 2500:
            config = "two_parallel_medium"
        else:
            config = "two_parallel_close"
    elif n == 3:
        config = "three_runway"
    else:
        config = "four_plus_runway"

    asv = ASV_BY_CONFIG[config]

    # Weather-driven capacity loss: if the airport's primary arrival pair is
    # too close for independent IFR approaches, effective annual capacity is
    # materially lower than the runway count alone suggests.
    # An airport is IMC-constrained only if it has NO parallel pair spaced
    # widely enough for simultaneous independent approaches. Having one close
    # pair is fine if another pair is far enough apart (Denver, Los Angeles);
    # having only close pairs is the real constraint (San Francisco, Seattle).
    has_independent_pair = any(p["independent_ifr"] for p in pairs)
    imc_constrained = bool(pairs) and not has_independent_pair
    imc_note = None
    if imc_constrained and n >= 2:
        asv = int(asv * IMC_CAPACITY_FACTOR)
        imc_note = (
            f"Widest parallel pair is ~{max_sep:,} ft apart, "
            f"below the ~{INDEPENDENT_IFR_SEPARATION_FT:,} ft needed for independent "
            f"simultaneous instrument approaches. Arrival capacity therefore drops "
            f"substantially in low visibility, and effective ASV is discounted by "
            f"{int((1 - IMC_CAPACITY_FACTOR) * 100)}%."
        )

    return {
        "config": config,
        "config_label": CONFIG_LABEL[config],
        "n_usable_runways": n,
        "parallel_pairs": pairs,
        "min_parallel_separation_ft": min_sep,
        "max_parallel_separation_ft": max_sep,
        "primary_pair_separation_ft": primary["separation_ft"] if primary else None,
        "independent_ifr_approaches": (has_independent_pair if pairs else None),
        "imc_constrained": imc_constrained,
        "imc_note": imc_note,
        "asv": asv,
        "asv_source": "runway_config",
        "asv_caveat": (
            "ASV derived from runway configuration using representative "
            "placeholder values, NOT transcribed from FAA AC 150/5060-5. "
            "Replace with published FAA capacity profiles before relying on it."
        ),
    }


def _bearing_deg(lat1, lon1, lat2, lon2) -> float:
    lat1, lon1 = math.radians(lat1), math.radians(lon1)
    lat2, lon2 = math.radians(lat2), math.radians(lon2)
    dl = lon2 - lon1
    y = math.sin(dl) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
