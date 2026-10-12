// Minimal CSV parser (quoted fields, escaped quotes, CRLF) for the csv param preview.

export interface CsvTable {
  header: string[];
  rows: string[][];
}

export function parseCsv(text: string, maxRows = 50): CsvTable {
  const records: string[][] = [];
  let field = '';
  let record: string[] = [];
  let inQuotes = false;
  let i = 0;
  const pushField = () => {
    record.push(field);
    field = '';
  };
  const pushRecord = () => {
    // skip fully-empty trailing lines
    if (record.length === 1 && record[0] === '') {
      record = [];
      return;
    }
    records.push(record);
    record = [];
  };
  while (i < text.length) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 2;
          continue;
        }
        inQuotes = false;
        i += 1;
        continue;
      }
      field += ch;
      i += 1;
      continue;
    }
    if (ch === '"') {
      inQuotes = true;
      i += 1;
      continue;
    }
    if (ch === ',') {
      pushField();
      i += 1;
      continue;
    }
    if (ch === '\r') {
      i += 1;
      continue;
    }
    if (ch === '\n') {
      pushField();
      pushRecord();
      i += 1;
      continue;
    }
    field += ch;
    i += 1;
  }
  pushField();
  pushRecord();

  if (records.length === 0) return { header: [], rows: [] };
  const [header, ...rows] = records;
  return { header, rows: rows.slice(0, maxRows) };
}
