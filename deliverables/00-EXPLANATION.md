# Does this build meet the assignment? Yes — here is exactly how

*Audit performed 2026-09-08 by running the system, not by reading its README.
Every number below came out of a command; the commands are in
[07-VERIFICATION-EVIDENCE.md](07-VERIFICATION-EVIDENCE.md).*

---

## 1. The verdict in one table

| The assignment asked for | Status | The one-line proof |
|---|---|---|
| Use public APIs to gather airport/aviation data | ✅ Met | 324 MB of real BTS T-100 downloaded; 624 airports, 52,649 routes in the database |
| Rank or compare airports on defined logic / KPI | ✅ Met | 5 pillars → weighted **geometric** mean → FAA tier; 4 named profiles |
| Explain its reasoning clearly | ✅ Met | `explain_score` attributes the score pillar-by-pillar in log space; every answer carries sources, vintage and assumptions |
| Support conversational follow-up | ✅ Met | "Why did you rank **the first one** above Boston?" resolved to PWM with no airport named |
| **Deterministic scoring, not only LLM output** | ✅ Met | `POST /rank` produces a full ranking with the LLM switched off — 5 identical SHA hashes across 5 calls |
| **Chat interface** | ✅ Met | Web UI on `:8000` with streamed answers, conversation history, tool trace |
| Voice *(bonus)* | ✅ Met | Speech-to-text + text-to-speech + barge-in turn-taking; 38 dedicated tests |
| Communicate assumption, uncertainty, scoping | ✅ Met | Assumption registry, per-answer confidence with named reasons, 400-draw weight sensitivity, explicit scope guard |
| **Deliverable: source code** | ✅ Met | 7,687 lines Python + 3,045 lines web; 203 tests, all passing |
| **Deliverable: design/architecture doc** | ✅ Met | `airport-agent/DESIGN.md` + files 02–05 in this folder |

**All ten line items are met.** The rest of this document explains *how*, and
then tells you the three things that are weaker than the headline suggests —
because the assignment also asked the agent to communicate uncertainty, and
that obligation extends to this document.

---

## 2. How each requirement is met

### 2.1 "Use public APIs to gather airport/aviation data"

Four public sources, all free, no paid tier:

| Source | What it provides | How it is fetched | Status |
|---|---|---|---|
| **OurAirports** (`davidmegginson.github.io/ourairports-data`) | Every US airport: identity, city, state, lat/lon, type, plus full **runway geometry** | Plain HTTPS CSV download, `etl/build.py:32-33` | ✅ Real, 12.7 MB + 4.0 MB |
| **BTS T-100 Segment (All Carriers)** via TranStats | Every nonstop segment flown: passengers, seats, departures, distance — the spine of the whole system | BTS publishes no API, so `etl/fetch_t100.py` drives the ASP.NET form: fetch viewstate tokens, POST the selection, receive a ZIP | ✅ Real, 152 MB (2019) + 172 MB (2024) |
| **Tavily** or **Brave Search** API | Announced capital programmes — *qualitative context only* | `api/websearch.py` | ⚪ Optional, no key set; tool self-reports unavailable |
| **FAA / OCAIR published filings** | Slot levels, settlement agreements, curfews, perimeter rules | Hand-transcribed into `etl/curated/*.csv` with a source URL per row | ⚠️ 21 airports only |

The important honesty point: **BTS has no REST API.** The assignment says "use
public APIs"; the most important public aviation dataset in the US is
distributed through a web form. The build automates that form rather than
substituting an easier but less relevant source, and documents that the
scraper will break if BTS changes the form.

**Verified:** the database reports `data_mode: "real"`,
`traffic_source: "BTS T-100 Segment (All Carriers), real"`, 624 airports,
52,649 routes, window year 2024.

---

### 2.2 "Rank or compare airports based on your defined logic or KPI"

The KPI is a composite of **five pillars**, each normalised to (0,1]:

