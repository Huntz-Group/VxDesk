// Hand-rolled inline SVG icons (16x16, stroke-based). No emoji, no icon font.

import type { CSSProperties } from 'react';

// Pastel category accents: filled pastel surfaces with dark text (#2A2A2A).
export const CATEGORY_COLORS: Record<string, string> = {
  trigger: '#FFB583', // peach
  input: '#BBE9F2', // soft blue
  control: '#BAAAD7', // lavender
  capture: '#FFD3E0', // pink
  vision: '#FFD3E0', // pink
  action: '#C9E7B5', // sage
  script: '#E5DCD5', // beige
  output: '#F6E7A9', // soft yellow-cream
  unknown: '#E5E0D5',
};

export function categoryColor(category: string): string {
  return CATEGORY_COLORS[category] ?? CATEGORY_COLORS.unknown;
}

const PATHS: Record<string, string> = {
  play: 'M5 3.5v9l7.5-4.5z',
  table: 'M2.5 3.5h11v9h-11zM2.5 7h11M2.5 10h11M6.5 3.5v9M10 3.5v9',
  loop: 'M3 8a5 5 0 0 1 8.5-3.5M13 8a5 5 0 0 1-8.5 3.5M11.5 1.5v3h-3M4.5 14.5v-3h3',
  branch: 'M4 3v4c0 2 2 3 4 3s4 1 4 3M4 3h.01M12 13h.01M4 3l3 7',
  clock: 'M8 14A6 6 0 1 0 8 2a6 6 0 0 0 0 12zM8 5v3.2l2.2 1.3',
  scan: 'M2.5 5.5v-3h3M13.5 5.5v-3h-3M2.5 10.5v3h3M13.5 10.5v3h-3M2 8h12',
  variable: 'M4 4C2.5 6 2.5 10 4 12M12 4c1.5 2 1.5 8 0 8M5.5 9.5h5M6.5 6.5l-2 3 2 3',
  terminal: 'M2.5 3.5h11v9h-11zM5 6.5l2 2-2 2M8.5 10.5H11',
  camera: 'M2.5 5.5h2l1.2-1.8h4.6L11.5 5.5h2v7h-11zM8 11a2.3 2.3 0 1 0 0-4.6A2.3 2.3 0 0 0 8 11z',
  image: 'M2.5 3.5h11v9h-11zM2.5 10.5l3-3 2.5 2.5 2-2 3.5 3.5M10.8 6.2h.01',
  text: 'M3 4.5h10M3 8h10M3 11.5h6',
  cursor: 'M4.5 2.5l7 5-3.2.6 1.8 3.4-2 1-1.8-3.4-2.6 2.2z',
  move: 'M8 2v12M2 8h12M8 2L5.8 4.2M8 2l2.2 2.2M8 14l-2.2-2.2M8 14l2.2-2.2M2 8l2.2-2.2M2 8l2.2 2.2M14 8l-2.2-2.2M14 8l-2.2 2.2',
  drag: 'M5 5.5h.01M11 10.5h.01M5 5.5c2 5 4 5 6 5M11 10.5l-1.6-1.2M11 10.5l-1.6 1.2',
  keyboard: 'M2 5h12v7H2zM4.5 7.2h.01M8 7.2h.01M11.5 7.2h.01M5 9.8h6',
  key: 'M8.8 8.8a3 3 0 1 0-2.1-.9L3 11.5V14h2.5v-1.5H7v-1.7zM10.8 5.2h.01',
  window: 'M2.5 3.5h11v9h-11zM2.5 6h11M4.3 4.7h.01M6 4.7h.01',
  launch: 'M8 13.5s-4.5-2-4.5-6.5c0-2 1-4.5 4.5-5 3.5.5 4.5 3 4.5 5 0 4.5-4.5 6.5-4.5 6.5zM8 8.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z',
  code: 'M6 5L3 8l3 3M10 5l3 3-3 3',
  save: 'M3 3h8l2 2v8H3zM5 3v3h5V3M5 13V9h6v4',
  info: 'M8 14.5A6.5 6.5 0 1 0 8 1.5a6.5 6.5 0 0 0 0 13zM8 7.2v3.6M8 4.9h.01',
  copy: 'M5.5 5.5v-3h8v8h-3M2.5 5.5h8v8h-8z',
  pause: 'M5.5 3.5v9M10.5 3.5v9',
  trash: 'M2.5 4h11M6 4V2.5h4V4M4 4l.7 9h6.6L12 4M6.5 6.5v4M9.5 6.5v4',
  plus: 'M8 3v10M3 8h10',
  generic: 'M8 2.5l5 2.75v5.5L8 13.5l-5-2.75v-5.5z',
};

export function NodeIcon({ name, size = 14, style }: { name: string; size?: number; style?: CSSProperties }) {
  const d = PATHS[name] ?? PATHS.generic;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.3}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={style}
      aria-hidden="true"
    >
      <path d={d} />
    </svg>
  );
}

/** Four-point sparkle (assistant toggle + headers). */
export function SparkleIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M8 1.6c.34 3.2 1.9 4.76 5.1 5.1.16.02.16.24 0 .26-3.2.34-4.76 1.9-5.1 5.1-.02.16-.24.16-.26 0-.34-3.2-1.9-4.76-5.1-5.1-.16-.02-.16-.24 0-.26 3.2-.34 4.76-1.9 5.1-5.1.02-.16.24-.16.26 0z" />
      <path d="M12.6 10.6c.17 1.6.95 2.38 2.55 2.55.08.01.08.13 0 .14-1.6.17-2.38.95-2.55 2.55-.01.08-.13.08-.14 0-.17-1.6-.95-2.38-2.55-2.55-.08-.01-.08-.13 0-.14 1.6-.17 2.38-.95 2.55-2.55.01-.08.13-.08.14 0z" opacity=".7" />
    </svg>
  );
}

/** Gear (settings). */
export function GearIcon({ size = 15 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.3}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="8" cy="8" r="2.2" />
      <path d="M8 1.8v1.7M8 12.5v1.7M1.8 8h1.7M12.5 8h1.7M3.6 3.6l1.2 1.2M11.2 11.2l1.2 1.2M12.4 3.6l-1.2 1.2M4.8 11.2l-1.2 1.2" />
    </svg>
  );
}

/** Filled record dot (●) for the Record button and recording bar. */
export function RecordDot({ size = 9, color = 'var(--rose)' }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 10 10" aria-hidden="true" style={{ flex: 'none' }}>
      <circle cx="5" cy="5" r="4.4" fill={color} />
    </svg>
  );
}
