import { useState } from "react";

import { Markdown } from "../components/Markdown";
import { Callout, Card, PageHeader } from "../components/ui";
import { useAgentRun } from "../hooks/useAgentRun";
import { useApp } from "../state/store";

const EXAMPLES = [
  "Compare the latest EU AI Act obligations for deployers of general-purpose models, with sources.",
  "What changed in Python 3.13 that affects long-running async services?",
  "Summarise recent guidance on HTTPS certificate lifetimes and cite the source.",
];

export function ResearchPage() {
  const { settings } = useApp();
  const { state, start, cancel } = useAgentRun();
  const [query, setQuery] = useState("");

  const searchConfigured = settings?.integrations.web_search.configured ?? false;

  const run = async (message: string) => {
    if (!message.trim()) return;
    await start({ message, workflow: "research" });
  };

  return (
    <div className="page">
      <PageHeader
        title="Research"
        subtitle="Searches the web, opens sources and separates sourced facts from estimates."
        actions={
          state.running ? (
            <button type="button" className="btn ghost" onClick={() => void cancel()}>
              Stop
            </button>
          ) : null
        }
      />

      {!searchConfigured ? (
        <Callout kind="warn" title="No search provider configured">
          Add a Brave, Tavily or SearXNG key in Settings. NexaPilot will say it cannot search live
          instead of inventing results.
        </Callout>
      ) : null}

      <Card title="Question">
        <textarea
          rows={4}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="What do you want to know? Include constraints, date ranges and preferred sources."
        />
        <div className="row wrap">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className="chip"
              onClick={() => {
                setQuery(example);
                void run(example);
              }}
            >
              {example.length > 70 ? `${example.slice(0, 69)}…` : example}
            </button>
          ))}
        </div>
        <div className="row end">
          <button
            type="button"
            className="btn primary"
            disabled={state.running || !query.trim()}
            onClick={() => void run(query)}
          >
            Run research
          </button>
        </div>
      </Card>

      {state.status ? <p className="status-line">{state.status}</p> : null}
      {state.error ? (
        <Callout kind="error" title="Research failed">
          {state.error}
        </Callout>
      ) : null}

      {state.text ? (
        <Card title="Findings" className="output">
          <Markdown text={state.text} />
        </Card>
      ) : null}

      {state.citations.length ? (
        <Card title="Citations">
          <ol className="citation-list">
            {state.citations.map((citation, index) => (
              <li key={`${citation.url ?? index}`}>
                {citation.url ? (
                  <a href={citation.url} target="_blank" rel="noreferrer noopener">
                    {citation.title || citation.url}
                  </a>
                ) : (
                  <span>{citation.title || citation.source || "Source"}</span>
                )}
                {citation.published ? (
                  <span className="muted small"> · published {citation.published}</span>
                ) : null}
              </li>
            ))}
          </ol>
        </Card>
      ) : null}
    </div>
  );
}
