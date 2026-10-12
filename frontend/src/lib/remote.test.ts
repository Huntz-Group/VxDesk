import { describe, expect, it } from 'vitest';
import { activityStyle, capsSummary, machinesLine, timeAgo, toEpochMs, transportStyle } from './remote';

describe('toEpochMs', () => {
  it('handles epoch seconds, epoch ms, and ISO strings', () => {
    expect(toEpochMs(1_700_000_000)).toBe(1_700_000_000_000);
    expect(toEpochMs(1_700_000_000_000)).toBe(1_700_000_000_000);
    expect(toEpochMs('2023-11-14T22:13:20Z')).toBe(1_700_000_000_000);
  });
  it('returns null for junk', () => {
    expect(toEpochMs(null)).toBeNull();
    expect(toEpochMs('not a date')).toBeNull();
    expect(toEpochMs(NaN)).toBeNull();
  });
});

describe('timeAgo', () => {
  const now = 1_700_000_000_000;
  it('friendly buckets', () => {
    expect(timeAgo(now - 10_000, now)).toBe('just now');
    expect(timeAgo(now - 2 * 60_000, now)).toBe('2 min ago');
    expect(timeAgo(now - 3 * 3_600_000, now)).toBe('3 h ago');
    expect(timeAgo(now - 5 * 86_400_000, now)).toBe('5 days ago');
    expect(timeAgo(null, now)).toBe('never');
  });
});

describe('capsSummary', () => {
  it('summarizes os + capabilities', () => {
    expect(capsSummary({ os: 'windows', engine: true, workflows: true })).toBe('windows · workflows');
    expect(capsSummary({ os: 'windows-xp', shell: true })).toBe('windows-xp · shell commands');
    expect(capsSummary({})).toBe('—');
    expect(capsSummary(null)).toBe('—');
  });
});

describe('activityStyle / transportStyle', () => {
  it('maps kinds to pastel chips', () => {
    expect(activityStyle('connected').color).toBe('#BBE9F2');
    expect(activityStyle('run_finished', true).color).toBe('#C9E7B5');
    expect(activityStyle('run_finished', false).color).toBe('#FBE4EA');
    expect(activityStyle('log').color).toBe('#E5E0D5');
  });
  it('maps transports', () => {
    expect(transportStyle('ws').label).toBe('WebSocket');
    expect(transportStyle('edge').label).toBe('Edge polling');
  });
});

describe('machinesLine', () => {
  it('plain-language counts', () => {
    expect(machinesLine(0, 0)).toBe('No machines registered yet');
    expect(machinesLine(2, 2)).toBe('2 machines connected');
    expect(machinesLine(1, 3)).toBe('1 of 3 machines connected');
    expect(machinesLine(0, 1)).toBe('1 machine registered, offline');
  });
});
