"""Airline spill model: estimating demand that capacity turned away.

Rationale
---------
Observed traffic systematically *understates* true demand wherever capacity
binds -- which is precisely the set of airports an investor cares about. The
standard identity from airline revenue management (Belobaba, MIT 16.75J) is:

    mean demand = mean observed load + mean spill

So an airport running at 92% load factor is not "8% empty"; it is turning
people away in the peaks. This module recovers an estimate of unconstrained
demand from observed load.

Model
-----
Demand D ~ Normal(mu, sigma) with sigma = K * mu (K is the demand coefficient
of variation; the MIT notes use K ~ 0.35 for unconstrained demand). With
capacity S seats and z = (S - mu) / sigma, expected spill is the standard
partial-expectation of the upper tail:

    E[(D - S)+] = sigma * ( phi(z) - z * (1 - Phi(z)) )

Observed load is L(mu) = mu - E[(D - S)+], which is strictly increasing in mu,
so we invert it by bisection to recover mu from the passengers we actually see.

Known limitations -- stated, not hidden
---------------------------------------
* Applying this to *annual airport aggregates* is a simplification. The model
  is properly a per-departure (or per-route-month) construct; aggregating
  first averages away the peaks where spill actually happens, so airport-level
  estimates here are CONSERVATIVE (they understate true spill). Applying it
  per segment-month and summing is the more correct approach and is what the
  ETL does when segment data is available.
* The normal distribution is a poor fit in the extreme upper tail; gamma or
  log-normal are common alternatives.
* K is imported from the literature, not estimated from this data.
"""
from __future__ import annotations

import math

DEFAULT_K = 0.35  # demand coefficient of variation (MIT 16.75J convention)


def _phi(z: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


def _Phi(z: float) -> float:
    """Standard normal CDF, via the stdlib error function."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def expected_spill(mu: float, sigma: float, capacity: float) -> float:
    """E[(D - S)+] for D ~ Normal(mu, sigma). Passengers turned away."""
    if sigma <= 0:
        return max(0.0, mu - capacity)
    z = (capacity - mu) / sigma
    return sigma * (_phi(z) - z * (1.0 - _Phi(z)))


def expected_load(mu: float, sigma: float, capacity: float) -> float:
    """E[min(D, S)] -- the traffic an observer actually records."""
    return mu - expected_spill(mu, sigma, capacity)


def solve_unconstrained_demand(observed_pax: float, seats: float,
                               k: float = DEFAULT_K,
                               tol: float = 1e-6,
                               max_iter: int = 200) -> float:
    """Invert the load function to recover unconstrained demand mu.

    Bisection on a monotone function; returns mu >= observed_pax.
    """
    if observed_pax <= 0 or seats <= 0:
        return max(0.0, observed_pax)

    def load_at(mu: float) -> float:
        return expected_load(mu, k * mu, seats)

    lo = observed_pax
    hi = max(observed_pax * 3.0, seats * 3.0)
    # Expand the bracket until the model can actually produce the observed load
    guard = 0
    while load_at(hi) < observed_pax and guard < 60:
        hi *= 1.5
        guard += 1

    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        if load_at(mid) < observed_pax:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol * max(1.0, observed_pax):
            break
    return 0.5 * (lo + hi)


def spill_estimate(observed_pax: float, seats: float,
                   k: float = DEFAULT_K) -> dict:
    """Full spill result for one airport/route aggregate.

    Returns the pieces separately so the agent can quote the inputs alongside
    the conclusion rather than presenting a bare number.
    """
    if not observed_pax or not seats or observed_pax <= 0 or seats <= 0:
        return {
            "observed_pax": observed_pax,
            "seats": seats,
            "load_factor": None,
            "unconstrained_demand": None,
            "spill_passengers": None,
            "spill_rate": None,
            "k_assumption": k,
            "note": "insufficient data",
        }

    mu = solve_unconstrained_demand(observed_pax, seats, k)
    spill = max(0.0, mu - observed_pax)
    return {
        "observed_pax": round(observed_pax),
        "seats": round(seats),
        "load_factor": round(observed_pax / seats, 4),
        "unconstrained_demand": round(mu),
        "spill_passengers": round(spill),
        "spill_rate": round(spill / mu, 4) if mu > 0 else None,
        "k_assumption": k,
        "note": ("Normal spill model with K={:.2f}. Applied to aggregate "
                 "traffic, so it understates true spill: peak-period spill "
                 "is averaged away.").format(k),
    }
