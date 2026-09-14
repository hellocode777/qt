<script setup>
import { onMounted, ref, computed, nextTick, onUnmounted } from 'vue';
import * as echarts from 'echarts';
import { api } from '../api';

const sh = ref(null);        // /system-health
const fh = ref(null);        // /health/factors overview
const st = ref([]);          // /health/strategies
const dq = ref(null);        // /data-quality
const errs = ref([]);
const loading = ref(false);
const fetchedAt = ref('');
const filter = ref('all');   // 因子 stage 过滤
const expanded = ref(null);  // 展开的因子名 (detail + IC 曲线)
let timer = null;

// ---- stage 视觉映射 ----
const stageStyle = {
  healthy:   { label: '健康',    cls: 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10' },
  warning:   { label: '警告',    cls: 'text-amber-300 border-amber-500/30 bg-amber-500/10' },
  weakening: { label: '减弱',    cls: 'text-amber-300 border-amber-500/30 bg-amber-500/10' },
  degraded:  { label: '衰减',    cls: 'text-red-400 border-red-500/30 bg-red-500/10' },
  stale:     { label: '失效',    cls: 'text-red-400 border-red-500/30 bg-red-500/10' },
  retired:   { label: '退役',    cls: 'text-slate-500 border-slate-600 bg-slate-700/20' },
  archived:  { label: '归档',    cls: 'text-slate-500 border-slate-600 bg-slate-700/20' },
};
const sevOrder = { degraded: 0, stale: 1, weakening: 2, warning: 3, healthy: 4, retired: 5, archived: 6 };

// ---- watchdog 状态 ----
function wdState(w) {
  if (!w.has_ping) return { txt: '无心跳', cls: 'text-red-400' };
  if (w.age_hours === null) return { txt: '—', cls: 'text-slate-500' };
  if (w.age_hours >= 30) return { txt: `${w.age_hours}h 未心跳`, cls: 'text-red-400' };
  if (w.age_hours >= 26) return { txt: `${w.age_hours}h 偏旧`, cls: 'text-amber-300' };
  return { txt: `${w.age_hours}h 前`, cls: 'text-emerald-400' };
}

// ---- 系统状态视觉 ----
const stateMeta = computed(() => {
  const s = sh.value?.system_state;
  if (!s) return null;
  const map = {
    NORMAL:  { cls: 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10', label: s.label || '正常' },
    WARNING: { cls: 'text-amber-300 border-amber-500/30 bg-amber-500/10', label: s.label || '警告' },
    PAUSED:  { cls: 'text-red-400 border-red-500/30 bg-red-500/10', label: s.label || '暂停' },
    STOP:    { cls: 'text-red-400 border-red-500/30 bg-red-500/10', label: s.label || '熔断' },
  };
  return map[s.state] || { cls: 'text-slate-400 border-slate-600 bg-slate-800/50', label: s.label || s.state };
});

const sortFactors = computed(() => {
  if (!fh.value) return [];
  const arr = [...(fh.value.factors || [])];
  if (filter.value !== 'all') arr = arr.filter(f => f.stage === filter.value);
  return arr.sort((a, b) => (sevOrder[a.stage] ?? 9) - (sevOrder[b.stage] ?? 9) || String(a.name).localeCompare(String(b.name)));
});

const factorStats = computed(() => {
  const f = fh.value;
  if (!f) return [];
  const picks = ['production', 'validated', 'weakening', 'degraded', 'stale', 'retired'];
  return picks.map(k => ({ key: k, v: f.counts?.[k] ?? 0 })).filter(x => x.key !== 'validated' || x.v > 0 || true);
});

const recs = computed(() => (fh.value?.recommendations || []).slice(0, 8));
const redundantPairs = computed(() => (fh.value?.correlation?.redundant || []).slice(0, 5));
const healthyCount = computed(() => fh.value?.n_healthy ?? 0);

async function load() {
  loading.value = true;
  const tasks = [
    api.systemHealth().then(d => (sh.value = d)).catch(e => errs.value.push('system-health: ' + e.message)),
    api.healthFactors().then(d => (fh.value = d)).catch(e => errs.value.push('health/factors: ' + e.message)),
    api.healthStrategies().then(d => (st.value = d.strategies || [])).catch(e => errs.value.push('health/strategies: ' + e.message)),
    api.dataQuality().then(d => (dq.value = d)).catch(e => errs.value.push('data-quality: ' + e.message)),
  ];
  await Promise.all(tasks);
  fetchedAt.value = new Date().toLocaleString('zh-CN', { hour12: false });
  loading.value = false;
  await nextTick();
  drawScoreHistory();
  drawQuality();
}

// 健康分历史曲线 (system_health_log.parquet → /system-health history)
function drawScoreHistory() {
  const el = document.getElementById('score-chart');
  if (!el) return;
  const inst = echarts.getInstanceByDom(el);
  if (inst) inst.dispose();
  if (!sh.value?.history?.length) return;
  const h = [...sh.value.history].sort((a, b) => String(a.timestamp).localeCompare(String(b.timestamp)));
  const dates = h.map(r => (r.date || String(r.timestamp).slice(0, 10)));
  const chart = echarts.init(el);
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { textStyle: { color: '#94a3b8' }, top: 0, data: ['策略健康分'] },
    grid: { left: 44, right: 16, top: 30, bottom: 22 },
    xAxis: { type: 'category', data: dates, axisLine: { lineStyle: { color: '#334155' } }, axisLabel: { color: '#64748b' } },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: '#1e293b' } } },
    series: [{
      name: '策略健康分', type: 'line', smooth: true, showSymbol: false,
      data: h.map(r => r.strategy_health_score),
      lineStyle: { color: '#22d3ee', width: 2 },
      areaStyle: { color: 'rgba(34,211,238,.08)' },
    }],
  });
}

