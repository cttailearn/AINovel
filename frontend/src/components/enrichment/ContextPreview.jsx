import { useMemo, useState } from 'react';

/**
 * 展示 LLM 实际收到的 prompt 上下文 (只读 + 可复制).
 * - 不直接发请求, 由调用方传入拆解结果 + intent + 规则, 客户端拼装展示.
 * - 折叠态默认收起, 展开后显示完整 system + user prompt 预览.
 */
export function ContextPreview({
  chapterTitle,
  chapterText,
  summary,
  recognition,
  sceneTag,
  enrichmentIntent,
  generalRule,
  sceneRule,
  rewriteTemplate = null,
  defaultOpen = false,
}) {
  const [open, setOpen] = useState(defaultOpen);

  const userPrompt = useMemo(() => {
    const recognitionStr = recognition
      ? JSON.stringify(recognition, null, 2)
      : '（未抽取）';
    return [
      '请改写以下章节。',
      '',
      `【章节标题】${chapterTitle || '（无）'}`,
      `【章节摘要】${summary || '（未生成）'}`,
      `【登场人物 / 关键事件】${recognitionStr}`,
      `【场景标签】${sceneTag || '（未标记）'}`,
      '',
      '【通用改写规则】',
      generalRule || '（使用默认）',
      '',
      '【场景特定改写规则】',
      sceneRule || '（无）',
      '',
      '【用户加料需求】(可空, 优先遵循)',
      (enrichmentIntent || '').trim() || '（无）',
      '',
      '【原文】',
      chapterText ? chapterText.slice(0, 400) + (chapterText.length > 400 ? '…' : '') : '（无）',
    ].join('\n');
  }, [chapterTitle, summary, recognition, sceneTag, generalRule, sceneRule, enrichmentIntent, chapterText]);

  const systemPrompt = useMemo(() => {
    if (rewriteTemplate?.system_prompt) return rewriteTemplate.system_prompt;
    return '你是一名擅长小说加料改写的写作助手。改写目标是: 在保留原章节主线和关键事件的前提下, 增强画面感、对话张力、动作细节与情绪渲染, 避免偏离原作设定与人设。用户会在「加料需求」中明确给出本次加料的方向, 请优先按用户意图展开, 若未给出则按通用规则均衡增强。输出仅包含改写后的正文, 不要解释、注释、Markdown 或章节标题。';
  }, [rewriteTemplate]);

  const handleCopy = async () => {
    try {
      // eslint-disable-next-line no-undef
      if (navigator?.clipboard?.writeText) {
        // eslint-disable-next-line no-undef
        await navigator.clipboard.writeText(`${systemPrompt}\n\n---\n\n${userPrompt}`);
      } else {
        // Fallback: select textarea
        const ta = document.createElement('textarea');
        ta.value = `${systemPrompt}\n\n---\n\n${userPrompt}`;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
    } catch {
      // 静默
    }
  };

  return (
    <div className={`context-preview ${open ? 'open' : 'closed'}`}>
      <header
        className="context-preview-head"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="context-preview-label">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
            <path
              d={open ? 'M6 9l6 6 6-6' : 'M9 6l6 6-6 6'}
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          提示词上下文 (LLM 实际收到)
        </span>
        <span className="context-preview-hint">
          {open ? '收起' : '展开查看'}
        </span>
      </header>
      {open && (
        <div className="context-preview-body">
          <div className="context-preview-block">
            <div className="context-preview-block-label">SYSTEM</div>
            <pre className="context-preview-text">{systemPrompt}</pre>
          </div>
          <div className="context-preview-block">
            <div className="context-preview-block-label">USER</div>
            <pre className="context-preview-text">{userPrompt}</pre>
          </div>
          <div className="context-preview-actions">
            <button
              type="button"
              className="editable-field-btn ghost"
              onClick={handleCopy}
            >
              复制完整 prompt
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
