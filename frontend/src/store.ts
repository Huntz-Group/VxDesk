// App-level store: backend reachability, system info, node catalog.

import { create } from 'zustand';
import { getCatalog, getSystemInfo } from './api';
import { FALLBACK_CATALOG } from './catalog-fallback';
import type { NodeDef, SystemInfo } from './types';

export type BackendStatus = 'unknown' | 'online' | 'offline';

interface AppState {
  backend: BackendStatus;
  systemInfo: SystemInfo | null;
  catalog: NodeDef[];
  catalogIsFallback: boolean;
  /** bumped whenever workflows change outside the list page (e.g. AI tools) */
  workflowsVersion: number;
  bumpWorkflows: () => void;
  refreshSystem: () => Promise<void>;
  loadCatalog: () => Promise<void>;
}

export const useAppStore = create<AppState>((set) => ({
  backend: 'unknown',
  systemInfo: null,
  catalog: FALLBACK_CATALOG.nodes,
  catalogIsFallback: true,
  workflowsVersion: 0,
  bumpWorkflows: () => set((s) => ({ workflowsVersion: s.workflowsVersion + 1 })),

  refreshSystem: async () => {
    try {
      const info = await getSystemInfo();
      set({ backend: 'online', systemInfo: info });
    } catch {
      set({ backend: 'offline', systemInfo: null });
    }
  },

  loadCatalog: async () => {
    try {
      const cat = await getCatalog();
      if (Array.isArray(cat.nodes) && cat.nodes.length > 0) {
        set({ catalog: cat.nodes, catalogIsFallback: false });
        return;
      }
      set({ catalog: FALLBACK_CATALOG.nodes, catalogIsFallback: true });
    } catch {
      set({ catalog: FALLBACK_CATALOG.nodes, catalogIsFallback: true });
    }
  },
}));

export function catalogDef(catalog: NodeDef[], type: string): NodeDef | undefined {
  return catalog.find((d) => d.type === type);
}
