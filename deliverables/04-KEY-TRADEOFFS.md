# Deliverable 2b — Key Tradeoffs

*Required by the assignment: "a short design/architecture document explaining:
… **key tradeoffs**".*

Every row is a decision that could reasonably have gone the other way. The
"what it costs" column is the point of this document — a tradeoff with no cost
was not a tradeoff.

---

## 1. Methodology tradeoffs

### 1.1 Geometric mean over arithmetic mean

**Chose:** weighted geometric mean of the five pillars.

**Why:** an arithmetic mean is fully compensatory — extreme congestion can buy
off zero buildability. Verified on the real weights: an unbuildable but
maximally congested airport scores **80.5** arithmetic vs a buildable moderate
one at **71.2**, and the ranking **reverses** under a geometric mean (64.5 vs
70.4). LaGuardia's real demand/ASV in this database is 1.43 against a
feasibility of 0.08. An arithmetic model recommends it. That model is wrong.

**What it costs:**
- Harder to explain to a non-technical committee. Mitigated by reporting
  **log-space contribution shares**, which *are* additive, in `explain_score`.
- Needs a floor (0.01) or a single zero annihilates the score — an arbitrary
  constant introduced purely to make the math behave.
- Contributions are not decomposable in level terms, so "this pillar cost you
  12 points" is not strictly available.

**With more time:** benchmark against PROMETHEE or ELECTRE, which handle
non-compensatory ranking with an explicit outranking relation rather than an
exponent trick.

---

### 1.2 Percentile rank within a cohort, over absolute normalisation

**Chose:** winsorise (5th–95th) then percentile-rank, per OECD/JRC.

**Why:** indicators arrive on wildly different scales (a ratio, minutes, a
share, a count). Percentile rank makes them comparable and interpretable —
"96th percentile of saturation among this cohort" means something to an
analyst; "0.82 saturation" does not.

**What it costs — and this is the largest methodological cost in the build:**

Percentile rank **destroys magnitude**. It says *where* an airport sits in the
distribution, not *how far apart* the airports are. Because the cohort is the
**national set of 624 airports** and most of them are small, a modest regional
airport is flattered:

> **PWM** operates at **11% of its Annual Service Volume** — objectively
> uncongested — yet ranks in the **87th percentile** of saturation nationally.
> That is why PWM (1.2 M passengers) outranks BOS (21.3 M) on the terminal
> profile.

The FAA tier is the designed backstop and it works — PWM is correctly reported
as **Tier D, "no capacity case"**, and the agent said so unprompted. But the
composite *score* does not know this.

**With more time:** rank within a peer cohort (hub class or size band), and
report rank *alongside* a standardised magnitude so both survive.

---

### 1.3 Hand-set weights over data-derived weights

**Chose:** five profiles with explicitly declared weights.

**Why:** PCA and factor-analytic weighting optimise for *variance explained*,
not for *investment relevance*. A weight of 0.30 on saturation is a judgment,
and stating it as a judgment is more honest than deriving it from an
eigenvector and calling it objective.

**What it costs:** they are my judgment. Mitigated — not eliminated — by the
400-draw Dirichlet **sensitivity analysis**, which reports how much the answer
depends on them. On New England, BGR leads in only **50%** of weight draws, and
BDL is explicitly flagged unstable (p10–p90 rank band 1–5).

**With more time:** budget-allocation elicitation with the actual investment
committee, then report the ranking under each partner's weights.

---

### 1.4 Feasibility as a hand-curated pillar

**Chose:** an analyst judgment in [0,1], sourced per airport from published
filings.

**Why:** buildability is genuinely not in any dataset. It lives in settlement
agreements, perimeter rules, curfews and site geography. SNA's constraint is a
1985 agreement with Newport Beach; no API returns that.

**What it costs:** curated for **21 of 624 airports (3.4%)**. The other 603 get
a size-based prior (large 0.55 / medium 0.75 / small 0.80) flagged as
`default_by_type`. Since feasibility is the pillar that stops the geometric
mean from crowning LaGuardia, it matters more than its 0.15 weight implies —
and it is trustworthy only for the airports someone actually looked at.

**With more time:** parse NPIAS submissions and FAR Part 150 noise filings to
derive it systematically.

---

### 1.5 Spill model applied to annual aggregates

**Chose:** Belobaba's spill identity, inverted by bisection on annual
airport-level totals.

**Why:** observed traffic understates demand exactly where capacity binds, so
using it raw would systematically under-rank the most investable airports.

