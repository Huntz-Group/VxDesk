# VxDesk — Recorder contract (backend ↔ frontend)

Record real desktop interactions (mouse clicks, typing, hotkeys, window switches) and
convert them into an editable workflow. Capture uses `pynput` global listeners;
screenshots for smart mode use the existing capture layer.

## Data model

A recording session lives in memory on the backend until converted or discarded.

Recorded event (normalized):
```json
{"t": 0.42, "kind": "click",  "x": 450, "y": 320, "button": "left", "window": "Untitled - Notepad"}
{"t": 1.10, "kind": "char",   "text": "h"}
{"t": 1.15, "kind": "key",    "key": "enter"}
{"t": 1.20, "kind": "key",    "key": "ctrl+s"}
{"t": 2.00, "kind": "window", "title": "Google Chrome"}
```
`t` = seconds since recording start. `window` = foreground window title at that moment
(best effort, pywin32). Printable characters arrive as `char`; everything else
(enter/tab/escape/backspace/delete/f-keys/chords) as `key` with normalized names
(`ctrl+s`, `alt+tab`, `shift+enter` …).

## Endpoints

- `POST /api/recorder/start` → `{session_id}` — starts listeners. 409 if already recording.
- `POST /api/recorder/stop` → `{session_id, events: [...], duration_s, step_preview: [...]}` —
  stops listeners and returns the raw events plus a human-readable preview of the
  converted steps (same summaries the converter will produce). Each `step_preview`
  item is `{"type": <node type>, "name": <plain-language label>}` so the UI can style
  rows by node category.
- `POST /api/recorder/discard` `{session_id}` → `{ok: true}` — drops the session.
- `GET  /api/recorder/status` → `{recording: bool, session_id?, event_count, elapsed_s}` —
  polled by the frontend (1 s) while recording.
- `POST /api/recorder/convert` `{session_id, name, mode: "smart"|"coordinates"}` →
  the created workflow JSON (validated before save, same as other creation paths).
  The session is consumed. Conversion errors → 400 `{detail}`.

Pressing **Esc** during recording stops it (same as `/stop`) and the Esc itself is NOT
recorded; the frontend notices via `status` polling. Escape keys mid-flow can still be
recorded — only the FIRST Esc pressed while no other key is held acts as stop. (If this
proves unreliable in practice, the stop hotkey is `esc` and mid-flow Esc is lost —
acceptable v1 tradeoff, documented in the UI.)

## Conversion rules (deterministic, unit-tested)

Walk events in time order, building a sequential node chain (edges `default`,
auto-layout x += 220, y = 120):

1. **Gap rule**: if `t - prev_t > 750 ms` insert `control.wait` (`ms` = gap, capped at 5000).
2. **Window rule**: if the event's `window` differs from the previous event's window
   (and is non-empty), insert `action.focus_window` (`title`) before the action — but at
   most one focus per distinct title in a row.
3. **click** →
   - `smart`: crop an ~80×80 template around the point from a screenshot taken AT CLICK
     TIME (saved to `assets/templates/rec_<session>_<n>.png`, clamped to screen bounds),
     emit `vision.find_image` (template, threshold 0.85) then `action.click`
     (`target: last_found`) with the raw x/y ALSO stored in the click params as fallback.
   - `coordinates`: single `action.click` (`target: point`, x, y, button).
4. **char runs** — consecutive `char` events with gaps < 800 ms and no window change →
   one `action.type_text` (`text` = concatenation, `interval_ms` = 30).
5. **key** → `action.press_key` (`keys`: `"enter"` or `["ctrl","s"]` shape matching the
   existing press_key param conventions).
6. Leading waits/focuses before the first real action are kept (they're meaningful);
   trailing wait after the last action is dropped.
7. Node names are plain language: `Click "Save"`, `Click at (450, 320)`, `Type "hello wor…"`,
   `Press Ctrl+S`, `Wait 1.2s`, `Focus "Notepad"`.

The converter MUST reuse the engine's node handlers/validation — produced workflows are
ordinary workflows, editable and runnable like any other.

## Safety / UX notes (frontend must surface)

- Recording captures EVERYTHING typed — the UI warns "avoid passwords" while recording.
- pynput listeners are always stopped on `/stop`, `/discard`, convert, and server shutdown.
- `smart` mode notes in the UI: "works best when the screen looks the same next time —
  tune the threshold if a step can't find its target."
