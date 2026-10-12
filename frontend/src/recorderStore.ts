// Recorder state machine: idle → recording → reviewing → idle.
// Global (survives page navigation); polls /api/recorder/status every 1 s
// while recording. Defensive about the Esc hotkey stopping the session
// server-side (see docs/recorder.md).

import { create } from 'zustand';
import {
  ApiRequestError,
  recorderConvert,
  recorderDiscard,
  recorderStart,
  recorderStatus,
  recorderStop,
} from './api';
import { useAppStore } from './store';
import type { RecorderMode, RecorderStopResult, Workflow } from './types';

export type RecorderPhase = 'idle' | 'starting' | 'recording' | 'stopped_note' | 'reviewing';

interface Toast {
  kind: 'ok' | 'error';
  text: string;
}

interface RecorderState {
  phase: RecorderPhase;
  sessionId: string | null;
  eventCount: number;
  elapsedS: number;
  /** inline note shown where the bar was (e.g. after an Esc stop) */
  note: string | null;
  review: RecorderStopResult | null;
  convertError: string | null;
  converting: boolean;
  toast: Toast | null;

  start: () => Promise<void>;
  stop: () => Promise<void>;
  cancel: () => Promise<void>;
  convert: (name: string, mode: RecorderMode) => Promise<Workflow | null>;
  discardReview: () => Promise<void>;
  dismissNote: () => void;
  showToast: (kind: 'ok' | 'error', text: string) => void;
}

let pollTimer: ReturnType<typeof setInterval> | null = null;
let toastTimer: ReturnType<typeof setTimeout> | null = null;
let noteTimer: ReturnType<typeof setTimeout> | null = null;

function stopPolling(): void {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

export const useRecorderStore = create<RecorderState>((set, get) => {
  const showToast = (kind: 'ok' | 'error', text: string) => {
    if (toastTimer) clearTimeout(toastTimer);
    set({ toast: { kind, text } });
    toastTimer = setTimeout(() => set({ toast: null }), 2200);
  };

  /** Esc (or anything else) ended the session server-side — decide what to show. */
  const handleServerSideStop = async () => {
    stopPolling();
    // Try the regular stop call: if the backend kept the session we still get
    // the events + preview and can go straight to review.
    try {
      const result = await recorderStop();
      set({ phase: 'reviewing', review: result, sessionId: result.session_id, note: null });
      return;
    } catch {
      // session really is gone
    }
    set({ phase: 'stopped_note', sessionId: null, note: 'Recording stopped. Nothing was saved.' });
    if (noteTimer) clearTimeout(noteTimer);
    noteTimer = setTimeout(() => set({ phase: 'idle', note: null }), 4000);
  };

  const poll = async () => {
    try {
      const status = await recorderStatus();
      if (status.recording) {
        set({
          eventCount: status.event_count ?? 0,
          elapsedS: status.elapsed_s ?? 0,
          sessionId: status.session_id ?? get().sessionId,
        });
      } else if (get().phase === 'recording') {
        await handleServerSideStop();
      }
    } catch {
      // backend hiccup — keep polling; a dead backend surfaces via other UI
    }
  };

  return {
    phase: 'idle',
    sessionId: null,
    eventCount: 0,
    elapsedS: 0,
    note: null,
    review: null,
    convertError: null,
    converting: false,
    toast: null,

    showToast,

    start: async () => {
      if (get().phase !== 'idle' && get().phase !== 'stopped_note') return;
      set({ phase: 'starting', note: null });
      try {
        const { session_id } = await recorderStart();
        set({ phase: 'recording', sessionId: session_id, eventCount: 0, elapsedS: 0 });
        stopPolling();
        pollTimer = setInterval(() => void poll(), 1000);
      } catch (e) {
        set({ phase: 'idle' });
        if (e instanceof ApiRequestError && e.status === 409) {
          showToast('error', 'A recording is already in progress');
        } else {
          showToast('error', e instanceof Error ? e.message : "Couldn't start recording");
        }
      }
    },

    stop: async () => {
      if (get().phase !== 'recording') return;
      stopPolling();
      try {
        const result = await recorderStop();
        set({ phase: 'reviewing', review: result, sessionId: result.session_id, convertError: null });
      } catch (e) {
        set({ phase: 'idle', sessionId: null });
        showToast('error', e instanceof Error ? e.message : "Couldn't stop the recording");
      }
    },

    cancel: async () => {
      const sessionId = get().sessionId;
      stopPolling();
      set({ phase: 'idle', sessionId: null, review: null });
      if (sessionId) {
        try {
          await recorderDiscard(sessionId);
        } catch {
          // already gone — fine
        }
      }
      showToast('ok', 'Recording discarded');
    },

    convert: async (name, mode) => {
      const sessionId = get().sessionId ?? get().review?.session_id;
      if (!sessionId) return null;
      set({ converting: true, convertError: null });
      try {
        const wf = await recorderConvert(sessionId, name, mode);
        set({ phase: 'idle', sessionId: null, review: null, converting: false });
        useAppStore.getState().bumpWorkflows();
        showToast('ok', 'Workflow created — happy tuning!');
        return wf;
      } catch (e) {
        set({
          converting: false,
          convertError: e instanceof Error ? e.message : 'Something went wrong — try again?',
        });
        return null;
      }
    },

    discardReview: async () => {
      const sessionId = get().sessionId ?? get().review?.session_id;
      set({ phase: 'idle', sessionId: null, review: null, convertError: null });
      if (sessionId) {
        try {
          await recorderDiscard(sessionId);
        } catch {
          // already gone — fine
        }
      }
      showToast('ok', 'Recording discarded');
    },

    dismissNote: () => {
      if (noteTimer) clearTimeout(noteTimer);
      set({ phase: 'idle', note: null });
    },
  };
});
