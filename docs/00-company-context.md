# 00 — Who Wonderful is, and why it changes your design

## The company

Wonderful is an Israeli-founded AI company (founded early 2025) building **enterprise customer-service AI agents that run across voice, chat and email, in every market and every language**. Trajectory:

| Date | Event |
|---|---|
| Jul 2025 | Out of stealth, $34M seed |
| Nov 2025 | $100M Series A (Index Ventures) |
| Mar 2026 | $150M Series B at **$2B** valuation |
| Sep 2026 | ~$550M Series C at **$5B** valuation (Insight Partners; Salesforce invests) |

Reported traction: agents handling tens of thousands of customer requests daily at roughly an **80% resolve rate**. Investors include Index, IVP, Bessemer, Vine, 9Yards, Insight, Salesforce.

> Verify the latest numbers before your interview — this space moves monthly. Sources at the bottom.

## What this implies for your submission

This is not a generic "build a chatbot" assignment. It is being graded by people who build production agents for a living. Five consequences:

**1. Voice is not a throwaway bonus — it's their core product surface.**
The brief says "(voice is a bonus)". For this company, shipping voice signals you understand their business. But shipping *bad* voice is worse than none. Do the cheap version well (see `05-voice.md`) and be ready to talk fluently about the STT→LLM→TTS pipeline vs. native speech-to-speech, barge-in, and end-of-turn detection. Knowing the tradeoffs matters more than the code.

**2. They will judge your agent architecture, not your data science.**
Tool design, when the model calls what, how you keep it from hallucinating numbers, how you handle multi-turn state, what happens when a tool fails. Make the agent loop legible and small. Do not hide it inside a framework you can't explain line by line.

**3. "80% resolve rate" is their language — they care about reliability under ambiguity.**
Handle the messy cases visibly: "LA airport" is ambiguous (LAX/BUR/LGB/ONT); "New England" needs a definition; "long haul" has no standard. An agent that asks one good clarifying question, or states its assumption and proceeds, is doing the thing they sell.

**4. Enterprise = data governance instincts.**
Mention it once, briefly: free Gemini tiers may train on your prompts; a real deployment would use a paid/no-training tier or self-host. One sentence shows the instinct without derailing the demo.

**5. Multilingual is their differentiator.**
You don't need to build it. But "the tool layer is language-independent; only the narration prompt is localized, so adding Spanish is a prompt change not a rewrite" is a strong throwaway line.

## What "profitable renovation" means to an investor (frame the whole thing this way)

The brief says: *identify airports where renovations will be most profitable based on increased flight and passenger capacity.* Decompose it:

```
Investment attractiveness ≈  (demand that is currently being turned away)
                           × (ability to monetize the unlocked traffic)
                           ÷ (difficulty / cost / risk of building it)
```

Three failure modes you should explicitly avoid, and say so out loud:

- **Ranking by size.** ATL is the biggest airport; that does not make it the best investment. Size ≠ opportunity.
- **Ranking by congestion alone.** LGA is jammed *and* nearly impossible to expand (land-locked, noise-constrained). Congestion without buildability is a trap. This is why the score must include a **feasibility discount** — it's the single most "investor-brained" part of your model.
- **Ignoring why demand is suppressed.** An airport can look "under capacity" because a legal settlement caps its passengers (see SNA/John Wayne in `11-demo-questions.md`). That's latent demand, not weak demand.

If you say only one thing in the interview, say this: *"Congestion tells you where the pain is. Feasibility tells you where you can actually build. Profit lives at the intersection, and most naive rankings only compute the first one."*

## Sources
- [Wonderful raises $150M Series B at $2B valuation — TechCrunch](https://techcrunch.com/2026/03/12/wonderful-raises-150m-series-b-at-2b-valuation/)
- [Wonderful more than doubles its valuation to $5B — TechCrunch](https://techcrunch.com/2026/09/02/wonderful-more-than-doubles-its-valuation-to-5b-in-under-6-months/)
- [Wonderful raised $100M Series A — TechCrunch](https://techcrunch.com/2025/11/11/wonderful-raised-100m-series-a-to-put-ai-agents-on-the-front-lines-of-customer-service/)
- [Index Ventures — Wonderful secures $100m](https://www.indexventures.com/perspectives/wonderful-secures-100m-to-drive-adoption-of-ai-agents-globally/)
- [AI Business — valued at $2 billion](https://aibusiness.com/agentic-ai/ai-customer-support-startup-valued-at-2-billion)
