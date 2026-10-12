// WebSocket client for /ws/runs/{run_id} with bounded reconnect.

import type { RunEvent } from './types';

export interface RunSocketHandlers {
  onEvent: (ev: RunEvent) => void;
  onOpen?: () => void;
  onClose?: (hadError: boolean) => void;
}

export class RunSocket {
  private ws: WebSocket | null = null;
  private handlers: RunSocketHandlers;
  private runId: string;
  private attempts = 0;
  private maxAttempts = 5;
  private closedByUser = false;
  private finished = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(runId: string, handlers: RunSocketHandlers) {
    this.runId = runId;
    this.handlers = handlers;
  }

  connect(): void {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${window.location.host}/ws/runs/${encodeURIComponent(this.runId)}`;
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      this.attempts = 0;
      this.handlers.onOpen?.();
    };
    ws.onmessage = (msg) => {
      try {
        const ev = JSON.parse(String(msg.data)) as RunEvent;
        if (ev.event === 'run_finished') this.finished = true;
        this.handlers.onEvent(ev);
      } catch {
        // ignore malformed frames
      }
    };
    ws.onclose = () => {
      this.handlers.onClose?.(false);
      if (!this.closedByUser && !this.finished) this.scheduleReconnect();
    };
    ws.onerror = () => {
      // onclose follows
    };
  }

  private scheduleReconnect(): void {
    if (this.closedByUser || this.finished || this.attempts >= this.maxAttempts) {
      this.handlers.onClose?.(true);
      return;
    }
    this.attempts += 1;
    const delay = Math.min(500 * 2 ** this.attempts, 5000);
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  close(): void {
    this.closedByUser = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.onmessage = null;
      try {
        this.ws.close();
      } catch {
        // already closed
      }
      this.ws = null;
    }
  }
}
