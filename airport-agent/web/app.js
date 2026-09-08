/* Wonderful — Airport Investment Intelligence
   Vanilla JS, no build step.

   The design principle throughout: the user should feel they are talking to an
   expert who can work with data, not watching an agent framework execute. So
   the thinking state shows human-readable progress ("Estimating spill against
   capacity"), never "calling tool / parsing JSON". The raw tool calls are still
   available behind a toggle, because "deterministic scoring, not just LLM
   output" has to stay demonstrable. */

/* Surface runtime errors instead of failing silently: a blank answer with a
   swallowed exception is the worst possible failure mode in a demo. */
window.addEventListener("error", (e) => showFatal(e.message));
window.addEventListener("unhandledrejection", (e) => showFatal(e.reason?.message || String(e.reason)));
function showFatal(msg) {
  const box = document.querySelector(".ai-body") || document.body;
  const el = document.createElement("div");
  el.className = "flag";
  el.textContent = "Interface error: " + msg;
  box.appendChild(el);
}

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const els = {
  sidebar: $("#sidebar"), thread: $("#thread"), welcome: $("#welcome"),
  input: $("#input"), send: $("#sendBtn"), mic: $("#micBtn"),
  banner: $("#banner"), history: $("#historyList"), note: $("#composerNote"),
  listenBar: $("#listenBar"), lbState: $("#lbState"), lbHeard: $("#lbHeard"),
  lbWave: $("#lbWave"), composer: $("#composer"), settings: $("#settingsOverlay"),
};

/* What the agent calls itself in the voice transcript. One constant, because
   the name appears on every line it speaks. */
const AGENT_NAME = "Investment Agent";

const SAMPLES = [
  "Which airports in New England are strong candidates for terminal expansion?",
  "Compare LA and Santa Ana airport congestion levels.",
  "What percentage of long-haul flights leave Anchorage?",
  "What is the unmet flight demand at SFO, and why?",
];

const prefs = {
  theme: localStorage.getItem("w.theme") || "light",   // spec leads with light mode
  trace: localStorage.getItem("w.trace") === "on",
  gender: localStorage.getItem("w.gender") || "female",
  voiceName: localStorage.getItem("w.voiceName") || "",
};

/* Developer mode has no switch in Settings any more — it is a build detail, not
   a user preference. It stays reachable at `?dev=1` (and `?dev=0` to turn it
   back off), because the trace under each answer is what shows the scoring is
   deterministic rather than something the model made up. Read here, before
   anything renders, and remembered afterwards. */
{
  const flag = new URLSearchParams(location.search).get("dev");
  if (flag !== null) {
    prefs.trace = flag !== "0" && flag !== "off" && flag !== "false";
    try { localStorage.setItem("w.trace", prefs.trace ? "on" : "off"); } catch {}
  }
}

let chatHistory = [];
let convState = {};
let conversations = [];      // real conversations, not a list of past prompts
let currentId = null;
let busy = false;
let meta = null;
let askAbort = null;         // cancels the in-flight text-chat stream

/* ─────────────────────────────── theme ─────────────────────────────── */
function applyTheme() {
  const sysDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const dark = prefs.theme === "dark" || (prefs.theme === "system" && sysDark);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
}
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme);

/* ───────────────────────── markdown (subset) ───────────────────────── */
/* Markdown rendering lives in web/markdown.js: it is the piece that decides
   whether an answer is readable, and pulled out it is testable under plain
   node instead of only by eye in a browser. See tests/test_markdown.mjs. */
const md = (src) => Markdown.render(src);

/* ─────────────────────────────── chat ─────────────────────────────── */
function enterThread() {
  els.welcome.classList.add("hidden");
  els.thread.classList.remove("hidden");
}

