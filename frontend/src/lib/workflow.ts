// Pure conversions between the workflow JSON document (api-contract) and
// React Flow nodes/edges. No React imports — unit-testable.

import type { Edge, Node } from '@xyflow/react';
import type { NodeDef, Workflow, WorkflowEdge, WorkflowNode } from '../types';

export interface VxNodeData extends Record<string, unknown> {
  /** engine type string, e.g. "vision.find_image" */
  nodeType: string;
  label: string;
  category: string;
  icon: string;
  params: Record<string, unknown>;
  disabled: boolean;
  /** branch source handles from the catalog (excludes implicit "default") */
  branchHandles: string[];
  /** validation messages targeted at this node (set by the editor) */
  issues: string[];
}

export type VxFlowNode = Node<VxNodeData, 'vx'>;
export type VxFlowEdge = Edge;

let idCounter = 0;

export function newId(prefix: string): string {
  idCounter += 1;
  return `${prefix}_${Date.now().toString(36)}${idCounter.toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

export function defaultParams(def: NodeDef): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const p of def.params) {
    if (p.default !== undefined) params[p.name] = p.default;
  }
  return params;
}

/** Source handle ids a node exposes: branch handles if any, otherwise ["default"]. */
export function sourceHandles(def: NodeDef | undefined): string[] {
  if (def?.branch_handles && def.branch_handles.length > 0) return def.branch_handles;
  return ['default'];
}

function toFlowNode(n: WorkflowNode, def: NodeDef | undefined): VxFlowNode {
  return {
    id: n.id,
    type: 'vx',
    position: { x: n.position.x, y: n.position.y },
    data: {
      nodeType: n.type,
      label: n.name || def?.label || n.type,
      category: def?.category ?? n.type.split('.')[0] ?? 'unknown',
      icon: def?.icon ?? 'generic',
      params: { ...n.params },
      disabled: n.disabled ?? false,
      branchHandles: def?.branch_handles ?? [],
      issues: [],
    },
  };
}

function toFlowEdge(e: WorkflowEdge): VxFlowEdge {
  const handle = e.sourceHandle ?? 'default';
  return {
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: handle,
    label: handle !== 'default' ? handle : undefined,
  };
}

export function workflowToFlow(
  wf: Workflow,
  catalog: NodeDef[],
): { nodes: VxFlowNode[]; edges: VxFlowEdge[] } {
  const defs = new Map(catalog.map((d) => [d.type, d]));
  return {
    nodes: wf.nodes.map((n) => toFlowNode(n, defs.get(n.type))),
    edges: wf.edges.map(toFlowEdge),
  };
}

export function flowToWorkflow(
  base: Workflow,
  nodes: VxFlowNode[],
  edges: VxFlowEdge[],
): Workflow {
  const wfNodes: WorkflowNode[] = nodes.map((n) => ({
    id: n.id,
    type: n.data.nodeType,
    name: n.data.label,
    position: { x: Math.round(n.position.x), y: Math.round(n.position.y) },
    params: { ...n.data.params },
    disabled: n.data.disabled || undefined,
  }));
  const wfEdges: WorkflowEdge[] = edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: e.sourceHandle ?? 'default',
  }));
  return { ...base, nodes: wfNodes, edges: wfEdges };
}

/** Instantiate a fresh flow node from a catalog definition. */
export function nodeFromDef(def: NodeDef, position: { x: number; y: number }): VxFlowNode {
  return {
    id: newId('n'),
    type: 'vx',
    position,
    data: {
      nodeType: def.type,
      label: def.label,
      category: def.category,
      icon: def.icon,
      params: defaultParams(def),
      disabled: false,
      branchHandles: def.branch_handles ?? [],
      issues: [],
    },
  };
}

/**
 * Best-effort mapping of server validation messages ("node n3: ...") to node ids.
 * Returns a map nodeId -> messages.
 */
export function mapIssuesToNodes(messages: string[], nodeIds: string[]): Map<string, string[]> {
  const map = new Map<string, string[]>();
  for (const msg of messages) {
    let matched = false;
    for (const id of nodeIds) {
      // match "n3" as a whole word or after "node "
      if (msg.includes(` ${id}`) || msg.includes(`(${id})`) || msg.startsWith(`${id}:`) || msg.includes(`node ${id}`)) {
        const list = map.get(id) ?? [];
        list.push(msg);
        map.set(id, list);
        matched = true;
        break;
      }
    }
    if (!matched) {
      const list = map.get('') ?? [];
      list.push(msg);
      map.set('', list);
    }
  }
  return map;
}
