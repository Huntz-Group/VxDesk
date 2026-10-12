import { useEffect, useMemo, useRef, useState } from 'react';
import { useEditorStore } from '../editorStore';
import { useAppStore } from '../store';
import { categoryColor, NodeIcon } from '../icons';
import type { NodeDef } from '../types';

const CATEGORY_ORDER = ['trigger', 'input', 'control', 'capture', 'vision', 'action', 'script', 'output'];

const CATEGORY_NAMES: Record<string, string> = {
  trigger: 'Triggers',
  input: 'Data',
  control: 'Logic',
  capture: 'Capture',
  vision: 'Vision',
  action: 'Actions',
  script: 'Script',
  output: 'Output',
};

export const NODE_DND_MIME = 'application/vxdesk-node';

interface Props {
  onAdd: (def: NodeDef) => void;
}

export function NodePalette({ onAdd }: Props) {
  const catalog = useAppStore((s) => s.catalog);
  const isFallback = useAppStore((s) => s.catalogIsFallback);
  const [collapsed, setCollapsed] = useState(false);
  const [query, setQuery] = useState('');
  const [closedGroups, setClosedGroups] = useState<Record<string, boolean>>({});
  const searchRef = useRef<HTMLInputElement | null>(null);

  // "Add a step…" from the pane context menu: expand and focus the search box.
  const paletteFocusNonce = useEditorStore((s) => s.paletteFocusNonce);
  useEffect(() => {
    if (paletteFocusNonce === 0) return;
    setCollapsed(false);
    const t = setTimeout(() => searchRef.current?.focus(), 40);
    return () => clearTimeout(t);
  }, [paletteFocusNonce]);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const byCat = new Map<string, NodeDef[]>();
    for (const def of catalog) {
      if (q && !`${def.label} ${def.description} ${def.type}`.toLowerCase().includes(q)) continue;
      const list = byCat.get(def.category) ?? [];
      list.push(def);
      byCat.set(def.category, list);
    }
    return [...byCat.entries()].sort(
      (a, b) =>
        (CATEGORY_ORDER.indexOf(a[0]) === -1 ? 99 : CATEGORY_ORDER.indexOf(a[0])) -
        (CATEGORY_ORDER.indexOf(b[0]) === -1 ? 99 : CATEGORY_ORDER.indexOf(b[0])),
    );
  }, [catalog, query]);

  if (collapsed) {
    return (
      <div className="palette collapsed">
        <button className="palette-collapse" title="Show steps" onClick={() => setCollapsed(false)}>
          »
        </button>
      </div>
    );
  }

  return (
    <div className="palette">
      <div className="palette-header">
        <span className="title">Steps</span>
        <button className="palette-collapse" title="Hide" onClick={() => setCollapsed(true)}>
          «
        </button>
      </div>
      <div className="palette-search">
        <input
          ref={searchRef}
          className="input"
          placeholder="Search steps…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      {isFallback && <div className="palette-fallback-note">Showing the built-in step list (backend offline).</div>}
      {groups.length === 0 && (
        <div className="palette-empty">No steps match “{query}”. Try a different word.</div>
      )}
      {groups.map(([cat, defs]) => {
        const closed = closedGroups[cat] ?? false;
        return (
          <div className="palette-group" key={cat}>
            <div
              className="palette-group-title"
              onClick={() => setClosedGroups((g) => ({ ...g, [cat]: !closed }))}
            >
              <span className="stripe" style={{ background: categoryColor(cat) }} />
              <span className="grow">{CATEGORY_NAMES[cat] ?? cat}</span>
              <span className="count">{defs.length}</span>
              <span>{closed ? '+' : '–'}</span>
            </div>
            {!closed &&
              defs.map((def) => (
                <div
                  key={def.type}
                  className="palette-item"
                  style={{ ['--cat' as string]: categoryColor(def.category) }}
                  title={`${def.type}\n\nDrag onto the canvas, or click to add`}
                  draggable
                  onDragStart={(ev) => {
                    ev.dataTransfer.setData(NODE_DND_MIME, def.type);
                    ev.dataTransfer.effectAllowed = 'move';
                  }}
                  onClick={() => onAdd(def)}
                >
                  <span className="icon">
                    <NodeIcon name={def.icon} />
                  </span>
                  <span>
                    <div className="label">{def.label}</div>
                    <div className="desc">{def.description}</div>
                  </span>
                </div>
              ))}
          </div>
        );
      })}
    </div>
  );
}
