"""The deterministic tool layer.

Every number the user ever sees is produced here, in Python, from the
database. The language model selects tools and narrates their output; it never
computes, estimates, or recalls a figure. That is what makes numeric
hallucination structurally impossible rather than merely discouraged.

Conventions every tool follows:
  * return `assumptions`, `data_vintage` and (where meaningful) `confidence`
    alongside the data, so provenance travels WITH the number and the model
    cannot quote a figure without its caveat also being in context;
  * return DENOMINATORS, not just ratios -- "142 of 1,183 departures" is
    checkable, "12%" is not;
  * return `null` plus a reason for missing data, never a plausible guess.
"""
from __future__ import annotations

import datetime as dt
import json

from .. import config, db, websearch
from ..scoring.composite import (assign_tier, pillar_contributions,
                                 score_cohort)
from ..scoring.pillars import compute_pillars
from ..scoring.profiles import PROFILES, resolve_weights
from ..scoring.sensitivity import rank_stability
from ..scoring.spill import spill_estimate


def _vintage() -> dict:
    m = db.meta()
    return {
        "window_year": m.get("window_year"),
        "years_covered": m.get("years"),
        "data_mode": m.get("data_mode"),
        "structural_source": m.get("structural_source"),
        "traffic_source": m.get("traffic_source"),
        "operational_source": m.get("operational_source"),
        "built_at": m.get("built_at"),
        "warning": (
            "TRAFFIC VOLUMES ARE SYNTHETIC. Airports, coordinates, runway "
            "geometry and route distances are real; passenger and flight "
            "volumes are modelled. Do not present these figures as measured."
            if m.get("data_mode") == "synthetic" else None
        ),
    }


def _vintage_age_months() -> float | None:
    m = db.meta()
    wy = m.get("window_year")
    if not wy:
        return None
    return max(0.0, (dt.date.today().year - int(wy)) * 12 + dt.date.today().month - 6)


# Source attribution shown as pills under each answer. Honest about the
# synthetic layer: if traffic volumes are modelled, the pill says so rather
# than implying BTS provided them.
_SOURCE_DEFS = {
    "OurAirports": {"label": "OurAirports", "detail": "Airport locations, regions and runway geometry",
                    "url": "https://davidmegginson.github.io/ourairports-data/"},
    "BTS": {"label": "BTS T-100", "detail": "Air carrier traffic: passengers, seats, departures",
            "url": "https://www.transtats.bts.gov/"},
    "SYNTHETIC": {"label": "Synthetic traffic", "detail":
                  "Passenger and flight volumes are MODELLED, not measured. "
                  "Structure, geography and runway geometry are real.", "url": None},
    "FAA_AC": {"label": "FAA AC 150/5060-5", "detail":
               "Airport Capacity and Delay: plan capacity at 60% of Annual Service Volume, build at 80%",
               "url": "https://www.faa.gov/documentlibrary/media/advisory_circular/150_5060_5.pdf"},
    "FAA_SLOTS": {"label": "FAA Slot Administration", "detail":
                  "IATA Level 2 / Level 3 airport designations",
                  "url": "https://www.faa.gov/about/office_org/headquarters_offices/ato/service_units/systemops/perf_analysis/slot_administration"},
    "SPILL": {"label": "MIT 16.75J", "detail":
              "Airline spill model (Belobaba): mean demand = observed load + spill",
              "url": "https://ocw.mit.edu/courses/16-75j-airline-management-spring-2006/f990b2cd2141f75cd9b348051af762e7_lect4b.pdf"},
    "OECD": {"label": "OECD/JRC", "detail":
             "Handbook on Constructing Composite Indicators: normalisation, weighting, sensitivity",
             "url": "https://www.oecd.org/en/publications/handbook-on-constructing-composite-indicators_533411815016.html"},
    "WEB": {"label": "Web", "detail":
            "Third-party reporting of announced plans. Qualitative context only; "
            "never an input to any score.", "url": None, "class": "external"},
    "CURATED": {"label": "Airport filings", "detail":
                "Curated constraints: settlement agreements, curfews, perimeter rules", "url": None},
}


