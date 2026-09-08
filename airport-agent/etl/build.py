"""Build data/airports.db from source data.

Idempotent: running it twice produces the same database. Structural data
(airports, coordinates, runway geometry, regions) is always REAL, pulled from
OurAirports. Traffic is real BTS T-100 if an export is present, otherwise a
clearly-flagged synthetic gravity model.

    python3 -m etl.build [--refresh] [--years 5]
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
import os
import random
import sqlite3
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api import config
from api.scoring.normalize import cagr, safe_div
from api.scoring.spill import spill_estimate
from etl.capacity import classify
from etl.traffic import load_t100_segments

OURAIRPORTS = {
    "airports.csv": "https://davidmegginson.github.io/ourairports-data/airports.csv",
    "runways.csv": "https://davidmegginson.github.io/ourairports-data/runways.csv",
}

US_COMMERCIAL_TYPES = ("large_airport", "medium_airport", "small_airport")

# A destination counts as "served" at roughly weekly frequency or better.
WEEKLY_SERVICE_DEPARTURES = 45
HUB_CLASS_BY_TYPE = {"large_airport": "L", "medium_airport": "M", "small_airport": "S"}


# --------------------------------------------------------------------------
def fetch_raw(refresh: bool = False) -> None:
    os.makedirs(config.RAW_DIR, exist_ok=True)
    for name, url in OURAIRPORTS.items():
        dest = os.path.join(config.RAW_DIR, name)
        if os.path.exists(dest) and not refresh:
            print(f"  [cached] {name} ({os.path.getsize(dest):,} bytes)")
            continue
        print(f"  [fetch ] {name} <- {url}")
        try:
            urllib.request.urlretrieve(url, dest)
            print(f"           {os.path.getsize(dest):,} bytes")
        except Exception as exc:                       # noqa: BLE001
            if os.path.exists(dest):
                print(f"           download failed ({exc}); using cached copy")
            else:
                raise SystemExit(
                    f"Cannot download {name} and no cached copy exists: {exc}"
                )


def load_airports() -> tuple[list[dict], list[dict]]:
    """Return (us_commercial_origins, international_destination_pool)."""
    path = os.path.join(config.RAW_DIR, "airports.csv")
    origins, intl = [], []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["scheduled_service"] != "yes":
                continue
            try:
                lat, lon = float(r["latitude_deg"]), float(r["longitude_deg"])
            except (TypeError, ValueError):
                continue
            code = (r["iata_code"] or "").strip().upper()
            rec = {
                "code": code or r["ident"],
                "ident": r["ident"],
                "name": r["name"],
                "city": r["municipality"],
                "country": r["iso_country"],
                "iso_region": r["iso_region"],
                "state": (r["iso_region"].split("-")[1]
                          if r["iso_region"].startswith("US-") else None),
                "lat": lat, "lon": lon,
                "continent": r["continent"] or "",
                "type": r["type"],
                "wikipedia": r["wikipedia_link"],
            }
            if r["iso_country"] == "US" and r["type"] in US_COMMERCIAL_TYPES and code:
                origins.append(rec)
            elif r["iso_country"] != "US" and r["type"] == "large_airport" and code:
                intl.append(rec)
    return origins, intl


def load_runways() -> dict[str, list[dict]]:
    path = os.path.join(config.RAW_DIR, "runways.csv")
    out = collections.defaultdict(list)
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["closed"] == "1":
                continue
            out[r["airport_ident"]].append(r)
    return out


def attach_runway_stats(airports: list[dict], runways: dict) -> None:
    """Attach real runway count / total pavement to each airport record.

    The synthetic traffic model uses these as its size proxy, so that airport
    scale is anchored to observable infrastructure rather than a random draw.
    """
    for a in airports:
        rs = runways.get(a["ident"], [])
        lengths = []
        for r in rs:
            try:
                v = int(float(r.get("length_ft") or 0))
            except (TypeError, ValueError):
                continue
            if v >= 3000:
                lengths.append(v)
        a["n_runways"] = len(lengths)
        a["total_runway_ft"] = sum(lengths)


def load_curated(name: str) -> dict[str, dict]:
    path = os.path.join(config.CURATED_DIR, name)
    if not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["code"].strip().upper(): r for r in csv.DictReader(fh)}


# --------------------------------------------------------------------------
def find_t100_files() -> list[str]:
    """Every real T-100 export we have, oldest first."""
    if not os.path.isdir(config.RAW_DIR):
        return []
    out = []
    for name in sorted(os.listdir(config.RAW_DIR)):
        if name.startswith("t100_segment") and name.endswith(".csv"):
            out.append(os.path.join(config.RAW_DIR, name))
    return out


def build_routes(origins, intl_pool):
    """Aggregate real T-100 segments to route-year rows.

    There is no fallback. If the export is missing the build stops, because an
    airport investment tool that quietly invents traffic is worse than one that
    refuses to start.
    """
    files = find_t100_files()
    if not files:
        raise SystemExit(
            "\n  No T-100 data found in data/raw/.\n\n"
            "  This tool runs on real BTS traffic data and has no synthetic mode.\n"
            "  Get it with:\n\n"
            "      python3 -m etl.fetch_t100 --years 2019,2023,2024\n\n"
            "  Or by hand: transtats.bts.gov -> Aviation -> Air Carriers ->\n"
            "  'T-100 Segment (All Carriers)', then save the CSV as\n"
            "  data/raw/t100_segment_<year>.csv\n")

    us_codes = {o["code"] for o in origins}
    acc = collections.defaultdict(
        lambda: {"departures": 0.0, "seats": 0.0, "passengers": 0.0, "distance_nmi": 0.0}
    )
    kept = skipped = 0
    for path in files:
        print(f"  [traffic] {os.path.basename(path)}")
        for seg in load_t100_segments(path):
            if seg["origin"] not in us_codes:
                skipped += 1
                continue
            k = (seg["origin"], seg["dest"], seg["year"])
            a = acc[k]
            a["departures"] += seg["departures"]
            a["seats"] += seg["seats"]
            a["passengers"] += seg["passengers"]
            if seg["distance_nmi"]:
                a["distance_nmi"] = seg["distance_nmi"]
            kept += 1
    print(f"  {kept:,} segment rows kept, {skipped:,} outside the US airport set")

    country = {a["code"]: a["country"] for a in origins + intl_pool}
    continent = {a["code"]: a.get("continent", "") for a in origins + intl_pool}
    rows = []
    for (o, d, y), v in acc.items():
        rows.append({
            "origin": o, "dest": d, "year": y,
            "departures": round(v["departures"], 2),
            "seats": round(v["seats"], 1),
            "passengers": round(v["passengers"], 1),
            "distance_nmi": round(v["distance_nmi"], 1),
            "international": 0 if country.get(d, "US") == "US" else 1,
            "dest_country": country.get(d, ""),
            "dest_continent": continent.get(d, ""),
        })
    return rows, "real"


def operational_metrics() -> dict:
    """Delay and peaking metrics.

    These need BTS On-Time Performance, which is a separate export and is not
    loaded. An earlier version generated them from the demand/capacity ratio,
    which both invented data and quietly made the saturation pillar correlate
    with itself. They are now reported as missing, which lowers the confidence
    score honestly rather than filling the gap with a plausible number.
    """
    return {
        "peaking": None,
        "taxi_out_p50": None,
        "del15_rate": None,
        "cancel_rate": None,
        "operational_source": "not loaded (needs BTS On-Time Performance)",
    }


def build_marts(origins, routes, runways, curated_slots, curated_cons, mode):
    by_origin = collections.defaultdict(list)
    for r in routes:
        by_origin[r["origin"]].append(r)

    years = sorted({r["year"] for r in routes})
    if not years:
        raise SystemExit("no route data produced")
    latest, earliest = years[-1], years[0]
    span = max(1, latest - earliest)

    rw = runways
    out = []
    for a in origins:
        rs = by_origin.get(a["code"], [])
        if not rs:
            continue
        cur = [r for r in rs if r["year"] == latest]
        if not cur:
            continue

        deps = sum(r["departures"] for r in cur)
        seats = sum(r["seats"] for r in cur)
        pax = sum(r["passengers"] for r in cur)
        if deps <= 0 or seats <= 0:
            continue

        lh_deps = sum(r["departures"] for r in cur
                      if r["distance_nmi"] >= config.LONG_HAUL_NMI)
        intl_deps = sum(r["departures"] for r in cur if r["international"])
        intl_pax = sum(r["passengers"] for r in cur if r["international"])

        cap = classify(rw.get(a["ident"], []))
        ops = 2.0 * deps
        dc_ratio = safe_div(ops, cap["asv"])

        # growth + upgauge from the multi-year series (genuinely computed)
        first = [r for r in rs if r["year"] == earliest]
        pax0 = sum(r["passengers"] for r in first) or None
        deps0 = sum(r["departures"] for r in first) or None
        seats0 = sum(r["seats"] for r in first) or None
        gauge0 = safe_div(seats0, deps0)
        gauge1 = safe_div(seats, deps)
        # With a single year loaded there is no growth to measure. Computing a
        # rate from one year against itself yields exactly 0.0%, which reads as
        # "flat" when the truth is "unknown" -- so report nothing instead.
        multi_year = latest != earliest
        cagr_pax = cagr(pax0, pax, span) if multi_year else None
        cagr_deps = cagr(deps0, deps, span) if multi_year else None
        cagr_gauge = cagr(gauge0, gauge1, span) if multi_year else None
        upgauge = (cagr_gauge - cagr_deps) if (cagr_gauge is not None and cagr_deps is not None) else None

        # Where does the long-haul flying actually go? This is what lets the
        # agent say "it is a Pacific gateway" instead of quoting a percentage.
        CONTINENT_NAMES = {"AS": "Asia", "EU": "Europe", "SA": "South America",
                           "OC": "Oceania", "AF": "Africa", "NA": "North America"}
        gw = collections.Counter()
        for rte in cur:
            if rte["international"] and rte["distance_nmi"] >= config.LONG_HAUL_NMI:
                name = CONTINENT_NAMES.get(rte.get("dest_continent") or "", None)
                if name and name != "North America":
                    gw[name] += rte["departures"]
        gw_total = sum(gw.values())
        gateways = [{"region": k, "share": round(v / gw_total, 3), "departures": round(v)}
                    for k, v in gw.most_common(3)] if gw_total else []

        sp = spill_estimate(pax, seats)
        ops_metrics = operational_metrics()

        cons = curated_cons.get(a["code"], {})
        slot = curated_slots.get(a["code"], {})
        feas = None
        if cons.get("feasibility"):
            try:
                feas = float(cons["feasibility"])
            except ValueError:
                feas = None
        if feas is None:
            # Default prior by airport size: bigger airports are, on average,
            # more built-out and harder to expand. Flagged as a default.
            feas = {"large_airport": 0.55, "medium_airport": 0.75,
                    "small_airport": 0.8}.get(a["type"], 0.7)
            feas_source = "default_by_type"
        else:
            feas_source = "curated"

        out.append({
            "code": a["code"], "ident": a["ident"], "name": a["name"],
            "city": a["city"], "state": a["state"], "iso_region": a["iso_region"],
            "lat": a["lat"], "lon": a["lon"], "type": a["type"],
            "hub_class": HUB_CLASS_BY_TYPE.get(a["type"], "N"),
            "wikipedia": a["wikipedia"],
            "window_year": latest, "years_covered": span + 1,
            "pax": round(pax), "seats": round(seats), "deps": round(deps),
            "ops": round(ops),
            "slf": round(pax / seats, 4),
            "gauge": round(gauge1, 1) if gauge1 else None,
            # Destinations with at least weekly service. Counting every DEST in
            # T-100 includes one-off charters and diversions, which inflates a
            # regional airport's network to look like a hub's.
            "n_destinations": len({r["dest"] for r in cur
                                   if r["departures"] >= WEEKLY_SERVICE_DEPARTURES}),
            "n_destinations_any": len({r["dest"] for r in cur}),
            "lh_share": round(lh_deps / deps, 4),
            "lh_departures": round(lh_deps),
            "intl_share": round(intl_deps / deps, 4),
            "intl_pax": round(intl_pax),
            "gateways": json.dumps(gateways),
            "asv": cap["asv"], "asv_source": cap["asv_source"],
            "asv_caveat": cap["asv_caveat"],
            "runway_config": cap["config"], "runway_config_label": cap["config_label"],
            "n_runways": cap["n_usable_runways"],
            "max_parallel_separation_ft": cap["max_parallel_separation_ft"],
            "independent_ifr_approaches": (
                None if cap["independent_ifr_approaches"] is None
                else int(cap["independent_ifr_approaches"])),
            "imc_constrained": int(cap["imc_constrained"]),
            "imc_note": cap["imc_note"],
            "dc_ratio": round(dc_ratio, 4) if dc_ratio else None,
            "cagr_pax_5y": round(cagr_pax, 5) if cagr_pax is not None else None,
            "cagr_deps_3y": round(cagr_deps, 5) if cagr_deps is not None else None,
            "cagr_gauge_3y": round(cagr_gauge, 5) if cagr_gauge is not None else None,
            "upgauge_delta": round(upgauge, 5) if upgauge is not None else None,
            "spill_rate": sp["spill_rate"],
            "spill_passengers": sp["spill_passengers"],
            "unconstrained_demand": sp["unconstrained_demand"],
            "taf_cagr": None,          # requires FAA TAF import
            "catchment_gap": None,     # requires Census import
            "slot_level": int(slot["iata_level"]) if slot.get("iata_level") else None,
            "slot_note": slot.get("note"),
            "feasibility": feas, "feasibility_source": feas_source,
            "constraint_fact": cons.get("fact"),
            "constraint_judgment": cons.get("judgment_note"),
            "constraint_source": cons.get("source"),
            "curfew": int(cons["curfew"]) if cons.get("curfew") else 0,
            "pax_cap": int(cons["pax_cap"]) if cons.get("pax_cap") else 0,
            "land_locked": int(cons["land_locked"]) if cons.get("land_locked") else 0,
            "data_mode": mode,
            **ops_metrics,
        })
    return out


# --------------------------------------------------------------------------
def write_db(marts, routes, meta):
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    if os.path.exists(config.DB_PATH):
        os.remove(config.DB_PATH)
    con = sqlite3.connect(config.DB_PATH)
    cur = con.cursor()

    cols = list(marts[0].keys())
    coldef = ", ".join(f'"{c}"' for c in cols)
    cur.execute(f"CREATE TABLE mart_airport_annual ({coldef})")
    cur.executemany(
        f"INSERT INTO mart_airport_annual VALUES ({','.join('?' * len(cols))})",
        [tuple(m[c] for c in cols) for m in marts],
    )
    cur.execute("CREATE UNIQUE INDEX idx_mart_code ON mart_airport_annual(code)")
    cur.execute("CREATE INDEX idx_mart_state ON mart_airport_annual(state)")

    cur.execute("""CREATE TABLE fact_route_annual
        (origin TEXT, dest TEXT, year INT, departures REAL, seats REAL,
         passengers REAL, distance_nmi REAL, international INT,
         dest_country TEXT, dest_continent TEXT)""")
    cur.executemany(
        "INSERT INTO fact_route_annual VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(r["origin"], r["dest"], r["year"], r["departures"], r["seats"],
          r["passengers"], r["distance_nmi"], r["international"],
          r["dest_country"], r["dest_continent"]) for r in routes],
    )
    cur.execute("CREATE INDEX idx_route_origin ON fact_route_annual(origin, year)")

    cur.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    cur.executemany("INSERT INTO meta VALUES (?,?)",
                    [(k, json.dumps(v)) for k, v in meta.items()])
    con.commit()
    con.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download source data")
    ap.add_argument("--years", type=int, default=5)
    args = ap.parse_args()

    print("1/5 source data")
    fetch_raw(args.refresh)

    print("2/5 airports + runways")
    origins, intl_pool = load_airports()
    runways = load_runways()
    attach_runway_stats(origins + intl_pool, runways)
    print(f"  {len(origins)} US commercial airports, {len(intl_pool)} international destinations")

    print("3/5 traffic")
    routes, mode = build_routes(origins, intl_pool)
    years = sorted({r["year"] for r in routes})
    print(f"  {len(routes):,} route-year rows from {len(years)} year(s): {years}")

    print("4/5 marts")
    marts = build_marts(origins, routes, runways,
                        load_curated("slot_levels.csv"),
                        load_curated("constraints.csv"), mode)
    print(f"  {len(marts)} airports scored-ready")

    print("5/5 write")
    meta = {
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "data_mode": mode,
        "years": years,
        "window_year": years[-1],
        "n_airports": len(marts),
        "n_routes": len(routes),
        "long_haul_nmi": config.LONG_HAUL_NMI,
        "structural_source": "OurAirports (real)",
        "traffic_source": "BTS T-100 Segment (All Carriers), real",
        "operational_source": "not loaded (needs BTS On-Time Performance)",
    }
    write_db(marts, routes, meta)
    print(f"\nwrote {config.DB_PATH} ({os.path.getsize(config.DB_PATH):,} bytes)")
    print(f"\n  All traffic is real BTS T-100 data ({', '.join(map(str, years))}).")
    if len(years) < 2:
        print("  Only one year loaded, so growth rates are unavailable and reported")
        print("  as unknown. Add more:  python3 -m etl.fetch_t100 --years 2019,2023")


if __name__ == "__main__":
    main()
