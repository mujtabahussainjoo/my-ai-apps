/**
 * Syllabus parsing and topic weightage.
 *
 * The `topics.weightage` column is an INT, but real exam blueprints publish
 * decimals ("Applications and Integration 33.1%"). Those cannot be stored
 * verbatim, and independently rounding 25 skills loses or invents points — the
 * total then drifts away from 100 and the exam page nags forever. So weights
 * are normalised with the largest-remainder method: floor everything, then hand
 * the leftover points to the rows with the biggest fractional part. The result
 * always sums to exactly 100 while staying as close as integers allow to the
 * published proportions.
 *
 * Only leaves carry weight. A parent domain like "Applications and Integration"
 * is a container whose value is the sum of its skills, so counting both is what
 * used to make a correct plan read 106%.
 */

export type SyllabusNode = {
  name: string;
  weight: number;
  note?: string | null;
  children?: SyllabusNode[];
};

export type SyllabusPreset = {
  id: string;
  label: string;
  /** Shown as the provenance line under the preset name. */
  source: string;
  description: string;
  nodes: SyllabusNode[];
};

/** Deepest rows of the tree — the ones that actually hold weight. */
export function leafNodes(nodes: SyllabusNode[]): SyllabusNode[] {
  const out: SyllabusNode[] = [];
  const walk = (list: SyllabusNode[]) => {
    for (const n of list) {
      if (n.children?.length) walk(n.children);
      else out.push(n);
    }
  };
  walk(nodes);
  return out;
}

/** Total weightage across the leaves. This is the number that must reach 100. */
export function sumLeafWeight(nodes: SyllabusNode[]): number {
  return leafNodes(nodes).reduce((s, n) => s + Math.max(0, n.weight), 0);
}

/**
 * Rescales every leaf so the total is exactly 100, then recomputes each parent's
 * weight as the sum of its children. Safe to run repeatedly — normalising an
 * already-normalised plan is a no-op.
 */
export function normalizeWeights(nodes: SyllabusNode[]): SyllabusNode[] {
  const leaves = leafNodes(nodes);
  if (leaves.length === 0) return [];

  const positive = leaves.map((n) => Math.max(0, n.weight));
  const total = positive.reduce((s, w) => s + w, 0);

  if (total <= 0) {
    // Nothing was weighted out — spread evenly rather than leaving it at 0%.
    const base = Math.floor(100 / leaves.length);
    const remainder = 100 - base * leaves.length;
    leaves.forEach((n, i) => {
      n.weight = base + (i < remainder ? 1 : 0);
    });
  } else {
    const exact = positive.map((w) => (w * 100) / total);
    const assigned = exact.map((v) => Math.floor(v));
    let used = assigned.reduce((s, v) => s + v, 0);

    const byFraction = exact
      .map((v, i) => ({ i, fraction: v - Math.floor(v) }))
      .sort((a, b) => b.fraction - a.fraction || a.i - b.i);

    for (let k = 0; used < 100 && byFraction.length > 0; k++) {
      assigned[byFraction[k % byFraction.length].i] += 1;
      used += 1;
    }
    leaves.forEach((n, i) => {
      n.weight = assigned[i];
    });
  }

  return withParentTotals(nodes);
}

/** Rewrites parent weights to match their children, depth first. */
function withParentTotals(nodes: SyllabusNode[]): SyllabusNode[] {
  return nodes.map((n) => {
    if (!n.children?.length) return { ...n, children: undefined };
    const children = withParentTotals(n.children);
    return {
      ...n,
      children,
      weight: children.reduce((s, c) => s + c.weight, 0),
    };
  });
}

/** Depth-first walk used by the preview list and the writer. */
export function flattenSyllabus(
  nodes: SyllabusNode[],
  depth = 0
): { node: SyllabusNode; depth: number }[] {
  const out: { node: SyllabusNode; depth: number }[] = [];
  for (const n of nodes) {
    out.push({ node: n, depth });
    if (n.children?.length) out.push(...flattenSyllabus(n.children, depth + 1));
  }
  return out;
}

/**
 * Reads the shape Anthropic's exam guides use — "Detailed objectives by domain":
 *
 *   Domain 1: Agents and Workflows (14.7%)
 *   Agent Architecture (4.5%)
 *   <a paragraph describing the skill>
 *   Agent Construction with Claude (5.3%)
 *
 * Tried before the generic outline parser because it is far more specific, and
 * because it keeps the skill names off the surrounding prose. Only the names
 * and weights are kept; the descriptive paragraphs are skipped.
 *
 * Validity is checked against the document itself: each domain's skills have to
 * add up to roughly the domain's own stated weight. That is a strong enough
 * signal that a prose document cannot accidentally satisfy it, so this returns
 * null for anything that is not genuinely a weighted blueprint.
 */
