// Bottom log console fed by WS run events, with per-node filtering.

import { useEffect, useMemo, useRef, useState } from 'react';
import { useEditorStore } from '../editorStore';

function fmtTime(ts: number): string {
  const d = new Date(ts);
  const p = (n: number, l = 2) => String(n).padStart(l, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
}

export function LogConsole() {
  const logs = useEditorStore((s) => s.logs);
  const nodes = useEditorStore((s) => s.nodes);
  const [filter, setFilter] = useState<string>('');
  const bodyRef = useRef<HTMLDivElement | null>(null);

  const nodeName = useMemo(() => {
    const m = new Map<string, string>();
    for (const n of nodes) m.set(n.id, n.data.label);
    return m;
  }, [nodes]);

  const visible = useMemo(
    () => (filter ? logs.filter((l) => l.nodeId === filter) : logs),
    [logs, filter],
  );

  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [visible.length]);

  return (
    <div className="console">
      <div className="console-head">
        <span className="title">What happened</span>
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">all nodes</option>
          {nodes.map((n) => (
            <option key={n.id} value={n.id}>
              {n.data.label} ({n.id})
            </option>
          ))}
        </select>
        <span className="grow" />
        <span>{visible.length} lines</span>
        <button
          className="btn small"
          onClick={() => useEditorStore.setState({ logs: [] })}
        >
          Clear
        </button>
      </div>
      <div className="console-body" ref={bodyRef}>
        {visible.length === 0 && <div className="muted">Nothing yet — press Run and watch what happens.</div>}
        {visible.map((l) => (
          <div key={l.seq} className={`console-line ${l.level}`}>
            <span className="ts">{fmtTime(l.ts)}</span>
            <span className="node">{l.nodeId ? (nodeName.get(l.nodeId) ?? l.nodeId) : '—'}</span>
            <span className="msg">{l.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