| Pillar | What it measures | Default weight |
|---|---|---|
| **Saturation** | How full the airport already is | 0.30 |
| **Unmet demand** | Demand being turned away or legally suppressed | 0.25 |
| **Growth** | How fast throughput is rising | 0.20 |
| **Feasibility** | Whether you can physically build there | 0.15 |
| **Monetization** | Whether the traffic mix pays for the build | 0.10 |

Two design decisions do the real work:

**(a) The aggregation is a weighted *geometric* mean, not an arithmetic one.**

```
Score = 100 × Π (pillar_i ^ w_i)
```

A geometric mean is *partially non-compensatory*: a near-zero pillar drags the
whole score down and cannot be bought off by strength elsewhere. This is not a
stylistic preference — it is the difference between a useful ranking and a
useless one. Under an arithmetic mean, **LaGuardia** — the most congested
airport in the US and one of the worst places on earth to spend expansion
capital, with a curated feasibility of **0.08** — would rank at or near the
top. Congestion tells you where the pain is; feasibility tells you where you
can actually build. The geometric mean forces both to be true at once.

**(b) The tiering is not mine — it is the FAA's.**

FAA Advisory Circular 150/5060-5 publishes capacity planning triggers against
Annual Service Volume: **start planning at 60% of ASV, start building at 80%**.
The agent applies those thresholds rather than inventing its own:

| Tier | Trigger | Meaning |
|---|---|---|
| **A** | demand/ASV ≥ 0.80 | Build now |
| **B** | ≥ 0.60 | Plan now |
| **C** | ≥ 0.45 | Monitor |
| **D** | < 0.45 | No capacity case |

This converts "my opinion about which airport is congested" into "the
regulator's published rule, computed from data". It is also what lets the
agent contradict its own composite score when the two disagree — and it did
exactly that during the audit (see §4.3).

**Four named profiles** re-weight the pillars per question type, because one
ranking cannot answer every question. Each profile is echoed in every response
so the user always knows which lens produced the answer:

- `investment` (default) — where capital pays off
- `terminal` — terminal expansion; leans on peak-hour and growth, per FAA AC 150/5360-13A
- `congestion` — pure congestion, 70/30 saturation/unmet demand, no growth or feasibility
- `airfield` — runway-side constraint

**Verified:** `congestion` correctly tops New England with **BOS**; `terminal`
tops it with **PWM**. Different questions, different answers, same data.

---

### 2.3 "Explain its reasoning clearly"

Three layers, all of which I exercised:

1. **Score attribution.** Geometric contributions are not additive in level
   terms, so `explain_score` reports the **log contribution share**, which *is*
   additive, and flags any pillar below 0.35 as actively dragging the score.
2. **Tier rationale in words.** Every tier carries the FAA sentence that
   justifies it, not just a letter.
3. **Provenance travels with the number.** Every tool returns `assumptions`,
   `data_vintage` and `sources` *alongside* the data, so the model physically
   cannot quote a figure without its caveat also being in context.

A real answer the system produced, unedited:

> SFO has an estimated **2,969,153 passengers turned away** (about 10.5% of
> estimated unconstrained demand), driven by: … **Runway geometry / weather
> (Measured):** the widest parallel runway pair is ~750 ft apart, well below
> the ~4,300 ft required for independent simultaneous instrument approaches…
>
> *Epistemic note:* Load factor, taxi-out times, slot level and runway geometry
> are **measurements**. That the airport turns away demand is an **inference**
> derived from them. How much of that suppressed demand would actually
> materialise if capacity were added remains **unknown** without loaded fare
> and O&D data (BTS DB1B).

That last paragraph — separating *measured*, *inferred* and *unknown* — is the
single clearest evidence that the reasoning requirement is met rather than
gestured at.

---

### 2.4 "Support conversational follow-up questions"

Conversation state is threaded through every turn. Verified live:

| Turn | Question | What the agent did |
|---|---|---|
| 1 | "Which airports in New England are strong candidates for terminal expansion?" | Ranked the region |
| 2 | "Why did you rank **the first one** above Boston?" | Resolved *the first one* → **PWM**, called `explain_score(PWM)`, compared against BOS |
| 3 | "What about **it** makes you uncertain?" | Resolved *it* → BOS, reported confidence **0.53** and named the three reasons |
| 4 | "Compare **it** to Providence." | Called `compare_airports` carrying the prior airports forward |

