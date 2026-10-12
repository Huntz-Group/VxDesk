// Assistant state: chat items, streaming lifecycle, AI status, side effects
// on workflows (list refresh + editor reload) when tools create/modify one.

import { create } from 'zustand';
import { streamAiChat } from './ai';
import { getAiStatus, getWorkflow } from './api';
import { useEditorStore } from './editorStore';
import { useAppStore } from './store';
import type { AiChatEvent, AiChatMessage, AiStatus } from './types';

export type ToolStatus = 'pending' | 'ok' | 'failed';

export interface ChatMessageItem {
  kind: 'message';
  key: number;
  role: 'user' | 'assistant';
  content: string;
  ts: number;
  isError?: boolean;
}

export interface ChatToolItem {
  kind: 'tool';
  key: number;
  toolId: string;
  name: string;
  summary: string;
  status: ToolStatus;
  ts: number;
}

export type ChatItem = ChatMessageItem | ChatToolItem;

interface AssistantState {
  open: boolean;
  settingsOpen: boolean;
  /** user dismissed the "let's pick a brain" card for this session */
  setupDismissed: boolean;
  items: ChatItem[];
  history: AiChatMessage[];
  streaming: boolean;
  status: AiStatus | null;

  toggle: () => void;
  setOpen: (open: boolean) => void;
  setSettingsOpen: (open: boolean) => void;
  dismissSetup: () => void;
  refreshStatus: () => Promise<void>;
  send: (text: string, workflowId?: string) => Promise<void>;
  abort: () => void;
  clear: () => void;
}

let itemKey = 0;
let abortController: AbortController | null = null;

/** A tool created/modified a workflow: refresh the list; reload the canvas if it's open. */
async function handleWorkflowSideEffect(workflowId: string): Promise<void> {
  useAppStore.getState().bumpWorkflows();
  const openWf = useEditorStore.getState().workflow;
  if (openWf && openWf.id === workflowId) {
    try {
      const fresh = await getWorkflow(workflowId);
      useEditorStore.getState().loadWorkflow(fresh, useAppStore.getState().catalog);
    } catch {
      // editor keeps its current state
    }
  }
}

export const useAssistantStore = create<AssistantState>((set, get) => ({
  open: false,
  settingsOpen: false,
  setupDismissed: false,
  items: [],
  history: [],
  streaming: false,
  status: null,

  toggle: () => {
    const next = !get().open;
    set({ open: next });
    if (next) void get().refreshStatus();
  },
  setOpen: (open) => set({ open }),
  setSettingsOpen: (settingsOpen) => set({ settingsOpen }),
  dismissSetup: () => set({ setupDismissed: true }),

  refreshStatus: async () => {
    try {
      set({ status: await getAiStatus() });
    } catch {
      set({ status: null });
    }
  },

  send: async (text, workflowId) => {
    const content = text.trim();
    if (!content || get().streaming) return;

    itemKey += 1;
    const userItem: ChatMessageItem = { kind: 'message', key: itemKey, role: 'user', content, ts: Date.now() };
    const history: AiChatMessage[] = [...get().history, { role: 'user', content }];
    set({ items: [...get().items, userItem], history, streaming: true });

    abortController = new AbortController();

    const addMessage = (msgContent: string, isError = false) => {
      itemKey += 1;
      set({
        items: [
          ...get().items,
          { kind: 'message', key: itemKey, role: 'assistant', content: msgContent, ts: Date.now(), isError },
        ],
      });
      if (!isError) set({ history: [...get().history, { role: 'assistant', content: msgContent }] });
    };

    const onEvent = (ev: AiChatEvent) => {
      switch (ev.event) {
        case 'assistant_message':
          addMessage(ev.content);
          break;
        case 'tool_start': {
          itemKey += 1;
          const toolItem: ChatToolItem = {
            kind: 'tool',
            key: itemKey,
            toolId: ev.id,
            name: ev.name,
            summary: ev.summary,
            status: 'pending',
            ts: Date.now(),
          };
          set({ items: [...get().items, toolItem] });
          break;
        }
        case 'tool_end':
          set({
            items: get().items.map((it) =>
              it.kind === 'tool' && it.toolId === ev.id
                ? { ...it, status: ev.ok ? 'ok' : 'failed', summary: ev.summary }
                : it,
            ),
          });
          if (ev.workflow_id) void handleWorkflowSideEffect(ev.workflow_id);
          break;
        case 'done':
          addMessage(ev.content);
          set({ streaming: false });
          break;
        case 'error':
          addMessage(ev.message || 'Something went wrong — try again?', true);
          set({ streaming: false });
          break;
      }
    };

    try {
      await streamAiChat(history, workflowId, { onEvent }, abortController.signal);
      // stream ended without done/error — treat as complete
      if (get().streaming) set({ streaming: false });
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        addMessage('Stopped early — no worries, nothing else will happen.', true);
      } else {
        addMessage(e instanceof Error && e.message ? e.message : 'Something went wrong — try again?', true);
      }
      set({ streaming: false });
    } finally {
      abortController = null;
    }
  },

  abort: () => {
    abortController?.abort();
  },

  clear: () => set({ items: [], history: [] }),
}));