export function parseWeightedBlueprint(text: string): SyllabusNode[] | null {
  const roots: SyllabusNode[] = [];
  let current: SyllabusNode | null = null;

  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.replace(/\s+/g, " ").trim();
    if (!line) continue;

    const domain = line.match(/^Domain\s+\d+\s*[:.\-–—]\s*(.{3,70}?)\s*[\(—–\-:]\s*(\d{1,3}(?:\.\d+)?)\s*%/i);
    if (domain) {
      current = { name: domain[1].trim(), weight: Number(domain[2]), children: [] };
      roots.push(current);
      continue;
    }

    // Only a line inside a known domain can be a skill.
    if (!current) continue;

    const skill = line.match(/^(.{3,70}?)\s*[\(—–\-:]\s*(\d{1,3}(?:\.\d+)?)\s*%\s*\)?$/);
    if (!skill) continue;

    const name = skill[1].trim();
    // A wrapped sentence ending in a number is prose, not a heading.
    if (/[.;,]$/.test(name)) continue;
    if (/\b(?:the|and|or|to|of|for|with|that|this|from|are|is|as|in|on|a|an)$/i.test(name)) continue;

    current.children!.push({ name, weight: Number(skill[2]) });
  }

  if (roots.length < 2) return null;
  if (roots.some((r) => !r.children?.length)) return null;

  // The document's own arithmetic has to agree with itself.
  for (const r of roots) {
    const sum = r.children!.reduce((s, c) => s + c.weight, 0);
    if (Math.abs(sum - r.weight) > Math.max(1.5, r.weight * 0.12)) return null;
  }

  return roots;
}

/**
 * Reads a syllabus that is already written as an outline with percentages, e.g.
 *
 *   Domain 2: Applications and Integration — 33.1%
 *     Claude Application Design (8.6%)
 *     Software Engineering Foundations — 7.4%
 *
 * A bulleted or numbered list with no percentages also parses; those rows come
 * back with weight 0 and are proportionalised later. Returns null when fewer
 * than two rows were recognised, which is the signal to fall back to the model.
 */
export function parseSyllabusOutline(text: string): SyllabusNode[] | null {
  const roots: SyllabusNode[] = [];
  /** One entry per indent level seen, holding that level's most recent row. */
  const stack: { indent: number; node: SyllabusNode; siblings: SyllabusNode[] }[] = [];

  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.replace(/\s+$/, "");
    if (!line.trim()) continue;

    const percent = matchTrailingPercent(line);
    const stripped = line.replace(percent.match, "").trim();
    const cleaned = cleanHeading(stripped);
    if (!cleaned) continue;

    const indent = countIndent(line);
    while (stack.length > 0 && stack[stack.length - 1].indent >= indent) stack.pop();

    const node: SyllabusNode = {
      name: cleaned.name,
      weight: percent.value,
      note: cleaned.note || null,
    };

    const parent = stack[stack.length - 1];
    if (parent) parent.node.children = [...(parent.node.children ?? []), node];
    else roots.push(node);

    stack.push({ indent, node, siblings: parent ? parent.node.children! : roots });
  }

  const found = flattenSyllabus(roots);
  if (found.length < 2) return null;

  // Without any percentages the outline is a heading list, not a weightage —
  // let the model read it instead of guessing an even split from titles alone.
  const weighted = found.filter((f) => f.node.weight > 0).length;
  if (weighted === 0) return null;

  if (!looksLikeSyllabus(found.map((f) => f.node))) return null;

  return roots;
}

/** No real exam has more weighted topics than this. */
const MAX_PLAUSIBLE_TOPICS = 80;

/**
 * Guards against reading a whole document as if every line were a topic.
 *
 * A vendor exam guide is mostly prose — wrapped sentences, proctoring rules,
 * page footers. Without this check the outline parser happily returns one 0%
 * "topic" per line (388 of them for the CCDV-F guide), and because a total is
 * produced the importer would save that as a real syllabus instead of falling
 * back to the model. Returns false for anything that does not look like a
 * heading list, so the caller returns null and takes the AI path.
 */
function looksLikeSyllabus(nodes: SyllabusNode[]): boolean {
  if (nodes.length > MAX_PLAUSIBLE_TOPICS) return false;

  // Headings are short. Wrapped prose sentences are not.
  const long = nodes.filter((n) => n.name.length > 90).length;
  if (long > nodes.length * 0.2) return false;

  // A syllabus is mostly headings; prose documents average well below this.
  const avg = nodes.reduce((s, n) => s + n.name.length, 0) / nodes.length;
  if (avg > 70) return false;

  // Page furniture ("-- 12 of 14 --") is a reliable tell for raw PDF text.
  const furniture = nodes.filter((n) => /^--\s*\d+\s+of\s+\d+\s*--$/.test(n.name)).length;
  if (furniture > 0) return false;

  return true;
}