No airport code was spoken in turns 2–4. The references resolved from context.

---

### 2.5 "Include some deterministic scoring or ranking logic (not only LLM output)"

This is the requirement most easily faked, so it is worth being precise about
how the build satisfies it.

**The LLM never performs arithmetic.** Every number the user sees is computed
in Python, in `api/scoring/`, from the database. The model's only jobs are to
*choose which tool to call*, *set its parameters*, and *narrate the result*.

Three independent pieces of evidence:

1. **The ranking runs with the LLM switched off.** `POST /rank` returns the
   complete scored, tiered, confidence-annotated ranking through a pure Python
   path that never touches a model. The web UI's ranking, the CLI, and the
   tests all exercise it.
2. **It is bit-for-bit deterministic.** Five identical requests produced five
   identical SHA hashes (`c3d35f8af2519e63` ×5). No sampling, no temperature,
   no model in the path.
3. **A numeric guard catches fabrication.** After every answer,
   `numeric_guard` extracts every figure ≥100 from the model's prose and
   checks it appears in some tool's output, tolerating comma-grouping and
   rounding. Anything unmatched is flagged. Tested directly: given a tool
   output containing `21280480`, the sentence *"BOS handled 21,280,480
   passengers and 999,777 cargo tonnes"* correctly flagged **`999,777`** and
   passed the real figure.

The guard also distinguishes *unverified* from *externally sourced* — a figure
from a press release is traceable, but to a publisher rather than to our own
code, and folding the two together would make the guard certify the exact
thing it exists to catch.

**There is also a complete keyless fallback.** If no API key is configured, a
hand-written rule-based planner (`api/agent/providers.py`, 764 lines) routes
questions to the same tools. The app is fully functional with no LLM at all —
it simply narrates less fluently.

---

### 2.6 "Include a chat interface to talk with the agent (voice is a bonus)"

**Chat:** a single-page web UI served at `http://127.0.0.1:8000` — streamed
token-by-token answers, markdown tables rendered whole, conversation history in
a sidebar, light/dark theme, suggested questions, and a developer toggle that
exposes the raw tool trace (name, arguments, timing, result) so the
deterministic layer stays demonstrable rather than merely claimed. A terminal
client (`ask.py`) offers the same thing without a browser.

**Voice — the bonus, and it is genuinely implemented, not stubbed:**

- **Speech in:** `SpeechRecognition` / `webkitSpeechRecognition`
- **Speech out:** `speechSynthesis` by default; if `ELEVENLABS_API_KEY` or
  `OPENAI_API_KEY` is set, `POST /speak` proxies a neural voice **server-side**
  so the key never reaches the browser
- **Turn-taking:** a dedicated 307-line module handling barge-in, the three
  different reasons `SpeechRecognition` fires `end`, and Chrome's habit of
  silently stopping `speechSynthesis` after ~15 seconds
- **A full voice-conversation mode**, separate from push-to-talk

38 of the 203 tests cover turn-taking alone.

---

### 2.7 "Clearly communicate assumption, uncertainty and scoping"

**Assumptions** are centralised in `config.assumption_registry()` and attached
to every substantive answer. The best example is long-haul distance:

> No ICAO/IATA standard exists for "long haul". Industry usage spans roughly
> 2,200–2,600 nmi; ICAO and IATA both define by flight time and disagree with
> each other. This threshold is configurable.

The agent does not assert a fact that does not exist. It states a choice
(2,500 nmi), names it as a choice, and exposes it as an environment variable.

**Uncertainty** is quantified, not hand-waved. Every ranked result carries a
confidence score built from three inspectable terms — input coverage (50%),
capacity-denominator quality (20%), and data recency (30%) — with the reasons
spelled out in English:

> `only 71% of scoring inputs are backed by data` ·
> `capacity denominator is runway_config, not a published FAA profile` ·
> `data is about 27 months old`

