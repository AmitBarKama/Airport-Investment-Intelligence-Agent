/* Regression tests for the voice turn-taking policy.
   Run with:  node --test tests/test_voice_turn_taking.mjs
   or via:    make test

   These exist because the bug they cover — the agent interrupting itself on
   its own text-to-speech — is invisible to every other kind of test. It only
   appears with a real microphone next to a real speaker, which no CI has. The
   decisions were therefore pulled out of the DOM code into web/turn-taking.js,
   where they are ordinary functions and the failure is an assertion. */

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const require = createRequire(import.meta.url);
const T = require("../web/turn-taking.js");

/* ─────────────────── the bug: reopening the microphone ─────────────────── */
/* The old handler was `if (vm.on && !vm.paused) setTimeout(vmListen, 200)`.
   Both flags are true during a response, so the recogniser reopened 200ms
   after we aborted it and ran for the whole answer — transcribing the agent's
   own voice off the speakers and treating it as the user's next question. */

const vm = (over) => ({ on: true, paused: false, suppress: false, state: "listening", ...over });

test("microphone reopens only while listening", () => {
  assert.equal(T.shouldReopenMic(vm()), true);
});

test("microphone does NOT reopen while the agent is speaking", () => {
  // The reported symptom. `on` and `paused` alone would have said yes.
  assert.equal(T.shouldReopenMic(vm({ state: "speaking", suppress: true })), false);
  assert.equal(T.shouldReopenMic(vm({ state: "speaking" })), false);
});

test("microphone does NOT reopen while the agent is thinking", () => {
  assert.equal(T.shouldReopenMic(vm({ state: "thinking", suppress: true })), false);
  assert.equal(T.shouldReopenMic(vm({ state: "thinking" })), false);
});

test("the suppress latch wins even when the state says listening", () => {
  /* `end` arrives asynchronously. If the state has already been set back to
     "listening" by the time it lands, a state check alone would let the
     aborted recogniser resurrect itself. */
  assert.equal(T.shouldReopenMic(vm({ suppress: true })), false);
});

test("microphone stays shut when paused or out of voice mode", () => {
  assert.equal(T.shouldReopenMic(vm({ paused: true })), false);
  assert.equal(T.shouldReopenMic(vm({ on: false })), false);
  assert.equal(T.shouldReopenMic(null), false);
});

/* ───────────────── the interruption decision: there isn't one ───────────── */
/* The energy detector that used to live here was the bug. It sampled the
   microphone while the agent spoke and fired at 300 ms of sustained level —
   and on laptop speakers the agent's own voice is exactly that. It is gone,
   and interruption is now an explicit act only. */

test("the app never opens a capture to decide things on its own", () => {
  /* Blunt on purpose. This is the actual promise being made — the agent
     cannot interrupt itself because nothing is listening while it talks — and
     it is the promise that has regressed twice. A source-level assertion is
     the only kind that survives having no microphone in CI. */
  const app = readFileSync(new URL("../web/app.js", import.meta.url), "utf8");
  for (const forbidden of ["getUserMedia", "AnalyserNode", "createAnalyser",
                           "getByteTimeDomainData", "createMediaStreamSource"]) {
    assert.ok(!app.includes(forbidden),
      `web/app.js reintroduced ${forbidden}: something is sampling audio again`);
  }
});

test("no energy-detector helpers survive in the policy module", () => {
  for (const gone of ["stepBargeIn", "bargeThreshold", "BARGE_SUSTAIN_MS", "BARGE_DECAY"]) {
    assert.equal(T[gone], undefined, `${gone} is still exported`);
  }
});

/* ────────────────── speaking one sentence at a time ────────────────────── */