function orb(cls) {
  return `<div class="orb-wrap ${cls}"><div class="orb-rings"><i></i><i></i><i></i></div>
          <img class="orb" src="/orb.png" alt=""></div>`;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const TICK = `<svg viewBox="0 0 16 16" width="10" height="10" fill="none" stroke="#fff"
  stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8.5l3 3 6-7"/></svg>`;

function addTurn(question) {
  enterThread();
  const turn = document.createElement("div");
  turn.className = "turn";
  turn.innerHTML = `
    <div class="user-row"><div class="user-msg">${md(question).replace(/^<p>|<\/p>$/g, "")}</div></div>
    <div class="ai-row">
      ${orb("inline thinking-orb")}
      <div class="ai-body">
        <div class="thinking">
          <div class="think-label">Let me take a look at that.</div>
          <div class="steps"></div>
        </div>
      </div>
    </div>`;
  els.thread.appendChild(turn);
  scroll();
  return turn;
}

function scroll() { els.thread.scrollTop = els.thread.scrollHeight; }

/** Reveal the human-readable steps, then tick them off.
    The phrases describe work the tool actually performs; the stagger is purely
    so they are legible (the computation itself takes milliseconds). */
function showSteps(turn, steps) {
  const box = turn.querySelector(".steps");
  if (!box) return;
  box.innerHTML = "";
  steps.forEach((label, i) => {
    const el = document.createElement("div");
    el.className = "step";
    el.style.animationDelay = `${i * 90}ms`;
    el.innerHTML = `<span class="tick">${TICK}</span><span>${label}</span>`;
    box.appendChild(el);
    setTimeout(() => el.classList.add("done"), 260 + i * 230);
  });
  // How long the steps need to be readable. The deterministic tools return in
  // tens of milliseconds, so without a floor the thinking state flashes past
  // before anyone can read it. This paces the reveal; it does not invent work,
  // and it never delays anything that is genuinely still running.
  turn.dataset.minThink = String(Math.min(1200, 320 + steps.length * 200));
  scroll();
}

/* Reveal one markdown block.

   Prose is typed out a word at a time so the answer arrives the way a person
   would say it, rather than appearing all at once. The markdown is rendered
   FIRST and then uncovered by walking its text nodes: revealing raw markdown
   character by character would flash half-finished "**bold" markers. Tables
   drop in whole, because a half-drawn table just looks broken. */
async function revealBlock(body, raw) {
  const holder = document.createElement("div");
  holder.innerHTML = md(raw);
  body.appendChild(holder);

  if (raw.trimStart().startsWith("|")) {
    holder.style.animation = "rise .32s ease both";
    scroll(); await sleep(170); return;
  }

  const walker = document.createTreeWalker(holder, NodeFilter.SHOW_TEXT);
  const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
  const texts = nodes.map((n) => n.nodeValue);
  nodes.forEach((n) => { n.nodeValue = ""; });

  for (let i = 0; i < nodes.length; i++) {
    let acc = "";
    for (const part of texts[i].split(/(\s+)/)) {
      acc += part;
      nodes[i].nodeValue = acc;
      if (part.trim()) { scroll(); await sleep(14 + Math.random() * 16); }
    }
    nodes[i].nodeValue = texts[i];
  }
}

/* Queue blocks as they stream in and reveal them in order, so arrival speed
   never outruns reading speed. */
function makeStreamer(body) {
  const queue = []; let running = false, ended = false, done = null;
  let gate = Promise.resolve();          // held until the thinking state is done
  async function drain() {
    running = true;
    await gate;
    while (queue.length) await revealBlock(body, queue.shift());
    running = false;
    if (ended && done) { const cb = done; done = null; cb(); }
  }
  return {
    hold(promise) { gate = promise; },
    push(block) { queue.push(block); if (!running) drain(); },
    finish(cb) {
      ended = true; done = cb;
      if (!running && !queue.length) { done = null; gate.then(cb); }
    },
  };
}

function renderEvidence(turn, payload) {
  const body = turn.querySelector(".ai-body");

  const ev = payload.evidence || {};

  // Which brain actually answered. This used to appear only inside the
  // developer-mode disclosure, so falling back from the model to the keyword
  // planner was invisible -- which is how a regex matcher served every turn of
  // a production transcript without anyone noticing.
  const planner = payload.provider || "unknown";
  const keyless = /built-in planner|no API key|rule_based/i.test(planner);
  const badge = document.createElement("div");
  badge.className = "planner" + (keyless ? " keyless" : "");
  badge.textContent = keyless
    ? "Answered by the keyword planner \u2014 no model in the loop"
    : "Answered by " + planner;
  body.appendChild(badge);

  // Deterministic score card — makes visible that the ranking is computed,
  // not narrated.
  const top = (ev.results && ev.results[0]) || null;
  if (top && top.pillars) {
    const card = document.createElement("div");
    card.className = "score-card";
    const rows = Object.entries(top.pillars)
      .filter(([, v]) => v != null)
      .map(([k, v]) => {
        const w = ev.weights?.[k];
        return `<div class="pbar"><span class="lbl">${k.replace(/_/g, " ")}</span>
          <span class="track"><span class="fill${v < 0.35 ? " drag" : ""}" data-w="${Math.round(v * 100)}"></span></span>
          <span class="num">${v.toFixed(2)}</span>
          <span class="num">${w == null ? "" : Math.round(w * 100) + "%"}</span></div>`;
      }).join("");
    card.innerHTML = `<div class="sc-head">
        <span class="sc-title">${top.code} investment score
          <span class="tier ${top.tier}">${top.tier}</span></span>
        <span class="sc-val">${top.score}<span> / 100</span></span>
      </div>${rows}`;
    body.appendChild(card);
    requestAnimationFrame(() => card.querySelectorAll(".fill").forEach(
      (f) => { f.style.width = f.dataset.w + "%"; }));
  }

  // Sources
  if (payload.sources?.length) {
    const row = document.createElement("div");
    row.className = "meta-row";
    const det = payload.sources.filter((s) => s.class !== "external");
    const ext = payload.sources.filter((s) => s.class === "external");
    row.innerHTML = `<span class="lab">Sources</span>` + det.map((s) =>
      `<span class="pill${s.key === "SYNTHETIC" ? " syn" : ""}" title="${(s.detail||"").replace(/"/g, "&quot;")}">${s.label}</span>`).join("")
      + (ext.length ? `<span class="lab">· from the web</span>` + ext.map((s) =>
        `<span class="pill ext" title="${(s.detail||"").replace(/"/g, "&quot;")}">${s.label}</span>`).join("") : "");
    body.appendChild(row);
  }

  // Assumptions & uncertainty
  const a = ev.assumptions;
  if (a) {
    const d = document.createElement("details");
    d.className = "disclose";
    const rows = Object.entries(a).filter(([, v]) => typeof v !== "object")
      .map(([k, v]) => `<div><b>${k.replace(/_/g, " ")}:</b> ${v}</div>`).join("");
    const conf = ev.confidence || top?.confidence;
    d.innerHTML = `<summary>Assumptions & uncertainty</summary>
      <div class="content">${conf ? `<div><b>Confidence: ${conf.label}.</b> ${(conf.reasons || []).join("; ")}</div>` : ""}${rows}</div>`;
    body.appendChild(d);
  }

  // Developer mode: how this answer was actually produced.
  if (prefs.trace && payload.traces?.length) {
    const d = document.createElement("details");
    d.className = "disclose dev";
    d.innerHTML = `<summary>Developer mode: ${payload.traces.length} deterministic call${payload.traces.length > 1 ? "s" : ""}</summary>
      <div class="content">
        <div class="dev-row"><b>Planner</b> ${payload.provider || "unknown"}</div>
        ${payload.traces.map((t) => `
          <div class="dev-call">
            <div class="dev-row"><b>Tool</b> <code>${t.name}</code><span class="dev-ms">${t.ms} ms</span></div>
            <div class="dev-row"><b>Why this tool</b> ${t.reason || "n/a"}</div>
            <div class="dev-row"><b>Arguments</b> <code>${JSON.stringify(t.args)}</code></div>
            <div class="dev-row"><b>Returned</b> ${t.rows == null ? t.summary : `${t.rows} records, ${t.summary}`}</div>
            ${t.sources?.length ? `<div class="dev-row"><b>Data used</b> ${t.sources.join(", ")}</div>` : ""}
            ${t.issues?.length ? `<div class="dev-row"><b>Warnings</b> ${t.issues.join("; ")}</div>` : ""}
          </div>`).join("")}
        <div class="dev-row"><b>Numbers checked</b> ${
          payload.unverified_numbers?.length
            ? `${payload.unverified_numbers.length} figure(s) not found in any tool output`
            : "every figure traced back to a tool result"}</div>
      </div>`;
    body.appendChild(d);
  }

  if (payload.externally_sourced_numbers?.length) {
    const n = document.createElement("div");
    n.className = "note-ext";
    n.textContent = `${payload.externally_sourced_numbers.length} figure(s) here come from third-party reporting, not from our own data: ${payload.externally_sourced_numbers.join(", ")}`;
    body.appendChild(n);
  }

  if (payload.unverified_numbers?.length) {
    const f = document.createElement("div");
    f.className = "flag";
    f.textContent = `⚠ ${payload.unverified_numbers.length} figure(s) in this answer were not found in any tool output: ${payload.unverified_numbers.join(", ")}`;
    body.appendChild(f);
  }

  if (payload.followup) {
    const f = document.createElement("div");
    f.className = "followup";
    f.textContent = payload.followup;
    f.onclick = () => ask(payload.followup.replace(/^Want me to /i, "").replace(/\?$/, "?"));
    body.appendChild(f);
  }

  // Reading aloud is a per-answer choice, not a global setting: you usually
  // want to hear one particular answer, not have every answer spoken at you.
  const act = document.createElement("div");
  act.className = "actions";
  act.innerHTML = `
    <button title="Read this answer aloud" data-a="say"><svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><path d="M10.5 4.2 6.8 7.2H4v5.6h2.8l3.7 3V4.2z"/><path d="M13.6 7.4a3.6 3.6 0 0 1 0 5.2M15.8 5.2a6.7 6.7 0 0 1 0 9.6"/></svg></button>
    <button title="Copy answer" data-a="copy"><svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="7" y="7" width="9.5" height="9.5" rx="2"/><path d="M13 4.5H5.5A1.5 1.5 0 0 0 4 6v7.5"/></svg></button>`;

  act.querySelector('[data-a=copy]').onclick = (e) => {
    navigator.clipboard?.writeText(payload.text || "");
    const b = e.currentTarget;
    b.classList.add("on"); setTimeout(() => b.classList.remove("on"), 1100);
  };
  const sayBtn = act.querySelector('[data-a=say]');
  sayBtn.onclick = () => {
    if (sayBtn.classList.contains("playing")) { stopSpeaking(); sayBtn.classList.remove("playing"); return; }
    document.querySelectorAll('.actions [data-a=say].playing')
      .forEach((b) => b.classList.remove("playing"));
    sayBtn.classList.add("playing");
    speak(spokenVersion(payload), () => sayBtn.classList.remove("playing"));
  };
  body.appendChild(act);
  scroll();
}

/* What to actually say out loud. Reading a markdown table aloud is unbearable,
   so tables and formatting markers are stripped and the prose is kept. */
function spokenVersion(payload) {
  const raw = payload.text || payload.speech_text || "";
  return raw.split("\n")
    .filter((l) => !l.trimStart().startsWith("|"))
    .join("\n")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/[*_`#]/g, "")
    .replace(/\n{2,}/g, ". ")
    .replace(/\s+/g, " ")
    .replace(/\.\s*\./g, ".")
    .trim();
}

async function ask(question) {
  if (busy || !question.trim()) return;
  busy = true; els.send.disabled = true; els.input.value = "";
  const ctl = new AbortController();
  askAbort = ctl;
  clearForming();
  if (!currentConv()) beginConversation(question);
  const turn = addTurn(question);

  let streamer = null, finalText = "";
  const started = Date.now();
  let pending = Promise.resolve();

  const startWriting = () => {
    if (streamer) return;
    streamer = makeStreamer(turn.querySelector(".ai-body"));
    const floor = Number(turn.dataset.minThink || 0);
    const wait = Math.max(0, floor - (Date.now() - started));
    streamer.hold(sleep(wait).then(() => {
      turn.querySelector(".thinking")?.remove();
      turn.querySelector(".orb-wrap.inline")?.classList.remove("thinking-orb");
    }));
  };

  try {
    const resp = await fetch("/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: question, history: chatHistory, state: convState, voice: false }),
      signal: ctl.signal,
    });
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const frames = buf.split("\n\n"); buf = frames.pop();
      for (const frame of frames) {
        const e = frame.match(/^event: (.+)$/m), d = frame.match(/^data: ([\s\S]+)$/m);
        if (!e || !d) continue;
        let p; try { p = JSON.parse(d[1]); } catch { continue; }
        const type = e[1].trim();

        if (type === "progress") showSteps(turn, p.steps || []);
        else if (type === "token") {
          finalText += p.t || "";
          startWriting();
          streamer.push(p.t || "");
        } else if (type === "done") {
          convState = p.state || convState;
          chatHistory = chatHistory.concat([{ role: "user", content: question },
                                            { role: "assistant", content: p.text || "" }]).slice(-12);
          startWriting();
          const payload = { ...p, text: p.text || finalText };
          recordTurn(question, payload);
          streamer.finish(() => renderEvidence(turn, payload));
        }
      }
    }
  } catch (err) {
    if (err.name === "AbortError") turn.remove();   // abandoned on purpose
    else turn.querySelector(".ai-body").innerHTML =
      md(`I couldn't reach the analysis service. ${err.message}`);
  } finally {
    busy = false; els.send.disabled = false;
    if (askAbort === ctl) askAbort = null;
    els.input.focus();
  }
}

/* ───────────────────────── conversations ───────────────────────── */
/* A conversation is its turns, not the question that started it. Clicking one
   in the sidebar reopens it: the answers come back, and the agent picks up the
   same context (what we ranked, which airports, which weights) instead of
   re-running the first prompt from scratch. */

const STORE_KEY = "w.conversations";

function saveConversations() {
  try {
    conversations = Conversations.capConversations(conversations);
    localStorage.setItem(STORE_KEY, JSON.stringify(conversations));
  } catch { /* quota or private mode: history is a convenience, not state */ }
}

function loadStoredConversations() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    conversations = raw ? JSON.parse(raw) : [];
  } catch { conversations = []; }
  renderAllHistories();
}

