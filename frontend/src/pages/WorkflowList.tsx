import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import {
  createWorkflow,
  deleteWorkflow,
  getWorkflow,
  listWorkflows,
  saveWorkflow,
} from '../api';
import { Blobs } from '../components/Blobs';
import { useAppStore } from '../store';
import type { WorkflowSummary } from '../types';

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return iso;
  }
}

export function WorkflowListPage() {
  const navigate = useNavigate();
  const backend = useAppStore((s) => s.backend);
  const workflowsVersion = useAppStore((s) => s.workflowsVersion);
  const [items, setItems] = useState<WorkflowSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(() => {
    setError(null);
    listWorkflows()
      .then(setItems)
      .catch((e: unknown) => {
        setItems(null);
        setError(e instanceof Error ? e.message : 'failed to load workflows');
      });
  }, []);

  useEffect(() => {
    if (backend === 'online') reload();
    else if (backend === 'offline') {
      setItems(null);
      setError(null);
    }
  }, [backend, reload, workflowsVersion]);

  const create = async () => {
    setBusy(true);
    try {
      const wf = await createWorkflow('Untitled workflow');
      navigate(`/workflow/${encodeURIComponent(wf.id)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'create failed');
      setBusy(false);
    }
  };

  const rename = async (wf: WorkflowSummary) => {
    const name = window.prompt('Give this workflow a new name', wf.name);
    if (!name || name === wf.name) return;
    try {
      const full = await getWorkflow(wf.id);
      await saveWorkflow({ ...full, name });
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'rename failed');
    }
  };

  const duplicate = async (wf: WorkflowSummary) => {
    try {
      const full = await getWorkflow(wf.id);
      const copy = await createWorkflow(`${wf.name} (copy)`, full.description);
      await saveWorkflow({ ...copy, nodes: full.nodes, edges: full.edges, variables: full.variables });
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'duplicate failed');
    }
  };

  const remove = async (wf: WorkflowSummary) => {
    if (!window.confirm(`Delete "${wf.name}" for good? This can't be undone.`)) return;
    try {
      await deleteWorkflow(wf.id);
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'delete failed');
    }
  };

  return (
    <div className="list-page">
      <div className="list-hero">
        <Blobs variant="hero" />
        <h1 className="wordmark">VxDesk</h1>
        <div className="tagline">Teach your computer to do the boring parts.</div>
        <button className="btn primary hero-cta" disabled={backend !== 'online' || busy} onClick={() => void create()}>
          {busy ? 'Creating…' : '+ New workflow'}
        </button>
      </div>

      <div className="list-body">
        {backend === 'offline' && (
          <div className="empty-state">
            Your workflows live on the backend, which is offline right now. Start it and press “Try again” above.
          </div>
        )}
        {error && <div className="error-text" style={{ marginBottom: 12 }}>{error}</div>}
        {backend !== 'offline' && items === null && !error && <div className="muted">Loading your workflows…</div>}

        {items && items.length === 0 && (
          <div className="empty-state">Nothing here yet — create your first workflow.</div>
        )}

        {items && items.length > 0 && (
          <div className="wf-grid">
            {items.map((wf) => (
              <div className="wf-card" key={wf.id}>
                <div className="wf-name" onClick={() => navigate(`/workflow/${encodeURIComponent(wf.id)}`)}>
                  {wf.name}
                </div>
                <div className="wf-desc">{wf.description || 'A desktop automation.'}</div>
                <div className="wf-meta">
                  <span className="chip-pastel">
                    {wf.node_count} step{wf.node_count === 1 ? '' : 's'}
                  </span>
                  <span className="wf-date">Updated {fmtTime(wf.updated_at)}</span>
                </div>
                <div className="wf-actions">
                  <button className="btn small primary" onClick={() => navigate(`/workflow/${encodeURIComponent(wf.id)}`)}>
                    Open
                  </button>
                  <span className="grow" />
                  <button className="btn text small" onClick={() => void rename(wf)}>
                    Rename
                  </button>
                  <button className="btn text small" onClick={() => void duplicate(wf)}>
                    Duplicate
                  </button>
                  <button className="btn text small danger" onClick={() => void remove(wf)}>
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
