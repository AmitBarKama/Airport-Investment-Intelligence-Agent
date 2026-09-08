# Design Document — Airport Investment Intelligence Agent

*Deliverable: scoring methodology · key tradeoffs · where AI is used.*

---

## 1. Problem framing

The brief asks where renovations will be *most profitable* based on increased
flight and passenger capacity. That is not the same as "which airport is
busiest." Decomposed:

```
Investment attractiveness ≈  (demand currently being turned away)
                           × (ability to monetize the unlocked traffic)
                           ÷ (difficulty, cost and risk of building it)
```

Three failure modes the design explicitly avoids:

1. **Ranking by size.** Atlanta is the biggest US airport. That says nothing
   about whether capital deployed there earns a return.
2. **Ranking by congestion alone.** LaGuardia is the most congested airport in
   the country *and* one of the worst places to spend expansion capital:
   land-locked, perimeter-ruled, slot-controlled. Congestion without
   buildability is a value trap.
3. **Reading suppressed demand as weak demand.** John Wayne (SNA) looks
   uncongested because a 1985 legal settlement caps its passengers and
   departures — that is latent demand, not absent demand.

The system is a **screening tool**: it narrows ~630 airports to a handful worth
a human analyst's week. It does not do site engineering, cost estimation or
diligence, and it says so when asked.

---

## 2. Scoring methodology

### 2.1 Anchored to a published federal standard

The single most important design decision: **do not invent thresholds, borrow
the regulator's.**

FAA Advisory Circular 150/5060-5 (*Airport Capacity and Delay*) defines Annual
Service Volume — the annual operations level at which average delay per aircraft
runs roughly 2.3–3.5 minutes — and sets planning triggers:

| Demand ÷ ASV | FAA guidance | Our tier |
|---|---|---|
| ≥ 0.80 | begin **construction** of added capacity | **A — Build now** |
| 0.60 – 0.80 | begin **planning** for added capacity | **B — Plan now** |
| 0.45 – 0.60 | approaching the planning trigger | **C — Monitor** |
| < 0.45 | — | **D — No capacity case** |

The agent leads with the **tier**, because that is the regulator's judgment, and
uses the composite score only to rank *within* a tier. "SFO is Tier A per FAA AC
150/5060-5 and ranks 2nd within that tier" is a far stronger claim than
"SFO scores 87."

Also drawn on: the FAA **FACT** reports (structure: analyse a defined candidate
set, project forward, tier by need), the **OECD/EC-JRC Handbook on Constructing
Composite Indicators** (normalisation → weighting → aggregation → uncertainty
analysis), **FAA AC 150/5360-13A** and **ACRP Report 25** (terminals are sized
off the design-day peak hour, not annual totals), and the **airline spill model**
(Belobaba, MIT 16.75J).

### 2.2 Five pillars

| Pillar | Weight | Inputs |
|---|---|---|
| **Saturation** | 0.30 | demand/ASV · median taxi-out · % delayed >15 min · peaking factor |
| **Unmet demand** | 0.25 | slot level · spill estimate · upgauging · catchment gap |
| **Growth** | 0.20 | historical passenger CAGR · FAA TAF forecast |
| **Feasibility** | 0.15 | land, curfews, legal caps, perimeter rules, runway room |
| **Monetization** | 0.10 | international share · long-haul share · gauge · destinations |

Two pillars deserve explanation.

**Unmet demand** is where the analytical content lives. Four independent signals:

- *Administrative suppression* — IATA Level 3 (JFK/LGA/DCA) and Level 2
  (EWR/ORD/SFO/LAX) designations are legal caps on demand. Observed traffic at
  these airports is a capped quantity, not a market outcome.
- *Spill* — the normal/Boeing spill model. With demand `D ~ N(μ, Kμ)`, capacity
  `S` and `z = (S−μ)/σ`, expected spill is `σ·[φ(z) − z·(1−Φ(z))]`. Observed
  load is `μ − E[spill]`, which is monotone in `μ`, so we invert it by bisection
  to recover unconstrained demand from the passengers we actually see. Grounded
  in the identity *mean demand = mean observed load + mean spill*.