def _sources(*keys: str) -> list[dict]:
    """Build the source pill list, always disclosing the traffic layer."""
    keys = list(keys)
    if db.meta().get("data_mode") == "synthetic":
        keys = ["SYNTHETIC" if k == "BTS" else k for k in keys]
    seen, out = set(), []
    for k in keys:
        if k in _SOURCE_DEFS and k not in seen:
            seen.add(k)
            out.append({"key": k, **_SOURCE_DEFS[k]})
    return out


def _gateways(m: dict) -> list[dict]:
    """Which world regions this airport's long-haul flying actually serves."""
    try:
        return json.loads(m.get("gateways") or "[]")
    except (TypeError, ValueError):
        return []


def _err(msg: str, **extra) -> dict:
    return {"error": msg, **extra}


# ---------------------------------------------------------------------------
def list_airports(region: str | None = None, states: list[str] | None = None,
                  metro: str | None = None, codes: list[str] | None = None,
                  hub_class: str | None = None, min_pax: float | None = None,
                  limit: int = 40) -> dict:
    """Find candidate airports by region, metro area, state or code."""
    resolved_region = None
    region_note = None
    if region:
        st, label, confidence = db.resolve_region_scored(region)
        if st is None:
            import difflib as _dl
            return _err(f"Unknown region {region!r}.",
                        known_regions=sorted(config.REGIONS),
                        did_you_mean=_dl.get_close_matches(
                            region.lower(), list(config.REGIONS), n=3, cutoff=0.6))
        states, resolved_region = st, label
        # Say how the words were read. Compass words like "the east" are
        # colloquial groupings covering a lot of ground, not Census regions,
        # and the user should be able to see the reading and correct it.
        if confidence != "exact" or len(st) > 6:
            region_note = (f"I read \u201c{region.strip()}\u201d as {label}: "
                           f"{len(st)} states, {', '.join(st[:8])}"
                           f"{', ...' if len(st) > 8 else ''}")
    resolved_metro = None
    if metro:
        mc, label = db.resolve_metro(metro)
        if mc is None:
            return _err(f"Unknown metro area {metro!r}.",
                        known_metros=sorted(config.METRO_GROUPS))
        codes, resolved_metro = mc, label

    rows = db.list_airports(states=states, codes=codes, hub_class=hub_class,
                            min_pax=min_pax, limit=limit)
    return {
        "count": len(rows),
        "airports": [{
            "code": r["code"], "name": r["name"], "city": r["city"],
            "state": r["state"], "hub_class": r["hub_class"],
            "passengers": r["pax"], "departures": r["deps"],
            "dc_ratio": r["dc_ratio"], "n_runways": r["n_runways"],
        } for r in rows],
        "sources": _sources("OurAirports", "BTS"),
        "filters_applied": {
            "region": resolved_region, "region_note": region_note,
            "region_states": states if resolved_region else None,
            "metro": resolved_metro,
            "states": states, "codes": codes, "hub_class": hub_class,
            "min_passengers": min_pax,
        },
        "assumptions": {
            **config.assumption_registry(),
            "selection": ("US commercial-service airports with scheduled "
                          "service, as classified by OurAirports."),
        },
        "data_vintage": _vintage(),
    }


