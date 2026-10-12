// Pure helpers for the Recorder UI (unit-tested).

import { CATEGORY_COLORS } from '../icons';
import type { NodeDef, RecorderStepPreview } from '../types';

/** 75 → "1:15", 9.6 → "0:09" */
export function formatClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

/** 12.37 → "12.4 seconds", 1.02 → "1.0 seconds" */
export function formatSeconds(seconds: number): string {
  return `${seconds.toFixed(1)} seconds`;
}

export interface PreviewDisplay {
  icon: string;
  /** pastel fill color for the icon chip */
  color: string;
  label: string;
}

interface KindStyle {
  icon: string;
  category: string;
}

/** Fallback styling when the preview item only carries an event kind. */
const KIND_STYLES: Record<string, KindStyle> = {
  click: { icon: 'cursor', category: 'action' },
  char: { icon: 'keyboard', category: 'action' },
  type: { icon: 'keyboard', category: 'action' },
  key: { icon: 'key', category: 'action' },
  wait: { icon: 'clock', category: 'control' },
  window: { icon: 'window', category: 'action' },
  focus: { icon: 'window', category: 'action' },
  find_image: { icon: 'image', category: 'vision' },
  vision: { icon: 'image', category: 'vision' },
  screenshot: { icon: 'camera', category: 'capture' },
};

/**
 * Map one step_preview item to icon/color/label for the review list.
 * Prefers the engine node type (looked up in the catalog), falls back to the
 * recorded event kind, then to a generic chip.
 */
export function describePreviewStep(
  step: RecorderStepPreview,
  index: number,
  catalog: NodeDef[],
): PreviewDisplay {
  const label = step.name ?? step.summary ?? `Step ${index + 1}`;

  if (step.type) {
    const def = catalog.find((d) => d.type === step.type);
    if (def) {
      return {
        icon: def.icon,
        color: CATEGORY_COLORS[def.category] ?? CATEGORY_COLORS.unknown,
        label,
      };
    }
    // unknown type — style by its category prefix if recognizable
    const cat = step.type.split('.')[0];
    if (cat && CATEGORY_COLORS[cat]) {
      return { icon: 'generic', color: CATEGORY_COLORS[cat], label };
    }
  }

  const kind = step.kind && KIND_STYLES[step.kind];
  if (kind) {
    return { icon: kind.icon, color: CATEGORY_COLORS[kind.category], label };
  }

  return { icon: 'generic', color: CATEGORY_COLORS.unknown, label };
}

/** Default name for the review modal's name field. */
export function defaultRecordingName(now: Date): string {
  const date = now.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
  return `Recorded workflow · ${date}`;
}
