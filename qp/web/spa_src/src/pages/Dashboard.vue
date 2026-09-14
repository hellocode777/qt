<script setup>
import { onMounted, ref, computed } from 'vue';
import * as echarts from 'echarts';
import { api, fmtMoney, fmtPct, pnlClass, fmtTime } from '../api';

const account = ref(null);   // account+index
const positions = ref([]);   // 全量（算活跃）
const papers = ref([]);
const portfolio = ref(null); // portfolio/nav_history.parquet 组合净值
const regime = ref(null);
const errs = ref([]);

const activePositions = computed(() => positions.value.filter(p => p.is_active));
// 活跃持仓按最新收盘标记；无行情时回落成本市值（后端 market_value_latest=None）
const mktValue = p => p.market_value_latest ?? p.market_value ?? 0;
// 账户估值统一来自 /api/v1/account 的 valuation（服务端单一实现，勿本地重算口径）
const valuation = computed(() => account.value?.valuation ?? null);
const totalValue = computed(() => {
  const v = valuation.value;
  if (v?.mark?.total_equity != null) return v.mark.total_equity;
  if (!account.value) return null;
  const mv = activePositions.value.reduce((s, p) => s + mktValue(p), 0);
  return account.value.account.cash + mv;
});
const activeMktValue = computed(() => {
  const v = valuation.value;
  if (v?.mark?.positions_value != null) return v.mark.positions_value;
  return activePositions.value.reduce((s, p) => s + mktValue(p), 0);
});

async function load() {
  const tasks = [
    api.account().then(d => (account.value = d)).catch(e => errs.value.push('account: ' + e.message)),
    api.positions().then(d => (positions.value = d.positions)).catch(e => errs.value.push('positions: ' + e.message)),
    api.paper().then(d => (papers.value = d.papers)).catch(e => errs.value.push('paper: ' + e.message)),
    api.portfolio().then(d => (portfolio.value = d)).catch(e => errs.value.push('portfolio: ' + e.message)),
    api.regime().then(d => (regime.value = d)).catch(e => errs.value.push('regime: ' + e.message)),
  ];
  await Promise.all(tasks);
  drawEquity();
}

// 组合净值优先 (portfolio/nav_history.parquet); 无则回退模拟盘第一条曲线
function drawEquity() {
  const el = document.getElementById('equity-chart');
  if (!el) return;
  const inst = echarts.getInstanceByDom(el);
  if (inst) inst.dispose();
  const chart = echarts.init(el);
  const pf = portfolio.value;
  let dates = [];
  let series = [];
  let sourceNote = '';
  if (pf && pf.records && pf.records.length) {
    const rows = pf.records;
    dates = rows.map(r => r.date);
    const seriesList = [{
      name: '组合净值', type: 'line', smooth: true, showSymbol: false,
      data: rows.map(r => r.total_nav),
      lineStyle: { color: '#38bdf8', width: 2 },
      areaStyle: { color: 'rgba(56,189,248,.08)' },
    }];
    if (rows.some(r => r.benchmark_value != null)) {
      seriesList.push({
        name: '基准', type: 'line', smooth: true, showSymbol: false,
        data: rows.map(r => r.benchmark_value),
        lineStyle: { color: '#64748b', width: 1.2, type: 'dashed' },
      });
    }
    series = seriesList;
    sourceNote = 'portfolio/nav_history.parquet · 现金+持仓';
  } else if (papers.value.length) {
    dates = papers.value[0].records.map(r => r.date);
    series = papers.value.map(p => ({
      name: p.strategy_id,
      type: 'line',
      smooth: true,
      showSymbol: false,
      data: p.records.map(r => +r.equity.toFixed(2)),
    }));
    sourceNote = 'fallback: paper_trading 模拟盘 (无组合净值记录)';
  } else {
    chart.dispose();
    return;
  }
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { textStyle: { color: '#94a3b8' }, top: 0 },
    grid: { left: 60, right: 20, top: 32, bottom: 24 },
    xAxis: { type: 'category', data: dates, axisLine: { lineStyle: { color: '#334155' } }, axisLabel: { color: '#64748b' } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: '#1e293b' } } },
    series,
  });
  el.__sourceNote = sourceNote;
  const noteEl = document.getElementById('equity-note');
  if (noteEl) noteEl.textContent = sourceNote;
}

