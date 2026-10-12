// Remote page (/remote): hub status & settings, machines (agents), activity feed.
// Codes against docs/remote-services.md management REST only.

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ApiRequestError,
  createRemoteAgent,
  deleteRemoteAgent,
  getRemoteActivity,
  getRemoteStatus,
  listRemoteAgents,
  listWorkflows,
  putRemoteSettings,
  runRemoteAgent,
} from '../api';
import {
  activityStyle,
  agentLabel,
  capsSummary,
  machinesLine,
  timeAgo,
  transportStyle,
} from '../lib/remote';
import { useAppStore } from '../store';
import type {
  NewAgentResult,
  RemoteActivityItem,
  RemoteAgent,
  RemoteStatus,
  WorkflowSummary,
} from '../types';

type Toast = { kind: 'ok' | 'error'; text: string } | null;

export function RemotePage() {
  const backend = useAppStore((s) => s.backend);
  const [status, setStatus] = useState<RemoteStatus | null>(null);
  const [agents, setAgents] = useState<RemoteAgent[]>([]);
  const [activity, setActivity] = useState<RemoteActivityItem[]>([]);
  const [toast, setToast] = useState<Toast>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((kind: 'ok' | 'error', text: string) => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ kind, text });
    toastTimer.current = setTimeout(() => setToast(null), 2200);
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await getRemoteStatus());
    } catch {
      setStatus(null);
    }
  }, []);

  const loadAgents = useCallback(async () => {
    try {
      setAgents(await listRemoteAgents());
    } catch {
      setAgents([]); // disabled / offline → friendly empty state
    }
  }, []);

  const loadActivity = useCallback(async () => {
    try {
      setActivity(await getRemoteActivity(200));
    } catch {
      setActivity([]);
    }
  }, []);

  useEffect(() => {
    void loadStatus();
    void loadAgents();
  }, [loadStatus, loadAgents, backend]);

  // activity feed: poll every 3 s while the page is open
  useEffect(() => {
    void loadActivity();
    const t = setInterval(() => void loadActivity(), 3000);
    return () => clearInterval(t);
  }, [loadActivity]);

  return (
    <div className="list-page">
      <div className="list-hero" style={{ paddingBottom: 12 }}>
        <h1 className="wordmark" style={{ fontSize: 32 }}>Remote</h1>
        <div className="tagline">Let your other machines run workflows — from one place.</div>
      </div>
      <div className="list-body remote-grid">
        <SettingsCard status={status} onSaved={loadStatus} showToast={showToast} backendOnline={backend === 'online'} />
        <AgentsCard
          agents={agents}
          enabled={status?.enabled === true}
          onChanged={() => {
            void loadAgents();
            void loadStatus();
          }}
          showToast={showToast}
          backendOnline={backend === 'online'}
        />
        <ActivityCard activity={activity} agents={agents} enabled={status?.enabled === true} />
      </div>
      {toast && <div className={`flo-toast ${toast.kind}`}>{toast.text}</div>}
    </div>
  );
}

// ---------- status & settings ----------