function currentConv() {
  return conversations.find((c) => c.id === currentId) || null;
}

function beginConversation(firstQuestion) {
  const title = firstQuestion.length > 38
    ? firstQuestion.slice(0, 38).trim() + "…" : firstQuestion;
  const conv = { id: `c${Date.now()}`, title, at: Date.now(),
                 turns: [], chatHistory: [], convState: {} };
  conversations.unshift(conv);
  conversations = Conversations.capConversations(conversations);
  currentId = conv.id;
  renderAllHistories();
  return conv;
}

function recordTurn(question, payload) {
  let conv = currentConv();
  if (!conv) conv = beginConversation(question);
  conv.turns.push({ q: question, payload });
  conv.chatHistory = chatHistory;
  conv.convState = convState;
  conv.at = Date.now();
  saveConversations();
  renderAllHistories();
}

const ICONS = {
  pin: `<svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor"
    stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path
    d="M12.4 2.6l5 5-1.9.5-2.6 2.6-.4 3.3-5.5-5.5 3.3-.4L13 5.1zM7.6 12.4L3.5 16.5"/></svg>`,
  rename: `<svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor"
    stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path
    d="M13.6 3.4l3 3L7.2 15.8l-3.7.7.7-3.7z"/></svg>`,
  del: `<svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor"
    stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path
    d="M4 6h12M8.5 6V4.5h3V6M6 6l.8 9.5h6.4L14 6"/></svg>`,
};

/* Which row is one click away from being deleted. Delete is two-step rather
   than a modal: the app has no confirm dialog anywhere, and adding one for
   this would be more machinery than the action deserves. */
let pendingDelete = null;
let pendingDeleteTimer = null;

function armDelete(id) {
  clearTimeout(pendingDeleteTimer);
  pendingDelete = id;
  pendingDeleteTimer = setTimeout(() => { pendingDelete = null; renderAllHistories(); }, 4000);
  renderAllHistories();
}

function renderAllHistories() {
  renderHistory();
  renderVoiceHistory();
}

/* One row. The row used to BE the button, which left nowhere to put the
   actions — a nested <button> is invalid and its clicks would bubble into
   "open this conversation". So the row is a wrapper now, and the title is a
   button inside it. */
function historyRow(c, opts = {}) {
  /* Voice mode gets pin and delete but not rename: renaming wants a keyboard,
     and typing is the one thing a hands-free mode is not for. */
  const actions = opts.actions || ["pin", "rename", "del"];
  const onOpen = opts.onOpen || openConversation;

  const row = document.createElement("div");
  row.className = "hist-item";
  if (c.id === currentId) row.classList.add("active");
  if (c.pinned) row.classList.add("pinned");

  const open = document.createElement("button");
  open.className = "hist-open";
  open.textContent = c.title;
  // Defensive: this runs at boot over whatever localStorage happens to hold,
  // and one malformed record would otherwise blank the whole sidebar.
  const n = (c.turns || []).length;
  open.title = `${n} message${n === 1 ? "" : "s"}`;
  open.onclick = () => onOpen(c.id);
  row.appendChild(open);

  const acts = document.createElement("span");
  acts.className = "hist-actions";
  const arm = pendingDelete === c.id;
  const markup = {
    pin: `<button data-a="pin" class="${c.pinned ? "on" : ""}"
       title="${c.pinned ? "Unpin" : "Pin"}" aria-label="${c.pinned ? "Unpin" : "Pin"}">${ICONS.pin}</button>`,
    rename: `<button data-a="rename" title="Rename" aria-label="Rename">${ICONS.rename}</button>`,
    del: `<button data-a="del" class="${arm ? "danger" : ""}"
       title="${arm ? "Click again to delete" : "Delete"}" aria-label="Delete">${ICONS.del}</button>`,
  };
  acts.innerHTML = actions.map((a) => markup[a] || "").join("");

  const on = (a, fn) => { const b = acts.querySelector(`[data-a="${a}"]`); if (b) b.onclick = fn; };
  on("pin", () => {
    conversations = Conversations.togglePin(conversations, c.id);
    saveConversations(); renderAllHistories();
  });
  on("rename", () => beginRename(c, row, open));
  on("del", () => {
    if (pendingDelete !== c.id) { armDelete(c.id); return; }
    deleteConversation(c.id);
  });
  row.appendChild(acts);
  return row;
}

/* Rename in place. No dialog, for the same reason delete has none. */
function beginRename(c, row, openBtn) {
  if (row.querySelector(".hist-rename")) return;
  const input = document.createElement("input");
  input.className = "hist-rename";
  input.value = c.title;
  input.setAttribute("aria-label", "Conversation title");
  row.replaceChild(input, openBtn);
  input.focus();
  input.select();

  let settled = false;
  const commit = (save) => {
    if (settled) return;
    settled = true;
    if (save) {
      // An empty title is treated as "I changed my mind", not as a title.
      conversations = Conversations.renameConversation(conversations, c.id, input.value);
      saveConversations();
    }
    renderAllHistories();
  };
  input.onkeydown = (e) => {
    if (e.key !== "Enter" && e.key !== "Escape") return;
    e.preventDefault();
    e.stopPropagation();          // Escape here means "cancel the rename" only
    commit(e.key === "Enter");
  };
  input.onblur = () => commit(true);
}

function deleteConversation(id) {
  const wasOpen = id === currentId;
  conversations = Conversations.deleteConversation(conversations, id);
  pendingDelete = null;
  clearTimeout(pendingDeleteTimer);
  // startNewConversation aborts any in-flight stream and restores the welcome
  // screen, which is exactly what deleting the open conversation should do.
  // In voice mode the transcript is the screen, so it has to be reset as well
  // — and whatever the agent is saying about the deleted thread stopped.
  if (wasOpen && vm.on) resetVoiceThread("Deleted. What would you like to look at next?");
  else if (wasOpen) startNewConversation();
  saveConversations();
  renderAllHistories();
}

function clearAllConversations() {
  conversations = [];
  if (vm.on) resetVoiceThread("Cleared. What would you like to look at next?");
  else startNewConversation();
  saveConversations();
  renderAllHistories();
}

/* Both conversation lists — the sidebar's and voice mode's — are drawn from
   the same array by the same code, so pinning, deleting and grouping cannot
   drift apart between the two modes. */
function renderHistoryInto(box, opts) {
  box.innerHTML = "";
  if (!conversations.length) {
    box.innerHTML = `<div class="hist-empty">Nothing yet</div>`;
    return;
  }
  const pinned = conversations.filter((c) => c.pinned);
  const rest = conversations.filter((c) => !c.pinned);
  const section = (label) => {
    const d = document.createElement("div");
    d.className = "sb-section";
    d.textContent = label;
    box.appendChild(d);
  };
  // Headers only earn their space once there is something in both groups.
  if (pinned.length && rest.length) {
    section("Pinned");
    pinned.forEach((c) => box.appendChild(historyRow(c, opts)));
    section("Recent");
    rest.forEach((c) => box.appendChild(historyRow(c, opts)));
  } else {
    Conversations.sortConversations(conversations)
      .forEach((c) => box.appendChild(historyRow(c, opts)));
  }
}

