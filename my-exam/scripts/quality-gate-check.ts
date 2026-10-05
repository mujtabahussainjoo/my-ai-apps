import "dotenv/config";
import { hasDanglingVisualReference, isNearDuplicate, validateGeneratedRow } from "../src/lib/generate";
import { matchTopic, rankTopics } from "../src/lib/topic-match";
import { cosine, findSemanticDuplicates } from "../src/lib/dedupe-semantic";
import { classifyUpload, titleFromPath } from "../src/lib/material-path";
import { parseJson } from "../src/lib/ai";
import {
  normalizeWeights,
  parseSyllabusOutline,
  parseWeightedBlueprint,
  sumLeafWeight,
} from "../src/lib/syllabus";

let failures = 0;
const ok = (label: string, cond: boolean) => {
  if (!cond) failures++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${label}`);
};

const goodMcq = (over: Record<string, unknown> = {}) => ({
  topicId: null,
  prompt: "Which HTTP verb is idempotent?",
  type: "mcq",
  choices: [
    { text: "POST", correct: false },
    { text: "GET", correct: true },
    { text: "PATCH", correct: false },
    { text: "PUT", correct: false },
  ],
  answer: "GET",
  explanation: "GET is safe and idempotent.",
  category: null,
  ...over,
});

console.log("--- the real question from your bank (must be REJECTED)");
const real = goodMcq({ prompt: "What is the main purpose of the diagram?", explanation: "" });
ok("rejects dangling 'the diagram'", !validateGeneratedRow(real, "mcq").ok);
ok("rejects empty explanation", !validateGeneratedRow(real, "mcq").ok);

// 4-5 option rule, enforced app-wide.
const withOptions = (n: number, correctAt = 0) =>
  goodMcq({
    choices: Array.from({ length: n }, (_, i) => ({
      text: `Option ${String.fromCharCode(65 + i)}`,
      correct: i === correctAt,
    })),
  });

// ---------------------------------------------------------------- JSON repair
// These are the exact shapes a small local model emits in practice.
const parse = (raw: string) => {
  try {
    return { ok: true as const, value: parseJson<Record<string, unknown>>(raw) };
  } catch (e) {
    return { ok: false as const, message: (e as Error).message };
  }
};

ok("parses clean JSON", parse('{"a":1}').ok);
ok("strips code fences", parse('```json\n{"a":1}\n```').ok);
ok("ignores prose around JSON", parse('Here you go:\n{"a":1}\nHope that helps!').ok);
ok("fixes trailing commas", parse('{"a":[1,2,],}').ok);
ok("fixes smart quotes", parse('{“a”:“b”}').ok);
ok("fixes bare undefined", parse('{"a":undefined,"b":2}').ok);
ok(
  "fixes unescaped newlines inside strings",
  parse('{"question":"line one\nline two"}').ok
);
ok(
  "closes output truncated mid-object",
  parse('{"questions":[{"question":"What is 2+2?","options":["3","4"]').ok
);
const salvaged = parse(
  'garbage {not json} {"question":"Q1","options":["a","b"]} {"question":"Q2","options":["c","d"]} trailing'
);
ok("recovers from junk between objects", salvaged.ok);
const junk = parse("this is not json at all");
ok(
  "error message names the failure and shows a snippet",
  !junk.ok && /invalid JSON/.test(junk.ok ? "" : junk.message)
);

// Near-duplicate detection: a weak model rephrases one question many ways.
// Threshold 0.70 was chosen from the real bank: true rephrasings score
// 0.71-1.00, while genuinely different questions that share wording score 0.67.
ok(
  "flags rephrased duplicates",
  isNearDuplicate(
    "What is the basic unit of processing in LLMs like Claude?",
    "What is the basic unit that LLMs like Claude work with?"
  )
);
ok(
  "flags word-order variants",
  isNearDuplicate("What is the context window in Claude?", "In Claude, what is the context window?")
);
ok(
  "allows genuinely different questions",
  !isNearDuplicate("What is the context window?", "How does sampling affect determinism?")
);
ok(
  "does not flag same-shaped but different questions",
  !isNearDuplicate(
    "What is the main purpose of the prompt in building a support-reply helper?",
    "What is the main purpose of the API pattern in building a support-reply helper?"
  )
);

// The original bug: the model omits correctIndex, every option ends up
// correct:false, and the question is saved ungradable (always scored 0).
const opt = (text: string, correct = false) => ({ text, correct });
ok(
  "rejects an option set with no correct option",
  !validateGeneratedRow(goodMcq({ choices: [opt("a"), opt("b"), opt("c"), opt("d")] }), "mcq").ok
);
ok(
  "rejects an option set with two correct options",
  !validateGeneratedRow(
    goodMcq({ choices: [opt("a", true), opt("b", true), opt("c"), opt("d")] }),
    "mcq"
  ).ok
);

// Topic filing: questions used to save with no topic at all.
const outline = [
  { id: "p-llm", name: "How LLMs Behave", parentId: null, parentName: null },
  { id: "s-token", name: "Tokens: the basic unit", parentId: "p-llm", parentName: "How LLMs Behave" },
  { id: "s-ctx", name: "Context window: a fixed token budget", parentId: "p-llm", parentName: "How LLMs Behave" },
  { id: "s-sample", name: "Sampling: why answers can differ", parentId: "p-llm", parentName: "How LLMs Behave" },
  { id: "s-nondet", name: "Non-determinism: what it means for tests", parentId: "p-llm", parentName: "How LLMs Behave" },
];
ok("files a token question under Tokens", matchTopic("What is the basic unit that Claude sees in text?", outline) === "s-token");
ok("files a context question under the context window", matchTopic("What is the context window?", outline) === "s-ctx");
ok("files a sampling question under Sampling", matchTopic("Why can two identical requests return different answers - sampling?", outline) === "s-sample");
ok(
  "does not file an unrelated question under a confident subtopic",
  matchTopic("How should you store the Anthropic API key?", outline) === null
);
ok(
  "prefers a subtopic over the exam-level topic",
  rankTopics("What is the context window?", outline, { limit: 2 })[0].name.startsWith("Context window")
);

// Semantic dedupe. The candidate block and the existing block sit in one vector
// array; reading the existing block at the wrong offset silently compared
// unrelated questions, so this is pinned down.
const near = [1, 0.99, 0.98];
const far = [0, 1, 0];
// Folder uploads: titles must reflect the folder a file came from, otherwise
// two chapters' "intro.pdf" collapse into one indistinguishable material.
ok("title matches the uploaded path pattern", titleFromPath("2. Anthropic/1. Module/MSO Foundations/1. Orientation.md") === "2. Anthropic/1. Module/MSO Foundations/1. Orientation");
ok("title uses real slashes, not spaced ones", !titleFromPath("A/B/c.md").includes(" / "));
ok("title leaves dashes and underscores alone", titleFromPath("Course/Week_01/intro-slides.md") === "Course/Week_01/intro-slides");
ok("title is the source path minus the extension", (() => { const p = "2. Anthropic/5. Module/Accelerators/9. Key takeaways.md"; return titleFromPath(p) === p.replace(/\.md$/, ""); })());
ok("title distinguishes same-named lessons in different modules", titleFromPath("2. Anthropic/1. Module/MSO Foundations/1. Orientation.md") !== titleFromPath("2. Anthropic/2. Module/Production-Grade/1 . Orientation.md"));
ok("title handles a single file", titleFromPath("notes.md") === "notes");
ok("title drops the extension only", titleFromPath("archive.tar.gz") === "archive.tar");
ok("title falls back when empty", titleFromPath("") === "Untitled");
ok("title normalises stray slashes", titleFromPath("/2. Anthropic//1. Module//basics.pdf/") === "2. Anthropic/1. Module/basics");
ok("title keeps a deep nested path", titleFromPath("A/B/C/D/e.md") === "A/B/C/D/e");

ok("accepts a normal pdf", classifyUpload("Course/basics.pdf").ok);
ok("accepts markdown in a folder", classifyUpload("Course/Week 1/notes.md").ok);
ok("skips macOS metadata", !classifyUpload("Course/.DS_Store").ok);
ok("skips hidden files", !classifyUpload(".env").ok);
ok("skips lockfiles", !classifyUpload("node_modules/pkg/package.json").ok);
ok("skips build output", !classifyUpload("dist/bundle.js").ok);
ok("skips unsupported extensions", !classifyUpload("Course/diagram.png").ok);
ok("skips files with no extension", !classifyUpload("Course/README").ok);
ok("skips files with no name", !classifyUpload("Course/").ok);

ok("cosine of identical vectors is 1", Math.abs(cosine(near, near) - 1) < 1e-9);
ok("cosine of unrelated vectors is 0", Math.abs(cosine([1, 0], [0, 1])) < 1e-9);
ok(
  "existing vectors are read after the candidate block",
  (() => {
    // candidates: identical to first existing. existing: [match, different]
    const vecs = [near, near, far];
    const d = findSemanticDuplicates(["q"], ["existing-match", "other"], vecs);
    return d.has(0);
  })()
);
ok(
  "a different question is not a duplicate",
  (() => {
    const vecs = [far, near];
    return !findSemanticDuplicates(["q"], ["existing"], vecs).has(0);
  })()
);

// A small model copies the "Correct answer: B" shape out of worked examples.
ok("rejects a leaked answer key as the prompt", !validateGeneratedRow(goodMcq({ prompt: "Correct answer: B" }), "mcq").ok);
ok(
  "rejects meta text about the correct answer",
  !validateGeneratedRow(goodMcq({ prompt: 'What is the correct answer for the question: "The product arrived"?' }), "mcq").ok
);
ok("still accepts a real question", validateGeneratedRow(goodMcq({ prompt: "Which Claude model is best for complex agents?" }), "mcq").ok);

ok("accepts 4 options", validateGeneratedRow(withOptions(4), "mcq").ok);
ok("accepts 5 options", validateGeneratedRow(withOptions(5, 2), "mcq").ok);
ok("rejects 3 options", !validateGeneratedRow(withOptions(3), "mcq").ok);
ok("rejects 2 options", !validateGeneratedRow(withOptions(2), "mcq").ok);
ok("rejects 6 options", !validateGeneratedRow(withOptions(6), "mcq").ok);
ok("rejects 1 option", !validateGeneratedRow(withOptions(1), "mcq").ok);

console.log("\n--- self-contained questions (must PASS)");
ok("plain mcq", validateGeneratedRow(goodMcq(), "mcq").ok);
ok(
  "mcq with inline ASCII diagram",
  validateGeneratedRow(
    goodMcq({
      prompt:
        "What does this request pipeline diagram show?\n```text\n[USER] -> [SDK] -> [API]\n         -> [MODEL]\n```\nPick the component that tokenizes the prompt.",
    }),
    "mcq"
  ).ok
);
ok(
  "mcq with inline program",
  validateGeneratedRow(
    goodMcq({
      prompt:
        "What does this function return?\n```python\ndef f(x):\n    return x * 2\n```\nChoose the output for f(3).",
    }),
    "mcq"
  ).ok
);
ok(
  "question that merely says 'table' as a noun",
  validateGeneratedRow(
    goodMcq({ prompt: "Which database table stores a user's saved exam attempts?" }),
    "mcq"
  ).ok
);
ok(
  "question that describes the diagram in words",
  validateGeneratedRow(
    goodMcq({ prompt: "In a request pipeline where the SDK forwards to the API which calls the model, what is the first hop?" }),
    "mcq"
  ).ok
);
ok(
  "question naming a figure but including it inline",
  validateGeneratedRow(
    goodMcq({ prompt: "The figure below shows sampling:\n```text\nprobs -> sample -> token\n```\nWhat does sampling do?" }),
    "mcq"
  ).ok
);

console.log("\n--- broken questions (must be REJECTED)");
const cases: [string, ReturnType<typeof goodMcq>][] = [
  ["'the diagram above'", goodMcq({ prompt: "According to the diagram above, what flows into the context window?" })],
  ["'following code'", goodMcq({ prompt: "What does the following code print?" })],
  ["'output above'", goodMcq({ prompt: "Why is the output above deterministic?" })],
  ["'figure below'", goodMcq({ prompt: "What is the main purpose of the figure below?" })],
  ["'see the table'", goodMcq({ prompt: "Which row of the table is correct?" })],
  ["'as shown in the chart'", goodMcq({ prompt: "As shown in the chart, when does the window reset?" })],
  ["screenshot even with fence", goodMcq({ prompt: "What does the screenshot show?\n```text\nfoo\n```" })],
  ["blank option", goodMcq({ choices: [{ text: "POST", correct: true }, { text: "", correct: false }] })],
  ["duplicate options", goodMcq({ choices: [{ text: "GET", correct: true }, { text: "GET", correct: false }] })],
  ["zero correct (bad correctIndex)", goodMcq({ choices: [{ text: "GET", correct: false }, { text: "PUT", correct: false }] })],
  ["two correct", goodMcq({ choices: [{ text: "GET", correct: true }, { text: "PUT", correct: true }] })],
  ["too short", goodMcq({ prompt: "Why?" })],
];
for (const [label, row] of cases) ok(`rejects ${label}`, !validateGeneratedRow(row, "mcq").ok);

console.log("\n--- true/false answer key (must be REJECTED when missing)");
ok(
  "rejects tf with no answer key",
  !validateGeneratedRow(
    { topicId: null, prompt: "HTTP is stateless by design in its protocol.", type: "true_false", choices: [], answer: "", explanation: "x", category: null },
    "true_false"
  ).ok
);
ok(
  "rejects tf with zero correct sides",
  !validateGeneratedRow(
    { topicId: null, prompt: "HTTP is stateless by design in its protocol.", type: "true_false", choices: [{ text: "True", correct: false }, { text: "False", correct: false }], answer: "True", explanation: "x", category: null },
    "true_false"
  ).ok
);
ok(
  "accepts a sound tf",
  validateGeneratedRow(
    { topicId: null, prompt: "HTTP is stateless by design in its protocol.", type: "true_false", choices: [{ text: "True", correct: true }, { text: "False", correct: false }], answer: "True", explanation: "Each request carries its own context.", category: null },
    "true_false"
  ).ok
);

console.log("\n--- regex unit checks");
ok("detects 'the diagram'", hasDanglingVisualReference("What is the main purpose of the diagram?"));
ok("ignores 'table' as a noun", !hasDanglingVisualReference("Which table holds the scores?"));
ok("allows fenced content", !hasDanglingVisualReference("The figure below:\n```text\na -> b\n```\nWhat flows?"));
ok("flags raster refs", hasDanglingVisualReference("Based on the image below, what is shown?\n```text\nx\n```"));

// Syllabus import. The bug these guard against: a whole exam guide was read as
// one 0% "topic" per line (388 of them) and saved as a real syllabus, because
// the outline parser had no plausibility check and so never fell back to AI.
console.log("\n--- syllabus parsing");

const proctoringProse = Array.from(
  { length: 150 },
  (_, i) =>
    `Candidates must remain within view of the proctor and webcam for the entire session, rule ${i} of the exam.`
).join("\n");
ok("rejects a wall of prose (returns null)", parseSyllabusOutline(proctoringProse) === null);
ok("rejects pdf page furniture", parseSyllabusOutline("Agents — 50%\nArchitecture — 30%\n-- 12 of 14 --") === null);

// The shape Anthropic's own CCDV-F guide uses.
const blueprintDoc = [
  "Domain 1: Agents and Workflows (14.7%)",
  "Agent Architecture (4.5%)",
  "Principles, patterns, and tradeoffs of agent architecture, including subagents.",
  "Agent Construction with Claude (5.3%)",
  "Methods, tools, and platforms for constructing Claude agents.",
  "Agent Patterns and Frameworks (4.9%)",
  "Common agent design patterns for tool use and retrieval.",
  "Domain 2: Eval, Testing, and Debugging (2.6%)",
  "Debugging and Error Handling (2.6%)",
  "Reading traces and instrumenting an agent for evaluation.",
].join("\n");
const blueprint = parseWeightedBlueprint(blueprintDoc);
ok("reads the official 'Domain N: Name (W%)' blueprint", blueprint !== null);
ok("blueprint keeps 2 domains", blueprint?.length === 2);
ok(
  "blueprint keeps only the 4 skill names, not the prose",
  (blueprint ?? []).flatMap((d) => d.children ?? []).length === 4
);
ok("blueprint sums to 100", Math.abs(sumLeafWeight(normalizeWeights(blueprint ?? [])) - 100) < 0.001);
// A document whose skills do not add up to their own domain weight is not a
// weightage blueprint, so it must be handed to the model instead.
ok(
  "rejects a blueprint whose skills contradict its domains",
  parseWeightedBlueprint("Domain 1: Agents (14.7%)\nArchitecture (40%)\nDomain 2: Tools (2.6%)\nMCP (2.6%)") === null
);

// Plain pasted outlines, in each shape people actually paste.
const mdOutline = "# Agents — 60%\n- Architecture (40%)\n- Patterns (20%)\n# Tools — 40%\n- MCP (40%)";
const md = parseSyllabusOutline(mdOutline);
ok("markdown bullets nest under their heading", md?.[0]?.children?.length === 2);
ok("markdown outline normalises to 100", Math.abs(sumLeafWeight(normalizeWeights(md ?? [])) - 100) < 0.001);

const alphaOutline = "1. Agents (60%)\n   a. Architecture (40%)\n   b. Patterns (20%)\n2. Tools (40%)\n   a. MCP (40%)";
ok("strips alphabetic list markers", parseSyllabusOutline(alphaOutline)?.[0]?.children?.[0]?.name === "Architecture");
ok("leaves initials alone", parseSyllabusOutline("A. Reyes — Testing (40%)\nB. Okafor — Debugging (60%)")?.[0]?.name === "A. Reyes — Testing");

// Weightage maths: largest-remainder must land on exactly 100 every time.
ok("normalises 25 uneven leaves to exactly 100", (() => {
  const nodes = Array.from({ length: 25 }, (_, i) => ({ name: `T${i}`, weight: i === 0 ? 33.1 : 2.4 }));
  return sumLeafWeight(normalizeWeights(nodes)) === 100;
})());
ok("parent weight is the sum of its children", (() => {
  // The parent is a heading, so normalising must rewrite it to whatever the
  // children now total — not leave it at the value the document gave it.
  const n = normalizeWeights([
    { name: "A", weight: 50, children: [{ name: "A1", weight: 30 }, { name: "A2", weight: 20 }] },
  ]);
  const childSum = n[0].children!.reduce((s, c) => s + c.weight, 0);
  return n[0].weight === childSum && childSum === 100;
})());
ok("all-zero weights are spread evenly, not left at 0", (() => {
  const n = normalizeWeights([
    { name: "A", weight: 0, children: [{ name: "A1", weight: 0 }, { name: "A2", weight: 0 }] },
  ]);
  return sumLeafWeight(n) === 100;
})());

console.log(`\n${failures === 0 ? "all checks passed" : `${failures} check(s) FAILED`}`);
process.exit(failures === 0 ? 0 : 1);
