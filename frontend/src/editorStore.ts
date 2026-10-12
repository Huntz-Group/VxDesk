// Editor-scoped store: the workflow document as React Flow nodes/edges plus
// run state (node status rings, log lines, replay).

import { create } from 'zustand';
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from '@xyflow/react';
import {
  flowToWorkflow,
  newId,
  nodeFromDef,
  sourceHandles,
  workflowToFlow,
  type VxFlowEdge,
  type VxFlowNode,
} from './lib/workflow';
import type { NodeDef, NodeState, RunStatus, Workflow } from './types';

export interface LogLine {
  seq: number;
  ts: number;
  level: string;
  nodeId?: string;
  message: string;
}

interface EditorState {
  workflow: Workflow | null;
  nodes: VxFlowNode[];
  edges: VxFlowEdge[];
  dirty: boolean;
  saving: boolean;
  issues: Record<string, string[]>;
  globalIssues: string[];

  runId: string | null;
  runStatus: RunStatus | null;
  nodeStates: Record<string, NodeState>;
  logs: LogLine[];
  replaying: boolean;

  loadWorkflow: (wf: Workflow, catalog: NodeDef[]) => void;
  reset: () => void;

  onNodesChange: (changes: NodeChange<VxFlowNode>[]) => void;
  onEdgesChange: (changes: EdgeChange<VxFlowEdge>[]) => void;
  onConnect: (conn: Connection) => void;
  addNode: (def: NodeDef, position: { x: number; y: number }) => void;
  deleteSelection: () => void;

  updateNodeParams: (id: string, patch: Record<string, unknown>) => void;
  renameNode: (id: string, label: string) => void;
  setNodeDisabled: (id: string, disabled: boolean) => void;
  setVariables: (vars: Record<string, string>) => void;
  renameWorkflow: (name: string) => void;

  /** select exactly one node (used by the context menu "Details") */
  selectOnly: (id: string) => void;
  /** clone a node: new id, offset position, label + " copy" (no edges) */
  duplicateNode: (id: string) => void;
  /** delete a node and its connected edges */
  deleteNode: (id: string) => void;

  /** incremented to ask the properties panel to focus a node's details (with a pulse) */
  propsFocusNonce: number;
  /** incremented to ask the palette to open and focus its search box */
  paletteFocusNonce: number;
  focusNodeDetails: (id: string) => void;
  focusPaletteSearch: () => void;

  toWorkflow: () => Workflow | null;
  markSaved: (wf: Workflow) => void;
  setIssues: (byNode: Record<string, string[]>, globalIssues: string[]) => void;
  clearIssues: () => void;

  beginRun: (runId: string) => void;
  setRunStatus: (status: RunStatus | null) => void;
  setNodeState: (id: string, state: NodeState) => void;
  setNodeStates: (states: Record<string, NodeState>) => void;
  appendLog: (level: string, message: string, nodeId?: string) => void;
  clearRun: () => void;
  loadReplay: (runId: string, status: RunStatus, states: Record<string, NodeState>) => void;
  exitReplay: () => void;
}

let logSeq = 0;

