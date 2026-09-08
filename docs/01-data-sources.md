# 01 — Data sources: what's free, what it gives you, what it costs you

## Verification status — read this first

I probed these endpoints from a network-restricted sandbox. Only a subset of hosts resolved, so treat the table as **research + a shortlist to verify**, not as tested truth. Run `scripts/verify_sources.sh` on your own machine before you commit to a source.

| Source | Status from my sandbox |
|---|---|
| OurAirports CSV | ✅ **Verified live** — HTTP 200, 12.7 MB, headers parsed |
| BTS TranStats (transtats.bts.gov) | ✅ **Verified reachable** — field list confirms T-100 data current through **May 2026**. But see the PREZIP warning below: guessed bulk filenames 404. |
| faa.gov, nasstatus.faa.gov, api.aviationapi.com, opensky-network.org, data.transportation.gov | ⚠️ **Unverified** — DNS blocked in sandbox, not evidence they're down. Verify locally. |

## The layered data strategy (this is the important architectural idea)

Do **not** call third-party APIs at question-answering time. Split into two layers:

```
   BULK / ETL LAYER (runs once, offline)          LIVE LAYER (optional, at query time)
   ────────────────────────────────────           ──────────────────────────────────
   BTS T-100 segment       ──┐                    FAA NAS Status  → today's ground stops
   BTS On-Time Performance ──┤                    OpenSky         → live flights near airport
   OurAirports (geo+runways)─┼→ airports.duckdb   METAR/weather   → current conditions
   FAA TAF (forecasts)     ──┤    (~50 MB)
   FAA enplanements        ──┤
   Curated static tables   ──┘
```

**Why this split:**
- **Determinism.** The same question gives the same answer. Required for a scoring system you have to defend.
- **Speed.** DuckDB answers in <50 ms. Every LLM turn may fire 2–4 tools; network latency there would make voice unusable.
- **Demo safety.** Conference wifi dies. Rate limits bite at the worst moment. Your demo must not depend on a third party being up.
- **The cost:** staleness. Mitigate by stamping every answer with the data vintage (`"T-100 through May 2026"`) and using the live layer only for genuinely real-time claims.

Say this in the interview: *"Live APIs are for real-time facts. Investment decisions run on annual traffic patterns, so I front-loaded them into a local analytical store and spent the runtime budget on reasoning quality instead of HTTP."*

---

## Tier 1 — The core four (build on these)

### 1. BTS T-100 Segment (Air Carrier Statistics) ⭐ the backbone
**What:** Every nonstop segment flown by US and foreign carriers, monthly, at carrier × origin × destination × aircraft-type grain.
**Fields you need:** `PASSENGERS`, `SEATS`, `DEPARTURES_PERFORMED`, `DEPARTURES_SCHEDULED`, `DISTANCE`, `RAMP_TO_RAMP`, `AIR_TIME`, `CLASS` (service class), `ORIGIN`, `DEST`, `MONTH`, `YEAR`.
**Unlocks:** load factor, seats, flights, average gauge, long-haul share, growth (CAGR), international share, route counts. This one table answers most of the assignment.
**Cost:** free, public domain. **Latency:** ~2 months. **Current through May 2026** (verified).
**Access:**
- Web form: `https://www.transtats.bts.gov/DL_SelectFields.asp?Table_ID=293` (T-100 Segment) — pick year, select all fields, get a ZIP.
- Bulk pre-zipped mirror: `https://transtats.bts.gov/PREZIP/` — widely used for scripted pulls. ⚠️ **I probed three plausible filenames (`T_T100D_SEGMENT_ALL_CARRIER.zip`, `T_T100_SEGMENT_ALL_CARRIER.zip`, `T_MASTER_CORD.zip`) and all returned HTTP 404** — the host answered, so the directory is live but that naming convention is wrong. **Discover the real filename before relying on this path:** open the `DL_SelectFields` form in a browser with devtools on the Network tab, submit one download, and copy the URL the form actually requests. Then script that. Budget 15 minutes for this; don't assume a convention from a blog post (including this one).
- Mirror of the same data: `https://data.transportation.gov` (Socrata SODA API, supports SoQL/JSON) — nicer to query, less predictable coverage.

