<script setup>
import { onMounted, ref } from 'vue';
import * as echarts from 'echarts';
import { api, fmtPct, pnlClass } from '../api';

const papers = ref([]);
const err = ref('');

// 由逐日 positions 快照差分推导当日净买卖 (数据源无逐笔成交清单)
// 首日: 从空仓起建仓, 持仓即买入; 之后: 与上一交易日持仓对比
function deriveDayTrades(records) {
  const out = [];
  let prevPos = {};
  for (let i = 0; i < records.length; i++) {
    const pos = records[i].positions || {};
    const trades = [];
    if (i === 0) {
      for (const [sym, qty] of Object.entries(pos)) {
        if (qty > 0) trades.push({ sym, side: 'BUY', qty });
      }
    } else {
      const syms = new Set([...Object.keys(prevPos), ...Object.keys(pos)]);
      for (const sym of syms) {
        const delta = (pos[sym] || 0) - (prevPos[sym] || 0);
        if (delta > 0) trades.push({ sym, side: 'BUY', qty: delta });
        else if (delta < 0) trades.push({ sym, side: 'SELL', qty: -delta });
      }
    }
    trades.sort((a, b) => a.sym.localeCompare(b.sym));
    out.push(trades);
    prevPos = pos;
  }
  return out;
}

function renderCards() {
  document.querySelectorAll('[data-paper-chart]').forEach(el => {
    const idx = +el.dataset.paperChart;
    const p = papers.value[idx];
    if (!p || !p.records?.length) return;
    const chart = echarts.init(el);
    chart.setOption({
      backgroundColor: 'transparent',
      grid: { left: 4, right: 4, top: 8, bottom: 4 },
      xAxis: { type: 'category', data: p.records.map(r => r.date), show: false },
      yAxis: { type: 'value', show: false },
      tooltip: { trigger: 'axis' },
      series: [{
        type: 'line', smooth: true, showSymbol: false, data: p.records.map(r => +r.equity.toFixed(2)),
        lineStyle: { width: 2, color: p.total_return_pct >= 0 ? '#f87171' : '#34d399' },
        areaStyle: { color: p.total_return_pct >= 0 ? 'rgba(248,113,113,.12)' : 'rgba(52,211,153,.12)' },
      }],
    });
  });
}

async function load() {
  try {
    const d = await api.paper();
    papers.value = (d.papers || []).map(p => ({
      ...p,
      tradesByDay: deriveDayTrades(p.records || []),
    }));
    setTimeout(renderCards, 50);
  } catch (e) { err.value = e.message; }
}

onMounted(load);
</script>

<template>
  <div>
    <h1 class="text-xl font-semibold text-slate-100 mb-5">模拟盘对比 <span class="text-[11px] font-normal text-slate-500 ml-2">qp/data/paper_trading · {{ papers[0]?.n_records ?? '—' }} 交易日</span></h1>

    <div v-if="err" class="card p-3 mb-4 text-red-400 text-[13px]">{{ err }}</div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
      <div v-for="(p, i) in papers" :key="p.run_id" class="card p-4">
        <div class="flex items-start justify-between mb-3">
          <div>
            <div class="font-medium text-slate-100 mono">{{ p.strategy_id }}</div>
            <div class="text-[11px] text-slate-500 mt-1">{{ p.run_id }} · start {{ p.start_date }} · capital {{ p.capital?.toLocaleString() }}</div>
          </div>
          <div class="text-right">
            <div class="text-xl font-semibold mono" :class="pnlClass(p.total_return_pct)">{{ fmtPct(p.total_return_pct) }}</div>
            <div class="text-[11px] text-slate-500">{{ p.latest_equity?.toLocaleString() }}</div>
          </div>
        </div>
        <div :data-paper-chart="i" class="h-36"></div>
        <div class="text-[11px] text-slate-500 mt-2 flex justify-between">
          <span>最后交易日: {{ p.records?.[p.records.length - 1]?.date || '—' }}</span>
          <span>{{ p.n_records }} 条记录</span>
        </div>
      </div>
    </div>

    <!-- 明细表 -->
    <div class="card overflow-hidden">
      <div class="px-4 pt-3.5 pb-2 card-title">日度明细（equity / 持仓 / 当日买卖）</div>
      <div class="overflow-x-auto">
        <table class="w-full text-[12px]">
          <thead>
            <tr class="text-left text-slate-500 border-b border-slate-800">
              <th class="px-4 py-2">date</th>
              <th v-for="p in papers" :key="'h' + p.run_id" class="px-4 py-2 text-right mono">{{ p.strategy_id }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(_, di) in (papers[0]?.records || [])" :key="di" class="border-b border-slate-800/40 hover:bg-slate-800/20 align-top">
              <td class="px-4 py-1.5 mono text-slate-400 whitespace-nowrap">{{ papers[0].records[di].date }}</td>
              <td v-for="p in papers" :key="p.run_id + di" class="px-4 py-1.5 text-right">
                <div class="mono text-slate-300 whitespace-nowrap">
                  {{ p.records[di] ? (+p.records[di].equity).toFixed(0) : '—' }}
                  <span class="text-[10px] text-slate-600"> ({{ p.records[di]?.n_positions ?? '—' }})</span>
                </div>
                <div v-if="p.records[di] && p.tradesByDay?.[di]?.length" class="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 justify-end"
                  :title="p.tradesByDay[di].map(t => (t.side === 'BUY' ? '买 ' : '卖 ') + t.sym + ' ×' + t.qty.toLocaleString()).join('\n')">
                  <span v-for="t in p.tradesByDay[di].slice(0, 6)" :key="t.sym + t.side" class="text-[10px] mono leading-tight"
                    :class="t.side === 'BUY' ? 'text-red-400' : 'text-emerald-400'">
                    {{ t.side === 'BUY' ? 'B' : 'S' }}{{ t.sym }}×{{ t.qty.toLocaleString() }}
                  </span>
                  <span v-if="p.tradesByDay[di].length > 6" class="text-[10px] mono text-slate-500 leading-tight">+{{ p.tradesByDay[di].length - 6 }}</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
