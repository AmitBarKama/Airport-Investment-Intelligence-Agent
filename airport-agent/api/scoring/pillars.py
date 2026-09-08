"""The five pillars of the investment score.

Each pillar is computed over a *cohort* (the set of airports being compared),
because normalisation is relative: "96th percentile of saturation among large
hubs" is meaningful, "0.82 saturation" is not.

Two kinds of indicator are deliberately mixed:
  * RELATIVE (percentile-ranked within the cohort): traffic, delay, growth --
    quantities where only the comparison carries meaning.
  * ABSOLUTE (already on a 0-1 judgment scale): slot level, feasibility --
    facts and analyst judgments that should not shift just because the peer
    group changed.
Mixing them is a choice, and it is documented in the returned `basis` field.
"""
from __future__ import annotations

from typing import Sequence

from .normalize import winsorized_percentile_rank
from .profiles import DEFAULT_SATURATION_MIX

# Slot control is a legal cap on demand, not a measurement -> absolute scale.
SLOT_SUPPRESSION = {3: 1.0, 2: 0.6, 1: 0.0}


def _col(rows: Sequence[dict], key: str) -> list:
    return [r.get(key) for r in rows]


def _blend(parts: dict[str, tuple[float | None, float]]) -> tuple[float | None, float]:
    """Weighted blend that redistributes weight away from missing inputs.

    Returns (value, coverage) where coverage is the share of intended weight
    that was actually backed by data. Coverage feeds the confidence score --
    a blend built from half its inputs should not look as solid as a full one.
    """
    num = 0.0
    used = 0.0
    total = 0.0
    for value, weight in parts.values():
        total += weight
        if value is not None:
            num += value * weight
            used += weight
    if used == 0 or total == 0:
        return None, 0.0
    return num / used, used / total


def compute_pillars(rows: Sequence[dict], saturation_mix: dict | None = None) -> list[dict]:
    """Compute all five pillars for a cohort.

    `rows` are per-airport metric dicts (see etl.build.mart_airport_annual).
    Returns one dict per airport, aligned with the input order.
    """
    mix = saturation_mix or DEFAULT_SATURATION_MIX
    n = len(rows)
    if n == 0:
        return []

    # --- relative indicators: percentile rank within this cohort -------------
    pct = {
        key: winsorized_percentile_rank(_col(rows, key))
        for key in (
            "dc_ratio", "taxi_out_p50", "del15_rate", "peaking",
            "spill_rate", "upgauge_delta", "catchment_gap",
            "cagr_pax_5y", "taf_cagr",
            "intl_share", "lh_share", "gauge", "n_destinations",
        )
    }

    out: list[dict] = []
    for i, r in enumerate(rows):
        # --- Pillar 1: Saturation -------------------------------------------
        saturation, sat_cov = _blend({
            "dc_ratio":     (pct["dc_ratio"][i],     mix.get("dc_ratio", 0.0)),
            "taxi_out_p50": (pct["taxi_out_p50"][i], mix.get("taxi_out_p50", 0.0)),
            "del15_rate":   (pct["del15_rate"][i],   mix.get("del15_rate", 0.0)),
            "peaking":      (pct["peaking"][i],      mix.get("peaking", 0.0)),
        })

        # --- Pillar 2: Unmet demand -----------------------------------------
        slot_level = r.get("slot_level")
        slot_signal = SLOT_SUPPRESSION.get(slot_level) if slot_level else 0.0
        unmet, unmet_cov = _blend({
            "slot":      (slot_signal,             0.30),
            "spill":     (pct["spill_rate"][i],    0.30),
            "upgauge":   (pct["upgauge_delta"][i], 0.25),
            "catchment": (pct["catchment_gap"][i], 0.15),
        })

        # --- Pillar 3: Growth ------------------------------------------------
        growth, growth_cov = _blend({
            "historic": (pct["cagr_pax_5y"][i], 0.50),
            "forecast": (pct["taf_cagr"][i],    0.50),
        })

        # --- Pillar 4: Feasibility (absolute analyst judgment) ---------------
        feas = r.get("feasibility")
        feas_cov = 1.0 if feas is not None else 0.0
        if feas is None:
            feas = 0.5  # neutral prior; flagged via coverage, not hidden

        # --- Pillar 5: Monetization ------------------------------------------
        monet, monet_cov = _blend({
            "intl":  (pct["intl_share"][i],     0.40),
            "lh":    (pct["lh_share"][i],       0.30),
            "gauge": (pct["gauge"][i],          0.20),
            "dests": (pct["n_destinations"][i], 0.10),
        })

        out.append({
            "code": r.get("code"),
            "saturation": saturation,
            "unmet_demand": unmet,
            "growth": growth,
            "feasibility": max(0.0, min(1.0, float(feas))),
            "monetization": monet,
            "coverage": {
                "saturation": round(sat_cov, 3),
                "unmet_demand": round(unmet_cov, 3),
                "growth": round(growth_cov, 3),
                "feasibility": round(feas_cov, 3),
                "monetization": round(monet_cov, 3),
            },
            "basis": {
                "saturation": "relative (percentile within cohort)",
                "unmet_demand": "mixed: slot level absolute, others relative",
                "growth": "relative",
                "feasibility": "absolute (curated analyst judgment)",
                "monetization": "relative",
            },
            "inputs": {
                "dc_ratio": r.get("dc_ratio"),
                "taxi_out_p50": r.get("taxi_out_p50"),
                "del15_rate": r.get("del15_rate"),
                "peaking": r.get("peaking"),
                "slot_level": slot_level,
                "spill_rate": r.get("spill_rate"),
                "upgauge_delta": r.get("upgauge_delta"),
                "cagr_pax_5y": r.get("cagr_pax_5y"),
                "taf_cagr": r.get("taf_cagr"),
                "intl_share": r.get("intl_share"),
                "lh_share": r.get("lh_share"),
            },
        })
    return out