That is the system reporting its own weaknesses, unprompted, at answer time.

**Weight sensitivity** goes further. A 400-draw Dirichlet perturbation around
each profile's weights re-ranks the cohort and reports how far each airport
moves:

> "BGR ranks first in **50%** of weight draws — the leader is likely but not
> certain under other weightings."

with per-airport p10–p90 rank bands and a `stable` flag. BDL was correctly
marked **unstable** (p_top1 0.28, band 1–5). Most submissions ship a ranked
list with false precision; this one ships a ranking that knows how fragile it is.

**Scoping** is enforced, not just documented. Out-of-scope questions are
refused with a plain explanation and a redirect, and a question naming an
unresolvable place is *never* silently answered nationally — because a
confident answer to a question the user did not ask is worse than admitting
the miss.

---

## 3. The two stated deliverables

**Source code** — `airport-agent/`, 7,687 lines of Python (zero third-party
dependencies in the analytics path; LangChain only for the optional model
layer) plus 3,045 lines of web. 126 Python tests and 77 JavaScript tests,
**all 203 passing**. Details in [01-SOURCE-CODE.md](01-SOURCE-CODE.md).

**Design / architecture document** — `airport-agent/DESIGN.md` already covers
this. Because the assignment named three specific things it must explain, this
folder splits them out so each can be checked off directly:

- Scoring methodology → [03-SCORING-METHODOLOGY.md](03-SCORING-METHODOLOGY.md)
- Key tradeoffs → [04-KEY-TRADEOFFS.md](04-KEY-TRADEOFFS.md)
- Where/how AI is used → [05-WHERE-AI-IS-USED.md](05-WHERE-AI-IS-USED.md)

---

## 4. All four sample questions, answered live

Each ran end-to-end through the real agent against real data.

### 4.1 "Which airports in New England are strong candidates for terminal expansion?"

Tools called: `list_airports` → `rank_airports(terminal)` → `explain_score` →
`rank_airports(hub_class=L)`. The agent ranked PWM and BGR top on the terminal
profile, then **immediately undercut its own ranking**:

> …both sit in FAA Tier D ("No capacity case") because their annual operations
> are below 45% of Annual Service Volume, meaning any investment case must rest
> on passenger experience or commercial yield rather than airfield capacity.

It then surfaced BOS separately as the region's large hub, with feasibility
0.35 "due to its landlocked peninsular site". That is the deterministic FAA
tier overriding the composite score in the narrative — the behaviour you want.

### 4.2 "Compare LA and Santa Ana airport congestion levels."

"LA" resolved through the metro alias table to the five-airport Los Angeles
group, then narrowed to LAX vs SNA.

- **LAX** — Tier B (Plan now), demand/ASV **0.69**, FAA Level 2
- **SNA** — Tier D, demand/ASV **0.44**

And then the insight that makes the comparison worth reading:

> SNA's low ratio is misleading: it operates under a legal settlement agreement
> with Newport Beach enforcing an annual passenger cap, a daily departure cap
> and a night curfew extended through 2035. **LAX congestion is physical and
> operational, offering viable terminal upside. SNA congestion is legally
> mandated; added capacity cannot be monetised without renegotiating the
> settlement.**

That distinction comes from the curated constraints file, and it is exactly the
kind of thing that separates an investable conclusion from a number.

### 4.3 "What is the percentage of long haul flights out of Anchorage airport?"

> **2.5%** — 1,083 of 42,816 departures.

With the denominator shown, the 2,500 nmi threshold disclosed as a
configurable assumption, and — critically — this caveat:

> **Cargo exclusion:** Only scheduled passenger service is counted. All-cargo
> operations are excluded. **This matters significantly for Anchorage**, where
> including freighters would change the long-haul share substantially.

Anchorage is one of the largest cargo hubs on earth. An agent that reported
2.5% without that sentence would be technically correct and practically
misleading. This one caught it.

### 4.4 "What is the unmet flight demand in SFO airport and why?"

> ~**2,969,153 passengers** turned away, ≈10.5% of estimated unconstrained demand.