# ---------------------------------------------------------------------------
def rank_airports(region: str | None = None, states: list[str] | None = None,
                  metro: str | None = None, codes: list[str] | None = None,
                  profile: str = "investment", weights: dict | None = None,
                  hub_class: str | None = None, top_n: int = 10,
                  peer_normalise: bool = True) -> dict:
    """Rank airports by investment attractiveness under a scoring profile."""
    sel = list_airports(region=region, states=states, metro=metro, codes=codes,
                        hub_class=hub_class, limit=500)
    if "error" in sel:
        return sel
    wanted = [a["code"] for a in sel["airports"]]
    if not wanted:
        return _err("No airports matched those filters.",
                    filters=sel.get("filters_applied"))

    try:
        w, meta = resolve_weights(profile, weights)
    except (KeyError, ValueError) as exc:
        return _err(str(exc), available_profiles=sorted(PROFILES))

    # Normalise against the full national cohort (or the hub-class peer group)
    # rather than only the selected airports: a New England airport's
    # percentile should not change just because we filtered the list.
    cohort = db.list_airports(limit=1000)
    if peer_normalise and hub_class:
        cohort = [c for c in cohort if c["hub_class"] == hub_class]

    pillars = compute_pillars(cohort, meta.get("saturation_mix"))
    scored = score_cohort(cohort, pillars, w, _vintage_age_months())

    by_code = {s["code"]: s for s in scored}
    picked = [by_code[c] for c in wanted if c in by_code]
    picked.sort(key=lambda r: r["score"], reverse=True)
    for i, r in enumerate(picked, 1):
        r["rank_in_selection"] = i

    return {
        "profile": profile,
        "profile_label": meta["label"],
        "profile_description": meta["description"],
        "weights": {k: round(v, 4) for k, v in w.items()},
        "normalised_against": (
            f"{len(cohort)} US commercial airports"
            + (f" in hub class {hub_class}" if hub_class else " (national cohort)")),
        "count": len(picked),
        "results": [{
            "rank": r["rank_in_selection"], "code": r["code"], "name": r["name"],
            "city": r["city"], "state": r["state"],
            "score": r["score"], "tier": r["tier"], "tier_label": r["tier_label"],
            "tier_rationale": r["tier_rationale"],
            "pillars": r["pillars"], "confidence": r["confidence"],
            "key_metrics": {
                "passengers": r["metrics"]["pax"],
                "departures": r["metrics"]["deps"],
                "load_factor": r["metrics"]["slf"],
                "dc_ratio": r["metrics"]["dc_ratio"],
                "asv": r["metrics"]["asv"],
                "asv_source": r["metrics"]["asv_source"],
                "n_runways": r["metrics"]["n_runways"],
                "slot_level": r["metrics"]["slot_level"],
                "feasibility": r["metrics"]["feasibility"],
                "feasibility_source": r["metrics"]["feasibility_source"],
                "constraint": r["metrics"]["constraint_fact"],
                # everything the investment case is argued from
                "growth": r["metrics"]["cagr_pax_5y"],
                "spill_rate": r["metrics"]["spill_rate"],
                "spill_passengers": r["metrics"]["spill_passengers"],
                "intl_share": r["metrics"]["intl_share"],
                "long_haul_share": r["metrics"]["lh_share"],
                "destinations": r["metrics"]["n_destinations"],
                "gateways": _gateways(r["metrics"]),
                "imc_constrained": bool(r["metrics"]["imc_constrained"]),
                "curfew": bool(r["metrics"]["curfew"]),
                "passenger_cap": bool(r["metrics"]["pax_cap"]),
                "land_locked": bool(r["metrics"]["land_locked"]),
                "judgment": r["metrics"]["constraint_judgment"],
            },
        } for r in picked[:top_n]],
        "filters_applied": sel["filters_applied"],
        "sources": _sources("BTS", "OurAirports", "FAA_AC", "FAA_SLOTS", "OECD"),
        "assumptions": {
            **config.assumption_registry(),
            "aggregation": (
                "Weighted GEOMETRIC mean of five pillars. Geometric rather than "
                "arithmetic so a near-zero pillar (for example, an airport that "
                "physically cannot be expanded) drags the whole score down and "
                "cannot be offset by strength elsewhere."),
            "normalisation": (
                "Indicators are winsorised at the 5th/95th percentile then "
                "converted to percentile rank within the cohort."),
        },
        "data_vintage": _vintage(),
    }


