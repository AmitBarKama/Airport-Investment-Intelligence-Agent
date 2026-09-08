/* Tests for the conversation list operations.
   Run with:  node --test tests/test_conversations.mjs   (or: make test)

   The one that matters is "a pinned conversation survives the cap". Before
   this module, the cap was two hardcoded `slice(0, 20)` calls that knew
   nothing about pins, so pinning a chat and then starting twenty more would
   delete the pinned one without a word. */

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const C = require("../web/conversations.js");

/** n conversations, newest first, matching what beginConversation() builds. */
const make = (n, over = () => ({})) =>
  Array.from({ length: n }, (_, i) => ({
    id: `c${n - i}`, title: `chat ${n - i}`, at: 1000 + (n - i),
    turns: [], chatHistory: [], convState: {}, ...over(i),
  }));

const ids = (list) => list.map((c) => c.id);

/* ─────────────────────────────── sorting ───────────────────────────────── */

test("pinned conversations sort to the top", () => {
  const list = make(4);                       // c4 c3 c2 c1
  const pinned = C.togglePin(list, "c2");
  assert.deepEqual(ids(C.sortConversations(pinned)), ["c2", "c4", "c3", "c1"]);
});

test("sorting is stable inside each group", () => {
  let list = make(5);                         // c5 c4 c3 c2 c1
  list = C.togglePin(list, "c2");
  list = C.togglePin(list, "c4");
  assert.deepEqual(ids(C.sortConversations(list)), ["c4", "c2", "c5", "c3", "c1"]);
});

test("sorting does not mutate the source array", () => {
  const list = make(3);
  const before = ids(list);
  C.sortConversations(C.togglePin(list, "c1"));
  assert.deepEqual(ids(list), before);
});

test("sorting tolerates junk", () => {
  assert.deepEqual(C.sortConversations(null), []);
  assert.deepEqual(C.sortConversations(undefined), []);
});

/* ──────────────────────────────── the cap ──────────────────────────────── */

test("an over-long list is trimmed to the cap", () => {
  const capped = C.capConversations(make(25));
  assert.equal(capped.length, C.MAX_CONVERSATIONS);
  assert.equal(capped[0].id, "c25", "newest is kept");
  assert.ok(!ids(capped).includes("c1"), "oldest is dropped");
});

test("a short list is untouched", () => {
  assert.equal(C.capConversations(make(3)).length, 3);
});

test("A PINNED CONVERSATION SURVIVES THE CAP", () => {
  /* The regression this module exists for. c1 is the oldest of 25 — first
     against the wall under a blind slice(0, 20) — but it is pinned. */
  const list = C.togglePin(make(25), "c1");
  const capped = C.capConversations(list);
  assert.ok(ids(capped).includes("c1"), "pinned conversation was evicted");
  assert.equal(capped.length, C.MAX_CONVERSATIONS,
    "pinning must not inflate the list beyond the cap");
  assert.ok(!ids(capped).includes("c2"), "an unpinned one is dropped in its place");
});

test("several pinned conversations all survive", () => {
  let list = make(30);
  for (const id of ["c1", "c2", "c3"]) list = C.togglePin(list, id);
  const kept = ids(C.capConversations(list));
  for (const id of ["c1", "c2", "c3"]) assert.ok(kept.includes(id), `${id} evicted`);
  assert.equal(kept.length, C.MAX_CONVERSATIONS);
});

test("pinning more than the cap keeps every pin", () => {
  // Explicit intent beats a number nobody chose. The list simply runs long.
  let list = make(25);
  for (const c of list) list = C.togglePin(list, c.id);
  const capped = C.capConversations(list);
  assert.equal(capped.length, 25);
  assert.ok(capped.every((c) => c.pinned));
});

test("cap does not reorder what it keeps", () => {
  const capped = C.capConversations(C.togglePin(make(22), "c1"));
  const kept = ids(capped);
  assert.deepEqual(kept, [...kept].sort((a, b) => Number(b.slice(1)) - Number(a.slice(1))),
    "storage order must stay newest-first; ordering is a render concern");
});

/* ─────────────────────────────── pinning ───────────────────────────────── */

test("togglePin flips both ways and touches nothing else", () => {
  const list = make(2);
  const on = C.togglePin(list, "c1");
  assert.equal(on.find((c) => c.id === "c1").pinned, true);
  assert.equal(on.find((c) => c.id === "c2").pinned, undefined);
  const off = C.togglePin(on, "c1");
  assert.equal(off.find((c) => c.id === "c1").pinned, false);
});

test("records stored before pinning existed read as unpinned", () => {
  const legacy = [{ id: "old", title: "before pins", turns: [] }];
  assert.equal(C.isPinned(legacy[0]), false);
  assert.deepEqual(ids(C.sortConversations(legacy)), ["old"]);
});

test("toggling an unknown id changes nothing", () => {
  const list = make(3);
  assert.deepEqual(C.togglePin(list, "nope"), list);
});

/* ─────────────────────────────── deleting ──────────────────────────────── */

test("delete removes exactly one conversation", () => {
  const left = C.deleteConversation(make(3), "c2");
  assert.deepEqual(ids(left), ["c3", "c1"]);
});

test("delete of an unknown id is a no-op, and the source is not mutated", () => {
  const list = make(3);
  assert.deepEqual(ids(C.deleteConversation(list, "nope")), ["c3", "c2", "c1"]);
  assert.equal(list.length, 3);
});

test("a pinned conversation can still be deleted", () => {
  // Pin protects against automatic eviction, not against the user meaning it.
  const list = C.togglePin(make(2), "c1");
  assert.deepEqual(ids(C.deleteConversation(list, "c1")), ["c2"]);
});

/* ─────────────────────────────── renaming ──────────────────────────────── */

test("rename sets the title", () => {
  const list = C.renameConversation(make(2), "c1", "Northeast expansion");
  assert.equal(list.find((c) => c.id === "c1").title, "Northeast expansion");
  assert.equal(list.find((c) => c.id === "c2").title, "chat 2", "others untouched");
});

test("an empty or whitespace rename is a no-op, not an empty title", () => {
  for (const bad of ["", "   ", "\n\t", null, undefined]) {
    const list = C.renameConversation(make(1), "c1", bad);
    assert.equal(list[0].title, "chat 1", `"${String(bad)}" wiped the title`);
  }
});

test("titles are collapsed, trimmed and length-capped", () => {
  assert.equal(C.cleanTitle("  spaced   out  "), "spaced out");
  assert.equal(C.cleanTitle("line\nbreak"), "line break");
  assert.equal(C.cleanTitle("x".repeat(200)).length, C.MAX_TITLE);
});

test("rename survives a round trip through JSON", () => {
  // Conversations are persisted with JSON.stringify; a rename must not rely
  // on anything that does not survive that.
  const list = C.renameConversation(C.togglePin(make(2), "c2"), "c2", "Pinned & renamed");
  const back = JSON.parse(JSON.stringify(list));
  const c2 = back.find((c) => c.id === "c2");
  assert.equal(c2.title, "Pinned & renamed");
  assert.equal(c2.pinned, true);
  assert.deepEqual(ids(C.sortConversations(back)), ["c2", "c1"]);
});