// 数据质量时间线 (reports/data_quality_*.json → PASS/FAIL + new_rows)
function drawQuality() {
  const el = document.getElementById('quality-chart');
  if (!el) return;
  const inst = echarts.getInstanceByDom(el);
  if (inst) inst.dispose();
  const reps = dq.value?.reports || [];
  if (!reps.length) return;
  const chart = echarts.init(el);
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { textStyle: { color: '#94a3b8' }, top: 0, data: ['新增行数', '总行数'] },
    grid: { left: 56, right: 16, top: 30, bottom: 22 },
    xAxis: { type: 'category', data: reps.map(r => r.date), axisLine: { lineStyle: { color: '#334155' } }, axisLabel: { color: '#64748b' } },
    yAxis: [
      { type: 'value', axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: '#1e293b' } } },
      { type: 'value', axisLabel: { color: '#64748b', formatter: '{value}M' }, splitLine: { show: false } },
    ],
    series: [
      { name: '新增行数', type: 'bar', data: reps.map(r => r.new_rows), itemStyle: { color: (p) => (reps[p.dataIndex]?.status === 'FAIL' ? '#f87171' : '#38bdf8') } },
      { name: '总行数', type: 'line', yAxisIndex: 1, smooth: true, showSymbol: false, data: reps.map(r => r.rows_after), lineStyle: { color: '#64748b', width: 1.2, type: 'dashed' } },
    ],
  });
}

// 展开因子 → detail + IC 曲线
async function toggleFactor(name) {
  if (expanded.value === name) { expanded.value = null; return; }
  expanded.value = name;
  await nextTick();
  try {
    const d = await api.healthFactor(name);
    const el = document.getElementById('ic-chart-' + name.replace(/[^a-zA-Z0-9_]/g, '_'));
    if (!el || !d?.chart_dates?.length) return;
    const chart = echarts.init(el);
    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      legend: { textStyle: { color: '#94a3b8' }, top: 0, data: ['IC_30d', 'IC_90d', 'IC_IR'] },
      grid: { left: 44, right: 16, top: 30, bottom: 22 },
      xAxis: { type: 'category', data: d.chart_dates, axisLine: { lineStyle: { color: '#334155' } }, axisLabel: { color: '#64748b' } },
      yAxis: { type: 'value', axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: '#1e293b' } } },
      series: [
        { name: 'IC_30d', type: 'line', smooth: true, showSymbol: false, data: d.chart_ic_30d || [], lineStyle: { color: '#f87171', width: 1.5 } },
        { name: 'IC_90d', type: 'line', smooth: true, showSymbol: false, data: d.chart_ic_90d || [], lineStyle: { color: '#fbbf24', width: 1.5 } },
        { name: 'IC_IR', type: 'line', smooth: true, showSymbol: false, data: d.chart_ic_ir || [], lineStyle: { color: '#22d3ee', width: 1.5 } },
      ],
    });
  } catch (e) {
    errs.value.push(`factor detail ${name}: ${e.message}`);
  }
}

