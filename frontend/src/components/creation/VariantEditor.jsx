// 富文本编辑器 (MVP: textarea + 字数统计 + 自动保存)
// UX-#13: Ctrl/Cmd+S 立即保存, 字数分语言统计, 段落渲染提示
import { useEffect, useMemo, useRef, useState } from 'react';

const SAVE_DEBOUNCE_MS = 800;

function countChars(text) {
  if (!text) return { total: 0, cn: 0, en: 0, punct: 0, spaces: 0, paragraphs: 0 };
  let cn = 0, en = 0, punct = 0, spaces = 0;
  for (const ch of text) {
    if (/\s/.test(ch)) { spaces += 1; continue; }
    // CJK 统一汉字 + 日韩 (基本汉字 + 平假/片假名)
    if (/[\u4e00-\u9fff\u3040-\u30ff\u3400-\u4dbf]/.test(ch)) cn += 1;
    else if (/[A-Za-z0-9]/.test(ch)) en += 1;
    else punct += 1;
  }
  const paragraphs = text.split(/\n\s*\n/).filter((p) => p.trim()).length;
  return { total: cn + en, cn, en, punct, spaces, paragraphs };
}

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
  const textareaRef = useRef(null);

  useEffect(() => {
    setContent(initialContent || '');
    lastSavedContentRef.current = initialContent || '';
    setLastSavedAt(null);
    dirtyRef.current = false;
  }, [initialContent, chapter?.id]);

  const charCount = useMemo(() => countChars(content), [content]);

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

  // UX-#13: Ctrl/Cmd+S 立即保存
  useEffect(() => {
    const onKey = (e) => {
      const isSave = (e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S');
      if (!isSave) return;
      e.preventDefault();
      if (!disabled && !saving) saveNow();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, dirtyRef.current, saving, disabled]);

  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  return (
    <div className="creation-editor">
      <div className="creation-editor-toolbar">
        <div className="creation-editor-status muted small">
          {charCount.total} 字 (中 {charCount.cn} / 英 {charCount.en})
          {charCount.paragraphs > 0 && ` · ${charCount.paragraphs} 段`}
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
            title="立即保存 (Ctrl/Cmd+S)"
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
        ref={textareaRef}
        className="creation-editor-textarea"
        value={content}
        onChange={handleChange}
        placeholder="章节正文... (空行分段, Ctrl/Cmd+S 立即保存)"
        disabled={disabled}
        spellCheck={false}
      />
      <p className="creation-editor-hint muted small">
        编辑会自动保存 (停顿 {SAVE_DEBOUNCE_MS}ms). Ctrl/Cmd+S 立即保存. 确认后, 系统会从本章抽取人物 / 事件 / 关系写入项目级知识图谱, 用于后续章节一致性.
      </p>
    </div>
  );
}
