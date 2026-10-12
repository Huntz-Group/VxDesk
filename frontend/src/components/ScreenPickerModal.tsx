// Screenshot picker: captures the screen via POST /api/capture/screenshot,
// lets the user rubber-band a region, then either reports the region
// (real screen coordinates) or crops it client-side and uploads it as a
// named template asset.

import { useCallback, useEffect, useRef, useState } from 'react';
import { captureScreenshot, uploadTemplate } from '../api';
import type { Region } from '../types';

interface Props {
  mode: 'region' | 'template';
  onRegion: (region: Region) => void;
  onTemplateSaved: (name: string) => void;
  onClose: () => void;
}

interface DragState {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export function ScreenPickerModal({ mode, onRegion, onTemplateSaved, onClose }: Props) {
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const [dragging, setDragging] = useState(false);
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let url: string | null = null;
    captureScreenshot()
      .then((blob) => {
        url = URL.createObjectURL(blob);
        setImgUrl(url);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'screenshot failed'));
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, []);

  /** display coords -> real screen px (image natural size vs rendered size) */
  const toReal = useCallback((dx: number, dy: number): { x: number; y: number } => {
    const img = imgRef.current;
    if (!img) return { x: Math.round(dx), y: Math.round(dy) };
    const rect = img.getBoundingClientRect();
    const scaleX = img.naturalWidth / rect.width;
    const scaleY = img.naturalHeight / rect.height;
    return { x: Math.round(dx * scaleX), y: Math.round(dy * scaleY) };
  }, []);

  const localPos = (ev: React.PointerEvent): { x: number; y: number } => {
    const stage = stageRef.current;
    if (!stage) return { x: 0, y: 0 };
    const r = stage.getBoundingClientRect();
    return {
      x: Math.min(Math.max(ev.clientX - r.left, 0), r.width),
      y: Math.min(Math.max(ev.clientY - r.top, 0), r.height),
    };
  };

  const onPointerDown = (ev: React.PointerEvent) => {
    if (!imgUrl) return;
    const p = localPos(ev);
    setDrag({ x0: p.x, y0: p.y, x1: p.x, y1: p.y });
    setDragging(true);
    (ev.target as Element).setPointerCapture?.(ev.pointerId);
  };
  const onPointerMove = (ev: React.PointerEvent) => {
    if (!dragging) return;
    const p = localPos(ev);
    setDrag((d) => (d ? { ...d, x1: p.x, y1: p.y } : d));
  };
  const onPointerUp = () => setDragging(false);

  const norm = drag
    ? {
        left: Math.min(drag.x0, drag.x1),
        top: Math.min(drag.y0, drag.y1),
        width: Math.abs(drag.x1 - drag.x0),
        height: Math.abs(drag.y1 - drag.y0),
      }
    : null;

  const realRegion = (): Region | null => {
    if (!norm || norm.width < 3 || norm.height < 3) return null;
    const a = toReal(norm.left, norm.top);
    const b = toReal(norm.left + norm.width, norm.top + norm.height);
    return { x: a.x, y: a.y, w: Math.max(1, b.x - a.x), h: Math.max(1, b.y - a.y) };
  };

  const confirmRegion = () => {
    const r = realRegion();
    if (r) onRegion(r);
  };

  const saveTemplate = async () => {
    const r = realRegion();
    const img = imgRef.current;
    const tplName = name.trim();
    if (!r || !img || !tplName) return;
    setSaving(true);
    setError(null);
    try {
      const canvas = document.createElement('canvas');
      canvas.width = r.w;
      canvas.height = r.h;
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('no 2d context');
      ctx.drawImage(img, r.x, r.y, r.w, r.h, 0, 0, r.w, r.h);
      const blob = await new Promise<Blob>((resolve, reject) =>
        canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('crop failed'))), 'image/png'),
      );
      const saved = await uploadTemplate(tplName, blob);
      onTemplateSaved(saved.name);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'upload failed');
      setSaving(false);
    }
  };

  const sel = realRegion();

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-head">
          <span>{mode === 'region' ? 'Pick an area on your screen' : 'Create a template from your screen'}</span>
          <button className="btn small" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="modal-body">
          {error && <div className="error-text" style={{ marginBottom: 8 }}>{error}</div>}
          {!imgUrl && !error && <div className="muted">Taking a screenshot…</div>}
          {imgUrl && (
            <>
              <div
                className="picker-stage"
                ref={stageRef}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
              >
                <img ref={imgRef} src={imgUrl} alt="screen" draggable={false} />
                {norm && norm.width > 0 && norm.height > 0 && (
                  <div
                    className="picker-rect"
                    style={{ left: norm.left, top: norm.top, width: norm.width, height: norm.height }}
                  />
                )}
              </div>
              <div className="picker-info">
                {sel
                  ? `area  x:${sel.x}  y:${sel.y}  w:${sel.w}  h:${sel.h}`
                  : 'Drag across the screenshot to mark an area'}
              </div>
            </>
          )}
          {mode === 'template' && imgUrl && (
            <div className="field" style={{ marginTop: 10, maxWidth: 320 }}>
              <label>Template name</label>
              <input
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="ok-button"
              />
            </div>
          )}
        </div>
        <div className="modal-foot">
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          {mode === 'region' ? (
            <button className="btn primary" disabled={!sel} onClick={confirmRegion}>
              Use this area
            </button>
          ) : (
            <button className="btn primary" disabled={!sel || !name.trim() || saving} onClick={saveTemplate}>
              {saving ? 'Saving…' : 'Save as template'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
