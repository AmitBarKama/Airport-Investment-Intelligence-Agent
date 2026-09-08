# 06 — LLM provider (you need a free API key)

## Recommendation

**Primary: Groq.** Free, no credit card, instant key, OpenAI-compatible API, tool calling, and it is *fast* — which matters disproportionately once voice is in the loop.
**Fallback: Google Gemini free tier.** Far more generous token throughput; use it if Groq's 1,000 req/day or 6,000 TPM bites.
**Build a 30-line provider interface so switching is one env var.** Do this on hour one — it also protects you if a provider is flaky on demo day.

## Free tiers compared (as of Sep 2026 — verify, these change monthly)

| Provider | Free? | Limits | Speed | Tool calling | Catch |
|---|---|---|---|---|---|
| **Groq** | ✅ no card | ~30 RPM, 6,000 TPM, 1,000 RPD (per model) | **Fastest** — LPU, sub-200 ms TTFT, 3–10× GPU inference | ✅ | Low TPM; long tool results eat it. Adding a card (Developer tier) gives ~10× limits. |
| **Google Gemini** | ✅ no card | **1,500 RPD, 15 RPM, 1M TPM** on 2.5 Flash / Flash-Lite (Pro heavily capped ~50 RPD) | Fast | ✅ solid function calling | ⚠️ **Free-tier prompts may be used for training.** Fine for public data; flag it. |
| **OpenRouter** | ✅ `:free` models | 20 RPM, 1,000 RPD | Varies | Varies by model | Free models rotate out without warning and throttle at peak. `openrouter/free` auto-router mitigates this. Great as a *third* fallback. |
| **Cerebras** | ⚠️ **no longer card-free** | As of Aug 2026: $5 credits after adding a verified card, expiring in 30 days | Extremely fast | ✅ | Was the most generous free tier; that era ended. |
| **Anthropic Claude** | ❌ paid | — | — | ✅ best-in-class | `claude-sonnet-5` $2/$10 per MTok; `claude-haiku-4-5` $1/$5; `claude-opus-5` $5/$25. This whole demo would cost well under $1 — worth it if you have credits. |

**Groq's real constraint is TPM, not RPM.** 6,000 tokens/minute is tight when you're pushing tool schemas + tool results + history every hop. Mitigations: keep tool results compact (return top-N rows, not everything), trim history to the last ~6 turns plus a summary, and don't inline giant JSON blobs the model doesn't need to read.

## Model choice on Groq
Pick a current instruct model with reliable tool calling (`llama-3.3-70b-versatile`, `gpt-oss-120b`, or whatever is current — **check the model list when you sign up; these rotate**). Prefer the largest model that meets your latency budget: tool-call argument accuracy is the failure mode that will actually hurt you, and it degrades fast on small models.

## Getting keys (all ~2 minutes, no card)
- **Groq:** `console.groq.com` → sign in → API Keys → create. Also gives you free Whisper STT (see `05-voice.md`) — one key for both.
- **Gemini:** `aistudio.google.com/apikey` → create. Instant.
- **OpenRouter:** `openrouter.ai/keys` → create; use `:free` model suffixes.

## The provider interface

```python
# api/agent/providers.py
class LLMProvider(Protocol):
    async def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse: ...

# Groq + OpenRouter: OpenAI-compatible, same client, different base_url
#   base_url="https://api.groq.com/openai/v1"
#   base_url="https://openrouter.ai/api/v1"
# Gemini: google-genai SDK, or its OpenAI-compat endpoint
# Anthropic: official `anthropic` SDK — note tool_use blocks differ in shape
```

Normalise to one `LLMResponse{text, tool_calls[], raw}` and the loop never knows which provider it's on. Choose via `LLM_PROVIDER=groq|gemini|openrouter|anthropic`.

> If you use Anthropic: current model IDs are `claude-opus-5`, `claude-sonnet-5`, `claude-haiku-4-5` (no date suffixes). Default to `claude-opus-5`; use adaptive thinking (`thinking={"type":"adaptive"}`) rather than a token budget.

## Cost reality check
This demo is maybe 50–200 LLM calls of a few thousand tokens each. On free tiers: $0. On Claude Sonnet 5: cents. **Do not spend design time on cost optimisation** — spend it on tool-call reliability, which is what actually breaks.

## What to say when asked "why this model?"
*"The model is the most swappable component in the system — it's behind a 30-line interface and one env var. That's deliberate: all the numbers come from deterministic Python, so changing models changes tone, not answers. I picked Groq for latency because voice makes latency user-visible, and Gemini as a fallback because its token throughput is an order of magnitude higher. In production with enterprise data I'd move to a tier with a no-training guarantee."*

## Sources
- [Groq free tier limits 2026](https://www.grizzlypeaksoftware.com/articles/p/groq-api-free-tier-limits-in-2026-what-you-actually-get-uwysd6mb)
- [Groq free tier: 30 RPM, 6K TPM, 14.4K req/day](https://tokenmix.ai/blog/groq-free-tier-limits-2026)
- [Gemini API free tier limits](https://tokenmix.ai/blog/gemini-api-free-tier-limits)
- [Gemini API free tier guide 2026](https://yingtu.ai/en/blog/gemini-api-free-tier)
- [OpenRouter Free Models Router](https://openrouter.ai/docs/guides/routing/routers/free-router)
- [Cerebras free tier changes 2026](https://tokenmix.ai/blog/cerebras-api-key-rate-limits-free-tier-2026)
- [Free AI APIs compared 2026](https://apiscout.dev/guides/free-ai-apis-developers-2026)