⚠️ **Two traps.**
1. **Service class.** T-100 includes all-cargo operations. `CLASS` codes distinguish scheduled passenger service (F/L) from all-cargo (G/P/R…). If you don't filter, Anchorage's long-haul share becomes a freighter statistic. **Confirm the exact code meanings in the BTS data dictionary before relying on them** — then say in the UI which classes you included.
2. **Market vs Segment.** *Segment* = physical nonstop legs (what you want for flights/seats/capacity). *Market* = origin-to-final-destination passenger flow. Mixing them silently double-counts.

### 2. OurAirports ✅ verified working
**What:** Every airport on earth — ICAO/IATA idents, type, name, lat/lon, elevation, municipality, `iso_region` (e.g. `US-MA`), scheduled-service flag. Plus a separate `runways.csv` with per-runway length, width, surface, lighting.
**Unlocks:** regional filtering (the "New England" question is a one-line `iso_region IN (...)`), runway count/length → capacity class, map display.
**Access (no key, no auth):**
```
https://davidmegginson.github.io/ourairports-data/airports.csv    # 12.7 MB, verified 200
https://davidmegginson.github.io/ourairports-data/runways.csv
```
**Cost:** free, public domain. **Caveat:** community-maintained, so runway data quality varies at small fields. Fine for the top few hundred US commercial airports.

### 3. BTS On-Time Performance (Marketing Carrier)
**What:** Row per scheduled domestic flight: `CRSDepTime` (scheduled time!), `DepDelay`, `TaxiOut`, `TaxiIn`, `WheelsOff`, `Cancelled`, `Diverted`, delay-cause minutes (carrier/weather/NAS/security/late-aircraft).
**Unlocks — and this is what most candidates will miss:** T-100 is monthly and has **no time of day**. On-Time Performance has scheduled departure times, so it's the *only* free way to build an **hourly departure profile** → peak-hour operations, peaking factor, and design-day peak-hour passengers. Terminal sizing is driven by peak hour, not annual totals. It also gives you **taxi-out time**, the standard proxy for airfield/surface congestion.
**Cost:** free. **Caveat:** big (hundreds of MB/year). Aggregate to per-airport-per-hour during ETL and throw the rows away. Domestic reporting carriers only.
**Access:** TranStats `DL_SelectFields.asp` (Reporting Carrier On-Time Performance) or the PREZIP mirror.

### 4. FAA Terminal Area Forecast (TAF)
**What:** The FAA's *official* forecast of enplanements, operations and based aircraft **per airport**, historical + forecast out past 2045.
**Unlocks:** the forward-looking half of the score. Historical CAGR tells you what happened; TAF tells you what the regulator expects. Using the FAA's own forecast rather than your own regression is both cheaper and far more defensible.
**Access:** `https://taf.faa.gov` (downloadable databases, zipped DBF) and `https://www.faa.gov/data_research/aviation/taf`.
**Cost:** free. **Caveat:** DBF format (use `dbfread` in Python); forecasts are unconstrained-demand style and known to be optimistic at some fields — disclose that.

---

## Tier 2 — High value, small effort

| Source | Gives you | Access | Notes |
|---|---|---|---|
| **FAA Passenger Boarding (Enplanements)** | Official CY enplanements + hub class (Large/Medium/Small/Non-hub) per airport, XLSX | `faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger` — e.g. `ARP-cy2024-all-enplanements.xlsx` | CY2025 final data was due late Aug 2026. Clean ground truth; use to sanity-check your T-100 aggregation. |
| **FAA Airport Capacity Profiles** ⭐ | Published **called rates** (hourly arrival/departure capacity) per major airport by runway config & weather. This is as close to a real ASV as you'll get for free. | `faa.gov/sites/faa.gov/files/airports/planning_capacity/profiles/<APT>-Airport-Capacity-Profile-2019.pdf` | Only ~30–45 airports; PDFs. Hand-transcribe the ones you need into a CSV — an afternoon's work that hugely upgrades your capacity denominator. |
| **FAA NPIAS** | 5-year airport development **cost estimates** per airport | `faa.gov/airports/planning_capacity/npias` | The capex side of the ROI story. Pairs beautifully with a demand score. |
| **FAA slot / IATA level designations** | JFK, LGA, DCA = **Level 3** (slot-controlled). EWR, ORD, SFO, LAX = **Level 2** (schedule-facilitated). | Hand-code ~10 rows | Tiny table, big payoff: it's your **administrative suppressed-demand** signal *and* your validation set. |
| **FAA NAS Status** | Live ground stops / ground delay programs / airport closures | `https://nasstatus.faa.gov/api/airport-status-information` (XML) | ⚠️ unverified from sandbox. Nice live-layer garnish; don't build the score on it. |
| **US Census Bureau API** | CBSA/metro population → enplanements per capita → catchment gap | `api.census.gov` — free instant key | Optional. Powers the "is this metro under-served?" signal. |