function nfmt(x) {
  if (x === null || x === undefined || x === '') return '—';
  const n = Number(x);
  if (Number.isNaN(n)) return x;
  return n.toFixed(4);
}

onMounted(() => {
  load();
  timer = setInterval(load, 60000); // 60s 自动刷新 (调度产物低频变化)
});
onUnmounted(() => { if (timer) clearInterval(timer); });
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-5 flex-wrap gap-3">
      <h1 class="text-xl font-semibold text-slate-100">监控 Monitor
        <span class="text-[11px] font-normal text-slate-500 ml-2">系统状态 · watchdog 心跳 · 因子/策略健康</span>
      </h1>
      <div class="flex items-center gap-3 text-[11px] text-slate-500">
        <span v-if="fetchedAt">刷新于 {{ fetchedAt }}</span>
        <button @click="load" class="px-3 py-1.5 rounded-md border border-slate-700 hover:border-cyan-500/50 hover:text-cyan-300 transition-colors"
          :disabled="loading">{{ loading ? '加载中…' : '↻ 刷新' }}</button>
      </div>
    </div>

    <div v-if="errs.length" class="card p-3 mb-4 border-red-500/30">
      <div class="text-[12px] text-red-400">{{ errs.join('; ') }}</div>
    </div>

    <!-- ── 系统状态 + 最新健康 ── -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
      <div class="card p-4">
        <div class="card-title mb-2">系统状态 (KillSwitch)</div>
        <template v-if="stateMeta">
          <div class="flex items-center gap-2 mb-2">
            <span class="text-[12px] px-2 py-0.5 rounded-md border mono" :class="stateMeta.cls">{{ sh.system_state.state }}</span>
            <span class="text-sm text-slate-300">{{ sh.system_state.is_blocked ? '🔒 禁止开仓' : '✅ 允许开仓' }}</span>
          </div>
          <div class="text-[12px] text-slate-400 leading-relaxed">{{ sh.system_state.reason || '—' }}</div>
          <div class="text-[10px] text-slate-600 mt-2">来源 {{ sh.system_state.source || '—' }} · {{ (sh.system_state.timestamp || '').slice(0, 16) }} · 转换 {{ sh.system_state.n_transitions ?? '—' }} 次</div>
        </template>
        <div v-else class="text-slate-500 text-[12px]">—</div>
      </div>

      <div class="card p-4">
        <div class="card-title mb-2">最新健康日志</div>
        <template v-if="sh?.latest_health">
          <div class="flex items-center gap-2 mb-2">
            <span class="text-[12px] px-2 py-0.5 rounded-md border mono text-slate-300">{{ sh.latest_health.regime }}</span>
            <span class="text-[12px] px-2 py-0.5 rounded-md border mono"
              :class="sh.latest_health.kill_switch_level === 'NORMAL' ? 'text-emerald-400 border-emerald-500/30' : 'text-red-400 border-red-500/30'">
              {{ sh.latest_health.kill_switch_level }}</span>
            <span class="text-[12px] text-slate-400">action={{ sh.latest_health.action ?? '—' }}</span>
          </div>
          <div class="flex justify-between text-[12px] mb-1">
            <span class="text-slate-500">策略健康分</span>
            <span class="mono" :class="(sh.latest_health.strategy_health_score ?? 100) >= 80 ? 'text-emerald-400' : 'text-amber-300'">
              {{ sh.latest_health.strategy_health_score ?? '—' }}/100</span>
          </div>
          <div class="flex justify-between text-[12px] mb-1">
            <span class="text-slate-500">模型衰减阶段</span>
            <span class="mono text-slate-300">{{ sh.latest_health.model_decay_stage ?? '—' }}</span>
          </div>
          <div class="flex justify-between text-[12px]">
            <span class="text-slate-500">告警</span>
            <span class="mono" :class="(sh.latest_health.n_alerts || 0) > 0 ? 'text-red-400' : 'text-slate-500'">{{ sh.latest_health.n_alerts ?? 0 }}</span>
          </div>
          <div class="text-[10px] text-slate-600 mt-2">日志 {{ sh.latest_health.date || '—' }} · {{ sh.latest_health.alerts_summary || '无' }}</div>
        </template>
        <div v-else class="text-slate-500 text-[12px]">无健康日志</div>
      </div>

      <div class="card p-4">
        <div class="card-title mb-2">watchdog 心跳</div>
        <template v-if="sh?.watchdog?.length">
          <div class="space-y-1.5 text-[12px]">
            <div v-for="w in sh.watchdog" :key="w.name" class="flex justify-between items-center">
              <span class="text-slate-400">
                <span class="inline-block w-2 h-2 rounded-full mr-1.5 align-middle"
                  :class="!w.has_ping ? 'bg-red-500' : (w.age_hours ?? 99) >= 30 ? 'bg-red-500' : (w.age_hours ?? 0) >= 26 ? 'bg-amber-400' : 'bg-emerald-400'"></span>
                {{ w.name }}
              </span>
              <span class="mono" :class="wdState(w).cls">{{ wdState(w).txt }}</span>
            </div>
          </div>
          <div class="text-[10px] text-slate-600 mt-2">期望: {{ sh.watchdog[0].expected?.startsWith('工作日') ? '工作日定时 (scheduler)' : '' }} · ping 文件内容=UTC ISO</div>
        </template>
        <div v-else class="text-slate-500 text-[12px]">—</div>
      </div>
    </div>

    <!-- ── 健康分历史 + watchdog 明细 ── -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
      <div class="card p-4 lg:col-span-2">
        <div class="card-title mb-2">策略健康分历史 (system_health_log.parquet)</div>
        <div id="score-chart" class="h-44"></div>
      </div>
      <div class="card overflow-hidden">
        <div class="px-4 pt-3.5 pb-2 card-title">watchdog 明细 (monitoring/watchdog/*.ping)</div>
        <table class="w-full text-[12px]">
          <thead>
            <tr class="text-left text-slate-500 border-b border-slate-800 text-[11px]">
              <th class="px-4 py-1.5">job</th><th class="px-2 py-1.5">期望</th>
              <th class="px-4 py-1.5 text-right">最后心跳</th><th class="px-4 py-1.5 text-right">距今</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="w in sh?.watchdog || []" :key="w.name" class="border-b border-slate-800/40">
              <td class="px-4 py-1.5 mono text-slate-300">{{ w.name }}</td>
              <td class="px-2 py-1.5 text-slate-500">{{ w.expected }}</td>
              <td class="px-4 py-1.5 mono text-right text-slate-400">{{ w.last_ping ? w.last_ping.slice(0, 16).replace('T', ' ') : '—' }}</td>
              <td class="px-4 py-1.5 mono text-right" :class="wdState(w).cls">{{ wdState(w).txt }}</td>
            </tr>
            <tr v-if="!(sh?.watchdog || []).length"><td colspan="4" class="px-4 py-4 text-center text-slate-500">—</td></tr>
          </tbody>
        </table>
        <div class="px-4 pb-2 text-[10px] text-slate-600">缺失心跳=job 未跑/被熔断跳过 (如 pre_close_check)</div>
      </div>
    </div>

    <!-- ── 因子健康 ── -->
    <div class="card p-4 mb-6">
      <div class="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div class="card-title">因子健康 (factor_health.parquet · 最近评估日)</div>
        <div class="flex items-center gap-1.5 flex-wrap">
          <span v-for="s in factorStats" :key="s.key"
            class="text-[10px] px-1.5 py-0.5 rounded border border-slate-700 text-slate-500">
            {{ s.key }} <b class="text-slate-300">{{ s.v }}</b></span>
          <span class="text-[10px] px-1.5 py-0.5 rounded border border-emerald-500/30 text-emerald-400">
            healthy <b>{{ healthyCount }}</b></span>
          <span class="text-[10px] px-1.5 py-0.5 rounded border border-red-500/30 text-red-400">
            degraded <b>{{ fh?.n_degraded ?? '—' }}</b></span>
          <select v-model="filter"
            class="bg-slate-900 border border-slate-700 rounded-md px-2 py-1 text-[11px] focus:outline-none">
            <option value="all">全部因子</option>
            <option value="degraded">仅衰减</option>
            <option value="weakening">仅减弱</option>
            <option value="warning">仅警告</option>
            <option value="healthy">仅健康</option>
            <option value="stale">仅失效</option>
          </select>
        </div>
      </div>

      <div v-if="recs.length" class="mb-3">
        <div class="text-[11px] text-amber-300/90 mb-1.5">⚠ 推荐动作 ({{ fh?.recommendations?.length || 0 }} 条, 显示前 {{ recs.length }})</div>
        <div class="space-y-1">
          <div v-for="(r, i) in recs" :key="i" class="text-[12px] leading-snug flex gap-2 items-baseline">
            <span class="mono shrink-0" :class="r.severity === 'danger' ? 'text-red-400' : 'text-amber-300'">{{ r.factor }}</span>
            <span class="text-slate-400">{{ r.message }} <span class="text-slate-600">→ {{ r.action }}</span></span>
          </div>
        </div>
      </div>

      <div v-if="redundantPairs.length" class="mb-3">
        <div class="text-[11px] text-slate-500 mb-1.5">冗余因子对 (相关度 ≥ {{ fh?.correlation?.threshold ?? '—' }})</div>
        <div class="flex flex-wrap gap-1.5">
          <span v-for="(p, i) in redundantPairs" :key="i" class="text-[11px] px-1.5 py-0.5 rounded border border-slate-700 text-slate-400 mono">{{ p }}</span>
        </div>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-[12px]">
          <thead>
            <tr class="text-left text-slate-500 border-b border-slate-800 text-[11px]">
              <th class="px-2 py-1.5">因子</th><th class="px-2 py-1.5">阶段</th>
              <th class="px-2 py-1.5 text-right">IC_30d</th><th class="px-2 py-1.5 text-right">IC_90d</th>
              <th class="px-2 py-1.5 text-right">IC_IR</th><th class="px-2 py-1.5 text-right">decay/日</th>
              <th class="px-2 py-1.5 text-right">N天</th><th class="px-2 py-1.5">摘要</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="f in sortFactors" :key="f.name">
              <tr class="border-b border-slate-800/40 hover:bg-slate-800/20 cursor-pointer align-top"
                @click="toggleFactor(f.name)">
                <td class="px-2 py-1.5 mono text-slate-200">{{ f.name }}</td>
                <td class="px-2 py-1.5">
                  <span class="text-[10px] px-1.5 py-0.5 rounded border" :class="(stageStyle[f.stage] || stageStyle.healthy).cls">
                    {{ (stageStyle[f.stage] || {}).label || f.stage }}</span>
                </td>
                <td class="px-2 py-1.5 mono text-right" :class="Number(f.ic_30d) < 0 ? 'text-red-400' : 'text-emerald-400'">{{ nfmt(f.ic_30d) }}</td>
                <td class="px-2 py-1.5 mono text-right" :class="Number(f.ic_90d) < 0 ? 'text-red-400' : 'text-emerald-400'">{{ nfmt(f.ic_90d) }}</td>
                <td class="px-2 py-1.5 mono text-right text-slate-300">{{ nfmt(f.ic_ir) }}</td>
                <td class="px-2 py-1.5 mono text-right" :class="Number(f.ic_decay_rate) < -0.0005 ? 'text-red-400' : 'text-slate-300'">{{ nfmt(f.ic_decay_rate) }}</td>
                <td class="px-2 py-1.5 mono text-right text-slate-500">{{ f.n_days ?? '—' }}</td>
                <td class="px-2 py-1.5 text-slate-500 max-w-72">{{ f.summary || '' }}</td>
              </tr>
              <tr v-if="expanded === f.name">
                <td colspan="8" class="px-4 py-2 bg-slate-900/60">
                  <div class="flex flex-wrap justify-between items-center gap-2 mb-1 text-[12px]">
                    <span class="text-slate-300">{{ f.name }} 详情 (factor_detail, IC 平滑曲线)</span>
                    <span class="text-[11px] text-slate-500">{{ f.recommended_action || '' }}</span>
                  </div>
                  <div :id="'ic-chart-' + f.name.replace(/[^a-zA-Z0-9_]/g, '_')" class="h-36"></div>
                </td>
              </tr>
            </template>
            <tr v-if="!sortFactors.length"><td colspan="8" class="px-4 py-5 text-center text-slate-500">无因子数据</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ── 策略健康 ── -->
    <div class="card overflow-hidden mb-6">
      <div class="px-4 pt-3.5 pb-2 card-title">策略健康 (strategy_health.parquet · {{ st[0]?.data_date || '—' }})</div>
      <div class="overflow-x-auto">
        <table class="w-full text-[12px]">
          <thead>
            <tr class="text-left text-slate-500 border-b border-slate-800 text-[11px]">
              <th class="px-4 py-1.5">策略</th><th class="px-2 py-1.5 text-right">健康分</th>
              <th class="px-2 py-1.5">级别</th><th class="px-2 py-1.5">趋势</th>
              <th class="px-2 py-1.5">信号</th><th class="px-2 py-1.5">告警</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in st" :key="s.strategy_id" class="border-b border-slate-800/40">
              <td class="px-4 py-2 mono text-slate-200">{{ s.strategy_id }}</td>
              <td class="px-2 py-2 mono text-right" :class="(s.health_score ?? 0) >= 80 ? 'text-emerald-400' : 'text-amber-300'">
                {{ s.health_score ?? '—' }}</td>
              <td class="px-2 py-2">
                <span class="text-[10px] px-1.5 py-0.5 rounded border"
                  :class="s.health_level === 'healthy' ? 'text-emerald-400 border-emerald-500/30' : 'text-amber-300 border-amber-500/30'">
                  {{ s.health_level_display || s.health_level }}</span>
              </td>
              <td class="px-2 py-2 text-slate-400">{{ s.trend_icon || '' }} {{ s.trend || '—' }}</td>
              <td class="px-2 py-2 text-slate-500 text-[11px]">{{ s.signal_summary || '—' }}</td>
              <td class="px-2 py-2 text-[11px]" :class="s.n_alerts ? 'text-red-400' : 'text-slate-600'">
                {{ s.n_alerts ? s.alerts?.join('; ') : '无' }}</td>
            </tr>
            <tr v-if="!st.length"><td colspan="6" class="px-4 py-4 text-center text-slate-500">无策略健康记录</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ── 数据质量时间线 ── -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
      <div class="card p-4 lg:col-span-2">
        <div class="card-title mb-2">数据质量 (reports/data_quality_*.json)</div>
        <div id="quality-chart" class="h-44"></div>
        <div class="text-[10px] text-slate-600 mt-1">新增行数柱 = 每次日更增量 · 红柱 = 当日 FAIL</div>
      </div>
      <div class="card overflow-hidden">
        <div class="px-4 pt-3.5 pb-2 card-title">最新报告 ({{ dq?.reports?.length ? dq.reports[dq.reports.length - 1].date : '—' }})</div>
        <template v-if="dq?.reports?.length">
          <div class="px-4 pb-3 text-[12px] space-y-1.5">
            <div class="flex justify-between"><span class="text-slate-500">整体状态</span>
              <span class="mono" :class="(dq.reports[dq.reports.length - 1].status || '') === 'PASS' ? 'text-emerald-400' : 'text-red-400'">
                {{ dq.reports[dq.reports.length - 1].status || '—' }}</span></div>
            <div class="flex justify-between"><span class="text-slate-500">总行数</span>
              <span class="mono text-slate-300">{{ (dq.reports[dq.reports.length - 1].rows_after || 0).toLocaleString() }}</span></div>
            <div class="flex justify-between"><span class="text-slate-500">新增行</span>
              <span class="mono text-slate-300">{{ (dq.reports[dq.reports.length - 1].new_rows || 0).toLocaleString() }}</span></div>
            <div class="flex justify-between"><span class="text-slate-500">股票数</span>
              <span class="mono text-slate-300">{{ dq.reports[dq.reports.length - 1].symbols ?? '—' }}</span></div>
            <div class="pt-1">
              <div class="text-slate-500 mb-1">逐项检查</div>
              <div class="flex flex-wrap gap-1">
                <span v-for="(v, k) in dq.reports[dq.reports.length - 1].checks || {}" :key="k"
                  class="text-[10px] px-1.5 py-0.5 rounded border border-slate-700"
                  :class="v === 'pass' ? 'text-emerald-400' : 'text-red-400'">{{ k }}:{{ v }}</span>
              </div>
            </div>
            <div class="text-[10px] text-slate-600 pt-1">sha256 {{ (dq.reports[dq.reports.length - 1].sha256 || '').slice(0, 12) }}…</div>
          </div>
        </template>
        <div v-else class="px-4 pb-4 text-slate-500 text-[12px]">无质量报告</div>
      </div>
    </div>

    <div class="text-[10px] text-slate-600 leading-relaxed">
      数据源: qp/data/monitoring/ (system_state/system_health_log/factor_health/factor_ic_series/strategy_health/watchdog)
      · 口径 = qp /health HTML 页同一服务层 (FactorHealthService/HealthService), 非前端重算
      · 期望频率来自 qp scheduler 注册 (工作日定时), 非执行依据
    </div>
  </div>
</template>