function renderHistory() {
  const clearBtn = $("#clearAll");
  if (clearBtn) clearBtn.disabled = !conversations.length;
  renderHistoryInto(els.history, {});
}

/** Rebuild a finished turn with no typing animation. */
function replayTurn(question, payload) {
  const turn = addTurn(question);
  turn.querySelector(".thinking")?.remove();
  turn.querySelector(".orb-wrap.inline")?.classList.remove("thinking-orb");
  const body = turn.querySelector(".ai-body");
  body.innerHTML = md(payload.text || "");
  renderEvidence(turn, payload);
}

function openConversation(id) {
  const conv = conversations.find((c) => c.id === id);
  if (!conv || busy) return;
  currentId = id;
  chatHistory = conv.chatHistory || [];
  convState = conv.convState || {};
  els.thread.innerHTML = "";
  enterThread();
  conv.turns.forEach((t) => replayTurn(t.q, t.payload));
  renderAllHistories();
  els.thread.scrollTop = 0;
  if (window.innerWidth <= 900) setSidebar(false);
}

/* Shared by the sidebar and by voice mode, so starting a fresh conversation
   means the same thing in both places: new context for the agent, not just a
   cleared screen. */
function startNewConversation() {
  /* Abandon anything still streaming. "New chat" used to be ignored outright
     while a request was in flight, so the answer to the abandoned question
     arrived in the fresh conversation a moment later. */
  askAbort?.abort();
  chatHistory = []; convState = {}; currentId = null;
  els.thread.innerHTML = "";
  els.thread.classList.add("hidden");
  els.welcome.classList.remove("hidden");
  renderAllHistories();
}

function newChat() {
  startNewConversation();
  els.input.focus();
}

/* ─────────────────────────────── voice ─────────────────────────────── */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognizer = null;

/* Generic speech recognition mangles aviation vocabulary: "BDL" comes back as
   "bee dee el", "Logan" as a name. Normalising before the text reaches the
   agent is the difference between a voice demo that works and one that fails
   on its first question. Corrections are shown, never applied silently. */
const LETTERS = { bee:"b", see:"c", sea:"c", dee:"d", ee:"e", eff:"f", gee:"g",
  aitch:"h", eye:"i", jay:"j", kay:"k", el:"l", em:"m", en:"n", oh:"o", pee:"p",
  cue:"q", queue:"q", are:"r", ess:"s", tee:"t", vee:"v", ex:"x", zee:"z" };
const PHONETIC = { alpha:"a", bravo:"b", charlie:"c", delta:"d", echo:"e", foxtrot:"f",
  golf:"g", hotel:"h", india:"i", juliet:"j", kilo:"k", lima:"l", mike:"m",
  november:"n", oscar:"o", papa:"p", quebec:"q", romeo:"r", sierra:"s", tango:"t",
  uniform:"u", victor:"v", whiskey:"w", xray:"x", yankee:"y", zulu:"z" };
const NICKNAMES = { logan:"BOS", "john wayne":"SNA", "orange county":"SNA", bradley:"BDL",
  "sea tac":"SEA", seatac:"SEA", ohare:"ORD", "o'hare":"ORD", midway:"MDW",
  national:"DCA", dulles:"IAD", laguardia:"LGA", "t f green":"PVD", jetport:"PWM",
  hartsfield:"ATL", "sky harbor":"PHX" };

function normalizeTranscript(text) {
  let out = text; const notes = [];
  for (const [name, code] of Object.entries(NICKNAMES)) {
    const re = new RegExp(`\\b${name}\\b`, "ig");
    if (re.test(out)) { out = out.replace(re, code); notes.push(`${name} → ${code}`); }
  }
  const result = []; let letters = [];
  const flush = () => {
    if (!letters.length) return;
    if (letters.length >= 3) {
      const code = letters.join("").toUpperCase();
      notes.push(`"${letters.join(" ")}" → ${code}`);
      result.push(code);
    } else result.push(...letters);
    letters = [];
  };
  for (const w of out.split(/\s+/)) {
    const k = w.toLowerCase().replace(/[^a-z']/g, "");
    const l = LETTERS[k] || PHONETIC[k] || (k.length === 1 && /[a-z]/.test(k) ? k : null);
    if (l) { letters.push(l); continue; }
    flush(); result.push(w);
  }
  flush();
  return { text: result.join(" "), notes };
}

let formingTurn = null;

/* The live transcript appears as a forming bubble in the thread, so the user
   can read what the agent is hearing while they are still speaking. */
function showForming(text) {
  if (!formingTurn) {
    enterThread();
    formingTurn = document.createElement("div");
    formingTurn.className = "turn";
    formingTurn.innerHTML = `<div class="user-row"><div class="user-msg forming"></div></div>`;
    els.thread.appendChild(formingTurn);
  }
  formingTurn.querySelector(".user-msg").innerHTML =
    text.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]))
    + '<span class="caret"></span>';
  scroll();
}
function clearForming() {
  formingTurn?.remove();
  formingTurn = null;
}

/* Listening happens in a bar above the composer, not a full-screen takeover:
   the conversation stays on screen so the user can read the last answer while
   they decide what to ask next. */
function openVoice() {
  // Voice mode owns the microphone while it is up; two recognisers against one
  // device is a race with no winner.
  if (vm.on) return;
  if (!SR) {
    els.note.textContent = "Voice input needs Chrome, Edge or Safari.";
    setTimeout(() => (els.note.textContent = ""), 4200);
    els.mic.classList.remove("listening");
    return;
  }
  els.listenBar.classList.remove("hidden");
  els.composer.classList.add("listening");
  els.lbState.textContent = "Listening";
  els.lbHeard.textContent = "";
  els.lbWave.classList.remove("idle");

  recognizer = new SR();
  recognizer.lang = "en-US"; recognizer.interimResults = true; recognizer.continuous = false;

  recognizer.onresult = (e) => {
    const last = e.results[e.results.length - 1];
    const raw = last[0].transcript;
    if (!last.isFinal) {
      els.lbHeard.textContent = raw;
      els.input.value = raw;
      showForming(raw);
      return;
    }
    const { text, notes } = normalizeTranscript(raw);
    els.lbState.textContent = "Got it";
    els.lbWave.classList.add("idle");
    els.lbHeard.textContent = notes.length ? `${text}  (${notes.join(", ")})` : text;
    showForming(text);
    setTimeout(() => { closeVoice(); ask(text); }, notes.length ? 900 : 420);
  };
  recognizer.onerror = (e) => {
    els.lbState.textContent = e.error === "not-allowed"
      ? "Microphone blocked" : "Didn't catch that";
    els.lbWave.classList.add("idle");
    setTimeout(closeVoice, 1600);
  };
  recognizer.onend = () => els.lbWave.classList.add("idle");
  try { recognizer.start(); } catch { /* already running */ }
}

function closeVoice() {
  try { recognizer?.stop(); } catch {}
  recognizer = null;
  els.listenBar.classList.add("hidden");
  els.composer.classList.remove("listening");
  els.mic.classList.remove("listening");
  els.input.value = "";
  clearForming();
}

/* ─────────────────────────── speech output ─────────────────────────── */
/* Default system voices sound robotic because they are the low-quality
   fallbacks. Most machines ship better ones, and on macOS the Enhanced and
   Premium downloads are dramatically better again, so prefer those by name
   before falling back to whatever exists. */
const FEMALE_VOICES = ["Ava", "Allison", "Samantha", "Susan", "Zoe", "Joelle",
  "Nicky", "Karen", "Moira", "Serena", "Fiona", "Tessa", "Google US English"];
const MALE_VOICES = ["Tom", "Aaron", "Evan", "Nathan", "Alex", "Daniel",
  "Oliver", "Rishi", "Lee", "Google UK English Male"];

let voiceList = [];

/* macOS ships a set of novelty voices (Bubbles, Boing, Bad News, Zarvox...)
   alongside the real ones. They are useless here and make the picker look
   broken, so they are filtered out. */
const NOVELTY = /^(albert|bad news|bahh|bells|boing|bubbles|cellos|deranged|good news|jester|junior|organ|princess|ralph|superstar|trinoids|whisper|wobble|zarvox|hysterical|grandma|grandpa|rocko|shelley|sandy|flo|eddy|reed|kathy|agnes|bruce|fred|dennis)\b/i;

