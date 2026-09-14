<script setup>
import { onMounted, ref, computed, nextTick } from 'vue';
import * as echarts from 'echarts';
import { api, fmtMoney, fmtPct, pnlClass } from '../api';

const data = ref(null);
const err = ref('');
const showClosed = ref(true);

const summary = computed(() => data.value?.summary || null);
const daily = computed(() => {
  const h = summary.value?.history || [];
  return [...h].reverse(); // 新→旧
});
const trades = computed(() => (data.value?.positions || []).filter(p => showClosed.value || p.status === 'ACTIVE'));
const activeCount = computed(() => (data.value?.positions || []).filter(p => p.status === 'ACTIVE').length);

async function load() {
  try {
    data.value = await api.simulation();
    await nextTick();
    drawEquity();
  } catch (e) { err.value = e.message; }
}

function drawEquity() {
  const el = document.getElementById('shadow-chart');
  const h = summary.value?.history || [];
  if (!el || !h.length) return;
  const chart = echarts.init(el);
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { textStyle: { color: '#94a3b8' }, top: 0, data: ['总权益', '持仓市值'] },
    grid: { left: 56, right: 16, top: 30, bottom: 24 },
    xAxis: { type: 'category', data: h.map(r => r.date), axisLine: { lineStyle: { color: '#334155' } }, axisLabel: { color: '#64748b' } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: '#1e293b' } } },
    series: [
      { name: '总权益', type: 'line', smooth: true, showSymbol: false, data: h.map(r => r.total_equity), lineStyle: { width: 2, color: '#38bdf8' }, areaStyle: { color: 'rgba(56,189,248,.08)' } },
      { name: '持仓市值', type: 'line', smooth: true, showSymbol: false, data: h.map(r => r.market_value), lineStyle: { width: 1, color: '#a78bfa' } },
    ],
  });
}

const stColor = {
  ACTIVE: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25',
  CLOSED: 'bg-slate-700/40 text-slate-400 border-slate-600',
};

