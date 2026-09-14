<script setup>
import { onMounted, ref, computed } from 'vue';
import { api, fmtTime, pnlClass } from '../api';

const decisions = ref([]);
const err = ref('');
const detail = ref(null);
const loadingDetail = ref(false);
const statusFilter = ref('all');

const statusColor = {
  closed: 'bg-slate-600/30 text-slate-400 border-slate-600',
  monitoring: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/25',
  approved: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25',
  pending: 'bg-amber-500/15 text-amber-300 border-amber-500/25',
  rejected: 'bg-red-500/15 text-red-300 border-red-500/25',
};

const shown = computed(() =>
  statusFilter.value === 'all' ? decisions.value : decisions.value.filter(d => d.status === statusFilter.value)
);

const statusCounts = computed(() => {
  const m = {};
  decisions.value.forEach(d => { m[d.status] = (m[d.status] || 0) + 1; });
  return m;
});

async function load() {
  try {
    const d = await api.decisions();
    decisions.value = d.decisions;
  } catch (e) { err.value = e.message; }
}

async function open(d) {
  loadingDetail.value = true;
  detail.value = null;
  try {
    detail.value = await api.decision(d.package_id);
  } catch (e) {
    detail.value = { error: e.message };
  } finally {
    loadingDetail.value = false;
  }
}

function close() { detail.value = null; }

// ── 人工复核动作 (写操作, 与老 UI HTML 同语义) ──
const actBusy = ref('');
const actMsg = ref('');
const actErr = ref('');

function curStatus() {
  return detail.value?.human_review?.status || detail.value?.status || '';
}

async function act(kind, action, label, confirmMsg) {
  if (!detail.value) return;
  if (!window.confirm(confirmMsg)) return;
  actBusy.value = kind;
  actMsg.value = '';
  actErr.value = '';
  try {
    const pid = detail.value.package_id;
    let r;
    if (kind === 'review') r = await api.reviewDecision(pid, action);
    else if (kind === 'execute') r = await api.executeDecision(pid);
    else r = await api.closeDecision(pid);
    if (r && r.ok) {
      actMsg.value = `✓ ${label} 成功 → ${r.detail?.human_review?.status || ''}`;
      await load();
      const listItem = decisions.value.find(d => d.package_id === pid);
      if (listItem) await open(listItem);
    } else {
      actErr.value = (r && r.error) || '操作失败 (状态机不允许该流转?)';
    }
  } catch (e) {
    actErr.value = e.message;
  }
  actBusy.value = '';
}

function actApprove() {
  const buys = Object.keys(detail.value?.risk_audit?.candidate_weights || {}).length;
  act('review', 'approve', '批准建仓',
    `批准决策包将按 SELL 平仓 + BUY 建仓执行 (写 data/positions + account, 与老 UI approve 相同)。\n\n候选 ${buys} 只。确定批准?`);
}
function actReject() {
  act('review', 'reject', '拒绝', '拒绝后决策包进入 REJECTED 终态, 不可再操作。确定拒绝?');
}
function actExecute() {
  act('execute', '', '标记已执行', '仅状态流转 APPROVED→PARTIALLY_EXECUTED→MONITORING, 不改变持仓。确定?');
}
function actClose() {
  act('close', '', '关闭', '关闭后进入 CLOSED 终态。确定?');
}

function regClass(r) {
  return r === 'bear' ? 'text-red-400' : r === 'sideways_down' ? 'text-amber-300' : r === 'sideways_up' ? 'text-cyan-300' : 'text-emerald-400';
}

onMounted(load);
</script>