---

## Tier 3 — Know them, probably skip them

| Source | Why you might want it | Why to skip for a 1-day build |
|---|---|---|
| **OpenSky Network** | Free live ADS-B; historical flights/tracks | **Auth changed: as of 18 Mar 2026 basic auth is dead — OAuth2 client-credentials only** (30-min tokens). Daily credit system (~8,000/day if you host a receiver). Anonymous = heavily throttled. Real-time ≠ your use case. |
| **BTS DB1B** | 10% ticket sample → **fares**, O&D vs connecting split | Genuinely the best monetization signal. Also the heaviest lift. Perfect "with another week I'd…" answer. |
| **Aviationstack / AeroDataBox / Aviation Edge / FlightAware AeroAPI** | Polished real-time flight APIs | Free tiers are tiny (aviationstack ≈ 100 req/month). You'd burn them in one demo, and none of them give you capacity or forecasts. |
| **Amadeus Self-Service** | Free test tier, some airport analytics endpoints | Test-environment data is partly synthetic. Don't build a scoring system on it. |
| **FAA ASPM / OPSNET** | The authoritative delay + operations counts | Most databases need an FAA login. Public users get finalized data 20 days after month end. Cite it as ground truth; use BTS On-Time as your accessible substitute. |
| **FAA APRA API** (`external-api.faa.gov/apra`) | NASR aeronautical data, charts | Useful for airport reference data, but OurAirports already covers what you need with zero friction. |

---

## Recommended minimum viable dataset

For a one-day build, this is enough to answer all four sample questions well:

1. **T-100 Segment**, last 5 full years + latest 12 months → traffic, load factor, gauge, long-haul, growth
2. **OurAirports** airports + runways → geography, region filter, runway config
3. **On-Time Performance**, latest 12 months, aggregated to airport×hour → peak hour, taxi-out, delay rate
4. **FAA TAF** → forecast growth
5. **Three hand-made CSVs** (~60 rows each, 1 hour of work, disproportionate payoff):
   - `slot_levels.csv` — IATA Level 2/3 designations
   - `capacity_profiles.csv` — called rates for airports where FAA publishes them
   - `constraints.csv` — curfews, passenger caps, legal settlements, land-locked flags (SNA's cap, LGA's perimeter rule, etc.)

That last file is where your domain credibility lives. It is also the honest answer to "how would you scale this?" — *"today it's curated for the top 60 airports; at scale I'd parse NPIAS and Part 150 filings."*

## Licensing
US federal government works (BTS, FAA, Census) are public domain — no attribution required, though you should attribute anyway. OurAirports is public domain. Commercial APIs are not; check terms before shipping anything beyond a demo.

## Sources
- [BTS — Airlines, Airports and Aviation](https://www.bts.gov/topics/airlines-airports-and-aviation)
- [BTS TranStats](https://www.transtats.bts.gov/)
- [FAA Terminal Area Forecast](https://www.faa.gov/data_research/aviation/taf)
- [FAA Passenger Boarding (Enplanement) Data](https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger)
- [FAA Capacity Analysis](https://www.faa.gov/about/office_org/headquarters_offices/ato/service_units/systemops/perf_analysis/airport_capacity)
- [FAA Slot Administration](https://www.faa.gov/about/office_org/headquarters_offices/ato/service_units/systemops/perf_analysis/slot_administration)
- [OpenSky REST API docs](https://openskynetwork.github.io/opensky-api/rest.html)
- [OpenSky OAuth2 migration](https://github.com/openskynetwork/opensky-api/blob/master/docs/free/rest.rst)
- [OPSNET public access rules — ASPMHelp](https://www.aspm.faa.gov/aspmhelp/index/Operations_Network_(OPSNET).html)