# ---------------------------------------------------------------------------
def airport_profile(code: str) -> dict:
    """Full KPI sheet for one airport."""
    cands = db.resolve_airport(code)
    if not cands:
        return _err(f"No US commercial airport matches {code!r}.")
    if cands[0]["code"] != code.strip().upper() and len(cands) > 1:
        return {
            "ambiguous": True,
            "query": code,
            "candidates": [{"code": c["code"], "name": c["name"],
                            "city": c["city"], "state": c["state"]}
                           for c in cands],
            "message": "Multiple airports match. Ask the user which one.",
        }
    a = db.get_airport(cands[0]["code"])
    if not a:
        return _err(f"No data for {code!r}.")

    tier = assign_tier(a["dc_ratio"])
    return {
        "code": a["code"], "name": a["name"], "city": a["city"],
        "state": a["state"], "hub_class": a["hub_class"],
        "traffic": {
            "passengers": a["pax"], "seats": a["seats"],
            "departures": a["deps"], "annual_operations_est": a["ops"],
            "load_factor": a["slf"], "avg_seats_per_departure": a["gauge"],
            "n_destinations": a["n_destinations"],
            "long_haul_share": a["lh_share"],
            "international_share": a["intl_share"],
            "gateways": _gateways(a),
        },
        "capacity": {
            "annual_service_volume": a["asv"], "asv_source": a["asv_source"],
            "asv_caveat": a["asv_caveat"],
            "demand_capacity_ratio": a["dc_ratio"],
            "tier": tier["tier"], "tier_label": tier["label"],
            "tier_rationale": tier["rationale"],
            "runway_config": a["runway_config_label"],
            "n_runways": a["n_runways"],
            "widest_parallel_separation_ft": a["max_parallel_separation_ft"],
            "independent_ifr_approaches": (
                None if a["independent_ifr_approaches"] is None
                else bool(a["independent_ifr_approaches"])),
            "imc_constrained": bool(a["imc_constrained"]),
            "imc_note": a["imc_note"],
        },
        "operations": {
            "median_taxi_out_min": a["taxi_out_p50"],
            "pct_departures_delayed_15min": a["del15_rate"],
            "cancellation_rate": a["cancel_rate"],
            "peaking_factor": a["peaking"],
            "source": a["operational_source"],
        },
        "growth": {
            "passenger_cagr": a["cagr_pax_5y"],
            "departures_cagr": a["cagr_deps_3y"],
            "gauge_cagr": a["cagr_gauge_3y"],
            "upgauge_delta": a["upgauge_delta"],
            "faa_taf_cagr": a["taf_cagr"],
            "note": ("FAA Terminal Area Forecast not loaded; growth uses "
                     "historical trend only." if a["taf_cagr"] is None else None),
        },
        "constraints": {
            "slot_level": a["slot_level"], "slot_note": a["slot_note"],
            "curfew": bool(a["curfew"]), "passenger_cap": bool(a["pax_cap"]),
            "land_locked": bool(a["land_locked"]),
            "feasibility": a["feasibility"],
            "feasibility_source": a["feasibility_source"],
            "fact": a["constraint_fact"],
            "analyst_judgment": a["constraint_judgment"],
            "source": a["constraint_source"],
        },
        "sources": _sources("BTS", "OurAirports", "FAA_AC", "FAA_SLOTS", "CURATED"),
        "assumptions": config.assumption_registry(),
        "data_vintage": _vintage(),
    }