- *Upgauging* — `CAGR(seats per departure) − CAGR(departures)`. When airlines add
  seats by flying bigger aircraft rather than more flights, that is the textbook
  symptom of an airport where another slot or gate cannot be had. Cheap to
  compute, genuinely diagnostic, and derived from the traffic table alone.
- *Catchment gap* — metro population vs enplanements per capita (not loaded;
  requires the Census API).

**Feasibility** is a **discount, not a bonus** — the investor's pillar. Curated
from public facts (settlement agreements, curfews, perimeter rules, land
constraints) with the fact and the judgment stored separately, each with a
source URL. This is the pillar that stops the model recommending LaGuardia.

### 2.3 Normalisation, weighting, aggregation

- **Normalise** by winsorised (5th/95th) **percentile rank within the cohort**.
  Robust to outliers, and directly interpretable: *"96th percentile of saturation
  among US commercial airports."* Absolute 0–1 judgments (slot level,
  feasibility) are deliberately *not* percentile-ranked — they are facts, and
  should not move because the peer group changed. Each pillar reports its
  `basis` so this is visible rather than buried.
- **Weight** equally-ish, hand-set, exposed in the API and overridable per
  request. Data-driven weighting (PCA) optimises for variance, not investment
  relevance — it would silently encode "whatever varies most" as "whatever
  matters most."
- **Aggregate** with a **weighted geometric mean**: `Score = 100 × Π pillarᵢ^wᵢ`.

  Geometric because it is *partially non-compensatory*: a near-zero pillar drags
  the whole score down and cannot be offset elsewhere. An arithmetic mean would
  let extreme congestion paper over zero buildability. This is asserted as a
  unit test, not just a claim:
  `tests/test_scoring.py::test_geometric_mean_is_not_compensatory` constructs a
  maximally-congested-but-unbuildable airport, shows the arithmetic mean ranks it
  above a balanced airport, and shows the geometric mean does not.

### 2.4 Question-specific profiles

One ranking cannot answer every question, so four named profiles shift the
weights — `investment` (default), `terminal` (peak-hour-weighted, per ACRP 25),
`congestion` (saturation only; no growth or feasibility, because those are
investment questions not congestion questions), `airfield` (runway-weighted).
The agent picks one and **says which it used and why**.

### 2.5 Uncertainty

Three mechanisms, all shipped:

1. **Confidence per airport** — input coverage, ASV source quality (published
   FAA profile > runway-config estimate > regression), and data recency, with
   the *reasons* rendered next to the label.
2. **Weight-sensitivity analysis** — 400 Dirichlet-perturbed weight vectors,
   reporting median rank, 10th–90th percentile band and P(rank 1). Output like
   *"BDL ranks first in 94% of weight draws"* is a much stronger claim than any
   argument for a particular weight vector. Straight from the OECD handbook's
   uncertainty step.
3. **Assumption registry** — returned with every tool result and rendered in the
   UI: long-haul threshold (and that no ICAO/IATA standard exists), the New
   England state list, cargo exclusion, the operations≈2×departures
   approximation, and the scope boundary.

### 2.6 Validation

The model is validated against a list it never sees. The FAA independently
publishes which airports are capacity-constrained: **Level 3** JFK, LGA, DCA;
**Level 2** EWR, ORD, SFO, LAX. The saturation pillar is built from traffic,
delay and runway capacity only. If it is measuring anything real, those seven
should surface at the top of a national saturation ranking — and that is an
automated test.

On real BTS data that test **passes**: all seven surface inside the top 25 of
624 airports on saturation, with SFO 4th, ORD 10th and LGA 15th.

A related test checks rank rather than absolute FAA tier, deliberately. JFK
scores tier C on our numbers because the ASV placeholder credits it with a
generic four-runway capacity, far more than it really has: JFK is slot-controlled
precisely because its usable capacity is low. That is a known weakness of the
capacity denominator, which is why `asv_source` travels with every answer.

