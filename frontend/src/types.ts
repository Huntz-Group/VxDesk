// TypeScript types mirroring docs/api-contract.md — the contract is the source of truth.

export interface Region {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Point {
  x: number;
  y: number;
}

// ---- System ----

export interface SystemInfo {
  version: string;
  os: string;
  python: string;
  capture: { backend: string; gpu: boolean; fps_hint?: number };
  ocr: { available: boolean; backend: string; gpu: boolean; provider?: string };
  gpu: { name: string; directml: boolean };
  screens: { index: number; x: number; y: number; width: number; height: number }[];
}

// ---- Workflows ----

export interface WorkflowNode {
  id: string;
  type: string;
  name: string;
  position: Point;
  params: Record<string, unknown>;
  disabled?: boolean;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string; // "default" when unbranched
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  variables: Record<string, string>;
}

export interface WorkflowSummary {
  id: string;
  name: string;
  description: string;
  updated_at: string;
  node_count: number;
}

export interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

// ---- Runs ----

export type RunStatus = 'running' | 'success' | 'failed' | 'stopped';

export type NodeRunStatus = 'pending' | 'running' | 'success' | 'failed' | 'skipped';

export interface NodeState {
  status: NodeRunStatus | string;
  output?: unknown;
  duration_ms?: number | null;
  error?: string | null;
}

export interface RunDetail {
  run_id: string;
  workflow_id: string;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  node_states: Record<string, NodeState>;
}

export interface RunSummary {
  run_id: string;
  workflow_id?: string;
  status: RunStatus;
  started_at: string;
  finished_at?: string | null;
  error?: string | null;
}

// WS /ws/runs/{run_id} events
export interface SnapshotEvent extends RunDetail {
  event: 'snapshot';
}
export interface RunStartedEvent {
  event: 'run_started';
  run_id: string;
}
export interface NodeStartedEvent {
  event: 'node_started';
  node_id: string;
  name?: string;
}
export interface NodeFinishedEvent {
  event: 'node_finished';
  node_id: string;
  status: NodeRunStatus | string;
  output?: unknown;
  duration_ms?: number;
}
export interface LogEvent {
  event: 'log';
  node_id?: string;
  level: string;
  message: string;
}
export interface RunFinishedEvent {
  event: 'run_finished';
  status: RunStatus;
  error?: string | null;
}

export type RunEvent =
  | SnapshotEvent
  | RunStartedEvent
  | NodeStartedEvent
  | NodeFinishedEvent
  | LogEvent
  | RunFinishedEvent;

// ---- Capture / vision ----

export interface WindowInfo {
  hwnd: number;
  title: string;
  rect: Region;
  visible: boolean;
}

export interface MatchResult {
  found: boolean;
  x: number;
  y: number;
  w: number;
  h: number;
  score: number;
  center: Point;
  elapsed_ms: number;
}

export interface OcrBox {
  text: string;
  confidence: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface OcrResult {
  boxes: OcrBox[];
  elapsed_ms: number;
}

// ---- Template assets ----

export interface TemplateInfo {
  name: string;
  width: number;
  height: number;
  size_bytes: number;
}

// ---- Node catalog ----

export type ParamKind =
  | 'string'
  | 'text'
  | 'number'
  | 'boolean'
  | 'select'
  | 'template'
  | 'region'
  | 'point'
  | 'csv'
  | 'code'
  | 'keys';

export interface SelectOption {
  value: string;
  label: string;
}

export interface ParamDef {
  name: string;
  label: string;
  kind: ParamKind;
  required?: boolean;
  default?: unknown;
  min?: number;
  max?: number;
  step?: number;
  options?: SelectOption[];
  placeholder?: string;
  help?: string;
}

export interface NodeDef {
  type: string;
  category: string;
  label: string;
  description: string;
  icon: string;
  branch_handles?: string[];
  params: ParamDef[];
}

export interface NodeCatalog {
  nodes: NodeDef[];
}

export interface ApiError {
  detail: string;
}

// ---- AI assistant (docs/ai-assistant.md) ----

export interface AiPreset {
  id: string;
  label: string;
  base_url: string;
  needs_key: boolean;
  model_hint: string;
}

export interface AiSettings {
  provider: string;
  base_url: string;
  model: string;
  has_api_key: boolean;
  presets: AiPreset[];
}

export interface AiStatus {
  configured: boolean;
  reachable?: boolean;
  model?: string;
  detail?: string;
}

export interface AiChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface AiAssistantMessageEvent {
  event: 'assistant_message';
  content: string;
}
export interface AiToolStartEvent {
  event: 'tool_start';
  id: string;
  name: string;
  summary: string;
}
export interface AiToolEndEvent {
  event: 'tool_end';
  id: string;
  name: string;
  ok: boolean;
  summary: string;
  workflow_id?: string;
}
export interface AiDoneEvent {
  event: 'done';
  content: string;
}
export interface AiErrorEvent {
  event: 'error';
  message: string;
}

export type AiChatEvent =
  | AiAssistantMessageEvent
  | AiToolStartEvent
  | AiToolEndEvent
  | AiDoneEvent
  | AiErrorEvent;

// ---- Recorder (docs/recorder.md) ----

export interface RecorderEvent {
  t: number;
  kind: 'click' | 'char' | 'key' | 'window' | string;
  x?: number;
  y?: number;
  button?: string;
  text?: string;
  key?: string;
  window?: string;
  title?: string;
}

/**
 * One row of the human-readable preview returned by /stop.
 * The contract does not fix the item shape, so every field is optional and
 * the UI degrades gracefully.
 */
export interface RecorderStepPreview {
  /** engine node type, e.g. "action.click" — present if the backend previews converted nodes */
  type?: string;
  /** recorded event kind, e.g. "click" / "key" / "char" / "wait" / "window" */
  kind?: string;
  /** plain-language node name, e.g. "Click \"Save\"" */
  name?: string;
  summary?: string;
}

export interface RecorderStartResult {
  session_id: string;
}

export interface RecorderStopResult {
  session_id: string;
  events: RecorderEvent[];
  duration_s: number;
  step_preview: RecorderStepPreview[];
}

export interface RecorderStatus {
  recording: boolean;
  session_id?: string;
  event_count: number;
  elapsed_s: number;
}

export type RecorderMode = 'smart' | 'coordinates';

// ---- Remote services (docs/remote-services.md) ----

export interface RemoteTransports {
  ws: boolean;
  tcp: boolean;
  edge: boolean;
}

export interface RemoteTls {
  enabled: boolean;
  cert: string;
  key: string;
}

export interface RemoteStatus {
  enabled: boolean;
  bind: string;
  transports: RemoteTransports;
  tcp_port: number;
  tls: RemoteTls;
  agents_online: number;
  agents_total: number;
  restart_required?: boolean;
}

export interface RemoteSettingsPatch {
  enabled?: boolean;
  bind?: string;
  transports?: Partial<RemoteTransports>;
  tcp_port?: number;
  tls?: Partial<RemoteTls>;
}

export interface RemoteAgent {
  agent_id: string;
  name: string;
  online: boolean;
  transport: 'ws' | 'tcp' | 'edge' | string;
  /** ISO-8601 string or epoch seconds/ms — backend dependent */
  last_seen: string | number | null;
  caps: Record<string, unknown>;
  address?: string;
}

export interface NewAgentResult {
  agent_id: string;
  token: string;
}

export interface RemoteActivityItem {
  ts: string | number;
  agent_id: string;
  kind: string;
  message: string;
  run_id?: string;
  command_id?: string;
  ok?: boolean;
}
