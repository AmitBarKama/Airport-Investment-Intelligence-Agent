# Deliverable 2a — Scoring Methodology

*Required by the assignment: "a short design/architecture document explaining:
**scoring methodology**".*

---

## 0. The one-paragraph version

Each airport gets five pillar scores in (0,1]. Relative quantities (traffic,
delay, growth) are **winsorised and percentile-ranked** within a cohort;
absolute judgments (slot level, feasibility) stay on their own 0–1 scale. The
five are combined with a **weighted geometric mean**, which prevents a strong
pillar from buying off a fatal one. The resulting 0–100 score is reported
*alongside*, never instead of, an **FAA capacity tier** derived from the
regulator's own published planning triggers. Every score carries a **confidence
score** built from data coverage, capacity-source quality and recency, and a
**400-draw weight sensitivity** run says how fragile the ranking is.

---

## 1. Why an airport is worth expanding — the investment thesis

Renovation pays off when **suppressed demand is released against a facility
that can physically absorb it, in a market that pays for the seats.** That
sentence decomposes directly into five pillars:

| Pillar | The question it answers | Default weight |
|---|---|---:|
| **Saturation** | Is it already full? | 0.30 |
| **Unmet demand** | Is demand being turned away or legally capped? | 0.25 |
| **Growth** | Is the pressure increasing? | 0.20 |
| **Feasibility** | Can you actually build there? | 0.15 |
| **Monetization** | Does the traffic mix pay for it? | 0.10 |

Congestion alone is a trap. LaGuardia is the most congested airport in the US
and one of the worst places on earth to spend expansion capital — there is
nowhere to put anything. Pillar 4 exists to say so, and the aggregation method
(§4) exists to make it *decisive* rather than merely subtracted.

---

## 2. The pillars, indicator by indicator

### Pillar 1 — Saturation

| Indicator | Default mix | Status in this build |
|---|---:|---|
| `dc_ratio` — annual operations ÷ Annual Service Volume | 0.50 | ✅ present |
| `taxi_out_p50` — median taxi-out minutes | 0.25 | ❌ NULL — needs BTS On-Time Performance |
| `del15_rate` — share of departures >15 min late | 0.15 | ❌ NULL |
| `peaking` — peak-hour concentration | 0.10 | ❌ NULL |

Profiles re-mix these. The `terminal` profile weights `peaking` at **0.50**,
because terminals are sized off the design-day peak hour rather than annual
totals (FAA AC 150/5360-13A, ACRP Report 25) — which is correct methodology
that this build currently cannot feed. The consequence is measured and reported,
not hidden: terminal-profile confidence drops to **71%** coverage.

**Annual Service Volume** is the denominator, computed in `etl/capacity.py`
from runway configuration per FAA AC 150/5060-5 — number of runways, parallel
separation, and whether independent IFR approaches are possible. Where
separation is under ~4,300 ft, arrival capacity collapses in low visibility, so
effective ASV is discounted. In this build **all 624 airports** use the
`runway_config` estimate; none use a published FAA capacity profile, and the
confidence score docks every airport for it by name.

### Pillar 2 — Unmet demand

| Indicator | Weight | Basis |
|---|---:|---|
| Slot level | 0.30 | **Absolute.** Level 3 → 1.0, Level 2 → 0.6, Level 1 → 0.0 |
| Spill rate | 0.30 | Relative |
| Upgauge delta | 0.25 | Relative |
| Catchment gap | 0.15 | Relative |

**Slot control is a legal cap on demand, not a measurement**, so it is scored
absolutely — an airport does not become less slot-controlled because its peer
group changed.

**Spill** is the analytically interesting one. Observed traffic systematically
*understates* true demand wherever capacity binds — precisely the set of
airports an investor cares about. The build applies the standard airline
revenue-management identity (Belobaba, MIT 16.75J):

```
mean demand = mean observed load + mean spill
```

With demand `D ~ Normal(μ, σ)`, `σ = K·μ` (K = 0.35 from the literature), and
capacity `S` seats, expected spill is the upper-tail partial expectation:

```
E[(D − S)⁺] = σ · ( φ(z) − z·(1 − Φ(z)) ),    z = (S − μ)/σ
```

Observed load `L(μ) = μ − E[(D−S)⁺]` is strictly increasing in μ, so the model
inverts it **by bisection** to recover unconstrained demand from the passengers
actually observed. An airport at 92% load factor is not "8% empty"; it is
turning people away in the peaks.