const LONG_ANSWER =
  "Boston Logan is the strongest candidate in New England, and it is not close. " +
  "It handled 21.3 million passengers in 2024 against an annual service volume " +
  "that puts it at 78 percent of capacity. The constraint is that Logan has " +
  "almost no room to expand: it sits on filled land with water on three sides, " +
  "so a new runway is not realistic. Bradley International is the obvious " +
  "alternative if you want land, but at 3.3 million passengers it has a demand " +
  "problem rather than a capacity problem.";

test("chunks rejoin to exactly the original text", () => {
  // spokenFromChunks rebuilds the heard prefix by joining these, so a dropped
  // space would corrupt what gets stored as said.
  for (const t of [LONG_ANSWER, "One sentence.", "No trailing stop", "a. b! c? d"]) {
    assert.equal(T.splitForSpeech(t).join(""), t, `round trip failed for: ${t}`);
  }
});

test("every chunk stays short enough for the engine to finish it", () => {
  // Chrome stops speechSynthesis at roughly 15s on one long utterance; at
  // ~165wpm the cap keeps every chunk to a handful of seconds.
  const chunks = T.splitForSpeech(LONG_ANSWER);
  assert.ok(chunks.length > 1, "a long answer must be split at all");
  for (const c of chunks) assert.ok(c.length <= T.MAX_SPEECH_CHUNK, `${c.length} chars`);
});

test("abbreviations do not end a sentence", () => {
  for (const t of ["St. Louis is not comparable to Boston in any respect at all.",
                   "Washington D.C. has three airports serving one metropolitan area.",
                   "Consider No. 3 on that list before making any final decision.",
                   "The U.S. system is unusual in how many hubs it actually has."]) {
    assert.equal(T.splitForSpeech(t).length, 1, `split mid-phrase: ${t}`);
  }
});

test("decimals do not end a sentence", () => {
  const t = "Atlanta handled 52.6 million passengers, which is 2.4 times Boston.";
  assert.equal(T.splitForSpeech(t).length, 1);
});

test("a very long sentence is broken at a comma", () => {
  const t = "Logan is constrained " + "and it is hemmed in on every side, ".repeat(12) + "so it cannot grow.";
  const chunks = T.splitForSpeech(t);
  assert.ok(chunks.length > 1);
  for (const c of chunks) assert.ok(c.length <= T.MAX_SPEECH_CHUNK);
  assert.equal(chunks.join(""), t);
});

test("empty and whitespace input produce no chunks to speak", () => {
  for (const t of ["", "   ", "\n", null, undefined]) {
    assert.deepEqual(T.splitForSpeech(t), []);
  }
});

/* ──────────────── how much was heard, exactly this time ────────────────── */

test("spokenFromChunks returns the finished chunks plus the current partial", () => {
  const chunks = ["First sentence. ", "Second sentence. ", "Third sentence."];
  assert.equal(T.spokenFromChunks(chunks, 0, 0), "");
  assert.equal(T.spokenFromChunks(chunks, 1, 0), "First sentence. ");
  assert.equal(T.spokenFromChunks(chunks, 1, 6), "First sentence. Second");
  assert.equal(T.spokenFromChunks(chunks, 3, 0), chunks.join(""));
});

test("spokenFromChunks clamps nonsense rather than throwing", () => {
  const chunks = ["a. ", "b."];
  assert.equal(T.spokenFromChunks(chunks, 99, 0), "a. b.");
  assert.equal(T.spokenFromChunks(chunks, -5, 0), "");
  assert.equal(T.spokenFromChunks(chunks, 0, 999), "a. ");
  assert.equal(T.spokenFromChunks(null, 1, 1), "");
});

/* ──────────────────────────── backchannels ─────────────────────────────── */

test("backchannels are not turns", () => {
  // Hyphenated forms included on purpose: Chrome returns "mm-hmm", not "mm hmm",
  // and the original space-only pattern let it through as a question.
  for (const s of ["mm-hmm", "mm hmm", "mhm", "uh huh", "uh-huh", "yeah", "right",
                   "ok", "okay", "sure", "I see", "got it", "go on", "Mm hmm.", "yep!"]) {
    assert.equal(T.isBackchannel(s), true, `"${s}" should be a backchannel`);
  }
});

