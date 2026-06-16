// 修复 #35: 全局键盘快捷键 hook.
//
// - Ctrl/Cmd + Enter: 触发传入的 submit
// - Esc: 触发传入的 cancel
// - 忽略在 input[type=text|search]/textarea/contenteditable 之外聚焦时也响应
//   (因为这俩元素本来就是文本编辑, 不应该被全局快捷键截胡).
import { useEffect } from 'react';

const TEXT_INPUT_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);

function isEditable(target) {
  if (!target) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (TEXT_INPUT_TAGS.has(tag)) {
    // input 里只有 text-like 才算
    const type = (target.type || '').toLowerCase();
    return !['checkbox', 'radio', 'button', 'submit', 'reset'].includes(type);
  }
  return false;
}

export function useKeyboardShortcuts({ onSubmit, onCancel, enabled = true } = {}) {
  useEffect(() => {
    if (!enabled) return undefined;
    const handler = (ev) => {
      // Esc 在所有场景都响应 (包括文本输入)
      if (ev.key === 'Escape' && onCancel) {
        ev.preventDefault();
        onCancel();
        return;
      }
      // Ctrl+Enter / Cmd+Enter: 提交
      if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter' && onSubmit) {
        // 即便在 textarea 里, 也允许 Ctrl+Enter 触发提交 (vs Enter 正常换行)
        if (isEditable(ev.target)) {
          ev.preventDefault();
        }
        onSubmit();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onSubmit, onCancel, enabled]);
}