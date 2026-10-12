// Typed REST client for the VxDesk backend (docs/api-contract.md).
// All paths are relative — the Vite dev server proxies /api and /ws.

import type {
  AiSettings,
  AiStatus,
  MatchResult,
  NewAgentResult,
  NodeCatalog,
  OcrResult,
  RecorderMode,
  RecorderStartResult,
  RecorderStatus,
  RecorderStopResult,
  Region,
  RemoteActivityItem,
  RemoteAgent,
  RemoteSettingsPatch,
  RemoteStatus,
  RunDetail,
  RunSummary,
  SystemInfo,
  TemplateInfo,
  ValidationResult,
  WindowInfo,
  Workflow,
  WorkflowSummary,
} from './types';

export class ApiRequestError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'ApiRequestError';
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
      else if (body.detail != null) detail = JSON.stringify(body.detail);
    } catch {
      // keep status text
    }
    throw new ApiRequestError(res.status, detail);
  }
  return (await res.json()) as T;
}

function json<T>(path: string, method: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

// ---- System ----

export const getSystemInfo = () => request<SystemInfo>('/api/system/info');

// ---- Workflows ----

export const listWorkflows = () => request<WorkflowSummary[]>('/api/workflows');

export const createWorkflow = (name: string, description = '') =>
  json<Workflow>('/api/workflows', 'POST', { name, description });

export const getWorkflow = (id: string) => request<Workflow>(`/api/workflows/${encodeURIComponent(id)}`);

export const saveWorkflow = (wf: Workflow) =>
  json<Workflow>(`/api/workflows/${encodeURIComponent(wf.id)}`, 'PUT', wf);

export const deleteWorkflow = (id: string) =>
  request<{ ok: boolean }>(`/api/workflows/${encodeURIComponent(id)}`, { method: 'DELETE' });

export const validateWorkflow = (id: string) =>
  json<ValidationResult>(`/api/workflows/${encodeURIComponent(id)}/validate`, 'POST', {});

export const runWorkflow = (id: string, opts: { inputs?: Record<string, unknown>; dry_run?: boolean } = {}) =>
  json<{ run_id: string }>(`/api/workflows/${encodeURIComponent(id)}/run`, 'POST', opts);

export const listRuns = (workflowId: string) =>
  request<RunSummary[]>(`/api/workflows/${encodeURIComponent(workflowId)}/runs`);

// ---- Runs ----

export const getRun = (runId: string) => request<RunDetail>(`/api/runs/${encodeURIComponent(runId)}`);

export const stopRun = (runId: string) =>
  json<{ ok: boolean }>(`/api/runs/${encodeURIComponent(runId)}/stop`, 'POST', {});

// ---- Capture / vision ----

export async function captureScreenshot(region?: Region, format: 'png' | 'jpeg' = 'png'): Promise<Blob> {
  const res = await fetch('/api/capture/screenshot', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(region ? { region, format } : { format }),
  });
  if (!res.ok) throw new ApiRequestError(res.status, `screenshot failed (${res.status})`);
  return res.blob();
}

export const listWindows = () => request<WindowInfo[]>('/api/windows');

export const testMatch = (template: string, threshold?: number, region?: Region) =>
  json<MatchResult>('/api/vision/test-match', 'POST', { template, threshold, region });

export const testOcr = (region?: Region, text?: string) =>
  json<OcrResult>('/api/vision/test-ocr', 'POST', { region, text });

// ---- Template assets ----

export const listTemplates = () => request<TemplateInfo[]>('/api/assets/templates');

export async function uploadTemplate(name: string, png: Blob): Promise<{ name: string; width: number; height: number }> {
  const form = new FormData();
  form.append('name', name);
  form.append('file', png, name.endsWith('.png') ? name : `${name}.png`);
  const res = await fetch('/api/assets/templates', { method: 'POST', body: form });
  if (!res.ok) {
    let detail = `upload failed (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      // keep default
    }
    throw new ApiRequestError(res.status, detail);
  }
  return (await res.json()) as { name: string; width: number; height: number };
}

export const templateUrl = (name: string) => `/api/assets/templates/${encodeURIComponent(name)}`;

export const deleteTemplate = (name: string) =>
  request<{ ok: boolean }>(`/api/assets/templates/${encodeURIComponent(name)}`, { method: 'DELETE' });

// ---- Node catalog ----

export const getCatalog = () => request<NodeCatalog>('/api/nodes/catalog');

// ---- AI assistant ----

export const getAiSettings = () => request<AiSettings>('/api/ai/settings');

export const putAiSettings = (body: { provider: string; base_url: string; model: string; api_key?: string | null }) =>
  json<AiSettings>('/api/ai/settings', 'PUT', body);

export const getAiStatus = () => request<AiStatus>('/api/ai/status');

// ---- Recorder ----

export const recorderStart = () => json<RecorderStartResult>('/api/recorder/start', 'POST', {});

export const recorderStop = () => json<RecorderStopResult>('/api/recorder/stop', 'POST', {});

export const recorderDiscard = (sessionId: string) =>
  json<{ ok: boolean }>('/api/recorder/discard', 'POST', { session_id: sessionId });

export const recorderStatus = () => request<RecorderStatus>('/api/recorder/status');

export const recorderConvert = (sessionId: string, name: string, mode: RecorderMode) =>
  json<Workflow>('/api/recorder/convert', 'POST', { session_id: sessionId, name, mode });

// ---- Remote services ----

export const getRemoteStatus = () => request<RemoteStatus>('/api/remote/status');

export const putRemoteSettings = (patch: RemoteSettingsPatch) =>
  json<RemoteStatus>('/api/remote/settings', 'PUT', patch);

export const listRemoteAgents = () => request<RemoteAgent[]>('/api/remote/agents');

export const createRemoteAgent = (name: string) =>
  json<NewAgentResult>('/api/remote/agents', 'POST', { name });

export const deleteRemoteAgent = (agentId: string) =>
  request<{ ok: boolean }>(`/api/remote/agents/${encodeURIComponent(agentId)}`, { method: 'DELETE' });

export const runRemoteAgent = (agentId: string, workflowId: string, dryRun: boolean) =>
  json<{ command_id: string }>(`/api/remote/agents/${encodeURIComponent(agentId)}/run`, 'POST', {
    workflow_id: workflowId,
    dry_run: dryRun,
  });

export const getRemoteActivity = (limit = 200) =>
  request<RemoteActivityItem[]>(`/api/remote/activity?limit=${limit}`);
