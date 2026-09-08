/* Turn-taking policy for the voice conversation.
   ─────────────────────────────────────────────────────────────────────────
   Everything here is a pure function of its arguments: no DOM, no microphone,
   no speaker, no timers. That is deliberate. The decisions in this file are
   the ones that go wrong in a voice agent — when to reopen the microphone,
   what counts as an interruption, how much of an answer was actually heard —
   and they are exactly the decisions that are impossible to test through a
   browser in CI. Split out, they run under plain node in milliseconds.

   app.js owns the audio plumbing and calls in here for every judgement call.
   tests/test_voice_turn_taking.mjs covers it. */

(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.TurnTaking = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  /* ───────────────────────── reopening the microphone ─────────────────────
     The single most important predicate in the file, and the one that was
     wrong.

     `SpeechRecognition` fires `end` for three different reasons that look
     identical from the handler: the browser's own end-of-speech timeout, a
     recognition error, and our own `abort()`. The old handler restarted the
     recogniser on all three:

         r.onend = () => { if (vm.on && !vm.paused) setTimeout(vmListen, 200); }

     `vm.on` and `vm.paused` are both still true during a response, so closing
     the microphone before speaking did nothing: `abort()` fired `end`, and a
     fresh recogniser opened 200 ms later and ran for the whole answer. The
     agent then transcribed its own voice off the speakers and treated it as
     the user's next question — it interrupted itself.

     Two guards, and both are needed. `state === "listening"` is the honest
     description of when a microphone should be open. `suppress` is an
     explicit latch set by whoever closed it, because `end` arrives
     asynchronously — by the time it lands, `state` may already have moved on
     to something else entirely, and a state check alone would race. */
  function shouldReopenMic(vm) {
    if (!vm || !vm.on) return false;      // not in voice mode at all
    if (vm.paused) return false;          // user pressed Pause
    if (vm.suppress) return false;        // something closed it on purpose
    return vm.state === "listening";      // only ever open while listening
  }

  /* ──────────────── why there is no automatic interruption ────────────────
     There was one here: an energy detector sampling the microphone while the
     agent spoke, firing an interrupt at 300 ms of sustained level. It has been
     removed, and this note is the reason it must not come back.

     The capture it listened on requested `echoCancellation`, but browser AEC
     references *system* playback and `speechSynthesis` renders outside the
     page's audio graph. On laptop speakers the agent's own voice therefore
     arrived as clean, sustained, above-threshold energy — indistinguishable
     from a person. Raising the threshold only trades self-interruption for an
     interrupt that never fires; the headphones setting that used to live here
     was a knob for a detector that could not be made correct either way.

     A real barge-in needs a far-end reference — the signal actually being
     played — so the decision can be "the microphone exceeds our own output"
     rather than "the microphone is loud". That requires owning the playback,
     which means a neural voice (an <audio> element we can route through
     createMediaElementSource) or a full speech-to-speech session. Until then
     the microphone is closed while the agent talks and interruption is an
     explicit act: the Stop button, the orb, or the spacebar.

     The invariant, asserted in tests/test_voice_turn_taking.mjs: the app never
     samples audio to decide anything on its own. */

  /* ────────────────────────────── backchannels ────────────────────────────
     "mm-hmm" means keep going, not stop. Treating it as a turn is how a voice
     agent ends up interrupting itself every time the user agrees with it.

     Note the [ -] separator class. Chrome's recogniser returns "mm-hmm" and
     "uh-huh" hyphenated far more often than spaced, and the space-only
     version of this pattern therefore missed the most common backchannel
     there is — it went straight through as a question. */
  const BACKCHANNEL = /^(m+[ -]?h*m+|hm+|uh[ -]?huh|a?ha|yeah|yep|yes|yup|ok|okay|sure|right|i see|got it|go on|carry on|sounds good|nice)[.!?]*$/i;

  /* The subset of those that ANSWER a question rather than merely acknowledge
     one. While the agent is speaking, "yes" is a nod and must not interrupt.
     But every answer ends with an offer -- "Want me to explain why DFW is ahead
     of DEN?" -- and once it has been asked, "yes" is the reply to it. Dropping
     it in the browser was indistinguishable from the agent ignoring the user,
     and it made the whole offer-acceptance path unreachable by voice. */
  const AFFIRMATIVE =
    /^(yeah|yep|yes|yup|ok|okay|sure|go on|carry on|sounds good|go ahead|do it|please do|please)[.!?]*$/i;

  function isAffirmative(text) {
    return AFFIRMATIVE.test(String(text || "").trim().replace(/\s+/g, " "));
  }

  function isBackchannel(text) {
    return BACKCHANNEL.test(String(text || "").trim().replace(/\s+/g, " "));
  }

  /* Whether a final transcript is a turn worth answering.

     The rule used to be "at least two words", which threw away precisely the
     follow-ups people actually say out loud — "Why?", "Really?", "Denver?",
     "Which one?" — before they were ever sent. The agent kept full context
     the whole time; it was simply never asked, which is indistinguishable
     from having no memory if you are the one talking to it.

     So the bar is only: real characters, and not a backchannel. One word is a
     perfectly good question. */
  function isUsableTurn(text, opts) {
    const t = String(text || "").trim();
    if (t.length < 2) return false;          // a stray consonant is not a turn
    if (!/[a-z0-9]/i.test(t)) return false;  // punctuation-only noise
    // An offer is outstanding, so "yes" is an answer, not a nod.
    if (opts && opts.awaitingAnswer && isAffirmative(t)) return true;
    return !isBackchannel(t);
  }

  /* ──────────────────────────────── echo ──────────────────────────────────
     Second line of defence, for the moment after playback stops when the
     speaker tail is still in the room and the recogniser has legitimately
     reopened. Content is the reliable signal: if what we just heard is mostly
     made of the words we were just saying, it is our own voice coming back.
     People interrupting almost never recite the agent's sentence at it. */
  function speakingWordsOf(text) {
    return new Set(String(text || "").toLowerCase()
      .replace(/[^a-z0-9 ]/g, " ").split(/\s+/).filter((w) => w.length > 2));
  }

  function looksLikeEcho(text, speakingWords) {
    if (!speakingWords || !speakingWords.size) return false;
    const words = String(text || "").toLowerCase().replace(/[^a-z0-9 ]/g, " ")
      .split(/\s+/).filter((w) => w.length > 2);
    if (!words.length) return true;   // nothing but filler while we speak
    const hits = words.filter((w) => speakingWords.has(w)).length;
    return hits / words.length >= 0.5;
  }

  /* ─────────────────────── how much was actually heard ────────────────────
     When the user cuts the agent off, the stored answer has to be truncated
     to the part that reached the speaker. Skip it and the model spends the
     rest of the conversation certain it delivered things nobody heard.

     Three estimators, best first, and the order matters:

       audio-clock   Exact. Only available for server-rendered neural audio,
                     where we hold an <audio> element with a real playhead.
       boundary      Exact. `onboundary` reports the character index the voice
                     has reached — but Chrome never fires it for remote
                     (network) voices, and those are the good ones. When it
                     does not fire, `saidChars` stays 0.
       elapsed       Crude: wall-clock time over an estimated speaking rate.

     The old code had the first two and fell back to `vm.saying.length` —
     the whole string — whenever both were unavailable. That is the worst
     possible answer: the silent case recorded the entire answer as heard,
     which is precisely the failure the truncation exists to prevent. An
     estimate that is 20% off is worth far more than an exact-looking value
     that is 100% wrong, so the last resort is time, and never "all of it". */
  /* ─────────────────── speaking one sentence at a time ───────────────────
     Chrome silently stops `speechSynthesis` after roughly 15 seconds on a
     single long utterance with a network voice — no `end`, no `error`, the
     voice simply stops mid-answer. An airport analysis read aloud runs well
     past that, so a whole answer handed over in one utterance is reliably
     truncated. Splitting it into sentences and queueing them keeps every
     utterance short enough to survive.

     It buys two more things. Stop takes effect at the current sentence rather
     than whenever the engine notices, and — because we know exactly which
     sentences finished — the truncation below becomes exact instead of an
     estimate. */
  const MAX_SPEECH_CHUNK = 220;
  const MIN_SPEECH_CHUNK = 40;

  /* Abbreviations that end in a full stop but not a sentence. Without these,
     "St. Louis" and "No. 3" split mid-phrase and the voice pauses in the
     wrong place. Decimals ("52.6 million") need no entry: the split requires
     whitespace after the stop, and a decimal point is followed by a digit. */
  const ABBREV = new Set([
    "st", "mr", "mrs", "ms", "dr", "prof", "jr", "sr", "inc", "corp", "co",
    "ltd", "no", "vs", "etc", "approx", "fig", "dept", "est", "mt", "ft",
    "ave", "blvd", "u.s", "d.c", "a.m", "p.m", "e.g", "i.e",
  ]);

  function endsWithAbbreviation(head) {
    const tail = head.match(/([A-Za-z.]+)$/);
    if (!tail) return false;
    const word = tail[1].toLowerCase().replace(/\.+$/, "");
    if (!word) return false;
    if (ABBREV.has(word)) return true;
    // Initialisms — "U.S", "D.C", "J.F.K": single letters joined by dots.
    return /^(?:[a-z]\.)*[a-z]$/.test(word);
  }

  /* Chunks concatenate back to the original text exactly, separators and all.
     `spokenFromChunks` depends on that: it rebuilds the spoken prefix by
     joining them, and a lost space would corrupt what gets stored as heard. */
  function splitForSpeech(text, maxLen = MAX_SPEECH_CHUNK) {
    const src = String(text == null ? "" : text);
    if (!src.trim()) return [];

    const parts = [];
    let start = 0;
    const boundary = /[.!?…]+["'\u2019\u201d)\]]*\s+/g;
    let m;
    while ((m = boundary.exec(src)) !== null) {
      if (endsWithAbbreviation(src.slice(start, m.index))) continue;
      const end = m.index + m[0].length;
      parts.push(src.slice(start, end));
      start = end;
    }
    if (start < src.length) parts.push(src.slice(start));
    return capLength(mergeShort(parts), maxLen);
  }

  /* A three-word sentence is a stumble, not a breath. Fold it into its
     neighbour so the cadence stays natural. */
  function mergeShort(chunks, min = MIN_SPEECH_CHUNK) {
    const out = [];
    for (const c of chunks) {
      const prevShort = out.length && out[out.length - 1].trim().length < min;
      if (out.length && (prevShort || c.trim().length < min)) out[out.length - 1] += c;
      else out.push(c);
    }
    return out;
  }

  /* A sentence can still be long enough to hit the engine's limit on its own,
     so break it at a comma — and failing that, at a space. */
  function capLength(chunks, maxLen) {
    const out = [];
    for (let c of chunks) {
      while (c.length > maxLen) {
        let cut = c.lastIndexOf(", ", maxLen);
        if (cut < maxLen * 0.4) cut = c.lastIndexOf(" ", maxLen);
        if (cut <= 0) break;                 // one impossibly long word: leave it
        out.push(c.slice(0, cut + 1));
        c = c.slice(cut + 1);
      }
      out.push(c);
    }
    return out;
  }

  /** Exactly what was spoken: the finished chunks, plus how far into the
      current one the voice has reached. */
  function spokenFromChunks(chunks, doneCount, charsInCurrent) {
    const list = Array.isArray(chunks) ? chunks : [];
    const done = Math.max(0, Math.min(Math.floor(doneCount) || 0, list.length));
    let out = list.slice(0, done).join("");
    const current = list[done];
    if (current && charsInCurrent > 0) {
      out += current.slice(0, Math.min(charsInCurrent, current.length));
    }
    return out;
  }

  const WORDS_PER_MINUTE = 165;   // typical for the en-US system voices at rate 1.0

  function spokenPrefix(saying, clock) {
    const full = String(saying || "");
    if (!full) return { text: "", via: "empty" };
    const c = clock || {};

    /* Exact, and now the normal case on the browser voice: we queued the
       sentences ourselves, so we know which of them finished. */
    if (Array.isArray(c.chunks) && c.chunks.length) {
      return {
        text: spokenFromChunks(c.chunks, c.chunksDone, c.saidChars),
        via: "chunks",
      };
    }
    if (isFinite(c.audioDuration) && c.audioDuration > 0) {
      return { text: cutAtWord(full, c.audioCurrentTime / c.audioDuration), via: "audio-clock" };
    }
    if (c.saidChars > 0) {
      return { text: full.slice(0, Math.min(c.saidChars, full.length)), via: "boundary" };
    }
    if (c.elapsedMs > 0) {
      const words = full.trim().split(/\s+/).length;
      const expectedMs = Math.max(500, (words / (c.wpm || WORDS_PER_MINUTE)) * 60000);
      return { text: cutAtWord(full, c.elapsedMs / expectedMs), via: "elapsed-estimate" };
    }
    return { text: "", via: "unknown" };   // stopped before a word came out
  }

  /* Cut on a word boundary. A truncation mid-word reads as corruption when the
     transcript is shown back to the user, and confuses the model when it is
     fed back as history. */
  function cutAtWord(text, frac) {
    const clamped = Math.max(0, Math.min(1, isFinite(frac) ? frac : 0));
    const n = Math.round(clamped * text.length);
    if (n >= text.length) return text;
    if (n <= 0) return "";
    const space = text.lastIndexOf(" ", n);
    return text.slice(0, space > 0 ? space : n);
  }

  return {
    shouldReopenMic,
    splitForSpeech, spokenFromChunks, MAX_SPEECH_CHUNK, MIN_SPEECH_CHUNK,
    isBackchannel, isUsableTurn, BACKCHANNEL,
    isAffirmative, AFFIRMATIVE,
    speakingWordsOf, looksLikeEcho,
    spokenPrefix, cutAtWord, WORDS_PER_MINUTE,
  };
}));