# ---------------------------------------------------------------------------
def flight_mix(code: str, dimension: str = "haul",
               long_haul_nmi: float | None = None) -> dict:
    """Distribution of departures by haul length, region or destination."""
    cands = db.resolve_airport(code)
    if not cands:
        return _err(f"No US commercial airport matches {code!r}.")
    a = db.get_airport(cands[0]["code"])
    if not a:
        return _err(f"No data for {code!r}.")
    rows = db.routes(a["code"])
    if not rows:
        return _err(f"No route data for {a['code']}.")

    threshold = float(long_haul_nmi or config.LONG_HAUL_NMI)
    total = sum(r["departures"] for r in rows)
    total_pax = sum(r["passengers"] for r in rows)

    if dimension == "haul":
        buckets = {
            "short_haul": (0, config.SHORT_HAUL_NMI),
            "medium_haul": (config.SHORT_HAUL_NMI, threshold),
            "long_haul": (threshold, float("inf")),
        }
        dist = {}
        for name, (lo, hi) in buckets.items():
            sel = [r for r in rows if lo <= r["distance_nmi"] < hi]
            d = sum(r["departures"] for r in sel)
            dist[name] = {
                "departures": round(d),
                "share_of_departures": round(d / total, 4) if total else None,
                "passengers": round(sum(r["passengers"] for r in sel)),
                "routes": len(sel),
                "range_nmi": [lo, None if hi == float("inf") else hi],
            }
        headline = {
            "long_haul_departures": dist["long_haul"]["departures"],
            "total_departures": round(total),
            "long_haul_share": dist["long_haul"]["share_of_departures"],
            "stated_as": (f"{dist['long_haul']['departures']:,} of "
                          f"{round(total):,} departures "
                          f"({(dist['long_haul']['share_of_departures'] or 0):.1%})"),
        }
        # Sensitivity to the threshold, because the threshold is a judgment call.
        alt = {}
        for t in (2200, 2500, 3000):
            d = sum(r["departures"] for r in rows if r["distance_nmi"] >= t)
            alt[f"{t}_nmi"] = round(d / total, 4) if total else None
    elif dimension == "international":
        intl = [r for r in rows if r["international"]]
        dom = [r for r in rows if not r["international"]]
        dist = {
            "international": {"departures": round(sum(r["departures"] for r in intl)),
                              "routes": len(intl)},
            "domestic": {"departures": round(sum(r["departures"] for r in dom)),
                         "routes": len(dom)},
        }
        headline = {"international_share": a["intl_share"]}
        alt = {}
    elif dimension == "destination":
        top = sorted(rows, key=lambda r: -r["departures"])[:20]
        dist = {r["dest"]: {"departures": round(r["departures"]),
                            "distance_nmi": r["distance_nmi"],
                            "international": bool(r["international"])} for r in top}
        headline = {"n_destinations": len(rows)}
        alt = {}
    else:
        return _err(f"Unknown dimension {dimension!r}.",
                    valid=["haul", "international", "destination"])

    return {
        "code": a["code"], "name": a["name"], "dimension": dimension,
        "headline": headline, "distribution": dist,
        "share_at_alternative_thresholds": alt,
        "sources": _sources("BTS", "OurAirports"),
        "totals": {"departures": round(total), "passengers": round(total_pax)},
        "assumptions": {
            **config.assumption_registry(),
            "long_haul_threshold_nmi": threshold,
            "cargo": ("Only scheduled passenger service is counted. All-cargo "
                      "operations are excluded. This matters most at cargo "
                      "hubs such as Anchorage, where including freighters "
                      "would change the long-haul share substantially."),
        },
        "data_vintage": _vintage(),
    }


# ---------------------------------------------------------------------------
def unmet_demand(code: str) -> dict:
    """Estimate suppressed demand and explain what is driving it."""
    cands = db.resolve_airport(code)
    if not cands:
        return _err(f"No US commercial airport matches {code!r}.")
    a = db.get_airport(cands[0]["code"])
    if not a:
        return _err(f"No data for {code!r}.")

    sp = spill_estimate(a["pax"], a["seats"])
    drivers, measured, inferred, unknown = [], {}, [], []

    measured["load_factor"] = a["slf"]
    measured["median_taxi_out_min"] = a["taxi_out_p50"]
    measured["demand_capacity_ratio"] = a["dc_ratio"]
    measured["upgauge_delta"] = a["upgauge_delta"]

    if a["slot_level"]:
        drivers.append({
            "driver": "Administrative suppression",
            "detail": (f"IATA Level {a['slot_level']} airport. "
                       f"{(a['slot_note'] or '').rstrip('. ')}. "
                       "Scheduling is constrained by rule, so the traffic we observe is "
                       "a capped number, not what the market would have produced."),
            "type": "measured",
        })
    if sp["spill_rate"]:
        drivers.append({
            "driver": "Spill (load-factor based)",
            "detail": (f"At a {a['slf']:.1%} seat load factor, the normal spill "
                       f"model implies roughly {sp['spill_passengers']:,} "
                       f"passengers turned away, about {sp['spill_rate']:.1%} of "
                       f"estimated unconstrained demand."),
            "type": "inferred",
        })
        inferred.append("spill estimate depends on an assumed demand variability K")
    if a["upgauge_delta"] and a["upgauge_delta"] > 0.002:
        drivers.append({
            "driver": "Upgauging",
            "detail": (f"Average aircraft size is growing {a['upgauge_delta']:.2%} "
                       "per year faster than departures. Airlines adding seats "
                       "with bigger aircraft rather than more flights is the "
                       "classic symptom of a slot- or gate-constrained airport."),
            "type": "measured",
        })
    if a["imc_constrained"]:
        drivers.append({
            "driver": "Runway geometry / weather",
            "detail": a["imc_note"],
            "type": "measured",
        })
    if a["pax_cap"] or a["curfew"]:
        drivers.append({
            "driver": "Legal cap or curfew",
            "detail": a["constraint_fact"],
            "type": "measured",
        })

    unknown.append(
        "How much suppressed demand would actually materialise if capacity "
        "existed. That requires fare and origin-destination data (BTS DB1B), "
        "which is not loaded.")
    if a["taf_cagr"] is None:
        unknown.append("Forward demand: FAA Terminal Area Forecast not loaded.")

    return {
        "code": a["code"], "name": a["name"],
        "spill": sp,
        "drivers": drivers,
        "measured": measured,
        "inference_caveats": inferred,
        "unknown": unknown,
        "epistemic_note": (
            "Load factor, taxi-out, slot level and runway geometry are "
            "MEASURED. That the airport turns away demand is INFERRED from "
            "them. How much of that demand would convert is UNKNOWN."),
        "sources": _sources("BTS", "SPILL", "FAA_SLOTS", "OurAirports", "CURATED"),
        "assumptions": config.assumption_registry(),
        "data_vintage": _vintage(),
    }


