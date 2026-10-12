// Schema-driven parameter controls for the properties panel.

import { useEffect, useState } from 'react';
import { listTemplates, templateUrl, testMatch } from '../api';
import { parseCsv } from '../lib/csv';
import type { MatchResult, ParamDef, Point, Region, TemplateInfo } from '../types';

const TEMPLATE_HINT = (
  <>
    You can insert values from earlier steps, like <code>{'{{ n1.output.score }}'}</code>,{' '}
    <code>{'{{ vars.name }}'}</code> or <code>{'{{ item.col }}'}</code>
  </>
);

function asString(v: unknown): string {
  return typeof v === 'string' ? v : v == null ? '' : String(v);
}
function asNumber(v: unknown): number | '' {
  return typeof v === 'number' && Number.isFinite(v) ? v : '';
}

export interface ParamFieldProps {
  def: ParamDef;
  value: unknown;
  onChange: (value: unknown) => void;
  /** current node type, for special-casing (loop source) */
  nodeType: string;
  /** sibling param values of the same node (e.g. threshold for test-match) */
  siblingParams: Record<string, unknown>;
  /** nodes of the workflow, for the loop source picker */
  workflowNodes: { id: string; type: string; name: string }[];
  backendOnline: boolean;
  onPickRegion: (apply: (r: Region) => void) => void;
  onNewTemplate: (apply: (name: string) => void) => void;
}

export function ParamField(props: ParamFieldProps) {
  const { def, value, onChange } = props;

  // Special case: control.loop "source" -> dropdown of input.data_table nodes
  if (props.nodeType === 'control.loop' && def.name === 'source') {
    const tables = props.workflowNodes.filter((n) => n.type === 'input.data_table');
    const current = asString(value);
    const currentNode = tables.find((t) => t.id === current);
    return (
      <div className="field">
        <label>{def.label}</label>
        <select className="select" value={current} onChange={(e) => onChange(e.target.value || undefined)}>
          <option value="">— none —</option>
          {tables.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} ({t.id})
            </option>
          ))}
        </select>
        <div className="hint">
          {currentNode
            ? `This loop works through the rows of "${currentNode.name}".`
            : 'Add a Data Table step to repeat once per row.'}
        </div>
      </div>
    );
  }

  switch (def.kind) {
    case 'number':
      return (
        <div className="field">
          <label>{def.label}</label>
          <input
            className="input"
            type="number"
            value={asNumber(value)}
            min={def.min}
            max={def.max}
            step={def.step}
            onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
          />
          {def.help && <div className="hint">{def.help}</div>}
        </div>
      );

    case 'boolean':
      return (
        <div className="field">
          <div className="row">
            <button
              type="button"
              className={`toggle${value === true ? ' on' : ''}`}
              onClick={() => onChange(value !== true)}
              aria-label={def.label}
            />
            <span style={{ fontSize: 12.5 }}>{def.label}</span>
          </div>
        </div>
      );

    case 'select':
      return (
        <div className="field">
          <label>{def.label}</label>
          <select className="select" value={asString(value)} onChange={(e) => onChange(e.target.value)}>
            {!def.required && <option value="">—</option>}
            {(def.options ?? []).map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      );

    case 'text':
      return (
        <div className="field">
          <label>{def.label}</label>
          <textarea className="textarea" value={asString(value)} onChange={(e) => onChange(e.target.value)} rows={3} />
          <div className="hint">{TEMPLATE_HINT}</div>
        </div>
      );

    case 'code':
      return (
        <div className="field">
          <label>{def.label}</label>
          <textarea
            className="textarea code"
            value={asString(value)}
            onChange={(e) => onChange(e.target.value)}
            rows={8}
            spellCheck={false}
            placeholder={def.placeholder}
          />
          <div className="hint">Runs with a ctx object; assign the result. {TEMPLATE_HINT}</div>
        </div>
      );

    case 'keys':
      return <KeysField def={def} value={value} onChange={onChange} />;

    case 'csv':
      return <CsvField def={def} value={value} onChange={onChange} />;

    case 'region':
      return <RegionField {...props} />;

    case 'point':
      return <PointField def={def} value={value} onChange={onChange} />;

    case 'template':
      return <TemplateField {...props} />;

    case 'string':
    default:
      return (
        <div className="field">
          <label>{def.label}</label>
          <input
            className="input"
            value={asString(value)}
            placeholder={def.placeholder}
            onChange={(e) => onChange(e.target.value)}
          />
          <div className="hint">{def.help ?? TEMPLATE_HINT}</div>
        </div>
      );
  }
}

