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

// === 预设规则 ===
export const PRESET_RULES = [
  { label: '通用', value: '^第.{1,30}章' },
  { label: '纯数字', value: '^第\\d+章' },
  { label: '中文数字', value: '^第[一二三四五六七八九十百千零\\d]+章' },
  { label: '第X章 标题', value: '^第.{1,30}章\\s+[^\\n]+' },
];

// === 行首标识（章节起始词）===
export const PREFIX_OPTIONS = [
  { value: '第', label: '第' },
  { value: 'Chapter ', label: 'Chapter' },
  { value: 'CHAPTER ', label: 'CHAPTER' },
  { value: '卷', label: '卷' },
];

// === 数字类型（行首标识之后的章节编号格式）===
export const NUMBER_TYPE_OPTIONS = [
  {
    value: 'arabic',
    label: '阿拉伯数字',
    // 匹配 "第123章" / "第1章" / "第12章" 等
    pattern: '\\d+',
  },
  {
    value: 'chinese',
    label: '中文数字',
    // 匹配 "第一章" / "第一百二十三章"
    pattern: '[一二三四五六七八九十百千零〇两\\d]+',
  },
  {
    value: 'mixed',
    label: '混合型数字',
    // 混合中文与阿拉伯数字，例如 "第1章" / "第一千零1章"
    pattern: '[一二三四五六七八九十百千零〇两\\d]+',
  },
  {
    value: 'roman',
    label: '罗马数字',
    pattern: '[IVXLCDM]+',
  },
  {
    value: 'sequence',
    label: '章回卷节部',
    pattern: '[\\d零一二三四五六七八九十百千]+',
  },
];

// === 附加规则（特殊章：序/楔子/番外/后记等）===
export const DEFAULT_EXTRA_RULE =
  '^\\s*(序章|序幕|序[1-9]|序曲|楔子|前言|后记|尾声|番外|最终章|外传|插曲)';

// === 模式选择 ===
export const PARSE_MODE = {
  SIMPLE: 'simple',
  REGEX: 'regex',
};

/**
 * 根据"行首标识 + 数字类型 + 附加规则"组装一个完整正则。
 * 返回用于 parse_with_rule 的单一正则字符串。
 *
 * 输出形如：
 *   ^\s*(第\s*\d+\s*(?:章|节|部|卷)|序章|序幕|楔子|...)
 *
 * @param {object} cfg
 * @param {string} cfg.prefix - 行首标识（如 "第"）
 * @param {string} cfg.numberType - 数字类型 key
 * @param {string} cfg.extraRule - 附加规则正则（完整 ^...）
 * @returns {string}
 */
export function buildSimpleRule({ prefix, numberType, extraRule }) {
  const safePrefix = escapeRegex(prefix || '第');
  const numOption = NUMBER_TYPE_OPTIONS.find((n) => n.value === numberType);
  const numPattern = numOption ? numOption.pattern : '\\d+';

  // 主匹配：行首标识 + 数字 + 量词(章/节/部/卷) + 可选同行副标题
  // 同行副标题以空格 / 中英文冒号 / 顿号开头，例如:
  //   "第二十八章 你们一起上吧"
  //   "第二十八章：你们一起上吧"
  //   "第二十八章、你们一起上吧"
  // 副标题长度不超过 60 个字符，避免跨段吞正文
  const titleTail = '(?:[\\s:：、][^\\n]{1,60})?';
  const mainAlt = `${safePrefix}\\s*${numPattern}\\s*(?:章|节|部|卷)${titleTail}`;

  // 附加规则：去掉它的 ^ 与最外层 ( ... )，并入主分组
  const extra = (extraRule || '').trim();
  let extraAlt = '';
  if (extra) {
    // 去掉开头的 ^ 与 \s*
    const body = extra.replace(/^\^\\s\*\(/, '').replace(/^\^\s*\(/, '');
    // 去掉结尾的 )，但保留 \)? 之类
    extraAlt = body.replace(/\)\s*$/, '');
  }

  const alts = extraAlt ? `${mainAlt}|${extraAlt}` : mainAlt;
  return `^\\s*(${alts})`;
}

/**
 * 从已有正则字符串反推出简单模式下的配置（仅做粗略推断）。
 * 解析不出时返回 null，前端回退到默认简单配置。
 */
export function parseSimpleRule(rule) {
  if (!rule || typeof rule !== 'string') return null;
  const hasChapter = /[章节部卷]/.test(rule);
  if (!hasChapter) return null;
  const hasArabic = /\\d\+/.test(rule);
  return {
    mode: PARSE_MODE.SIMPLE,
    prefix: /^.{0,2}Chapter/i.test(rule) ? 'Chapter ' : '第',
    numberType: hasArabic ? 'arabic' : 'chinese',
    extraRule: DEFAULT_EXTRA_RULE,
  };
}
