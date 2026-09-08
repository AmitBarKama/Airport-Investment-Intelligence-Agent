"""Traffic data: real BTS T-100 when available, synthetic gravity model otherwise.

REAL PATH (preferred)
---------------------
`load_t100_segments()` reads a BTS T-100 Segment CSV export and emits rows in
the canonical segment shape. T-100 is the backbone dataset: every nonstop
segment flown by US and foreign carriers, monthly, at carrier x origin x dest
x aircraft grain, giving passengers, seats, departures and distance.

Get it from https://www.transtats.bts.gov/ (Air Carrier Statistics -> T-100
Segment). Drop the CSV at data/raw/t100_segment.csv and re-run the ETL.

There is no synthetic fallback. An earlier version modelled traffic with a
gravity model when the real export was missing; it was clearly labelled, but
labelled invented numbers are still invented numbers, and they invite exactly
the misreading they warn about. If the real data is absent the ETL now stops
and says so.
"""
from __future__ import annotations

import csv
import hashlib
import math
import os
import random
from typing import Iterable, Iterator

NM_PER_KM = 0.539957
EARTH_R_KM = 6371.0

# Airport "mass" for the gravity model, by OurAirports type.
TYPE_MASS = {"large_airport": 1.0, "medium_airport": 0.16, "small_airport": 0.03}

# Distance decay. Higher beta -> shorter-haul network.
#
# Real networks are not one uniform decay: large hubs are long-haul gateways
# and reach much further than regional fields, which fly short thin routes.
# A single global beta produced a network where no major airport had ANY
# long-haul flying, which is obviously wrong. So decay flattens with airport
# mass: BETA_SMALL for a regional field, BETA_LARGE for a major hub.
GRAVITY_BETA = 1.05
BETA_SMALL = 1.18
BETA_LARGE = 0.72

# Calibration target: the largest US hubs perform roughly 300-400k departures
# a year. DEPARTURE_SCALE is tuned so the synthetic network lands in that
# range rather than producing demand/capacity ratios above 1.0, which are
# physically impossible to sustain.
DEPARTURE_SCALE = 15_000

# How steeply traffic scales with runway pavement. Tuned so that the busiest
# hubs land near 300k annual departures while regional fields land in the tens
# of thousands -- roughly the real spread.
INFRA_EXPONENT = 1.6

# Seats per departure by haul length, roughly matching real fleet assignment:
# regional jets on short thin routes, widebodies on long ones.
def _gauge_for_distance(nmi: float, rng: random.Random) -> int:
    if nmi < 300:
        base = rng.choice([50, 70, 76, 100])
    elif nmi < 900:
        base = rng.choice([76, 143, 150, 172])
    elif nmi < 2000:
        base = rng.choice([150, 172, 178, 186])
    elif nmi < 3000:
        base = rng.choice([178, 186, 199, 236])
    else:
        base = rng.choice([236, 254, 276, 296, 350])
    return base


def great_circle_nmi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(min(1.0, math.sqrt(a))) * NM_PER_KM


def _seed_for(code: str) -> int:
    return int(hashlib.sha256(code.encode()).hexdigest()[:8], 16)


# --------------------------------------------------------------------------
# Real T-100
# --------------------------------------------------------------------------

# BTS T-100 service class codes. F/L are scheduled passenger service; G, P, R
# and friends are all-cargo. Mixing them is the single most common way to get
# a wrong answer out of this dataset -- it is why Anchorage's "long-haul share"
# becomes a freighter statistic if you are not careful.
PASSENGER_SERVICE_CLASSES = {"F", "L"}
ALL_CARGO_SERVICE_CLASSES = {"G", "P", "R"}


def load_t100_segments(path: str,
                       passenger_only: bool = True) -> Iterator[dict]:
    """Stream a BTS T-100 Segment CSV into canonical segment rows.

    Column names follow the BTS export (case-insensitive match). Verify the
    service-class code meanings against the current BTS data dictionary before
    relying on the passenger/cargo split.
    """
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        field_map = {k.lower().strip(): k for k in (reader.fieldnames or [])}

        def col(row, *names, default=None):
            for n in names:
                key = field_map.get(n.lower())
                if key is not None and row.get(key) not in (None, ""):
                    return row[key]
            return default

        for row in reader:
            svc = (col(row, "CLASS", "SERVICE_CLASS") or "").strip().upper()
            if passenger_only and svc and svc not in PASSENGER_SERVICE_CLASSES:
                continue
            try:
                deps = float(col(row, "DEPARTURES_PERFORMED", default=0) or 0)
                seats = float(col(row, "SEATS", default=0) or 0)
                pax = float(col(row, "PASSENGERS", default=0) or 0)
                dist_mi = float(col(row, "DISTANCE", default=0) or 0)
            except ValueError:
                continue
            if deps <= 0:
                continue
            yield {
                "year": int(float(col(row, "YEAR", default=0) or 0)),
                "month": int(float(col(row, "MONTH", default=0) or 0)),
                "origin": (col(row, "ORIGIN", default="") or "").strip().upper(),
                "dest": (col(row, "DEST", default="") or "").strip().upper(),
                "carrier": (col(row, "UNIQUE_CARRIER", "CARRIER", default="") or "").strip(),
                "service_class": svc,
                "departures": deps,
                "seats": seats,
                "passengers": pax,
                "distance_nmi": dist_mi * 0.868976,  # statute miles -> nautical
                "data_mode": "real",
            }