With four drivers, each tagged *Measured* or *Inferred*: IATA Level 2
administrative suppression; spill at 83.2% seat load factor; upgauging at
5.15%/yr (airlines adding seats via larger aircraft rather than more flights —
a classic capacity-constraint symptom); and runway geometry (750 ft parallel
separation against the ~4,300 ft needed for independent IFR approaches,
discounting effective ASV by 15% in low visibility).

The spill figure is not invented: it inverts the standard airline revenue-
management identity (Belobaba, MIT 16.75J) — *mean demand = observed load +
spill* — by bisection, and the module's own docstring states that applying it
to annual aggregates makes the estimate **conservative**.

---

## 5. Three things weaker than the headline

The assignment asks the agent to communicate uncertainty. That obligation
applies to this document too.

**5.1 Operational data was never loaded.** `taxi_out_p50`, `del15_rate` and
`peaking` are NULL for all 624 airports — BTS On-Time Performance is not in the
build. The saturation pillar therefore rests on demand/ASV alone. This bites
hardest on the `terminal` profile, which intends to weight peak-hour
concentration at **0.50** of its saturation mix and instead gets nothing from
it: coverage drops to **71%**. The system detects and reports this correctly,
which is the right behaviour — but a reviewer should know that "congestion" in
this build means "demand against capacity", not "measured delay".

**5.2 Feasibility is curated for 21 of 624 airports.** The remaining 603 get a
size-based prior (large 0.55 / medium 0.75 / small 0.80). Feasibility carries
15–17% of the weight and is the pillar that stops the geometric mean from
crowning LaGuardia — so it matters more than its weight suggests. It is
trustworthy for the ~21 airports an analyst has actually looked at, and a
placeholder everywhere else.

**5.3 Percentile ranking is against the national cohort, which flatters small
airports.** PWM sits at **11%** of its Annual Service Volume — genuinely
uncongested — yet lands in the **87th percentile** of saturation, because most
of the 624-airport cohort is smaller still. That is why PWM (1.2 M passengers)
outranks BOS (21.3 M) on the terminal profile. The FAA tier catches it and the
agent said so out loud, but the composite score does not. Ranking within a
peer cohort (hub class or size band) rather than nationally would fix it.

There is also one **data-modelling bug** worth fixing before this is shown to
an investor: `hub_class` is derived from OurAirports' *physical airport type*,
not the FAA hub category. 20 airports labelled `L` have under 2 M passengers —
one has 20,028. In New England, BOS, BDL, PVD **and** PWM are all labelled `L`,
whereas by FAA definition only BOS is a large hub. Full detail and a fix in
[08-GAPS-RISKS-AND-FIXES.md](08-GAPS-RISKS-AND-FIXES.md).

---

## 6. What was fixed during this audit

| Issue | Severity | Action |
|---|---|---|
| A **live Google API key** was committed in `airport-agent/.env.example`, which is *not* gitignored | 🔴 High | Replaced with a commented placeholder. **The key was exposed and should be rotated at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).** |
| Root `README.md` claimed the build ships on synthetic traffic | 🟠 Medium | Corrected — traffic is real BTS T-100 |
| Both READMEs claimed "45 tests" | 🟠 Medium | Corrected to 126 Python + 77 JS |
| `DESIGN.md` listed "load real BTS T-100" as future work | 🟠 Medium | Marked done; narrowed to the On-Time Performance gap that genuinely remains |

Backups of every edited file are in the job's tmp directory.

---

## 7. Bottom line

The build does what the assignment asked, and the parts that are hard to fake —
deterministic scoring anchored to a published federal standard, a numeric guard
that makes hallucinated figures structurally detectable, quantified uncertainty
with named reasons, and an agent willing to contradict its own ranking when the
regulator's threshold disagrees — are the parts that are strongest.

The weaknesses are real but they are **disclosed by the running system at
answer time**, which is the behaviour the assignment asked for. An agent that
says "71% of my inputs are backed by data" is more useful to an investment
committee than one that reports a score to one decimal place and stays quiet.