export const useEditorStore = create<EditorState>((set, get) => ({
  workflow: null,
  nodes: [],
  edges: [],
  dirty: false,
  saving: false,
  issues: {},
  globalIssues: [],

  runId: null,
  runStatus: null,
  nodeStates: {},
  logs: [],
  replaying: false,

  loadWorkflow: (wf, catalog) => {
    const { nodes, edges } = workflowToFlow(wf, catalog);
    set({
      workflow: wf,
      nodes,
      edges,
      dirty: false,
      saving: false,
      issues: {},
      globalIssues: [],
      runId: null,
      runStatus: null,
      nodeStates: {},
      logs: [],
      replaying: false,
    });
  },

  reset: () =>
    set({
      workflow: null,
      nodes: [],
      edges: [],
      dirty: false,
      saving: false,
      issues: {},
      globalIssues: [],
      runId: null,
      runStatus: null,
      nodeStates: {},
      logs: [],
      replaying: false,
    }),

  onNodesChange: (changes) => {
    const nodes = applyNodeChanges(changes, get().nodes);
    const structural = changes.some((c) => c.type !== 'select' && c.type !== 'dimensions');
    set({ nodes, dirty: get().dirty || structural });
  },

  onEdgesChange: (changes) => {
    const edges = applyEdgeChanges(changes, get().edges);
    const structural = changes.some((c) => c.type !== 'select');
    set({ edges, dirty: get().dirty || structural });
  },

  onConnect: (conn) => {
    const source = get().nodes.find((n) => n.id === conn.source);
    const allowed = source ? sourceHandlesFromData(source) : ['default'];
    const handle = conn.sourceHandle && allowed.includes(conn.sourceHandle) ? conn.sourceHandle : allowed[0];
    const edge: VxFlowEdge = {
      id: newId('e'),
      source: conn.source,
      target: conn.target,
      sourceHandle: handle ?? 'default',
      label: handle && handle !== 'default' ? handle : undefined,
    };
    set({ edges: addEdge(edge, get().edges), dirty: true });
  },

  addNode: (def, position) => {
    const node = nodeFromDef(def, position);
    set({ nodes: [...get().nodes, node], dirty: true });
  },

  deleteSelection: () => {
    const { nodes, edges } = get();
    const removedIds = new Set(nodes.filter((n) => n.selected).map((n) => n.id));
    const keptEdges = edges.filter((e) => !e.selected && !removedIds.has(e.source) && !removedIds.has(e.target));
    set({
      nodes: nodes.filter((n) => !n.selected),
      edges: keptEdges,
      dirty: true,
    });
  },

  updateNodeParams: (id, patch) =>
    set({
      nodes: get().nodes.map((n) =>
        n.id === id ? { ...n, data: { ...n.data, params: { ...n.data.params, ...patch } } } : n,
      ),
      dirty: true,
    }),

  renameNode: (id, label) =>
    set({
      nodes: get().nodes.map((n) => (n.id === id ? { ...n, data: { ...n.data, label } } : n)),
      dirty: true,
    }),

  setNodeDisabled: (id, disabled) =>
    set({
      nodes: get().nodes.map((n) => (n.id === id ? { ...n, data: { ...n.data, disabled } } : n)),
      dirty: true,
    }),

  setVariables: (vars) => {
    const wf = get().workflow;
    if (!wf) return;
    set({ workflow: { ...wf, variables: vars }, dirty: true });
  },

  renameWorkflow: (name) => {
    const wf = get().workflow;
    if (!wf) return;
    set({ workflow: { ...wf, name }, dirty: true });
  },

  selectOnly: (id) =>
    set({ nodes: get().nodes.map((n) => (n.id === id ? { ...n, selected: true } : { ...n, selected: false })) }),

  duplicateNode: (id) => {
    const src = get().nodes.find((n) => n.id === id);
    if (!src) return;
    const copy: VxFlowNode = {
      ...src,
      id: newId('n'),
      position: { x: src.position.x + 48, y: src.position.y + 48 },
      selected: true,
      data: { ...src.data, label: `${src.data.label} copy`, params: { ...src.data.params } },
    };
    set({
      nodes: [...get().nodes.map((n) => ({ ...n, selected: false })), copy],
      dirty: true,
    });
  },

  deleteNode: (id) =>
    set({
      nodes: get().nodes.filter((n) => n.id !== id),
      edges: get().edges.filter((e) => e.source !== id && e.target !== id),
      dirty: true,
    }),

  propsFocusNonce: 0,
  paletteFocusNonce: 0,

  focusNodeDetails: (id) => {
    get().selectOnly(id);
    set((s) => ({ propsFocusNonce: s.propsFocusNonce + 1 }));
  },

  focusPaletteSearch: () => set((s) => ({ paletteFocusNonce: s.paletteFocusNonce + 1 })),

  toWorkflow: () => {
    const { workflow, nodes, edges } = get();
    if (!workflow) return null;
    return flowToWorkflow(workflow, nodes, edges);
  },

  markSaved: (wf) => set({ workflow: wf, dirty: false, saving: false }),

  setIssues: (byNode, globalIssues) => set({ issues: byNode, globalIssues }),
  clearIssues: () => set({ issues: {}, globalIssues: [] }),

  beginRun: (runId) =>
    set({ runId, runStatus: 'running', nodeStates: {}, logs: [], replaying: false }),

  setRunStatus: (status) => set({ runStatus: status }),

  setNodeState: (id, state) =>
    set({ nodeStates: { ...get().nodeStates, [id]: state } }),

  setNodeStates: (states) => set({ nodeStates: { ...states } }),

  appendLog: (level, message, nodeId) => {
    logSeq += 1;
    const line: LogLine = { seq: logSeq, ts: Date.now(), level, nodeId, message };
    const logs = [...get().logs, line];
    // cap the console to avoid unbounded growth
    set({ logs: logs.length > 2000 ? logs.slice(logs.length - 2000) : logs });
  },

  clearRun: () => set({ runId: null, runStatus: null, nodeStates: {}, logs: [], replaying: false }),

  loadReplay: (runId, status, states) =>
    set({ runId, runStatus: status, nodeStates: { ...states }, replaying: true, logs: [] }),

  exitReplay: () => set({ replaying: false, nodeStates: {}, runId: null, runStatus: null, logs: [] }),
}));

function sourceHandlesFromData(node: VxFlowNode): string[] {
  const branch = node.data.branchHandles;
  if (branch.length > 0) return branch;
  return ['default'];
}

export { sourceHandles };