The module states its own limitations rather than burying them: applying a
per-departure construct to annual aggregates averages away the peaks where
spill happens, so these estimates are **conservative**; the normal distribution
fits the extreme tail poorly; and K is imported from the literature, not
estimated from this data.

**Upgauging** — average aircraft size growing faster than departures — is a
classic revealed symptom of capacity constraint. When an airline cannot add
flights, it adds seats per flight. SFO shows **+5.15%/yr**.

### Pillar 3 — Growth

Historic passenger CAGR (0.50) + FAA Terminal Area Forecast CAGR (0.50).
**The TAF half is NULL for every airport in this build**, so growth is
backward-looking only. Coverage reports 50% for this pillar.

### Pillar 4 — Feasibility

**Absolute, and the only openly subjective pillar.** It answers: given the
site, the law and the neighbours, can capacity actually be added?

Curated from published filings for **21 airports**, each row carrying a fact, a
judgment and a source URL — LGA 0.08 (land-constrained, perimeter rule, slot
controls), DCA 0.10, SNA 0.12 (1985 Newport Beach settlement: passenger cap,
departure cap, curfew through 2035), BOS 0.35 (peninsular site), DEN 0.95.

The other **603 airports** receive a size-based prior — large 0.55, medium
0.75, small 0.80 — flagged as `default_by_type`. This is the build's largest
soft spot.

### Pillar 5 — Monetization

International share (0.40) + long-haul share (0.30) + average gauge (0.20) +
destination count (0.10). Long-haul and international traffic drive
higher-value terminal real estate, customs and lounge revenue, and larger
aircraft per movement.

---

## 3. Normalisation

Method follows the **OECD / EC-JRC Handbook on Constructing Composite
Indicators (2008)**:

1. **Winsorise** to the 5th–95th percentile band. Outliers are *clamped, not
   dropped*: Atlanta should not be discarded, but it should not flatten every
   other airport's normalised position either.
2. **Percentile-rank** within the cohort, using the **midrank** convention so a
   block of identical values does not get an arbitrary ordering.
3. **Floor at 0.01.** The composite is geometric, so a true zero would
   annihilate the score. The floor keeps a worst-in-class pillar severe but not
   fatal.

Relative and absolute indicators are deliberately mixed, and every pillar
returns a `basis` field saying which it is — `"relative (percentile within
cohort)"` vs `"absolute (curated analyst judgment)"` — because a reader who does
not know which they are looking at cannot interpret the number.

> **Known consequence.** Percentile ranking is done against the **national
> cohort of 624 airports**, most of which are small. PWM sits at 11% of its ASV
> — genuinely uncongested — yet lands in the **87th percentile** of saturation.
> The FAA tier catches this correctly (Tier D, "no capacity case"), but the
> composite score does not.

---

## 4. Aggregation — why geometric, not arithmetic

```
Score = 100 × Π ( pillar_i ^ w_i )
```

implemented in log space and renormalised by the weight actually used, so an
airport with a missing pillar is not penalised twice (once by the gap, once by
a shrunken exponent sum).

**This is the single most consequential choice in the methodology.** A
geometric mean is *partially non-compensatory*: a near-zero pillar drags the
whole score down and cannot be bought off by strength elsewhere.

