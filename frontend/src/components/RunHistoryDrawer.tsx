// Run history drawer: past runs of the current workflow; clicking one loads
// its node_states onto the canvas in read-only replay mode.

import { useEffect, useState } from 'react';
import { getRun, listRuns } from '../api';
import { useEditorStore } from '../editorStore';
import type { RunSummary } from '../types';

interface Props {
  workflowId: string;
  onClose: () => void;
}

function fmtTime(iso?: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function RunHistoryDrawer({ workflowId, onClose }: Props) {
  const loadReplay = useEditorStore((s) => s.loadReplay);
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listRuns(workflowId)
      .then(setRuns)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'failed to load runs'));
  }, [workflowId]);

  const openRun = async (runId: string) => {
    try {
      const detail = await getRun(runId);
      loadReplay(detail.run_id, detail.status, detail.node_states ?? {});
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed to load run');
    }
  };

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <div className="drawer">
        <div className="drawer-head">
          <span>Past runs</span>
          <button className="btn small" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="drawer-body">
          {error && <div className="error-text" style={{ padding: 8 }}>{error}</div>}
          {!runs && !error && <div className="muted" style={{ padding: 8 }}>Loading…</div>}
          {runs && runs.length === 0 && <div className="muted" style={{ padding: 8 }}>No runs yet — press Run to make one.</div>}
          {runs?.map((r) => (
            <div className="run-item" key={r.run_id} onClick={() => void openRun(r.run_id)}>
              <span className={`chip ${r.status}`} style={{ fontSize: 10, padding: '1px 8px' }}>
                {r.status}
              </span>
              <div className="meta">
                <div className="id">{r.run_id}</div>
                <div className="time">
                  {fmtTime(r.started_at)}
                  {r.error ? ` — ${r.error}` : ''}
                </div>
              </div>
            </div>
          ))}
          {runs && runs.length > 0 && (
            <div className="muted" style={{ padding: 8, fontSize: 11.5 }}>
              Click a run to see how each step did — the canvas shows its results read-only.
            </div>
          )}
        </div>
      </div>
    </>
  );
}
