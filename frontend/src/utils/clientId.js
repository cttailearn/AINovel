// 修复 #28: 统一的 clientId 生成器.
//
// 之前 CreationTaskContext / EnrichmentTaskContext 各有自己的
// getOrCreateClientId, 用 ``cli_${Date.now()}_${rand}`` 这种弱随机格式,
// 与项目内其它 ainovel.* v1 key 命名不一致. 现在统一用 crypto.randomUUID()
// 生成稳定 + 唯一的 client id, 并集中管理 localStorage key.
const STORAGE_KEY = 'ainovel.client.id.v1';

function generateId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `cli_${crypto.randomUUID()}`;
  }
  // 兜底 (极旧的浏览器 / WebView 不支持 crypto.randomUUID)
  return `cli_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 12)}`;
}

export function getOrCreateClientId() {
  if (typeof window === 'undefined') return null;
  try {
    let id = window.localStorage.getItem(STORAGE_KEY);
    if (!id) {
      id = generateId();
      window.localStorage.setItem(STORAGE_KEY, id);
    }
    return id;
  } catch {
    return null;
  }
}

export const CLIENT_ID_STORAGE_KEY = STORAGE_KEY;