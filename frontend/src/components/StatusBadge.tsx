import { useEffect } from 'react';
import { useAppStore } from '../store';

/** Friendly status pill in the top bar; polls /api/system/info. */
export function StatusBadge() {
  const backend = useAppStore((s) => s.backend);
  const info = useAppStore((s) => s.systemInfo);
  const refreshSystem = useAppStore((s) => s.refreshSystem);

  useEffect(() => {
    void refreshSystem();
    const t = setInterval(() => void refreshSystem(), 15000);
    return () => clearInterval(t);
  }, [refreshSystem]);

  if (backend === 'offline') {
    return (
      <span className="status-badge offline" title="Can't reach the VxDesk backend at 127.0.0.1:8765">
        <span className="dot" />
        Backend offline
      </span>
    );
  }
  if (!info) {
    return (
      <span className="status-badge" title="Checking the backend…">
        <span className="dot" />
        Checking…
      </span>
    );
  }
  const gpuOn = info.capture.gpu && info.ocr.available && info.ocr.gpu;
  const title = [
    `VxDesk ${info.version} · ${info.os} · Python ${info.python}`,
    `Capture: ${info.capture.backend}${info.capture.gpu ? ' (GPU)' : ' (CPU)'}`,
    `Text recognition: ${info.ocr.available ? `${info.ocr.backend} · ${info.ocr.gpu ? 'GPU' : 'CPU'}` : 'unavailable'}`,
    `Graphics: ${info.gpu.name}`,
    `Screens: ${info.screens.map((s) => `${s.width}×${s.height}`).join(', ')}`,
  ].join('\n');
  return (
    <span className={`status-badge ${gpuOn ? 'online' : 'degraded'}`} title={title}>
      <span className="dot" />
      {gpuOn ? 'Ready · GPU on' : 'Ready'}
    </span>
  );
}

export function OfflineBanner() {
  const backend = useAppStore((s) => s.backend);
  const refreshSystem = useAppStore((s) => s.refreshSystem);
  const loadCatalog = useAppStore((s) => s.loadCatalog);
  if (backend !== 'offline') return null;
  return (
    <div className="offline-banner">
      <span>
        <b>We can't reach the VxDesk backend.</b> Start it on 127.0.0.1:8765 — until then you can look around, but
        saving and running are paused.
      </span>
      <span className="grow" />
      <button
        className="btn small"
        onClick={() => {
          void refreshSystem();
          void loadCatalog();
        }}
      >
        Try again
      </button>
    </div>
  );
}
