// Floating assistant chat panel (right side, works on both pages).

import { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router';
import { useAssistantStore, type ChatItem } from '../assistantStore';
import { useEditorStore } from '../editorStore';
import { GearIcon, SparkleIcon } from '../icons';
import { Blobs } from './Blobs';
import { AiSettingsDialog } from './AiSettingsDialog';

function fmtTime(ts: number): string {
  const d = new Date(ts);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}`;
}

function ToolChip({ item }: { item: Extract<ChatItem, { kind: 'tool' }> }) {
  return (
    <div className={`ai-tool ${item.status}`}>
      <span className="ai-tool-dot" />
      <span className="ai-tool-text">{item.status === 'pending' ? `${item.summary}…` : item.summary}</span>
      <span className="ai-tool-time">{fmtTime(item.ts)}</span>
    </div>
  );
}

export function AssistantPanel() {
  const open = useAssistantStore((s) => s.open);
  const items = useAssistantStore((s) => s.items);
  const streaming = useAssistantStore((s) => s.streaming);
  const status = useAssistantStore((s) => s.status);
  const setupDismissed = useAssistantStore((s) => s.setupDismissed);
  const settingsOpen = useAssistantStore((s) => s.settingsOpen);
  const setOpen = useAssistantStore((s) => s.setOpen);
  const setSettingsOpen = useAssistantStore((s) => s.setSettingsOpen);
  const dismissSetup = useAssistantStore((s) => s.dismissSetup);
  const send = useAssistantStore((s) => s.send);
  const abort = useAssistantStore((s) => s.abort);
  const clear = useAssistantStore((s) => s.clear);

  const [draft, setDraft] = useState('');
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const location = useLocation();

  // workflow currently open in the editor (only on /workflow/:id)
  const openWorkflowId = useEditorStore((s) => s.workflow?.id);
  const workflowId = location.pathname.startsWith('/workflow/') ? openWorkflowId : undefined;

  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [items.length, streaming, open]);

  if (!open) return settingsOpen ? <AiSettingsDialog /> : null;

  const showSetup = status !== null && status.configured === false && !setupDismissed;

  const submit = () => {
    const text = draft.trim();
    if (!text || streaming) return;
    setDraft('');
    void send(text, workflowId);
  };

  return (
    <>
      <div className="ai-panel">
        <div className="ai-head">
          <span className="ai-head-title">
            <SparkleIcon size={15} />
            Assistant
          </span>
          <span className="grow" />
          <button className="ai-icon-btn" title="Assistant settings" onClick={() => setSettingsOpen(true)}>
            <GearIcon />
          </button>
          <button className="ai-icon-btn" title="Close" onClick={() => setOpen(false)}>
            ✕
          </button>
        </div>

        {showSetup ? (
          <div className="ai-setup">
            <Blobs variant="empty" />
            <div className="ai-setup-title font-display">Let's pick a brain for me</div>
            <p>
              I need a language model to think with — a local one like Ollama works great, or bring your own
              provider.
            </p>
            <button className="btn primary" onClick={() => setSettingsOpen(true)}>
              Set it up
            </button>
            <button className="btn text" onClick={dismissSetup}>
              Maybe later
            </button>
          </div>
        ) : (
          <>
            <div className="ai-body" ref={bodyRef}>
              {items.length === 0 && (
                <div className="ai-empty">
                  <Blobs variant="empty" />
                  <div className="ai-empty-title font-display">Hi! I can build workflows for you.</div>
                  <div className="ai-empty-hint">
                    Try: “Make a workflow that types hello into Notepad”
                  </div>
                </div>
              )}
              {items.map((item) =>
                item.kind === 'tool' ? (
                  <ToolChip key={item.key} item={item} />
                ) : (
                  <div key={item.key} className={`ai-msg ${item.role}${item.isError ? ' error' : ''}`}>
                    <div className="ai-bubble">{item.content}</div>
                    <div className="ai-time">{fmtTime(item.ts)}</div>
                  </div>
                ),
              )}
              {streaming && <div className="ai-thinking">Thinking…</div>}
            </div>

            {items.length > 0 && !streaming && (
              <div className="ai-clear-row">
                <button className="btn text small" onClick={clear}>
                  Start a fresh chat
                </button>
              </div>
            )}

            <div className="ai-input-row">
              <textarea
                className="ai-input"
                placeholder={streaming ? 'Working on it…' : 'Ask me to build or run something…'}
                value={draft}
                disabled={streaming}
                rows={2}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    submit();
                  }
                }}
              />
              {streaming ? (
                <button className="btn" onClick={abort} title="Stop waiting (the backend may finish anyway)">
                  Stop
                </button>
              ) : (
                <button className="btn primary" disabled={!draft.trim()} onClick={submit}>
                  Send
                </button>
              )}
            </div>
          </>
        )}
      </div>
      {settingsOpen && <AiSettingsDialog />}
    </>
  );
}
