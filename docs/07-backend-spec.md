# 07 — Backend spec

## ETL

`etl/fetch.py` → downloads to `data/raw/`, caches by content hash, never re-downloads.
`etl/build.py` → normalises into DuckDB. Idempotent: `make etl` twice gives the same DB.

**Order of work (do it in this order — each stage is independently useful):**
1. OurAirports → `dim_airport`, `dim_runway` *(verified working; gets you the region filter in 20 min)*
2. Curated CSVs → `dim_constraints`, `dim_slot_level`, `dim_capacity_profile` *(hand-written, no download)*
3. T-100 Segment → `fact_segment_monthly` *(the big one)*
4. On-Time Performance → `agg_hourly_departures`, `agg_delay_monthly` *(aggregate on ingest, discard rows)*
5. FAA TAF → `fact_forecast`
6. Derived: `mart_airport_annual`, `mart_scores`

If you run out of time, stop after 4. Steps 1–4 answer every sample question except forecast-based growth.

## Schema

```sql
dim_airport(code PK, icao, name, city, state, iso_region, lat, lon,
            hub_class, is_commercial, cbsa_code)
dim_runway(code, runway_id, length_ft, width_ft, surface, lighted)
dim_slot_level(code, iata_level, note, source_url)
dim_constraints(code, curfew, pax_cap, cap_expiry, land_locked, perimeter_rule,
                settlement_note, feasibility_adj, source_url)
dim_capacity_profile(code, config, vmc_arr_rate, imc_arr_rate, vmc_dep_rate,
                     imc_dep_rate, asv_annual, asv_source)

fact_segment_monthly(year, month, carrier, origin, dest, aircraft_type,
                     service_class, departures_performed, departures_scheduled,
                     seats, passengers, distance_mi)
agg_hourly_departures(code, hour_of_day, dow, n_departures, avg_seats)
agg_delay_monthly(code, year, month, taxi_out_p50, taxi_out_p90,
                  dep_del15_rate, cancel_rate, mean_dep_delay)
fact_forecast(code, fiscal_year, enplanements, operations, source)

mart_airport_annual(code, window_end, pax, seats, deps, ops, slf, gauge,
                    lh_share, intl_share, n_destinations, cagr_pax_5y,
                    cagr_gauge_3y, cagr_deps_3y, peak_hr_deps, peaking, php,
                    taxi_out_p50, del15_rate, dc_ratio, asv, asv_source,
                    confidence, data_vintage)
mart_scores(code, profile, saturation, unmet_demand, growth, feasibility,
            monetization, composite, tier, rank_overall, rank_in_class)
```

**Store raw metrics and scores separately.** Re-scoring with new weights must not require re-running the ETL — the `weights` argument on `rank_airports` depends on it.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/chat` | **SSE stream.** Body `{message, history[], state{}, voice_mode}`. Emits `tool_trace` / `token` / `done`. |
| `POST` | `/transcribe` | Optional Groq Whisper STT (multipart audio) |
| `GET` | `/airports?region=&state=&hub_class=` | Candidate lookup |
| `GET` | `/airport/{code}` | Full KPI sheet |
| `POST` | `/rank` | Deterministic ranking — **works with no LLM at all** |
| `POST` | `/compare` | Side-by-side |
| `GET` | `/explain/{code}?profile=` | Pillar contribution breakdown |
| `POST` | `/sensitivity` | Rank-stability bands |
| `GET` | `/meta` | Data vintages, row counts, config, active assumptions |

Exposing the deterministic endpoints separately from `/chat` is itself a design statement: **the analytics are a product, the chat is an interface onto them.** It also means you can demo the scoring even if your LLM key dies.

## SSE contract
```
event: tool_trace
data: {"name":"rank_airports","args":{...},"result_summary":{...},"ms":42}

event: token
data: {"t":"BDL "}

event: done
data: {"evidence":{"table":[...],"assumptions":{...},"confidence":"medium",
       "data_vintage":{...}},"speech_text":"...","state":{...}}
```

## Testing — the four that matter
1. `test_scoring.py` — pure-function tests on a fixed 10-airport fixture. Golden values, no network, no LLM.
2. `test_backtest.py` — the FAA Level 2/3 validation from `02-scoring-methodology.md`. **This is your headline test.**
3. `test_tools.py` — each tool returns valid schema, includes assumptions, handles unknown codes.
4. `test_spill.py` — spill solver monotonicity: higher load factor ⇒ higher spill; converges; degenerate cases don't explode.

Skip agent-loop integration tests. They're slow, flaky, and not what's being graded.

## Config
```
LLM_PROVIDER=groq
GROQ_API_KEY=...
LLM_MODEL=...
LONG_HAUL_NMI=2500
SCORE_WEIGHTS='{"saturation":0.30,"unmet_demand":0.25,"growth":0.20,"feasibility":0.15,"monetization":0.10}'
DUCKDB_PATH=data/airports.duckdb
```
Every assumption is config, and `/meta` echoes it. When someone asks "what if long-haul were 3,000 nmi?", the answer is a parameter change the agent can make mid-conversation — not a code change.