<template>
  <div class="grid grid-cols-1 lg:grid-cols-5 gap-4">
    <!-- 左侧：列表 -->
    <div class="lg:col-span-2">
      <h1 class="text-xl font-semibold text-slate-100 mb-5">决策包
        <span class="text-[11px] font-normal text-slate-500 ml-2">data/decisions/dp-*.json · {{ decisions.length }} 个</span>
      </h1>

      <div class="flex gap-1.5 mb-3 flex-wrap">
        <button @click="statusFilter='all'"
          class="text-[11px] px-2 py-1 rounded border"
          :class="statusFilter==='all' ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300' : 'border-slate-700 text-slate-400'">
          全部 {{ decisions.length }}</button>
        <button v-for="(c, st) in statusCounts" :key="st" @click="statusFilter=st"
          class="text-[11px] px-2 py-1 rounded border"
          :class="statusFilter===st ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300' : 'border-slate-700 text-slate-400'">
          {{ st }} {{ c }}</button>
      </div>

      <div v-if="err" class="card p-3 mb-3 text-red-400 text-[12px]">{{ err }}</div>

      <div class="space-y-2 max-h-[80vh] overflow-y-auto pr-1">
        <div v-for="d in shown" :key="d.package_id" @click="open(d)"
          class="card p-3 cursor-pointer hover:border-slate-600 transition-colors"
          :class="{ 'border-cyan-500/40': detail?.package_id === d.package_id }">
          <div class="flex items-center justify-between mb-1">
            <span class="mono text-[12px] text-slate-200">{{ d.date }}</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded border"
              :class="statusColor[d.status] || 'bg-slate-700/40 text-slate-400 border-slate-600'">{{ d.status }}</span>
          </div>
          <div class="flex items-center gap-3 text-[11px] text-slate-500">
            <span>regime <b :class="regClass(d.regime)">{{ d.regime }}</b></span>
            <span>conf {{ d.regime_confidence != null ? (d.regime_confidence * 100).toFixed(0) + '%' : '—' }}</span>
            <span class="mono">{{ Object.entries(d.signals || {}).map(([k, v]) => k + ':' + v).join(' ') || '—' }}</span>
          </div>
          <div class="flex items-center gap-2 mt-1.5 text-[10px]">
            <span v-if="d.passed" class="text-emerald-500">✓ 风控通过</span>
            <span v-else class="text-red-500">✗ 风控拦截</span>
            <span class="text-slate-600">review {{ d.reviewed ? '✓' : '✗' }} · exec {{ d.executed ? '✓' : '✗' }}</span>
          </div>
        </div>
        <div v-if="!shown.length" class="card p-5 text-center text-slate-500 text-[12px]">无匹配</div>
      </div>
    </div>

    <!-- 右侧：详情 -->
    <div class="lg:col-span-3">
      <div v-if="loadingDetail" class="card p-6 text-center text-slate-500 text-[13px]">加载中…</div>
      <template v-else-if="detail">
        <div v-if="detail.error" class="card p-4 text-red-400 text-[13px]">{{ detail.error }}
          <button @click="close" class="ml-3 text-slate-500 hover:text-slate-300">关闭</button>
        </div>
        <template v-else>
          <div class="card p-5">
            <div class="flex items-start justify-between mb-4">
              <div>
                <div class="card-title mb-1">决策包详情</div>
                <div class="mono text-slate-100 text-[15px]">{{ detail.package_id }}</div>
                <div class="text-[11px] text-slate-500 mt-1">date {{ detail.date }} · generated {{ fmtTime(detail.generated_at) }}</div>
              </div>
              <button @click="close" class="text-slate-500 hover:text-slate-300 text-[12px] border border-slate-700 rounded px-2 py-1">✕ 关闭</button>
            </div>

            <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
              <div class="border border-slate-800 rounded-lg p-2.5">
                <div class="card-title mb-1">市场状态</div>
                <div class="mono text-lg" :class="regClass(detail.regime.regime)">{{ detail.regime.regime }}</div>
                <div class="text-[10px] text-slate-500">conf {{ (detail.regime.confidence * 100).toFixed(0) }}% · exposure {{ (detail.regime.suggested_exposure * 100).toFixed(0) }}%</div>
              </div>
              <div class="border border-slate-800 rounded-lg p-2.5">
                <div class="card-title mb-1">风控审计</div>
                <div class="mono text-lg" :class="detail.risk_audit?.passed ? 'text-emerald-400' : 'text-red-400'">{{ detail.risk_audit?.passed ? '通过' : '拦截' }}</div>
                <div class="text-[10px] text-slate-500">cand {{ detail.risk_audit?.candidates_in }}→{{ detail.risk_audit?.candidates_out }}</div>
              </div>
              <div class="border border-slate-800 rounded-lg p-2.5">
                <div class="card-title mb-1">人工复核</div>
                <div class="mono text-lg text-slate-200">{{ detail.human_review?.reviewed ? '已复核' : '未复核' }}</div>
                <div class="text-[10px] text-slate-500">status {{ detail.human_review?.status }} · by {{ detail.human_review?.reviewer || '—' }}</div>
              </div>
              <div class="border border-slate-800 rounded-lg p-2.5">
                <div class="card-title mb-1">执行报告</div>
                <div class="mono text-lg text-slate-200">{{ detail.report?.n_buys ?? 0 }}买 / {{ detail.report?.n_sells ?? 0 }}卖</div>
                <div class="text-[10px] text-slate-500">invested {{ detail.report?.total_invested ?? 0 }}</div>
              </div>
            </div>

            <div class="card-title mb-2">regime.summary</div>
            <p class="text-[12px] text-slate-300 bg-slate-900/60 border border-slate-800 rounded p-2.5 mb-4">{{ detail.regime.summary || '—' }}</p>

            <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
              <div>
                <div class="card-title mb-2">信号 (strategy)</div>
                <div class="border border-slate-800 rounded-lg p-2.5 text-[12px]">
                  <div v-for="(v, k) in detail.strategy" :key="k" class="flex justify-between py-0.5">
                    <span class="text-slate-500">{{ k }}</span>
                    <span class="mono text-slate-300">{{ typeof v === 'object' ? JSON.stringify(v) : v }}</span>
                  </div>
                </div>
              </div>
              <div>
                <div class="card-title mb-2">候选权重 (risk_audit.candidate_weights)</div>
                <div class="border border-slate-800 rounded-lg p-2.5 text-[12px]">
                  <div v-for="(w, code) in (detail.risk_audit?.candidate_weights || {})" :key="code" class="flex justify-between py-0.5">
                    <span class="mono text-slate-300">{{ code }}</span>
                    <span class="mono text-slate-400">{{ (w * 100).toFixed(2) }}%</span>
                  </div>
                  <div v-if="!Object.keys(detail.risk_audit?.candidate_weights || {}).length" class="text-slate-600">无候选（空仓）</div>
                </div>
              </div>
            </div>

            <div class="card-title mb-2">validation → health</div>
            <div class="space-y-1.5 mb-4">
              <div v-for="(v, sid) in (detail.validation || {})" :key="sid"
                class="border border-slate-800 rounded-lg p-2.5 flex flex-wrap gap-x-6 gap-y-1 text-[12px]">
                <span class="mono text-slate-200 w-40">{{ sid }}</span>
                <span :class="v.health?.health_level === 'healthy' ? 'text-emerald-400' : 'text-amber-400'">{{ v.health?.health_level }}</span>
                <span class="text-slate-500">score <b class="mono text-slate-300">{{ v.health?.health_score }}</b></span>
                <span class="text-slate-500">stage {{ v.stage }} · {{ v.recommendation }}</span>
              </div>
            </div>

            <div class="card-title mb-2">状态流转 (human_review.status_history)</div>
            <div class="flex flex-wrap items-center gap-1.5 text-[11px]">
              <template v-for="(h, i) in (detail.human_review?.status_history || [])" :key="i">
                <span class="px-2 py-0.5 rounded border border-slate-700 text-slate-300 mono">{{ h.to_status }}</span>
                <span v-if="i < detail.human_review.status_history.length - 1" class="text-slate-600">→</span>
              </template>
              <span v-if="!detail.human_review?.status_history?.length" class="text-slate-600">—</span>
            </div>

            <!-- 操作条: 按当前状态可用 -->
            <div class="mt-5 pt-4 border-t border-slate-800">
              <div class="card-title mb-2">人工复核操作 <span class="text-[10px] font-normal text-slate-600">当前状态: {{ curStatus() }} · 与老 UI 同语义 (approve=建仓)</span></div>
              <div class="flex flex-wrap items-center gap-2">
                <button v-if="['pending', 'modified'].includes(curStatus())" @click="actApprove" :disabled="!!actBusy"
                  class="text-[12px] px-3 py-1.5 rounded-md bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/25 disabled:opacity-50">
                  {{ actBusy === 'review' ? '处理中…' : '✓ 批准建仓' }}</button>
                <button v-if="curStatus() === 'pending'" @click="actReject" :disabled="!!actBusy"
                  class="text-[12px] px-3 py-1.5 rounded-md bg-red-500/10 border border-red-500/40 text-red-300 hover:bg-red-500/20 disabled:opacity-50">✗ 拒绝</button>
                <button v-if="['approved', 'partially_executed'].includes(curStatus())" @click="actExecute" :disabled="!!actBusy"
                  class="text-[12px] px-3 py-1.5 rounded-md bg-cyan-500/15 border border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/25 disabled:opacity-50">
                  {{ actBusy === 'execute' ? '处理中…' : '▶ 标记已执行' }}</button>
                <button v-if="curStatus() === 'monitoring'" @click="actClose" :disabled="!!actBusy"
                  class="text-[12px] px-3 py-1.5 rounded-md border border-slate-600 text-slate-300 hover:bg-slate-700/50 disabled:opacity-50">☑ 关闭</button>
                <span v-if="!['pending', 'modified', 'approved', 'partially_executed', 'monitoring'].includes(curStatus())"
                  class="text-[11px] text-slate-600">当前状态无可用操作 ({{ curStatus() || '—' }})</span>
              </div>
              <div v-if="actMsg" class="text-[12px] text-emerald-400 mt-2">{{ actMsg }}</div>
              <div v-if="actErr" class="text-[12px] text-red-400 mt-2">{{ actErr }}</div>
            </div>
          </div>
        </template>
      </template>
      <div v-else class="card p-10 text-center text-slate-600 text-[13px]">← 点击左侧决策包查看详情</div>
    </div>
  </div>
</template>
