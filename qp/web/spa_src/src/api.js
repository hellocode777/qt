// qp-proto API client — 全走 qp FastAPI :8080 真实端点 (vite proxy /api)
async function get(path) {
  const res = await fetch(`/api/v1${path}`);
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return res.json();
}

async function getRaw(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return res.json();
}

async function post(path, body = {}) {
  const res = await fetch(`/api/v1${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return res.json();
}

export const api = {
  account: () => get('/account'),
  positions: (activeOnly = false) => get(`/positions${activeOnly ? '?active_only=true' : ''}`),
  paper: () => get('/paper'),
  strategies: () => get('/strategies'),
  factors: () => get('/factors'),
  decisions: () => get('/decisions'),
  decision: (id) => get(`/decisions/${id}`),
  experiments: () => get('/experiments'),
  experiment: (id) => get(`/experiments/${id}`),
  experimentNav: (id) => get(`/experiments/${id}/nav`),
  experimentTrades: (id) => get(`/experiments/${id}/trades`),
  regime: () => get('/regime'),
  // 健康监控 (8080 /api/v1/health/*)
  healthFactors: () => get('/health/factors'),
  healthFactor: (name) => get(`/health/factors/${encodeURIComponent(name)}`),
  healthStrategies: () => get('/health/strategies'),
  systemHealth: () => get('/system-health'),
  // 影子盘 / 组合 / 数据质量 / 股票 / 知识库
  simulation: () => get('/simulation'),
  portfolio: () => get('/portfolio'),
  dataQuality: () => get('/data-quality'),
  stockSearch: (q) => get(`/stocks/search?q=${encodeURIComponent(q)}`),
  knowledge: () => get('/knowledge'),
  knowledgeContent: (path) => get(`/knowledge/content?path=${encodeURIComponent(path)}`),
  // 决策人工复核动作 (写操作, 与老 UI 同语义)
  reviewDecision: (id, action, notes = '') => post(`/decisions/${id}/review`, { action, notes }),
  executeDecision: (id, notes = '') => post(`/decisions/${id}/execute`, { notes }),
  closeDecision: (id, notes = '') => post(`/decisions/${id}/close`, { notes }),
  // K线走 qp 原生 stocks 端点 (8080)
  industryHeat: (source = '', limit = 200) =>
    get(`/industry-heat?limit=${limit}${source ? '&source=' + source : ''}`),
  kline: (code, days = 365) => getRaw(`/api/stocks/${code}/kline?days=${days}`),
};

export function fmtMoney(x) {
  if (x === null || x === undefined) return '—';
  return x.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function fmtPct(x, digits = 2) {
  if (x === null || x === undefined) return '—';
  return `${x >= 0 ? '+' : ''}${x.toFixed(digits)}%`;
}

// A股: 正红负绿
export function pnlClass(x) {
  if (x === null || x === undefined) return '';
  if (x > 0) return 'up';
  if (x < 0) return 'down';
  return 'text-slate-400';
}

export function fmtTime(iso) {
  if (!iso) return '—';
  return iso.replace('T', ' ').slice(0, 19) + 'Z';
}
