// Recorder chrome: the ● Record header button, the floating recording bar,
// the inline stopped note and small toasts. Mounted once, works on both pages.

import { RecordDot } from '../icons';
import { formatClock } from '../lib/recorder';
import { useRecorderStore } from '../recorderStore';

/** Header pill: ● Record. Active (rose tint, pulsing dot) while recording. */
export function RecordButton() {
  const phase = useRecorderStore((s) => s.phase);
  const start = useRecorderStore((s) => s.start);
  const recording = phase === 'recording' || phase === 'starting';

  return (
    <button
      className={`btn small rec-toggle${recording ? ' active' : ''}`}
      onClick={() => void start()}
      disabled={recording}
      title={recording ? 'Recording in progress' : 'Record your clicks and typing into a workflow'}
    >
      <span className={recording ? 'rec-dot-pulse' : undefined} style={{ display: 'inline-flex' }}>
        <RecordDot />
      </span>
      {recording ? 'Recording…' : 'Record'}
    </button>
  );
}

/** Floating bottom-center bar shown while recording + stopped note + toasts. */
export function RecorderBar() {
  const phase = useRecorderStore((s) => s.phase);
  const eventCount = useRecorderStore((s) => s.eventCount);
  const elapsedS = useRecorderStore((s) => s.elapsedS);
  const note = useRecorderStore((s) => s.note);
  const toast = useRecorderStore((s) => s.toast);
  const stop = useRecorderStore((s) => s.stop);
  const cancel = useRecorderStore((s) => s.cancel);
  const dismissNote = useRecorderStore((s) => s.dismissNote);

  return (
    <>
      {phase === 'recording' && (
        <div className="rec-bar">
          <span className="rec-bar-status">
            <span className="rec-dot-pulse" style={{ display: 'inline-flex' }}>
              <RecordDot />
            </span>
            Recording… {formatClock(elapsedS)} · {eventCount} action{eventCount === 1 ? '' : 's'} captured
          </span>
          <span className="rec-bar-caption">
            Everything you type is recorded — avoid passwords. Press Esc or Stop to finish.
          </span>
          <span className="rec-bar-actions">
            <button className="btn small primary" onClick={() => void stop()}>
              Stop
            </button>
            <button className="btn small text" onClick={() => void cancel()}>
              Cancel
            </button>
          </span>
        </div>
      )}
      {phase === 'stopped_note' && note && (
        <div className="rec-bar note">
          <span className="rec-bar-status">{note}</span>
          <button className="btn small text" onClick={dismissNote}>
            OK
          </button>
        </div>
      )}
      {toast && <div className={`flo-toast ${toast.kind}`}>{toast.text}</div>}
    </>
  );
}
