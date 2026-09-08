/* Markdown for the answer bubble.
   ─────────────────────────────────────────────────────────────────────────
   Small on purpose: no dependency, no innerHTML of anything unescaped, and
   only the subset an analyst answer actually contains.

   It lives in its own file because it grew a bug class that is invisible in
   the browser until someone reads an answer: the original renderer knew about
   `###` headings, `-` bullets and pipe tables, which is exactly what the
   deterministic templates emit. A language model writes different markdown --
   numbered lists, `##` headings, nested bullets, links -- and all of it came
   out as literal asterisks and pipes. Pulled out here, every case is a plain
   node test; see tests/test_markdown.mjs.

   app.js owns the DOM and calls in here for the HTML. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.Markdown = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;" };
  const escape = (s) => String(s == null ? "" : s).replace(/[&<>]/g, (c) => ESC[c]);

  /* Inline spans. Code is lifted out first so its contents are never treated
     as emphasis -- `**not bold**` inside backticks must stay literal. */
  function inline(t) {
    // Code spans are lifted out before anything else so their contents are
    // never treated as emphasis, and put back last. The placeholder uses a
    // control character: an earlier version wrapped the index in spaces, which
    // the restore step then matched against ordinary prose like "top 5".
    const code = [];
    const MARK = "\u0000";
    let s = t.replace(/`([^`]+)`/g, (_, c) => MARK + (code.push(c) - 1) + MARK);
    s = s
      .replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (_, label, href) =>
        /^(https?:|\/|#)/.test(href)
          ? `<a href="${href.replace(/"/g, "&quot;")}" target="_blank" ` +
            `rel="noopener noreferrer">${label}</a>`
          : label)
      .replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*\w])\*([^*\n]+)\*/g, "$1<em>$2</em>")
      .replace(/(^|\s)_([^_\n]+)_/g, "$1<em>$2</em>");
    return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${code[i]}</code>`);
  }

  function render(src) {
    const lines = escape(src).replace(/\r\n?/g, "\n").split("\n");
    const out = [];
    const lists = [];                 // open lists: {tag, indent}
    let inTable = false, inCode = false, code = [];

    const closeTable = () => {
      if (inTable) { out.push("</tbody></table></div>"); inTable = false; }
    };
    const closeLists = (toIndent) => {
      while (lists.length && lists[lists.length - 1].indent >= toIndent) {
        out.push(`</li></${lists.pop().tag}>`);
      }
    };
    const closeAll = () => closeLists(-1);

    for (const raw of lines) {
      const line = raw.replace(/\s+$/, "");

      if (/^\s*```/.test(line)) {
        if (inCode) { out.push(`<pre><code>${code.join("\n")}</code></pre>`); code = []; }
        else { closeAll(); closeTable(); }
        inCode = !inCode;
        continue;
      }
      if (inCode) { code.push(line); continue; }

      // Tables. A row is a line fenced by pipes; the |---|---| separator is
      // structural and never rendered.
      if (/^\s*\|.*\|\s*$/.test(line)) {
        closeAll();
        const body = line.trim().slice(1, -1);
        if (/^[\s\-:|]+$/.test(body)) continue;
        const cells = body.split("|").map((c) => inline(c.trim()));
        if (!inTable) {
          out.push('<div class="table-wrap"><table><thead><tr>' +
                   cells.map((c) => `<th>${c}</th>`).join("") + "</tr></thead><tbody>");
          inTable = true;
        } else {
          out.push("<tr>" + cells.map((c) => `<td>${c}</td>`).join("") + "</tr>");
        }
        continue;
      }
      closeTable();

      if (!line.trim()) { closeAll(); continue; }

      if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { closeAll(); out.push("<hr>"); continue; }

      const h = line.match(/^\s*(#{1,6})\s+(.*)$/);
      if (h) {
        closeAll();
        // An answer is not a page: it has a heading and a sub-heading, and
        // that is all. Mapping level-for-level put "##" at 15px and "###" at
        // 13px under 16px body text -- headings smaller than what they head.
        const level = h[1].length <= 2 ? 3 : 4;
        out.push(`<h${level}>${inline(h[2])}</h${level}>`);
        continue;
      }

      // The source is escaped before block parsing, so a blockquote marker
      // arrives as "&gt;" rather than ">".
      const quote = line.match(/^\s*(?:&gt;|>)\s?(.*)$/);
      if (quote) { closeAll(); out.push(`<blockquote>${inline(quote[1])}</blockquote>`); continue; }

      // Bullets and numbers, nested by indentation.
      const item = line.match(/^(\s*)([-*+]|\d{1,3}[.)])\s+(.*)$/);
      if (item) {
        const indent = item[1].replace(/\t/g, "    ").length;
        const tag = /\d/.test(item[2]) ? "ol" : "ul";
        while (lists.length && lists[lists.length - 1].indent > indent) {
          out.push(`</li></${lists.pop().tag}>`);
        }
        const top = lists[lists.length - 1];
        if (top && top.indent === indent) {
          if (top.tag === tag) out.push("</li><li>");
          else {
            out.push(`</li></${lists.pop().tag}>`);
            out.push(`<${tag}><li>`); lists.push({ tag, indent });
          }
        } else {
          out.push(`<${tag}><li>`); lists.push({ tag, indent });
        }
        out.push(inline(item[3]));
        continue;
      }

      // An indented line under a bullet continues that bullet.
      if (lists.length && /^\s{2,}\S/.test(line)) { out.push(" " + inline(line.trim())); continue; }

      closeAll();
      out.push(`<p>${inline(line.trim())}</p>`);
    }

    if (inCode) out.push(`<pre><code>${code.join("\n")}</code></pre>`);
    closeTable(); closeAll();
    return out.join("");
  }

  /* Speech, not screen. Text-to-speech reads "**" aloud, and a markdown table
     read row by row is unintelligible, so strip the syntax and drop tables
     rather than narrating their pipes. */
  function plain(src) {
    return String(src == null ? "" : src)
      .replace(/```[\s\S]*?```/g, " ")
      .replace(/^\s*\|.*\|\s*$/gm, " ")
      .replace(/^\s*[-*_]{3,}\s*$/gm, " ")
      .replace(/^\s*#{1,6}\s+/gm, "")
      .replace(/^\s*>\s?/gm, "")
      .replace(/^\s*([-*+]|\d{1,3}[.)])\s+/gm, "")
      .replace(/\[([^\]\n]+)\]\([^)]*\)/g, "$1")
      .replace(/\*\*\*|\*\*|\*|`|_/g, "")
      .replace(/\s*\n\s*/g, " ")
      .replace(/\s{2,}/g, " ")
      .trim();
  }

  return { render, plain, escape, inline };
}));
