import type { ReactNode } from "react";

const LINK = /^https?:\/\//i;

function inline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\)|https?:\/\/[^\s)]+)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let index = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    const token = match[0];
    const key = `${keyPrefix}-${index++}`;
    if (token.startsWith("`")) {
      nodes.push(<code key={key}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("[")) {
      const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token);
      if (link && link[2] && LINK.test(link[2])) {
        nodes.push(
          <a key={key} href={link[2]} target="_blank" rel="noreferrer noopener">
            {link[1]}
          </a>,
        );
      } else {
        nodes.push(token);
      }
    } else if (LINK.test(token)) {
      nodes.push(
        <a key={key} href={token} target="_blank" rel="noreferrer noopener">
          {token}
        </a>,
      );
    }
    lastIndex = match.index + token.length;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

export function Markdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let buffer: string[] = [];
  let code: string[] | null = null;
  let list: { ordered: boolean; items: string[] } | null = null;

  const flushParagraph = () => {
    if (!buffer.length) return;
    const joined = buffer.join(" ");
    blocks.push(<p key={`p-${blocks.length}`}>{inline(joined, `p${blocks.length}`)}</p>);
    buffer = [];
  };

  const flushList = () => {
    if (!list) return;
    const Tag = list.ordered ? "ol" : "ul";
    blocks.push(
      <Tag key={`l-${blocks.length}`}>
        {list.items.map((item, position) => (
          <li key={position}>{inline(item, `li${blocks.length}-${position}`)}</li>
        ))}
      </Tag>,
    );
    list = null;
  };

  for (const line of lines) {
    if (line.trimStart().startsWith("```")) {
      if (code === null) {
        flushParagraph();
        flushList();
        code = [];
      } else {
        blocks.push(
          <pre key={`c-${blocks.length}`}>
            <code>{code.join("\n")}</code>
          </pre>,
        );
        code = null;
      }
      continue;
    }
    if (code !== null) {
      code.push(line);
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading && heading[1] && heading[2]) {
      flushParagraph();
      flushList();
      const level = Math.min(heading[1].length + 2, 6);
      const Tag = `h${level}` as "h3" | "h4" | "h5" | "h6";
      blocks.push(<Tag key={`h-${blocks.length}`}>{inline(heading[2], `h${blocks.length}`)}</Tag>);
      continue;
    }
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    const ordered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (bullet || ordered) {
      flushParagraph();
      const isOrdered = Boolean(ordered);
      if (!list || list.ordered !== isOrdered) {
        flushList();
        list = { ordered: isOrdered, items: [] };
      }
      const item = (bullet ?? ordered)?.[1];
      if (item) list.items.push(item);
      continue;
    }
    if (line.startsWith("> ")) {
      flushParagraph();
      flushList();
      blocks.push(
        <blockquote key={`q-${blocks.length}`}>{inline(line.slice(2), `q${blocks.length}`)}</blockquote>,
      );
      continue;
    }
    buffer.push(line.trim());
  }

  if (code !== null) {
    blocks.push(
      <pre key={`c-${blocks.length}`}>
        <code>{code.join("\n")}</code>
      </pre>,
    );
  }
  flushParagraph();
  flushList();

  return <div className="markdown">{blocks}</div>;
}
