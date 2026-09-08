"""Normalisation utilities for the composite indicator.

Method follows the OECD/EC-JRC *Handbook on Constructing Composite Indicators*
(2008): winsorise to blunt outliers, then convert to percentile rank so that
indicators on wildly different scales become comparable and interpretable.

Everything here is a pure function over plain Python floats. No numpy, so the
whole scoring path runs on a bare interpreter and is trivially unit-testable.
"""
from __future__ import annotations

from typing import Iterable, Sequence


def winsorize(values: Sequence[float], lower_pct: float = 5.0,
              upper_pct: float = 95.0) -> list[float]:
    """Clamp values into the [lower_pct, upper_pct] percentile band.

    Outliers are clamped rather than dropped: ATL should not be discarded, but
    it also should not flatten every other airport's normalised position.
    """
    clean = [v for v in values if v is not None]
    if not clean:
        return list(values)
    lo = percentile(clean, lower_pct)
    hi = percentile(clean, upper_pct)
    return [None if v is None else min(max(v, lo), hi) for v in values]


def percentile(values: Sequence[float], pct: float) -> float:
    """Linear-interpolation percentile (same convention as numpy's default)."""
    clean = sorted(v for v in values if v is not None)
    if not clean:
        raise ValueError("percentile of empty sequence")
    if len(clean) == 1:
        return float(clean[0])
    k = (len(clean) - 1) * (pct / 100.0)
    lo_i, hi_i = int(k), min(int(k) + 1, len(clean) - 1)
    frac = k - lo_i
    return float(clean[lo_i] * (1 - frac) + clean[hi_i] * frac)


def percentile_rank(values: Sequence[float], floor: float = 0.01) -> list[float]:
    """Map each value to its percentile rank in (0, 1].

    Uses the midrank convention (ties share the average of their positions) so
    that a block of identical values does not get an arbitrary ordering.

    `floor` keeps results strictly positive. The composite uses a *geometric*
    mean, so a genuine zero on any pillar would annihilate the whole score;
    the floor keeps a worst-in-class pillar severe but not fatal.
    """
    n = len(values)
    if n == 0:
        return []
    present = [(v, i) for i, v in enumerate(values) if v is not None]
    if not present:
        return [None] * n
    if len(present) == 1:
        out = [None] * n
        out[present[0][1]] = 1.0
        return out

    out: list[float | None] = [None] * n
    vals = [v for v, _ in present]
    for v, i in present:
        less = sum(1 for x in vals if x < v)
        equal = sum(1 for x in vals if x == v)
        # midrank: count everything strictly below, plus half of the ties
        raw = (less + 0.5 * equal) / len(vals)
        out[i] = max(floor, min(1.0, raw))
    return out


def winsorized_percentile_rank(values: Sequence[float], lower_pct: float = 5.0,
                               upper_pct: float = 95.0,
                               floor: float = 0.01) -> list[float]:
    """The normalisation actually used by the pillars: winsorise, then rank."""
    return percentile_rank(winsorize(values, lower_pct, upper_pct), floor=floor)


def invert(values: Iterable[float]) -> list[float]:
    """Flip an already-normalised (0,1] series so that 'more' becomes 'less'."""
    return [None if v is None else (1.0 - v) for v in values]


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def safe_div(num: float | None, den: float | None) -> float | None:
    """Division that returns None instead of raising or inventing a value.

    Missing data must stay missing: silently substituting 0 here would create
    plausible-looking figures that never existed, which is the exact failure
    mode the whole design is trying to prevent.
    """
    if num is None or den in (None, 0):
        return None
    return num / den


def cagr(first: float | None, last: float | None, years: float) -> float | None:
    """Compound annual growth rate. None when it is not defined."""
    if first is None or last is None or years <= 0:
        return None
    if first <= 0 or last <= 0:
        return None
    return (last / first) ** (1.0 / years) - 1.0
