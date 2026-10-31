export interface Capabilities {
  streaming: boolean;
  tool_calling: boolean;
  structured_output: boolean;
  system_prompt: boolean;
  vision: boolean;
  max_context_tokens: number | null;
}

export interface ProviderSpec {
  id: string;
  display_name: string;
  requires_api_key: boolean;
  supports_custom_base_url: boolean;
  default_base_url: string;
  default_model: string;
  supported_auth_modes: string[];
  capabilities: Capabilities;
}

export interface ProviderConfig {
  id: string;
  provider: string;
  model: string;
  base_url: string;
  auth_mode: string;
  capabilities: Capabilities;
  is_active: boolean;
  has_secret: boolean;
  secret_reference: string;
}

export interface ActiveProvider {
  provider: string;
  model: string;
  base_url: string;
  capabilities: Capabilities;
  is_configured: boolean;
  detail: Record<string, unknown>;
}

export interface SecretBackendStatus {
  backend: string;
  security: "os-vault" | "degraded" | "ephemeral" | string;
  note: string;
}

export interface AppSettings {
  app_name: string;
  environment: string;
  active_provider: string;
  active_model: string;
  active_provider_configured: boolean;
  integrations: {
    web_search: { provider: string; configured: boolean };
    travel: { provider: string; configured: boolean };
    finance: { provider: string; configured: boolean; broker_configured: boolean };
    email: { oauth_client_configured: boolean };
  };
  coding: {
    workspace_root: string;
    workspace_configured: boolean;
    max_output_bytes: number;
  };
  security: {
    secret_backend: SecretBackendStatus;
    api_bound_to: string;
  };
  limits: {
    max_tool_iterations: number;
    max_agent_steps: number;
    finance_max_order_value: number;
    finance_max_order_quantity: number;
  };
}

export interface SecretStatus {
  name: string;
  label: string;
  configured: boolean;
}

export interface Account {
  id: string;
  provider: string;
  email: string;
  label: string;
  status: string;
  scopes: string[];
  auth_mode: string;
  last_sync_at: string | null;
  error: string;
}

export interface Conversation {
  id: string;
  title: string;
  workflow: string;
  updated_at: string;
  provider: string;
  model: string;
}

export interface ChatMessageRecord {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  created_at: string;
  provider?: string;
  model?: string;
  citations?: Citation[];
}

export interface Citation {
  title?: string;
  url?: string;
  source?: string;
  published?: string;
  retrieved_at?: string;
}

export interface Approval {
  id: string;
  action: string;
  title: string;
  description: string;
  target: string;
  risk: string;
  cost: string;
  consequences: string;
  status: string;
  payload: Record<string, unknown>;
  created_at?: string;
}

export interface ActivityEntry {
  id: string;
  workflow: string;
  status: string;
  provider: string;
  model: string;
  steps: number;
  request: Record<string, unknown>;
  error: string;
  started_at: string;
  completed_at: string | null;
}

export interface ToolInfo {
  name: string;
  purpose: string;
  permissions: string[];
  side_effects: boolean;
  requires_approval: boolean;
  approval_action: string;
  risk: string;
  timeout_seconds: number;
}

export type ToolRunResult =
  | { status: "approval_required"; approval: Approval }
  | { status: "completed"; tool: string; output: Record<string, unknown>; approval_id: string };

export interface StreamEvent {
  type: string;
  text?: string;
  message?: string;
  code?: string;
  details?: Record<string, unknown>;
  tool?: string;
  arguments?: Record<string, unknown>;
  status?: string;
  workflow?: string;
  detail?: unknown;
  approval?: Approval;
  approvals?: Approval[];
  answer?: string;
  citations?: Citation[];
  tool_results?: Array<Record<string, unknown>>;
  task_run_id?: string;
  conversation_id?: string;
  provider?: string;
  model?: string;
}
