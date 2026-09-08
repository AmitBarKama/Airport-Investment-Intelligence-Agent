# 02 — Scoring methodology

> Design rule: **every number the user sees is produced by a Python function, never by the language model.** The LLM chooses which function to call and explains the result. Nothing else.

## 1. The published standards this is anchored to

Don't invent thresholds. Borrow the regulator's. This is the highest-leverage move in the whole assignment.

### FAA AC 150/5060-5 — *Airport Capacity and Delay* ⭐ the load-bearing citation
Defines **Annual Service Volume (ASV)**: the annual level of operations at which average delay per aircraft sits at roughly **2.3–3.5 minutes**. And it gives planning trigger points:

| Demand ÷ ASV | FAA guidance |
|---|---|
| **≥ 0.60** | Begin **planning** for additional airfield capacity |
| **≥ 0.80** | Begin **construction** of additional capacity |

That is a federally published, defensible, deterministic rule — and it maps *exactly* onto "which airports are candidates for expansion." Use it as your primary tiering, not a made-up 0–100 cutoff.
→ `https://www.faa.gov/documentlibrary/media/advisory_circular/150_5060_5.pdf`

### FAA FACT (Future Airport Capacity Task) reports
The FAA's own methodology for identifying which airports will need capacity, from macro trends in congestion and delay. FACT3 analysed 48 airports and projected which would be constrained by 2030. **Mirror its structure**: analyse a defined candidate set, project forward, tier by need.
→ `https://www.faa.gov/sites/faa.gov/files/airports/resources/publications/reports/FACT3-Airport-Capacity-Needs-in-the-NAS.pdf`

### OECD / EC-JRC *Handbook on Constructing Composite Indicators* (2008)
The canonical reference for exactly the thing you are building: turning many indicators into one defensible index. Its ten steps — theoretical framework → data selection → imputation → multivariate analysis → **normalisation** → **weighting** → **aggregation** → **uncertainty & sensitivity analysis** → back to the data → visualisation. Following a named methodology beats hand-waving.
→ `https://www.oecd.org/content/dam/oecd/en/publications/reports/2008/08/handbook-on-constructing-composite-indicators-methodology-and-user-guide_g1gh9301/9789264043466-en.pdf`

### Airline spill models (Belobaba / MIT 16.75J; Boeing spill model)
The rigorous treatment of *unmet* demand. Core identity:

> **mean demand = mean observed load + mean spill**

Observed traffic *understates* true demand whenever capacity binds. That single sentence justifies the whole "unmet demand" pillar — and it's why ranking on raw passenger counts is wrong at exactly the airports you care about.
→ `https://ocw.mit.edu/courses/16-75j-airline-management-spring-2006/f990b2cd2141f75cd9b348051af762e7_lect4b.pdf`

### FAA AC 150/5360-13A — *Airport Terminal Planning* & ACRP Report 25
Terminal facilities are sized off the **design-day peak hour**, not annual totals. Justifies using peak-hour passengers rather than enplanements for the *terminal* question.

---

## 2. Metric definitions

All from a rolling 12-month window unless noted. Per airport `a`:

```
PAX      = Σ passengers            (T-100 segment, departures from a, passenger service classes)
SEATS    = Σ seats
DEPS     = Σ departures_performed
OPS      ≈ 2 × DEPS                 # departures + arrivals
SLF      = PAX / SEATS              # seat load factor
GAUGE    = SEATS / DEPS             # average aircraft size
LH_SHARE = Σ DEPS[distance ≥ D_LH] / DEPS
```

From On-Time Performance, aggregated to airport × hour-of-day:
```
PEAK_HR_DEPS = 95th percentile of scheduled departures per hour   # robust design-hour
PEAKING      = PEAK_HR_DEPS / mean hourly departures (operating hours only)
PHP          = PEAK_HR_DEPS × GAUGE × SLF        # design-day peak-hour passengers
TAXI_OUT_P50 = median taxi-out minutes
DEL15_RATE   = share of departures delayed > 15 min
CANCEL_RATE  = share cancelled
```

> Use the **95th percentile**, not the max. One Thanksgiving Sunday shouldn't define your design hour. This is the kind of choice they'll ask about.

---

## 3. The five pillars

### Pillar 1 — Saturation (weight 0.30)
*How full is it already?*
```
DC_RATIO = OPS / ASV
```
`ASV` in priority order:
1. FAA Airport Capacity Profile called rates, where published (~40 airports) — best.
2. Runway-configuration lookup from AC 150/5060-5 (single runway / close parallels / far parallels / intersecting) — approximate.
3. Peer-group regression fallback — worst; mark low-confidence.

⚠️ **Do not hard-code ASV values from memory.** Read them out of the AC and cite the figure number. An interviewer who plans airports for a living will catch an invented number instantly. If you're short on time, ship the lookup table with a visible `# TODO: verified against AC 150/5060-5 Fig 2-x` and say so — honest beats fabricated.

