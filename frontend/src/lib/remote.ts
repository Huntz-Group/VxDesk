// Pure helpers for the Remote page (unit-tested).

import { CATEGORY_COLORS } from '../icons';
import type { RemoteAgent } from '../types';

/** Accepts ISO-8601 strings, epoch seconds or epoch ms; returns epoch ms or null. */
export function toEpochMs(ts: string | number | null | undefined): number | null {
  if (ts == null) return null;
  if (typeof ts === 'number') {
    if (!Number.isFinite(ts)) return null;
    // epoch seconds vs ms: anything before ~2001 in ms is surely seconds
    return ts < 1e10 ? ts * 1000 : ts;
  }
  const parsed = Date.parse(ts);
  return Number.isNaN(parsed) ? null : parsed;
}

/** Friendly relative time: "just now", "2 min ago", "3 h ago", "5 days ago". */
export function timeAgo(ts: string | number | null | undefined, nowMs = Date.now()): string {
  const ms = toEpochMs(ts);
  if (ms == null) return 'never';
  const diff = Math.max(0, nowMs - ms);
  const sec = Math.floor(diff / 1000);
  if (sec < 45) return 'just now';
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} min ago`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.floor(h / 24);
  return `${d} day${d === 1 ? '' : 's'} ago`;
}

/** Capabilities dict → short plain summary, e.g. "windows · workflows". */
export function capsSummary(caps: Record<string, unknown> | null | undefined): string {
  if (!caps) return '—';
  const parts: string[] = [];
  if (typeof caps.os === 'string' && caps.os) parts.push(caps.os);
  if (caps.engine === true || caps.workflows === true) parts.push('workflows');
  if (caps.shell === true) parts.push('shell commands');
  return parts.length > 0 ? parts.join(' · ') : '—';
}

export interface KindStyle {
  label: string;
  color: string;
  textColor?: string;
}

/** Activity kind → pastel chip styling. */
export function activityStyle(kind: string, ok?: boolean): KindStyle {
  if (ok === false || kind === 'failed' || kind === 'error') {
    return { label: 'failed', color: '#FBE4EA', textColor: '#8C4356' }; // rose
  }
  switch (kind) {
    case 'connected':
    case 'hello':
      return { label: 'connected', color: CATEGORY_COLORS.input }; // soft blue
    case 'run_started':
      return { label: 'started a run', color: CATEGORY_COLORS.input };
    case 'run_finished':
    case 'ran_workflow':
      return { label: 'ran a workflow', color: CATEGORY_COLORS.action, textColor: '#4E7D3A' }; // sage
    case 'log':
      return { label: 'log', color: '#E5E0D5', textColor: '#54453F' }; // grey-beige
    default:
      return { label: kind, color: '#E5E0D5', textColor: '#54453F' };
  }
}

/** Transport id → pastel chip styling + plain label. */
export function transportStyle(transport: string): KindStyle {
  switch (transport) {
    case 'ws':
      return { label: 'WebSocket', color: CATEGORY_COLORS.input };
    case 'tcp':
      return { label: 'TCP', color: CATEGORY_COLORS.control };
    case 'edge':
      return { label: 'Edge polling', color: CATEGORY_COLORS.output };
    default:
      return { label: transport || '—', color: '#E5E0D5' };
  }
}

/** Friendly machine-count line for the settings card. */
export function machinesLine(online: number, total: number): string {
  if (total === 0) return 'No machines registered yet';
  if (online === 0) return total === 1 ? '1 machine registered, offline' : `${total} machines registered, all offline`;
  if (online === total) return `${online} machine${online === 1 ? '' : 's'} connected`;
  return `${online} of ${total} machines connected`;
}

/** Best-effort display name for an agent id (activity feed rows). */
export function agentLabel(agentId: string, agents: RemoteAgent[]): string {
  return agents.find((a) => a.agent_id === agentId)?.name ?? agentId;
}
