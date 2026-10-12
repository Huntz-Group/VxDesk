// Right-hand panel: node properties (schema-driven) + workflow variables.

import { useEffect, useMemo, useState } from 'react';
import { useEditorStore } from '../editorStore';
import { useAppStore, catalogDef } from '../store';
import { categoryColor, NodeIcon } from '../icons';
import type { Region } from '../types';
import { ParamField } from './ParamField';
import { ScreenPickerModal } from './ScreenPickerModal';

type PickerState =
  | { mode: 'region'; apply: (r: Region) => void }
  | { mode: 'template'; apply: (name: string) => void }
  | null;

export function PropertiesPanel() {
  const nodes = useEditorStore((s) => s.nodes);
  const workflow = useEditorStore((s) => s.workflow);
  const updateNodeParams = useEditorStore((s) => s.updateNodeParams);
  const renameNode = useEditorStore((s) => s.renameNode);
  const setNodeDisabled = useEditorStore((s) => s.setNodeDisabled);
  const deleteSelection = useEditorStore((s) => s.deleteSelection);
  const setVariables = useEditorStore((s) => s.setVariables);
  const catalog = useAppStore((s) => s.catalog);
  const backendOnline = useAppStore((s) => s.backend === 'online');

  const [tab, setTab] = useState<'node' | 'variables'>('node');
  const [picker, setPicker] = useState<PickerState>(null);
  const [pulse, setPulse] = useState(false);

  // "Details" from the context menu lands here: switch to the Step tab and
  // give the panel a one-time highlight pulse.
  const focusNonce = useEditorStore((s) => s.propsFocusNonce);
  useEffect(() => {
    if (focusNonce === 0) return;
    setTab('node');
    setPulse(true);
    const t = setTimeout(() => setPulse(false), 1100);
    return () => clearTimeout(t);
  }, [focusNonce]);

  const selected = nodes.find((n) => n.selected);
  const def = selected ? catalogDef(catalog, selected.data.nodeType) : undefined;

  const workflowNodes = useMemo(
    () => nodes.map((n) => ({ id: n.id, type: n.data.nodeType, name: n.data.label })),
    [nodes],
  );

  return (
    <div className={`props${pulse ? ' pulse' : ''}`}>
      <div className="props-tabs">
        <button className={tab === 'node' ? 'active' : ''} onClick={() => setTab('node')}>
          Step
        </button>
        <button className={tab === 'variables' ? 'active' : ''} onClick={() => setTab('variables')}>
          Variables
        </button>
      </div>
      <div className="props-body">
        {tab === 'variables' ? (
          <VariablesEditor
            variables={workflow?.variables ?? {}}
            onChange={setVariables}
          />
        ) : !selected ? (
          <div className="props-empty">
            Click a step on the canvas to see its settings here.
            <div style={{ marginTop: 10 }}>
              <span className="kbd-hint">Del</span> removes the selected step
            </div>
          </div>
        ) : (
          <>
            <div className="row" style={{ marginBottom: 10 }}>
              <span className="cat-chip" style={{ background: categoryColor(selected.data.category) }}>
                <NodeIcon name={selected.data.icon} size={13} />
                {def?.label ?? selected.data.nodeType}
              </span>
              <div className="grow" />
              <div className="muted" style={{ fontFamily: 'var(--mono)', fontSize: 10.5 }}>
                {selected.data.nodeType} · {selected.id}
              </div>
            </div>
            {def?.description && (
              <div className="muted" style={{ fontSize: 12.5, marginBottom: 12 }}>
                {def.description}
              </div>
            )}

            <div className="field">
              <label>Name</label>
              <input
                className="input"
                value={selected.data.label}
                onChange={(e) => renameNode(selected.id, e.target.value)}
              />
            </div>

            <div className="field">
              <div className="row">
                <button
                  type="button"
                  className={`toggle${selected.data.disabled ? ' on' : ''}`}
                  onClick={() => setNodeDisabled(selected.id, !selected.data.disabled)}
                  aria-label="Pause this step"
                />
                <span style={{ fontSize: 12.5 }}>Pause this step (it will be skipped)</span>
              </div>
            </div>

            <div className="props-section-title">Settings</div>
            {(def?.params ?? []).length === 0 && <div className="muted">Nothing to set up for this step.</div>}
            {(def?.params ?? []).map((p) => (
              <ParamField
                key={p.name}
                def={p}
                value={selected.data.params[p.name]}
                onChange={(v) => updateNodeParams(selected.id, { [p.name]: v })}
                nodeType={selected.data.nodeType}
                siblingParams={selected.data.params}
                workflowNodes={workflowNodes}
                backendOnline={backendOnline}
                onPickRegion={(apply) => setPicker({ mode: 'region', apply })}
                onNewTemplate={(apply) => setPicker({ mode: 'template', apply })}
              />
            ))}

            <div className="props-section-title"> </div>
            <button className="btn danger small" onClick={deleteSelection}>
              Delete this step
            </button>
          </>
        )}
      </div>

      {picker && (
        <ScreenPickerModal
          mode={picker.mode}
          onClose={() => setPicker(null)}
          onRegion={(r) => {
            if (picker.mode === 'region') picker.apply(r);
            setPicker(null);
          }}
          onTemplateSaved={(name) => {
            if (picker.mode === 'template') picker.apply(name);
            setPicker(null);
          }}
        />
      )}
    </div>
  );
}

function VariablesEditor({
  variables,
  onChange,
}: {
  variables: Record<string, string>;
  onChange: (vars: Record<string, string>) => void;
}) {
  const entries = Object.entries(variables);

  const setEntry = (i: number, key: string, val: string) => {
    const next = entries.map(([k, v], j) => (j === i ? ([key, val] as [string, string]) : ([k, v] as [string, string])));
    onChange(Object.fromEntries(next));
  };
  const removeEntry = (i: number) => {
    onChange(Object.fromEntries(entries.filter((_, j) => j !== i)));
  };
  const addEntry = () => {
    let k = 'var1';
    let n = 1;
    while (k in variables) k = `var${++n}`;
    onChange({ ...variables, [k]: '' });
  };

  return (
    <>
      <div className="muted" style={{ fontSize: 12.5, marginBottom: 10 }}>
        Named values your steps can reuse, like <code style={{ fontFamily: 'var(--mono)' }}>{'{{ vars.name }}'}</code>.
      </div>
      {entries.map(([k, v], i) => (
        <div className="var-row" key={i}>
          <input className="input" value={k} placeholder="name" onChange={(e) => setEntry(i, e.target.value, v)} />
          <input className="input" value={v} placeholder="value" onChange={(e) => setEntry(i, k, e.target.value)} />
          <button className="del" title="Remove" onClick={() => removeEntry(i)}>
            ✕
          </button>
        </div>
      ))}
      <button className="btn small" onClick={addEntry}>
        + Add variable
      </button>
    </>
  );
}