What *does* validate in every mode is structural, because runway geometry is
always real: the classifier computes SFO's parallel-runway separation as
**750 ft** directly from threshold coordinates, matching the published figure,
and correctly identifies SFO and SEA as unable to run independent parallel
instrument approaches while DFW, DEN, ORD, ATL and JFK can.

---

## 3. Where AI is used — and where it deliberately is not

| Layer | AI? | Why |
|---|---|---|
| Intent understanding, entity resolution | ✅ | natural language is genuinely hard |
| Choosing which analysis to run | ✅ | maps an open-ended question onto 8 tools |
| Explaining results, narrating tradeoffs | ✅ | this is what language models are good at |
| Handling ambiguity and follow-ups | ✅ | pronouns, referents, "what if" |
| **Any number, ratio, rank or score** | ❌ **never** | deterministic Python, unit-tested |
| **Weighting, normalisation, aggregation** | ❌ never | reviewable, reproducible |
| **Tier assignment** | ❌ never | it is an FAA rule, not a judgment |

The invariant: **the model cannot hallucinate the numbers because the numbers
were never its to invent.** Enforced three ways —

1. Tools return typed JSON; the model sees only tool output, never raw data.
2. The system prompt forbids un-sourced figures outright.
3. `numeric_guard()` scans the finished answer and flags any number appearing in
   no tool output (ignoring small ordinals and years). Surfaced in the UI.

Tools also return **denominators, not just ratios** — "38,117 of 59,486
departures (64.1%)" is checkable; "64%" is not — and return `null` with a reason
rather than a plausible-looking guess when data is missing.

The provider is behind a 30-line interface (Groq / Gemini / OpenRouter /
Anthropic / rule-based), selected by one environment variable. Swapping models
changes tone, not answers. With no key configured a rule-based planner routes
questions to the same tools, so the deterministic pipeline stays demonstrable.

---

## 4. Key tradeoffs

| Decision | Why | What it costs | With more time |
|---|---|---|---|
| **Feasibility as a discount** | congestion without buildability is a value trap | curated for ~20 airports | parse NPIAS + Part 150 filings |
| **Geometric mean** | unbuildable airports can't be rescued by congestion | harder to explain; needs a floor | compare against PROMETHEE/ELECTRE |
| **Percentile rank within cohort** | robust to outliers, interpretable | loses magnitude information | report rank *and* standardised magnitude |
| **Hand-set weights** | transparent; PCA optimises variance, not relevance | they are my judgment | budget-allocation elicitation with analysts |
| **Offline ETL → local DB** | deterministic, <50 ms, survives bad wifi | staleness | scheduled refresh + live delay layer |
| **stdlib only (no FastAPI/DuckDB/React)** | runs anywhere with zero install; the reviewer needs no setup | no pandas ergonomics, no component framework | port to FastAPI + React once deps are available |
| **Hand-written agent loop** | the loop *is* the deliverable; a framework would hide it | no free retries/checkpointing | LangGraph if workflows branch |
| **SSE not WebSockets** | one-way streaming over plain HTTP | can't do bidirectional audio | WebSockets for native speech-to-speech |
| **Web Speech API for voice** | free, no key, ~40 lines, can't blow a quota mid-demo | no Firefox; Chrome sends audio to Google | Groq Whisper (free tier) + ElevenLabs |
| **Synthetic traffic fallback** | keeps the system runnable and testable end to end | volumes are not real | drop in a BTS T-100 export (path implemented) |

### Interface decision worth flagging

The design spec says *do not show technical agent logs*. That conflicts on its
face with the assignment's requirement to demonstrate deterministic scoring
rather than raw LLM output. The resolution: move the proof from a stack trace
to things a person can actually read — human-readable progress steps, a score
card showing each pillar and its weight, source pills, and an assumptions
disclosure. The raw tool calls remain one toggle away in Settings. The user
sees an expert thinking; the reviewer can still audit every number.

