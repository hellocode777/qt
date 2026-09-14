<script setup>
import { onMounted, ref, nextTick } from 'vue';
import * as echarts from 'echarts';
import { api, fmtTime, fmtPct } from '../api';

const experiments = ref([]);
const err = ref('');
const selected = ref(null);   // 列表项
const detail = ref(null);     // 实验详情 json
const nav = ref(null);
const trades = ref(null);
const loading = ref(false);
const expandPeriod = ref(null);
// 对比模式: 勾选 2-4 个有 NAV 的实验归一化叠线
const compareSel = ref([]);
const compareNavs = ref({});
const MAX_COMPARE = 4;

async function toggleCompare(e) {
  if (!e.has_nav) return;
  const id = e.experiment_id;
  const i = compareSel.value.indexOf(id);
  if (i >= 0) {
    compareSel.value.splice(i, 1);
    delete compareNavs.value[id];
  } else {
    if (compareSel.value.length >= MAX_COMPARE) {
      alert(`最多对比 ${MAX_COMPARE} 个实验`);
      return;
    }
    compareSel.value.push(id);
    compareNavs.value = { ...compareNavs.value, [id]: null };
    try {
      const n = await api.experimentNav(id);
      compareNavs.value = { ...compareNavs.value, [id]: n.has_data ? n : null };
    } catch (ex) {
      compareNavs.value = { ...compareNavs.value, [id]: null };
    }
  }
  await nextTick();
  drawCompare();
}

function shortName(id) { return id.replace('multifactor_', ''); }

function drawCompare() {
  const el = document.getElementById('compare-chart');
  if (!el) return;
  const inst = echarts.getInstanceByDom(el);
  if (inst) inst.dispose();
  const entries = compareSel.value.map(id => ({ id, nav: compareNavs.value[id] }))
    .filter(x => x.nav && x.nav.portfolio && x.nav.portfolio.length);
  if (!entries.length) return;
  const chart = echarts.init(el);
  const palette = ['#38bdf8', '#f87171', '#fbbf24', '#a78bfa'];
  const series = entries.map((x, i) => {
    const vals = x.nav.portfolio;
    const first = vals.find(v => v != null);
    return {
      name: shortName(x.id), type: 'line', smooth: true, showSymbol: false,
      data: vals.map(v => (v != null && first ? +(v / first * 100).toFixed(2) : null)),
      lineStyle: { width: 1.6, color: palette[i % 4] },
    };
  });
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { textStyle: { color: '#94a3b8' }, top: 0, type: 'scroll' },
    grid: { left: 50, right: 16, top: 30, bottom: 24 },
    xAxis: { type: 'category', data: entries[0].nav.dates, axisLabel: { color: '#64748b' }, axisLine: { lineStyle: { color: '#334155' } } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: '#1e293b' } } },
    series,
  });
}

async function clearCompare() {
  compareSel.value = [];
  compareNavs.value = {};
  await nextTick();
  drawCompare();
}

async function load() {
  try {
    const d = await api.experiments();
    experiments.value = d.experiments;
    if (d.experiments.length) await select(d.experiments[0]);
  } catch (e) { err.value = e.message; }
}

async function select(e) {
  selected.value = e;
  loading.value = true;
  detail.value = null;
  nav.value = null;
  trades.value = null;
  expandPeriod.value = null;
  try {
    const [d, n, t] = await Promise.all([
      api.experiment(e.experiment_id),
      api.experimentNav(e.experiment_id),
      api.experimentTrades(e.experiment_id),
    ]);
    detail.value = d;
    nav.value = n.has_data ? n : null;
    trades.value = t && !t.error ? t : null;
    loading.value = false;      // 必须在 nextTick 前置 false → 详情分支才会渲染
    await nextTick();
    drawNav();
  } catch (ex) {
    err.value = ex.message;
  } finally {
    loading.value = false;
  }
}