function refreshVoices() {
  voiceList = (window.speechSynthesis?.getVoices() || [])
    .filter((v) => /^en/i.test(v.lang) && !NOVELTY.test(v.name));
  const sel = $("#voicePicker");
  if (sel) {
    sel.innerHTML = `<option value="">Best available</option>` + voiceList.map((v) =>
      `<option value="${v.name}">${v.name}${/premium|enhanced/i.test(v.name) ? " ★" : ""} (${v.lang})</option>`).join("");
    sel.value = prefs.voiceName || "";
  }
}
window.speechSynthesis?.addEventListener?.("voiceschanged", refreshVoices);

function pickVoice() {
  if (!voiceList.length) refreshVoices();
  if (prefs.voiceName) {
    const exact = voiceList.find((v) => v.name === prefs.voiceName);
    if (exact) return exact;
  }
  const wanted = prefs.gender === "male" ? MALE_VOICES : FEMALE_VOICES;
  for (const name of wanted) {
    const better = voiceList.find((v) => v.name.includes(name) && /premium|enhanced/i.test(v.name));
    if (better) return better;
    const plain = voiceList.find((v) => v.name.includes(name));
    if (plain) return plain;
  }
  return voiceList.find((v) => v.default) || voiceList[0] || null;
}

let audioEl = null;
let speechStartedAt = 0;

/* Bumped every time speech starts or is torn down. An utterance's completion
   callback checks it before firing, which is how we tell "the agent finished
   its sentence" (resume listening) apart from "we cancelled it" (the
   interrupt path decides what happens next). Without this, cancelling races
   its own callback and two code paths both try to reopen the microphone. */
let speechEpoch = 0;

function stopSpeaking() {
  speechEpoch++;
  /* Drops anything still queued. Each chunk checks the epoch before it starts,
     so cancelling here stops the whole answer, not just the current sentence. */
  try { speechSynthesis?.cancel(); } catch {}
  if (audioEl) {
    const el = audioEl;
    audioEl = null;
    /* Detach before pausing. The old code did `el.src = ""`, which fires an
       `error` event on the element — so `onerror` ran on top of `onended` and
       the completion callback fired twice, re-entering the listen path. */
    el.onended = null; el.onerror = null;
    try { el.pause(); } catch {}
    try { URL.revokeObjectURL(el.src); } catch {}
  }
  speechStartedAt = 0;
}

/* Fade out over ~50ms. Cutting audio dead produces an audible click, which
   makes an interruption feel like a glitch rather than a response.

   Only reachable on the neural path, where we hold the <audio> element.
   `speechSynthesis` exposes no volume on a speaking utterance, so browser
   speech is cancelled outright — one more reason a neural voice is worth
   configuring. */
async function fadeOutSpeech(ms = 50) {
  if (audioEl) {
    const v0 = audioEl.volume, steps = 5;
    for (let i = 1; i <= steps; i++) {
      audioEl.volume = Math.max(0, v0 * (1 - i / steps));
      await sleep(ms / steps);
    }
  }
  stopSpeaking();
}

/* How much of the utterance actually reached the speaker before we stopped.
   The estimator hierarchy and the reasoning behind it live in
   web/turn-taking.js; this only gathers the clock readings it needs. The
   estimator it settled on is recorded so developer mode can show it — when
   truncation looks wrong, which estimator ran is the first thing to know. */
function spokenPrefix() {
  const r = TurnTaking.spokenPrefix(vm.saying, {
    chunks: vm.chunks,
    chunksDone: vm.chunksDone,
    audioDuration: audioEl ? audioEl.duration : NaN,
    audioCurrentTime: audioEl ? audioEl.currentTime : 0,
    saidChars: vm.saidChars,
    elapsedMs: speechStartedAt ? performance.now() - speechStartedAt : 0,
  });
  vm.saidVia = r.via;
  return r.text;
}

/* Speak, preferring a neural voice from the server when one is configured.
   The browser's own voices are the reason synthetic speech still sounds
   synthetic; a neural voice is the only real fix, so we ask the backend first
   and fall back only when no key is set.

   Resolves when audio is genuinely audible, not when the request was sent.
   Callers arm the interruption detector on that promise, and arming it any
   earlier leaves the detector live through the whole TTS round trip — where
   any noise in the room fires a barge-in against an utterance that has not
   started playing yet. */
async function speak(text, onEnd) {
  stopSpeaking();
  const epoch = ++speechEpoch;
  /* Fires at most once, and never for an utterance that was cancelled: a
     cancel means the interrupt path is already deciding what happens next,
     and letting the completion callback run too has both of them reopening
     the microphone. */
  let fired = false;
  const done = () => {
    if (fired || epoch !== speechEpoch) return;
    fired = true;
    onEnd?.();
  };
  if (!text) { done(); return; }

  if (meta?.tts && meta.tts !== "browser") {
    try {
      const r = await fetch("/speak", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, gender: prefs.gender }),
      });
      /* Bail rather than falling through. Dropping out of this branch after a
         cancel would continue to the browser-voice block below and start
         speaking the very utterance that was just called off. */
      if (epoch !== speechEpoch) return;
      if (r.ok) {
        const blob = await r.blob();
        if (epoch !== speechEpoch) return;        // interrupted mid-download
        const el = new Audio(URL.createObjectURL(blob));
        audioEl = el;
        el.onended = () => { if (audioEl === el) audioEl = null; done(); };
        el.onerror = () => { if (audioEl === el) audioEl = null; done(); };
        await el.play();
        speechStartedAt = performance.now();
        return;
      }
    } catch { /* fall through to the browser voice */ }
  }

  if (!window.speechSynthesis) { done(); return; }

  /* One sentence per utterance. Chrome stops speechSynthesis after roughly
     fifteen seconds on a single long one — silently, no end event, the voice
     just stops mid-answer — and a full airport analysis runs well past that.
     Queueing sentences keeps every utterance short enough to finish, and as a
     bonus tells us exactly how much was spoken when the user cuts in. */
  const chunks = TurnTaking.splitForSpeech(text);
  vm.chunks = chunks;
  vm.chunksDone = 0;
  vm.saidChars = 0;
  if (!chunks.length) { done(); return; }

  for (let i = 0; i < chunks.length; i++) {
    if (epoch !== speechEpoch) return;         // interrupted: abandon the queue
    vm.chunksDone = i;
    vm.saidChars = 0;
    await speakOne(chunks[i], i === 0);
  }
  if (epoch !== speechEpoch) return;
  vm.chunksDone = chunks.length;
  done();

  /** Resolves when this one utterance ends, is cancelled, or fails. */
  function speakOne(chunk, isFirst) {
    return new Promise((resolve) => {
      const u = new SpeechSynthesisUtterance(chunk);
      const v = pickVoice();
      if (v) { u.voice = v; u.lang = v.lang; }
      u.rate = 0.99; u.pitch = 1.0;
      /* Character reached within this chunk. Chrome never fires it for remote
         voices, which is why the chunk index above is the real accounting and
         this only refines it. */
      u.onboundary = (e) => { if (e.charIndex != null) vm.saidChars = e.charIndex; };

      let settled = false;
      const finish = () => { if (!settled) { settled = true; resolve(); } };
      u.onstart = () => { if (isFirst) speechStartedAt = performance.now(); };
      u.onend = finish;
      u.onerror = finish;
      speechSynthesis.speak(u);
      /* Chrome occasionally loses an utterance outright and fires nothing.
         Without a ceiling the queue would stall with the orb on "Speaking"
         for ever, so bound the wait by how long the words could possibly
         take, generously. */
      const words = chunk.trim().split(/\s+/).length;
      setTimeout(finish, 4000 + (words / 165) * 60000 * 2);
    });
  }
}

/* ───────────────────── how interruption works here ───────────────────── */
/* It is explicit. Stop, the orb, or the spacebar. Nothing listens while the
   agent talks, so it cannot interrupt itself — that is a property of the code
   rather than a threshold that happens to hold.

   There used to be an energy detector here, sampling a second, echo-cancelled
   capture during playback. It could not work: browser AEC references *system*
   playback, and speechSynthesis renders outside the page's audio graph, so on
   speakers the agent's own voice reached it as clean sustained energy and it
   duly interrupted the agent mid-sentence. See web/turn-taking.js for why
   raising the threshold is not a fix, and what a real barge-in would need.

   SpeechRecognition opens its own microphone and accepts no MediaStream and
   no constraints, so we cannot filter what it hears. The only control we have
   is whether it runs at all — hence the latch in vmStopListening(), and the
   care in TurnTaking.shouldReopenMic over when it may reopen. */

