import { useEffect, useMemo, useState } from "react";

import { Callout, Card, Field, PageHeader } from "../components/ui";
import { api, getApiToken, setApiToken } from "../lib/api";
import type { ProviderSpec, SecretStatus } from "../lib/types";
import { describeError, useApp } from "../state/store";

const AUTH_LABELS: Record<string, string> = {
  api_key: "API key",
  none: "No authentication",
  bearer_optional: "Bearer token (optional)",
  managed_identity: "Managed identity",
};

export function SettingsPage() {
  const { settings, active, configs, notify, refresh } = useApp();
  const [specs, setSpecs] = useState<ProviderSpec[]>([]);
  const [providerId, setProviderId] = useState("");
  const [form, setForm] = useState({ model: "", base_url: "", auth_mode: "api_key", api_key: "" });
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);

  const [general, setGeneral] = useState({
    web_search_provider: "",
    web_search_endpoint: "",
    travel_provider: "",
    travel_api_base_url: "",
    finance_provider: "",
    finance_broker_base_url: "",
    coding_workspace_root: "",
  });

  const [secrets, setSecrets] = useState<SecretStatus[]>([]);
  const [secretDrafts, setSecretDrafts] = useState<Record<string, string>>({});
  const [token, setToken] = useState(() => getApiToken());

  const spec = useMemo(() => specs.find((item) => item.id === providerId), [specs, providerId]);

  useEffect(() => {
    void api
      .providers()
      .then((items) => {
        setSpecs(items);
        const preferred = items.find((item) => item.id === active?.provider) ?? items[0];
        if (preferred) {
          setProviderId(preferred.id);
          setForm((current) => ({
            ...current,
            model: active?.model || preferred.default_model,
            base_url: active?.base_url || preferred.default_base_url,
            auth_mode: preferred.supported_auth_modes[0] ?? "api_key",
          }));
        }
      })
      .catch((error: unknown) => {
        const info = describeError(error);
        notify("error", info.message, info.hint);
      });
  }, [active?.base_url, active?.model, active?.provider, notify]);

  useEffect(() => {
    if (!settings) return;
    setGeneral({
      web_search_provider: settings.integrations.web_search.provider,
      web_search_endpoint: "",
      travel_provider: settings.integrations.travel.provider,
      travel_api_base_url: "",
      finance_provider: settings.integrations.finance.provider,
      finance_broker_base_url: "",
      coding_workspace_root: settings.coding.workspace_root,
    });
  }, [settings]);

  useEffect(() => {
    void api
      .secrets()
      .then(setSecrets)
      .catch(() => setSecrets([]));
  }, []);

  const chooseProvider = (id: string) => {
    setProviderId(id);
    const next = specs.find((item) => item.id === id);
    if (!next) return;
    setForm({
      model: next.default_model,
      base_url: next.default_base_url,
      auth_mode: next.supported_auth_modes[0] ?? "api_key",
      api_key: "",
    });
    setTestResult(null);
  };

  const payload = () => ({
    provider: providerId,
    model: form.model,
    base_url: form.base_url,
    auth_mode: form.auth_mode,
    api_key: form.api_key || null,
  });

  const test = async () => {
    setBusy(true);
    try {
      const response = await api.testProvider(payload());
      setTestResult({ ok: response.ok, message: response.message || (response.ok ? "Connected." : "Failed.") });
    } catch (error) {
      const info = describeError(error);
      setTestResult({ ok: false, message: info.message });
    } finally {
      setBusy(false);
    }
  };

  const save = async (activate: boolean) => {
    setBusy(true);
    try {
      if (activate) await api.activateProvider(payload());
      else await api.saveProvider(payload());
      notify("success", activate ? "Provider activated." : "Configuration saved.");
      setForm((current) => ({ ...current, api_key: "" }));
      await refresh();
    } catch (error) {
      const info = describeError(error);
      notify("error", info.message, info.hint);
    } finally {
      setBusy(false);
    }
  };

  const saveGeneral = async () => {
    setBusy(true);
    try {
      await api.updateSettings(general);
      notify("success", "Settings saved and persisted.");
      await refresh();
    } catch (error) {
      const info = describeError(error);
      notify("error", info.message, info.hint);
    } finally {
      setBusy(false);
    }
  };

  const saveSecret = async (name: string) => {
    const value = secretDrafts[name];
    if (!value) return;
    try {
      await api.setSecret(name, value);
      setSecretDrafts((current) => ({ ...current, [name]: "" }));
      setSecrets(await api.secrets());
      notify("success", "Secret stored in the configured secret backend.");
      await refresh();
    } catch (error) {
      const info = describeError(error);
      notify("error", info.message, info.hint);
    }
  };

  const removeSecret = async (name: string) => {
    try {
      await api.deleteSecret(name);
      setSecrets(await api.secrets());
      await refresh();
    } catch (error) {
      const info = describeError(error);
      notify("error", info.message, info.hint);
    }
  };

  return (
    <div className="page">
      <PageHeader
        title="Settings"
        subtitle="One active model at a time. Switching validates the target before activating it."
      />

      <Card title="Active model">
        <div className="row wrap">
          <span className={`badge ${active?.is_configured ? "badge-low" : "badge-warn"}`}>
            {active?.is_configured ? "Active" : "Not configured"}
          </span>
          {active?.provider ? (
            <span className="badge">
              {active.provider} · {active.model}
            </span>
          ) : null}
          {active?.capabilities ? (
            <>
              <span className="badge">streaming {active.capabilities.streaming ? "yes" : "no"}</span>
              <span className="badge">tools {active.capabilities.tool_calling ? "yes" : "no"}</span>
              <span className="badge">
                structured {active.capabilities.structured_output ? "yes" : "no"}
              </span>
            </>
          ) : null}
        </div>

        <div className="grid two">
          <Field label="Provider">
            <select value={providerId} onChange={(event) => chooseProvider(event.target.value)}>
              {specs.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.display_name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Model identifier">
            <input
              value={form.model}
              onChange={(event) => setForm({ ...form, model: event.target.value })}
              placeholder={spec?.default_model}
            />
          </Field>
          <Field
            label="Base URL"
            hint={spec?.supports_custom_base_url ? "Custom endpoints are allowed for this provider." : undefined}
          >
            <input
              value={form.base_url}
              onChange={(event) => setForm({ ...form, base_url: event.target.value })}
              disabled={!spec?.supports_custom_base_url}
            />
          </Field>
          <Field label="Authentication">
            <select
              value={form.auth_mode}
              onChange={(event) => setForm({ ...form, auth_mode: event.target.value })}
            >
              {(spec?.supported_auth_modes ?? ["api_key"]).map((mode) => (
                <option key={mode} value={mode}>
                  {AUTH_LABELS[mode] ?? mode}
                </option>
              ))}
            </select>
          </Field>
        </div>

        {spec?.requires_api_key && form.auth_mode === "api_key" ? (
          <Field label="API key" hint="Stored in the OS credential vault, never in the database or logs.">
            <input
              type="password"
              value={form.api_key}
              onChange={(event) => setForm({ ...form, api_key: event.target.value })}
              placeholder={active?.provider === providerId ? "Leave blank to keep the saved key" : "sk-…"}
            />
          </Field>
        ) : null}

        {testResult ? (
          <Callout kind={testResult.ok ? "success" : "error"} title={testResult.ok ? "Connection ok" : "Connection failed"}>
            {testResult.message}
          </Callout>
        ) : null}

        <div className="row end">
          <button type="button" className="btn ghost" disabled={busy} onClick={() => void test()}>
            Test connection
          </button>
          <button type="button" className="btn" disabled={busy} onClick={() => void save(false)}>
            Save only
          </button>
          <button type="button" className="btn primary" disabled={busy} onClick={() => void save(true)}>
            Save and activate
          </button>
        </div>
      </Card>

      <Card title="Saved configurations">
        {configs.length ? (
          <table className="table">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Model</th>
                <th>Secret</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {configs.map((config) => (
                <tr key={config.id}>
                  <td>{config.provider}</td>
                  <td className="mono">{config.model}</td>
                  <td>{config.has_secret ? "stored" : "missing"}</td>
                  <td>{config.is_active ? "active" : "inactive"}</td>
                  <td className="row end">
                    {!config.is_active ? (
                      <button
                        type="button"
                        className="btn ghost small"
                        disabled={busy}
                        onClick={() =>
                          void api
                            .activateSavedProvider(config.id)
                            .then(() => refresh())
                            .catch((error: unknown) => {
                              const info = describeError(error);
                              notify("error", info.message, info.hint);
                            })
                        }
                      >
                        Activate
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="btn danger small"
                      disabled={busy}
                      onClick={() =>
                        void api
                          .deleteProvider(config.id)
                          .then(() => refresh())
                          .catch((error: unknown) => {
                            const info = describeError(error);
                            notify("error", info.message, info.hint);
                          })
                      }
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">No saved configurations yet.</p>
        )}
      </Card>

      <Card
        title="Integrations"
        actions={
          <button type="button" className="btn primary small" disabled={busy} onClick={() => void saveGeneral()}>
            Save settings
          </button>
        }
      >
        <div className="grid two">
          <Field label="Web search provider" hint="Brave, Tavily or a SearXNG endpoint.">
            <select
              value={general.web_search_provider}
              onChange={(event) => setGeneral({ ...general, web_search_provider: event.target.value })}
            >
              <option value="">Not configured</option>
              <option value="brave">Brave</option>
              <option value="tavily">Tavily</option>
              <option value="searxng">SearXNG</option>
            </select>
          </Field>
          <Field label="Search endpoint (SearXNG)">
            <input
              value={general.web_search_endpoint}
              onChange={(event) => setGeneral({ ...general, web_search_endpoint: event.target.value })}
              placeholder="https://searx.example.org"
            />
          </Field>
          <Field label="Travel provider">
            <select
              value={general.travel_provider}
              onChange={(event) => setGeneral({ ...general, travel_provider: event.target.value })}
            >
              <option value="">Not configured</option>
              <option value="amadeus">Amadeus</option>
              <option value="rail-guidance">Rail guidance only</option>
            </select>
          </Field>
          <Field label="Travel API base URL">
            <input
              value={general.travel_api_base_url}
              onChange={(event) => setGeneral({ ...general, travel_api_base_url: event.target.value })}
              placeholder="https://test.api.amadeus.com"
            />
          </Field>
          <Field label="Finance data provider">
            <select
              value={general.finance_provider}
              onChange={(event) => setGeneral({ ...general, finance_provider: event.target.value })}
            >
              <option value="">Not configured</option>
              <option value="stooq">Stooq</option>
              <option value="yahoo">Yahoo</option>
            </select>
          </Field>
          <Field label="Broker base URL" hint="Leave empty for paper trading only.">
            <input
              value={general.finance_broker_base_url}
              onChange={(event) => setGeneral({ ...general, finance_broker_base_url: event.target.value })}
              placeholder="https://broker.example.com/api"
            />
          </Field>
          <Field label="Coding workspace" hint="Absolute path to the folder the coding agent may touch.">
            <input
              value={general.coding_workspace_root}
              onChange={(event) => setGeneral({ ...general, coding_workspace_root: event.target.value })}
              placeholder="/home/you/projects"
            />
          </Field>
        </div>
      </Card>

      <Card title="Secrets">
        <p className="muted small">
          Values are written to the {settings?.security.secret_backend.backend ?? "configured"} secret
          store and never returned by the API.
          {settings?.security.secret_backend.security !== "os-vault" ? (
            <span className="muted"> {settings?.security.secret_backend.note}</span>
          ) : null}
        </p>
        <ul className="list">
          {secrets.map((secret) => (
            <li key={secret.name}>
              <div className="secret-row">
                <div>
                  <strong>{secret.label}</strong>
                  <div className="muted small mono">{secret.name}</div>
                </div>
                <div className="row">
                  <input
                    type="password"
                    value={secretDrafts[secret.name] ?? ""}
                    onChange={(event) =>
                      setSecretDrafts((current) => ({ ...current, [secret.name]: event.target.value }))
                    }
                    placeholder={secret.configured ? "Stored — replace" : "Not set"}
                    aria-label={secret.label}
                  />
                  <button
                    type="button"
                    className="btn small"
                    onClick={() => void saveSecret(secret.name)}
                    disabled={!secretDrafts[secret.name]}
                  >
                    Save
                  </button>
                  {secret.configured ? (
                    <button
                      type="button"
                      className="btn danger small"
                      onClick={() => void removeSecret(secret.name)}
                    >
                      Remove
                    </button>
                  ) : null}
                </div>
              </div>
            </li>
          ))}
        </ul>
      </Card>

      <Card title="Runtime and security">
        <div className="grid two">
          <div>
            <p className="muted small">Secret backend</p>
            <p>
              {settings?.security.secret_backend.backend ?? "—"}{" "}
              <span className="muted small">
                ({settings?.security.secret_backend.security ?? "unknown"})
              </span>
            </p>
          </div>
          <div>
            <p className="muted small">API bound to</p>
            <p className="mono">{settings?.security.api_bound_to ?? "—"}</p>
          </div>
          <div>
            <p className="muted small">Tool iteration limit</p>
            <p>{settings?.limits.max_tool_iterations ?? "—"}</p>
          </div>
          <div>
            <p className="muted small">Agent step limit</p>
            <p>{settings?.limits.max_agent_steps ?? "—"}</p>
          </div>
        </div>
        <Field label="Local API token" hint="Required only when the backend sets NEXAPILOT_API_TOKEN.">
          <div className="row">
            <input
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="Optional shared token"
            />
            <button
              type="button"
              className="btn"
              onClick={() => {
                setApiToken(token.trim());
                notify("info", "API token saved for this device.");
              }}
            >
              Save token
            </button>
          </div>
        </Field>
      </Card>
    </div>
  );
}