function drawNav() {
  const el = document.getElementById('exp-nav-chart');
  if (!el || !nav.value) return;
  const chart = echarts.init(el);
  const series = [
    {
      name: '组合净值', type: 'line', smooth: true, showSymbol: false,
      data: nav.value.portfolio, lineStyle: { width: 1.8, color: '#38bdf8' },
    },
  ];
  if (nav.value.benchmark) {
    series.push({
      name: '基准', type: 'line', smooth: true, showSymbol: false,
      data: nav.value.benchmark, lineStyle: { width: 1.2, color: '#64748b', type: 'dashed' },
    });
  }
  if (nav.value.drawdown) {
    series.push({
      name: '回撤', type: 'line', yAxisIndex: 1, showSymbol: false,
      data: nav.value.drawdown.map(x => x != null ? +(x * 100).toFixed(2) : null),
      lineStyle: { width: 1, color: '#f87171' }, areaStyle: { color: 'rgba(248,113,113,.08)' },
    });
  }
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { textStyle: { color: '#94a3b8' }, top: 0 },
    grid: { left: 60, right: 50, top: 32, bottom: 24 },
    xAxis: { type: 'category', data: nav.value.dates, axisLabel: { color: '#64748b' }, axisLine: { lineStyle: { color: '#334155' } } },
    yAxis: [
      { type: 'value', scale: true, axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: '#1e293b' } } },
      { type: 'value', scale: true, axisLabel: { color: '#64748b', formatter: '{value}%' }, splitLine: { show: false } },
    ],
    series,
  });
}

const cellColor = {
  buy: 'bg-emerald-500/60',
  sell: 'bg-red-500/60',
  hold: 'bg-cyan-500/20',
  none: 'bg-slate-800/40',
};

onMounted(load);
</script>

