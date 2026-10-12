import { describe, expect, it } from 'vitest';
import { parseSseLine, SseParser } from './ai';

describe('parseSseLine', () => {
  it('parses a data line into an event', () => {
    const ev = parseSseLine('data: {"event":"done","content":"All set!"}');
    expect(ev).toEqual({ event: 'done', content: 'All set!' });
  });

  it('ignores comments, blanks and malformed JSON', () => {
    expect(parseSseLine(': keep-alive')).toBeNull();
    expect(parseSseLine('')).toBeNull();
    expect(parseSseLine('data:')).toBeNull();
    expect(parseSseLine('data: {not json')).toBeNull();
    expect(parseSseLine('data: [1,2]')).toBeNull();
  });

  it('parses tool events with workflow_id', () => {
    const ev = parseSseLine('data: {"event":"tool_end","id":"call_1","name":"create_workflow","ok":true,"summary":"Created wf_9 (6 steps)","workflow_id":"wf_9"}');
    expect(ev?.event).toBe('tool_end');
    expect(ev && 'workflow_id' in ev ? ev.workflow_id : undefined).toBe('wf_9');
  });
});

describe('SseParser', () => {
  it('handles lines split across chunks', () => {
    const p = new SseParser();
    expect(p.push('data: {"event":"assistant_messa')).toEqual([]);
    const out = p.push('ge","content":"hi"}\ndata: {"event":"done","content":"bye"}\n');
    expect(out.map((e) => e.event)).toEqual(['assistant_message', 'done']);
  });

  it('flush returns a trailing unterminated line', () => {
    const p = new SseParser();
    p.push('data: {"event":"done","content":"end"}');
    expect(p.flush().map((e) => e.event)).toEqual(['done']);
    expect(p.flush()).toEqual([]);
  });
});
