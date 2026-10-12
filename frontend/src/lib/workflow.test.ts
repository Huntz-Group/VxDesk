import { describe, expect, it } from 'vitest';
import { FALLBACK_CATALOG } from '../catalog-fallback';
import type { Workflow } from '../types';
import {
  defaultParams,
  flowToWorkflow,
  mapIssuesToNodes,
  nodeFromDef,
  sourceHandles,
  workflowToFlow,
} from './workflow';

const catalog = FALLBACK_CATALOG.nodes;

const sample: Workflow = {
  id: 'wf_test',
  name: 'Test',
  description: '',
  nodes: [
    { id: 'n1', type: 'trigger.manual', name: 'Start', position: { x: 0, y: 0 }, params: {} },
    {
      id: 'n2',
      type: 'vision.find_image',
      name: 'Find button',
      position: { x: 220, y: 40 },
      params: { template: 'ok.png', threshold: 0.8 },
    },
    { id: 'n3', type: 'action.click', name: 'Click it', position: { x: 440, y: 0 }, params: { target: 'last_found' } },
  ],
  edges: [
    { id: 'e1', source: 'n1', target: 'n2', sourceHandle: 'default' },
    { id: 'e2', source: 'n2', target: 'n3', sourceHandle: 'found' },
  ],
  variables: { env: 'prod' },
};

describe('workflowToFlow / flowToWorkflow round-trip', () => {
  it('preserves the workflow document through a round trip', () => {
    const { nodes, edges } = workflowToFlow(sample, catalog);
    expect(nodes).toHaveLength(3);
    expect(edges).toHaveLength(2);
    const back = flowToWorkflow(sample, nodes, edges);
    expect(back.id).toBe(sample.id);
    expect(back.variables).toEqual(sample.variables);
    expect(back.nodes.map((n) => n.id).sort()).toEqual(['n1', 'n2', 'n3']);
    expect(back.nodes.find((n) => n.id === 'n2')?.params).toEqual({ template: 'ok.png', threshold: 0.8 });
    expect(back.edges.find((e) => e.id === 'e2')?.sourceHandle).toBe('found');
  });

  it('labels branch edges with their handle and leaves default edges unlabeled', () => {
    const { edges } = workflowToFlow(sample, catalog);
    expect(edges.find((e) => e.id === 'e1')?.label).toBeUndefined();
    expect(edges.find((e) => e.id === 'e2')?.label).toBe('found');
  });

  it('rounds positions to integers on export', () => {
    const { nodes, edges } = workflowToFlow(sample, catalog);
    nodes[0].position = { x: 10.6, y: -3.2 };
    const back = flowToWorkflow(sample, nodes, edges);
    expect(back.nodes[0].position).toEqual({ x: 11, y: -3 });
  });
});

describe('catalog helpers', () => {
  it('branch nodes expose branch handles, others the implicit default', () => {
    const findImage = catalog.find((d) => d.type === 'vision.find_image');
    const wait = catalog.find((d) => d.type === 'control.wait');
    expect(sourceHandles(findImage)).toEqual(['found', 'not_found']);
    expect(sourceHandles(wait)).toEqual(['default']);
  });

  it('nodeFromDef applies param defaults', () => {
    const findImage = catalog.find((d) => d.type === 'vision.find_image');
    expect(findImage).toBeDefined();
    const node = nodeFromDef(findImage!, { x: 5, y: 6 });
    expect(node.data.params.threshold).toBe(0.8);
    expect(node.data.branchHandles).toEqual(['found', 'not_found']);
    expect(node.id).toMatch(/^n_/);
  });

  it('defaultParams only includes keys that declare a default', () => {
    const findImage = catalog.find((d) => d.type === 'vision.find_image');
    const params = defaultParams(findImage!);
    expect(params).toEqual({ threshold: 0.8 });
  });

  it('fallback catalog covers the contract node table', () => {
    const types = catalog.map((d) => d.type);
    for (const t of [
      'trigger.manual',
      'input.data_table',
      'control.loop',
      'control.condition',
      'control.wait',
      'control.wait_for',
      'control.set_variable',
      'control.log',
      'capture.screenshot',
      'vision.find_image',
      'vision.find_text',
      'action.click',
      'action.move',
      'action.drag',
      'action.type_text',
      'action.press_key',
      'action.focus_window',
      'action.launch',
      'script.python',
      'output.save_screenshot',
    ]) {
      expect(types).toContain(t);
    }
  });
});

describe('mapIssuesToNodes', () => {
  it('routes messages mentioning a node id to that node, rest to global', () => {
    const map = mapIssuesToNodes(
      ['node n2: missing required param template', 'workflow has no trigger'],
      ['n1', 'n2', 'n3'],
    );
    expect(map.get('n2')).toEqual(['node n2: missing required param template']);
    expect(map.get('')).toEqual(['workflow has no trigger']);
  });
});