Blend with observed delay so the ratio is grounded in reality:
```
Saturation = 0.5·pct(DC_RATIO) + 0.25·pct(TAXI_OUT_P50) + 0.15·pct(DEL15_RATE) + 0.10·pct(PEAKING)
```

### Pillar 2 — Unmet demand (weight 0.25) ⭐ your differentiator
*How much demand is being turned away right now?* Four independent signals:

**(a) Administrative suppression** — slot controls are demand caps by law.
`Level 3 (JFK/LGA/DCA) → 1.0 · Level 2 (EWR/ORD/SFO/LAX) → 0.6 · else 0`

**(b) Spill estimate** — Boeing/normal spill model. Demand `D ~ Normal(μ, σ)`, `σ = K·μ`, `K ≈ 0.35`. With seats `S` and `z = (S − μ)/σ`:
```
E[spill] = σ · [ φ(z) − z·(1 − Φ(z)) ]
```
You observe load, not demand, so solve for `μ` by fixed-point iteration until `μ − E[spill](μ) = PAX`. Report `spill_rate = E[spill]/μ`.
Sanity: at ~85% load factor, spill is small; at 90%+ it climbs sharply. If your numbers don't behave that way, you have a bug.

**(c) Upgauging signal** — the cleanest computable evidence of a *physical* constraint:
```
UPGAUGE = CAGR₃(GAUGE) − CAGR₃(DEPS)
```
Positive means airlines are adding seats by flying **bigger aircraft rather than more flights** — the textbook symptom of an airport where you can't get another slot or gate. Cheap to compute, genuinely insightful, and nobody else will have it.

**(d) Catchment gap** *(optional)* — metro population (Census) vs enplanements per capita relative to peer median. Under-served + constrained = latent demand.

### Pillar 3 — Growth outlook (weight 0.20)
```
Growth = 0.5·pct(CAGR₅(PAX))  +  0.5·pct(TAF_CAGR to 2035)
```
Historical trend plus the FAA's own forecast. Two independent views; disagreement between them is itself worth surfacing.

### Pillar 4 — Feasibility (weight 0.15) ⭐ the investor's pillar
*Can you actually build here?* A **discount**, not a bonus. Start at 1.0, subtract:
- land-locked / no room for a runway or concourse
- legal caps or settlement agreements (SNA)
- curfews / noise litigation history
- perimeter rules (LGA/DCA)
- single runway with no expansion path
- add back for: existing NPIAS-programmed projects, spare land, recent master plan

Curated for the top ~60 airports. Say plainly that it's curated and that at scale you'd parse NPIAS + Part 150 filings.

**This pillar is why LGA doesn't top your list despite being the most congested airport in America.** That is the sentence that shows you're thinking like an investor, not a data analyst.

### Pillar 5 — Monetization (weight 0.10)
```
Monetization = 0.4·pct(INTL_SHARE) + 0.3·pct(LH_SHARE) + 0.2·pct(GAUGE) + 0.1·pct(nonstop_destinations)
```
International/long-haul traffic means higher revenue per passenger, bigger terminals, customs facilities — more capex but more upside. With DB1B you'd add real fare data; say so.

---

## 4. Normalisation, weighting, aggregation