/* ─────────────────────── voice conversation mode ─────────────────────── */
/* A different thing from dictation. Dictation types for you; this is a
   back-and-forth: it listens, answers out loud, then listens again, and the
   words from both sides appear under the orb so you can follow along. The
   orb's animation is the state indicator. */
const vm = {
  on: false, state: "idle", recog: null,
  paused: false, liveEl: null,
  suppress: false,            // the recogniser is closed ON PURPOSE, keep it shut
  restartTimer: null,         // pending reopen, cancellable
  responding: false,          // re-entrancy guard around a turn
  heldForSettings: false,     // turn suspended while the Settings sheet is open
  abort: null,                // AbortController for the in-flight /chat request
  speakingWords: new Set(),   // what the agent is saying right now
  spokeAt: 0,
  saying: "",                 // full text of the current utterance
  chunks: [],                 // it, split into the sentences we queue one by one
  chunksDone: 0,              // how many of those the voice has finished
  saidChars: 0,               // how far into the current chunk it has reached
  saidVia: "",                // which estimator produced that figure
  pendingOffer: null,         // the question we just asked, so "yes" is an answer
};

/* The microphone hears the agent through the speakers, so the recogniser
   transcribes the agent's own answer and treats it as a new question. Browser
   echo cancellation helps but does not solve it, because the speech recogniser
   opens its own capture path.

   The reliable signal is content: if what we just "heard" is largely made of
   the words we are currently saying, it is echo, not a person. Real
   interruptions almost never repeat the agent's sentence back verbatim. */
function looksLikeEcho(text) {
  return TurnTaking.looksLikeEcho(text, vm.speakingWords);
}

function setSpeakingText(text) {
  vm.speakingWords = TurnTaking.speakingWordsOf(text);
  vm.spokeAt = Date.now();
}

function vmSetState(state, label) {
  vm.state = state;
  const o = $("#vmOrb");
  o.classList.remove("listening", "thinking", "speaking", "idle");
  o.classList.add(state);
  $("#vmState").textContent = label;
}

/* A ranking read aloud is unusable, so the voice summarises it. The table is
   what the user asked for, though, so it belongs in the transcript. */
function vmEvidenceMarkdown(payload) {
  const rows = payload && payload.evidence && payload.evidence.results;
  if (!Array.isArray(rows) || rows.length < 2) return "";
  return "\n\n| # | Airport | Tier | Score |\n|---|---|---|---|\n" +
    rows.map((r, i) => `| ${i + 1} | **${r.code}** ${(r.name || "").slice(0, 22)}` +
                       ` | ${r.tier || "\u2013"} | ${r.score} |`).join("\n");
}

function vmLine(who, text, live = false) {
  const el = document.createElement("div");
  el.className = `vm-line ${who}${live ? " live" : ""}`;
  // The agent's side is markdown -- tables, numbered lists, bold. It used to be
  // escaped and dumped raw, so the transcript showed literal pipes and
  // asterisks. What the user says is plain text and stays escaped.
  const body = who === "agent" ? md(text) : Markdown.escape(text);
  el.innerHTML = `<span class="who">${who === "user" ? "You" : AGENT_NAME}</span>` +
                 `<div class="vm-body">${body}</div>`;
  $("#vmTranscript").appendChild(el);
  $("#vmTranscript").scrollTop = $("#vmTranscript").scrollHeight;
  return el;
}

async function startVoiceChat() {
  if (!SR) {
    els.note.textContent = "Voice conversation needs Chrome, Edge or Safari.";
    setTimeout(() => (els.note.textContent = ""), 4200);
    return;
  }
  vm.on = true; vm.paused = false; vm.responding = false;
  $("#voiceMode").classList.remove("hidden");
  // Dictation opens its own recogniser and never checks whether a voice
  // conversation is starting. Without this, both run against one microphone.
  closeVoice();
  renderVoiceTranscript();      // pick the conversation up where it left off
  renderVoiceHistory();
  setVmButton("pause");
  vmResumeListening();
}

function endVoiceChat() {
  vm.on = false;
  vm.heldForSettings = false;
  vm.speakingWords.clear();
  vm.abort?.abort();          // don't leave a stream running behind a closed UI
  vmStopListening();
  stopSpeaking();
  vm.saying = ""; vm.chunks = []; vm.chunksDone = 0; vm.saidChars = 0; vm.saidVia = "";
  $("#voiceMode").classList.add("hidden");
}

function newVoiceConversation() {
  resetVoiceThread("New conversation. What would you like to look at?");
}

/* Back to an empty voice thread, with something said about why. Shared by
   "New chat" and by deleting the conversation that is currently open.

   Stop whatever is being said, and whatever is still being fetched: continuing
   to talk about the old thread while the transcript says it is gone would be
   confusing. */
function resetVoiceThread(message) {
  vm.abort?.abort();
  stopSpeaking();
  vm.speakingWords.clear();
  vm.saying = ""; vm.chunks = []; vm.chunksDone = 0; vm.saidChars = 0; vm.saidVia = "";
  startNewConversation();
  $("#vmTranscript").innerHTML = "";
  vmLine("agent", message);
  setVmButton("pause");
  vmResumeListening();
}

/* The voice transcript is the chat thread's counterpart, so it has to open
   showing the conversation so far rather than a blank screen. Starting empty
   was most of why voice mode felt like it had no memory: the agent was being
   sent the full history on every turn and answering from it, but nothing on
   screen said so. */
function renderVoiceTranscript() {
  const box = $("#vmTranscript");
  if (!box) return;
  box.innerHTML = "";
  const conv = currentConv();
  if (!conv) return;
  conv.turns.forEach((t) => {
    vmLine("user", t.q);
    // The spoken wording where we have it, so the transcript reads as what
    // was actually said out loud rather than the written answer.
    vmLine("agent", t.payload?.text || t.payload?.speech_text || "");
  });
  box.scrollTop = box.scrollHeight;
}

function renderVoiceHistory() {
  const box = $("#vmHistory");
  if (!box) return;
  renderHistoryInto(box, { actions: ["pin", "del"], onOpen: openVoiceConversation });
}

function openVoiceConversation(id) {
  const conv = conversations.find((c) => c.id === id);
  if (!conv) return;
  // Don't switch out from under an answer in progress.
  if (vm.state === "speaking" || vm.state === "thinking") interruptSpeech();
  openConversation(id);
  renderVoiceTranscript();
  vmLine("agent", `Switched to: ${conv.title}`);
}

/* Listening.
   A single recogniser runs while the agent is idle, with continuous results,
   and the turn boundary is decided by the browser's own end-of-speech
   detection rather than by us guessing at silence.

   It is closed for the whole of a response, and reopened only through
   vmResumeListening(). Everything about the reopen is deliberate: see
   TurnTaking.shouldReopenMic for why the obvious version of the `onend`
   handler makes the agent interrupt itself. */

