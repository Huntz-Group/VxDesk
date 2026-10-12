import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { useEditorStore } from '../editorStore';
import { categoryColor, NodeIcon } from '../icons';
import type { VxFlowNode } from '../lib/workflow';

function formatOutput(output: unknown): string {
  try {
    const s = JSON.stringify(output, null, 2);
    return s.length > 600 ? `${s.slice(0, 600)}\n…` : s;
  } catch {
    return String(output);
  }
}

export const VxNode = memo(function VxNode({ id, data, selected }: NodeProps<VxFlowNode>) {
  const runStatus = useEditorStore((s) => s.nodeStates[id]?.status);
  const output = useEditorStore((s) => s.nodeStates[id]?.output);
  const issues = useEditorStore((s) => s.issues[id]);

  const color = categoryColor(data.category);
  const branches = data.branchHandles;
  const hasOutput = output !== undefined && output !== null;
  const ringClass = runStatus ? `ring ${runStatus}` : 'ring';

  return (
    <div
      className={`vx-node${selected ? ' selected' : ''}${data.disabled ? ' disabled' : ''}${hasOutput ? ' has-output' : ''}`}
      style={{ ['--cat' as string]: color }}
    >
      {runStatus && <div className={ringClass} />}
      <Handle type="target" position={Position.Left} id="target" />
      <div className="vx-node-header">
        <span className="icon">
          <NodeIcon name={data.icon} />
        </span>
        <span className="label" title={data.label}>
          {data.label}
        </span>
      </div>
      <div className="vx-node-type">
        {data.nodeType}
        {data.disabled && <span className="vx-node-paused">paused</span>}
      </div>
      {issues && issues.length > 0 && (
        <div className="vx-node-issues">
          {issues.map((m, i) => (
            <div key={i}>{m}</div>
          ))}
        </div>
      )}
      {branches.length === 0 ? (
        <Handle type="source" position={Position.Right} id="default" />
      ) : (
        <div style={{ paddingBottom: 6 }}>
          {branches.map((h) => (
            <div className="handle-row" key={h}>
              <span className="branch-label">{h.replace('_', ' ')}</span>
              <Handle type="source" position={Position.Right} id={h} style={{ top: '50%' }} />
            </div>
          ))}
        </div>
      )}
      {hasOutput && (
        <div className="output-tip">
          {typeof runStatus === 'string' && <div style={{ color: 'var(--text)', marginBottom: 4 }}>Result ({runStatus})</div>}
          {formatOutput(output)}
        </div>
      )}
    </div>
  );
});