/* ──────────── what counts as a turn worth answering ────────────────────── */
/* The rule was "at least two words", which silently discarded every one-word
   follow-up before it was ever sent. The agent had full context throughout —
   it was simply never asked, which from the user's side is indistinguishable
   from an agent with no memory. */

test("one-word follow-ups are real questions", () => {
  for (const q of ["Why?", "Really?", "Denver?", "How?", "When?", "no", "More."]) {
    assert.equal(T.isUsableTurn(q), true, `"${q}" was discarded`);
  }
});

test("backchannels are still not turns", () => {
  for (const q of ["mm-hmm", "ok", "yeah", "sure", "right", "got it"]) {
    assert.equal(T.isUsableTurn(q), false, `"${q}" was treated as a question`);
  }
});

test("noise is not a turn", () => {
  for (const q of ["", " ", "...", "!", "a", "\n", null, undefined]) {
    assert.equal(T.isUsableTurn(q), false, `${JSON.stringify(q)} was treated as a question`);
  }
});

test("ordinary questions are turns", () => {
  for (const q of ["What about Denver", "Compare that to LAX",
                   "Which airport has the most room to expand"]) {
    assert.equal(T.isUsableTurn(q), true);
  }
});

test("real questions are not backchannels", () => {
  for (const s of ["yes but what about Denver", "okay so which airport wins",
                   "right, compare that to LAX", "no"]) {
    assert.equal(T.isBackchannel(s), false, `"${s}" should be a turn`);
  }
});

/* ─────────────────────────────── echo ──────────────────────────────────── */

test("the agent's own words coming back are recognised as echo", () => {
  const words = T.speakingWordsOf(
    "Boston Logan is running near capacity and has very little room to expand");
  assert.equal(T.looksLikeEcho("logan is running near capacity", words), true);
  assert.equal(T.looksLikeEcho("what about Denver instead", words), false);
});

test("nothing is echo when the agent is not speaking", () => {
  assert.equal(T.looksLikeEcho("anything at all", new Set()), false);
});

/* ─────────────────── how much of the answer was heard ──────────────────── */
/* The old code fell back to the WHOLE string whenever both exact estimators
   were unavailable, which is the one answer that must never be given: it
   records the entire answer as heard and the model spends the rest of the
   conversation referring to things the user never heard. */

const ANSWER = "Boston Logan is running near capacity and it has very little room to expand";

test("finished chunks are the preferred estimator, over every approximation", () => {
  const chunks = T.splitForSpeech(ANSWER);
  const r = T.spokenPrefix(ANSWER, {
    chunks, chunksDone: 1, saidChars: 0,
    audioDuration: 10, audioCurrentTime: 9, elapsedMs: 99999,
  });
  assert.equal(r.via, "chunks", "an exact figure must beat an estimated one");
  assert.equal(r.text, chunks[0]);
});

test("audio playhead is used when there is one", () => {
  const r = T.spokenPrefix(ANSWER, { audioDuration: 10, audioCurrentTime: 5 });
  assert.equal(r.via, "audio-clock");
  assert.ok(r.text.length > 0 && r.text.length < ANSWER.length);
  assert.ok(ANSWER.startsWith(r.text));
});

test("boundary character index is used when onboundary fired", () => {
  const r = T.spokenPrefix(ANSWER, { saidChars: 12 });
  assert.equal(r.via, "boundary");
  assert.equal(r.text, ANSWER.slice(0, 12));
});

test("elapsed time is used when onboundary never fires", () => {
  // Chrome's remote voices never fire onboundary, so saidChars stays 0.
  const r = T.spokenPrefix(ANSWER, { saidChars: 0, elapsedMs: 2000 });
  assert.equal(r.via, "elapsed-estimate");
  assert.ok(r.text.length > 0, "must estimate something, not give up");
  assert.ok(r.text.length < ANSWER.length,
    "must NOT record the whole answer as heard — this was the bug");
});