function vmListen() {
  if (!vm.on || vm.paused || vm.suppress) return;
  if (vm.recog) return;                     // one recogniser at a time

  const r = new SR();
  vm.recog = r;
  r.lang = "en-US";
  r.interimResults = true;
  r.continuous = true;

  r.onresult = (e) => {
    if (!vm.on || vm.paused) return;
    const res = e.results[e.results.length - 1];
    const text = res[0].transcript.trim();

    /* The recogniser is closed while the agent talks, so its own voice should
       never reach here. This catches the speaker tail in the moment after
       playback stops and before the room goes quiet. The state check is a
       belt-and-braces guard for results the browser delivers late, after we
       have already moved on. */
    if (Date.now() - vm.spokeAt < 700 && looksLikeEcho(text)) return;
    if (vm.state === "speaking" || vm.state === "thinking") return;

    if (!res.isFinal) {
      if (!text) return;
      if (!vm.liveEl) vm.liveEl = vmLine("user", text, true);
      else vm.liveEl.innerHTML = `<span class="who">You</span>${text}`;
      $("#vmTranscript").scrollTop = $("#vmTranscript").scrollHeight;
      return;
    }

    // Final result: this is the end of a spoken turn.
    const { text: clean } = normalizeTranscript(text);
    /* Both forms, because normalisation spells out letters: "i see" becomes
       "i c", which no longer looks like a backchannel even though it is one. */
    const answering = { awaitingAnswer: !!vm.pendingOffer };
    if (!TurnTaking.isUsableTurn(text, answering) ||
        !TurnTaking.isUsableTurn(clean, answering)) {
      // "mm-hmm" is not a question. "Why?" is — see isUsableTurn.
      vm.liveEl?.remove(); vm.liveEl = null; return;
    }
    vm.liveEl?.remove(); vm.liveEl = null;
    vmLine("user", clean);
    vmRespond(clean);
  };

  r.onerror = (e) => {
    if (!vm.on) return;
    if (e.error === "not-allowed") {
      vmSetState("idle", "Microphone blocked");
      setTimeout(endVoiceChat, 1800);
    }
    // "no-speech" and "aborted" are normal in a continuous session; onend restarts.
  };

  r.onend = () => {
    if (vm.recog === r) vm.recog = null;
    /* `end` fires for the browser's own end-of-speech timeout, for errors,
       AND for our own abort() — the handler cannot tell them apart. Restarting
       unconditionally (which is what this used to do) meant closing the
       microphone before speaking had no effect whatsoever: abort() fired
       `end`, a fresh recogniser opened 200 ms later, and it ran for the entire
       answer with the speakers playing into it. */
    if (!TurnTaking.shouldReopenMic(vm)) return;
    clearTimeout(vm.restartTimer);
    vm.restartTimer = setTimeout(vmListen, 200);
  };

  /* The label belongs to vmResumeListening, not here: setting it again would
     stamp on "Go ahead", which is how the agent acknowledges being cut off. */
  try { r.start(); } catch { vm.recog = null; }
}

/* Close the recogniser and latch it shut.
   The latch matters because `end` is asynchronous: by the time it arrives the
   state may have moved on, so a state check alone would race. Only
   vmResumeListening() lifts it. */
function vmStopListening() {
  vm.suppress = true;
  clearTimeout(vm.restartTimer);
  vm.restartTimer = null;
  const r = vm.recog;
  vm.recog = null;
  try { r?.abort(); } catch {}
}

/* The one way back to listening. Lifting the latch and reopening the
   microphone are the same act, so they live in the same function — every
   caller that used to do `vmSetState("listening"); vmListen();` goes through
   here, and none of them can forget the latch. */
function vmResumeListening(label = "Listening") {
  vm.suppress = false;
  if (!vm.on || vm.paused) return;
  vmSetState("listening", label);
  vmListen();
}

async function vmRespond(question) {
  /* One turn at a time. Without this, two final results arriving close
     together (which happens: the recogniser can deliver a late result just as
     the next one lands) start two overlapping answers. */
  if (vm.responding) return;
  vm.responding = true;

  /* Close the recogniser for the whole answer — thinking included, not just
     speaking. Interruption during the answer is the energy detector's job on
     our own echo-cancelled capture, or an explicit tap on Stop or the orb. */
  vmStopListening();
  vmSetState("thinking", "Thinking");
  /* Offer Stop from the moment the turn begins. It used to appear only once
     audio started, so there was a window — the whole of the model call — with
     no way to call the turn off at all. */
  setVmButton("stop");

  /* Cancellable, so interrupting during "Thinking" actually stops the turn.
     Without it the request ran to completion and the agent started speaking a
     now-unwanted answer over whatever the user had begun saying. */
  const ctl = new AbortController();
  vm.abort = ctl;

  try {
    const resp = await fetch("/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: question, history: chatHistory,
                             state: convState, voice: true }),
      signal: ctl.signal,
    });
    const reader = resp.body.getReader(); const dec = new TextDecoder();
    let buf = "", payload = null;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const frames = buf.split("\n\n"); buf = frames.pop();
      for (const f of frames) {
        const e = f.match(/^event: (.+)$/m), d = f.match(/^data: ([\s\S]+)$/m);
        if (!e || !d) continue;
        let p; try { p = JSON.parse(d[1]); } catch { continue; }
        if (e[1].trim() === "progress") $("#vmState").textContent = p.steps?.[0] || "Thinking";
        if (e[1].trim() === "done") payload = p;
      }
    }
    if (!payload) throw new Error("no response");

    convState = payload.state || convState;
    chatHistory = chatHistory.concat([{ role: "user", content: question },
                                      { role: "assistant", content: payload.text || "" }]).slice(-12);
    // The spoken conversation lands in the chat too, so it is still there
    // after you leave voice mode.
    if (!currentConv()) beginConversation(question);
    recordTurn(question, payload);
    renderVoiceHistory();
    enterThread();
    replayTurn(question, payload);

    // Two different jobs: the transcript shows the written answer so tables and
    // lists are readable; the voice gets the same words with the markdown
    // stripped, because text-to-speech otherwise reads the asterisks out loud.
    // The voice prompt says detail belongs on the screen, not in the speaker,
    // so the spoken answer is three sentences and the ranking the user actually
    // asked for goes into the transcript, where it can be read.
    vm.pendingOffer = payload.followup || null;
    const written = (payload.text || payload.speech_text || "") +
                    vmEvidenceMarkdown(payload);
    const said = Markdown.plain(payload.speech_text || payload.text || "");
    vmSetState("speaking", "Speaking");
    vmLine("agent", written);
    setSpeakingText(said);
    setVmButton("stop");
    vm.saying = said;
    vm.chunks = []; vm.chunksDone = 0;   // speak() fills these in
    vm.saidChars = 0;
    vm.saidVia = "";

    /* Awaited: speak() resolves when audio is actually audible. Arming the
       detector before that point leaves it live through the TTS round trip,
       where any noise fires a barge-in against an utterance that has not
       started. */
    await speak(said, () => {
      vm.spokeAt = Date.now();
      setTimeout(() => vm.speakingWords.clear(), 600);
      setVmButton("pause");
      vmResumeListening();
    });
  } catch (err) {
    if (err.name === "AbortError") return;   // interrupted on purpose
    vmLine("agent", `Something went wrong: ${err.message}`);
    vmSetState("idle", "Trouble connecting");
    setVmButton("pause");
    setTimeout(() => vmResumeListening(), 1400);
  } finally {
    vm.responding = false;
    if (vm.abort === ctl) vm.abort = null;
  }
}

/* One button, two jobs: interrupt while the agent is talking, pause the
   microphone the rest of the time. */
function setVmButton(mode) {
  const b = $("#vmMute");
  if (!b) return;
  b.dataset.mode = mode;
  b.textContent = mode === "stop" ? "Stop" : vm.paused ? "Resume" : "Pause";
  const hint = $("#vmHint");
  if (hint) {
    /* Says what the controls are, because there is no automatic barge-in to
       fall back on: talking over the agent does nothing by design. */
    hint.textContent = mode === "stop"
      ? "Stop, tap the orb, or press space to interrupt"
      : "It is listening. Just start talking.";
  }
}

/* The only way an answer stops early. Every caller is a deliberate user
   action — Stop, the orb, the spacebar, or opening Settings mid-answer. */
async function interruptSpeech() {
  const heard = spokenPrefix();          // read the clocks before stopping them
  const via = vm.saidVia;
  const beforeAnyAudio = vm.state === "thinking";

  /* Cancel the request too, not just the audio. Interrupting during "Thinking"
     used to stop nothing: the stream ran to completion and the agent started
     reading out an answer to a question the user had already moved on from. */
  vm.abort?.abort();

  await fadeOutSpeech();
  vm.speakingWords.clear();

  // Record only what was actually said out loud. Storing the full answer would
  // leave the model convinced it delivered things the user never heard.
  if (vm.saying && heard.length < vm.saying.length) {
    truncateLastAnswer(heard);
    const el = Array.from(document.querySelectorAll(".vm-line.agent")).pop();
    if (el) {
      // Which estimator produced the cut, when the trace toggle is on: if a
      // truncation looks wrong, that is the first thing worth knowing.
      const note = prefs.trace ? ` (interrupted · ${via})` : " (interrupted)";
      el.innerHTML = `<span class="who">${AGENT_NAME}</span>${
        heard.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]))}` +
        `<span class="cut">${note}</span>`;
    }
  }
  vm.saying = ""; vm.chunks = []; vm.chunksDone = 0; vm.saidChars = 0; vm.saidVia = "";

  /* Stopped before a word came out. Nothing goes into chatHistory — the turn
     genuinely did not happen — but the transcript still shows the question,
     so say what became of it rather than leaving it hanging unanswered. */
  if (beforeAnyAudio) vmLine("agent", "Stopped.");

  setVmButton("pause");
  vmResumeListening("Go ahead");
}