# ---------------------------------------------------------------------------
def compare_airports(codes: list[str], metrics: list[str] | None = None) -> dict:
    """Side-by-side comparison with a per-metric verdict."""
    if not codes or len(codes) < 2:
        return _err("Provide at least two airport codes to compare.")
    resolved, unresolved = [], []
    for c in codes:
        cand = db.resolve_airport(c)
        if cand:
            resolved.append(cand[0]["code"])
        else:
            unresolved.append(c)
    rows = [db.get_airport(c) for c in resolved]
    rows = [r for r in rows if r]
    if len(rows) < 2:
        return _err("Could not resolve enough airports.", unresolved=unresolved)

    default_metrics = ["dc_ratio", "slf", "taxi_out_p50", "del15_rate",
                       "peaking", "spill_rate", "slot_level", "pax", "deps"]
    metrics = metrics or default_metrics
    # (label, direction, display format) -- formatting lives here so every
    # surface renders the same number the same way.
    labels = {
        "dc_ratio": ("Demand / Annual Service Volume", "higher", "ratio"),
        "slf": ("Seat load factor", "higher", "pct"),
        "taxi_out_p50": ("Median taxi-out", "higher", "min"),
        "del15_rate": ("Departures delayed >15 min", "higher", "pct"),
        "peaking": ("Peak-hour concentration", "higher", "ratio"),
        "spill_rate": ("Estimated spill rate", "higher", "pct"),
        "slot_level": ("IATA slot level", "higher", "level"),
        "pax": ("Passengers", "higher", "int"),
        "deps": ("Departures", "higher", "int"),
    }

    def fmt(v, kind):
        if v is None:
            return None
        if kind == "pct":
            return f"{v * 100:.1f}%"
        if kind == "int":
            return f"{round(v):,}"
        if kind == "min":
            return f"{v:.1f} min"
        if kind == "level":
            return f"Level {int(v)}"
        return f"{v:.2f}"

    table = []
    for m in metrics:
        label, direction, kind = labels.get(m, (m, "higher", "ratio"))
        vals = {r["code"]: r.get(m) for r in rows}
        present = {k: v for k, v in vals.items() if v is not None}
        leader = max(present, key=present.get) if present else None
        table.append({
            "metric": m, "label": label, "values": vals,
            "display": {k: fmt(v, kind) for k, v in vals.items()},
            "more_congested": leader,
            "note": None if present else "no data for any selected airport",
        })

    return {
        "airports": [{"code": r["code"], "name": r["name"], "city": r["city"],
                      "state": r["state"], "tier": assign_tier(r["dc_ratio"])["tier"],
                      "constraint": r["constraint_fact"],
                      "slot_level": r["slot_level"],
                      "curfew": bool(r["curfew"]),
                      "passenger_cap": bool(r["pax_cap"])} for r in rows],
        "comparison": table,
        "unresolved": unresolved,
        "sources": _sources("BTS", "FAA_AC", "FAA_SLOTS", "CURATED"),
        "interpretation_warning": (
            "A low congestion reading does not always mean spare demand. An "
            "airport operating under a legal passenger cap or curfew is "
            "DEMAND-constrained by agreement, not capacity-constrained by "
            "physics, and the two have opposite investment implications."),
        "assumptions": config.assumption_registry(),
        "data_vintage": _vintage(),
    }


