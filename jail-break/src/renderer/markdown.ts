/**
 * Tiny, dependency-free Markdown renderer for assistant replies.
 *
 * Loaded as a classic script BEFORE renderer.js (see index.html), so it runs
 * without a bundler. Everything is escaped first — no raw HTML from the model
 * ever reaches the DOM.
 *
 * Supported: headings, bold/italic, inline code, fenced code blocks,
 * bulleted + numbered lists, tables, blockquotes, rules, safe links.
 */
interface Window {
  renderMarkdown?: (text: string) => string;
  escapeHtmlText?: (text: string) => string;
}

(function (): void {
  "use strict";

  const NO_HTML: Record<string, string> = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  };

  function escapeHtml(value: unknown): string {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch: string) => NO_HTML[ch]);
  }

  function safeUrl(url: string): string | null {
    return /^https?:\/\//i.test(url) ? url : null;
  }

  function inline(text: string): string {
    const slots: string[] = [];

    // Inline code first so its contents are not formatted further.
    let out = text.replace(/`([^`]+)`/g, (_m: string, code: string) => {
      slots.push('<code class="inline-code">' + code + "</code>");
      return "\u0001" + (slots.length - 1) + "\u0001";
    });

    // [label](https://url)
    out = out.replace(
      /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      (_m: string, label: string, url: string) => {
        const safe = safeUrl(url.replace(/&amp;/g, "&"));
        if (!safe) return label;
        return (
          '<a href="' +
          escapeHtml(safe) +
          '" target="_blank" rel="noreferrer noopener">' +
          label +
          "</a>"
        );
      }
    );

    // Bare URLs.
    out = out.replace(
      /(^|[\s(])(https?:\/\/[^\s<)]+)/g,
      (_m: string, lead: string, url: string) => {
        const safe = safeUrl(url.replace(/&amp;/g, "&"));
        if (!safe) return lead + url;
        return (
          lead +
          '<a href="' +
          escapeHtml(safe) +
          '" target="_blank" rel="noreferrer noopener">' +
          url +
          "</a>"
        );
      }
    );

    out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/(^|[\s(])\*([^*\n]+)\*(?=$|[\s.,;:!?)])/g, "$1<em>$2</em>");
    out = out.replace(/~~([^~]+)~~/g, "<del>$1</del>");

    return out.replace(/\u0001(\d+)\u0001/g, (_m: string, i: string) => slots[Number(i)] || "");
  }

  function codeBlockHtml(lang: string, code: string, index: number): string {
    const label = lang || "text";
    return (
      '<div class="code-block" data-code-index="' +
      index +
      '"><div class="code-head"><span class="code-lang">' +
      escapeHtml(label) +
      '</span><button type="button" class="code-copy" title="Copy code">Copy</button></div>' +
      '<pre><code class="language-' +
      escapeHtml(label) +
      '">' +
      code +
      "</code></pre></div>"
    );
  }

  function splitRow(line: string): string[] {
    const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
    return trimmed.split("|").map((cell: string) => cell.trim());
  }

  function isTableSeparator(line: string): boolean {
    return /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/.test(line);
  }

  function renderMarkdown(source: unknown): string {
    const blocks: Array<{ lang: string; code: string }> = [];

    // Pull fenced code out first: its contents must never be re-formatted.
    const withoutCode = String(source == null ? "" : source).replace(
      /```([A-Za-z0-9_+#.-]*)[ \t]*\r?\n([\s\S]*?)```/g,
      (_m: string, lang: string, code: string) => {
        blocks.push({ lang: String(lang || "").toLowerCase(), code: escapeHtml(code.replace(/\s+$/, "")) });
        return "\u0002CODE" + (blocks.length - 1) + "\u0002";
      }
    );

    const lines = escapeHtml(withoutCode).replace(/\r\n/g, "\n").split("\n");
    const html: string[] = [];
    let para: string[] = [];
    let list: { type: "ul" | "ol"; items: string[] } | null = null;
    let table: string[][] | null = null;
    let quote: string[] = [];

    function flushPara(): void {
      if (para.length) {
        html.push("<p>" + inline(para.join(" ")) + "</p>");
        para = [];
      }
    }
    function flushList(): void {
      if (list) {
        html.push(
          "<" +
            list.type +
            ">" +
            list.items.map((item: string) => "<li>" + inline(item) + "</li>").join("") +
            "</" +
            list.type +
            ">"
        );
        list = null;
      }
    }
    function flushTable(): void {
      if (!table || !table.length) {
        table = null;
        return;
      }
      const head = table[0];
      const body = table.slice(1);
      html.push(
        '<div class="table-wrap"><table><thead><tr>' +
          head.map((cell: string) => "<th>" + inline(cell) + "</th>").join("") +
          "</tr></thead><tbody>" +
          body
            .map(
              (row: string[]) =>
                "<tr>" +
                head
                  .map((_c: string, i: number) => "<td>" + inline(row[i] || "") + "</td>")
                  .join("") +
                "</tr>"
            )
            .join("") +
          "</tbody></table></div>"
      );
      table = null;
    }
    function flushQuote(): void {
      if (quote.length) {
        html.push("<blockquote>" + inline(quote.join(" ")) + "</blockquote>");
        quote = [];
      }
    }
    function flushAll(): void {
      flushPara();
      flushList();
      flushTable();
      flushQuote();
    }

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const trimmed = line.trim();

      const codeMatch = trimmed.match(/^\u0002CODE(\d+)\u0002$/);
      if (codeMatch) {
        flushAll();
        const block = blocks[Number(codeMatch[1])];
        html.push(codeBlockHtml(block.lang, block.code, Number(codeMatch[1])));
        continue;
      }

      if (!trimmed) {
        flushAll();
        continue;
      }

      // Table: header row followed by a separator row.
      if (trimmed.indexOf("|") !== -1 && isTableSeparator(lines[i + 1] || "")) {
        flushAll();
        const rows: string[][] = [splitRow(trimmed)];
        i += 1;
        while (i + 1 < lines.length && /\|/.test(lines[i + 1]) && lines[i + 1].trim()) {
          i += 1;
          rows.push(splitRow(lines[i]));
        }
        table = rows;
        flushTable();
        continue;
      }

      const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        flushAll();
        const level = Math.min(heading[1].length + 2, 6); // ## -> h4 inside a bubble
        html.push("<h" + level + ">" + inline(heading[2]) + "</h" + level + ">");
        continue;
      }

      if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
        flushAll();
        html.push("<hr />");
        continue;
      }

      const quoteMatch = trimmed.match(/^&gt;\s?(.*)$/);
      if (quoteMatch) {
        flushPara();
        flushList();
        flushTable();
        quote.push(quoteMatch[1]);
        continue;
      }

      const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
      if (bullet) {
        flushPara();
        flushTable();
        flushQuote();
        if (!list || list.type !== "ul") {
          flushList();
          list = { type: "ul", items: [] };
        }
        list.items.push(bullet[1]);
        continue;
      }

      const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
      if (numbered) {
        flushPara();
        flushTable();
        flushQuote();
        if (!list || list.type !== "ol") {
          flushList();
          list = { type: "ol", items: [] };
        }
        list.items.push(numbered[1]);
        continue;
      }

      if (list) {
        if (/^\s{2,}\S/.test(line)) {
          // Continuation line of the previous bullet.
          list.items[list.items.length - 1] += " " + trimmed;
          continue;
        }
        flushList();
      }

      para.push(trimmed);
    }

    flushAll();
    return html.join("");
  }

  window.renderMarkdown = renderMarkdown;
  window.escapeHtmlText = escapeHtml;
})();