function SettingsCard({
  status,
  onSaved,
  showToast,
  backendOnline,
}: {
  status: RemoteStatus | null;
  onSaved: () => void;
  showToast: (kind: 'ok' | 'error', text: string) => void;
  backendOnline: boolean;
}) {
  const [bind, setBind] = useState('127.0.0.1');
  const [ws, setWs] = useState(true);
  const [tcp, setTcp] = useState(true);
  const [edge, setEdge] = useState(true);
  const [tcpPort, setTcpPort] = useState(8766);
  const [cert, setCert] = useState('');
  const [key, setKey] = useState('');
  const [restartRequired, setRestartRequired] = useState(false);
  const [saving, setSaving] = useState(false);

  // hydrate the form when status first arrives
  const hydrated = useRef(false);
  useEffect(() => {
    if (!status || hydrated.current) return;
    hydrated.current = true;
    setBind(status.bind || '127.0.0.1');
    setWs(status.transports?.ws ?? true);
    setTcp(status.transports?.tcp ?? true);
    setEdge(status.transports?.edge ?? true);
    setTcpPort(status.tcp_port ?? 8766);
    setCert(status.tls?.cert ?? '');
    setKey(status.tls?.key ?? '');
    setRestartRequired(status.restart_required === true);
  }, [status]);

  const toggleEnabled = async () => {
    if (!status) return;
    try {
      const next = await putRemoteSettings({ enabled: !status.enabled });
      setRestartRequired(next.restart_required === true);
      onSaved();
      showToast('ok', next.enabled ? 'Remote access is on' : 'Remote access is off');
    } catch (e) {
      showToast('error', e instanceof Error ? e.message : "Couldn't change that");
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      const next = await putRemoteSettings({
        bind,
        transports: { ws, tcp, edge },
        tcp_port: tcpPort,
        tls: { enabled: cert.trim() !== '' && key.trim() !== '', cert: cert.trim(), key: key.trim() },
      });
      setRestartRequired(next.restart_required === true);
      onSaved();
      showToast('ok', 'Settings saved');
    } catch (e) {
      showToast('error', e instanceof Error ? e.message : "Couldn't save settings");
    } finally {
      setSaving(false);
    }
  };

  const enabled = status?.enabled === true;

  return (
    <div className="remote-card">
      <div className="remote-card-head">
        <span className="remote-card-title font-display">Remote access</span>
        <span className="grow" />
        {status && (
          <span className="muted" style={{ fontSize: 12.5 }}>
            {machinesLine(status.agents_online, status.agents_total)}
          </span>
        )}
        <button
          type="button"
          className={`toggle${enabled ? ' on' : ''}`}
          aria-label="Remote access"
          disabled={!status || !backendOnline}
          onClick={() => void toggleEnabled()}
        />
      </div>

      {!status && (
        <div className="muted" style={{ padding: '6px 0' }}>
          {backendOnline ? 'Loading settings…' : 'Remote settings are unavailable while the backend is offline.'}
        </div>
      )}

      {status && !enabled && (
        <div className="muted" style={{ padding: '6px 0' }}>
          Remote access is off. Flip the switch to let other machines connect.
        </div>
      )}

      {status && enabled && (
        <>
          <div className="field">
            <label>Who can connect</label>
            <select className="select" value={bind} onChange={(e) => setBind(e.target.value)}>
              <option value="127.0.0.1">Only this PC (safest)</option>
              <option value="0.0.0.0">Other devices on my network</option>
            </select>
            {bind === '0.0.0.0' && (
              <div className="hint" style={{ color: '#8c6d1f' }}>
                Heads up: any device on your network could try to connect — only use this on networks you trust.
              </div>
            )}
          </div>

          <div className="field">
            <label>Ways to connect</label>
            <label className="check-row">
              <input type="checkbox" checked={ws} onChange={(e) => setWs(e.target.checked)} />
              <span>
                <b>WebSocket</b> — live, instant connection. Best for most machines.
              </span>
            </label>
            <label className="check-row">
              <input type="checkbox" checked={tcp} onChange={(e) => setTcp(e.target.checked)} />
              <span>
                <b>TCP</b> — simple socket connection for tiny clients.
              </span>
            </label>
            <label className="check-row">
              <input type="checkbox" checked={edge} onChange={(e) => setEdge(e.target.checked)} />
              <span>
                <b>Edge polling</b> — plain HTTP check-ins for very old machines (even XP-era).
              </span>
            </label>
          </div>

          <div className="inline-grid">
            <div className="field">
              <label>TCP port</label>
              <input
                className="input"
                type="number"
                min={1}
                max={65535}
                value={tcpPort}
                onChange={(e) => setTcpPort(Number(e.target.value) || 8766)}
              />
            </div>
            <div />
          </div>

          <div className="props-section-title">Secure connections (TLS)</div>
          <div className="inline-grid">
            <div className="field">
              <label>Certificate path</label>
              <input className="input" value={cert} placeholder="C:\\certs\\vxdesk.crt" onChange={(e) => setCert(e.target.value)} />
            </div>
            <div className="field">
              <label>Key path</label>
              <input className="input" value={key} placeholder="C:\\certs\\vxdesk.key" onChange={(e) => setKey(e.target.value)} />
            </div>
          </div>
          <div className="hint" style={{ marginTop: -6, marginBottom: 12 }}>
            For wss:// and https:// — leave empty for local use.
          </div>

          {restartRequired && <div className="rec-note-box">Restart VxDesk to apply these changes.</div>}

          <div className="row">
            <button className="btn primary small" disabled={saving} onClick={() => void save()}>
              {saving ? 'Saving…' : 'Save settings'}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// ---------- machines (agents) ----------

function AgentsCard({
  agents,
  enabled,
  onChanged,
  showToast,
  backendOnline,
}: {
  agents: RemoteAgent[];
  enabled: boolean;
  onChanged: () => void;
  showToast: (kind: 'ok' | 'error', text: string) => void;
  backendOnline: boolean;
}) {
  const [addOpen, setAddOpen] = useState(false);
  const [runTarget, setRunTarget] = useState<RemoteAgent | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);

  const remove = async (agent: RemoteAgent) => {
    try {
      await deleteRemoteAgent(agent.agent_id);
      showToast('ok', `"${agent.name}" was removed`);
      setConfirmRemove(null);
      onChanged();
    } catch (e) {
      showToast('error', e instanceof Error ? e.message : "Couldn't remove it");
    }
  };

  return (
    <div className="remote-card">
      <div className="remote-card-head">
        <span className="remote-card-title font-display">Machines</span>
        <span className="grow" />
        <button
          className="btn small"
          disabled={!enabled || !backendOnline}
          title={enabled ? 'Register a new machine' : 'Turn on remote access first'}
          onClick={() => setAddOpen(true)}
        >
          + Add a machine
        </button>
      </div>

      {agents.length === 0 ? (
        <div className="muted" style={{ padding: '6px 0' }}>
          {enabled ? 'No machines yet — add one to get its connection details.' : 'Nothing to see while remote access is off.'}
        </div>
      ) : (
        <table className="remote-table">
          <thead>
            <tr>
              <th>Name</th>
              <th style={{ width: 70 }}>Status</th>
              <th style={{ width: 110 }}>Connects via</th>
              <th style={{ width: 100 }}>Last seen</th>
              <th style={{ width: 150 }}>Can do</th>
              <th style={{ width: 200 }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => {
              const t = transportStyle(a.transport);
              return (
                <tr key={a.agent_id}>
                  <td>
                    <div style={{ fontWeight: 700 }}>{a.name}</div>
                    {a.address && <div className="muted" style={{ fontSize: 11 }}>{a.address}</div>}
                  </td>
                  <td>
                    <span className="row" style={{ gap: 6 }}>
                      <span className={`online-dot${a.online ? ' on' : ''}`} />
                      <span className="muted" style={{ fontSize: 11.5 }}>{a.online ? 'online' : 'offline'}</span>
                    </span>
                  </td>
                  <td>
                    <span className="chip" style={{ background: t.color, color: t.textColor }}>{t.label}</span>
                  </td>
                  <td className="muted">{timeAgo(a.last_seen)}</td>
                  <td className="muted">{capsSummary(a.caps)}</td>
                  <td>
                    <div className="row" style={{ gap: 4 }}>
                      <button
                        className="btn small"
                        disabled={!a.online}
                        title={a.online ? 'Send a workflow to this machine' : 'Machine is offline'}
                        onClick={() => setRunTarget(a)}
                      >
                        Run workflow…
                      </button>
                      {confirmRemove === a.agent_id ? (
                        <>
                          <button className="btn small danger" onClick={() => void remove(a)}>
                            Sure?
                          </button>
                          <button className="btn text small" onClick={() => setConfirmRemove(null)}>
                            Keep
                          </button>
                        </>
                      ) : (
                        <button className="btn text small danger" onClick={() => setConfirmRemove(a.agent_id)}>
                          Remove
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {addOpen && (
        <AddMachineModal
          onClose={() => setAddOpen(false)}
          onCreated={() => {
            onChanged();
          }}
        />
      )}
      {runTarget && (
        <RunDialog
          agent={runTarget}
          onClose={() => setRunTarget(null)}
          showToast={showToast}
        />
      )}
    </div>
  );
}

// ---------- add machine modal (token shown ONCE) ----------

function AddMachineModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState('');
  const [created, setCreated] = useState<NewAgentResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const host = window.location.hostname;

  const copy = async (text: string, tag: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(tag);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      setCopied(null);
    }
  };

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await createRemoteAgent(name.trim() || 'New machine');
      setCreated(result);
      onCreated();
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.detail : e instanceof Error ? e.message : "Couldn't add the machine");
    } finally {
      setBusy(false);
    }
  };

  const agentCmd = created
    ? `python -m vxdesk.agent --server ws://${host}:8765 --token ${created.token} --agent-id ${created.agent_id}`
    : '';
  const edgeCmd = created
    ? `python vxdesk_edge.py   # vxdesk_edge.ini: server=http://${host}:8765, agent_id=${created.agent_id}, token=${created.token}`
    : '';

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ width: 520 }}>
        <div className="modal-head">
          <span>{created ? 'Machine added' : 'Add a machine'}</span>
          <button className="btn small" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="modal-body">
          {!created ? (
            <>
              <div className="muted" style={{ marginBottom: 12 }}>
                Give the machine a friendly name. You'll get a token to connect it with.
              </div>
              <div className="field">
                <label>Name</label>
                <input
                  className="input"
                  autoFocus
                  placeholder="Shop floor PC"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && void create()}
                />
              </div>
              {error && <div className="rec-error">{error}</div>}
            </>
          ) : (
            <>
              <div className="rec-note-box" style={{ marginBottom: 12 }}>
                Save this token — it won't be shown again.
              </div>
              <div className="field">
                <label>Token</label>
                <div className="token-box" onClick={() => void copy(created.token, 'token')} title="Click to copy">
                  {created.token}
                </div>
                <div className="hint">{copied === 'token' ? 'Copied!' : 'Click the token to copy it.'}</div>
              </div>
              <div className="field">
                <label>On that machine (full agent)</label>
                <div className="snippet-box">
                  <code>{agentCmd}</code>
                  <button className="btn small" onClick={() => void copy(agentCmd, 'agent')}>
                    {copied === 'agent' ? 'Copied ✓' : 'Copy'}
                  </button>
                </div>
              </div>
              <div className="field">
                <label>Very old machine (edge polling)</label>
                <div className="snippet-box">
                  <code>{edgeCmd}</code>
                  <button className="btn small" onClick={() => void copy(edgeCmd, 'edge')}>
                    {copied === 'edge' ? 'Copied ✓' : 'Copy'}
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
        <div className="modal-foot">
          {!created ? (
            <>
              <button className="btn" onClick={onClose}>
                Cancel
              </button>
              <button className="btn primary" disabled={busy} onClick={() => void create()}>
                {busy ? 'Adding…' : 'Add machine'}
              </button>
            </>
          ) : (
            <button className="btn primary" onClick={onClose}>
              Done
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------- run workflow dialog ----------

function RunDialog({
  agent,
  onClose,
  showToast,
}: {
  agent: RemoteAgent;
  onClose: () => void;
  showToast: (kind: 'ok' | 'error', text: string) => void;
}) {
  const [workflows, setWorkflows] = useState<WorkflowSummary[] | null>(null);
  const [workflowId, setWorkflowId] = useState('');
  const [dryRun, setDryRun] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    listWorkflows()
      .then((wfs) => {
        setWorkflows(wfs);
        if (wfs.length > 0) setWorkflowId(wfs[0].id);
      })
      .catch(() => setWorkflows([]));
  }, []);

  const send = async () => {
    if (!workflowId) return;
    setSending(true);
    setError(null);
    try {
      await runRemoteAgent(agent.agent_id, workflowId, dryRun);
      showToast('ok', `Sent to "${agent.name}" — it'll start shortly`);
      onClose();
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.detail : e instanceof Error ? e.message : "Couldn't send it");
      setSending(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ width: 420 }}>
        <div className="modal-head">
          <span>Run on “{agent.name}”</span>
          <button className="btn small" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="modal-body">
          <div className="field">
            <label>Workflow</label>
            <select className="select" value={workflowId} onChange={(e) => setWorkflowId(e.target.value)}>
              {(workflows ?? []).map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
            {workflows !== null && workflows.length === 0 && (
              <div className="hint">No workflows yet — create one first.</div>
            )}
          </div>
          <label className="check-row">
            <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
            <span>Practice mode (nothing will be clicked or typed for real)</span>
          </label>
          {error && <div className="rec-error" style={{ marginTop: 10 }}>{error}</div>}
        </div>
        <div className="modal-foot">
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" disabled={!workflowId || sending} onClick={() => void send()}>
            {sending ? 'Sending…' : 'Send to machine'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------- activity feed ----------

function ActivityCard({
  activity,
  agents,
  enabled,
}: {
  activity: RemoteActivityItem[];
  agents: RemoteAgent[];
  enabled: boolean;
}) {
  return (
    <div className="remote-card">
      <div className="remote-card-head">
        <span className="remote-card-title font-display">Activity</span>
        <span className="grow" />
        <span className="muted" style={{ fontSize: 11.5 }}>updates every few seconds</span>
      </div>
      {activity.length === 0 ? (
        <div className="muted" style={{ padding: '6px 0' }}>
          {enabled
            ? 'Nothing yet — connect a machine and its activity will show up here.'
            : 'Nothing to see while remote access is off.'}
        </div>
      ) : (
        <div className="activity-list">
          {activity.map((item, i) => {
            const style = activityStyle(item.kind, item.ok);
            return (
              <div className="activity-row" key={`${item.ts}-${i}`}>
                <span className="activity-time">{timeAgo(item.ts)}</span>
                <span className="activity-agent">{agentLabel(item.agent_id, agents)}</span>
                <span className="chip" style={{ background: style.color, color: style.textColor }}>
                  {style.label}
                </span>
                <span className="activity-msg">{item.message}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
