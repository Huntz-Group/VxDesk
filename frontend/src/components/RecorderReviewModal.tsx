// Review modal shown after Stop: step preview, name, smart/exact choice,
// create-or-discard.

import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { NodeIcon } from '../icons';
import { defaultRecordingName, describePreviewStep, formatSeconds } from '../lib/recorder';
import { useRecorderStore } from '../recorderStore';
import { useAppStore } from '../store';
import type { RecorderMode } from '../types';

export function RecorderReviewModal() {
  const phase = useRecorderStore((s) => s.phase);
  const review = useRecorderStore((s) => s.review);
  const converting = useRecorderStore((s) => s.converting);
  const convertError = useRecorderStore((s) => s.convertError);
  const convert = useRecorderStore((s) => s.convert);
  const discardReview = useRecorderStore((s) => s.discardReview);
  const catalog = useAppStore((s) => s.catalog);
  const navigate = useNavigate();

  const [name, setName] = useState(() => defaultRecordingName(new Date()));
  const [mode, setMode] = useState<RecorderMode>('smart');

  // fresh defaults each time a new recording arrives for review
  const reviewSession = review?.session_id;
  useEffect(() => {
    if (reviewSession) {
      setName(defaultRecordingName(new Date()));
      setMode('smart');
    }
  }, [reviewSession]);

  const steps = useMemo(
    () => (review?.step_preview ?? []).map((step, i) => describePreviewStep(step, i, catalog)),
    [review, catalog],
  );

  if (phase !== 'reviewing' || !review) return null;

  const create = async () => {
    const wf = await convert(name.trim() || defaultRecordingName(new Date()), mode);
    if (wf) navigate(`/workflow/${encodeURIComponent(wf.id)}`);
  };

  return (
    <div className="modal-backdrop">
      <div className="modal" style={{ width: 520 }}>
        <div className="modal-head">
          <span>Your recording</span>
          <span className="muted" style={{ fontFamily: 'var(--sans)', fontWeight: 400, fontSize: 12.5 }}>
            {steps.length} step{steps.length === 1 ? '' : 's'} · {formatSeconds(review.duration_s)}
          </span>
        </div>
        <div className="modal-body">
          {steps.length === 0 ? (
            <div className="empty-state" style={{ marginBottom: 14 }}>
              Nothing was captured — try recording again and do a few clicks first.
            </div>
          ) : (
            <div className="rec-steps">
              {steps.map((s, i) => (
                <div className="rec-step" key={i}>
                  <span className="rec-step-index">{i + 1}</span>
                  <span className="rec-step-icon" style={{ background: s.color }}>
                    <NodeIcon name={s.icon} size={13} />
                  </span>
                  <span className="rec-step-label" title={s.label}>
                    {s.label}
                  </span>
                </div>
              ))}
            </div>
          )}

          <div className="field" style={{ marginTop: 14 }}>
            <label>Name</label>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </div>

          <div className="rec-modes">
            <button
              type="button"
              className={`rec-mode${mode === 'smart' ? ' active' : ''}`}
              onClick={() => setMode('smart')}
            >
              <span className="rec-mode-title">Smart (recommended)</span>
              <span className="rec-mode-desc">
                Find buttons and text on screen next time, so it still works if things move a little.
              </span>
              {mode === 'smart' && (
                <span className="rec-mode-note">Tune a step's threshold later if it can't find its target.</span>
              )}
            </button>
            <button
              type="button"
              className={`rec-mode${mode === 'coordinates' ? ' active' : ''}`}
              onClick={() => setMode('coordinates')}
            >
              <span className="rec-mode-title">Exact positions</span>
              <span className="rec-mode-desc">Replay the exact clicks. Fastest, but breaks if the window moves.</span>
            </button>
          </div>

          {convertError && <div className="rec-error">{convertError}</div>}
        </div>
        <div className="modal-foot">
          <button className="btn text" onClick={() => void discardReview()}>
            Discard
          </button>
          <span className="grow" />
          <button className="btn primary" disabled={steps.length === 0 || converting} onClick={() => void create()}>
            {converting ? 'Creating…' : 'Create workflow'}
          </button>
        </div>
      </div>
    </div>
  );
}