onMounted(load);
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-5">
      <h1 class="text-xl font-semibold text-slate-100">总览 Dashboard</h1>
      <div v-if="regime" class="flex items-center gap-2">
        <span class="text-[11px] px-2 py-1 rounded-md border"
          :class="regime.regime.regime === 'bear' ? 'border-red-500/30 bg-red-500/10 text-red-400' : 'border-amber-500/30 bg-amber-500/10 text-amber-300'">
          最新决策 {{ regime.date }} · 状态 {{ regime.regime.regime }}
        </span>
      </div>
    </div>

    <!-- KPI 卡 -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
      <div class="card p-4">
        <div class="card-title mb-2">账户总资产 (现金+持仓市值)</div>
        <div class="text-2xl font-semibold mono">{{ totalValue !== null ? fmtMoney(totalValue) : '—' }}</div>
        <div class="text-[11px] text-slate-500 mt-1">初始 100,000 · 现金 {{ account ? fmtMoney(account.account.cash) : '—' }}</div>
        <div class="text-[11px] text-slate-500 mt-0.5" v-if="valuation?.mark">
          持仓按 {{ valuation.quote_date || '—' }} 收盘 · 成本口径 {{ fmtMoney(valuation.cost.positions_value) }}
          <span v-if="valuation.mark.n_fallback_cost"> · {{ valuation.mark.n_fallback_cost }} 只无行情按成本计</span>
        </div>
        <div class="text-[11px] mt-0.5" v-if="valuation?.mark">
          浮动盈亏
          <span :class="pnlClass(valuation.mark.unrealized_pnl)">{{ fmtMoney(valuation.mark.unrealized_pnl) }}</span>
          <span class="text-slate-500">（费后 {{ fmtMoney(valuation.mark.unrealized_pnl_net) }}，估费 {{ fmtMoney(valuation.mark.est_round_trip_fee) }}）</span>
        </div>
      </div>
      <div class="card p-4">
        <div class="card-title mb-2">活跃持仓</div>
        <div class="text-2xl font-semibold mono">{{ activePositions.length }} <span class="text-sm text-slate-500">/ {{ positions.length }} 总</span></div>
        <div class="text-[11px] text-slate-500 mt-1">市值(最新收盘) {{ fmtMoney(activeMktValue) }}</div>
      </div>
      <div class="card p-4">
        <div class="card-title mb-2">已实现盈亏 (累计 · 毛/费后)</div>
        <div class="text-2xl font-semibold mono" :class="pnlClass(account ? account.index.total_realized_pnl : null)">
          {{ account ? fmtMoney(account.index.total_realized_pnl) : '—' }}
        </div>
        <div class="text-[11px] mt-1" v-if="valuation?.realized">
          费后
          <span :class="pnlClass(valuation.realized.net)" title="费用按每行都真实成交估算；记账回滚行（entry=exit、pnl=0）实际未成交，会高估费用">{{ fmtMoney(valuation.realized.net) }}</span>
          <span class="text-slate-500"> · {{ valuation.realized.n_closed }} 笔平仓</span>
        </div>
        <div class="text-[11px] text-slate-500 mt-0.5">positions/index.json · 费率见持仓页脚注</div>
      </div>
      <div class="card p-4">
        <div class="card-title mb-2">建议敞口 (最新 regime)</div>
        <div class="text-2xl font-semibold mono" v-if="regime">
          {{ (regime.regime.suggested_exposure * 100).toFixed(0) }}%
          <span class="text-sm text-slate-500">/ 100%</span>
        </div>
        <div class="text-[11px] text-slate-500 mt-1" v-if="regime">
          confidence {{ (regime.regime.confidence * 100).toFixed(0) }}% · trend {{ regime.regime.trend_strength?.toFixed?.(2) ?? '—' }}
        </div>
      </div>
    </div>

    <!-- regime 详情 + 错误提示 -->
    <div v-if="errs.length" class="card p-3 mb-4 border-red-500/30">
      <div class="text-[12px] text-red-400">加载失败: {{ errs.join('; ') }}</div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-5">
      <!-- 组合净值 -->
      <div class="card p-4 lg:col-span-2">
        <div class="flex justify-between items-center mb-2">
          <div class="card-title">组合净值 + 基准</div>
          <div id="equity-note" class="text-[10px] text-slate-500">portfolio/nav_history.parquet</div>
        </div>
        <div id="equity-chart" class="h-56"></div>
        <div v-if="papers.length" class="flex gap-4 mt-2 text-[11px]">
          <span v-for="p in papers" :key="p.run_id" class="text-slate-400">
            {{ p.strategy_id }}: <b :class="pnlClass(p.total_return_pct)">{{ fmtPct(p.total_return_pct) }}</b>
            ({{ p.latest_equity.toLocaleString() }})</span>
        </div>
      </div>

      <!-- 最新 regime 摘要 -->
      <div class="card p-4">
        <div class="card-title mb-3">最新决策包 · 市场状态</div>
        <template v-if="regime">
          <div class="text-[12px] text-slate-400 leading-relaxed mb-3">{{ regime.regime.summary }}</div>
          <div class="space-y-2 text-[12px]">
            <div class="flex justify-between"><span class="text-slate-500">信号策略</span>
              <span class="mono">{{ Object.entries(regime.signals || {}).map(([k,v]) => `${k}: ${v}`).join(' · ') || '—' }}</span></div>
            <div class="flex justify-between"><span class="text-slate-500">风控审计</span>
              <span class="mono" :class="regime.risk_audit?.passed ? 'text-emerald-400' : 'text-red-400'">{{ regime.risk_audit?.passed ? 'passed' : 'failed' }}</span></div>
            <div class="flex justify-between"><span class="text-slate-500">人工复核</span>
              <span class="mono" :class="regime.human_review?.executed ? 'text-emerald-400' : 'text-amber-400'">{{ regime.human_review?.reviewed ? 'reviewed' : 'pending' }}</span></div>
            <div class="flex justify-between"><span class="text-slate-500">建议候选</span>
              <span class="mono">{{ Object.keys(regime.risk_audit?.candidate_weights || {}).join(', ') || '—' }}</span></div>
          </div>
          <div class="text-[10px] text-slate-600 mt-3">package: {{ regime.package_id }}<br />generated: {{ fmtTime(regime.human_review?.execution_time) }}</div>
        </template>
        <div v-else class="text-slate-500 text-[12px]">无决策包</div>
      </div>
    </div>

    <!-- 活跃持仓 -->
    <div class="card overflow-hidden">
      <div class="flex justify-between items-center px-4 pt-3.5 pb-2">
        <div class="card-title">活跃持仓 ({{ activePositions.length }})</div>
        <div class="text-[10px] text-slate-500">来源 positions.parquet · 市值/浮动盈亏按最新收盘标记（未计费用）</div>
      </div>
      <table class="w-full text-[13px]">
        <thead>
          <tr class="text-left text-slate-500 text-[11px] border-b border-slate-800">
            <th class="px-4 py-2">代码</th><th class="px-4 py-2">策略</th><th class="px-4 py-2 text-right">建仓日</th>
            <th class="px-4 py-2 text-right">成本价</th><th class="px-4 py-2 text-right">最新价</th><th class="px-4 py-2 text-right">股数</th>
            <th class="px-4 py-2 text-right">市值</th><th class="px-4 py-2 text-right">浮动盈亏</th><th class="px-4 py-2">备注</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in activePositions" :key="p.position_id" class="border-b border-slate-800/60 hover:bg-slate-800/30">
            <td class="px-4 py-2.5 mono text-slate-100">{{ p.symbol }}</td>
            <td class="px-4 py-2 text-slate-400">{{ p.strategy_id }}</td>
            <td class="px-4 py-2 mono text-slate-400 text-right">{{ p.entry_date }}</td>
            <td class="px-4 py-2 mono text-right">{{ p.entry_price }}</td>
            <td class="px-4 py-2 mono text-right text-slate-400"
              :title="`收盘 ${p.quote_date || '—'}${p.latest_suspended ? ' (停牌)' : ''}`">{{ fmtMoney(p.latest_price) }}</td>
            <td class="px-4 py-2 mono text-right">{{ p.shares }}</td>
            <td class="px-4 py-2 mono text-right">{{ fmtMoney(mktValue(p)) }}</td>
            <td class="px-4 py-2 mono text-right" :class="pnlClass(p.unrealized_pnl)">
              {{ fmtMoney(p.unrealized_pnl) }}
              <span class="text-[11px] text-slate-500">{{ p.unrealized_pnl_pct != null ? fmtPct(p.unrealized_pnl_pct * 100) : '' }}</span>
              <div class="text-[10px] text-slate-600" v-if="p.unrealized_pnl_net != null">
                费后 {{ fmtMoney(p.unrealized_pnl_net) }} {{ fmtPct(p.unrealized_pnl_net_pct * 100) }}
              </div>
            </td>
            <td class="px-4 py-2 text-slate-500 max-w-52 truncate">{{ p.notes || '—' }}</td>
          </tr>
          <tr v-if="!activePositions.length"><td colspan="9" class="px-4 py-6 text-center text-slate-500">无活跃持仓</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