# ---------------------------------------------------------------------------
def explain_score(code: str, profile: str = "investment",
                  weights: dict | None = None) -> dict:
    """Break a score into per-pillar contributions."""
    cand = db.resolve_airport(code)
    if not cand:
        return _err(f"No US commercial airport matches {code!r}.")
    target = cand[0]["code"]
    try:
        w, meta = resolve_weights(profile, weights)
    except (KeyError, ValueError) as exc:
        return _err(str(exc), available_profiles=sorted(PROFILES))

    cohort = db.list_airports(limit=1000)
    pillars = compute_pillars(cohort, meta.get("saturation_mix"))
    scored = score_cohort(cohort, pillars, w, _vintage_age_months())
    row = next((s for s in scored if s["code"] == target), None)
    if row is None:
        return _err(f"{target} not in the scored cohort.")
    praw = next(p for p in pillars if p["code"] == target)

    contribs = pillar_contributions(row["pillars"], w)
    drags = [c for c in contribs if c["drag"]]
    return {
        "code": target, "name": row["name"],
        "profile": profile, "profile_label": meta["label"],
        "weights": {k: round(v, 4) for k, v in w.items()},
        "score": row["score"],
        "rank_national": row["rank"],
        "cohort_size": len(cohort),
        "tier": row["tier"], "tier_label": row["tier_label"],
        "tier_rationale": row["tier_rationale"],
        "contributions": contribs,
        "dragging_pillars": [c["pillar"] for c in drags],
        "pillar_inputs": praw["inputs"],
        "pillar_basis": praw["basis"],
        "coverage": praw["coverage"],
        "confidence": row["confidence"],
        "sources": _sources("BTS", "FAA_AC", "OECD"),
        "how_to_read": (
            "The composite is a weighted GEOMETRIC mean, so contributions are "
            "multiplicative, not additive. 'share_of_shortfall' is each "
            "pillar's share of the gap between this score and a perfect one, "
            "computed in log space where the terms do add up."),
        "assumptions": config.assumption_registry(),
        "data_vintage": _vintage(),
    }


# ---------------------------------------------------------------------------
def sensitivity_analysis(codes: list[str] | None = None,
                         region: str | None = None,
                         profile: str = "investment",
                         n_draws: int = 400) -> dict:
    """How stable is the ranking if the weights change?"""
    try:
        w, meta = resolve_weights(profile, None)
    except (KeyError, ValueError) as exc:
        return _err(str(exc), available_profiles=sorted(PROFILES))

    if region:
        st, _ = db.resolve_region(region)
        if st is None:
            return _err(f"Unknown region {region!r}.")
        sel = db.list_airports(states=st, limit=200)
    elif codes:
        resolved = [db.resolve_airport(c)[0]["code"]
                    for c in codes if db.resolve_airport(c)]
        sel = db.list_airports(codes=resolved, limit=200)
    else:
        sel = db.list_airports(limit=25)
    if len(sel) < 2:
        return _err("Need at least two airports for a stability analysis.")

    pillars = compute_pillars(sel, meta.get("saturation_mix"))
    scored = score_cohort(sel, pillars, w, _vintage_age_months())
    stab = rank_stability(scored, w, n_draws=n_draws)

    ordered = sorted(stab["per_airport"].items(),
                     key=lambda kv: kv[1]["median_rank"])
    return {
        "profile": profile, "base_weights": {k: round(v, 4) for k, v in w.items()},
        "n_draws": n_draws,
        "headline": stab["headline"],
        "method": stab["method"],
        "sources": _sources("OECD", "BTS"),
        "airports": [{
            "code": c, "median_rank": b["median_rank"],
            "rank_band_p10_p90": [b["p10_rank"], b["p90_rank"]],
            "p_top1": b["p_top1"], "p_top3": b["p_top3"], "stable": b["stable"],
        } for c, b in ordered],
        "assumptions": {
            **config.assumption_registry(),
            "sensitivity": ("Weights resampled from a Dirichlet distribution "
                            "centred on the profile weights. Per the OECD/JRC "
                            "composite-indicator handbook, the defensible claim "
                            "is not that the weights are right, but that the "
                            "conclusion survives reasonable changes to them."),
        },
        "data_vintage": _vintage(),
    }