Concretely — compare two airports under the default `investment` weights.
Airport A is maximally congested, supply-constrained, fast-growing and highly
monetisable, but **unbuildable** (feasibility 0.08 — LaGuardia's actual curated
value). Airport B is moderately constrained but has room to build (feasibility
0.95 — Denver's actual value):

| | pillars | arithmetic | geometric |
|---|---|---:|---:|
| **A** "LaGuardia-like" | sat 0.95 · unmet 0.95 · growth 0.90 · **feas 0.08** · monet 0.90 | **80.5** | **64.5** |
| **B** "Denver-like" | sat 0.70 · unmet 0.60 · growth 0.75 · **feas 0.95** · monet 0.60 | **71.2** | **70.4** |

Note what happens: **the ranking reverses.** Under an arithmetic mean, A beats
B by nine points and tops the list — the model recommends pouring capital into
the one place it cannot be spent. Under a geometric mean, B wins. The
unbuildable site cannot buy its way to the top with congestion alone.

That is not a hypothetical: LGA's real demand/ASV in this database is **1.43** —
the most saturated airport in the cohort — against a curated feasibility of
**0.08**. `test_scoring.py` carries this as an explicit non-compensatory proof.

*(Figures computed directly from `geometric_score` with the default weights.)*

---

## 5. Tiering — the regulator's judgment, not mine

The score is *always* reported next to a tier taken from **FAA Advisory
Circular 150/5060-5 (Airport Capacity and Delay)**:

| Tier | demand/ASV | Label | FAA guidance |
|---|---|---|---|
| **A** | ≥ 0.80 | Build now | Construction of additional capacity should be underway |
| **B** | ≥ 0.60 | Plan now | Capacity planning should have started |
| **C** | ≥ 0.45 | Monitor | Approaching the 60% planning trigger |
| **D** | < 0.45 | No capacity case | Any case must rest on something other than airfield capacity |

Leading with the tier means leading with the regulator's published rule rather
than my weighting. It also gives the agent a way to **contradict its own
ranking** — which it did during the audit, reporting PWM as the top terminal
candidate and immediately noting that it sits in Tier D and therefore has no
airfield capacity case at all.

---

## 6. Profiles

One ranking cannot answer every question, so the build ships four and *names
the one it used* in every response.

| Profile | sat | unmet | growth | feas | monet | For |
|---|---:|---:|---:|---:|---:|---|
| `investment` *(default)* | 0.30 | 0.25 | 0.20 | 0.15 | 0.10 | Where capital pays off |
| `terminal` | 0.20 | 0.25 | 0.28 | 0.17 | 0.10 | Terminal expansion (peak-hour led) |
| `congestion` | 0.70 | 0.30 | — | — | — | Pure congestion comparison |
| `airfield` | 0.45 | 0.30 | 0.15 | 0.10 | — | Runway-side constraint |

`congestion` deliberately zeroes growth, feasibility and monetization: those are
investment questions, not congestion questions. Asking "compare LA and Santa
Ana congestion" should not silently import a view about buildability.

**Verified:** on New England, `congestion` tops with **BOS** and `terminal` tops
with **PWM** — the profiles genuinely separate.

Weights are overridable per request and renormalised to sum to 1.

---

## 7. Confidence

A deliberately blunt, fully inspectable score in [0,1]:

```
confidence = 0.50 × input_coverage
           + 0.20 × asv_source_quality      (published FAA profile 1.0 │ runway_config 0.5 │ peer regression 0.2)
           + 0.30 × recency                 (linear decay over 36 months)
```

An opaque confidence number would be worse than none at all, so the reasons are
returned in English. Actual output from this build:

> `only 71% of scoring inputs are backed by data` ·
> `capacity denominator is runway_config, not a published FAA profile` ·
> `data is about 27 months old`

**Coverage** is tracked per pillar by the blending function, which redistributes
weight away from missing inputs and reports the share of intended weight that
was actually backed by data. A blend built from half its inputs must not look as
solid as a full one.

Measured across profiles on New England: investment 0.56, terminal 0.53,
congestion 0.56, airfield 0.56 — all labelled **medium**. The system is not
claiming more than it has.

---

## 8. Sensitivity — how fragile is the ranking?

Weights are a judgment, so the build quantifies how much the answer depends on
them. `sensitivity_analysis` draws **400 Dirichlet-perturbed weight vectors**
around the profile centre (OECD/JRC uncertainty-analysis practice), re-ranks
under each, and reports median rank, p10–p90 rank band, P(top 1), P(top 3) and
a stability flag.

Actual output, New England / investment:

| Airport | median rank | p10–p90 | P(top 1) | stable |
|---|---:|---|---:|---|
| BGR | 1.5 | 1–3 | 0.50 | ✅ |
| PWM | 2.0 | 1–3 | 0.22 | ✅ |
| BDL | 3.0 | 1–5 | 0.28 | ❌ |

> "BGR ranks first in 50% of weight draws — the leader is likely but not certain
> under other weightings."

A ranking that reports its own instability is worth more to an investment
committee than a point estimate to one decimal place.

---

## 9. Assumptions the methodology rests on

| Assumption | Value | Why it is a choice, not a fact |
|---|---|---|
| Long haul | ≥ 2,500 nmi | **No ICAO/IATA standard exists.** Industry usage spans 2,200–2,600 nmi; ICAO and IATA define by flight *time* and disagree with each other. Configurable. |
| Annual operations | 2 × departures performed | T-100 reports departures; arrivals are assumed to match |
| Demand variability | K = 0.35 | Imported from MIT 16.75J, not estimated from this data |
| IMC capacity loss | 15% ASV discount | Applied where parallel separation < ~4,300 ft |
| Weekly service | ≥ 52 departures/yr to count a destination | Counting every T-100 destination includes charters and diversions, inflating a regional airport's network to look like a hub's |
| Scope | US commercial-service airports | Not general aviation, not non-US, not airline or equity analysis |

All are returned by `config.assumption_registry()` and attached to every
substantive answer.
