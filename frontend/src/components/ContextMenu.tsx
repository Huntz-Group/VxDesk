// Right-click context menu for the canvas (nodes and empty pane).

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useEditorStore } from '../editorStore';
import { NodeIcon } from '../icons';
import { clampMenuPosition } from '../lib/menu';

export interface MenuState {
  x: number;
  y: number;
  /** null = pane menu (empty canvas) */
  nodeId: string | null;
}

interface Props {
  menu: MenuState;
  onFitView: () => void;
  onClose: () => void;
}

interface Item {
  key: string;
  icon: string;
  label: string;
  danger?: boolean;
  dividerBefore?: boolean;
  onClick: () => void;
}

export function ContextMenu({ menu, onFitView, onClose }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState({ x: menu.x, y: menu.y });

  // close on outside click / Escape
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('mousedown', onDown, true);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('mousedown', onDown, true);
      window.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  // clamp inside the viewport once we know the menu's size
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    setPos(clampMenuPosition(menu.x, menu.y, rect.width, rect.height, window.innerWidth, window.innerHeight));
  }, [menu]);

  const node = useEditorStore((s) => (menu.nodeId ? s.nodes.find((n) => n.id === menu.nodeId) : undefined));
  const store = useEditorStore.getState();

  const items: Item[] = menu.nodeId
    ? [
        {
          key: 'details',
          icon: 'info',
          label: 'Details',
          onClick: () => store.focusNodeDetails(menu.nodeId as string),
        },
        {
          key: 'duplicate',
          icon: 'copy',
          label: 'Duplicate',
          onClick: () => store.duplicateNode(menu.nodeId as string),
        },
        {
          key: 'pause',
          icon: node?.data.disabled ? 'play' : 'pause',
          label: node?.data.disabled ? 'Resume step' : 'Pause step',
          onClick: () => store.setNodeDisabled(menu.nodeId as string, !(node?.data.disabled ?? false)),
        },
        {
          key: 'delete',
          icon: 'trash',
          label: 'Delete',
          danger: true,
          dividerBefore: true,
          onClick: () => store.deleteNode(menu.nodeId as string),
        },
      ]
    : [
        {
          key: 'add',
          icon: 'plus',
          label: 'Add a step…',
          onClick: () => store.focusPaletteSearch(),
        },
        { key: 'fit', icon: 'scan', label: 'Fit view', onClick: onFitView },
      ];

  return (
    <div className="ctx-menu" ref={ref} style={{ left: pos.x, top: pos.y }} role="menu">
      {items.map((item) => (
        <div key={item.key}>
          {item.dividerBefore && <div className="ctx-divider" />}
          <button
            className={`ctx-item${item.danger ? ' danger' : ''}`}
            role="menuitem"
            onClick={() => {
              item.onClick();
              onClose();
            }}
          >
            <NodeIcon name={item.icon} size={13} />
            <span>{item.label}</span>
          </button>
        </div>
      ))}
    </div>
  );
}