function truncateLastAnswer(heard) {
  for (let i = chatHistory.length - 1; i >= 0; i--) {
    if (chatHistory[i].role === "assistant") {
      chatHistory[i].content = heard.trim() + " [interrupted here]";
      break;
    }
  }
  /* The conversation record keeps its own copy, and that copy is what gets
     restored when the chat is reopened. Without writing it back, the
     truncation lasted only until you switched conversations, and the model
     was handed the full answer it never actually delivered. */
  const conv = currentConv();
  if (conv) {
    conv.chatHistory = chatHistory;
    saveConversations();
  }
}

/* ─────────────────────────────── settings ─────────────────────────────── */
function syncSettings() {
  $$("#genderRadios button").forEach((b) => b.classList.toggle("sel", b.dataset.gender === prefs.gender));
  const sel = $("#voicePicker"); if (sel) sel.value = prefs.voiceName || "";
}

/* ─────────────────────────────── wiring ─────────────────────────────── */
els.welcome.querySelector("#suggestions").innerHTML = SAMPLES.map((q) =>
  `<button><span class="q">${q}</span><span class="arrow">
   <svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.7">
   <path d="M4 10h11M10.5 5.5L15 10l-4.5 4.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span></button>`).join("");
$$("#suggestions button").forEach((b) => { b.onclick = () => ask(b.querySelector(".q").textContent); });

$("#composer").addEventListener("submit", (e) => { e.preventDefault(); ask(els.input.value); });
els.mic.onclick = () => { els.mic.classList.add("listening"); openVoice(); };
$("#voiceChatBtn").onclick = startVoiceChat;
$("#vmClose").onclick = endVoiceChat;
$("#vmNewChat").onclick = newVoiceConversation;
/* Tapping the orb interrupts: stop talking and listen. That is the single
   most important control in a spoken conversation. */
$("#vmOrb").onclick = () => {
  if (!vm.on) return;
  // Thinking counts. Waiting out a model call you no longer want is the most
  // irritating thing a voice agent can make you do.
  if (vm.state === "speaking" || vm.state === "thinking") interruptSpeech();
};
$("#vmMute").onclick = (e) => {
  if (e.currentTarget.dataset.mode === "stop") { interruptSpeech(); return; }
  vm.paused = !vm.paused;
  if (vm.paused) {
    vmStopListening(); stopSpeaking();
    vmSetState("idle", "Paused");
  } else {
    vmResumeListening();
  }
  setVmButton("pause");
};
$("#lbStop").onclick = closeVoice;
/* One function decides whether the sidebar is open, because on a phone it is
   an overlay and the scrim has to agree with it. Toggling the class in two
   places is how the two drift apart and strand a scrim over a closed panel. */
function setSidebar(open) {
  els.sidebar.classList.toggle("collapsed", !open);
  $("#scrim").classList.toggle("hidden", !open);
}
$("#toggleSidebar").onclick = () =>
  setSidebar(els.sidebar.classList.contains("collapsed"));
$("#scrim").onclick = () => setSidebar(false);
$("#newChat").onclick = newChat;
/* Clear all is two-step, like the per-row delete: destructive, no undo, and
   the label carries the confirmation so no dialog is needed. */
{
  const btn = $("#clearAll"), lbl = btn.querySelector(".lbl");
  let armed = false, timer = null;
  const reset = () => {
    armed = false;
    btn.classList.remove("armed");
    lbl.textContent = "Clear all conversations";
  };
  btn.onclick = () => {
    if (!conversations.length) return;
    if (!armed) {
      armed = true;
      btn.classList.add("armed");
      lbl.textContent = "Click again to clear all";
      clearTimeout(timer);
      timer = setTimeout(reset, 4000);
      return;
    }
    clearTimeout(timer);
    reset();
    clearAllConversations();
  };
}
/* One handler, both switches: the header's and voice mode's. They render from
   `data-theme` on <html>, so flipping it keeps them in step by itself. */
$$(".theme-switch").forEach((sw) => {
  sw.onclick = () => {
    prefs.theme = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    localStorage.setItem("w.theme", prefs.theme); applyTheme(); syncSettings(); refreshVoices();
    // Voice lists populate asynchronously in most browsers.
    setTimeout(refreshVoices, 400);
  };
});
/* Settings is reachable from the voice conversation too — it is where the voice
   itself is chosen, so it is needed most exactly there.

   Opening it holds the turn. Three things would otherwise go wrong: the
   recogniser would transcribe you reading the sheet; a voice preview would be
   heard as your next question; and a preview started while the agent is
   mid-answer cancels that utterance, whose completion callback is what hands
   the microphone back — leaving the orb stuck on "Speaking" for good. */
async function openSettings() {
  els.settings.classList.remove("hidden");
  syncSettings();
  if (!vm.on || vm.paused || vm.heldForSettings) return;
  vm.heldForSettings = true;
  // Truncates the stored answer to what was actually heard, and aborts an
  // in-flight request, exactly as tapping the orb would.
  if (vm.state === "speaking" || vm.state === "thinking") await interruptSpeech();
  vmStopListening();
  vmSetState("idle", "Settings open");
  setVmButton("pause");
}

function closeSettings() {
  els.settings.classList.add("hidden");
  if (!vm.heldForSettings) return;
  vm.heldForSettings = false;
  stopSpeaking();               // cut a voice preview still playing
  vmResumeListening();
}

/* Settings is reachable from the sidebar in either mode, and from the voice
   top bar on screens too narrow to show a sidebar at all. */
$$(".js-open-settings").forEach((b) => { b.onclick = openSettings; });
$("#closeSettings").onclick = closeSettings;
els.settings.onclick = (e) => { if (e.target === els.settings) closeSettings(); };
document.addEventListener("keydown", (e) => {
  /* Spacebar stops the agent talking. With no automatic barge-in, interrupting
     has to be effortless, and reaching for the mouse mid-sentence is not. */
  if (e.code === "Space" && vm.on && !vm.paused &&
      (vm.state === "speaking" || vm.state === "thinking")) {
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName || "")) return;
    e.preventDefault();
    interruptSpeech();
    return;
  }
  if (e.key !== "Escape") return;
  // The sheet is on top, so Escape belongs to it first. Without this, one
  // press closed the settings AND ended the conversation underneath.
  if (!els.settings.classList.contains("hidden")) { closeSettings(); return; }
  closeVoice();
  endVoiceChat();
});
$$("#genderRadios button").forEach((b) => b.onclick = () => {
  prefs.gender = b.dataset.gender; prefs.voiceName = "";
  localStorage.setItem("w.gender", prefs.gender);
  localStorage.setItem("w.voiceName", "");
  syncSettings();
  const v = pickVoice();
  speak(v ? `Hello, I'm ${v.name.replace(/\s*\(.*\)/, "")}. I'll read your answers.`
          : "No speech voices are installed on this system.");
});
$("#voicePicker").onchange = (e) => {
  prefs.voiceName = e.target.value;
  localStorage.setItem("w.voiceName", prefs.voiceName);
  speak("This is how I'll sound.");
};
$("#voiceTest").onclick = () =>
  speak("Boston Logan is running near capacity, and it has very little room to expand.");

applyTheme(); syncSettings(); refreshVoices(); loadStoredConversations();
// Voice lists populate asynchronously in most browsers.
setTimeout(refreshVoices, 400);

fetch("/meta").then((r) => r.json()).then((m) => {
  meta = m;
  const mode = m.data?.data_mode;
  if (mode === "synthetic") {
    els.banner.classList.remove("hidden");
    els.banner.innerHTML = `<b>Demonstration data.</b> Airports, coordinates, runway geometry
      and route distances are real. Passenger and flight <b>volumes are modelled</b>,
      so treat them as illustrative. Add a BTS T-100 export at
      <code>data/raw/t100_segment.csv</code> and re-run
      <code>python3 -m etl.build</code> for measured traffic.`;
  }
  if (!SR) els.mic.title = "Voice input needs Chrome, Edge or Safari";
});

els.input.focus();

/* Deep link: /?q=... asks one question on load. Useful for sharing a specific
   answer and for automated screenshots. The query is stripped from the URL so
   a refresh doesn't silently re-run it. */
const deepLink = new URLSearchParams(location.search).get("q");
if (deepLink) {
  window.history.replaceState({}, "", location.pathname);
  setTimeout(() => ask(deepLink), 120);
}