def capital_programmes(code: str, max_results: int = 5) -> dict:
    """What has this airport announced it will build?

    Deliberately separate from everything that produces a number. Announced
    plans are statements of intent, not capacity: an airport can announce a
    terminal and never build it. So this returns cited third-party claims and
    is excluded from scoring by construction, not by convention.

    Falls back to the curated constraints file when no search key is set, so
    the answer degrades to today's behaviour rather than to nothing.
    """
    cands = db.resolve_airport(code)
    if not cands:
        return _err(f"No US commercial airport matches {code!r}.")
    a = db.get_airport(cands[0]["code"])
    if not a:
        return _err(f"No data for {code!r}.")

    # Query is built here, from a template. The user's raw text never reaches
    # the search provider: that bounds both scope and injection surface.
    query = (f"{a['name']} ({a['code']}) terminal expansion OR capital improvement "
             f"program OR master plan OR concourse")
    res = websearch.search(query, max_results)

    return {
        "code": a["code"], "name": a["name"],
        "query_used": query,
        "provider": res.get("provider"),
        "findings": res.get("findings") or [],
        "unavailable": res.get("unavailable"),
        "curated_fallback": a.get("constraint_fact"),
        "curated_source": a.get("constraint_source"),
        "evidence_class": "third_party_reported",
        "excluded_from_scoring": True,
        "sources": _sources("CURATED") + (
            [{"key": "WEB", **_SOURCE_DEFS["WEB"]}] if res.get("findings") else []),
        "assumptions": {
            **config.assumption_registry(),
            "web": ("Announced plans are statements of intent, not delivered "
                    "capacity, and are not used in any score or ranking."),
        },
        "data_vintage": _vintage(),
    }


def web_research(question: str, code: str | None = None,
                 max_results: int = 5) -> dict:
    """Look up something on the web that the loaded data cannot answer.

    `capital_programmes` deliberately never lets the user's text reach the
    search provider, because its query is a fixed template. Here a free-form
    question IS the point, so the containment moves rather than disappears:
    the query is scoped to an airport or to US airports generally, it is capped
    in length, the result is tagged `third_party_reported` and
    `excluded_from_scoring`, and `api/scoring/*` cannot import this module at
    all -- asserted by walking the import graph in tests. Web findings are
    quotable, citable evidence. They are never an input to a number.
    """
    q = " ".join((question or "").split())[:200]
    if not q:
        return _err("Give me something to research.")

    airport, scope = None, "US airport capacity and expansion"
    if code:
        cands = db.resolve_airport(code)
        if not cands:
            return _err(f"No US commercial airport matches {code!r}.")
        airport = db.get_airport(cands[0]["code"])
        if airport:
            scope = f"{airport['name']} ({airport['code']}) airport"

    query = f"{scope} {q}"
    res = websearch.search(query, max_results)

    return {
        "question": q,
        "code": (airport or {}).get("code"),
        "query_used": query,
        "provider": res.get("provider"),
        "findings": res.get("findings") or [],
        "unavailable": res.get("unavailable"),
        "evidence_class": "third_party_reported",
        "excluded_from_scoring": True,
        "sources": [{"key": "WEB", **_SOURCE_DEFS["WEB"]}] if res.get("findings") else [],
        "assumptions": {
            **config.assumption_registry(),
            "web": ("Web findings are third-party claims. They are cited so they can "
                    "be checked, and are never used in any score or ranking."),
        },
        "data_vintage": _vintage(),
    }


TOOLS = {
    "list_airports": list_airports,
    "capital_programmes": capital_programmes,
    "web_research": web_research,
    "rank_airports": rank_airports,
    "airport_profile": airport_profile,
    "flight_mix": flight_mix,
    "unmet_demand": unmet_demand,
    "compare_airports": compare_airports,
    "explain_score": explain_score,
    "sensitivity_analysis": sensitivity_analysis,
}
