export function escapeRegex(input) {
  return String(input).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function tryCompileRegex(rule) {
  try {
    return { ok: true, regex: new RegExp(rule, 'm') };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

export const PRESET_RULES = [
  { label: '通用', value: '^第.{1,30}章' },
  { label: '纯数字', value: '^第\\d+章' },
  { label: '中文数字', value: '^第[一二三四五六七八九十百千零\\d]+章' },
  { label: '第X章 标题', value: '^第.{1,30}章\\s+[^\\n]+' },
];