// ---- keys (hotkey recorder-ish) ----

function KeysField({ def, value, onChange }: { def: ParamDef; value: unknown; onChange: (v: unknown) => void }) {
  const [manual, setManual] = useState(false);
  return (
    <div className="field">
      <label>{def.label}</label>
      <div className="row">
        <input
          className="input"
          value={asString(value)}
          placeholder={def.placeholder ?? 'click, then press keys'}
          readOnly={!manual}
          onChange={(e) => manual && onChange(e.target.value)}
          onKeyDown={(e) => {
            if (manual) return;
            e.preventDefault();
            const key = e.key.toLowerCase();
            if (['control', 'shift', 'alt', 'meta'].includes(key)) return;
            const parts: string[] = [];
            if (e.ctrlKey) parts.push('ctrl');
            if (e.altKey) parts.push('alt');
            if (e.shiftKey) parts.push('shift');
            if (e.metaKey) parts.push('win');
            parts.push(key === ' ' ? 'space' : key);
            onChange(parts.join('+'));
          }}
        />
        <button type="button" className="btn small" onClick={() => setManual((m) => !m)} title="Toggle manual typing">
          abc
        </button>
      </div>
      <div className="hint">Click the box and press the keys (like Ctrl+S), or tap abc to type them.</div>
    </div>
  );
}

// ---- csv ----