One real bug found during interface testing, worth recording because it was
invisible from the server side: the SSE response advertised
`Connection: keep-alive` with no `Content-Length` and no chunked encoding, so
the client could not tell where the body ended. `curl` tolerated it, Node hung
after the final event, and Chrome withheld the stream entirely — the answer
never appeared. Fixed by closing the connection so EOF delimits the body.

### The honest weak points

- **The ASV denominator.** For airports without a published FAA capacity
  profile, ASV comes from a runway-configuration lookup whose values are
  *representative placeholders, not transcribed from AC 150/5060-5*. This is
  stated loudly in `etl/capacity.py`, flagged as `asv_source="runway_config"`,
  and drives the confidence score down. Fabricating a precise-looking number
  here would have been the worst thing this codebase could do.
- **Delay, taxi-out and peaking are not loaded.** They need BTS On-Time
  Performance, a separate export. An earlier version generated them from the
  demand/capacity ratio, which both invented data and made the saturation
  pillar correlate with itself. They now report as missing, which lowers the
  confidence score honestly instead of filling the gap.
- **Growth needs a second year of T-100.** With one year loaded it is reported
  as unknown rather than computed as zero.
- **No fare or O&D data** (BTS DB1B), so monetization is a proxy and "how much
  suppressed demand would actually convert" is reported as *unknown* rather
  than estimated.

---

## 5. What I would do next, in order

1. ~~Load real BTS T-100~~ **— done.** The database is built from T-100
   Segment (All Carriers) 2019 + 2024: 624 airports, 52,649 routes. Still
   outstanding is BTS **On-Time Performance**, without which `taxi_out_p50`,
   `del15_rate` and `peaking` are NULL for every airport — the saturation
   pillar currently rests on demand/ASV alone, and the FAA backtest stays
   skipped.
2. Transcribe FAA Airport Capacity Profiles for the ~40 airports where they are
   published; replace the placeholder ASV table.
3. FAA Terminal Area Forecast for the forward-looking half of the growth pillar.
4. BTS DB1B for real fares and O&D-vs-connecting split → genuine monetization.
5. An eval set of ~30 question/expected-behaviour pairs, so agent quality is
   measured rather than eyeballed.

---

## Sources

- [FAA AC 150/5060-5, *Airport Capacity and Delay*](https://www.faa.gov/documentlibrary/media/advisory_circular/150_5060_5.pdf)
- [FAA FACT3, *Airport Capacity Needs in the NAS*](https://www.faa.gov/sites/faa.gov/files/airports/resources/publications/reports/FACT3-Airport-Capacity-Needs-in-the-NAS.pdf)
- [FAA Slot Administration (Level 2/3 designations)](https://www.faa.gov/about/office_org/headquarters_offices/ato/service_units/systemops/perf_analysis/slot_administration)
- [FAA AC 150/5360-13A, *Airport Terminal Planning*](https://www.faa.gov/documentLibrary/media/Advisory_Circular/AC-150-5360-13A-Airport-Terminal-Planning.pdf)
- [ACRP Report 25, *Airport Passenger Terminal Planning and Design*](https://onlinepubs.trb.org/onlinepubs/acrp/acrp_rpt_025v1.pdf)
- [OECD/JRC, *Handbook on Constructing Composite Indicators*](https://www.oecd.org/content/dam/oecd/en/publications/reports/2008/08/handbook-on-constructing-composite-indicators-methodology-and-user-guide_g1gh9301/9789264043466-en.pdf)
- [MIT 16.75J, *Demand, Load and Spill Analysis* (Belobaba)](https://ocw.mit.edu/courses/16-75j-airline-management-spring-2006/f990b2cd2141f75cd9b348051af762e7_lect4b.pdf)
- [FAA SFO Airport Capacity Profile](https://www.faa.gov/sites/faa.gov/files/airports/planning_capacity/profiles/SFO-Airport-Capacity-Profile-2019.pdf)
- [John Wayne Airport Settlement Agreement FAQs](https://www.ocair.com/about/administration/settlement-agreement/settlement-agreement-faqs/)
- [BTS TranStats (T-100)](https://www.transtats.bts.gov/) · [OurAirports data](https://davidmegginson.github.io/ourairports-data/)
