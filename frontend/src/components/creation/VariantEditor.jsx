// 富文本编辑器 (MVP: textarea + 字数统计 + 自动保存)
import { useEffect, useRef, useState } from 'react';

const SAVE_DEBOUNCE_MS = 800;

export function VariantEditor({
  chapter,
  initialContent,
  onSave,
  onConfirm,
  saving = false,
  confirming = false,
  disabled = false,
}) {
  const [content, setContent] = useState(initialContent || '');
  const [lastSavedAt, setLastSavedAt] = useState(null);
  const dirtyRef = useRef(false);
  const timerRef = useRef(null);
  const lastSavedContentRef = useRef(initialContent || '');

  useEffect(() => {
    setContent(initialContent || '');
    lastSavedContentRef.current = initialContent || '';
    setLastSavedAt(null);
    dirtyRef.current = false;
  }, [initialContent, chapter?.id]);

  const wordCount = (() => {
    let n = 0;
    for (const ch of content) if (!/\s/.test(ch)) n += 1;
    return n;
  })();

  const handleChange = (e) => {
    setContent(e.target.value);
    dirtyRef.current = true;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      if (dirtyRef.current && content !== lastSavedContentRef.current) {
        const toSave = content;
        onSave?.(toSave).then(() => {
          lastSavedContentRef.current = toSave;
          setLastSavedAt(new Date());
          dirtyRef.current = false;
        }).catch(() => {});
      }
    }, SAVE_DEBOUNCE_MS);
  };

  // 立即保存
  const saveNow = async () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!dirtyRef.current) return;
    try {
      await onSave?.(content);
      lastSavedContentRef.current = content;
      setLastSavedAt(new Date());
      dirtyRef.current = false;
    } catch (e) {
      // toast 由父级处理
    }
  };

  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  return (
    <div className="creation-editor">
      <div className="creation-editor-toolbar">
        <div className="creation-editor-status muted small">
          {wordCount} 字
          {lastSavedAt && ` · 已保存于 ${lastSavedAt.toLocaleTimeString()}`}
          {saving && ' · 保存中...'}
          {dirtyRef.current && !saving && ' · 有未保存修改'}
        </div>
        <div className="creation-editor-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={saveNow}
            disabled={saving || disabled || !dirtyRef.current}
          >
            保存
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={onConfirm}
            disabled={disabled || saving || confirming || !content.trim()}
          >
            {confirming ? '确认中...' : '确认本章并入图谱'}
          </button>
        </div>
      </div>
      <textarea
        className="creation-editor-textarea"
        value={content}
        onChange={handleChange}
        placeholder="章节正文..."
        disabled={disabled}
        spellCheck={false}
      />
      <p className="creation-editor-hint muted small">
        编辑会自动保存 (停顿 {SAVE_DEBOUNCE_MS}ms). 确认后, 系统会从本章抽取人物 / 事件 / 关系写入项目级知识图谱, 用于后续章节一致性.
      </p>
    </div>
  );
}