**What it costs:** the model is properly a per-departure construct. Aggregating
to the year first averages away the peaks where spill actually happens, so
these estimates are **conservative** — they understate true spill. The normal
distribution also fits the extreme upper tail poorly, and K = 0.35 is imported
from the literature rather than estimated from this data. All three are stated
in the module's own docstring.

**With more time:** apply per segment-month and sum; fit K from observed
data; test a gamma tail.

---

## 2. Architecture tradeoffs

### 2.1 Offline ETL into SQLite, not live API calls

**Why:** determinism (identical questions must give identical numbers), latency
(T-100 is a 172 MB CSV), and a single honest vintage stamp.

**What it costs:** staleness. The window is 2024 and today is 2026 — the
confidence score docks every airport for it by name ("data is about 27 months
old"). The system knows it is stale; it just cannot be fresher without a
refresh job.

---

### 2.2 Standard library only in the deterministic path

**Why:** no version drift in the scoring layer, trivially unit-testable, runs
on a bare interpreter, and a reviewer can read every line that produces a
number without chasing a dependency.

**What it costs:** no pandas ergonomics in the ETL, hand-rolled percentile and
normal-CDF functions, a hand-rolled `.env` reader, and a hand-rolled HTTP
server. More code to own — 7,687 lines, some of which a library would have
provided.

---

### 2.3 Two agent paths (LangGraph + a keyless planner) instead of one

**Why:** the app must be fully functional with no API key, so the deterministic
half stays demonstrable and a reviewer with no key can still exercise it.

**What it costs:** **two implementations to keep in sync**, and the 764-line
rule-based planner is the single largest module in the codebase. The cost
showed up concretely during the audit: when the LLM call failed transiently
mid-conversation, the fallback took over and its scope guard **refused a
legitimate follow-up** ("What about it makes you uncertain?") because the
sentence contains no aviation vocabulary. The graph path handles it fine. See
[08-GAPS-RISKS-AND-FIXES.md](08-GAPS-RISKS-AND-FIXES.md).

---

### 2.4 SSE rather than WebSockets

**Why:** one-way streaming over plain HTTP, no extra dependency, works through
any proxy.

**What it costs:** no bidirectional audio, so native speech-to-speech is off
the table. Voice is therefore browser-side STT → HTTP → browser-side or proxied
TTS, which adds latency versus a duplex audio stream.

---

### 2.5 Browser Web Speech API as the default voice

**Why:** free, no key, cannot blow a quota mid-demo, ~40 lines.

**What it costs:** Firefox is unsupported; Chrome ships the audio to Google;
and the built-in voices are the reason synthetic speech still sounds synthetic.
Mitigated by an optional server-side proxy to ElevenLabs or OpenAI TTS, keyed
so the key never reaches the browser.

---

### 2.6 Showing the tool trace at all

The interface brief says *do not show technical agent logs*. That collides head-on
with the assignment's requirement to demonstrate deterministic scoring rather
than raw LLM output.

**Resolution:** move the proof from a stack trace to things a person can read —
human-readable progress steps ("Estimating spill against capacity"), a score
card showing each pillar and its weight, source pills, and an assumptions
disclosure. The raw tool calls stay one toggle away in Settings.

The user sees an expert thinking. The reviewer can still audit every number.

---

## 3. Scope tradeoffs — what was deliberately not built

| Not built | Why not |
|---|---|
| Vector store / RAG | The questions are quantitative. Retrieving numbers approximately when SQL retrieves them exactly is strictly worse. |
| Fine-tuning | The model's job is tool selection and narration. Prompting plus hard argument validation covers it. |
| Frontend framework | No build step means a reviewer opens one file. |
| Cargo analysis | T-100 carries it, but the investment thesis here is passenger terminals. **Called out explicitly in the Anchorage answer**, where excluding freight materially changes the result. |
| Non-US airports | Scope is US commercial-service. The FAA thresholds the whole model is anchored to do not apply elsewhere. |
| Financial modelling (IRR, capex) | Would require project-level cost data that is not public. The agent ranks *candidacy*, not returns — and says so. |

---

## 4. The one tradeoff I would revisit first

**Percentile-ranking against the national cohort.** It is the only decision in
the build that produces a result an investor would call *wrong on its face* —
a 1.2 M-passenger airport at 11% utilisation outranking Boston for terminal
expansion. Everything else in the list trades polish, coverage or effort.
This one trades correctness, and it is cheap to fix: rank within hub class.
