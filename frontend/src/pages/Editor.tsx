// Editor view: /workflow/:id — React Flow canvas + palette + properties +
// run bar + log console + run history.

import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { getWorkflow, runWorkflow, saveWorkflow, stopRun, validateWorkflow } from '../api';
import { Blobs } from '../components/Blobs';
import { ContextMenu, type MenuState } from '../components/ContextMenu';
import { LogConsole } from '../components/LogConsole';
import { NodePalette, NODE_DND_MIME } from '../components/NodePalette';
import { PropertiesPanel } from '../components/PropertiesPanel';
import { RunHistoryDrawer } from '../components/RunHistoryDrawer';
import { VxNode } from '../components/VxNode';
import { useEditorStore } from '../editorStore';
import { categoryColor } from '../icons';
import { mapIssuesToNodes } from '../lib/workflow';
import { useAppStore, catalogDef } from '../store';
import type { NodeDef, RunEvent, Workflow } from '../types';
import { RunSocket } from '../ws';

const nodeTypes: NodeTypes = { vx: VxNode };

export function EditorPage() {
  return (
    <ReactFlowProvider>
      <EditorInner />
    </ReactFlowProvider>
  );
}

function EditorInner() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const catalog = useAppStore((s) => s.catalog);
  const backend = useAppStore((s) => s.backend);
  const loadCatalog = useAppStore((s) => s.loadCatalog);

  const workflow = useEditorStore((s) => s.workflow);
  const nodes = useEditorStore((s) => s.nodes);
  const edges = useEditorStore((s) => s.edges);
  const dirty = useEditorStore((s) => s.dirty);
  const saving = useEditorStore((s) => s.saving);
  const runStatus = useEditorStore((s) => s.runStatus);
  const runId = useEditorStore((s) => s.runId);
  const replaying = useEditorStore((s) => s.replaying);
  const globalIssues = useEditorStore((s) => s.globalIssues);

  const { screenToFlowPosition, fitView } = useReactFlow();
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dryRun, setDryRun] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [toast, setToast] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const editingNameRef = useRef(false);
  editingNameRef.current = editingName;
  const socketRef = useRef<RunSocket | null>(null);
  const fittedRef = useRef(false);

  const showToast = useCallback((kind: 'ok' | 'error', text: string) => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast({ kind, text });
    toastTimerRef.current = setTimeout(() => setToast(null), 1600);
  }, []);

  // ---- load ----
  useEffect(() => {
    void loadCatalog();
    let cancelled = false;
    fittedRef.current = false;
    getWorkflow(id)
      .then((wf) => {
        if (!cancelled) useEditorStore.getState().loadWorkflow(wf, useAppStore.getState().catalog);
      })
      .catch((e: unknown) => {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : 'failed to load workflow');
      });
    return () => {
      cancelled = true;
      socketRef.current?.close();
      useEditorStore.getState().reset();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Re-map node visuals if the catalog arrives after the workflow.
  useEffect(() => {
    const wf = useEditorStore.getState().workflow;
    if (wf && catalog.length > 0) useEditorStore.getState().loadWorkflow(wf, catalog);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog]);

  // The `fitView` prop only runs on mount, when nodes haven't loaded yet —
  // fit once the first nodes actually arrive (and dimensions are measured).
  useEffect(() => {
    if (fittedRef.current || nodes.length === 0) return;
    fittedRef.current = true;
    const raf = requestAnimationFrame(() => {
      void fitView({ padding: 0.25, duration: 200 });
    });
    return () => cancelAnimationFrame(raf);
  }, [nodes.length, fitView]);

  // ---- save / validate ----
  const save = useCallback(async (): Promise<Workflow | null> => {
    const wf = useEditorStore.getState().toWorkflow();
    if (!wf) return null;
    useEditorStore.setState({ saving: true });
    try {
      const saved = await saveWorkflow(wf);
      useEditorStore.getState().markSaved(saved);
      return saved;
    } catch (e) {
      useEditorStore.setState({ saving: false });
      useEditorStore.getState().appendLog('error', `save failed: ${e instanceof Error ? e.message : e}`);
      return null;
    }
  }, []);

  const saveWithToast = useCallback(async () => {
    const saved = await save();
    if (saved) showToast('ok', 'Saved ✓');
    else showToast('error', "Couldn't save — is the backend running?");
  }, [save, showToast]);

  // Ctrl+S / Cmd+S saves (also inside text fields); Ctrl+D duplicates the
  // selected step. Neither fires during replay or inline name editing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      const key = e.key.toLowerCase();
      const st = useEditorStore.getState();
      if (key === 's') {
        e.preventDefault();
        if (st.replaying || editingNameRef.current) return;
        void saveWithToast();
      } else if (key === 'd') {
        const t = e.target as HTMLElement | null;
        if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
        const selected = st.nodes.filter((n) => n.selected);
        if (selected.length === 0 || st.replaying) return;
        e.preventDefault();
        for (const n of selected) st.duplicateNode(n.id);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [saveWithToast]);

  const validate = useCallback(async () => {
    const saved = await save();
    if (!saved) return;
    const store = useEditorStore.getState();
    store.appendLog('system', 'validating…');
    try {
      const result = await validateWorkflow(saved.id);
      const mapped = mapIssuesToNodes(
        [...result.errors, ...result.warnings],
        store.nodes.map((n) => n.id),
      );
      const byNode: Record<string, string[]> = {};
      const globals: string[] = [];
      for (const [nodeId, msgs] of mapped) {
        if (nodeId === '') globals.push(...msgs);
        else byNode[nodeId] = msgs;
      }
      store.setIssues(byNode, globals);
      store.appendLog(
        result.valid ? 'system' : 'error',
        result.valid
          ? `valid — ${result.warnings.length} warning(s)`
          : `invalid — ${result.errors.length} error(s), ${result.warnings.length} warning(s)`,
      );
    } catch (e) {
      store.appendLog('error', `validate failed: ${e instanceof Error ? e.message : e}`);
    }
  }, [save]);

  // ---- run ----
  const handleRunEvent = useCallback((ev: RunEvent) => {
    const store = useEditorStore.getState();
    switch (ev.event) {
      case 'snapshot':
        store.setRunStatus(ev.status);
        store.setNodeStates(ev.node_states ?? {});
        store.appendLog('system', `attached to run (status: ${ev.status})`);
        break;
      case 'run_started':
        store.setRunStatus('running');
        store.appendLog('system', `run started (${ev.run_id})`);
        break;
      case 'node_started':
        store.setNodeState(ev.node_id, { status: 'running' });
        store.appendLog('system', `started${ev.name ? ` — ${ev.name}` : ''}`, ev.node_id);
        break;
      case 'node_finished':
        store.setNodeState(ev.node_id, {
          status: ev.status,
          output: ev.output,
          duration_ms: ev.duration_ms,
        });
        store.appendLog(
          ev.status === 'failed' ? 'error' : 'system',
          `finished — ${ev.status}${typeof ev.duration_ms === 'number' ? ` (${ev.duration_ms} ms)` : ''}`,
          ev.node_id,
        );
        break;
      case 'log':
        store.appendLog(ev.level, ev.message, ev.node_id);
        break;
      case 'run_finished':
        store.setRunStatus(ev.status);
        store.appendLog(
          ev.status === 'success' ? 'system' : 'error',
          `run finished: ${ev.status}${ev.error ? ` — ${ev.error}` : ''}`,
        );
        break;
    }
  }, []);

  const run = useCallback(async () => {
    if (useEditorStore.getState().runStatus === 'running') return;
    const saved = await save();
    if (!saved) return;
    useEditorStore.getState().clearIssues();
    try {
      const { run_id } = await runWorkflow(saved.id, { dry_run: dryRun });
      const store = useEditorStore.getState();
      store.beginRun(run_id);
      store.appendLog('system', dryRun ? 'run requested (dry-run)…' : 'run requested…');
      socketRef.current?.close();
      const socket = new RunSocket(run_id, {
        onEvent: handleRunEvent,
        onClose: (hadError) => {
          if (hadError) {
            const s = useEditorStore.getState();
            if (s.runStatus === 'running') {
              s.setRunStatus(null);
              s.appendLog('error', 'lost connection to run stream');
            }
          }
        },
      });
      socketRef.current = socket;
      socket.connect();
    } catch (e) {
      useEditorStore.getState().appendLog('error', `run failed to start: ${e instanceof Error ? e.message : e}`);
    }
  }, [dryRun, handleRunEvent, save]);

  const stop = useCallback(async () => {
    const id2 = useEditorStore.getState().runId;
    if (!id2) return;
    try {
      await stopRun(id2);
      useEditorStore.getState().appendLog('system', 'stop requested…');
    } catch (e) {
      useEditorStore.getState().appendLog('error', `stop failed: ${e instanceof Error ? e.message : e}`);
    }
  }, []);

  // ---- palette / dnd ----
  const addNodeAt = useCallback(
    (def: NodeDef, clientX?: number, clientY?: number) => {
      const pos =
        clientX !== undefined && clientY !== undefined
          ? screenToFlowPosition({ x: clientX, y: clientY })
          : screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 });
      useEditorStore.getState().addNode(def, pos);
    },
    [screenToFlowPosition],
  );

  const onDrop = useCallback(
    (ev: React.DragEvent) => {
      ev.preventDefault();
      const type = ev.dataTransfer.getData(NODE_DND_MIME);
      if (!type) return;
      const def = catalogDef(useAppStore.getState().catalog, type);
      if (def) addNodeAt(def, ev.clientX, ev.clientY);
    },
    [addNodeAt],
  );

  if (loadError) {
    return (
      <div className="editor" style={{ alignItems: 'center', justifyContent: 'center' }}>
        <div className="empty-state" style={{ maxWidth: 420 }}>
          <div style={{ marginBottom: 10 }}>We couldn't open that workflow: {loadError}</div>
          <button className="btn" onClick={() => navigate('/')}>
            Back to workflows
          </button>
        </div>
      </div>
    );
  }
  if (!workflow) {
    return (
      <div className="editor" style={{ alignItems: 'center', justifyContent: 'center' }}>
        <div className="muted">Opening your workflow…</div>
      </div>
    );
  }

  const running = runStatus === 'running';

  return (
    <div className="editor">
      <div className="runbar" style={{ borderTop: 'none', borderBottom: '1px solid var(--hairline)' }}>
        <button className="btn small" onClick={() => navigate('/')}>
          ← All workflows
        </button>
        {editingName ? (
          <input
            className="input"
            style={{ width: 220 }}
            autoFocus
            defaultValue={workflow.name}
            onBlur={(e) => {
              useEditorStore.getState().renameWorkflow(e.target.value.trim() || workflow.name);
              setEditingName(false);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
              if (e.key === 'Escape') setEditingName(false);
            }}
          />
        ) : (
          <span className="font-display" style={{ fontWeight: 600, fontSize: 15, cursor: 'text' }} title="Click to rename" onClick={() => setEditingName(true)}>
            {workflow.name}
          </span>
        )}
        {dirty && <span className="dirty-dot">Unsaved changes</span>}
        {saving && <span className="muted">Saving…</span>}
        <span className="grow" />
        {globalIssues.length > 0 && (
          <span className="error-text" title={globalIssues.join('\n')}>
            {globalIssues.length} thing{globalIssues.length === 1 ? '' : 's'} to fix — hover to see
          </span>
        )}
        <button className="btn small" disabled={backend !== 'online' || saving} onClick={() => void saveWithToast()} title="Ctrl+S">
          Save
        </button>
        <button className="btn small" disabled={backend !== 'online' || saving} onClick={() => void validate()}>
          Check
        </button>
        <button className="btn small" disabled={backend !== 'online'} onClick={() => setHistoryOpen(true)}>
          Past runs
        </button>
      </div>

      {replaying && (
        <div className="replay-banner">
          <span>
            You're looking at a past run ({runStatus}) — the canvas shows its results, read-only.
          </span>
          <span className="grow" />
          <button className="btn small" onClick={() => useEditorStore.getState().exitReplay()}>
            Back to editing
          </button>
        </div>
      )}

      <div className="editor-body">
        <NodePalette onAdd={(def) => addNodeAt(def)} />
        <div className="canvas-wrap" onDrop={onDrop} onDragOver={(ev) => {
          ev.preventDefault();
          ev.dataTransfer.dropEffect = 'move';
        }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={useEditorStore.getState().onNodesChange}
            onEdgesChange={useEditorStore.getState().onEdgesChange}
            onConnect={useEditorStore.getState().onConnect}
            onNodeContextMenu={(ev, node) => {
              ev.preventDefault();
              if (!replaying) setMenu({ x: ev.clientX, y: ev.clientY, nodeId: node.id });
            }}
            onPaneContextMenu={(ev) => {
              ev.preventDefault();
              const me = ev as unknown as React.MouseEvent;
              setMenu({ x: me.clientX, y: me.clientY, nodeId: null });
            }}
            onMoveStart={() => setMenu(null)}
            fitView
            minZoom={0.2}
            maxZoom={2}
            deleteKeyCode={['Delete']}
            nodesDraggable={!replaying}
            nodesConnectable={!replaying}
            edgesFocusable={!replaying}
            proOptions={{ hideAttribution: true }}
            colorMode="light"
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1.5} color="#DDD9CC" />
            <MiniMap
              pannable
              zoomable
              nodeColor={(n) => categoryColor((n.data as { category?: string }).category ?? 'unknown')}
              maskColor="rgba(239, 237, 230, 0.72)"
            />
            <Controls showInteractive={false} />
          </ReactFlow>
          {toast && <div className={`save-toast ${toast.kind}`}>{toast.text}</div>}
          {menu && (
            <ContextMenu
              menu={menu}
              onClose={() => setMenu(null)}
              onFitView={() => void fitView({ padding: 0.25, duration: 200 })}
            />
          )}
          {nodes.length === 0 && (
            <div className="canvas-empty">
              <Blobs variant="empty" />
              <div className="big">Drag your first step here</div>
              <div className="small">Pick one from the list on the left — a trigger is a good start.</div>
            </div>
          )}
        </div>
        <PropertiesPanel />
      </div>

      <div className="runbar">
        <button
          className="btn primary"
          disabled={backend !== 'online' || running || replaying}
          onClick={() => void run()}
        >
          ▶ Run
        </button>
        <button className="btn" disabled={!running} onClick={() => void stop()}>
          Stop
        </button>
        <label className="check" title="Runs through the steps without clicking or typing for real">
          <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
          Practice mode (nothing will be clicked or typed)
        </label>
        {runStatus && (
          <span className={`chip ${runStatus}`}>
            {runStatus}
            {runId ? ` · ${runId.slice(0, 12)}` : ''}
          </span>
        )}
      </div>

      <LogConsole />

      {historyOpen && <RunHistoryDrawer workflowId={workflow.id} onClose={() => setHistoryOpen(false)} />}
    </div>
  );
}
