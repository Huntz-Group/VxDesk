// Pure helpers for the canvas context menu.

/** Clamp a menu at (x, y) so it stays fully inside the viewport. */
export function clampMenuPosition(
  x: number,
  y: number,
  menuWidth: number,
  menuHeight: number,
  viewportWidth: number,
  viewportHeight: number,
  pad = 8,
): { x: number; y: number } {
  const maxX = Math.max(pad, viewportWidth - menuWidth - pad);
  const maxY = Math.max(pad, viewportHeight - menuHeight - pad);
  return {
    x: Math.min(Math.max(pad, x), maxX),
    y: Math.min(Math.max(pad, y), maxY),
  };
}