onMounted(load);
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-5 flex-wrap gap-3">
      <h1 class="text-xl font-semibold text-slate-100">影子盘 Shadow
        <span class="text-[11px] font-normal text-slate-500 ml-2">simulation/shadow_*.parquet · 候选/实验策略暗跑 (非已上策略)</span>
      </h1>
      <div class="text-[11px] text-slate-500">更新: {{ daily[0]?.date || '—' }}</div>
    </div>

    <div v-if="err" class="card p-3 mb-4 text-red-400 text-[13px]">{{ err }}</div>

    <!-- KPI -->
    <div v-if="summary" class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
      <div class="card p-4">
        <div class="card-title mb-2">最新总权益</div>
        <div class="text-2xl font-semibold mono">{{ summary.history?.length ? fmtMoney(summary.history[summary.history.length - 1].total_equity) : '—' }}</div>
        <div class="text-[11px] text-slate-500 mt-1">初始 {{ fmtMoney(summary.history?.[0]?.total_equity ?? 100000) }}</div>
      </div>
      <div class="card p-4">
        <div class="card-title mb-2">累计收益 (区间)</div>
        <div class="text-2xl font-semibold mono" :class="pnlClass(summary.total_return * 100)">{{ fmtPct(summary.total_return * 100) }}</div>
        <div class="text-[11px] text-slate-500 mt-1">{{ summary.history?.length || 0 }} 个交易日</div>
      </div>
      <div class="card p-4">
        <div class="card-title mb-2">持仓 / 已平仓</div>
        <div class="text-2xl font-semibold mono">{{ activeCount }} <span class="text-sm text-slate-500">active</span></div>
        <div class="text-[11px] text-slate-500 mt-1">已平 {{ summary.closed_count ?? '—' }} 笔 · 胜率 {{ summary.win_rate || '—' }}</div>
      </div>
      <div class="card p-4">
        <div class="card-title mb-2">已实现盈亏</div>
        <div class="text-2xl font-semibold mono" :class="pnlClass(summary.realized_pnl)">{{ fmtMoney(summary.realized_pnl) }}</div>
        <div class="text-[11px] text-slate-500 mt-1">来源 shadow_positions.parquet</div>
      </div>
    </div>

    <!-- 净值曲线 + 每日明细 -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
      <div class="card p-4 lg:col-span-2">
        <div class="card-title mb-2">影子盘净值 (shadow_daily.parquet)</div>
        <div id="shadow-chart" class="h-52"></div>
      </div>
      <div class="card overflow-hidden">
        <div class="px-4 pt-3.5 pb-2 card-title">日度明细</div>
        <table class="w-full text-[12px]">
          <thead>
            <tr class="text-left text-slate-500 border-b border-slate-800 text-[11px]">
              <th class="px-4 py-1.5">date</th><th class="px-2 py-1.5 text-right">权益</th>
              <th class="px-2 py-1.5 text-right">持仓</th><th class="px-4 py-1.5 text-right">日盈亏</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in daily" :key="r.date" class="border-b border-slate-800/40">
              <td class="px-4 py-1.5 mono text-slate-300">{{ r.date }}</td>
              <td class="px-2 py-1.5 mono text-right">{{ (+r.total_equity).toFixed(0) }}</td>
              <td class="px-2 py-1.5 mono text-right text-slate-500">{{ r.n_positions }}</td>
              <td class="px-4 py-1.5 mono text-right" :class="pnlClass(r.daily_pnl)">{{ (+(r.daily_pnl || 0)).toFixed(0) }}</td>
            </tr>
            <tr v-if="!daily.length"><td colspan="4" class="px-4 py-4 text-center text-slate-500">无日度记录</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 交易记录 -->
    <div class="card overflow-hidden mb-6">
      <div class="flex items-center justify-between px-4 pt-3.5 pb-2">
        <div class="card-title">影子持仓 / 交易记录 ({{ trades.length }})</div>
        <label class="flex items-center gap-1.5 text-[11px] text-slate-500 cursor-pointer">
          <input type="checkbox" v-model="showClosed" class="accent-cyan-500" /> 显示已平仓
        </label>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-[12px]">
          <thead>
            <tr class="text-left text-slate-500 border-b border-slate-800 text-[11px]">
              <th class="px-4 py-1.5">代码</th><th class="px-2 py-1.5">策略</th><th class="px-2 py-1.5">状态</th>
              <th class="px-2 py-1.5 text-right">建仓</th><th class="px-2 py-1.5 text-right">成本</th><th class="px-2 py-1.5 text-right">股数</th>
              <th class="px-2 py-1.5 text-right">平仓日</th><th class="px-2 py-1.5 text-right">盈亏</th><th class="px-2 py-1.5 text-right">盈亏%</th>
              <th class="px-4 py-1.5">平仓原因</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in trades" :key="p.symbol + p.entry_date" class="border-b border-slate-800/40 hover:bg-slate-800/20">
              <td class="px-4 py-1.5 mono text-slate-200">{{ p.symbol }}</td>
              <td class="px-2 py-1.5 text-slate-400">{{ p.strategy }}</td>
              <td class="px-2 py-1.5"><span class="text-[10px] px-1.5 py-0.5 rounded border" :class="stColor[p.status] || ''">{{ p.status }}</span></td>
              <td class="px-2 py-1.5 mono text-right text-slate-400">{{ p.entry_date }}</td>
              <td class="px-2 py-1.5 mono text-right">{{ p.entry_price }}</td>
              <td class="px-2 py-1.5 mono text-right">{{ p.shares }}</td>
              <td class="px-2 py-1.5 mono text-right text-slate-400">{{ p.exit_date || '—' }}</td>
              <td class="px-2 py-1.5 mono text-right" :class="pnlClass(p.pnl)">{{ fmtMoney(p.pnl) }}</td>
              <td class="px-2 py-1.5 mono text-right" :class="pnlClass(p.pnl_pct)">{{ p.pnl_pct != null ? (+p.pnl_pct * 100).toFixed(2) + '%' : '—' }}</td>
              <td class="px-4 py-1.5 text-slate-500 max-w-44 truncate">{{ p.exit_reason || '—' }}</td>
            </tr>
            <tr v-if="!trades.length"><td colspan="10" class="px-4 py-5 text-center text-slate-500">无记录</td></tr>
          </tbody>
        </table>
      </div>
      <div class="px-4 pb-2 text-[10px] text-slate-600">pnl/pnl_pct 为平仓时结算 · decision_id 关联决策包</div>
    </div>
  </div>
</template>
