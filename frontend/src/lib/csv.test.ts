import { describe, expect, it } from 'vitest';
import { parseCsv } from './csv';

describe('parseCsv', () => {
  it('parses headers and rows', () => {
    const t = parseCsv('name,url\nAcme,https://a\nGlobex,https://b\n');
    expect(t.header).toEqual(['name', 'url']);
    expect(t.rows).toEqual([
      ['Acme', 'https://a'],
      ['Globex', 'https://b'],
    ]);
  });

  it('handles quoted fields, commas and escaped quotes', () => {
    const t = parseCsv('a,b\n"x, y","say ""hi"""');
    expect(t.rows[0]).toEqual(['x, y', 'say "hi"']);
  });

  it('handles CRLF and empty input', () => {
    expect(parseCsv('a,b\r\n1,2\r\n').rows).toEqual([['1', '2']]);
    expect(parseCsv('')).toEqual({ header: [], rows: [] });
  });

  it('caps row count', () => {
    const text = `h\n${Array.from({ length: 100 }, (_, i) => String(i)).join('\n')}`;
    expect(parseCsv(text, 10).rows).toHaveLength(10);
  });
});
