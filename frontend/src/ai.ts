// SSE client for POST /api/ai/chat (docs/ai-assistant.md).
// Uses fetch + a streamed reader so events render incrementally.

import { ApiRequestError } from './api';
import type { AiChatEvent, AiChatMessage } from './types';

/** Parse a single SSE `data:` line into an event. Returns null for anything else. */
export function parseSseLine(line: string): AiChatEvent | null {
  const trimmed = line.trim();
  if (!trimmed.startsWith('data:')) return null;
  const payload = trimmed.slice(5).trim();
  if (!payload) return null;
  try {
    const obj = JSON.parse(payload) as AiChatEvent;
    return typeof obj === 'object' && obj !== null && 'event' in obj ? obj : null;
  } catch {
    return null;
  }
}

/**
 * Incremental SSE parser: feed raw decoded text (possibly partial lines),
 * get back complete events. Handles lines split across chunks.
 */
export class SseParser {
  private buffer = '';

  push(text: string): AiChatEvent[] {
    this.buffer += text;
    const events: AiChatEvent[] = [];
    let idx: number;
    while ((idx = this.buffer.indexOf('\n')) !== -1) {
      const line = this.buffer.slice(0, idx);
      this.buffer = this.buffer.slice(idx + 1);
      const ev = parseSseLine(line);
      if (ev) events.push(ev);
    }
    return events;
  }

  /** Flush any trailing line without a newline (end of stream). */
  flush(): AiChatEvent[] {
    const rest = this.buffer;
    this.buffer = '';
    const ev = parseSseLine(rest);
    return ev ? [ev] : [];
  }
}

export interface AiChatHandlers {
  onEvent: (ev: AiChatEvent) => void;
}

const GENERIC_ERROR = 'Something went wrong — try again?';

/**
 * POST /api/ai/chat and stream events. Resolves when the stream ends;
 * throws AiRequestError for non-200 responses, Error for network failures.
 */
export async function streamAiChat(
  messages: AiChatMessage[],
  workflowId: string | undefined,
  handlers: AiChatHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch('/api/ai/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(workflowId ? { messages, workflow_id: workflowId } : { messages }),
      signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new Error('Could not reach the backend — is it running?');
  }

  if (!res.ok) {
    let detail = GENERIC_ERROR;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      // keep generic
    }
    throw new ApiRequestError(res.status, detail);
  }
  if (!res.body) throw new Error(GENERIC_ERROR);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const ev of parser.push(decoder.decode(value, { stream: true }))) handlers.onEvent(ev);
    }
    for (const ev of parser.flush()) handlers.onEvent(ev);
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    // mid-stream failure
    throw new Error(GENERIC_ERROR);
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // already released
    }
  }
}
