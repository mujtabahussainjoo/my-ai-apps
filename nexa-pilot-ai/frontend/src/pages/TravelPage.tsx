import { useState } from "react";

import { Markdown } from "../components/Markdown";
import { Callout, Card, Field, PageHeader } from "../components/ui";
import { useAgentRun } from "../hooks/useAgentRun";
import { useApp } from "../state/store";

type Mode = "flights" | "hotels" | "trains";

const MODES: Array<{ id: Mode; label: string }> = [
  { id: "flights", label: "Flights" },
  { id: "hotels", label: "Hotels" },
  { id: "trains", label: "Trains" },
];

export function TravelPage() {
  const { settings } = useApp();
  const { state, start, cancel } = useAgentRun();
  const [mode, setMode] = useState<Mode>("flights");
  const [form, setForm] = useState({
    origin: "",
    destination: "",
    depart: "",
    ret: "",
    travellers: "1",
    budget: "",
    notes: "",
  });

  const configured = settings?.integrations.travel.configured ?? false;

  const update = (key: keyof typeof form) => (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  const buildMessage = (): string => {
    const travellers = `${form.travellers || "1"} traveller(s)`;
    if (mode === "hotels") {
      return [
        `Find hotels in ${form.destination || "the destination"}.`,
        `Check-in ${form.depart || "TBD"}, check-out ${form.ret || "TBD"}.`,
        form.budget ? `Budget: ${form.budget}.` : "",
        form.notes,
        "Compare total price, fees, cancellation terms and availability. Include the provider and retrieval time for every offer.",
      ]
        .filter(Boolean)
        .join(" ");
    }
    if (mode === "trains") {
      return [
        `Find train options from ${form.origin || "origin"} to ${form.destination || "destination"}.`,
        `Departure date ${form.depart || "TBD"}. ${travellers}.`,
        form.budget ? `Budget: ${form.budget}.` : "",
        form.notes,
        "Use only official or authorised sources; if live booking is unavailable, guide me through the official flow instead of claiming a booking.",
      ]
        .filter(Boolean)
        .join(" ");
    }
    return [
      `Find flights from ${form.origin || "origin"} to ${form.destination || "destination"}.`,
      `Departure ${form.depart || "TBD"}${form.ret ? `, return ${form.ret}` : ""}. ${travellers}.`,
      form.budget ? `Budget: ${form.budget}.` : "",
      form.notes,
      "Compare total price, baggage, fees, cancellation terms, timing and availability. Include the provider and retrieval time.",
    ]
      .filter(Boolean)
      .join(" ");
  };

  return (
    <div className="page">
      <PageHeader
        title="Travel"
        subtitle="Discover flights, hotels and trains with provider and retrieval time on every option."
        actions={
          state.running ? (
            <button type="button" className="btn ghost" onClick={() => void cancel()}>
              Stop
            </button>
          ) : null
        }
      />

      {!configured ? (
        <Callout kind="warn" title="No travel provider configured">
          Add Amadeus credentials in Settings → Integrations to check live availability. Without a
          provider, NexaPilot explains the limitation rather than inventing offers.
        </Callout>
      ) : null}

      <Card title="Search">
        <div className="segmented">
          {MODES.map((item) => (
            <button
              key={item.id}
              type="button"
              className={mode === item.id ? "active" : ""}
              onClick={() => setMode(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="grid two">
          <Field label={mode === "hotels" ? "City" : "Origin"}>
            <input value={form.origin} onChange={update("origin")} placeholder="e.g. DEL or Delhi" />
          </Field>
          <Field label={mode === "hotels" ? "Area (optional)" : "Destination"}>
            <input
              value={form.destination}
              onChange={update("destination")}
              placeholder="e.g. LHR or London"
            />
          </Field>
          <Field label={mode === "hotels" ? "Check-in" : "Departure"}>
            <input value={form.depart} onChange={update("depart")} type="date" />
          </Field>
          <Field label={mode === "hotels" ? "Check-out" : "Return (optional)"}>
            <input value={form.ret} onChange={update("ret")} type="date" />
          </Field>
          <Field label="Travellers">
            <input
              value={form.travellers}
              onChange={update("travellers")}
              type="number"
              min={1}
              max={9}
            />
          </Field>
          <Field label="Budget (optional)">
            <input value={form.budget} onChange={update("budget")} placeholder="e.g. under €600" />
          </Field>
        </div>

        <Field label="Preferences">
          <textarea
            rows={2}
            value={form.notes}
            onChange={update("notes")}
            placeholder="Direct flights, refundable fares, near public transport…"
          />
        </Field>

        <div className="row end">
          <button
            type="button"
            className="btn primary"
            disabled={state.running}
            onClick={() => void start({ message: buildMessage(), workflow: "travel" })}
          >
            Search options
          </button>
        </div>
      </Card>

      {state.status ? <p className="status-line">{state.status}</p> : null}
      {state.error ? (
        <Callout kind="error" title="Search failed">
          {state.error}
        </Callout>
      ) : null}
      {state.text ? (
        <Card title="Options" className="output">
          <Markdown text={state.text} />
        </Card>
      ) : null}
      <Callout kind="info" title="Booking is never automatic">
        NexaPilot shows a full preview and needs explicit approval before any booking or payment.
        Nothing is purchased from this page.
      </Callout>
    </div>
  );
}