function CsvField({ def, value, onChange }: { def: ParamDef; value: unknown; onChange: (v: unknown) => void }) {
  const text = asString(value);
  const table = text.trim() ? parseCsv(text) : null;
  return (
    <div className="field">
      <label>{def.label}</label>
      <textarea
        className="textarea code"
        value={text}
        onChange={(e) => onChange(e.target.value)}
        rows={5}
        spellCheck={false}
        placeholder={'name,url\nAcme,https://…'}
      />
      {def.help && <div className="hint">{def.help}</div>}
      {table && table.header.length > 0 && (
        <div className="csv-preview">
          <table>
            <thead>
              <tr>
                {table.header.map((h, i) => (
                  <th key={i}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((r, i) => (
                <tr key={i}>
                  {table.header.map((_, j) => (
                    <td key={j}>{r[j] ?? ''}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {table && table.rows.length > 0 && (
        <div className="hint">
          {table.rows.length} row{table.rows.length === 1 ? '' : 's'} · columns:{' '}
          {table.header.map((h) => `{{ item.${h} }}`).join('  ')}
        </div>
      )}
    </div>
  );
}

// ---- region ----

function RegionField({ def, value, onChange, onPickRegion, backendOnline }: ParamFieldProps) {
  const r = (value ?? {}) as Partial<Region>;
  const setPart = (k: keyof Region, v: number | '') => {
    const next: Partial<Region> = { ...r, [k]: v === '' ? undefined : v };
    const complete = next.x != null && next.y != null && next.w != null && next.h != null;
    onChange(complete ? (next as Region) : undefined);
  };
  return (
    <div className="field">
      <label>{def.label}</label>
      <div className="inline-grid-4">
        {(['x', 'y', 'w', 'h'] as const).map((k) => (
          <input
            key={k}
            className="input"
            type="number"
            placeholder={k}
            title={k}
            value={r[k] ?? ''}
            onChange={(e) => setPart(k, e.target.value === '' ? '' : Number(e.target.value))}
          />
        ))}
      </div>
      <div className="row" style={{ marginTop: 6 }}>
        <button
          type="button"
          className="btn small"
          disabled={!backendOnline}
          title={backendOnline ? 'Choose the area on a live screenshot' : 'Backend is offline'}
          onClick={() => onPickRegion((region) => onChange(region))}
        >
          Pick an area on screen
        </button>
        {r.x != null && (
          <button type="button" className="btn small" onClick={() => onChange(undefined)}>
            Clear
          </button>
        )}
      </div>
    </div>
  );
}

// ---- point ----

function PointField({ def, value, onChange }: { def: ParamDef; value: unknown; onChange: (v: unknown) => void }) {
  const p = (value ?? {}) as Partial<Point>;
  const setPart = (k: keyof Point, v: number | '') => {
    const next: Partial<Point> = { ...p, [k]: v === '' ? undefined : v };
    onChange(next.x != null && next.y != null ? (next as Point) : undefined);
  };
  return (
    <div className="field">
      <label>{def.label}</label>
      <div className="inline-grid">
        <input
          className="input"
          type="number"
          placeholder="x"
          value={p.x ?? ''}
          onChange={(e) => setPart('x', e.target.value === '' ? '' : Number(e.target.value))}
        />
        <input
          className="input"
          type="number"
          placeholder="y"
          value={p.y ?? ''}
          onChange={(e) => setPart('y', e.target.value === '' ? '' : Number(e.target.value))}
        />
      </div>
    </div>
  );
}

// ---- template ----

function TemplateField({ def, value, onChange, siblingParams, backendOnline, onNewTemplate }: ParamFieldProps) {
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [match, setMatch] = useState<MatchResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  const name = asString(value);

  useEffect(() => {
    if (!backendOnline) return;
    listTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]));
  }, [backendOnline]);

  const threshold = typeof siblingParams.threshold === 'number' ? siblingParams.threshold : undefined;
  const region = siblingParams.region as Region | undefined;

  const runTest = async () => {
    if (!name) return;
    setTesting(true);
    setTestError(null);
    setMatch(null);
    try {
      setMatch(await testMatch(name, threshold, region));
    } catch (e) {
      setTestError(e instanceof Error ? e.message : 'test-match failed');
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="field">
      <label>{def.label}</label>
      <div className="row">
        <select
          className="select"
          value={name}
          onChange={(e) => {
            onChange(e.target.value || undefined);
            setMatch(null);
          }}
        >
          <option value="">— choose a template —</option>
          {templates.map((t) => (
            <option key={t.name} value={t.name}>
              {t.name} ({t.width}×{t.height})
            </option>
          ))}
          {name && !templates.some((t) => t.name === name) && <option value={name}>{name} (missing)</option>}
        </select>
      </div>
      {name && (
        <div className="template-preview">
          <img src={templateUrl(name)} alt={name} onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')} />
        </div>
      )}
      <div className="row" style={{ marginTop: 6 }}>
        <button
          type="button"
          className="btn small"
          disabled={!backendOnline}
          title={backendOnline ? 'Cut a new template out of a screenshot' : 'Backend is offline'}
          onClick={() => onNewTemplate((saved) => onChange(saved))}
        >
          Create from screen
        </button>
        <button type="button" className="btn small" disabled={!backendOnline || !name || testing} onClick={runTest}>
          {testing ? 'Looking…' : 'Try it now'}
        </button>
      </div>
      {testError && <div className="match-result miss">{testError}</div>}
      {match && (
        <div className={`match-result ${match.found ? 'found' : 'miss'}`}>
          {match.found
            ? `Found it!  match ${(match.score * 100).toFixed(0)}%  at (${match.x}, ${match.y})  ${match.w}×${match.h}  ${match.elapsed_ms} ms`
            : `Not on screen right now  (closest match ${(match.score * 100).toFixed(0)}%)  ${match.elapsed_ms} ms`}
        </div>
      )}
    </div>
  );
}
