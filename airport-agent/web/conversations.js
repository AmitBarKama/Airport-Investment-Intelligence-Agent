/* Conversation list operations.
   ─────────────────────────────────────────────────────────────────────────
   Pure functions over an array of conversation records: no DOM, no
   localStorage. Same shape as web/turn-taking.js, and for the same reason —
   the one genuinely subtle rule in here (pinning versus the storage cap) is
   the kind that fails silently, weeks later, by quietly deleting something
   the user explicitly asked to keep.

   A conversation record, as built by beginConversation() in app.js:
     { id, title, at, turns[], chatHistory[], convState{}, pinned? }

   `pinned` is optional. Records saved before it existed simply lack it, which
   reads as falsy — no migration needed. */

(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.Conversations = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  /* The list is newest-first (beginConversation unshifts), and stays that way.
     Sorting is a *view* concern, so it is applied at render time rather than
     by reordering the stored array — otherwise "most recent" and "insertion
     order" drift apart and eviction starts removing the wrong records. */
  const MAX_CONVERSATIONS = 20;

  /** Pinned first, insertion order preserved inside each group. */
  function sortConversations(list) {
    const src = Array.isArray(list) ? list : [];
    return [...src.filter(isPinned), ...src.filter((c) => !isPinned(c))];
  }

  function isPinned(c) {
    return !!(c && c.pinned);
  }

  /* Trim to the storage cap.

     This replaces a blind `slice(0, 20)`, which had no idea what a pin was: a
     pinned conversation that drifted past the twentieth slot was evicted
     exactly like any other, so pinning it bought nothing. Pinned records are
     therefore exempt — only unpinned ones are dropped, oldest (last) first.

     If someone pins more than the cap, all the pins survive and the list is
     simply longer than MAX_CONVERSATIONS. Pinning is explicit intent; honouring
     it beats honouring a number nobody chose. */
  function capConversations(list, max = MAX_CONVERSATIONS) {
    const src = Array.isArray(list) ? list : [];
    let budget = max - src.filter(isPinned).length;
    return src.filter((c) => isPinned(c) || budget-- > 0);
  }

  /** Toggle the pin on one conversation. Returns a new array. */
  function togglePin(list, id) {
    return (list || []).map((c) =>
      c.id === id ? { ...c, pinned: !isPinned(c) } : c);
  }

  function deleteConversation(list, id) {
    return (list || []).filter((c) => c.id !== id);
  }

  /* Titles are generated from the first question and truncated to 38 chars, so
     a hand-typed one gets a little more room but not unlimited: the sidebar is
     258px wide and anything longer is ellipsis either way. An empty or
     whitespace-only rename is a no-op rather than an error — the user almost
     certainly meant to cancel. */
  const MAX_TITLE = 60;

  function cleanTitle(raw) {
    return String(raw == null ? "" : raw).replace(/\s+/g, " ").trim().slice(0, MAX_TITLE);
  }

  function renameConversation(list, id, title) {
    const clean = cleanTitle(title);
    if (!clean) return list || [];
    return (list || []).map((c) => (c.id === id ? { ...c, title: clean } : c));
  }

  return {
    MAX_CONVERSATIONS, MAX_TITLE,
    sortConversations, capConversations, togglePin,
    deleteConversation, renameConversation, cleanTitle, isPinned,
  };
}));