test("nothing spoken yet records nothing as heard", () => {
  const r = T.spokenPrefix(ANSWER, { saidChars: 0, elapsedMs: 0 });
  assert.equal(r.text, "");
  assert.equal(r.via, "unknown");
});

test("an over-run estimate is clamped to the full answer, never past it", () => {
  const r = T.spokenPrefix(ANSWER, { saidChars: 0, elapsedMs: 999999 });
  assert.equal(r.text, ANSWER);
});

test("truncation lands on a word boundary", () => {
  for (const frac of [0.1, 0.25, 0.37, 0.5, 0.66, 0.8, 0.95]) {
    const cut = T.cutAtWord(ANSWER, frac);
    assert.ok(ANSWER.startsWith(cut));
    assert.ok(!/\S$/.test(cut) || ANSWER[cut.length] === " " || cut.length === ANSWER.length,
      `"${cut}" ends mid-word`);
  }
});

test("empty and degenerate inputs do not throw", () => {
  assert.equal(T.spokenPrefix("", {}).via, "empty");
  assert.equal(T.spokenPrefix(ANSWER, null).via, "unknown");
  assert.equal(T.spokenPrefix(ANSWER, { audioDuration: NaN, saidChars: 0, elapsedMs: 0 }).text, "");
  assert.equal(T.cutAtWord("abc", NaN), "");
});

/* ───────────── answering the agent's own question, out loud ─────────────── */
/* Every answer ends with an offer. "yes" was on the backchannel list, so in
   voice mode it was discarded in the browser and never reached the agent at
   all -- the offer-acceptance path existed but was unreachable by speech,
   which from the user's chair is the agent ignoring them. */

test("an affirmative is a nod when nothing was asked", () => {
  for (const s of ["yes", "ok", "sure", "yeah"]) {
    assert.equal(T.isUsableTurn(s), false, `"${s}" should stay a backchannel`);
  }
});

test("an affirmative is a turn when an offer is outstanding", () => {
  for (const s of ["yes", "yes.", "ok", "sure", "go on", "go ahead", "sounds good"]) {
    assert.equal(T.isUsableTurn(s, { awaitingAnswer: true }), true,
                 `"${s}" was discarded while the agent was waiting for an answer`);
  }
});

test("a pure acknowledgement is never an answer, even when we asked", () => {
  for (const s of ["mm-hmm", "mhm", "uh-huh", "right", "i see", "nice"]) {
    assert.equal(T.isUsableTurn(s, { awaitingAnswer: true }), false,
                 `"${s}" is a nod, not an acceptance`);
  }
});

test("a real question is a turn either way", () => {
  for (const opts of [undefined, { awaitingAnswer: true }]) {
    assert.equal(T.isUsableTurn("why?", opts), true);
    assert.equal(T.isUsableTurn("top 5 airports", opts), true);
  }
});

test("noise is still noise while we are waiting", () => {
  for (const s of ["", " ", "...", "b"]) {
    assert.equal(T.isUsableTurn(s, { awaitingAnswer: true }), false, JSON.stringify(s));
  }
});

test("voice mode actually passes the flag, and tracks the offer", () => {
  const src = readFileSync(new URL("../web/app.js", import.meta.url), "utf8");
  assert.match(src, /isUsableTurn\(\s*text,\s*answering\s*\)/,
               "the turn filter must know whether we just asked something");
  assert.match(src, /vm\.pendingOffer\s*=\s*payload\.followup/,
               "nothing records that an offer is outstanding");
});

test("the voice transcript carries the detail the speaker cannot", () => {
  const src = readFileSync(new URL("../web/app.js", import.meta.url), "utf8");
  assert.match(src, /function vmEvidenceMarkdown/,
               "a ranking summarised aloud must still be readable on screen");
});
