# 11 — The four sample questions, worked

Rehearse these. They're what you'll be asked to run. Each shows a different capability — make sure the differences are visible.

---

## Q1. "Which airports in New England are strong candidates for terminal expansion?"
**Tests:** regional filtering, ranking, methodology.
**Flow:** `list_airports(states=[ME,NH,VT,MA,RI,CT], is_commercial=true)` → `rank_airports(profile="terminal")`.

**Assumptions to state:** New England = the six states; terminal profile weights peak-hour passengers, peaking factor and growth above runway D/C; commercial-service airports only.

**The insight that makes this answer good:** BOS will top it and that's obvious. The *interesting* finding is the relief airports — **BDL (Hartford), PVD (Providence), MHT (Manchester)** — which sit in BOS's catchment and have physical room to grow. Boston is land-constrained and expensive; regional overflow capacity is a real investment thesis in New England, and it's the kind of thing an analyst is actually hired to surface.

Say: *"Ranking by size gives you Boston, which you already knew. The model's value is what it says about the second tier."*

---

## Q2. "Compare LA and Santa Ana airport congestion levels."
**Tests:** disambiguation, comparison, domain depth.
**Flow:** disambiguate "LA" (LAX/BUR/LGB/ONT — assume LAX, offer the rest) → `compare_airports(["LAX","SNA"], metrics=["dc_ratio","taxi_out","del15","slf","peaking","slot_level"])`.

**The domain detail that wins this question:** SNA is not congested in the ordinary sense — it is *legally capped*. Under a settlement agreement with Newport Beach dating to 1985 (amended 2003 and 2014) it has operated under an annual passenger cap (11.8M through 2025, rising to as much as ~12.5M from 2026 under a formula) and a cap on average daily departures (85, rising to 95). There's also a curfew: no scheduled departures 10pm–7am, no arrivals 11pm–7am, extended an hour on Sunday mornings — in force through 2035.

So the right answer isn't "LAX is more congested." It's: **LAX is capacity-constrained (FAA Level 2, schedule-facilitated); SNA is *demand*-constrained by legal agreement.** Those are different problems with opposite investment implications — you can build your way out of one and not the other.

⚠️ Verify the current cap numbers before the interview; they step up on a schedule.

---

## Q3. "What is the percentage of long haul flights out of Anchorage airport?"
**Tests:** precise computation, and whether you notice the trap.
**Flow:** `flight_mix(code="ANC", dimension="haul", long_haul_nmi=2500)`.

**Two things to surface, both of which are the actual point of the question:**

1. **There is no standard definition of "long haul."** Industry usage spans ~2,200–2,600 nmi; ICAO defines by flight time (long-haul 8–16 h), IATA differently (6–16 h); airlines each use their own. So the agent must state its threshold, say it's configurable, and ideally show sensitivity: "at 2,500 nmi it's X%; at 3,000 nmi it's Y%."

2. **Anchorage is one of the world's largest cargo hubs.** If you include all-cargo operations, ANC's long-haul share is dominated by freighters to Asia and the number means something completely different. The agent must say which service classes it counted and offer both figures.

Report as a fraction with denominators — "142 of 1,183 scheduled passenger departures (12.0%)" — not a bare percentage.

*This question looks like arithmetic. It's actually testing whether you communicate assumptions. Treat it that way.*

---

## Q4. "What is the unmet flight demand in SFO airport and why?"
**Tests:** the hardest reasoning; measurement vs. inference.
**Flow:** `unmet_demand("SFO")` → `airport_profile("SFO")` → `explain_score("SFO")`.

**Components of the answer:**
- **Spill estimate** — from the load-factor-based spill model, with the K assumption stated.
- **Administrative suppression** — SFO is an FAA **Level 2** schedule-facilitated airport; carriers coordinate schedules with the FAA. That is demand management by definition.
- **Upgauging** — if seats/departure is growing faster than departures, airlines are adding capacity the only way available.
- **The physical reason, which is the real answer:** SFO's two main arrival runways, **28L and 28R, are only ~750 feet apart**. That spacing is far below what's required for independent simultaneous instrument approaches, so in low-visibility conditions arrivals must be staggered and **arrival capacity roughly halves** — from around 60/hour in visual conditions. Bay Area marine-layer weather then converts a runway-geometry fact into chronic, weather-triggered delay. (In 2026 an FAA change to side-by-side visual approaches cut the clear-weather arrival rate further before being partially reversed — check the current state.)

**This is the question where you separate measurement from inference:**
> *Measured:* load factor 8x.x%, taxi-out median N minutes, Level 2 designation, upgauge delta.
> *Inferred:* the airport turns away demand because runway geometry caps arrivals in IMC.
> *Unknown:* how much of the suppressed demand would materialise if capacity existed — that needs fare and O&D data (DB1B) we don't have.

An agent that draws that three-way line is doing something most don't.

---

## Follow-up chain to rehearse
```
Q1 → "Why is BDL ahead of PVD?"            explain_score
   → "What if growth mattered more?"        rank_airports(weights=...)
   → "Is that ranking stable?"              sensitivity_analysis
   → "Compare the top two on delays."       compare_airports
   → "What are you assuming about long haul?" (reads assumption registry)
```

## Out-of-scope probes to handle gracefully
- "Should I buy airline stocks?" → out of scope, one sentence, offer capacity analysis
- "What about Heathrow?" → US airports only; explain the data is BTS/FAA
- "Which airport will be busiest in 2040?" → forecast horizon exceeds TAF confidence; say so

## Sources
- [John Wayne Airport Settlement Agreement FAQs](https://www.ocair.com/about/administration/settlement-agreement/settlement-agreement-faqs/)
- [SFO Airport Capacity Profile (FAA)](https://www.faa.gov/sites/faa.gov/files/airports/planning_capacity/profiles/SFO-Airport-Capacity-Profile-2019.pdf)
- [Flight length definitions — no international standard](https://en.wikipedia.org/wiki/Flight_length)
- [FAA Slot Administration — Level 2/3 designations](https://www.faa.gov/about/office_org/headquarters_offices/ato/service_units/systemops/perf_analysis/slot_administration)
