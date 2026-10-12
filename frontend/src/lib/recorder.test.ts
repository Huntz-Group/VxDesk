import { describe, expect, it } from 'vitest';
import { FALLBACK_CATALOG } from '../catalog-fallback';
import { describePreviewStep, formatClock, formatSeconds } from './recorder';

const catalog = FALLBACK_CATALOG.nodes;

describe('formatClock', () => {
  it('formats m:ss', () => {
    expect(formatClock(75)).toBe('1:15');
    expect(formatClock(9.6)).toBe('0:09');
    expect(formatClock(0)).toBe('0:00');
  });
});

describe('formatSeconds', () => {
  it('formats one decimal', () => {
    expect(formatSeconds(12.37)).toBe('12.4 seconds');
    expect(formatSeconds(1.02)).toBe('1.0 seconds');
  });
});

describe('describePreviewStep', () => {
  it('uses the catalog when an engine type is present', () => {
    const d = describePreviewStep({ type: 'vision.find_image', name: 'Click "Save"' }, 0, catalog);
    expect(d.icon).toBe('image');
    expect(d.label).toBe('Click "Save"');
  });

  it('falls back to kind styling for clicks, keys and waits', () => {
    expect(describePreviewStep({ kind: 'click', summary: 'Click at (450, 320)' }, 1, catalog).icon).toBe('cursor');
    expect(describePreviewStep({ kind: 'key', summary: 'Press Ctrl+S' }, 2, catalog).icon).toBe('key');
    expect(describePreviewStep({ kind: 'wait', summary: 'Wait 1.2s' }, 3, catalog).icon).toBe('clock');
  });

  it('keeps unknown shapes readable', () => {
    const d = describePreviewStep({}, 4, catalog);
    expect(d.label).toBe('Step 5');
    expect(d.icon).toBe('generic');
  });

  it('handles unknown engine types via category prefix', () => {
    const d = describePreviewStep({ type: 'action.future_thing', name: 'New step' }, 0, catalog);
    expect(d.color).toBe('#C9E7B5'); // action sage
  });
});
