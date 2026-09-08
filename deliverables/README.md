# Deliverables — Airport Investment Intelligence Agent

This folder is the submission set. Every claim in it was verified by running
the code on **2026-09-08**; the commands and their raw output are in
[07-VERIFICATION-EVIDENCE.md](07-VERIFICATION-EVIDENCE.md).

## Start here

| # | File | What it is |
|---|------|-----------|
| — | **[00-EXPLANATION.md](00-EXPLANATION.md)** | **The one to read first.** Does the build meet every requirement, and *how* — in plain language, with evidence. |
| 01 | [01-SOURCE-CODE.md](01-SOURCE-CODE.md) | Deliverable 1: the source code — what is where, how to run it, how to check it |
| 02 | [02-DESIGN-AND-ARCHITECTURE.md](02-DESIGN-AND-ARCHITECTURE.md) | Deliverable 2: system design and data flow |
| 03 | [03-SCORING-METHODOLOGY.md](03-SCORING-METHODOLOGY.md) | Deliverable 2a: the scoring methodology, formula by formula |
| 04 | [04-KEY-TRADEOFFS.md](04-KEY-TRADEOFFS.md) | Deliverable 2b: key tradeoffs and what was given up |
| 05 | [05-WHERE-AI-IS-USED.md](05-WHERE-AI-IS-USED.md) | Deliverable 2c: exactly where and how AI is used — and where it is forbidden |
| 06 | [06-REQUIREMENTS-COMPLIANCE.md](06-REQUIREMENTS-COMPLIANCE.md) | Requirement-by-requirement matrix with file/line evidence |
| 07 | [07-VERIFICATION-EVIDENCE.md](07-VERIFICATION-EVIDENCE.md) | The raw audit: commands run, output produced |
| 08 | [08-GAPS-RISKS-AND-FIXES.md](08-GAPS-RISKS-AND-FIXES.md) | Honest limitations, known defects, and what to fix first |

## The short answer

**Yes — the build satisfies all four functional requirements, both stated
deliverables, and the voice bonus.** It answers all four sample questions
correctly against real BTS data, ranks deterministically without any LLM
involvement, and discloses its own uncertainty.

Three things a reviewer should know up front, because the build does not hide
them and neither should this page:

1. **Traffic data is real; operational data is not loaded.** 624 airports and
   52,649 routes come from BTS T-100. But BTS On-Time Performance was never
   loaded, so taxi-out times, delay rates and peak-hour concentration are NULL
   for every airport. The scoring engine detects this and reports 71–78%
   input coverage with a "medium" confidence label rather than pretending.
2. **Feasibility is hand-curated for 21 of 624 airports.** The other 603 get a
   size-based prior. Feasibility carries 15–17% of the weight.
3. **Percentile ranking is national.** A modest regional airport at 11% of its
   Annual Service Volume still lands in the 87th percentile of saturation,
   because most of the 624-airport cohort is tiny. The FAA tier catches this
   (it correctly reports "Tier D — no capacity case"), but the composite score
   does not. See [08-GAPS-RISKS-AND-FIXES.md](08-GAPS-RISKS-AND-FIXES.md).

None of these break a requirement. All three are disclosed by the running
system at answer time, which is itself one of the requirements.