function matchTrailingPercent(line: string): { match: string; value: number } {
  const re = /[—–\-:(\[]?\s*(\d{1,3}(?:\.\d+)?)\s*%[^%]*$/;
  const m = line.match(re);
  if (!m) return { match: "", value: 0 };
  const value = Math.min(100, Math.max(0, Number(m[1])));
  return { match: m[0], value: Number.isFinite(value) ? value : 0 };
}

/** "3. Claude Code Operation (3.1%)" -> "Claude Code Operation" */
function cleanHeading(raw: string): { name: string; note: string } {
  let s = raw
    .replace(/^\s*#{1,6}\s*/, "")
    .replace(/^\s*[-*+]\s+/, "")
    .replace(/^\s*\d+[).]\s*/, "")
    // Alphabetic and roman sub-markers ("a. Architecture", "iv. Testing").
    // Lowercase only, and only with whitespace after the dot, so an initial
    // like "A. Reyes" or a name like "e.g." is left alone.
    .replace(/^\s*[a-z]{1,4}[.)]\s+(?=\S)/, "")
    .replace(/^\s*(domain|section|module|topic|unit|part)\s*\d*\s*[:.\-–—]\s*/i, "")
    .replace(/\s*[:(\[]\s*$/, "")
    .replace(/\s+/g, " ")
    .trim();
  if (!s) return { name: "", note: "" };

  // A trailing parenthetical that is not a weight is kept as the note.
  let note = "";
  const noteMatch = s.match(/^(.*?)\s*[(\[]([^)\]]{3,120})[)\]]\s*$/);
  if (noteMatch && !/\d\s*%/.test(noteMatch[2])) {
    s = noteMatch[1].trim();
    note = noteMatch[2].trim();
  }
  return { name: s.slice(0, 160), note };
}

function countIndent(line: string): number {
  const m = line.match(/^[\s]*/)?.[0] ?? "";
  const tabs = (m.match(/\t/g) ?? []).length * 4;
  const spaces = m.replace(/\t/g, "").length;

  // Markdown carries its nesting in the marker, not in leading whitespace: a
  // bullet under "# Agents" is indented 0 and would otherwise become a sibling.
  // Bullets count one level deeper than bare text, and a deeper heading counts
  // shallower, so the marker order alone reproduces the document's hierarchy.
  const bullet = /^\s*[-*+]\s+/.test(line) ? 4 : 0;
  const heading = line.match(/^\s*(#{1,6})\s/);
  const headingDepth = heading ? (7 - heading[1].length) * -4 : 0;

  return tabs + spaces + bullet + headingDepth;
}

// ------------------------------------------------------------------ presets

/**
 * Anthropic's published blueprint for Claude Certified Developer – Foundations
 * (CCDV-F), Exam Guide v1.0. The guide gives a weight to every one of the 25
 * skills as well as to the 8 domains, so topics can be seeded at the skill
 * level and the domain totals fall out of the sum. Domains and skills together
 * come to exactly 100.0%.
 */
const CCDV_F_BLUEPRINT: SyllabusNode[] = [
  {
    name: "Applications and Integration",
    weight: 33.1,
    children: [
      { name: "Claude Application Design", weight: 8.6 },
      { name: "Software Engineering Foundations", weight: 7.4 },
      { name: "Claude API Mechanics", weight: 6.8 },
      { name: "Configuration Management", weight: 4.1 },
      { name: "Understanding Requirements", weight: 3.4 },
      { name: "Systems Life Cycle", weight: 2.8 },
    ],
  },
  {
    name: "Model Selection and Optimization",
    weight: 16.8,
    children: [
      { name: "Technical Fundamentals", weight: 6.1 },
      { name: "LLM Fundamentals", weight: 5.2 },
      { name: "Cost and Token Management", weight: 2.8 },
      { name: "Model Selection and Tradeoffs", weight: 2.7 },
    ],
  },
  {
    name: "Agents and Workflows",
    weight: 14.7,
    children: [
      { name: "Agent Construction with Claude", weight: 5.3 },
      { name: "Agent Patterns and Frameworks", weight: 4.9 },
      { name: "Agent Architecture", weight: 4.5 },
    ],
  },
  {
    name: "Prompt and Context Engineering",
    weight: 11.0,
    children: [
      { name: "Prompt Engineering", weight: 4.6 },
      { name: "Context Engineering", weight: 3.8 },
      { name: "Output Handling", weight: 2.6 },
    ],
  },
  {
    name: "Tools and MCPs",
    weight: 10.6,
    children: [
      { name: "Tool Implementation", weight: 4.4 },
      { name: "Agentic Customization", weight: 4.1 },
      { name: "MCP Server Development", weight: 2.1 },
    ],
  },
  {
    name: "Security and Safety",
    weight: 8.1,
    children: [
      { name: "AI Application Security", weight: 3.2 },
      { name: "Guardrails and Safe Deployment", weight: 2.3 },
      { name: "Identity, Secrets, and Key Management", weight: 1.6 },
      { name: "Claude Hooks", weight: 1.0 },
    ],
  },
  {
    name: "Claude Code",
    weight: 3.1,
    children: [{ name: "Claude Code Operation", weight: 3.1 }],
  },
  {
    name: "Eval, Testing, and Debugging",
    weight: 2.6,
    children: [{ name: "Debugging and Error Handling", weight: 2.6 }],
  },
];

export const SYLLABUS_PRESETS: SyllabusPreset[] = [
  {
    id: "ccdv-foundations",
    label: "Claude Certified Developer – Foundations (CCDV-F)",
    source: "Anthropic Exam Guide v1.0 · 8 domains, 25 weighted skills",
    description:
      "The full official blueprint. Applications and Integration alone is a third of the paper, while Claude Code and Eval together are under 6%.",
    nodes: CCDV_F_BLUEPRINT,
  },
];

/** Titles that are almost certainly preparing for CCDV-F, so the preset leads. */
export function suggestedPresetFor(title: string): SyllabusPreset | null {
  const t = title.toLowerCase();
  const wantsCcdv =
    t.includes("ccdv") ||
    t.includes("ccdf") ||
    t.includes("claude certified developer") ||
    (t.includes("claude") && (t.includes("foundation") || t.includes("developer")));
  return wantsCcdv ? (SYLLABUS_PRESETS[0] ?? null) : null;
}

export function getPreset(id: string): SyllabusPreset | null {
  return SYLLABUS_PRESETS.find((p) => p.id === id) ?? null;
}

/** Deep copy so a preview can be edited without touching the preset constant. */
export function cloneNodes(nodes: SyllabusNode[]): SyllabusNode[] {
  return nodes.map((n) => ({
    ...n,
    children: n.children?.length ? cloneNodes(n.children) : undefined,
  }));
}

// ------------------------------------------------------- existing DB topics

/** Minimal shape of a topic row that the weight maths needs. */
export type WeightedTopic = { id: string; name: string; weightage: number; parentId?: string | null };

/** The ids of every topic that has no children, i.e. the ones that hold weight. */
export function leafTopicIds(topics: WeightedTopic[]): Set<string> {
  const parents = new Set(topics.map((t) => t.parentId).filter((p): p is string => !!p));
  return new Set(topics.filter((t) => !parents.has(t.id)).map((t) => t.id));
}

/**
 * Total weightage that counts towards the exam. Parents are containers, so they
 * are excluded; a plan that is entirely flat (no subtopics) is unaffected.
 */
export function totalAssignedWeight(topics: WeightedTopic[]): number {
  const leaves = leafTopicIds(topics);
  return topics.reduce((s, t) => (leaves.has(t.id) ? s + t.weightage : s), 0);
}

/** True when the weights are close enough to 100 that nagging the user is noise. */
export function weightsAreBalanced(topics: WeightedTopic[]): boolean {
  return Math.abs(totalAssignedWeight(topics) - 100) <= 1;
}

/**
 * Splits `total` slots across `weights`, summing to exactly `total`.
 *
 * Plain `Math.round` per row loses slots: 20 questions across six domains rounds
 * 14.7% to 3 and can finish at 19, and across twenty-five small skills every row
 * rounds to 0 so the whole paper gets filled by an unweighted fallback. Flooring
 * first and handing the remainder to the largest fractional parts always spends
 * the full budget.
 */
export function allocateByWeight(weights: number[], total: number): number[] {
  const slots = Math.max(0, Math.round(total));
  if (weights.length === 0 || slots === 0) return weights.map(() => 0);

  const positive = weights.map((w) => (Number.isFinite(w) ? Math.max(0, w) : 0));
  const sum = positive.reduce((s, w) => s + w, 0);
  if (sum <= 0) return positive.map(() => 0);

  const exact = positive.map((w) => (w * slots) / sum);
  const out = exact.map((v) => Math.floor(v));
  let used = out.reduce((s, v) => s + v, 0);

  const byFraction = exact
    .map((v, i) => ({ i, fraction: v - Math.floor(v) }))
    .sort((a, b) => b.fraction - a.fraction || a.i - b.i);

  for (let k = 0; used < slots && byFraction.length > 0; k++) {
    out[byFraction[k % byFraction.length].i] += 1;
    used += 1;
  }
  return out;
}