<template>
  <div class="grid grid-cols-1 lg:grid-cols-5 gap-4">
    <!-- 左: 实验列表 -->
    <div class="lg:col-span-2">
      <h1 class="text-xl font-semibold text-slate-100 mb-5">回测实验
        <span class="text-[11px] font-normal text-slate-500 ml-2">data/experiments/multifactor_*.json · {{ experiments.length }} 个</span>
      </h1>
      <div v-if="err" class="card p-3 mb-3 text-red-400 text-[12px]">{{ err }}</div>
      <div class="space-y-2 max-h-[80vh] overflow-y-auto pr-1">
        <div v-for="e in experiments" :key="e.experiment_id" @click="select(e)"
          class="card p-3 cursor-pointer hover:border-slate-600 transition-colors"
          :class="{ 'border-cyan-500/40': selected?.experiment_id === e.experiment_id }">
          <div class="flex items-center justify-between mb-1">
            <span class="mono text-[12px] text-slate-200">{{ e.experiment_id.replace('multifactor_', '') }}</span>
            <div class="flex gap-1 items-center">
              <span v-if="e.has_nav" class="text-[9px] text-cyan-500/80 border border-cyan-500/20 rounded px-1">NAV</span>
              <span class="text-[10px] px-1.5 py-0.5 rounded border border-slate-700 text-slate-500">{{ e.status }}</span>
              <button v-if="e.has_nav" @click.stop.prevent="toggleCompare(e)" :title="compareSel.includes(e.experiment_id) ? '取消对比' : '加入对比'"
                class="text-[13px] leading-none px-1 rounded border"
                :class="compareSel.includes(e.experiment_id) ? 'border-cyan-500/50 text-cyan-300 bg-cyan-500/10' : 'border-slate-700 text-slate-600 hover:text-cyan-300'">
                {{ compareSel.includes(e.experiment_id) ? '◉' : '○' }}</button>
            </div>
          </div>
          <div class="text-[11px] text-slate-500 mb-1 truncate">{{ e.description || '—' }}</div>
          <div class="flex items-center gap-2.5 text-[11px] mono">
            <span class="text-slate-500">S <b class="text-slate-200">{{ e.metrics.sharpe_ratio ?? '—' }}</b></span>
            <span class="text-slate-500">IC <b class="text-slate-200">{{ e.metrics.ic_mean ?? '—' }}</b></span>
            <span class="text-slate-500">超额 <b class="text-emerald-400">{{ e.metrics.excess_return_pct != null ? e.metrics.excess_return_pct.toFixed(1) + '%' : '—' }}</b></span>
            <span class="text-slate-500">DD <b class="text-red-400">{{ e.metrics.max_drawdown_pct != null ? '-' + e.metrics.max_drawdown_pct.toFixed(1) + '%' : '—' }}</b></span>
          </div>
        </div>
      </div>
    </div>

    <!-- 右: 详情 -->
    <div class="lg:col-span-3">
      <!-- 对比卡: 勾选 2+ 显示 -->
      <div v-if="compareSel.length >= 2" class="card p-4 mb-4">
        <div class="flex items-center justify-between mb-1">
          <div class="card-title">实验对比 (归一化到 100, 起点相等)</div>
          <button @click="clearCompare" class="text-[11px] px-2 py-0.5 rounded border border-slate-700 text-slate-500 hover:text-red-300">✕ 清空对比</button>
        </div>
        <div class="text-[11px] text-slate-500 mb-2 mono flex gap-3 flex-wrap">
          <span v-for="id in compareSel" :key="id" :class="compareNavs[id] ? 'text-cyan-300' : 'text-slate-600'">
            {{ shortName(id) }}{{ compareNavs[id] ? '' : ' (无NAV)' }}</span>
        </div>
        <div id="compare-chart" class="h-56"></div>
      </div>

      <div v-if="loading" class="card p-6 text-center text-slate-500 text-[13px]">加载中…</div>
      <template v-else-if="detail">
        <div class="card p-5 mb-4">
          <div class="card-title mb-1">{{ selected?.experiment_id }}</div>
          <div class="text-[12px] text-slate-400">{{ detail.config?.description || '—' }}</div>
          <div class="flex flex-wrap gap-x-5 gap-y-1 mt-2 text-[11px] text-slate-500">
            <span>策略 <b class="mono text-slate-300">{{ detail.config?.strategy_name || '—' }}</b></span>
            <span>数据集 <b class="mono text-slate-300">{{ detail.lineage?.dataset || detail.config?.dataset_version || '—' }}</b></span>
            <span>算法 <b class="mono text-slate-300">{{ detail.lineage?.model_algo || '—' }}</b></span>
            <span>完成 <b class="mono text-slate-300">{{ fmtTime(detail.completed_at) }}</b></span>
            <span>特征 <b class="text-slate-300">{{ (detail.config?.features || []).join(', ') }}</b></span>
          </div>
        </div>

        <!-- 指标卡 -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          <div class="card p-3">
            <div class="card-title mb-1">Sharpe</div>
            <div class="text-xl font-semibold mono" :class="detail.metrics.sharpe_ratio >= 1 ? 'text-emerald-400' : 'text-slate-200'">{{ detail.metrics.sharpe_ratio ?? '—' }}</div>
          </div>
          <div class="card p-3">
            <div class="card-title mb-1">IC (mean / t)</div>
            <div class="text-xl font-semibold mono text-slate-100">{{ detail.metrics.ic_mean ?? '—' }}</div>
            <div class="text-[10px] text-slate-500 mono">t={{ detail.metrics.ic_t_stat ?? '—' }} IR={{ detail.metrics.ic_ir ?? '—' }}</div>
          </div>
          <div class="card p-3">
            <div class="card-title mb-1">年化收益</div>
            <div class="text-xl font-semibold mono text-red-400">{{ detail.metrics.annual_return_pct != null ? detail.metrics.annual_return_pct.toFixed(1) + '%' : '—' }}</div>
            <div class="text-[10px] text-slate-500">总收益 {{ detail.metrics.total_return_pct != null ? detail.metrics.total_return_pct.toFixed(1) + '%' : '—' }}</div>
          </div>
          <div class="card p-3">
            <div class="card-title mb-1">最大回撤</div>
            <div class="text-xl font-semibold mono text-emerald-400">-{{ detail.metrics.max_drawdown_pct != null ? detail.metrics.max_drawdown_pct.toFixed(1) + '%' : '—' }}</div>
            <div class="text-[10px] text-slate-500">超额 {{ fmtPct(detail.metrics.excess_return_pct ?? null) }}</div>
          </div>
        </div>

        <!-- 净值曲线 -->
        <div class="card p-4 mb-4">
          <div class="flex justify-between items-center mb-1">
            <div class="card-title">净值曲线 (daily_nav.parquet)</div>
            <div v-if="trades" class="text-[10px] text-slate-500 mono">{{ trades.total_periods }} 个调仓期 · {{ trades.n_features }} 特征 · top{{ trades.top_n }} · 换手 {{ trades.total_buys }}买/{{ trades.total_sells }}卖</div>
          </div>
          <div v-if="nav" id="exp-nav-chart" class="h-56"></div>
          <div v-else class="text-[12px] text-slate-500 py-8 text-center">该实验无 daily_nav.parquet</div>
        </div>

        <!-- 调仓明细 -->
        <div v-if="trades?.rebalance_periods?.length" class="card p-4 mb-4">
          <div class="card-title mb-3">调仓明细 (trade_events.json 重建)</div>
          <div class="space-y-1.5 max-h-72 overflow-y-auto pr-1">
            <div v-for="p in trades.rebalance_periods" :key="p.date"
              class="border border-slate-800 rounded-lg">
              <div @click="expandPeriod = expandPeriod === p.date ? null : p.date"
                class="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-slate-800/40 text-[12px]">
                <span class="mono text-slate-200 w-20">{{ p.date }}</span>
                <span class="text-emerald-400">买 {{ p.n_buys }}</span>
                <span class="text-red-400">卖 {{ p.n_sells }}</span>
                <span class="text-slate-500">持有 {{ p.n_hold }}</span>
                <span class="ml-auto text-slate-600">{{ expandPeriod === p.date ? '▴' : '▾' }}</span>
              </div>
              <div v-if="expandPeriod === p.date" class="px-3 pb-2 flex gap-6 flex-wrap text-[11px]">
                <div>
                  <span class="text-emerald-500 block mb-1">买入:</span>
                  <span v-for="b in p.buys" :key="b.symbol" class="inline-block mr-2 mono text-slate-300">{{ b.symbol }} <span class="text-slate-600">¥{{ b.price }} #{{ b.rank }}</span></span>
                </div>
                <div>
                  <span class="text-red-500 block mb-1">卖出:</span>
                  <span v-for="s in p.sells" :key="s.symbol" class="inline-block mr-2 mono text-slate-300">{{ s.symbol }} <span class="text-slate-600">¥{{ s.price }}</span></span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 持仓时间线 -->
        <div v-if="trades?.timeline_symbols?.length" class="card p-4">
          <div class="card-title mb-2">持仓时间线 (近 {{ trades.timeline_dates.length }} 期 · top30 交易频率)</div>
          <div class="overflow-x-auto">
            <table class="border-collapse text-[9px]">
              <thead>
                <tr>
                  <th class="text-slate-600 pr-2 text-left">sym</th>
                  <th v-for="d in trades.timeline_dates" :key="d" class="text-slate-600 font-normal px-0.5">{{ d }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in trades.timeline_symbols" :key="row.symbol">
                  <td class="mono text-slate-400 pr-2 py-0.5">{{ row.symbol }} <span class="text-slate-600">×{{ row.count }}</span></td>
                  <td v-for="(c, i) in row.cells" :key="i" class="px-0.5 py-0.5">
                    <span class="inline-block w-3 h-3 rounded-sm" :class="cellColor[c] || 'bg-slate-800/40'" :title="c"></span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
      <div v-else class="card p-10 text-center text-slate-600 text-[13px]">← 点击左侧实验查看回测详情</div>
    </div>
  </div>
</template>
