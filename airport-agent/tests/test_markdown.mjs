/* Regression tests for the answer renderer.
   Run with:  node --test tests/test_markdown.mjs
   or via:    make test

   These exist because the bug they cover is invisible to every other kind of
   test and to the developer who wrote the templates: the original renderer
   handled exactly the markdown the deterministic templates emit -- bold,
   `-` bullets, `###` headings, pipe tables -- and nothing else. The moment a
   language model wrote the prose instead, its numbered lists, `##` headings,
   nested bullets and links came out as literal asterisks and hashes, and the
   voice transcript rendered no markdown at all.

   Pulled into web/markdown.js, every case is an assertion here. */

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const require = createRequire(import.meta.url);
const M = require("../web/markdown.js");

/* ───────────────────────── what the model writes ───────────────────────── */

test("numbered lists become an ordered list, not a paragraph of digits", () => {
  const html = M.render("1. **DFW** — Tier A\n2. **DEN** — Tier A");
  assert.match(html, /<ol>/);
  assert.equal((html.match(/<li>/g) || []).length, 2);
  assert.doesNotMatch(html, /<p>1\./);
});

test("bullets nested under a numbered item stay nested", () => {
  const html = M.render(
    "1. **DFW**\n   * saturation 0.974\n   * feasibility 0.90\n2. **DEN**");
  assert.match(html, /<ol><li>.*<ul><li>/s);
  assert.equal((html.match(/<ul>/g) || []).length, 1);
  assert.equal((html.match(/<\/ul>/g) || []).length, 1);
});

test("every heading level renders as a heading", () => {
  // Two levels only: a heading and a sub-heading. Deeper markdown collapses
  // rather than shrinking below the body text it introduces.
  for (const [src, tag] of [["# One", "h3"], ["## Two", "h3"],
                            ["### Three", "h4"], ["#### Four", "h4"]]) {
    assert.match(M.render(src), new RegExp(`<${tag}>`), src);
  }
  assert.doesNotMatch(M.render("## Two"), /#/);
});

test("links become anchors, and only safe schemes", () => {
  assert.match(M.render("See [the AC](https://faa.gov/ac)."),
               /<a href="https:\/\/faa\.gov\/ac"[^>]*>the AC<\/a>/);
  // javascript: is not a link; keep the words, drop the href
  const bad = M.render("[click](javascript:alert(1))");
  assert.doesNotMatch(bad, /<a /);
  assert.match(bad, /click/);
});

/* ──────────────────────────────── tables ───────────────────────────────── */

test("a pipe table becomes a table, and the separator row is not a row", () => {
  const html = M.render(
    "| Airport | Tier | Score |\n|---|---|---|\n| DFW | A | 75.6 |\n| DEN | A | 73.7 |");
  assert.match(html, /<table>/);
  assert.equal((html.match(/<th>/g) || []).length, 3);
  assert.equal((html.match(/<tr>/g) || []).length, 3);   // header + 2 body rows
  assert.doesNotMatch(html, /---/);
});

test("a table scrolls in its own container so the page never does", () => {
  const html = M.render("| a | b |\n|---|---|\n| 1 | 2 |");
  assert.match(html, /<div class="table-wrap">/);
});

test("bold survives inside a table cell", () => {
  assert.match(M.render("| x |\n|---|\n| **DFW** |"), /<td><strong>DFW<\/strong><\/td>/);
});

/* ───────────────────────────── inline spans ────────────────────────────── */

test("an ordinary number is never eaten by the code-span placeholder", () => {
  // The first placeholder wrapped its index in spaces, so restoring it
  // matched prose like "top 5" and replaced it with <code>undefined</code>.
  assert.equal(M.render("top 5 airports and 0 others"),
               "<p>top 5 airports and 0 others</p>");
});

test("markdown inside a code span stays literal", () => {
  assert.match(M.render("Use `**not bold**` here"), /<code>\*\*not bold\*\*<\/code>/);
});

test("html in the source is escaped, not executed", () => {
  const html = M.render("<img src=x onerror=alert(1)> and <b>hi</b>");
  assert.doesNotMatch(html, /<img/);
  assert.doesNotMatch(html, /<b>/);
  assert.match(html, /&lt;img/);
});

test("bold, italic and code all render", () => {
  const html = M.render("**b** and *i* and `c`");
  assert.match(html, /<strong>b<\/strong>/);
  assert.match(html, /<em>i<\/em>/);
  assert.match(html, /<code>c<\/code>/);
});

/* ─────────────────────────── blocks and safety ─────────────────────────── */

test("fenced code is preserved and never parsed as markdown", () => {
  const html = M.render("```\n| not | a | table |\n**not bold**\n```");
  assert.match(html, /<pre><code>/);
  assert.doesNotMatch(html, /<table>/);
  assert.doesNotMatch(html, /<strong>/);
});

test("rules and quotes render", () => {
  assert.match(M.render("---"), /<hr>/);
  assert.match(M.render("> a caveat"), /<blockquote>a caveat<\/blockquote>/);
});

test("every opened tag is closed", () => {
  const html = M.render(
    "## H\n\n1. one\n   - deep\n2. two\n\n| a |\n|---|\n| 1 |\n\ntail");
  for (const tag of ["ol", "ul", "li", "table", "tbody", "div"]) {
    const open = (html.match(new RegExp(`<${tag}[ >]`, "g")) || []).length;
    const close = (html.match(new RegExp(`</${tag}>`, "g")) || []).length;
    assert.equal(open, close, `${tag} left unbalanced in: ${html}`);
  }
});

test("empty and null input do not throw", () => {
  for (const v of ["", null, undefined]) assert.equal(typeof M.render(v), "string");
});

/* ────────────────────────────── for speech ─────────────────────────────── */

test("plain() strips the syntax text-to-speech would read aloud", () => {
  const said = M.plain("## Top 5\n\n1. **DFW** — Tier A\n2. **DEN**\n\nSee [the AC](https://faa.gov/ac).");
  assert.doesNotMatch(said, /[*#\[\]()]|https/);
  assert.match(said, /DFW/);
  assert.match(said, /the AC/);
});

test("plain() drops tables rather than narrating their pipes", () => {
  const said = M.plain("Here:\n\n| Airport | Score |\n|---|---|\n| DFW | 75.6 |\n\nThat's it.");
  assert.doesNotMatch(said, /\|/);
  assert.match(said, /Here:/);
  assert.match(said, /That's it\./);
});

/* ─────────────────────── the wiring, asserted at source ────────────────── */

test("the voice transcript renders markdown instead of escaping it raw", () => {
  const src = readFileSync(new URL("../web/app.js", import.meta.url), "utf8");
  const fn = src.slice(src.indexOf("function vmLine("));
  const body = fn.slice(0, fn.indexOf("\n}"));
  assert.match(body, /md\(text\)/,
               "vmLine must render the agent's markdown, not dump it as text");
});

test("app.js does not carry its own second markdown renderer", () => {
  const src = readFileSync(new URL("../web/app.js", import.meta.url), "utf8");
  assert.doesNotMatch(src, /function md\(src\)/,
                      "two renderers means one of them drifts");
});
