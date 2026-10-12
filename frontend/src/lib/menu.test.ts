import { describe, expect, it } from 'vitest';
import { clampMenuPosition } from './menu';

describe('clampMenuPosition', () => {
  it('keeps a menu that fits where it was opened', () => {
    expect(clampMenuPosition(100, 100, 200, 160, 1024, 768)).toEqual({ x: 100, y: 100 });
  });

  it('clamps past the right and bottom edges', () => {
    expect(clampMenuPosition(1000, 760, 200, 160, 1024, 768)).toEqual({ x: 816, y: 600 });
  });

  it('clamps negative coordinates to the padding', () => {
    expect(clampMenuPosition(-50, -10, 200, 160, 1024, 768)).toEqual({ x: 8, y: 8 });
  });

  it('stays at padding when the menu is bigger than the viewport', () => {
    expect(clampMenuPosition(300, 300, 2000, 2000, 1024, 768)).toEqual({ x: 8, y: 8 });
  });
});
