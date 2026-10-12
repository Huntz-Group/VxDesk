// AI settings dialog: provider preset, base_url, model, write-only API key,
// plus a live status line from GET /api/ai/status.

import { useEffect, useState } from 'react';
import { getAiSettings, putAiSettings } from '../api';
import { useAssistantStore } from '../assistantStore';
import type { AiPreset, AiSettings } from '../types';

function StatusLine() {
  const status = useAssistantStore((s) => s.status);
  if (!status) {
    return (
      <div className="ai-status-line">
        <span className="dot beige" />
        Can't check right now — backend offline?
      </div>
    );
  }
  if (!status.configured) {
    return (
      <div className="ai-status-line">
        <span className="dot beige" />
        Not set up yet
      </div>
    );
  }
  if (status.reachable) {
    return (
      <div className="ai-status-line ok">
        <span className="dot sage" />
        Connected{status.model ? ` · ${status.model}` : ''}
      </div>
    );
  }
  return (
    <div className="ai-status-line bad">
      <span className="dot rose" />
      Can't reach the model — is it running?
    </div>
  );
}

export function AiSettingsDialog() {
  const setSettingsOpen = useAssistantStore((s) => s.setSettingsOpen);
  const refreshStatus = useAssistantStore((s) => s.refreshStatus);

  const [settings, setSettings] = useState<AiSettings | null>(null);
  const [provider, setProvider] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedOk, setSavedOk] = useState(false);

  useEffect(() => {
    getAiSettings()
      .then((s) => {
        setSettings(s);
        setProvider(s.provider || s.presets[0]?.id || 'custom');
        setBaseUrl(s.base_url);
        setModel(s.model);
      })
      .catch((e: unknown) => setLoadError(e instanceof Error ? e.message : 'failed to load settings'));
    void refreshStatus();
  }, [refreshStatus]);

  const applyPreset = (id: string) => {
    setProvider(id);
    const preset: AiPreset | undefined = settings?.presets.find((p) => p.id === id);
    if (preset) {
      setBaseUrl(preset.base_url);
      setModel(preset.model_hint);
    }
  };

  const needsKey = settings?.presets.find((p) => p.id === provider)?.needs_key ?? true;

  const save = async () => {
    setSaving(true);
    setSavedOk(false);
    setLoadError(null);
    try {
      const body: { provider: string; base_url: string; model: string; api_key?: string } = {
        provider,
        base_url: baseUrl.trim(),
        model: model.trim(),
      };
      if (apiKey.trim()) body.api_key = apiKey.trim();
      const s = await putAiSettings(body);
      setSettings(s);
      setApiKey('');
      setSavedOk(true);
      await refreshStatus();
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'save failed');
    } finally {
      setSaving(false);
    }
  };

  const close = () => setSettingsOpen(false);

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className="modal" style={{ width: 420 }}>
        <div className="modal-head">
          <span>Assistant settings</span>
          <button className="btn small" onClick={close}>
            Close
          </button>
        </div>
        <div className="modal-body">
          {loadError && <div className="error-text" style={{ marginBottom: 10 }}>{loadError}</div>}
          {!settings && !loadError && <div className="muted">Loading…</div>}
          {settings && (
            <>
              <StatusLine />
              <div className="field" style={{ marginTop: 14 }}>
                <label>Provider</label>
                <select className="select" value={provider} onChange={(e) => applyPreset(e.target.value)}>
                  {settings.presets.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>Base URL</label>
                <input
                  className="input"
                  value={baseUrl}
                  placeholder="http://localhost:11434/v1"
                  onChange={(e) => setBaseUrl(e.target.value)}
                />
              </div>
              <div className="field">
                <label>Model</label>
                <input
                  className="input"
                  value={model}
                  placeholder="qwen2.5:7b"
                  onChange={(e) => setModel(e.target.value)}
                />
              </div>
              <div className="field">
                <label>API key {settings.has_api_key && <span className="ai-key-saved">Saved ✓</span>}</label>
                <input
                  className="input"
                  type="password"
                  value={apiKey}
                  placeholder="Only needed for some providers — stored locally, never shown"
                  onChange={(e) => setApiKey(e.target.value)}
                />
                {!needsKey && <div className="hint">This provider usually runs without a key.</div>}
              </div>
            </>
          )}
        </div>
        <div className="modal-foot">
          {savedOk && <span className="muted" style={{ alignSelf: 'center' }}>Saved — nice.</span>}
          <span className="grow" />
          <button className="btn" onClick={close}>
            Cancel
          </button>
          <button className="btn primary" disabled={!settings || saving || !baseUrl.trim() || !model.trim()} onClick={() => void save()}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
