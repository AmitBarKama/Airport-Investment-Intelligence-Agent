# 05 — Voice

Wonderful is a **voice-first** customer-service agent company. This "bonus" is the part of the assignment most aligned with what they do — but a broken voice demo is worse than a polished text one. Ship the cheap version well, and be able to talk about the expensive version fluently.

## Recommendation

**Default: Web Speech API for both directions. Zero keys, zero cost, ~40 lines.**
**Upgrade path: Groq `whisper-large-v3-turbo` for STT (free tier) when accuracy matters.**

Ship the browser version; wire the Groq path behind a toggle if time allows. Talk about the rest.

## The options

| Option | STT | TTS | Cost | Latency | Verdict |
|---|---|---|---|---|---|
| **Web Speech API** | ✅ browser-native | ✅ browser-native | **$0**, no key | Good | ✅ **Ship this** |
| **Groq Whisper v3 Turbo** | ✅ excellent | ✗ | **Free tier** (20 RPM, 2,000 req/day, 7,200 audio-sec/hr) | ~228× realtime | ✅ **Best free upgrade** |
| Deepgram (Nova-3 / Flux) | ✅ best-in-class streaming | ✅ Aura-2 | $200 free credit, no card | Lowest | Great, but credits expire |
| ElevenLabs (Scribe v2 / Flash v2.5) | ✅ | ✅ **best quality**, ~75 ms | Monthly free allowance | Very low | Best-sounding TTS |
| Gemini Live API | native speech-to-speech | native | Free tier available | Very low | The "real" architecture — see below |
| OpenAI Realtime | native speech-to-speech | native | Paid | Very low | Same class, paid |

## Why Web Speech API wins for this build

**Pros**
- Zero setup: no key, no backend audio route, no billing. `webkitSpeechRecognition` + `speechSynthesis`, both in the browser.
- Free forever, no quota to blow mid-demo.
- Privacy talking point: TTS runs fully on-device; Safari can even do on-device recognition.
- ~40 lines total, so it can't eat your day.

**Cons — know them, they're the follow-up questions**
- **Firefox doesn't support recognition** (behind `dom.webspeech.recognition.enable`). Demo in Chrome/Edge/Safari; feature-detect and hide the mic otherwise.
- **HTTPS or `localhost` only** — plain HTTP fails before the session starts.
- **Chrome sends audio to Google's servers** (not on-device); Safari prompts for macOS-level Speech Recognition permission and notes data goes to Apple. Say this out loud — it's exactly the enterprise data-governance instinct Wonderful cares about.
- TTS voice quality depends on the OS.
- No barge-in, no real end-of-turn detection.

## The airport-code problem — do this, it's the detail that lands

Generic STT mangles aviation vocabulary. "SFO" comes back as "s f o", "essef oh", "San Francisco". "BDL" becomes "bee dee el". Untreated, your voice demo fails on its first question.

**Fix: a normalisation pass between STT and the LLM.**

```python
def normalize_transcript(text: str) -> tuple[str, list[str]]:
    # 1. collapse spelled-out letters:  "b d l" / "bee dee el" -> "BDL"
    # 2. phonetic alphabet: "bravo delta lima" -> "BDL"
    # 3. fuzzy-match spans against airport names, cities, IATA/ICAO codes
    #    (rapidfuzz, threshold ~85) using the OurAirports table as the lexicon
    # 4. domain synonyms: "Logan"->BOS, "John Wayne"/"Orange County"->SNA,
    #    "Bradley"->BDL, "Sea-Tac"->SEA, "O'Hare"->ORD, "National"->DCA
    # 5. return (normalized_text, corrections[]) and SHOW the corrections in the UI
```

Two reasons this matters beyond correctness: it's a **constrained-vocabulary ASR** technique (the real fix in production is biasing/keyword boosting at the recogniser), and showing the correction in the UI — *"heard 'bradley' → BDL"* — turns a failure mode into a trust signal. That's a voice-product instinct, which is precisely what this company hires for.

## Making answers speakable

Text answers and spoken answers are different products. A ranked markdown table read aloud is unbearable.

- Have the agent produce **two fields**: `display_markdown` and `speech_text`.
- `speech_text`: ≤3 sentences, no tables, no bullet characters, no URLs. Numbers rounded and spoken naturally — "about eighty-seven percent", not "87.24%".
- Give the model a voice-mode system instruction: *"Voice mode is active. Answer in at most three spoken sentences, lead with the conclusion, offer to go deeper. Detail goes to the screen, not the speaker."*
- Barge-in poor-man's version: `speechSynthesis.cancel()` when the mic re-opens.

## Implementation sketch

```ts
// web/src/hooks/useVoice.ts
const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
const supported = !!SR;

function listen(onFinal: (t: string) => void) {
  const r = new SR();
  r.lang = "en-US"; r.interimResults = true; r.continuous = false;
  r.onresult = (e: any) => {
    const last = e.results[e.results.length - 1];
    if (last.isFinal) onFinal(last[0].transcript);
  };
  r.start(); return () => r.stop();
}

function speak(text: string) {
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1.05; u.pitch = 1.0;
  speechSynthesis.speak(u);
}
```

Groq STT upgrade (server side, if you wire it):
```python
# POST audio blob -> /transcribe
client.audio.transcriptions.create(
    file=("audio.webm", audio_bytes),
    model="whisper-large-v3-turbo",
    prompt="Aviation context. Airport codes: SFO, LAX, BOS, BDL, PVD, ANC, SNA...",
)
```
The `prompt` parameter biases Whisper toward your vocabulary — the correct fix for the airport-code problem, one line.

## The architecture question they will ask

**"Would you build it this way in production?"** — No, and here's the answer:

| | Pipeline (STT → LLM → TTS) | Native speech-to-speech (Gemini Live / OpenAI Realtime) |
|---|---|---|
| Latency | Additive: 3 hops, ~1–2 s | Single hop, sub-second |
| Barge-in | Hard, bolted on | Native |
| Prosody / tone | Lost — text is a lossy bottleneck | Preserved; can adapt to user affect |
| Tool calling | Mature, easy | Supported, less battle-tested |
| Debuggability | **Every stage inspectable** | Opaque |
| Cost control | Swap any component | Locked to one vendor |

*"For a one-day analytical demo I chose the pipeline: it's free, every stage is inspectable, and the tool-calling path is identical to text mode. For a production voice agent I'd move to native speech-to-speech over WebSockets — you can't get natural turn-taking or barge-in when the LLM only ever sees text, because everything about how something was said is discarded at the STT boundary."*

That paragraph is worth more than the code.

## Sources
- [MDN — Using the Web Speech API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Speech_API/Using_the_Web_Speech_API)
- [MDN — SpeechRecognition](https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition)
- [Groq — Whisper Large v3 Turbo](https://console.groq.com/docs/model/whisper-large-v3-turbo)
- [Groq free tier limits 2026](https://www.grizzlypeaksoftware.com/articles/p/groq-api-free-tier-limits-in-2026-what-you-actually-get-uwysd6mb)
- [Gemini Live API overview](https://ai.google.dev/gemini-api/docs/live-api)
- [Gemini Live API over WebSockets](https://ai.google.dev/gemini-api/docs/live-api/get-started-websocket)
