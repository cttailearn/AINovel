// UX-#1: 横向拖拽分栏手柄
// - 通过 CSS 变量 --toc-width / --ref-width 控制分栏宽度
// - 拖拽时实时改父元素的 inline style, 松开后持久化到 localStorage
// - onDragStart/Stop 可选, 用于禁用文本选择等
import { useCallback, useRef, useState } from 'react';

const STORAGE_KEY = 'ainovel.creation.paneWidths.v1';
const MIN_WIDTH = 180;
const MAX_WIDTH = 720;

function readStored() {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const obj = JSON.parse(raw);
    if (typeof obj !== 'object' || !obj) return null;
    return obj;
  } catch {
    return null;
  }
}

function writeStored(tocWidth, refWidth) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ tocWidth, refWidth, ts: Date.now() })
    );
  } catch { /* noop */ }
}

export function PaneWidthsContext() {
  // 提供给外部使用的读取函数
  return {
    read: readStored,
    write: writeStored,
    MIN: MIN_WIDTH,
    MAX: MAX_WIDTH,
  };
}

export function ResizablePaneDivider({
  side,                // 'toc' | 'reference'
  containerRef,        // 用于获取容器宽度以约束分栏
  persist = true,
  cssVarName,          // '--toc-width' | '--ref-width'
  hidden = false,
}) {
  const ref = useRef(null);
  const [dragging, setDragging] = useState(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(0);

  const applyWidth = useCallback(
    (px) => {
      const w = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, Math.round(px)));
      if (containerRef && containerRef.current) {
        containerRef.current.style.setProperty(cssVarName, `${w}px`);
      } else {
        document.documentElement.style.setProperty(cssVarName, `${w}px`);
      }
      return w;
    },
    [containerRef, cssVarName]
  );

  const onMouseDown = useCallback(
    (e) => {
      e.preventDefault();
      const container = containerRef && containerRef.current;
      if (!container) return;
      // 读当前 CSS 变量值
      const cs = window.getComputedStyle(container);
      const cur = parseFloat(cs.getPropertyValue(cssVarName)) || 280;
      startXRef.current = e.clientX;
      startWidthRef.current = cur;
      setDragging(true);
      // 屏蔽选区
      const onMove = (ev) => {
        const delta = ev.clientX - startXRef.current;
        const newW = side === 'toc' ? startWidthRef.current + delta
                                   : startWidthRef.current - delta;
        applyWidth(newW);
      };
      const onUp = (ev) => {
        setDragging(false);
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        // 持久化
        if (persist) {
          const tocW = parseFloat(
            window.getComputedStyle(container).getPropertyValue('--toc-width')
          ) || 280;
          const refW = parseFloat(
            window.getComputedStyle(container).getPropertyValue('--ref-width')
          ) || 440;
          writeStored(tocW, refW);
        }
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    },
    [applyWidth, containerRef, cssVarName, side, persist]
  );

  if (hidden) return null;

  return (
    <div
      ref={ref}
      role="separator"
      aria-orientation="vertical"
      aria-label={side === 'toc' ? '调整左侧章节大纲宽度' : '调整右侧参考面板宽度'}
      className={`creation-pane-divider${dragging ? ' is-dragging' : ''}`}
      onMouseDown={onMouseDown}
    />
  );
}

// 初始化分栏宽度: 启动时从 localStorage 恢复到 CSS 变量
export function applyStoredPaneWidths(containerEl) {
  if (!containerEl) return;
  const stored = readStored();
  if (!stored) return;
  if (typeof stored.tocWidth === 'number') {
    const w = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, stored.tocWidth));
    containerEl.style.setProperty('--toc-width', `${w}px`);
  }
  if (typeof stored.refWidth === 'number') {
    const w = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, stored.refWidth));
    containerEl.style.setProperty('--ref-width', `${w}px`);
  }
}