**Normalise** by **percentile rank within a peer group** (peer = FAA hub class: Large / Medium / Small / Non-hub).
- Robust to outliers (ATL doesn't flatten everything else), and directly interpretable: *"SFO sits at the 96th percentile of saturation among large hubs."*
- Winsorize at the 5th/95th percentile before ranking; floor at 0.01 so the geometric mean can't collapse to zero.
- **Compare like with like.** Ranking BOS against BDL on raw volume is meaningless; ranking each against its own class is not.

**Weight**: equal-ish, hand-set, **exposed in the API and the UI**. Defensible because transparent; alternatives (PCA-derived, AHP, budget-allocation surveys) are in the OECD handbook — name them as what you'd do with expert input.

**Aggregate** with a **weighted geometric mean**:
```
Score = 100 × Π pillarᵢ^wᵢ        (Σwᵢ = 1)
```
**Why geometric, not arithmetic?** Geometric is *partially non-compensatory*: a near-zero pillar drags the whole score down and can't be bought off by strength elsewhere. That's the correct economics here — an airport that physically cannot expand is not a good investment no matter how congested it is. An arithmetic mean would let extreme congestion paper over zero feasibility. **This is a top-3 interview question; have the answer ready.**

---

## 5. Tiering — lead with this, not the score

The 0–100 score ranks. The **tier** is what you actually defend, because the FAA set the cut points:

| Tier | Rule | Meaning |
|---|---|---|
| **A — Build now** | `DC_RATIO ≥ 0.80` | FAA: construction of added capacity should be underway |
| **B — Plan now** | `0.60 ≤ DC_RATIO < 0.80` | FAA: planning should have started |
| **C — Monitor** | `0.45 ≤ DC_RATIO < 0.60` | Approaching the planning trigger |
| **D — No capacity case** | `< 0.45` | Any investment case rests on something other than capacity |

Then rank *within* tier by composite score. "SFO is Tier A per FAA AC 150/5060-5, and ranks 2nd within Tier A on our composite" is a much stronger sentence than "SFO scores 87."

---

## 6. Uncertainty — ship it, don't hide it

Three mechanisms, all cheap, all differentiating:

**(a) Confidence score per airport**
```
confidence = 0.5·(non-imputed fields / total fields)
           + 0.3·recency_factor(data vintage)
           + 0.2·(1 if ASV from FAA profile, 0.5 if runway-derived, 0.2 if regression)
```
Render as High / Medium / Low next to every result.

**(b) Weight-sensitivity analysis** — the impressive one, ~20 lines:
```python
for _ in range(1000):
    w = dirichlet(alpha = base_weights * 40)     # ±~25% jitter
    ranks.append(rank_airports(w))
# report: median rank, 10th–90th percentile rank band, P(top-3)
```
Then the agent can say: *"BOS ranks #1 in 92% of weight draws — the conclusion is robust to how you weight the pillars."* Or, more honestly: *"PVD ranges from #3 to #11 depending on weights; treat that ordering as soft."* This directly satisfies "clearly communicate assumption, uncertainty and scoping," and it's straight out of the OECD handbook.

**(c) Explicit assumption registry** — a dict returned with every answer:
```json
{"long_haul_threshold_nmi": 2500,
 "long_haul_note": "No ICAO/IATA standard exists; industry usage spans 2,200-2,600 nmi. Configurable.",
 "new_england_states": ["ME","NH","VT","MA","RI","CT"],
 "service_classes_included": ["scheduled passenger"],
 "cargo_excluded": true,
 "data_vintage": {"t100": "2026-05", "ontime": "2026-05", "taf": "2026"},
 "ops_estimate": "OPS approximated as 2 x departures_performed"}
```

---

## 7. Validating that the score isn't nonsense

You have **free ground truth**. The FAA already tells you which airports are capacity-constrained:
- **Level 3 slot-controlled:** JFK, LGA, DCA
- **Level 2 schedule-facilitated:** EWR, ORD, SFO, LAX

**If your Saturation pillar doesn't put those seven near the top, your model is broken.** Write it as a test:

```python
def test_saturation_recovers_faa_constrained_airports():
    top15 = rank_by_saturation().head(15).index
    for apt in ["JFK", "LGA", "DCA", "EWR", "ORD", "SFO", "LAX"]:
        assert apt in top15
```

A passing backtest against an independent regulator list is worth more than any amount of prose about your methodology. Cross-check volumes against FAA published enplanements too.

---

## 8. Question-specific scoring variants

Different questions need different weightings — expose them as named profiles:

| Question type | Profile | Weighting shift |
|---|---|---|
| "terminal expansion candidates" | `terminal` | ↑ PHP, peaking, gate pressure, growth; ↓ runway D/C |
| "congestion comparison" | `congestion` | Saturation + delay only; no growth/feasibility |
| "runway/airfield capacity" | `airfield` | ↑ D/C, taxi-out, weather-driven capacity loss |
| default investment ranking | `investment` | the five pillars above |

The agent picks the profile from the question — and **tells the user which one it used and why**. That's reasoning made visible.

## Sources
- [FAA AC 150/5060-5, Airport Capacity and Delay](https://www.faa.gov/documentlibrary/media/advisory_circular/150_5060_5.pdf)
- [FAA FACT3 report](https://www.faa.gov/sites/faa.gov/files/airports/resources/publications/reports/FACT3-Airport-Capacity-Needs-in-the-NAS.pdf)
- [OECD/JRC Handbook on Constructing Composite Indicators](https://www.oecd.org/content/dam/oecd/en/publications/reports/2008/08/handbook-on-constructing-composite-indicators-methodology-and-user-guide_g1gh9301/9789264043466-en.pdf)
- [MIT 16.75J — Demand, Load and Spill Analysis (Belobaba)](https://ocw.mit.edu/courses/16-75j-airline-management-spring-2006/f990b2cd2141f75cd9b348051af762e7_lect4b.pdf)
- [FAA AC 150/5360-13A, Airport Terminal Planning](https://www.faa.gov/documentLibrary/media/Advisory_Circular/AC-150-5360-13A-Airport-Terminal-Planning.pdf)
- [ACRP Report 25, Airport Passenger Terminal Planning and Design](https://onlinepubs.trb.org/onlinepubs/acrp/acrp_rpt_025v1.pdf)
- [FAA Slot Administration (Level 2/3 designations)](https://www.faa.gov/about/office_org/headquarters_offices/ato/service_units/systemops/perf_analysis/slot_administration)
